"""Scheduler + worker.

* `tick()` runs once a minute: every enabled workflow with trigger `schedule` whose cron
  expression matches the current local minute is queued (deduped per minute, so running
  several schedulers is safe).
* `run_forever()` is the worker process: `python -m app.scheduler`.
  In development the API starts the same loop in a background thread (EMBEDDED_WORKER=true).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from .config import get_settings
from .db import SessionLocal
from .engine import cron
from .engine.queue import enqueue, run_due_jobs
from .models import Workflow
from .util import now, to_local

log = logging.getLogger(__name__)


def tick(db, at: datetime | None = None) -> list[str]:
    at = at or now()
    local = to_local(at).replace(second=0, microsecond=0)
    fired = []
    for wf in db.query(Workflow).filter(Workflow.enabled.is_(True), Workflow.is_template.is_(False), Workflow.trigger_event == "schedule").all():
        if not wf.schedule:
            continue
        try:
            if cron.matches(wf.schedule, local):
                job = enqueue(db, "scheduled_workflow", {"workflow_id": wf.id, "fired_at": local.isoformat()}, run_at=at, dedupe_key=f"sched:{wf.id}:{local:%Y%m%d%H%M}")
                if job:
                    fired.append(wf.key)
        except ValueError:
            log.error("Invalid cron on workflow %s: %s", wf.key, wf.schedule)
    db.commit()
    return fired


def run_forever(stop: threading.Event | None = None) -> None:
    poll = get_settings().worker_poll_seconds
    last_minute = None
    log.info("Worker started (poll=%ss)", poll)
    while not (stop and stop.is_set()):
        db = SessionLocal()
        try:
            minute = now().replace(second=0, microsecond=0)
            if minute != last_minute:
                fired = tick(db)
                if fired:
                    log.info("Scheduled workflows fired: %s", fired)
                last_minute = minute
            run_due_jobs(db)
        except Exception:
            log.exception("Worker loop error")
            db.rollback()
        finally:
            db.close()
        time.sleep(poll)


def start_embedded() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(stop,), daemon=True, name="worker").start()
    return stop


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_forever()
