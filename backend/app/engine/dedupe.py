"""Duplicate detection (on create) and merging (weekly merge queue)."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import (
    Application,
    Candidate,
    DuplicatePair,
    FollowUp,
    Interaction,
    Match,
    Draft,
    OutboundEmail,
    Ticket,
    DocumentRequest,
    DocumentItem,
    ConsentRecord,
)
from ..util import normalize_email, normalize_linkedin, normalize_phone


def find_duplicates(db: Session, email=None, phone=None, linkedin_url=None, exclude_id: int | None = None) -> list[tuple[Candidate, list[str]]]:
    e, p, l = normalize_email(email), normalize_phone(phone), normalize_linkedin(linkedin_url)
    conds = []
    if e:
        conds.append(Candidate.email == e)
    if p:
        conds.append(Candidate.phone == p)
    if l:
        conds.append(Candidate.linkedin_url == l)
    if not conds:
        return []
    q = db.query(Candidate).filter(or_(*conds), Candidate.merged_into_id.is_(None), Candidate.purged.is_(False))
    if exclude_id:
        q = q.filter(Candidate.id != exclude_id)
    out = []
    for c in q.all():
        on = []
        if e and c.email == e:
            on.append("email")
        if p and c.phone == p:
            on.append("phone")
        if l and c.linkedin_url == l:
            on.append("linkedin_url")
        out.append((c, on))
    return out


def queue_pair(db: Session, a_id: int, b_id: int, matched_on: list[str]) -> DuplicatePair | None:
    a, b = sorted([a_id, b_id])
    existing = db.query(DuplicatePair).filter_by(candidate_a_id=a, candidate_b_id=b).one_or_none()
    if existing:
        return existing
    pair = DuplicatePair(candidate_a_id=a, candidate_b_id=b, matched_on=matched_on)
    db.add(pair)
    db.flush()
    return pair


def scan_all(db: Session) -> int:
    """Weekly sweep: queue every pair sharing an email, phone or LinkedIn URL."""
    created = 0
    for field in ("email", "phone", "linkedin_url"):
        col = getattr(Candidate, field)
        rows = (
            db.query(col, Candidate.id)
            .filter(col.isnot(None), col != "", Candidate.merged_into_id.is_(None), Candidate.purged.is_(False))
            .order_by(col, Candidate.id)
            .all()
        )
        groups: dict[str, list[int]] = {}
        for val, cid in rows:
            groups.setdefault(val, []).append(cid)
        for ids in groups.values():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    existed = db.query(DuplicatePair).filter_by(candidate_a_id=a, candidate_b_id=b).one_or_none()
                    if existed:
                        if field not in (existed.matched_on or []):
                            existed.matched_on = list(existed.matched_on or []) + [field]
                        continue
                    queue_pair(db, a, b, [field])
                    created += 1
    db.flush()
    return created


FILL_FIELDS = [
    "email", "phone", "linkedin_url", "location", "years_experience", "current_project_status", "work_authorization",
    "availability", "preferred_type", "expected_compensation", "work_arrangement", "past_projects", "interview_status",
    "career_goals", "headline", "summary", "university", "degree", "grad_year", "resume_text", "owner_id",
]


def merge(db: Session, keep: Candidate, drop: Candidate) -> Candidate:
    """Merge `drop` into `keep`: fill blank fields, union skills, move related records."""
    for f in FILL_FIELDS:
        if not getattr(keep, f) and getattr(drop, f):
            setattr(keep, f, getattr(drop, f))
    keep.skills = sorted({*(keep.skills or []), *(drop.skills or [])}, key=str.lower)
    for model in (Interaction, FollowUp, Draft, OutboundEmail, Ticket, DocumentRequest, DocumentItem, ConsentRecord, Application):
        db.query(model).filter(model.candidate_id == drop.id).update({model.candidate_id: keep.id}, synchronize_session=False)
    # Matches: keep the better one per requirement.
    for m in db.query(Match).filter(Match.candidate_id == drop.id).all():
        other = db.query(Match).filter_by(candidate_id=keep.id, requirement_id=m.requirement_id).one_or_none()
        if other:
            other.score = max(other.score, m.score)
            db.delete(m)
        else:
            m.candidate_id = keep.id
    drop.merged_into_id = keep.id
    db.query(DuplicatePair).filter(
        or_(DuplicatePair.candidate_a_id == drop.id, DuplicatePair.candidate_b_id == drop.id), DuplicatePair.status == "open"
    ).update({DuplicatePair.status: "merged"}, synchronize_session=False)
    db.flush()
    return keep
