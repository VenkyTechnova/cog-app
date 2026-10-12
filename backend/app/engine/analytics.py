"""Activity, quality, pipeline and data-quality metrics, plus the automation-impact model."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import ACTIVE_STAGES, ALL_STAGES, CATEGORIES, STAGE_LABELS
from ..models import (
    Candidate,
    DataQualitySnapshot,
    DocumentRequest,
    DuplicatePair,
    FollowUp,
    Interaction,
    OutboundEmail,
    StageTransition,
    TaskItem,
    User,
    Workflow,
    WorkflowRun,
)
from ..util import aware, local_today, now

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")


def _live(q, model=Candidate):
    return q.filter(model.merged_into_id.is_(None), model.purged.is_(False))


def activity(db: Session, since: datetime, user_id: int | None = None) -> dict:
    def cnt(types, meaningful=None):
        q = db.query(func.count(Interaction.id)).filter(Interaction.occurred_at >= since, Interaction.type.in_(types))
        if user_id:
            q = q.filter(Interaction.user_id == user_id)
        if meaningful is not None:
            q = q.filter(Interaction.meaningful.is_(meaningful))
        return q.scalar() or 0

    eq = db.query(func.count(OutboundEmail.id)).filter(OutboundEmail.kind == "candidate", OutboundEmail.status == "sent", OutboundEmail.sent_at >= since)
    if user_id:
        eq = eq.filter(OutboundEmail.user_id == user_id)
    pq = db.query(func.count(Candidate.id)).filter(Candidate.created_at >= since)
    if user_id:
        pq = pq.filter(Candidate.owner_id == user_id)
    contacts_q = db.query(func.count(func.distinct(Interaction.candidate_id))).filter(
        Interaction.occurred_at >= since, Interaction.type.in_(["call", "email_out", "linkedin_message", "linkedin_connection", "meeting"])
    )
    if user_id:
        contacts_q = contacts_q.filter(Interaction.user_id == user_id)
    return {
        "calls": cnt(["call"]),
        "linkedin_connections": cnt(["linkedin_connection"]),
        "linkedin_messages": cnt(["linkedin_message"]),
        "emails_sent": eq.scalar() or 0,
        "profiles_added": pq.scalar() or 0,
        "unique_contacts": contacts_q.scalar() or 0,
    }


def quality(db: Session, since: datetime, user_id: int | None = None) -> dict:
    mq = db.query(func.count(Interaction.id)).filter(Interaction.occurred_at >= since, Interaction.meaningful.is_(True))
    if user_id:
        mq = mq.filter(Interaction.user_id == user_id)

    def reached(stage):
        q = db.query(func.count(func.distinct(StageTransition.candidate_id))).filter(StageTransition.at >= since, StageTransition.to_stage == stage)
        if user_id:
            q = q.join(Candidate, Candidate.id == StageTransition.candidate_id).filter(Candidate.owner_id == user_id)
        return q.scalar() or 0

    return {
        "meaningful_conversations": mq.scalar() or 0,
        "interested": reached("interested"),
        "qualified": reached("qualified"),
        "documents_received": reached("docs_received"),
        "onboarded": reached("onboarding"),
    }


def pipeline(db: Session, user_id: int | None = None) -> dict:
    q = _live(db.query(Candidate.stage, func.count(Candidate.id)))
    if user_id:
        q = q.filter(Candidate.owner_id == user_id)
    by_stage = {s: 0 for s in ALL_STAGES}
    for s, n in q.group_by(Candidate.stage).all():
        by_stage[s] = n
    fq = db.query(func.count(func.distinct(FollowUp.candidate_id))).filter(FollowUp.status == "open")
    if user_id:
        fq = fq.filter(FollowUp.owner_id == user_id)
    iq = db.query(func.count(Interaction.id)).filter(Interaction.type == "meeting", Interaction.outcome == "client_interview")
    if user_id:
        iq = iq.filter(Interaction.user_id == user_id)
    interviews = iq.scalar() or 0
    return {
        "by_stage": by_stage,
        "labels": STAGE_LABELS,
        "active": sum(by_stage[s] for s in ACTIVE_STAGES),
        "in_follow_up": fq.scalar() or 0,
        "in_opportunity_pipeline": by_stage["marketing_pipeline"],
        "interviews": interviews,
        "placements": by_stage["placed"],
    }


def data_quality(db: Session) -> dict:
    t = now()
    cands = _live(db.query(Candidate)).all()
    total = len(cands) or 1
    accurate = sum(1 for c in cands if (not c.email or EMAIL_RE.match(c.email)) and (not c.phone or len(c.phone) == 10) and c.full_name and c.skills)
    open_dups = db.query(func.count(DuplicatePair.id)).filter(DuplicatePair.status == "open").scalar() or 0
    last = dict(db.query(Interaction.candidate_id, func.max(Interaction.occurred_at)).group_by(Interaction.candidate_id).all())
    active = [c for c in cands if c.stage in ACTIVE_STAGES]
    stale = sum(1 for c in active if (aware(last.get(c.id)) or aware(c.created_at)) < t - timedelta(days=30))
    week = t - timedelta(days=7)
    due = db.query(FollowUp).filter(FollowUp.due_at >= week, FollowUp.due_at <= t, FollowUp.status != "cancelled").all()
    on_time = sum(1 for f in due if f.status == "done" and f.completed_at and aware(f.completed_at) <= aware(f.due_at) + timedelta(days=1))
    fu_compliance = (on_time / len(due)) if due else 1.0
    doc_cands = [c for c in cands if c.stage in ("docs_requested", "docs_received", "onboarding")]
    complete = 0
    for c in doc_cands:
        r = db.query(DocumentRequest).filter(DocumentRequest.candidate_id == c.id).order_by(DocumentRequest.id.desc()).first()
        if r and r.status in ("complete", "verified"):
            complete += 1
    doc_completeness = (complete / len(doc_cands)) if doc_cands else 1.0
    metrics = {
        "accuracy": round(accurate / total, 3),
        "duplicate_rate": round(open_dups / total, 3),
        "open_duplicates": open_dups,
        "stale_rate": round(stale / (len(active) or 1), 3),
        "stale_records": stale,
        "follow_up_compliance": round(fu_compliance, 3),
        "document_completeness": round(doc_completeness, 3),
    }
    score = 100 * (
        0.30 * metrics["accuracy"]
        + 0.15 * (1 - min(metrics["duplicate_rate"] * 5, 1))
        + 0.20 * (1 - metrics["stale_rate"])
        + 0.20 * metrics["follow_up_compliance"]
        + 0.15 * metrics["document_completeness"]
    )
    return {"score": round(score, 1), "metrics": metrics}


def snapshot_data_quality(db: Session) -> DataQualitySnapshot:
    dq = data_quality(db)
    today = local_today()
    snap = db.query(DataQualitySnapshot).filter_by(snapshot_date=today).one_or_none()
    if snap is None:
        snap = DataQualitySnapshot(snapshot_date=today, score=dq["score"], metrics=dq["metrics"])
        db.add(snap)
    else:
        snap.score, snap.metrics = dq["score"], dq["metrics"]
    db.flush()
    return snap


def impact(db: Session) -> dict:
    """Estimated (task map) and measured (workflow runs) automation impact."""
    tasks = db.query(TaskItem).order_by(TaskItem.sort_order).all()
    by_cat = {c: {"count": 0, "minutes_saved": 0, "baseline": 0} for c in CATEGORIES}
    by_stage: dict[str, dict] = {}
    for t in tasks:
        cat = by_cat.setdefault(t.category, {"count": 0, "minutes_saved": 0, "baseline": 0})
        cat["count"] += 1
        cat["minutes_saved"] += t.est_minutes_saved_per_week
        cat["baseline"] += t.baseline_minutes_per_week
        st = by_stage.setdefault(t.stage, {"count": 0, "minutes_saved": 0, "baseline": 0})
        st["count"] += 1
        st["minutes_saved"] += t.est_minutes_saved_per_week
        st["baseline"] += t.baseline_minutes_per_week
    baseline = sum(t.baseline_minutes_per_week for t in tasks)
    saved = sum(t.est_minutes_saved_per_week for t in tasks)
    week = now() - timedelta(days=7)
    runs = (
        db.query(Workflow.name, Workflow.minutes_saved_per_run, func.count(WorkflowRun.id))
        .join(WorkflowRun, WorkflowRun.workflow_id == Workflow.id)
        .filter(WorkflowRun.at >= week, WorkflowRun.status == "completed")
        .group_by(Workflow.id, Workflow.name, Workflow.minutes_saved_per_run)
        .all()
    )
    recruiters = db.query(func.count(User.id)).filter(User.role == "recruiter", User.is_active.is_(True)).scalar() or 1
    measured_minutes = sum(m * n for _, m, n in runs)
    top = sorted(tasks, key=lambda t: t.est_minutes_saved_per_week, reverse=True)[:10]
    return {
        "per_recruiter_week": {
            "baseline_hours": round(baseline / 60, 1),
            "hours_saved": round(saved / 60, 1),
            "after_hours": round((baseline - saved) / 60, 1),
            "percent_reduction": round(100 * saved / baseline, 1) if baseline else 0,
        },
        "team_week": {"recruiters": recruiters, "hours_saved": round(recruiters * saved / 60, 1)},
        "by_category": by_cat,
        "by_stage": by_stage,
        "task_count": len(tasks),
        "measured_last_7d": {
            "hours_saved_team": round(measured_minutes / 60, 1),
            "hours_saved_per_recruiter": round(measured_minutes / 60 / recruiters, 1),
            "workflows": [{"name": n, "runs": c, "minutes": round(m * c, 1)} for n, m, c in sorted(runs, key=lambda r: -r[1] * r[2])],
        },
        "top_tasks": [{"id": t.id, "task_name": t.task_name, "category": t.category, "minutes": t.est_minutes_saved_per_week} for t in top],
    }
