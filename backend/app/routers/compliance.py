"""Compliance & Audit: consent log, flagged advice keywords, habit review queue, retention queue, audit/access log."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import HABITS
from ..db import get_db
from ..deps import current_user, require_roles
from ..models import (
    AuditLog,
    Candidate,
    ComplianceFlag,
    ConsentRecord,
    DocumentItem,
    HabitFlag,
    Interaction,
    User,
)
from ..serializers import row
from ..storage import get_storage
from ..util import now

router = APIRouter(prefix="/api/compliance", tags=["compliance"])
MANAGERS = ("ta_lead", "admin")


@router.get("/consent")
def consent_log(db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS, "recruiter"))):
    q = db.query(ConsentRecord)
    if u.role == "recruiter":
        q = q.join(Candidate, Candidate.id == ConsentRecord.candidate_id).filter(Candidate.owner_id == u.id)
    rows = q.order_by(ConsentRecord.requested_at.desc()).limit(500).all()
    return [{**row(r, exclude={"token", "consent_text"}), "candidate_name": r.candidate.full_name if r.candidate else None} for r in rows]


@router.get("/flags")
def flags(status: str = "open", db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS))):
    q = db.query(ComplianceFlag)
    if status != "all":
        q = q.filter(ComplianceFlag.status == status)
    users = {x.id: x.name for x in db.query(User).all()}
    cands = {c.id: c.full_name for c in db.query(Candidate.id, Candidate.full_name).all()}
    return [{**row(f), "user_name": users.get(f.user_id), "candidate_name": cands.get(f.candidate_id)} for f in q.order_by(ComplianceFlag.created_at.desc()).limit(500).all()]


class ReviewIn(BaseModel):
    status: str  # reviewed / dismissed / coached
    note: str = ""


@router.post("/flags/{fid}")
def review_flag(fid: int, body: ReviewIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS))):
    f = db.get(ComplianceFlag, fid)
    if f is None:
        raise HTTPException(404)
    f.status, f.reviewed_by = body.status, u.id
    audit(db, "compliance_flag.reviewed", "compliance_flag", fid, u.id, body.model_dump())
    db.commit()
    return row(f)


@router.get("/habits")
def habits(status: str = "open", user_id: int | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(HabitFlag)
    if u.role == "recruiter":
        q = q.filter(HabitFlag.user_id == u.id)  # recruiters see their own coaching items
    elif user_id:
        q = q.filter(HabitFlag.user_id == user_id)
    if status != "all":
        q = q.filter(HabitFlag.status == status)
    users = {x.id: x.name for x in db.query(User).all()}
    items = [{**row(h), "label": HABITS.get(h.habit, h.habit), "user_name": users.get(h.user_id), "candidate_name": h.candidate.full_name if h.candidate else None} for h in q.order_by(HabitFlag.created_at.desc()).limit(500).all()]
    summary: dict = {}
    sq = db.query(HabitFlag).filter(HabitFlag.status == "open")
    if u.role == "recruiter":
        sq = sq.filter(HabitFlag.user_id == u.id)
    for h in sq.all():
        s = summary.setdefault(users.get(h.user_id, "Unassigned"), {})
        s[h.habit] = s.get(h.habit, 0) + 1
    return {"items": items, "habits": HABITS, "by_recruiter": summary}


@router.post("/habits/{hid}")
def review_habit(hid: int, body: ReviewIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS))):
    h = db.get(HabitFlag, hid)
    if h is None:
        raise HTTPException(404)
    h.status, h.coaching_note, h.reviewed_by, h.reviewed_at = body.status, body.note, u.id, now()
    audit(db, "habit.reviewed", "habit_flag", hid, u.id, body.model_dump())
    db.commit()
    return row(h)


@router.get("/retention")
def retention_queue(db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS))):
    rows = db.query(Candidate).filter(Candidate.retention_expires_at <= now(), Candidate.purged.is_(False)).all()
    upcoming = db.query(Candidate).filter(Candidate.retention_expires_at > now(), Candidate.purged.is_(False)).order_by(Candidate.retention_expires_at).limit(20).all()
    ser = lambda c: {"id": c.id, "full_name": c.full_name, "stage": c.stage, "retention_expires_at": row(c)["retention_expires_at"], "last_contact_at": row(c)["last_contact_at"]}
    return {"due": [ser(c) for c in rows], "upcoming": [ser(c) for c in upcoming]}


class ExtendIn(BaseModel):
    days: int = 365
    reason: str


@router.post("/retention/{cid}/extend")
def extend(cid: int, body: ExtendIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS))):
    c = db.get(Candidate, cid)
    if c is None:
        raise HTTPException(404)
    from datetime import timedelta

    c.retention_expires_at = now() + timedelta(days=body.days)
    audit(db, "retention.extended", "candidate", cid, u.id, body.model_dump())
    db.commit()
    return {"ok": True}


@router.post("/retention/{cid}/purge")
def purge(cid: int, db: Session = Depends(get_db), u: User = Depends(require_roles("admin", "ta_lead"))):
    """Anonymise personal data and delete stored documents. Aggregate metrics are preserved."""
    c = db.get(Candidate, cid)
    if c is None:
        raise HTTPException(404)
    storage = get_storage()
    for item in db.query(DocumentItem).filter_by(candidate_id=cid).all():
        if item.storage_key:
            try:
                storage.delete(item.storage_key)
            except Exception:
                pass
        item.storage_key = None
        item.filename = None
    for i in db.query(Interaction).filter_by(candidate_id=cid).all():
        i.body = ""
        i.subject = i.subject if i.type == "stage_change" else "[purged]"
    for field in ("email", "phone", "linkedin_url", "resume_text", "past_projects", "career_goals", "summary", "expected_compensation", "interview_status"):
        setattr(c, field, None if field in ("email", "phone", "linkedin_url") else "")
    c.full_name = f"Purged candidate #{c.id}"
    c.purged = True
    audit(db, "candidate.purged", "candidate", cid, u.id, {})
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(action: str | None = None, entity_type: str | None = None, user_id: int | None = None, limit: int = 200, db: Session = Depends(get_db), u: User = Depends(require_roles(*MANAGERS))):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    users = {x.id: x.name for x in db.query(User).all()}
    return [{**row(a), "user_name": users.get(a.user_id)} for a in q.order_by(AuditLog.at.desc()).limit(min(limit, 1000)).all()]
