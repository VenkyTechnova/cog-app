"""Explainable match scoring between a candidate and a requirement (0-100).

The score is deterministic and transparent (skills 50, experience 20, location 15,
work authorization 10, availability 5, minus an employment-type mismatch penalty) so a
recruiter can see *why* someone ranks where they do. When an LLM is configured, the AI
layer adds a short narrative on top, but never changes the number.
"""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy.orm import Session

from ..constants import OUTCOME_STAGES
from ..models import Candidate, Match, Requirement
from ..settings_store import get_setting
from ..util import aware, now

ALIASES = {
    "js": "javascript",
    "react.js": "react",
    "reactjs": "react",
    "node": "node.js",
    "nodejs": "node.js",
    "k8s": "kubernetes",
    "golang": "go",
    "postgres": "postgresql",
    "ts": "typescript",
    "aws cloud": "aws",
    "amazon web services": "aws",
    "gcp": "google cloud",
    "ml": "machine learning",
    "py": "python",
    "springboot": "spring boot",
    "c sharp": "c#",
    ".net core": ".net",
    "dotnet": ".net",
}

US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me",
    "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa",
    "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}


def norm_skill(s: str) -> str:
    s = s.strip().lower()
    return ALIASES.get(s, s)


def _loc_parts(loc: str) -> tuple[str, str]:
    parts = [p.strip().lower() for p in re.split(r",", loc or "") if p.strip()]
    city = parts[0] if parts else ""
    state = parts[1] if len(parts) > 1 else ""
    if state not in US_STATES and city in US_STATES:
        state, city = city, ""
    return city, state


def score(candidate: Candidate, req: Requirement) -> tuple[float, dict]:
    breakdown: dict = {}
    req_skills = {norm_skill(s) for s in (req.skills or [])}
    cand_skills = {norm_skill(s) for s in (candidate.skills or [])}
    label = {norm_skill(s): s for s in (req.skills or [])}
    matched = [label[k] for k in sorted(req_skills & cand_skills)]
    missing = [label[k] for k in sorted(req_skills - cand_skills)]
    skill_pts = 50.0 * (len(matched) / len(req_skills)) if req_skills else 25.0
    breakdown["skills"] = {"points": round(skill_pts, 1), "max": 50, "matched": matched, "missing": missing}

    yrs = candidate.years_experience or 0
    if req.min_years <= 0:
        exp_pts = 20.0
    else:
        exp_pts = 20.0 * min(yrs / req.min_years, 1.0)
    breakdown["experience"] = {"points": round(exp_pts, 1), "max": 20, "candidate_years": yrs, "required": req.min_years}

    if req.work_arrangement == "Remote":
        loc_pts, why = 15.0, "Remote role"
    else:
        c_city, c_state = _loc_parts(candidate.location)
        r_city, r_state = _loc_parts(req.location)
        if c_city and c_city == r_city:
            loc_pts, why = 15.0, "Same city"
        elif c_state and c_state == r_state:
            loc_pts, why = 10.0, "Same state"
        elif (candidate.work_arrangement or "").lower() in ("flexible", "onsite", "hybrid") and "reloc" in (candidate.career_goals or "").lower():
            loc_pts, why = 8.0, "Open to relocation"
        elif (candidate.work_arrangement or "") == "Remote":
            loc_pts, why = 2.0, "Candidate prefers remote; role is " + req.work_arrangement.lower()
        else:
            loc_pts, why = 4.0, "Different location"
    breakdown["location"] = {"points": loc_pts, "max": 15, "note": why}

    accepted = req.accepted_work_auth or []
    if not accepted or not candidate.work_authorization:
        wa_pts, why = (10.0 if not accepted else 5.0), ("Any authorization accepted" if not accepted else "Authorization unknown")
    elif candidate.work_authorization in accepted:
        wa_pts, why = 10.0, "Authorization accepted"
    else:
        wa_pts, why = 0.0, f"{candidate.work_authorization} not in accepted list"
    breakdown["work_authorization"] = {"points": wa_pts, "max": 10, "note": why}

    av = (candidate.availability or "").lower()
    if any(k in av for k in ("immediate", "now", "available")):
        av_pts = 5.0
    elif any(k in av for k in ("1 week", "2 week", "two week")):
        av_pts = 4.0
    elif "month" in av or "30" in av:
        av_pts = 2.5
    elif av:
        av_pts = 1.5
    else:
        av_pts = 2.0
    breakdown["availability"] = {"points": av_pts, "max": 5, "value": candidate.availability}

    penalty = 0.0
    pt = candidate.preferred_type
    if req.employment_type in ("W-2", "C2C") and pt in ("W-2", "C2C") and pt != req.employment_type:
        penalty = 10.0
    breakdown["employment_type_penalty"] = penalty

    total = max(0.0, min(100.0, skill_pts + exp_pts + loc_pts + wa_pts + av_pts - penalty))
    return round(total, 1), breakdown


def upsert_match(db: Session, candidate: Candidate, req: Requirement, reengagement: bool = False) -> Match:
    s, b = score(candidate, req)
    m = db.query(Match).filter_by(candidate_id=candidate.id, requirement_id=req.id).one_or_none()
    if m is None:
        m = Match(candidate_id=candidate.id, requirement_id=req.id, score=s, breakdown=b, is_reengagement=reengagement)
        db.add(m)
    else:
        m.score, m.breakdown = s, b
        m.is_reengagement = m.is_reengagement or reengagement
    return m


def score_candidate_against_open(db: Session, candidate: Candidate) -> list[Match]:
    reqs = db.query(Requirement).filter(Requirement.status == "open").all()
    out = [upsert_match(db, candidate, r) for r in reqs]
    candidate.fit_score = max((m.score for m in out), default=None)
    db.flush()
    return out


def eligible_pool(db: Session):
    return db.query(Candidate).filter(Candidate.merged_into_id.is_(None), Candidate.purged.is_(False))


def match_requirement(db: Session, req: Requirement, limit: int = 5) -> list[Match]:
    """Score every eligible candidate for a new requirement and return the top N.

    Past candidates in Hold / Not Interested / Closed whose last contact is older than
    `digest.reengagement_min_days` are included and flagged as re-engagement matches.
    Candidates who are Not Interested and contacted recently are excluded (respect their answer).
    """
    min_days = int(get_setting(db, "digest.reengagement_min_days"))
    cutoff = now() - timedelta(days=min_days)
    results: list[Match] = []
    for c in eligible_pool(db).all():
        if c.email_opt_out and not c.phone:
            continue
        reengage = False
        if c.stage in ("hold", "not_interested", "closed"):
            last = aware(c.last_contact_at) or aware(c.created_at)
            if last and last > cutoff:
                continue
            reengage = True
        elif c.stage in OUTCOME_STAGES:  # placed
            continue
        results.append(upsert_match(db, c, req, reengagement=reengage))
    db.flush()
    results.sort(key=lambda m: m.score, reverse=True)
    return results[:limit]
