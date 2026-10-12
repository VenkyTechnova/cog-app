"""Outbound email with delivery logging, open/click tracking and unsubscribe links.

Every email is written to `outbound_emails` first (the delivery log), then handed to the
configured transport: console (dev), SMTP (e.g. Mailhog / Microsoft 365 relay), SendGrid or SES.
Candidate-facing mail passes a final compliance gate here, regardless of the caller.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import OFFER_DISCLAIMER
from .models import OutboundEmail
from .util import body_hash, now, sign

log = logging.getLogger(__name__)


def text_to_html(text: str) -> str:
    esc = html_lib.escape(text or "")
    esc = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', esc)
    paras = "".join(f"<p style=\"margin:0 0 12px\">{p.replace(chr(10), '<br>')}</p>" for p in esc.split("\n\n"))
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;'
        f'line-height:1.5;color:#1f2937;max-width:600px">{paras}</div>'
    )


def unsubscribe_url(kind: str, ident: int) -> str:
    token = sign({"k": kind, "id": ident})
    return f"{get_settings().api_url}/api/public/unsubscribe/{token}"


def _instrument(html: str, email_id: str) -> str:
    api = get_settings().api_url

    def wrap(m):
        url = m.group(1)
        if "/api/public/unsubscribe/" in url or "/api/t/" in url:
            return m.group(0)
        return f'href="{api}/api/t/c/{email_id}?u={quote(url, safe="")}"'

    html = re.sub(r'href="([^"]+)"', wrap, html)
    pixel = f'<img src="{api}/api/t/o/{email_id}.gif" width="1" height="1" alt="" style="display:none">'
    return html + pixel


def send_email(
    db: Session,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    kind: str = "system",
    candidate_id: int | None = None,
    user_id: int | None = None,
    draft_id: int | None = None,
    track: bool = True,
    trusted_fragments: list[str] | None = None,
    attachments: list[dict] | None = None,
    unsubscribe: str | None = None,
) -> OutboundEmail:
    rec = OutboundEmail(
        to_email=to,
        subject=subject,
        text=text,
        html="",
        kind=kind,
        candidate_id=candidate_id,
        user_id=user_id,
        draft_id=draft_id,
        body_hash=body_hash(text),
        attachments=[{"filename": a["filename"], "content_type": a.get("content_type")} for a in attachments or []],
    )
    db.add(rec)
    db.flush()

    if kind == "candidate":
        from .engine.compliance import record_flags, scan

        body_to_scan = subject + "\n" + text
        for frag in [OFFER_DISCLAIMER, *(trusted_fragments or [])]:
            body_to_scan = body_to_scan.replace(frag, "")
        result = scan(body_to_scan)
        if result.blocked:
            rec.status = "blocked"
            rec.error = "Compliance: " + ", ".join(result.categories)
            record_flags(db, result, "email", rec.id, candidate_id, user_id)
            log.warning("Blocked candidate email %s: %s", rec.id, rec.error)
            return rec
        if unsubscribe is None and candidate_id:
            unsubscribe = unsubscribe_url("candidate", candidate_id)

    if unsubscribe:
        text = f"{text}\n\n—\nTo stop receiving these emails: {unsubscribe}"
        rec.text = text
    body_html = html or text_to_html(text)
    if unsubscribe and html:
        body_html += f'<p style="font-size:12px;color:#6b7280">Don\'t want these emails? <a href="{unsubscribe}">Unsubscribe or change preferences</a>.</p>'
    rec.html = _instrument(body_html, rec.id) if track else body_html

    try:
        rec.provider_message_id = _transport(to, subject, rec.text, rec.html, attachments or [], unsubscribe)
        rec.status = "sent"
        rec.sent_at = now()
    except Exception as exc:  # delivery failures are logged, and the job queue may retry
        rec.status = "failed"
        rec.error = str(exc)[:1000]
        log.exception("Email delivery failed")
    db.flush()
    return rec


def _transport(to: str, subject: str, text: str, html: str, attachments: list[dict], unsubscribe: str | None) -> str | None:
    s = get_settings()
    backend = s.mail_backend
    if backend == "console":
        log.info("EMAIL → %s | %s\n%s", to, subject, text[:500])
        return "console"
    if backend == "smtp":
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.mail_from, to, subject
        if unsubscribe:
            msg["List-Unsubscribe"] = f"<{unsubscribe}>"
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        for a in attachments:
            maintype, subtype = (a.get("content_type") or "application/octet-stream").split("/", 1)
            msg.add_attachment(a["content"], maintype=maintype, subtype=subtype, filename=a["filename"])
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_tls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return "smtp"
    if backend == "sendgrid":
        import base64

        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": re.search(r"<(.+)>", s.mail_from).group(1) if "<" in s.mail_from else s.mail_from},
            "subject": subject,
            "content": [{"type": "text/plain", "value": text}, {"type": "text/html", "value": html}],
            "tracking_settings": {"click_tracking": {"enable": False}, "open_tracking": {"enable": False}},
        }
        if attachments:
            payload["attachments"] = [
                {"content": base64.b64encode(a["content"]).decode(), "filename": a["filename"], "type": a.get("content_type")} for a in attachments
            ]
        if unsubscribe:
            payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe}>"}
        r = httpx.post(
            "https://api.sendgrid.com/v3/mail/send", json=payload, headers={"Authorization": f"Bearer {s.sendgrid_api_key}"}, timeout=20
        )
        r.raise_for_status()
        return r.headers.get("X-Message-Id")
    if backend == "ses":
        import boto3  # optional dependency

        client = boto3.client("sesv2", region_name=s.aws_region)
        r = client.send_email(
            FromEmailAddress=s.mail_from,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": text}, "Html": {"Data": html}}}},
        )
        return r.get("MessageId")
    raise ValueError(f"Unknown MAIL_BACKEND {backend}")
