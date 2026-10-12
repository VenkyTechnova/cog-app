"""Analytics dashboards + Automation Impact report."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..engine import analytics
from ..models import DataQualitySnapshot, Interaction, OutboundEmail, User
from ..serializers import row
from ..util import local_today, now, start_of_local_day

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
def overview(days: int = 7, user_id: int | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)):
    since = now() - timedelta(days=days)
    uid = user_id
    recruiters = db.query(User).filter(User.role == "recruiter", User.is_active.is_(True)).order_by(User.name).all()
    daily = []
    for k in range(days - 1, -1, -1):
        d = local_today() - timedelta(days=k)
        start, end = start_of_local_day(d), start_of_local_day(d + timedelta(days=1))
        q = db.query(Interaction.type, func.count(Interaction.id)).filter(Interaction.occurred_at >= start, Interaction.occurred_at < end)
        if uid:
            q = q.filter(Interaction.user_id == uid)
        counts = dict(q.group_by(Interaction.type).all())
        eq = db.query(func.count(OutboundEmail.id)).filter(OutboundEmail.kind == "candidate", OutboundEmail.status == "sent", OutboundEmail.sent_at >= start, OutboundEmail.sent_at < end)
        if uid:
            eq = eq.filter(OutboundEmail.user_id == uid)
        daily.append({"date": d.isoformat(), "calls": counts.get("call", 0), "emails": eq.scalar() or 0, "linkedin": counts.get("linkedin_connection", 0) + counts.get("linkedin_message", 0)})
    eq_all = db.query(OutboundEmail).filter(OutboundEmail.kind == "candidate", OutboundEmail.status == "sent", OutboundEmail.sent_at >= since)
    if uid:
        eq_all = eq_all.filter(OutboundEmail.user_id == uid)
    emails = eq_all.all()
    return {
        "days": days,
        "activity": analytics.activity(db, since, uid),
        "quality": analytics.quality(db, since, uid),
        "pipeline": analytics.pipeline(db, uid),
        "data_quality": analytics.data_quality(db),
        "dq_trend": [{"date": s.snapshot_date.isoformat(), "score": s.score} for s in db.query(DataQualitySnapshot).order_by(DataQualitySnapshot.snapshot_date).all()[-30:]],
        "daily": daily,
        "email_engagement": {"sent": len(emails), "opened": sum(1 for e in emails if e.opened_at), "clicked": sum(1 for e in emails if e.click_count)},
        "by_recruiter": [
            {"id": r.id, "name": r.name, **analytics.activity(db, since, r.id), **analytics.quality(db, since, r.id)} for r in recruiters
        ],
    }


@router.get("/impact")
def impact(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return analytics.impact(db)


@router.get("/data-quality/history")
def dq_history(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return [row(s) for s in db.query(DataQualitySnapshot).order_by(DataQualitySnapshot.snapshot_date.desc()).limit(90).all()]
