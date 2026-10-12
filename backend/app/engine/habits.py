"""Monitor for the 13 "habits worth breaking". Violations go to the manager review queue.

Some habits are raised in real time where they happen (compliance language, generic
messages, outreach cap, skipped consent, duplicates, irrelevant outreach, unnecessary
document requests); the nightly sweep covers the time-based ones.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import ACTIVE_STAGES, CONSENT_GATED_STAGES, HABITS
from ..models import Candidate, FollowUp, HabitFlag, Interaction, OutboundEmail
from ..settings_store import get_setting
from ..util import aware, now
from .stages import missing_qualification_fields


def raise_habit(db: Session, habit: str, user_id: int | None, candidate_id: int | None, detail: str, key: str) -> HabitFlag | None:
    if habit not in HABITS:
        raise ValueError(habit)
    if db.query(HabitFlag).filter_by(dedupe_key=key).first():
        return None
    f = HabitFlag(habit=habit, user_id=user_id, candidate_id=candidate_id, detail=detail, dedupe_key=key)
    db.add(f)
    db.flush()
    return f


def run_monitor(db: Session) -> dict:
    t = now()
    counts = {h: 0 for h in HABITS}

    # Missed follow-ups: open and overdue by > 2 days.
    for f in db.query(FollowUp).filter(FollowUp.status == "open", FollowUp.due_at < t - timedelta(days=2)).all():
        if raise_habit(db, "missed_follow_up", f.owner_id, f.candidate_id, f"Follow-up '{f.reason}' overdue since {aware(f.due_at):%b %d}", f"missed:{f.id}"):
            counts["missed_follow_up"] += 1

    # Stale records: active stage, no interaction in 30 days.
    last = dict(db.query(Interaction.candidate_id, func.max(Interaction.occurred_at)).group_by(Interaction.candidate_id).all())
    for c in db.query(Candidate).filter(Candidate.stage.in_(ACTIVE_STAGES), Candidate.merged_into_id.is_(None), Candidate.purged.is_(False)).all():
        la = aware(last.get(c.id)) or aware(c.created_at)
        if la and la < t - timedelta(days=30) and c.stage != "sourced":
            if raise_habit(db, "stale_record", c.owner_id, c.id, f"No activity since {la:%b %d}", f"stale:{c.id}:{t:%Y%m}"):
                counts["stale_record"] += 1
        # Incomplete records: qualified or later but missing required fields.
        if c.stage in ["qualified", "process_explained", *CONSENT_GATED_STAGES]:
            missing = missing_qualification_fields(c)
            if missing and raise_habit(db, "incomplete_record", c.owner_id, c.id, "Missing: " + ", ".join(missing), f"incomplete:{c.id}:{','.join(missing)}"):
                counts["incomplete_record"] += 1

    # Excessive contact: more than 6 logged call attempts in 7 days.
    rows = (
        db.query(Interaction.candidate_id, Interaction.user_id, func.count(Interaction.id))
        .filter(Interaction.type == "call", Interaction.occurred_at >= t - timedelta(days=7))
        .group_by(Interaction.candidate_id, Interaction.user_id)
        .all()
    )
    for cid, uid, n in rows:
        if n > 6 and raise_habit(db, "excessive_contact", uid, cid, f"{n} calls in 7 days", f"calls:{cid}:{t:%Y%W}"):
            counts["excessive_contact"] += 1

    # Oversharing: candidate documents emailed outside authorized domains.
    domains = [d.lower() for d in get_setting(db, "compliance.authorized_domains")]
    for e in db.query(OutboundEmail).filter(OutboundEmail.created_at >= t - timedelta(days=1), OutboundEmail.kind != "candidate").all():
        if e.attachments and e.candidate_id and e.to_email.split("@")[-1].lower() not in domains:
            if raise_habit(db, "oversharing_data", e.user_id, e.candidate_id, f"Attachment sent to {e.to_email}", f"overshare:{e.id}"):
                counts["oversharing_data"] += 1
    db.flush()
    return counts
