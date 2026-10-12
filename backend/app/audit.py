"""Audit logging helper. Every write to candidate data and every sensitive read is logged."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog
from .util import now


def audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    user_id: int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            detail=detail or {},
            ip=ip,
            at=now(),
        )
    )
