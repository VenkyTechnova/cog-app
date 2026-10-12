"""Postgres-backed job queue with delays, retries (exponential backoff) and dedupe keys.

Uses `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL so several workers can run safely.
The interface (enqueue / run_due_jobs) is small enough to swap for Celery or Temporal later.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from ..models import Job
from ..util import now

log = logging.getLogger(__name__)

HANDLERS: dict[str, Callable[[Session, dict], dict | None]] = {}


def handler(job_type: str):
    def deco(fn):
        HANDLERS[job_type] = fn
        return fn

    return deco


def enqueue(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    run_at: datetime | None = None,
    delay_minutes: float = 0,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
    workflow_id: int | None = None,
) -> Job | None:
    if dedupe_key:
        existing = db.query(Job).filter(Job.dedupe_key == dedupe_key, Job.status.in_(["queued", "running", "done"])).first()
        if existing:
            return None
    job = Job(
        type=job_type,
        payload=payload or {},
        run_at=run_at or (now() + timedelta(minutes=delay_minutes)),
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
        workflow_id=workflow_id,
    )
    db.add(job)
    db.flush()
    return job


def cancel(db: Session, job_type: str, match: dict) -> int:
    n = 0
    for j in db.query(Job).filter(Job.type == job_type, Job.status == "queued").all():
        if all(j.payload.get(k) == v for k, v in match.items()):
            j.status = "cancelled"
            n += 1
    return n


def _claim(db: Session, limit: int) -> list[Job]:
    q = db.query(Job).filter(Job.status == "queued", Job.run_at <= now()).order_by(Job.run_at, Job.id).limit(limit)
    if db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    jobs = q.all()
    for j in jobs:
        j.status = "running"
        j.attempts += 1
    db.commit()
    return jobs


def run_job(db: Session, job: Job) -> None:
    fn = HANDLERS.get(job.type)
    try:
        if fn is None:
            raise RuntimeError(f"No handler for job type {job.type}")
        result = fn(db, job.payload or {})
        job.status = "done"
        job.result = result or {}
        job.finished_at = now()
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(Job, job.id)
        job.last_error = f"{exc}\n{traceback.format_exc()[-1500:]}"
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.finished_at = now()
            log.error("Job %s (%s) failed permanently: %s", job.id, job.type, exc)
        else:
            job.status = "queued"
            job.run_at = now() + timedelta(minutes=2 ** job.attempts)
            log.warning("Job %s (%s) failed, retrying: %s", job.id, job.type, exc)
        db.commit()


def run_due_jobs(db: Session, limit: int = 100, max_rounds: int = 10) -> int:
    """Run every job that is due. Jobs enqueued by jobs are picked up in later rounds."""
    from . import actions  # noqa: F401  (register handlers)

    total = 0
    for _ in range(max_rounds):
        jobs = _claim(db, limit)
        if not jobs:
            break
        for j in jobs:
            run_job(db, j)
            total += 1
    return total
