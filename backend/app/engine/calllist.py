"""Daily cold-call list: ranked by match score and time since last contact."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import CallListItem, Candidate, Match, Requirement, User
from ..util import aware, local_today, now

CALLABLE_STAGES = ["sourced", "contacted", "interested", "hold", "closed"]


def build_for_user(db: Session, user: User, size: int = 20) -> list[CallListItem]:
    today = local_today()
    db.query(CallListItem).filter_by(user_id=user.id, list_date=today, status="pending").delete()
    t = now()
    q = db.query(Candidate).filter(
        Candidate.stage.in_(CALLABLE_STAGES),
        Candidate.phone.isnot(None),
        Candidate.merged_into_id.is_(None),
        Candidate.purged.is_(False),
    )
    q = q.filter((Candidate.owner_id == user.id) | (Candidate.owner_id.is_(None)))
    scored = []
    for c in q.all():
        if c.snoozed_until and aware(c.snoozed_until) > t:
            continue
        last = aware(c.last_contact_at)
        if last and last > t - timedelta(days=3):
            continue  # contacted very recently — give them space
        if c.stage in ("hold", "closed") and last and last > t - timedelta(days=90):
            continue
        best = (
            db.query(Match).join(Requirement).filter(Match.candidate_id == c.id, Requirement.status == "open", Match.status != "not_fit").order_by(Match.score.desc()).first()
        )
        match_score = best.score if best else (c.fit_score or 0)
        days_since = (t - last).days if last else 45
        recency = min(days_since, 45) / 45 * 30
        stage_boost = {"interested": 15, "sourced": 5}.get(c.stage, 0)
        total = match_score * 0.6 + recency + stage_boost
        reason = f"Match {match_score:.0f}" + (f" for {best.requirement.title}" if best else "") + (f" · last contact {days_since}d ago" if last else " · never contacted")
        scored.append((total, c, best, reason))
    scored.sort(key=lambda x: x[0], reverse=True)
    items = []
    for rank, (total, c, best, reason) in enumerate(scored[:size], start=1):
        it = CallListItem(user_id=user.id, candidate_id=c.id, requirement_id=best.requirement_id if best else None, list_date=today, rank=rank, score=round(total, 1), reason=reason)
        db.add(it)
        items.append(it)
    db.flush()
    return items


def build_all(db: Session) -> int:
    n = 0
    for u in db.query(User).filter(User.role == "recruiter", User.is_active.is_(True)).all():
        n += len(build_for_user(db, u))
    return n
