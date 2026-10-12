"""Drafts awaiting approval, sequences, Recruiter Home and the pipeline board."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import ALL_STAGES, STAGE_LABELS
from ..db import get_db
from ..deps import current_user, require_roles
from ..engine import followups, outreach
from ..models import Application, CallListItem, Candidate, Draft, Notification, Requirement, Sequence, Ticket, User
from ..serializers import candidate_card, row
from ..util import aware, local_today, now

router = APIRouter(prefix="/api", tags=["outreach"])
STAFF = ("recruiter", "ta_lead", "coordinator")


def _draft(d: Draft) -> dict:
    out = row(d)
    out["candidate"] = candidate_card(d.candidate) if d.candidate else None
    out["requirement_title"] = d.requirement.title if d.requirement else None
    return out


@router.get("/drafts")
def list_drafts(status: str = "pending_approval,blocked,manual_send", mine: bool = True, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    q = db.query(Draft).filter(Draft.status.in_(status.split(",")))
    if mine and u.role == "recruiter":
        q = q.filter((Draft.owner_id == u.id) | (Draft.owner_id.is_(None)))
    q = q.filter((Draft.sequence_id.is_(None)) | (Draft.step == 1))
    return [_draft(d) for d in q.order_by(Draft.created_at.desc()).limit(200).all()]


class DraftEdit(BaseModel):
    subject: str | None = None
    body: str | None = None


def _get(db: Session, did: int) -> Draft:
    d = db.get(Draft, did)
    if d is None:
        raise HTTPException(404)
    return d


@router.patch("/drafts/{did}")
def edit_draft(did: int, body: DraftEdit, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    d = _get(db, did)
    try:
        outreach.update_draft(db, d, body.subject, body.body)
    except outreach.OutreachError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return _draft(d)


@router.post("/drafts/{did}/approve")
def approve_draft(did: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    d = _get(db, did)
    if d.sequence_id:
        seq = db.get(Sequence, d.sequence_id)
        try:
            outreach.approve_sequence(db, seq, u)
            from ..engine.outreach import process_sequences

            process_sequences(db)  # send step 1 now
        except outreach.OutreachError as e:
            db.commit()
            raise HTTPException(422, str(e))
        db.commit()
        return _draft(d)
    try:
        outreach.approve(db, d, u)
    except outreach.OutreachError as e:
        db.commit()  # persist compliance flags / status
        raise HTTPException(422, str(e))
    db.commit()
    return _draft(d)


@router.post("/drafts/{did}/reject")
def reject_draft(did: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    d = _get(db, did)
    if d.sequence_id:
        outreach.stop_sequences(db, d.candidate_id, "rejected")
    d.status = "rejected"
    audit(db, "draft.rejected", "draft", did, u.id, {})
    db.commit()
    return _draft(d)


@router.post("/drafts/{did}/mark-sent")
def mark_sent(did: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    d = _get(db, did)
    if d.channel == "email":
        raise HTTPException(422, "Email drafts are sent by the platform")
    outreach.mark_sent_manually(db, d, u)
    db.commit()
    return _draft(d)


@router.get("/sequences/{sid}")
def get_sequence(sid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    s = db.get(Sequence, sid)
    if s is None:
        raise HTTPException(404)
    return {"sequence": row(s), "drafts": [row(d) for d in db.query(Draft).filter_by(sequence_id=sid).order_by(Draft.step).all()]}


@router.post("/sequences/{sid}/stop")
def stop_sequence(sid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    s = db.get(Sequence, sid)
    if s is None:
        raise HTTPException(404)
    outreach.stop_sequences(db, s.candidate_id, "stopped_by_recruiter")
    db.commit()
    return row(s)


# ---------------------------------------------------------------------------
# Recruiter Home
# ---------------------------------------------------------------------------
@router.get("/home")
def home(user_id: int | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)):
    target = db.get(User, user_id) if (user_id and u.role in ("ta_lead", "admin")) else u
    today = local_today()
    calls = db.query(CallListItem).filter_by(user_id=target.id, list_date=today).order_by(CallListItem.rank).all()
    if not calls and target.role == "recruiter":
        from ..engine.calllist import build_for_user

        calls = build_for_user(db, target)
        db.commit()
    due = followups.due_for_user(db, target)
    hot = db.query(Candidate).filter(Candidate.hot_reply.is_(True), Candidate.merged_into_id.is_(None))
    if target.role == "recruiter":
        hot = hot.filter(Candidate.owner_id == target.id)
    drafts = db.query(Draft).filter(Draft.status.in_(["pending_approval", "blocked", "manual_send"]), (Draft.sequence_id.is_(None)) | (Draft.step == 1))
    if target.role == "recruiter":
        drafts = drafts.filter((Draft.owner_id == target.id) | (Draft.owner_id.is_(None)))
    tickets = db.query(Ticket).filter(Ticket.status != "resolved")
    if target.role == "recruiter":
        tickets = tickets.filter(Ticket.requested_by == target.id)
    apps = (
        db.query(Application)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .filter(Application.created_at >= now() - timedelta(days=3), Application.shortlist_status.in_(["pending", "suggested"]), Candidate.merged_into_id.is_(None))
        .order_by(Application.fit_score.desc().nullslast())
        .limit(10)
        .all()
    )

    def fu(f):
        return {**row(f), "candidate": candidate_card(f.candidate)}

    return {
        "user": {"id": target.id, "name": target.name, "role": target.role},
        "call_list": [{**row(i), "candidate": candidate_card(i.candidate), "requirement_title": i.requirement.title if i.requirement else None} for i in calls],
        "follow_ups_today": [fu(f) for f in due["today"]],
        "follow_ups_overdue": [fu(f) for f in due["overdue"]],
        "hot_replies": [candidate_card(c) for c in hot.order_by(Candidate.hot_reply_at.desc()).all()],
        "drafts": [_draft(d) for d in drafts.order_by(Draft.created_at.desc()).limit(30).all()],
        "tickets": [{**row(t), "candidate_name": t.candidate.full_name if t.candidate else None} for t in tickets.order_by(Ticket.due_at).all()],
        "applicants": [{**row(a), "candidate": candidate_card(a.candidate), "requirement_title": a.requirement.title if a.requirement else None} for a in apps],
        "notifications": [row(n) for n in db.query(Notification).filter_by(user_id=u.id, read=False).order_by(Notification.created_at.desc()).limit(10).all()],
    }


@router.post("/call-list/{iid}")
def call_list_status(iid: int, status: str, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    it = db.get(CallListItem, iid)
    if it is None:
        raise HTTPException(404)
    it.status = status
    db.commit()
    return row(it)


@router.post("/call-list/rebuild")
def rebuild_call_list(db: Session = Depends(get_db), u: User = Depends(require_roles("recruiter"))):
    from ..engine.calllist import build_for_user

    items = build_for_user(db, u)
    db.commit()
    return {"items": len(items)}


@router.post("/applications/{aid}/shortlist")
def shortlist(aid: int, decision: str, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    a = db.get(Application, aid)
    if a is None or decision not in ("shortlisted", "rejected"):
        raise HTTPException(422)
    a.shortlist_status = decision
    c = a.candidate
    if decision == "shortlisted" and c.owner_id is None:
        c.owner_id = u.id
    audit(db, f"application.{decision}", "application", aid, u.id, {})
    db.commit()
    return row(a)


# ---------------------------------------------------------------------------
# Pipeline board
# ---------------------------------------------------------------------------
@router.get("/pipeline")
def pipeline(owner_id: int | None = None, requirement_id: int | None = None, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    q = db.query(Candidate).filter(Candidate.merged_into_id.is_(None), Candidate.purged.is_(False))
    if owner_id:
        q = q.filter(Candidate.owner_id == owner_id)
    cands = q.order_by(Candidate.updated_at.desc()).all()
    if requirement_id:
        from ..models import Match

        ids = {m.candidate_id for m in db.query(Match).filter(Match.requirement_id == requirement_id, Match.score >= 50).all()}
        cands = [c for c in cands if c.id in ids]
    cols = {s: [] for s in ALL_STAGES}
    for c in cands:
        card = candidate_card(c)
        nf = aware(c.next_follow_up_at)
        card["follow_up_overdue"] = bool(nf and nf < now())
        cols[c.stage].append(card)
    return {"columns": [{"stage": s, "label": STAGE_LABELS[s], "cards": cols[s]} for s in ALL_STAGES]}
