"""Intake: creating candidates (with dedupe), inbound applications, requirements, and inbound email."""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy.orm import Session

from ..audit import audit
from ..models import Application, Candidate, Interaction, Requirement, User
from ..settings_store import get_setting
from ..util import normalize_email, normalize_linkedin, normalize_phone, now
from . import ai
from .dedupe import find_duplicates, queue_pair
from .events import emit

CANDIDATE_FIELDS = {
    "full_name", "email", "phone", "linkedin_url", "location", "source", "skills", "years_experience",
    "current_project_status", "work_authorization", "availability", "preferred_type", "expected_compensation",
    "work_arrangement", "owner_id", "past_projects", "interview_status", "career_goals", "headline", "summary",
    "university", "degree", "grad_year", "resume_text",
}


def _clean(data: dict) -> dict:
    out = {k: v for k, v in data.items() if k in CANDIDATE_FIELDS and v not in (None, "")}
    if "email" in out:
        out["email"] = normalize_email(out["email"])
    if "phone" in out:
        out["phone"] = normalize_phone(out["phone"])
    if "linkedin_url" in out:
        out["linkedin_url"] = normalize_linkedin(out["linkedin_url"])
    if isinstance(out.get("skills"), str):
        out["skills"] = [s.strip() for s in out["skills"].split(",") if s.strip()]
    return out


def upsert_candidate(db: Session, data: dict, user_id: int | None = None, event: str = "candidate.created", merge_existing: bool = True) -> tuple[Candidate, bool]:
    """Create a candidate, or update the existing record if one matches on email / phone / LinkedIn.

    Returns (candidate, created). Deduplication happens here, on create, for every source.
    """
    clean = _clean(data)
    dups = find_duplicates(db, clean.get("email"), clean.get("phone"), clean.get("linkedin_url"))
    if dups and merge_existing:
        existing, on = dups[0]
        for k, v in clean.items():
            if k == "skills":
                existing.skills = sorted({*(existing.skills or []), *v}, key=str.lower)
            elif not getattr(existing, k):
                setattr(existing, k, v)
        if len(dups) > 1:
            for other, on2 in dups[1:]:
                queue_pair(db, existing.id, other.id, on2)
        audit(db, "candidate.deduplicated", "candidate", existing.id, user_id, {"matched_on": on, "source": clean.get("source")})
        db.flush()
        emit(db, "candidate.updated", candidate_id=existing.id, user_id=user_id, payload={"dedupe": True, "matched_on": on})
        return existing, False
    days = int(get_setting(db, "retention.days_inactive"))
    c = Candidate(**clean, retention_expires_at=now() + timedelta(days=days))
    if not c.full_name:
        c.full_name = "Unknown candidate"
    db.add(c)
    db.flush()
    for other, on in dups:  # only when merge_existing=False
        queue_pair(db, c.id, other.id, on)
        if user_id:
            from .habits import raise_habit

            raise_habit(db, "duplicate_record", user_id=user_id, candidate_id=c.id, detail=f"Duplicate of #{other.id} on {', '.join(on)}", key=f"dup:{c.id}:{other.id}")
    audit(db, "candidate.created", "candidate", c.id, user_id, {"source": c.source})
    db.add(Interaction(candidate_id=c.id, user_id=user_id, type="system", subject=f"Record created from {c.source}"))
    db.flush()
    emit(db, "candidate.created", candidate_id=c.id, user_id=user_id, payload={"source": c.source})
    if event != "candidate.created":
        emit(db, event, candidate_id=c.id, user_id=user_id, payload={"source": c.source})
    return c, True


def receive_application(db: Session, data: dict, requirement_id: int | None = None, source: str = "job_board") -> Application:
    """Parse the resume, create/dedupe the candidate and log the application."""
    resume = data.get("resume_text") or ""
    parsed = ai.parse_resume(resume) if resume else {}
    merged = {**parsed, **{k: v for k, v in data.items() if v}}
    merged["source"] = "Job Posting"
    if parsed.get("skills") and data.get("skills"):
        merged["skills"] = sorted({*parsed["skills"], *data["skills"]})
    c, _ = upsert_candidate(db, merged, event="candidate.created")
    app = Application(candidate_id=c.id, requirement_id=requirement_id, source=source, raw={k: v for k, v in data.items() if k != "resume_text"})
    db.add(app)
    db.flush()
    db.add(Interaction(candidate_id=c.id, type="system", subject=f"Applied via {source}", meta={"application_id": app.id, "requirement_id": requirement_id}))
    emit(db, "application.received", candidate_id=c.id, requirement_id=requirement_id, payload={"application_id": app.id})
    return app


def create_requirement(db: Session, data: dict, user_id: int | None = None) -> Requirement:
    fields = {"title", "client", "skills", "location", "work_arrangement", "employment_type", "rate", "min_years", "priority", "description", "accepted_work_auth", "source", "owner_id"}
    clean = {k: v for k, v in data.items() if k in fields and v is not None}
    if isinstance(clean.get("skills"), str):
        clean["skills"] = [s.strip() for s in clean["skills"].split(",") if s.strip()]
    r = Requirement(**clean)
    db.add(r)
    db.flush()
    audit(db, "requirement.created", "requirement", r.id, user_id, {"title": r.title})
    emit(db, "requirement.created", requirement_id=r.id, user_id=user_id, payload={"priority": r.priority})
    return r


REQ_LINE = {
    "title": r"(?:title|role|position)\s*[:\-]\s*(.+)",
    "client": r"(?:client|end client|company)\s*[:\-]\s*(.+)",
    "location": r"(?:location)\s*[:\-]\s*(.+)",
    "skills": r"(?:skills|must have|tech stack|required skills)\s*[:\-]\s*(.+)",
    "rate": r"(?:rate|pay rate|bill rate)\s*[:\-]\s*(.+)",
    "employment_type": r"(?:type|employment type|tax term)\s*[:\-]\s*(.+)",
    "min_years": r"(\d{1,2})\+?\s*(?:years|yrs)",
    "priority": r"(?:priority)\s*[:\-]\s*(high|medium|low)",
}


def parse_requirement_email(subject: str, body: str) -> dict:
    text = f"{subject}\n{body}"
    out: dict = {"source": "email_parser"}
    for k, pat in REQ_LINE.items():
        m = re.search(pat, text, re.I)
        if m:
            out[k] = m.group(1).strip()
    if "title" not in out:
        out["title"] = re.sub(r"^(fw|fwd|re|req|requirement)\s*[:\-]\s*", "", subject, flags=re.I).strip() or "Untitled requirement"
    out.setdefault("client", "Unknown client")
    if "min_years" in out:
        out["min_years"] = int(out["min_years"])
    et = (out.get("employment_type") or "").upper()
    out["employment_type"] = "W-2" if "W2" in et.replace("-", "") and "C2C" not in et else ("C2C" if "C2C" in et and "W2" not in et.replace("-", "") else "Either")
    loc = out.get("location", "")
    out["work_arrangement"] = "Remote" if "remote" in loc.lower() else ("Hybrid" if "hybrid" in text.lower() else "Onsite")
    if out.get("priority"):
        out["priority"] = out["priority"].capitalize()
    if "skills" not in out:
        out["skills"] = ai.parse_resume(body).get("skills", [])[:8]
    return out


def handle_inbound_email(db: Session, from_email: str, subject: str, body: str, to_email: str = "") -> dict:
    """Entry point for the inbox parser (Gmail / Microsoft 365 push, or SendGrid Inbound Parse)."""
    if to_email and to_email.lower().startswith("requirements@"):
        r = create_requirement(db, parse_requirement_email(subject, body))
        return {"type": "requirement", "requirement_id": r.id}
    email = normalize_email(from_email)
    c = db.query(Candidate).filter(Candidate.email == email, Candidate.merged_into_id.is_(None)).first()
    if c is None:
        return {"type": "unmatched"}
    cls, conf = ai.classify_reply(body)
    c.last_reply_class = cls
    c.last_reply_at = now()
    c.last_contact_at = now()
    db.add(Interaction(candidate_id=c.id, type="email_in", direction="in", subject=subject, body=body[:5000], outcome=cls, meaningful=True, meta={"confidence": conf}))
    db.flush()
    emit(db, "email.reply_received", candidate_id=c.id, payload={"reply_class": cls, "confidence": conf, "subject": subject})
    return {"type": "reply", "candidate_id": c.id, "reply_class": cls}


def owner_or_default(db: Session, c: Candidate) -> User | None:
    if c.owner_id:
        return db.get(User, c.owner_id)
    return db.query(User).filter(User.role == "recruiter").order_by(User.id).first()
