"""Inbound integrations: ATS / job boards, client requirement emails, recruiter inbox replies, post engagement.

Authenticate with either header:
  X-Webhook-Secret: <WEBHOOK_SECRET>
  X-Signature: sha256=<hex HMAC-SHA256 of the raw body using WEBHOOK_SECRET>
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..engine.events import emit
from ..engine.intake import create_requirement, handle_inbound_email, receive_application, upsert_candidate

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


async def verify(request: Request):
    secret = get_settings().webhook_secret.encode()
    raw = await request.body()
    sig = request.headers.get("x-signature", "")
    if sig.startswith("sha256="):
        expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig[7:], expected):
            return
    if hmac.compare_digest(request.headers.get("x-webhook-secret", "").encode(), secret):
        return
    raise HTTPException(401, "Invalid webhook signature")


class ApplicationIn(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    resume_text: str | None = None
    skills: list[str] | None = None
    years_experience: float | None = None
    work_authorization: str | None = None
    requirement_id: int | None = None
    source: str = "job_board"


@router.post("/application", dependencies=[Depends(verify)])
def application(body: ApplicationIn, db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    rid = data.pop("requirement_id", None)
    src = data.pop("source", "job_board")
    app = receive_application(db, data, rid, src)
    db.commit()
    return {"application_id": app.id, "candidate_id": app.candidate_id, "fit_score": app.fit_score}


class RequirementHook(BaseModel):
    title: str
    client: str
    skills: list[str] | str = []
    location: str = ""
    work_arrangement: str = "Remote"
    employment_type: str = "Either"
    rate: str = ""
    min_years: int = 0
    priority: str = "Medium"
    description: str = ""


@router.post("/requirement", dependencies=[Depends(verify)])
def requirement(body: RequirementHook, db: Session = Depends(get_db)):
    r = create_requirement(db, {**body.model_dump(), "source": "ats"})
    db.commit()
    return {"requirement_id": r.id}


class InboundEmail(BaseModel):
    from_email: str
    to_email: str = ""
    subject: str = ""
    body: str = ""


@router.post("/inbound-email", dependencies=[Depends(verify)])
def inbound_email(body: InboundEmail, db: Session = Depends(get_db)):
    """Normalised inbound mail. Adapters for Gmail push (Pub/Sub) or Microsoft Graph change
    notifications fetch the message and POST it here; SendGrid Inbound Parse can post directly."""
    res = handle_inbound_email(db, body.from_email, body.subject, body.body, body.to_email)
    db.commit()
    return res


class PostEngagement(BaseModel):
    full_name: str
    linkedin_url: str | None = None
    email: str | None = None
    post_title: str = ""
    comment: str = ""
    owner_id: int | None = None


@router.post("/post-engagement", dependencies=[Depends(verify)])
def post_engagement(body: PostEngagement, db: Session = Depends(get_db)):
    c, created = upsert_candidate(db, {"full_name": body.full_name, "linkedin_url": body.linkedin_url, "email": body.email, "source": "Recruitment Post", "owner_id": body.owner_id})
    emit(db, "post.engagement", candidate_id=c.id, payload={"post_title": body.post_title, "comment": body.comment[:500]})
    db.commit()
    return {"candidate_id": c.id, "created": created}
