"""Unauthenticated endpoints: document portal, e-consent, unsubscribe, digest one-click actions, email tracking.

Every endpoint is authorised by an unguessable token (portal / consent) or an HMAC-signed token.
"""
from __future__ import annotations

import base64
from datetime import date
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import client_ip
from ..engine import documents, followups
from ..engine.events import emit
from ..models import Candidate, ConsentRecord, DocumentItem, DocumentRequest, EmailEvent, Interaction, Match, OutboundEmail, User
from ..settings_store import get_setting
from ..util import aware, now, unsign

router = APIRouter(prefix="/api", tags=["public"])

CONSENT_TEXT = (
    "I confirm that Cognitech Technologies has explained its process to me, that my questions about payroll, tax or work "
    "authorization have been routed to the appropriate team, and that I would like to proceed to the documentation step. "
    "I understand this is not a final employment commitment and that I can withdraw at any time by replying to my recruiter."
)
PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>{title}</title>"
        "<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f3f4f6;margin:0;padding:24px;color:#111827}"
        ".card{max-width:520px;margin:40px auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 1px 3px rgba(0,0,0,.08)}"
        "h1{font-size:20px;margin:0 0 12px;color:#0f3d5e}a{color:#0f3d5e}</style></head>"
        f"<body><div class=card><h1>{title}</h1>{body}</div></body></html>"
    )


# ---------------------------------------------------------------------------
# Document portal (the React app renders /portal/:token and calls these)
# ---------------------------------------------------------------------------
def _portal_request(db: Session, token: str) -> DocumentRequest:
    req = db.query(DocumentRequest).filter_by(token=token).one_or_none()
    if req is None or req.status == "cancelled":
        raise HTTPException(404, "This link is not valid")
    if aware(req.expires_at) < now():
        raise HTTPException(410, "This link has expired. Please ask your recruiter for a new one.")
    return req


@router.get("/public/portal/{token}")
def portal(token: str, db: Session = Depends(get_db)):
    req = _portal_request(db, token)
    c = db.get(Candidate, req.candidate_id)
    owner = db.get(User, c.owner_id) if c.owner_id else None
    return {
        "first_name": c.full_name.split(" ")[0],
        "recruiter": owner.name if owner else "Cognitech Talent Acquisition",
        "status": req.status,
        "expires_at": aware(req.expires_at).isoformat(),
        "max_file_mb": get_setting(db, "documents.max_file_mb"),
        "accepted": ["PDF", "JPG", "PNG", "DOCX (resume only)"],
        "items": [
            {"id": i.id, "label": i.label, "required": i.required, "needs_expiry": i.needs_expiry, "status": i.status,
             "handled_by": i.handled_by, "filename": i.filename, "validation": i.validation, "review_note": i.review_note if i.status == "rejected" else ""}
            for i in req.items
        ],
    }


@router.post("/public/portal/{token}/items/{item_id}")
async def upload(token: str, item_id: int, request: Request, file: UploadFile = File(...), expiry_date: str | None = Form(None), db: Session = Depends(get_db)):
    req = _portal_request(db, token)
    item = db.get(DocumentItem, item_id)
    if item is None or item.request_id != req.id:
        raise HTTPException(404)
    if item.status == "verified":
        raise HTTPException(409, "This document is already verified")
    data = await file.read()
    exp = None
    if expiry_date:
        try:
            exp = date.fromisoformat(expiry_date)
        except ValueError:
            raise HTTPException(422, "Expiry date must be YYYY-MM-DD")
    try:
        result = documents.store_upload(db, item, file.filename or "upload", file.content_type or "", data, exp)
    except documents.DocumentRuleError as e:
        raise HTTPException(410, str(e))
    audit(db, "portal.upload", "document", item.id, None, {"ok": result["ok"]}, client_ip(request))
    db.commit()
    return {"item_id": item.id, "status": item.status, **result, "request_status": req.status}


# ---------------------------------------------------------------------------
# E-consent
# ---------------------------------------------------------------------------
@router.get("/public/consent/{token}")
def consent_get(token: str, db: Session = Depends(get_db)):
    rec = db.query(ConsentRecord).filter_by(token=token).one_or_none()
    if rec is None:
        raise HTTPException(404)
    return {"first_name": rec.candidate.full_name.split(" ")[0], "text": rec.consent_text or CONSENT_TEXT, "status": rec.status, "recorded_at": aware(rec.recorded_at).isoformat() if rec.recorded_at else None}


@router.post("/public/consent/{token}")
def consent_post(token: str, body: dict, request: Request, db: Session = Depends(get_db)):
    rec = db.query(ConsentRecord).filter_by(token=token).one_or_none()
    if rec is None:
        raise HTTPException(404)
    if rec.status != "pending":
        raise HTTPException(409, f"Already {rec.status}")
    granted = bool(body.get("granted"))
    rec.status = "granted" if granted else "declined"
    rec.recorded_at = now()
    rec.ip = client_ip(request)
    rec.user_agent = (request.headers.get("user-agent") or "")[:300]
    c = rec.candidate
    db.add(Interaction(candidate_id=c.id, type="consent", subject=f"Consent {rec.status} (e-consent)", meta={"consent_id": rec.id, "ip": rec.ip}, meaningful=True))
    audit(db, f"consent.{rec.status}", "candidate", c.id, None, {"consent_id": rec.id}, rec.ip)
    db.flush()
    if granted:
        emit(db, "consent.recorded", candidate_id=c.id, payload={"consent_id": rec.id})
    elif c.owner_id:
        from ..engine.notify import notify

        notify(db, f"{c.full_name} declined to proceed", "Consider a no-pressure check-in.", user_ids=[c.owner_id], link=f"/candidates/{c.id}")
    db.commit()
    return {"status": rec.status}


# ---------------------------------------------------------------------------
# Unsubscribe (candidates: outreach emails; staff: daily digest)
# ---------------------------------------------------------------------------
@router.get("/public/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    body = unsign(token)
    if not body:
        return _page("Link not valid", "<p>This unsubscribe link is invalid.</p>")
    if body["k"] == "candidate":
        c = db.get(Candidate, body["id"])
        if c:
            c.email_opt_out = True
            from ..engine.outreach import stop_sequences

            stop_sequences(db, c.id, "unsubscribed")
            audit(db, "candidate.unsubscribed", "candidate", c.id, None, {"via": "link"})
            db.commit()
        return _page("You're unsubscribed", "<p>You won't receive further outreach emails from Cognitech Technologies. If this was a mistake, just reply to your recruiter.</p>")
    if body["k"] == "digest":
        u = db.get(User, body["id"])
        if u:
            u.digest_enabled = False
            audit(db, "digest.unsubscribed", "user", u.id, u.id, {})
            db.commit()
        return _page("Daily digest turned off", f"<p>You can turn it back on any time in <a href='{get_settings().app_url}/settings?tab=digest'>Settings → Digest</a>.</p>")
    return _page("Link not valid", "")


# ---------------------------------------------------------------------------
# Digest one-click actions (snooze / not a fit)
# ---------------------------------------------------------------------------
@router.get("/public/digest-action/{token}")
def digest_action(token: str, db: Session = Depends(get_db)):
    body = unsign(token)
    app = get_settings().app_url
    if not body:
        return _page("Link expired", f"<p>This action link has expired. <a href='{app}'>Open Recruiter Home</a>.</p>")
    c = db.get(Candidate, body["c"])
    u = db.get(User, body["u"])
    if c is None or u is None:
        raise HTTPException(404)
    if body["a"] == "snooze":
        followups.snooze(db, c, 1)
        audit(db, "digest.snooze", "candidate", c.id, u.id, {})
        msg = "snoozed"
    elif body["a"] == "not_fit":
        if body.get("r"):
            m = db.query(Match).filter_by(candidate_id=c.id, requirement_id=body["r"]).one_or_none()
            if m:
                m.status = "not_fit"
        c.hot_reply = False
        db.add(Interaction(candidate_id=c.id, user_id=u.id, type="note", subject="Marked not a fit from daily digest", meta={"requirement_id": body.get("r")}))
        audit(db, "digest.not_fit", "candidate", c.id, u.id, {"requirement_id": body.get("r")})
        msg = "not_fit"
    else:
        raise HTTPException(422)
    db.commit()
    return RedirectResponse(f"{app}/candidates/{c.id}?done={msg}", status_code=303)


# ---------------------------------------------------------------------------
# Email tracking
# ---------------------------------------------------------------------------
@router.get("/t/o/{email_id}.gif")
def track_open(email_id: str, db: Session = Depends(get_db)):
    e = db.get(OutboundEmail, email_id)
    if e:
        e.open_count = (e.open_count or 0) + 1
        e.opened_at = e.opened_at or now()
        db.add(EmailEvent(email_id=email_id, type="open"))
        db.commit()
    return Response(PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@router.get("/t/c/{email_id}")
def track_click(email_id: str, u: str, db: Session = Depends(get_db)):
    url = unquote(u)
    s = get_settings()
    allowed_hosts = {urlparse(s.app_url).netloc, urlparse(s.api_url).netloc}
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc not in allowed_hosts:
        e = db.get(OutboundEmail, email_id)
        if e is None or url not in (e.html or ""):
            raise HTTPException(400, "Unknown link")  # prevents open redirects
    e = db.get(OutboundEmail, email_id)
    if e:
        e.click_count = (e.click_count or 0) + 1
        e.opened_at = e.opened_at or now()
        db.add(EmailEvent(email_id=email_id, type="click", url=url[:2000]))
        db.commit()
    return RedirectResponse(url, status_code=302)
