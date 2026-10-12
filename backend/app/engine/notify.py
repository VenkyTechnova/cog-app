"""In-app notifications, optionally mirrored to email."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Notification, User


def notify(
    db: Session,
    title: str,
    body: str = "",
    user_ids: list[int] | None = None,
    role: str | None = None,
    link: str | None = None,
    kind: str = "info",
    email: bool = False,
) -> list[Notification]:
    ids = set(user_ids or [])
    if role:
        ids |= {u.id for u in db.query(User).filter(User.role == role, User.is_active.is_(True)).all()}
    out = []
    for uid in ids:
        n = Notification(user_id=uid, title=title, body=body, link=link, kind=kind)
        db.add(n)
        out.append(n)
        if email:
            from ..mail import send_email

            u = db.get(User, uid)
            if u:
                full_link = f"{get_settings().app_url}{link}" if link and link.startswith("/") else link
                send_email(db, u.email, title, f"{body}\n\n{full_link or ''}".strip(), kind="notification", user_id=uid)
    db.flush()
    return out
