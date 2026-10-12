"""Runtime (admin-editable) settings persisted in the `settings` table."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from .constants import DEFAULT_FOLLOW_UP_DAYS
from .models import Setting

DEFAULTS: dict[str, Any] = {
    # Daily digest
    "digest.time": "07:30",  # local time (America/New_York by default)
    "digest.business_days_only": True,
    "digest.when_empty": "note",  # note | skip
    "digest.top_matches": 5,
    "digest.reengagement_min_days": 90,
    # Follow-ups
    "followup.cadence_days": DEFAULT_FOLLOW_UP_DAYS,
    "followup.reminder_time": "07:00",
    # Outreach guardrails
    "outreach.max_per_candidate_7d": 3,
    "outreach.min_hours_between": 48,
    "outreach.sequence_offsets_days": [0, 3, 7],
    # Documents
    "documents.reminder_interval_hours": 48,
    "documents.max_reminders": 3,
    "documents.portal_ttl_days": 14,
    "documents.max_file_mb": 10,
    "documents.expiry_warning_days": 60,
    "documents.sla_hours": 96,  # pending documents past this appear in the digest
    # Retention
    "retention.days_inactive": 730,
    # Weekly report
    "report.weekly_day": "mon",
    "report.weekly_time": "08:00",
    # Matching
    "matching.min_score_suggest": 50,
    "matching.irrelevant_threshold": 40,
    # Authorized domains for sharing candidate data
    "compliance.authorized_domains": ["cognitech.example"],
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return copy.deepcopy(DEFAULTS.get(key))
    return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def all_settings(db: Session) -> dict[str, Any]:
    out = copy.deepcopy(DEFAULTS)
    for row in db.query(Setting).all():
        out[row.key] = row.value
    return out
