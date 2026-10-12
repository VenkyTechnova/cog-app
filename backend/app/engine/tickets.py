"""Delegation Center: tickets to Payroll, Immigration, Onboarding, Marketing, Coordinator — with SLAs."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import TEAMS
from ..models import Candidate, Interaction, Ticket, User
from ..util import aware, now
from .notify import notify

# Candidate-facing team names (never mention immigration in an automated email).
CANDIDATE_TEAM_LABEL = {
    "payroll": "Payroll",
    "immigration": "authorized specialist",
    "onboarding": "Onboarding",
    "marketing": "Marketing",
    "coordinator": "Recruiting Coordinator",
}


def create_ticket(
    db: Session,
    team: str,
    kind: str,
    subject: str,
    description: str = "",
    candidate: Candidate | None = None,
    requested_by: int | None = None,
    acknowledge_candidate: bool = False,
    sla_hours: int | None = None,
) -> Ticket:
    if team not in TEAMS:
        raise ValueError(f"Unknown team {team}")
    sla = sla_hours or TEAMS[team]["sla_hours"]
    t = Ticket(
        team=team,
        kind=kind,
        subject=subject,
        description=description,
        candidate_id=candidate.id if candidate else None,
        requested_by=requested_by,
        sla_hours=sla,
        due_at=now() + timedelta(hours=sla),
    )
    db.add(t)
    db.flush()
    if candidate:
        db.add(Interaction(candidate_id=candidate.id, user_id=requested_by, type="ticket", subject=f"Delegated to {TEAMS[team]['label']}: {subject}", meta={"ticket_id": t.id}))
    audit(db, "ticket.created", "ticket", t.id, requested_by, {"team": team, "kind": kind})
    notify(db, f"New {TEAMS[team]['label']} ticket: {subject}", description[:300], role=team, link=f"/delegation?ticket={t.id}", kind="ticket")
    if acknowledge_candidate and candidate and candidate.email and not candidate.email_opt_out:
        _acknowledge(db, t, candidate, requested_by)
    from .events import emit

    emit(db, "ticket.created", candidate_id=candidate.id if candidate else None, user_id=requested_by, payload={"ticket_id": t.id, "team": team, "kind": kind})
    return t


def _acknowledge(db: Session, t: Ticket, c: Candidate, user_id: int | None) -> None:
    from ..mail import send_email
    from .ai import generate_draft

    recruiter = db.get(User, c.owner_id) if c.owner_id else None
    subject, body, _ = generate_draft(db, "ticket_ack", c, None, recruiter, {"team_label": CANDIDATE_TEAM_LABEL[t.team], "sla_hours": t.sla_hours})
    rec = send_email(db, c.email, subject, body, kind="candidate", candidate_id=c.id, user_id=user_id)
    if rec.status == "sent":
        t.candidate_acknowledged = True
        db.add(Interaction(candidate_id=c.id, type="email_out", direction="out", subject=subject, body=body, meta={"email_id": rec.id, "auto": True}))


def resolve(db: Session, t: Ticket, resolution: str, user_id: int | None) -> Ticket:
    t.status = "resolved"
    t.resolution = resolution
    t.resolved_at = now()
    audit(db, "ticket.resolved", "ticket", t.id, user_id, {})
    if t.requested_by:
        notify(db, f"Ticket resolved: {t.subject}", resolution[:300], user_ids=[t.requested_by], link=f"/delegation?ticket={t.id}")
    db.flush()
    return t


def check_slas(db: Session) -> int:
    """Mark breached tickets and notify the team + requester once."""
    n = 0
    for t in db.query(Ticket).filter(Ticket.status != "resolved").all():
        if aware(t.due_at) < now() and not t.breached:
            t.breached = True
        if t.breached and not t.breach_notified:
            ids = [t.requested_by] if t.requested_by else []
            ids += [u.id for u in db.query(User).filter(User.role == "ta_lead").all()]
            notify(db, f"SLA breached: {TEAMS[t.team]['label']} — {t.subject}", f"Due {aware(t.due_at):%b %d %H:%M} UTC", user_ids=ids, role=t.team, link=f"/delegation?ticket={t.id}", kind="sla", email=True)
            t.breach_notified = True
            n += 1
    db.flush()
    return n
