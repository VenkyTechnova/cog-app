"""AI layer: resume parsing, draft generation, reply classification, call-note summaries.

Two providers:
* `template` (default) — deterministic, rule-based. No external calls; fully testable.
* `anthropic` — uses Claude for richer drafts / parsing. Output is always passed through
  the compliance scanner and is never sent without human approval.
"""
from __future__ import annotations

import json
import logging
import re

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import COMPANY_PROCESS_ITEMS
from ..models import Candidate, EmailTemplate, Requirement, User
from ..util import first_name
from .matching import norm_skill
from .templates_default import TEMPLATES

log = logging.getLogger(__name__)

SKILL_VOCAB = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Angular", "Vue", "Node.js", "Go", "Rust", "C#", ".NET",
    "C++", "Kotlin", "Swift", "Scala", "Ruby", "PHP", "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka",
    "Spark", "Hadoop", "Airflow", "Snowflake", "Databricks", "dbt", "AWS", "Azure", "Google Cloud", "Kubernetes",
    "Docker", "Terraform", "Ansible", "Jenkins", "GitHub Actions", "Linux", "Spring Boot", "Django", "FastAPI",
    "Flask", "GraphQL", "REST", "Microservices", "Machine Learning", "PyTorch", "TensorFlow", "NLP", "LLM",
    "Tableau", "Power BI", "Salesforce", "ServiceNow", "SAP", "Selenium", "Cypress", "Playwright", "iOS", "Android",
    "Data Engineering", "DevOps", "SRE", "Cybersecurity", "Splunk", "Informatica", "ETL", "Pandas",
]


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
def render(text: str, ctx: dict) -> str:
    def rep(m):
        return str(ctx.get(m.group(1).strip(), ""))

    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", rep, text)


def get_template(db: Session | None, key: str) -> dict:
    if db is not None:
        row = db.get(EmailTemplate, key)
        if row is not None:
            return {"subject": row.subject, "body": row.body, "channel": row.channel, "auto_send_allowed": row.auto_send_allowed}
    return TEMPLATES[key]


def _specific_detail(c: Candidate, req: Requirement | None) -> str:
    matched = []
    if req:
        rs = {norm_skill(s) for s in req.skills or []}
        matched = [s for s in c.skills or [] if norm_skill(s) in rs]
    if c.headline and matched:
        role = c.headline.split("·")[0].strip()
        return f"your work as a {role} — especially the {matched[0]} side"
    if c.university and c.grad_year:
        return f"you studied {c.degree or 'at'} {'at ' if c.degree else ''}{c.university} ({c.grad_year}) and have been working with {', '.join((c.skills or [])[:2])}"
    if c.past_projects:
        proj = c.past_projects.split(".")[0][:90]
        return f"your project experience ({proj.strip()})"
    if matched:
        return f"your {matched[0]} experience"
    if c.skills:
        return f"your background in {', '.join(c.skills[:2])}"
    return "your engineering background"


def build_context(c: Candidate | None, req: Requirement | None, recruiter: User | None, extra: dict | None = None) -> dict:
    ctx: dict = {
        "recruiter_name": recruiter.name if recruiter else "Cognitech Talent Acquisition",
        "recruiter_first": first_name(recruiter.name) if recruiter else "our team",
        "recruiter_email": recruiter.email if recruiter else "talent@cognitech.example",
        "process_items": "\n".join(f"{i + 1}. {item}" for i, item in enumerate(COMPANY_PROCESS_ITEMS)),
    }
    if c is not None:
        skills = c.skills or []
        ctx.update(
            first_name=first_name(c.full_name),
            full_name=c.full_name,
            skill_area=(skills[0] if skills else "software"),
            specific_detail=_specific_detail(c, req),
            project_clause=(f" with {c.current_project_status.lower()}" if c.current_project_status else ""),
        )
    if req is not None:
        rs = {norm_skill(s) for s in req.skills or []}
        matched = [s for s in (c.skills if c else []) or [] if norm_skill(s) in rs]
        ctx.update(
            req_title=req.title,
            req_skills=", ".join(req.skills[:4]) if req.skills else "modern engineering",
            req_arrangement=req.work_arrangement.lower(),
            req_location_clause=(f", {req.location}" if req.location and req.work_arrangement != "Remote" else ""),
            req_clause=f", including a {req.title} role",
            matched_skills=", ".join(matched[:3]) or ctx.get("skill_area", "your stack"),
            skill_area=(matched[0] if matched else ctx.get("skill_area") or (req.skills[0] if req.skills else "software")),
            relevance=(
                f"your hands-on experience with {', '.join(matched[:3])} is exactly what this team needs"
                if matched
                else f"your background in {ctx.get('skill_area', 'software')} looks like a strong fit"
            ),
            question=f"Are you open to hearing about {matched[0] if matched else (req.skills[0] if req.skills else 'new')} projects right now?",
        )
    else:
        ctx.setdefault("req_title", "open")
        ctx.setdefault("req_clause", "")
        ctx.setdefault("matched_skills", ctx.get("skill_area", ""))
        ctx.setdefault("question", "Are you open to new projects at the moment?")
    ctx.update(extra or {})
    return ctx


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------
LLM_SYSTEM = (
    "You write recruiter messages for Cognitech Technologies. Tone: warm, specific, brief, respectful, never pushy. "
    "Hard rules: never mention pay dates, pay amounts, rates, tax outcomes, visas, immigration or legal status; "
    "never promise anything; no urgency language; one specific detail about the candidate; end with one simple question. "
    "Return JSON: {\"subject\": str, \"body\": str}."
)


def generate_draft(db: Session | None, kind: str, c: Candidate | None, req: Requirement | None, recruiter: User | None, extra: dict | None = None) -> tuple[str, str, str]:
    tpl = get_template(db, kind)
    ctx = build_context(c, req, recruiter, extra)
    subject, body = render(tpl.get("subject", ""), ctx), render(tpl["body"], ctx)
    settings = get_settings()
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key and kind in ("linkedin_note", "cold_email", "intro_message", "follow_up", "reengagement", "check_in", "dm"):
        try:
            prompt = (
                f"Message type: {kind}. Template (keep the structure):\n{tpl['body']}\n\n"
                f"Rendered baseline:\n{body}\n\nCandidate: {json.dumps(_cand_brief(c))}\n"
                f"Requirement: {json.dumps(_req_brief(req))}\nImprove the personalization. "
                + ("Keep it to 5 lines or fewer." if kind == "linkedin_note" else "")
            )
            out = _call_llm(prompt, LLM_SYSTEM)
            data = json.loads(out[out.find("{"): out.rfind("}") + 1])
            return data.get("subject", subject) or subject, data["body"], "llm"
        except Exception as exc:  # fall back to the deterministic template
            log.warning("LLM draft failed, using template: %s", exc)
    return subject, body, "template"


def _cand_brief(c: Candidate | None) -> dict:
    if not c:
        return {}
    return {"first_name": first_name(c.full_name), "headline": c.headline, "skills": c.skills, "years": c.years_experience, "university": c.university, "past_projects": c.past_projects[:300]}


def _req_brief(r: Requirement | None) -> dict:
    if not r:
        return {}
    return {"title": r.title, "skills": r.skills, "arrangement": r.work_arrangement, "location": r.location}


def _call_llm(prompt: str, system: str, max_tokens: int = 800) -> str:
    s = get_settings()
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": s.llm_model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    resp.raise_for_status()
    return "".join(b.get("text", "") for b in resp.json().get("content", []))


# ---------------------------------------------------------------------------
# LinkedIn search strings
# ---------------------------------------------------------------------------
def boolean_queries(req: Requirement) -> list[dict]:
    skills = req.skills or []
    core = skills[:3]
    q_core = " AND ".join(f'"{s}"' for s in core) if core else '"software engineer"'
    title_terms = re.sub(r"\b(sr\.?|senior|jr\.?|junior|lead|principal|ii|iii)\b", "", req.title, flags=re.I).strip()
    alt = " OR ".join(f'"{s}"' for s in skills[3:6])
    loc = req.location if req.work_arrangement != "Remote" else "United States"
    out = [
        {"label": "Title + core stack", "query": f'("{title_terms}") AND {q_core}', "filters": {"location": loc}},
        {"label": "Core stack + adjacent skills", "query": f"{q_core}" + (f" AND ({alt})" if alt else ""), "filters": {"location": loc}},
        {
            "label": "Recent graduates (university / degree / grad year)",
            "query": f'{q_core} AND ("Computer Science" OR "Information Technology" OR "Computer Engineering")',
            "filters": {"location": loc, "graduation_year": "last 3 years", "degree": "Master's or Bachelor's"},
        },
        {"label": "Exclude non-fits", "query": f"{q_core} NOT (recruiter OR \"talent acquisition\" OR sales)", "filters": {"location": loc}},
    ]
    return out


# ---------------------------------------------------------------------------
# Reply classification
# ---------------------------------------------------------------------------
REPLY_RULES = [
    ("unsubscribe", r"\b(unsubscribe|remove me|stop (emailing|contacting)|do not contact|opt me out)\b"),
    ("not_interested", r"\b(not interested|no thanks|no thank you|please don'?t|not looking|i'?m (happy|settled) where|pass on this)\b"),
    ("not_now", r"\b(not (right )?now|maybe later|in a few (weeks|months)|reach out (again )?(later|in)|currently (on|in) a project|circle back|busy right now|next (month|quarter))\b"),
    ("interested", r"\b(interested|sounds (good|great)|let'?s (talk|connect|chat)|happy to (talk|chat)|call me|available (to|for) (a )?(call|chat)|tell me more|open to|yes\b|share (the )?(details|jd))\b"),
    ("question", r"\?"),
]


def classify_reply(text: str) -> tuple[str, float]:
    t = (text or "").lower()
    # Only look at the new part of the reply (drop quoted history).
    t = re.split(r"\n\s*(on .+ wrote:|>)", t)[0]
    for cls, pat in REPLY_RULES:
        if re.search(pat, t):
            # "not interested" contains "interested": order of rules handles it.
            return cls, 0.85 if cls != "question" else 0.6
    return "question", 0.4


# ---------------------------------------------------------------------------
# Resume parsing
# ---------------------------------------------------------------------------
def parse_resume(text: str) -> dict:
    t = text or ""
    out: dict = {}
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t)
    if m:
        out["email"] = m.group(0).lower()
    m = re.search(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", t)
    if m:
        out["phone"] = m.group(0)
    m = re.search(r"(https?://)?(www\.)?linkedin\.com/in/[\w-]+/?", t, re.I)
    if m:
        out["linkedin_url"] = m.group(0)
    m = re.search(r"(\d{1,2})\+?\s*(years|yrs)", t, re.I)
    if m:
        out["years_experience"] = float(m.group(1))
    found = []
    low = t.lower()
    for s in SKILL_VOCAB:
        pat = r"(?<![\w.])" + re.escape(s.lower()) + r"(?![\w])"
        if re.search(pat, low):
            found.append(s)
    out["skills"] = found
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    if lines and len(lines[0].split()) <= 4 and "@" not in lines[0]:
        out["full_name"] = lines[0].title() if lines[0].isupper() else lines[0]
    m = re.search(r"(university|institute|college) of [A-Z][\w ]+|[A-Z][\w]+ (University|Institute of Technology)", t)
    if m:
        out["university"] = m.group(0).strip()
    m = re.search(r"\b(M\.?S\.?|B\.?S\.?|Master'?s|Bachelor'?s|B\.?Tech|M\.?Tech)\b[^\n,]{0,40}", t)
    if m:
        out["degree"] = m.group(0).strip()
    m = re.search(r"\b(20[0-3]\d)\b(?=[^\n]{0,20}(grad|expected|$))", t, re.I)
    if m:
        out["grad_year"] = int(m.group(1))
    return out


# ---------------------------------------------------------------------------
# Call-notes summary → pre-fill the 18 fields
# ---------------------------------------------------------------------------
def summarize_call(transcript: str) -> dict:
    """Extract structured fields from call notes or a speech-to-text transcript.

    Returns suggestions only; the recruiter reviews them in the call-outcome form.
    """
    t = transcript or ""
    low = t.lower()
    out: dict = {}
    parsed = parse_resume(t)
    for k in ("email", "phone", "years_experience", "skills"):
        if parsed.get(k):
            out[k] = parsed[k]
    if re.search(r"\b(w-?2)\b", low) and not re.search(r"\bc2c\b", low):
        out["preferred_type"] = "W-2"
    elif re.search(r"\bc2c\b", low) and not re.search(r"\bw-?2\b", low):
        out["preferred_type"] = "C2C"
    elif re.search(r"\bw-?2\b", low) and re.search(r"\bc2c\b", low):
        out["preferred_type"] = "Either"
    for arr in ("remote", "hybrid", "onsite"):
        if re.search(rf"\b{arr}\b", low):
            out["work_arrangement"] = arr.capitalize()
            break
    m = re.search(r"available (immediately|in \w+ weeks?|in \w+ months?|from [\w ]+)", low)
    if m:
        out["availability"] = m.group(0).replace("available ", "").capitalize()
    elif "immediately" in low:
        out["availability"] = "Immediate"
    m = re.search(r"(project (ends|ending|wraps up) [\w ]+|between projects|on the bench|currently employed at [\w ]+|currently (working|on a project) [\w ]+)", low)
    if m:
        out["current_project_status"] = m.group(0).strip().capitalize()
    m = re.search(r"(based in|lives in|located in) ([A-Z][\w ]+(, ?[A-Z]{2})?)", t)
    if m:
        out["location"] = m.group(2).strip()
    m = re.search(r"interview(ing|s)? (with|at) ([\w ,]+)", low)
    if m:
        out["interview_status"] = m.group(0).capitalize()
    m = re.search(r"(goal|looking to|wants to) ([^.]+)", low)
    if m:
        out["career_goals"] = m.group(0).capitalize()
    if re.search(r"\b(not interested|no longer looking)\b", low):
        out["outcome"] = "not_interested"
    elif re.search(r"\b(call back|busy|later)\b", low):
        out["outcome"] = "call_back"
    elif re.search(r"\b(interested|keen|excited)\b", low):
        out["outcome"] = "interested"
    return out


def profile_summary(c: Candidate, req: Requirement | None = None) -> dict:
    rs = {norm_skill(s) for s in (req.skills if req else []) or []}
    return {
        "headline": c.headline or (f"{c.years_experience:g}-year engineer" if c.years_experience else "Engineer"),
        "highlighted_skills": [{"skill": s, "match": norm_skill(s) in rs} for s in c.skills or []],
        "education": " · ".join(x for x in [c.degree, c.university, str(c.grad_year) if c.grad_year else ""] if x),
        "projects": [p.strip() for p in (c.past_projects or "").split(".") if p.strip()][:4],
        "talking_point": _specific_detail(c, req),
    }
