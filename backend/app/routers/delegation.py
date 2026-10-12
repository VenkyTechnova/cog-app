"""Delegation Center: tickets with SLA timers, recruitment-post requests with a checklist gate."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import TEAMS
from ..db import get_db
from ..deps import current_user, require_roles
from ..engine import compliance, tickets
from ..models import RecruitmentPost, Ticket, User
from ..serializers import row
from ..util import aware, now

router = APIRouter(prefix="/api", tags=["delegation"])

POST_CHECKLIST = {
    "accurate": "Role details match the requirement (title, skills, location, arrangement)",
    "clear": "Clear, plain language; one call to action",
    "consistent_with_process": "Describes Cognitech's approved process accurately",
    "no_pay_or_immigration_claims": "No pay amounts, pay dates, tax or immigration statements",
    "disclaimer": "Includes 'not a final employment commitment' where an opportunity is described",
}


def _ticket(t: Ticket, users: dict) -> dict:
    d = row(t)
    d["candidate_name"] = t.candidate.full_name if t.candidate else None
    d["requested_by_name"] = users.get(t.requested_by)
    d["assignee_name"] = users.get(t.assignee_id)
    d["team_label"] = TEAMS[t.team]["label"]
    d["seconds_to_due"] = int((aware(t.due_at) - now()).total_seconds()) if t.status != "resolved" else None
    return d


@router.get("/tickets")
def list_tickets(team: str | None = None, status: str = "open,in_progress", db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(Ticket)
    my_team = {"payroll": "payroll", "immigration": "immigration", "onboarding": "onboarding", "marketing": "marketing", "coordinator": "coordinator"}.get(u.role)
    if my_team:
        q = q.filter(Ticket.team == my_team)
    elif team:
        q = q.filter(Ticket.team == team)
    if status != "all":
        q = q.filter(Ticket.status.in_(status.split(",")))
    users = {x.id: x.name for x in db.query(User).all()}
    items = [_ticket(t, users) for t in q.order_by(Ticket.due_at).all()]
    counts = {k: {"open": 0, "breached": 0, "label": v["label"], "sla_hours": v["sla_hours"]} for k, v in TEAMS.items()}
    cq = db.query(Ticket).filter(Ticket.status != "resolved")
    if my_team:
        cq = cq.filter(Ticket.team == my_team)
        counts = {my_team: counts[my_team]}
    for t in cq.all():
        counts[t.team]["open"] += 1
        counts[t.team]["breached"] += int(t.breached or aware(t.due_at) < now())
    return {"items": items, "teams": counts}


class TicketIn(BaseModel):
    team: str
    subject: str
    description: str = ""
    kind: str = "request"
    candidate_id: int | None = None


@router.post("/tickets")
def create(body: TicketIn, db: Session = Depends(get_db), u: User = Depends(current_user)):
    from ..models import Candidate

    c = db.get(Candidate, body.candidate_id) if body.candidate_id else None
    t = tickets.create_ticket(db, body.team, body.kind, body.subject, body.description, c, u.id)
    db.commit()
    return row(t)


class TicketUpdate(BaseModel):
    status: str | None = None
    assignee_id: int | None = None
    resolution: str | None = None


@router.patch("/tickets/{tid}")
def update(tid: int, body: TicketUpdate, db: Session = Depends(get_db), u: User = Depends(current_user)):
    t = db.get(Ticket, tid)
    if t is None:
        raise HTTPException(404)
    if u.role in TEAMS and u.role != t.team:
        raise HTTPException(403)
    if body.status == "resolved":
        if not (body.resolution or t.resolution):
            raise HTTPException(422, "Add a resolution note")
        tickets.resolve(db, t, body.resolution or t.resolution, u.id)
    elif body.status:
        t.status = body.status
    if body.assignee_id is not None:
        t.assignee_id = body.assignee_id
    if body.resolution is not None and body.status != "resolved":
        t.resolution = body.resolution
    audit(db, "ticket.updated", "ticket", tid, u.id, body.model_dump(exclude_none=True))
    db.commit()
    return row(t)


# ---------------------------------------------------------------------------
# Recruitment posts
# ---------------------------------------------------------------------------
@router.get("/posts")
def list_posts(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return {"items": [row(p) for p in db.query(RecruitmentPost).order_by(RecruitmentPost.created_at.desc()).all()], "checklist": POST_CHECKLIST}


class PostUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    checklist: dict | None = None
    status: str | None = None


@router.patch("/posts/{pid}")
def update_post(pid: int, body: PostUpdate, db: Session = Depends(get_db), u: User = Depends(require_roles("marketing", "recruiter", "ta_lead"))):
    p = db.get(RecruitmentPost, pid)
    if p is None:
        raise HTTPException(404)
    for k in ("title", "body", "checklist"):
        v = getattr(body, k)
        if v is not None:
            setattr(p, k, v)
    scan = compliance.scan(f"{p.title}\n{p.body}")
    if body.status:
        if body.status == "published":
            missing = [k for k in POST_CHECKLIST if not (p.checklist or {}).get(k)]
            if missing:
                raise HTTPException(422, {"message": "Checklist incomplete", "missing": missing})
            if scan.blocked:
                raise HTTPException(422, {"message": "Post contains pay / tax / immigration statements", "hits": scan.as_dict()["hits"]})
            p.published_at = now()
            if p.ticket_id:
                t = db.get(Ticket, p.ticket_id)
                if t and t.status != "resolved":
                    tickets.resolve(db, t, f"Published on {p.channel}", u.id)
        p.status = body.status
    audit(db, "post.updated", "post", pid, u.id, {"status": body.status})
    db.commit()
    return {**row(p), "compliance": scan.as_dict()}
