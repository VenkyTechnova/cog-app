"""Workflow Builder API: trigger → conditions → actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import ALL_STAGES, REPLY_CLASSES, STAGE_LABELS, TEAMS
from ..db import get_db
from ..deps import current_user, require_roles
from ..engine import cron
from ..engine.actions import ACTION_CATALOG
from ..engine.events import EVENT_TYPES, OPS, build_ctx, dispatch, evaluate
from ..engine.queue import enqueue
from ..engine.templates_default import TEMPLATES
from ..models import Candidate, Event, Job, Workflow, WorkflowRun, User
from ..seed.workflows import GUARDRAILS, WORKFLOWS
from ..serializers import row
from ..util import now

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

CONDITION_FIELDS = {
    "candidate.stage": {"type": "enum", "options": ALL_STAGES},
    "candidate.source": {"type": "str"},
    "candidate.work_authorization": {"type": "str"},
    "candidate.preferred_type": {"type": "enum", "options": ["W-2", "C2C", "Either"]},
    "candidate.fit_score": {"type": "number"},
    "candidate.years_experience": {"type": "number"},
    "candidate.email": {"type": "str"},
    "candidate.phone": {"type": "str"},
    "candidate.email_opt_out": {"type": "bool"},
    "candidate.hot_reply": {"type": "bool"},
    "candidate.comfort_check_complete": {"type": "bool"},
    "candidate.consent_granted": {"type": "bool"},
    "candidate.has_vendor_conflict": {"type": "bool"},
    "candidate.skills": {"type": "list"},
    "payload.reply_class": {"type": "enum", "options": REPLY_CLASSES},
    "payload.outcome": {"type": "str"},
    "payload.connected": {"type": "bool"},
    "payload.from_stage": {"type": "enum", "options": ALL_STAGES},
    "payload.to_stage": {"type": "enum", "options": ALL_STAGES},
    "payload.source": {"type": "str"},
    "requirement.priority": {"type": "enum", "options": ["High", "Medium", "Low"]},
    "requirement.employment_type": {"type": "enum", "options": ["W-2", "C2C", "Either"]},
}


def _ser(w: Workflow) -> dict:
    return row(w)


@router.get("/catalog")
def catalog(u: User = Depends(current_user)):
    return {
        "events": EVENT_TYPES,
        "actions": ACTION_CATALOG,
        "operators": OPS,
        "condition_fields": CONDITION_FIELDS,
        "stages": {s: STAGE_LABELS[s] for s in ALL_STAGES},
        "teams": {k: v["label"] for k, v in TEAMS.items()},
        "templates": {k: {"name": v["name"], "auto_send_allowed": v["auto_send_allowed"]} for k, v in TEMPLATES.items()},
        "draft_kinds": ["linkedin_note", "intro_message", "cold_email", "follow_up", "reengagement", "check_in", "dm", "offer_explainer"],
        "workflow_templates": WORKFLOWS,
        "guardrails": GUARDRAILS,
    }


@router.get("")
def list_workflows(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return [_ser(w) for w in db.query(Workflow).order_by(Workflow.trigger_event, Workflow.id).all()]


@router.get("/{wid}")
def get_workflow(wid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    w = db.get(Workflow, wid)
    if w is None:
        raise HTTPException(404)
    runs = db.query(WorkflowRun).filter_by(workflow_id=wid).order_by(WorkflowRun.at.desc()).limit(50).all()
    jobs = db.query(Job).filter(Job.workflow_id == wid).order_by(Job.id.desc()).limit(20).all()
    return {**_ser(w), "runs": [row(r) for r in runs], "jobs": [row(j) for j in jobs]}


class WorkflowIn(BaseModel):
    key: str | None = None
    name: str | None = None
    description: str | None = None
    task_id: str | None = None
    trigger_event: str | None = None
    schedule: str | None = None
    conditions: list[dict] | None = None
    actions: list[dict] | None = None
    enabled: bool | None = None
    minutes_saved_per_run: float | None = None


def _validate(data: dict, db: Session | None = None):
    if db is not None and data.get("task_id"):
        from ..models import TaskItem

        if db.get(TaskItem, data["task_id"]) is None:
            raise HTTPException(422, f"Unknown task id {data['task_id']}")
    if "trigger_event" in data and data["trigger_event"] not in EVENT_TYPES:
        raise HTTPException(422, f"Unknown trigger {data['trigger_event']}")
    if data.get("trigger_event") == "schedule" and not cron.validate(data.get("schedule") or ""):
        raise HTTPException(422, "Scheduled workflows need a valid 5-field cron expression")
    for a in data.get("actions") or []:
        if a.get("type") not in ACTION_CATALOG:
            raise HTTPException(422, f"Unknown action {a.get('type')}")
        if a["type"] == "send_template":
            tpl = TEMPLATES.get((a.get("params") or {}).get("template"))
            if not tpl or not tpl["auto_send_allowed"]:
                raise HTTPException(422, "Only auto-send-approved templates can be sent by a workflow; personalized outreach must be approved by a recruiter")
    for c in data.get("conditions") or []:
        if c.get("op") not in OPS:
            raise HTTPException(422, f"Unknown operator {c.get('op')}")


@router.post("")
def create_workflow(body: WorkflowIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    data = body.model_dump(exclude_none=True)
    if not data.get("name") or not data.get("trigger_event") or not data.get("actions"):
        raise HTTPException(422, "name, trigger_event and at least one action are required")
    _validate(data, db)
    base = data.get("key") or data["name"].lower().replace(" ", "_")[:60]
    key, n = base, 1
    while db.query(Workflow).filter_by(key=key).first():
        n += 1
        key = f"{base}_{n}"
    data["key"] = key
    w = Workflow(**data)
    db.add(w)
    db.flush()
    audit(db, "workflow.created", "workflow", w.id, u.id, {"key": key})
    db.commit()
    return _ser(w)


@router.patch("/{wid}")
def update_workflow(wid: int, body: WorkflowIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    w = db.get(Workflow, wid)
    if w is None:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    data.pop("key", None)
    _validate({"trigger_event": w.trigger_event, "schedule": w.schedule, **data}, db)
    for k, v in data.items():
        setattr(w, k, v)
    audit(db, "workflow.updated", "workflow", wid, u.id, {k: v for k, v in data.items() if k != "actions"})
    db.commit()
    return _ser(w)


@router.delete("/{wid}")
def delete_workflow(wid: int, db: Session = Depends(get_db), u: User = Depends(require_roles("admin"))):
    w = db.get(Workflow, wid)
    if w is None:
        raise HTTPException(404)
    if w.system:
        raise HTTPException(422, "System workflows can be disabled but not deleted")
    db.query(WorkflowRun).filter_by(workflow_id=wid).delete()
    db.delete(w)
    audit(db, "workflow.deleted", "workflow", wid, u.id, {})
    db.commit()
    return {"ok": True}


class TestIn(BaseModel):
    candidate_id: int | None = None
    payload: dict = {}


@router.post("/{wid}/test")
def test_workflow(wid: int, body: TestIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    """Dry run: evaluate the conditions against a real candidate without executing any action."""
    w = db.get(Workflow, wid)
    if w is None:
        raise HTTPException(404)
    ev = Event(id=0, type=w.trigger_event, candidate_id=body.candidate_id, payload=body.payload)
    ctx = build_ctx(db, ev)
    ok, reasons = evaluate(w.conditions, ctx)
    actions = []
    for a in w.actions:
        a_ok, a_r = evaluate(a.get("conditions") or [], ctx)
        actions.append({"type": a["type"], "label": ACTION_CATALOG[a["type"]]["label"], "would_run": ok and a_ok, "delay_minutes": a.get("delay_minutes", 0), "reasons": a_r})
    return {"matched": ok, "reasons": reasons, "context": ctx, "actions": actions}


@router.post("/{wid}/run-now")
def run_now(wid: int, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    w = db.get(Workflow, wid)
    if w is None:
        raise HTTPException(404)
    if w.trigger_event != "schedule":
        raise HTTPException(422, "Only scheduled workflows can be run on demand")
    if not w.enabled:
        raise HTTPException(422, "Enable the workflow before running it")
    job = enqueue(db, "scheduled_workflow", {"workflow_id": w.id, "fired_at": now().isoformat(), "manual": True})
    from ..engine.queue import run_job

    job.status, job.attempts = "running", 1
    db.commit()
    run_job(db, job)
    audit(db, "workflow.run_now", "workflow", wid, u.id, {})
    db.commit()
    last = db.query(WorkflowRun).filter_by(workflow_id=wid).order_by(WorkflowRun.id.desc()).first()
    return {"ok": True, "last_run": row(last) if last else None}
