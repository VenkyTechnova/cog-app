"""The 10-stage candidate state machine, with the playbook's non-negotiable guardrails.

* Event-driven moves follow FORWARD_TRANSITIONS (or go to an outcome stage).
* Manual moves may go anywhere but need a reason, and are audit-logged.
* Hard guardrails apply to every move, manual or not:
  - No stage from Docs Requested onward until the comfort check is complete AND consent is recorded.
  - No Onboarding until every required document is verified.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import (
    ALL_STAGES,
    CONSENT_GATED_STAGES,
    FORWARD_TRANSITIONS,
    OUTCOME_STAGES,
    REQUIRED_FOR_QUALIFIED,
    STAGE_LABELS,
)
from ..models import Candidate, ConsentRecord, DocumentItem, DocumentRequest, Interaction, StageTransition
from ..util import now


class TransitionError(Exception):
    def __init__(self, message: str, code: str = "invalid_transition"):
        super().__init__(message)
        self.code = code


def consent_granted(db: Session, c: Candidate) -> bool:
    return db.query(ConsentRecord).filter_by(candidate_id=c.id, consent_type="proceed", status="granted").first() is not None


def comfort_check_complete(c: Candidate) -> bool:
    return bool((c.comfort_check or {}).get("completed_at")) and bool((c.comfort_check or {}).get("all_yes", True))


def all_docs_verified(db: Session, c: Candidate) -> bool:
    req = db.query(DocumentRequest).filter(DocumentRequest.candidate_id == c.id, DocumentRequest.status != "cancelled").order_by(DocumentRequest.id.desc()).first()
    if req is None:
        return False
    items = db.query(DocumentItem).filter_by(request_id=req.id, required=True).all()
    return bool(items) and all(i.status == "verified" for i in items)


def missing_qualification_fields(c: Candidate) -> list[str]:
    missing = []
    for f in REQUIRED_FOR_QUALIFIED:
        v = getattr(c, f)
        if v in (None, "", []):
            missing.append(f)
    return missing


def check(db: Session, c: Candidate, to: str, manual: bool, reason: str = "") -> None:
    """Raise TransitionError if the move isn't allowed."""
    if to not in ALL_STAGES:
        raise TransitionError(f"Unknown stage '{to}'")
    frm = c.stage
    if to in CONSENT_GATED_STAGES:
        if not comfort_check_complete(c):
            raise TransitionError("The comfort check must be completed before moving to " + STAGE_LABELS[to], "comfort_check_required")
        if not consent_granted(db, c):
            raise TransitionError("Candidate consent must be recorded before moving to " + STAGE_LABELS[to], "consent_required")
    if to == "onboarding" and not all_docs_verified(db, c):
        raise TransitionError("All required documents must be verified before Onboarding", "documents_unverified")
    if manual:
        if not reason or len(reason.strip()) < 3:
            raise TransitionError("A reason is required for manual stage changes", "reason_required")
        if to == "qualified" and missing_qualification_fields(c):
            raise TransitionError("Missing qualification fields: " + ", ".join(missing_qualification_fields(c)), "qualification_incomplete")
        return
    if to in OUTCOME_STAGES:
        return
    if to not in FORWARD_TRANSITIONS.get(frm, []):
        raise TransitionError(f"Cannot move automatically from {STAGE_LABELS.get(frm, frm)} to {STAGE_LABELS[to]}")
    if to == "qualified" and missing_qualification_fields(c):
        raise TransitionError("Missing qualification fields: " + ", ".join(missing_qualification_fields(c)), "qualification_incomplete")


def transition(
    db: Session,
    c: Candidate,
    to: str,
    user_id: int | None = None,
    reason: str = "",
    manual: bool = False,
    trigger: str = "",
    emit_event: bool = True,
) -> StageTransition | None:
    if c.stage == to:
        return None
    try:
        check(db, c, to, manual, reason)
    except TransitionError as e:
        if manual and e.code in ("comfort_check_required", "consent_required") and user_id:
            from .habits import raise_habit

            raise_habit(db, "skipped_consent", user_id=user_id, candidate_id=c.id, detail=str(e), key=f"skipped_consent:{c.id}:{to}")
        raise
    frm = c.stage
    c.stage = to
    t = now()
    st = StageTransition(candidate_id=c.id, from_stage=frm, to_stage=to, reason=reason, manual=manual, trigger=trigger, user_id=user_id, at=t)
    db.add(st)
    db.add(
        Interaction(
            candidate_id=c.id,
            user_id=user_id,
            type="stage_change",
            subject=f"{STAGE_LABELS.get(frm, frm)} → {STAGE_LABELS[to]}",
            body=reason,
            meta={"from": frm, "to": to, "manual": manual, "trigger": trigger},
            occurred_at=t,
        )
    )
    audit(db, "stage.manual_override" if manual else "stage.changed", "candidate", c.id, user_id, {"from": frm, "to": to, "reason": reason, "trigger": trigger})
    db.flush()
    # Follow-up cadence is applied by the `stage_follow_up_cadence` workflow (editable / pausable).
    if emit_event:
        from .events import emit

        emit(db, "stage.changed", candidate_id=c.id, user_id=user_id, payload={"from_stage": frm, "to_stage": to, "manual": manual})
    return st


def try_transition(db: Session, c: Candidate, to: str, **kw) -> StageTransition | None:
    """Event-driven helper: silently ignore moves that aren't valid from the current stage."""
    try:
        return transition(db, c, to, **kw)
    except TransitionError:
        return None
