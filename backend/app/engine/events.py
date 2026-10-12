"""Event bus: every domain change emits an event; enabled workflows subscribed to it run.

Immediate actions run inline inside a SAVEPOINT (so the UI reflects them at once). If one
fails, the savepoint is rolled back and the action is re-queued as a job with retries.
Delayed actions are always queued.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import Candidate, Event, Requirement, Workflow, WorkflowRun
from ..util import aware, now
from .queue import enqueue, handler

log = logging.getLogger(__name__)

MAX_DEPTH = 6
_depth = 0

# Catalogue shown in the Workflow Builder.
EVENT_TYPES = {
    "candidate.created": "A candidate record was created (any source)",
    "candidate.imported": "A LinkedIn / CSV profile was imported",
    "candidate.updated": "Candidate fields changed",
    "application.received": "Inbound job-posting application received",
    "requirement.created": "A new requirement / job opening was added",
    "stage.changed": "Candidate moved between pipeline stages",
    "linkedin.connected": "LinkedIn connection accepted (status set to Connected)",
    "email.sent": "An outreach email was sent",
    "email.reply_received": "A candidate replied (classified)",
    "call.logged": "A call outcome was recorded",
    "qualification.saved": "Qualification form saved",
    "process.explained": "Recruiter marked the process as explained",
    "comfort_check.completed": "Comfort check completed",
    "consent.recorded": "Candidate granted consent to proceed",
    "document.uploaded": "Candidate uploaded a document",
    "documents.complete": "All required documents uploaded and valid",
    "document.verified": "Onboarding verified a document",
    "documents.verified": "All required documents verified",
    "note.saved": "A note was saved",
    "ticket.created": "A delegation ticket was created",
    "post.engagement": "Someone engaged with a recruitment post",
    "schedule": "Runs on a cron schedule",
}

OPS = ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "not_exists", "contains", "is_true", "is_false"]


def _cand_dict(c: Candidate | None) -> dict:
    if c is None:
        return {}
    return {
        "id": c.id,
        "stage": c.stage,
        "source": c.source,
        "work_authorization": c.work_authorization,
        "preferred_type": c.preferred_type,
        "fit_score": c.fit_score,
        "email": c.email,
        "phone": c.phone,
        "owner_id": c.owner_id,
        "email_opt_out": c.email_opt_out,
        "linkedin_status": c.linkedin_status,
        "hot_reply": c.hot_reply,
        "comfort_check_complete": bool((c.comfort_check or {}).get("completed_at")),
        "consent_granted": _consent_granted(c),
        "skills": c.skills or [],
        "years_experience": c.years_experience,
        "has_vendor_conflict": bool((c.vendor_conflict or {}).get("conflict")),
    }


def _consent_granted(c: Candidate) -> bool:
    from ..models import ConsentRecord
    from sqlalchemy.orm import object_session

    s = object_session(c)
    if s is None:
        return False
    return (
        s.query(ConsentRecord).filter_by(candidate_id=c.id, consent_type="proceed", status="granted").first() is not None
    )


def build_ctx(db: Session, ev: Event) -> dict:
    c = db.get(Candidate, ev.candidate_id) if ev.candidate_id else None
    r = db.get(Requirement, ev.requirement_id) if ev.requirement_id else None
    return {
        "event": {"type": ev.type, "id": ev.id, **(ev.payload or {})},
        "payload": ev.payload or {},
        "candidate": _cand_dict(c),
        "requirement": {"id": r.id, "priority": r.priority, "employment_type": r.employment_type, "skills": r.skills} if r else {},
    }


def _get(ctx: dict, path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def evaluate(conditions: list[dict], ctx: dict) -> tuple[bool, list[str]]:
    reasons = []
    for cond in conditions or []:
        val = _get(ctx, cond.get("field", ""))
        op, target = cond.get("op", "eq"), cond.get("value")
        ok = False
        try:
            if op == "eq":
                ok = val == target
            elif op == "neq":
                ok = val != target
            elif op == "in":
                ok = val in (target or [])
            elif op == "not_in":
                ok = val not in (target or [])
            elif op in ("gt", "gte", "lt", "lte"):
                if val is not None:
                    v, t = float(val), float(target)
                    ok = {"gt": v > t, "gte": v >= t, "lt": v < t, "lte": v <= t}[op]
            elif op == "exists":
                ok = val not in (None, "", [], {})
            elif op == "not_exists":
                ok = val in (None, "", [], {})
            elif op == "contains":
                ok = target in (val or [])
            elif op == "is_true":
                ok = bool(val)
            elif op == "is_false":
                ok = not bool(val)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            reasons.append(f"{cond.get('field')} {op} {target!r} (was {val!r})")
            return False, reasons
    return True, reasons


def emit(
    db: Session,
    type_: str,
    candidate_id: int | None = None,
    requirement_id: int | None = None,
    user_id: int | None = None,
    payload: dict | None = None,
) -> Event:
    ev = Event(type=type_, candidate_id=candidate_id, requirement_id=requirement_id, user_id=user_id, payload=payload or {}, occurred_at=now())
    db.add(ev)
    db.flush()
    dispatch(db, ev)
    return ev


def dispatch(db: Session, ev: Event, only_workflow_id: int | None = None) -> list[WorkflowRun]:
    global _depth
    if _depth >= MAX_DEPTH:
        log.warning("Max workflow depth reached at event %s", ev.type)
        return []
    q = db.query(Workflow).filter(Workflow.enabled.is_(True), Workflow.is_template.is_(False), Workflow.trigger_event == ev.type)
    if only_workflow_id:
        q = q.filter(Workflow.id == only_workflow_id)
    runs = []
    _depth += 1
    try:
        for wf in q.order_by(Workflow.id).all():
            ctx = build_ctx(db, ev)
            ok, reasons = evaluate(wf.conditions, ctx)
            if not ok:
                continue  # non-matching workflows aren't logged, to keep the run log readable
            run = WorkflowRun(workflow_id=wf.id, event_id=ev.id, candidate_id=ev.candidate_id, status="matched", detail={"actions": []}, at=now())
            db.add(run)
            db.flush()
            wf.run_count = (wf.run_count or 0) + 1
            wf.last_run_at = now()
            results = []
            for idx, action in enumerate(wf.actions or []):
                delay = float(action.get("delay_minutes") or 0)
                if delay > 0:
                    enqueue(db, "workflow_action", {"workflow_id": wf.id, "action_index": idx, "event_id": ev.id, "run_id": run.id}, delay_minutes=delay, workflow_id=wf.id)
                    results.append({"type": action["type"], "status": "scheduled", "delay_minutes": delay})
                    continue
                a_ok, a_reasons = evaluate(action.get("conditions") or [], build_ctx(db, ev))
                if not a_ok:
                    results.append({"type": action["type"], "status": "skipped", "reasons": a_reasons})
                    continue
                results.append(_run_inline(db, wf, idx, ev, run))
                if results[-1].get("halt"):
                    break
            run.detail = {"actions": results}
            run.status = "failed" if any(r.get("status") == "retrying" for r in results) else "completed"
            runs.append(run)
        db.flush()
    finally:
        _depth -= 1
    return runs


def _run_inline(db: Session, wf: Workflow, idx: int, ev: Event, run: WorkflowRun) -> dict:
    from .actions import execute_action

    action = wf.actions[idx]
    sp = db.begin_nested()
    try:
        res = execute_action(db, action, ev, wf) or {}
        sp.commit()
        return {"type": action["type"], "status": "done", **res}
    except Exception as exc:
        sp.rollback()
        log.warning("Inline action %s failed (%s); queued for retry", action.get("type"), exc)
        enqueue(db, "workflow_action", {"workflow_id": wf.id, "action_index": idx, "event_id": ev.id, "run_id": run.id}, delay_minutes=1, workflow_id=wf.id)
        return {"type": action["type"], "status": "retrying", "error": str(exc)[:300]}


@handler("workflow_action")
def _job_workflow_action(db: Session, payload: dict) -> dict:
    from .actions import execute_action

    wf = db.get(Workflow, payload["workflow_id"])
    ev = db.get(Event, payload["event_id"])
    if wf is None or ev is None or not wf.enabled:
        return {"skipped": True}
    action = wf.actions[payload["action_index"]]
    # Re-check conditions at execution time (state may have changed during the delay).
    ok, reasons = evaluate(action.get("conditions") or [], build_ctx(db, ev))
    if not ok:
        return {"skipped": True, "reasons": reasons}
    res = execute_action(db, action, ev, wf) or {}
    return res
