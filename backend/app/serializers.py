"""Model → JSON helpers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.inspection import inspect

from .constants import STAGE_LABELS
from .util import aware


def _val(v: Any) -> Any:
    if isinstance(v, datetime):
        return aware(v).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def row(obj, exclude: set[str] | None = None) -> dict:
    if obj is None:
        return None  # type: ignore[return-value]
    ex = exclude or set()
    return {c.key: _val(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs if c.key not in ex}


def user(u) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_active": u.is_active, "digest_enabled": u.digest_enabled, "digest_prefs": u.digest_prefs or {}} if u else None


def candidate_card(c) -> dict:
    return {
        "id": c.id,
        "full_name": c.full_name,
        "headline": c.headline,
        "skills": c.skills or [],
        "location": c.location,
        "stage": c.stage,
        "stage_label": STAGE_LABELS.get(c.stage, c.stage),
        "owner_id": c.owner_id,
        "fit_score": c.fit_score,
        "source": c.source,
        "hot_reply": c.hot_reply,
        "email": c.email,
        "phone": c.phone,
        "work_authorization": c.work_authorization,
        "preferred_type": c.preferred_type,
        "last_contact_at": _val(c.last_contact_at),
        "next_follow_up_at": _val(c.next_follow_up_at),
        "created_at": _val(c.created_at),
    }


def candidate_full(c) -> dict:
    d = row(c, exclude={"resume_text"})
    d["stage_label"] = STAGE_LABELS.get(c.stage, c.stage)
    return d
