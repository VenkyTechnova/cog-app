"""Rule-based follow-up scheduling and reminders."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..constants import STAGE_LABELS
from ..models import Candidate, FollowUp, User
from ..settings_store import get_setting
from ..util import aware, local_tz, now, start_of_local_day, local_today


def _next_business_morning(dt: datetime) -> datetime:
    """Move a due date to 9:00 local time, rolling weekends forward to Monday."""
    local = dt.astimezone(local_tz())
    while local.weekday() >= 5:
        local += timedelta(days=1)
    local = local.replace(hour=9, minute=0, second=0, microsecond=0)
    return local.astimezone(dt.tzinfo)


def schedule(db: Session, c: Candidate, days: float, reason: str, rule: str = "manual", owner_id: int | None = None) -> FollowUp:
    due = _next_business_morning(now() + timedelta(days=days))
    f = FollowUp(candidate_id=c.id, owner_id=owner_id or c.owner_id, due_at=due, reason=reason, rule=rule)
    db.add(f)
    db.flush()
    _sync_next(db, c)
    return f


def schedule_for_stage(db: Session, c: Candidate) -> FollowUp | None:
    cadence = get_setting(db, "followup.cadence_days") or {}
    days = cadence.get(c.stage)
    # Replace any open cadence follow-up with one for the new stage.
    for f in db.query(FollowUp).filter_by(candidate_id=c.id, status="open", rule="stage_cadence").all():
        f.status = "cancelled"
    db.flush()
    if days is None:
        _sync_next(db, c)
        return None
    return schedule(db, c, float(days), f"{STAGE_LABELS.get(c.stage, c.stage)} follow-up", rule="stage_cadence")


def complete(db: Session, f: FollowUp) -> None:
    f.status = "done"
    f.completed_at = now()
    db.flush()
    c = db.get(Candidate, f.candidate_id)
    if c:
        _sync_next(db, c)


def snooze(db: Session, c: Candidate, days: int = 1) -> None:
    c.snoozed_until = now() + timedelta(days=days)
    for f in db.query(FollowUp).filter_by(candidate_id=c.id, status="open").all():
        f.due_at = _next_business_morning(max(aware(f.due_at), now()) + timedelta(days=days))
    db.flush()
    _sync_next(db, c)


def _sync_next(db: Session, c: Candidate) -> None:
    nxt = db.query(FollowUp).filter_by(candidate_id=c.id, status="open").order_by(FollowUp.due_at).first()
    c.next_follow_up_at = nxt.due_at if nxt else None


def due_for_user(db: Session, user: User, include_overdue: bool = True) -> dict:
    end_today = start_of_local_day(local_today() + timedelta(days=1))
    start_today = start_of_local_day()
    q = db.query(FollowUp).join(Candidate, Candidate.id == FollowUp.candidate_id).filter(
        FollowUp.status == "open", Candidate.merged_into_id.is_(None), Candidate.purged.is_(False)
    )
    if user.role == "recruiter":
        q = q.filter(FollowUp.owner_id == user.id)
    rows = q.filter(FollowUp.due_at < end_today).order_by(FollowUp.due_at).all()
    today = [f for f in rows if aware(f.due_at) >= start_today]
    overdue = [f for f in rows if aware(f.due_at) < start_today] if include_overdue else []
    return {"today": today, "overdue": overdue}
