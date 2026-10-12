"""Task Map: the categorised inventory of every recurring playbook task."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import CATEGORIES, CATEGORY_RULES, TASK_STATUSES, TEAMS
from ..db import get_db
from ..deps import current_user, require_roles
from ..engine.analytics import impact
from ..models import TaskItem, User, Workflow
from ..seed.workflows import BUILTINS, GUARDRAILS
from ..serializers import row

router = APIRouter(prefix="/api/tasks", tags=["task map"])


def _ser(t: TaskItem, wf_by_key: dict) -> dict:
    d = row(t)
    key = t.workflow_key or ""
    if key.startswith("guardrail:"):
        g = next((g for g in GUARDRAILS if g["key"] == key), None)
        d["implementation"] = {"type": "guardrail", "label": g["name"] if g else key, "description": g["description"] if g else ""}
    elif key.startswith("builtin:"):
        d["implementation"] = {"type": "builtin", "label": BUILTINS.get(key, key)}
    elif key in wf_by_key:
        w = wf_by_key[key]
        d["implementation"] = {"type": "workflow", "label": w.name, "workflow_id": w.id, "enabled": w.enabled}
    else:
        d["implementation"] = None
    return d


def _stage_order(db: Session) -> list[str]:
    order: dict[str, int] = {}
    for stage, so in db.query(TaskItem.stage, TaskItem.sort_order).all():
        order[stage] = min(order.get(stage, so), so)
    return sorted(order, key=order.get)


@router.get("")
def list_tasks(category: str | None = None, stage: str | None = None, q: str | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)):
    qry = db.query(TaskItem)
    if category:
        qry = qry.filter(TaskItem.category == category)
    if stage:
        qry = qry.filter(TaskItem.stage == stage)
    tasks = qry.order_by(TaskItem.sort_order).all()
    if q:
        ql = q.lower()
        tasks = [t for t in tasks if ql in t.task_name.lower() or ql in (t.rationale or "").lower() or ql in t.id.lower()]
    wf_by_key = {w.key: w for w in db.query(Workflow).all()}
    return {
        "items": [_ser(t, wf_by_key) for t in tasks],
        "categories": CATEGORIES,
        "category_rules": CATEGORY_RULES,
        "statuses": TASK_STATUSES,
        "teams": {k: v["label"] for k, v in TEAMS.items()},
        "stages": _stage_order(db),
        "summary": impact(db),
    }


class TaskIn(BaseModel):
    id: str | None = None
    playbook_section: str | None = None
    stage: str | None = None
    task_name: str | None = None
    frequency: str | None = None
    current_owner: str | None = None
    category: str | None = None
    rationale: str | None = None
    trigger: str | None = None
    automation_action: str | None = None
    delegate_to: str | None = None
    sla_hours: int | None = None
    est_minutes_saved_per_week: int | None = None
    baseline_minutes_per_week: int | None = None
    status: str | None = None
    workflow_key: str | None = None


def _validate(data: dict):
    if "category" in data and data["category"] not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    if "status" in data and data["status"] not in TASK_STATUSES:
        raise HTTPException(422, f"status must be one of {TASK_STATUSES}")
    if data.get("category") == "Delegate" and not data.get("delegate_to"):
        raise HTTPException(422, "Delegate tasks need a delegate_to team")
    if data.get("delegate_to") and data["delegate_to"] not in TEAMS:
        raise HTTPException(422, f"delegate_to must be one of {list(TEAMS)}")


@router.patch("/{tid}")
def update_task(tid: str, body: TaskIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    t = db.get(TaskItem, tid)
    if t is None:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    data.pop("id", None)
    merged = {**row(t), **data}
    if merged["category"] != "Delegate":
        merged["delegate_to"] = None
        if t.delegate_to or "delegate_to" in data:
            data["delegate_to"] = None
    _validate({k: merged.get(k) for k in ("category", "status", "delegate_to")})
    for k, v in data.items():
        setattr(t, k, v)
    t.updated_by = u.id
    audit(db, "task.updated", "task", tid, u.id, data)
    db.commit()
    return _ser(t, {w.key: w for w in db.query(Workflow).all()})


@router.post("")
def create_task(body: TaskIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    data = body.model_dump(exclude_unset=True)
    for req in ("id", "stage", "task_name", "category"):
        if not data.get(req):
            raise HTTPException(422, f"{req} is required")
    if db.get(TaskItem, data["id"]):
        raise HTTPException(409, "Task id already exists")
    _validate(data)
    data.setdefault("playbook_section", "")
    data.setdefault("frequency", "Weekly")
    data.setdefault("current_owner", "Recruiter")
    data["sort_order"] = (db.query(TaskItem).count() or 0) + 1
    t = TaskItem(**data, updated_by=u.id)
    db.add(t)
    audit(db, "task.created", "task", t.id, u.id, data)
    db.commit()
    return _ser(t, {w.key: w for w in db.query(Workflow).all()})


@router.delete("/{tid}")
def delete_task(tid: str, db: Session = Depends(get_db), u: User = Depends(require_roles("admin"))):
    t = db.get(TaskItem, tid)
    if t is None:
        raise HTTPException(404)
    db.query(Workflow).filter(Workflow.task_id == tid).update({Workflow.task_id: None})
    db.delete(t)
    audit(db, "task.deleted", "task", tid, u.id, {})
    db.commit()
    return {"ok": True}


@router.get("/impact")
def impact_report(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return impact(db)
