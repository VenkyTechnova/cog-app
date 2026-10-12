"""Settings: runtime settings, email templates, digest preview / send / logs, integrations, job queue."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import current_user, require_roles
from ..digest.builder import build
from ..digest.sender import render, send_digest
from ..engine import compliance, cron
from ..engine.queue import run_due_jobs
from ..models import DigestLog, EmailTemplate, Job, OutboundEmail, User, Workflow
from ..serializers import row
from ..settings_store import DEFAULTS, all_settings, set_setting

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_all(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return {"values": all_settings(db), "defaults": DEFAULTS}


class SettingIn(BaseModel):
    value: Any


@router.put("/settings/{key}")
def put(key: str, body: SettingIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    if key not in DEFAULTS:
        raise HTTPException(404, "Unknown setting")
    v = body.value
    if key == "digest.time":
        try:
            h, m = str(v).split(":")
            assert 0 <= int(h) < 24 and 0 <= int(m) < 60
        except Exception:
            raise HTTPException(422, "Use HH:MM (24h)")
    if key == "digest.when_empty" and v not in ("note", "skip"):
        raise HTTPException(422, "Use 'note' or 'skip'")
    set_setting(db, key, v)
    if key in ("digest.time", "digest.business_days_only"):
        vals = all_settings(db)
        wf = db.query(Workflow).filter_by(key="daily_digest").one_or_none()
        if wf:
            wf.schedule = cron.time_to_cron(vals["digest.time"], bool(vals["digest.business_days_only"]))
    audit(db, "setting.updated", "setting", key, u.id, {"value": v})
    db.commit()
    return {"key": key, "value": v}


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------
@router.get("/templates")
def templates(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return [row(t) for t in db.query(EmailTemplate).order_by(EmailTemplate.key).all()]


class TemplateIn(BaseModel):
    subject: str | None = None
    body: str | None = None
    name: str | None = None


@router.put("/templates/{key}")
def update_template(key: str, body: TemplateIn, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    t = db.get(EmailTemplate, key)
    if t is None:
        raise HTTPException(404)
    new_body = body.body if body.body is not None else t.body
    new_subject = body.subject if body.subject is not None else t.subject
    res = compliance.scan(f"{new_subject}\n{new_body}")
    if res.blocked:
        raise HTTPException(422, {"message": "Templates can't contain pay, tax or immigration statements", "hits": res.as_dict()["hits"]})
    t.body, t.subject = new_body, new_subject
    if body.name:
        t.name = body.name
    audit(db, "template.updated", "template", key, u.id, {})
    db.commit()
    return row(t)


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------
@router.get("/digest/preview", response_class=HTMLResponse)
def preview(user_id: int | None = None, format: str = "html", db: Session = Depends(get_db), u: User = Depends(current_user)):
    target = db.get(User, user_id) if (user_id and u.role in ("ta_lead", "admin")) else u
    kind = "team_rollup" if target.role == "ta_lead" else "recruiter"
    d = build(db, target, kind)
    subject, html, text = render(d)
    db.rollback()  # preview must not persist match refreshes etc.
    if format == "text":
        return HTMLResponse(f"<pre style='white-space:pre-wrap;font:13px/1.5 ui-monospace,monospace'>{text.replace('<', '&lt;')}</pre>")
    return HTMLResponse(html)


@router.post("/digest/send-now")
def send_now(user_id: int | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)):
    target = db.get(User, user_id) if (user_id and u.role in ("ta_lead", "admin")) else u
    entry = send_digest(db, target, "team_rollup" if target.role == "ta_lead" else "recruiter", force=True)
    audit(db, "digest.sent_manually", "user", target.id, u.id, {"status": entry.status})
    db.commit()
    return row(entry)


@router.get("/digest/logs")
def digest_logs(db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(DigestLog)
    if u.role not in ("ta_lead", "admin"):
        q = q.filter(DigestLog.user_id == u.id)
    out = []
    for d in q.order_by(DigestLog.created_at.desc()).limit(100).all():
        e = d.email
        out.append({**row(d), "user_name": d.user.name, "opened_at": row(e)["opened_at"] if e else None, "open_count": e.open_count if e else 0, "click_count": e.click_count if e else 0})
    return out


@router.get("/emails")
def emails(kind: str | None = None, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    q = db.query(OutboundEmail)
    if kind:
        q = q.filter(OutboundEmail.kind == kind)
    return [row(e, exclude={"html"}) for e in q.order_by(OutboundEmail.created_at.desc()).limit(200).all()]


# ---------------------------------------------------------------------------
# Integrations & jobs
# ---------------------------------------------------------------------------
@router.get("/integrations")
def integrations(u: User = Depends(current_user)):
    s = get_settings()
    return [
        {"key": "mail", "name": "System email", "status": s.mail_backend, "connected": s.mail_backend != "console", "detail": f"Backend: {s.mail_backend}"},
        {"key": "inbox", "name": "Recruiter mailboxes (Gmail / Microsoft 365)", "status": s.inbox_provider,
         "connected": bool(s.google_client_id or s.ms_client_id), "detail": "Replies are received via push webhook → /api/webhooks/inbound-email"},
        {"key": "ats", "name": "ATS / job boards", "status": "webhook", "connected": True, "detail": "POST /api/webhooks/application and /api/webhooks/requirement"},
        {"key": "linkedin", "name": "LinkedIn", "status": "manual", "connected": True, "detail": "Profile import (CSV/JSON) + manual sending only, per LinkedIn ToS"},
        {"key": "sheets", "name": "Google Sheets / CSV", "status": "import", "connected": True, "detail": "Requirements → Import CSV"},
        {"key": "llm", "name": "AI layer", "status": s.llm_provider, "connected": s.llm_provider != "template" and bool(s.anthropic_api_key), "detail": "Drafts are always human-approved"},
        {"key": "storage", "name": "Document storage", "status": s.storage_backend, "connected": True, "detail": "Encrypted at rest (Fernet + SSE for S3)"},
        {"key": "sso", "name": "Single sign-on", "status": s.auth_mode, "connected": s.auth_mode == "oidc", "detail": s.oidc_issuer or "Dev login enabled"},
    ]


@router.get("/jobs")
def jobs(status: str | None = None, db: Session = Depends(get_db), u: User = Depends(require_roles("ta_lead", "admin"))):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    return [row(j) for j in q.order_by(Job.id.desc()).limit(200).all()]


@router.post("/jobs/run-due")
def run_jobs(db: Session = Depends(get_db), u: User = Depends(require_roles("admin", "ta_lead"))):
    return {"ran": run_due_jobs(db)}
