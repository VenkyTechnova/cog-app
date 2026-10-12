"""Renders and sends daily digests; logs delivery; honours preferences and the empty-digest rule."""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from ..config import get_settings
from ..mail import send_email, unsubscribe_url
from ..models import DigestLog, User
from ..settings_store import get_setting
from ..util import first_name, local_today, to_local
from .builder import Digest, build

log = logging.getLogger(__name__)

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html", "j2"], default_for_string=False),
    trim_blocks=True,
    lstrip_blocks=True,
)
_text_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent / "templates")), autoescape=False, trim_blocks=True, lstrip_blocks=True)


def render(d: Digest) -> tuple[str, str, str]:
    s = get_settings()
    c = d.counts
    title = "Team Opportunities Rollup" if d.kind == "team_rollup" else "New Opportunities"
    n_new = c["new_requirements"] + c["applicants"] + c["hot_replies"]
    subject = (
        f"{title}: {c['new_requirements']} new reqs, {c['applicants']} applicants, {c['hot_replies']} hot replies"
        if not d.is_empty
        else f"{title}: nothing new today"
    )
    summary = [
        ("New reqs", c["new_requirements"], "#0f3d5e"),
        ("Applicants", c["applicants"], "#0e7490"),
        ("Hot replies", c["hot_replies"], "#b91c1c"),
        ("Follow-ups", c["follow_ups_today"] + c["follow_ups_overdue"], "#7c3aed"),
        ("Docs past SLA", c["pending_documents"], "#b45309"),
    ]
    ctx = {
        "d": d,
        "subject": subject,
        "title": title,
        "first_name": first_name(d.user.name),
        "date_label": f"{to_local(d.generated_at):%A, %B %d}",
        "since_label": f"{to_local(d.since):%a %b %d, %I:%M %p}",
        "sent_label": f"{to_local(d.generated_at):%I:%M %p %Z}",
        "summary": summary,
        "preheader": f"{n_new} new opportunities · {c['follow_ups_today']} follow-ups today · {c['follow_ups_overdue']} overdue",
        "app_url": s.app_url,
        "prefs_url": f"{s.app_url}/settings?tab=digest",
        "unsubscribe_url": unsubscribe_url("digest", d.user.id),
    }
    html = _env.get_template("digest.html.j2").render(**ctx)
    text = _text_env.get_template("digest.txt.j2").render(**ctx)
    return subject, html, text


def send_digest(db: Session, user: User, kind: str = "recruiter", force: bool = False) -> DigestLog:
    today = local_today()
    if not force:
        existing = db.query(DigestLog).filter_by(user_id=user.id, digest_date=today, kind=kind).filter(DigestLog.status.in_(["sent", "empty_note"])).first()
        if existing:
            return existing
    d = build(db, user, kind)
    when_empty = get_setting(db, "digest.when_empty")
    if d.is_empty and when_empty == "skip":
        entry = DigestLog(user_id=user.id, digest_date=today, kind=kind, status="skipped", counts=d.counts)
        db.add(entry)
        db.flush()
        return entry
    subject, html, text = render(d)
    rec = send_email(db, user.email, subject, text, html=html, kind="digest", user_id=user.id, unsubscribe=unsubscribe_url("digest", user.id))
    status = "failed" if rec.status != "sent" else ("empty_note" if d.is_empty else "sent")
    entry = DigestLog(user_id=user.id, digest_date=today, kind=kind, status=status, counts=d.counts, email_id=rec.id)
    db.add(entry)
    db.flush()
    return entry


def send_all_digests(db: Session) -> dict:
    out = {"sent": 0, "skipped": 0, "failed": 0, "empty_note": 0, "disabled": 0}
    for u in db.query(User).filter(User.is_active.is_(True), User.role.in_(["recruiter", "ta_lead"])).order_by(User.id).all():
        if not u.digest_enabled:
            out["disabled"] += 1
            continue
        kind = "team_rollup" if u.role == "ta_lead" else "recruiter"
        try:
            entry = send_digest(db, u, kind)
            out[entry.status] = out.get(entry.status, 0) + 1
        except Exception:
            log.exception("Digest failed for %s", u.email)
            out["failed"] += 1
    db.flush()
    return out
