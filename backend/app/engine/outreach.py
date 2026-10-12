"""Drafts, approval and sending; cold-email sequences (stop on reply, cap, no repeats)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..audit import audit
from ..models import Candidate, Draft, Interaction, Match, Requirement, Sequence, User
from ..settings_store import get_setting
from ..util import now
from . import compliance
from .ai import generate_draft

OPPORTUNITY_KINDS = {"cold_email", "follow_up", "reengagement", "intro_message", "offer_explainer", "process_summary", "dm", "check_in"}
CHANNEL = {"linkedin_note": "linkedin", "intro_message": "linkedin", "dm": "dm"}


class OutreachError(Exception):
    pass


def create_draft(
    db: Session,
    kind: str,
    candidate: Candidate | None,
    requirement: Requirement | None = None,
    owner: User | None = None,
    extra: dict | None = None,
    sequence: Sequence | None = None,
    step: int | None = None,
    offset_days: int = 0,
) -> Draft:
    owner = owner or (db.get(User, candidate.owner_id) if candidate and candidate.owner_id else None)
    subject, body, gen = generate_draft(db, kind, candidate, requirement, owner, extra)
    if kind in OPPORTUNITY_KINDS and CHANNEL.get(kind, "email") == "email":
        body = compliance.with_disclaimer(body, candidate)
    d = Draft(
        candidate_id=candidate.id if candidate else None,
        requirement_id=requirement.id if requirement else None,
        owner_id=owner.id if owner else None,
        kind=kind,
        channel=CHANNEL.get(kind, "email"),
        subject=subject,
        body=body,
        generated_by=gen,
        sequence_id=sequence.id if sequence else None,
        step=step,
        send_offset_days=offset_days,
    )
    d.compliance = _check(d, candidate)
    if d.compliance["blocked"]:
        d.status = "blocked"
    db.add(d)
    db.flush()
    return d


def _check(d: Draft, candidate: Candidate | None) -> dict:
    res = compliance.scan(f"{d.subject}\n{d.body}", ignore=compliance.OFFER_DISCLAIMER).as_dict()
    res["generic"] = compliance.is_generic(d.body, candidate)
    if d.channel == "linkedin" and d.kind == "linkedin_note":
        lines = [l for l in d.body.splitlines() if l.strip()]
        res["too_long"] = len(lines) > 5
        res["question_count"] = d.body.count("?")
    return res


def update_draft(db: Session, d: Draft, subject: str | None, body: str | None) -> Draft:
    if d.status in ("sent",):
        raise OutreachError("Draft already sent")
    if subject is not None:
        d.subject = subject
    if body is not None:
        d.body = body
    c = db.get(Candidate, d.candidate_id) if d.candidate_id else None
    d.compliance = _check(d, c)
    d.status = "blocked" if d.compliance["blocked"] else "pending_approval"
    db.flush()
    return d


def approve(db: Session, d: Draft, user: User) -> Draft:
    """Approve a draft. Email drafts outside a sequence are sent immediately.

    LinkedIn notes / DMs are never sent by the system (LinkedIn ToS): approval marks them
    ready for the recruiter to copy and send manually.
    """
    c = db.get(Candidate, d.candidate_id) if d.candidate_id else None
    d.compliance = _check(d, c)
    if d.compliance["blocked"]:
        d.status = "blocked"
        compliance.record_flags(db, compliance.scan(f"{d.subject}\n{d.body}", ignore=compliance.OFFER_DISCLAIMER), "draft", d.id, d.candidate_id, user.id)
        db.flush()
        raise OutreachError("Blocked by compliance: " + ", ".join(d.compliance["categories"]) + ". Route this to the right team instead.")
    if d.kind == "linkedin_note" and d.compliance.get("too_long"):
        raise OutreachError("LinkedIn connection notes must be 5 lines or fewer")
    if d.compliance.get("generic"):
        from .habits import raise_habit

        raise_habit(db, "generic_message", user_id=user.id, candidate_id=d.candidate_id, detail=f"Draft #{d.id} has no personal detail", key=f"generic:{d.id}")
    d.status = "approved"
    d.approved_at = now()
    d.approved_by = user.id
    audit(db, "draft.approved", "draft", d.id, user.id, {"kind": d.kind})
    if d.channel != "email":
        d.status = "manual_send"
        db.flush()
        return d
    if d.sequence_id is None and c is not None:
        send_draft(db, d, user)
    db.flush()
    return d


def mark_sent_manually(db: Session, d: Draft, user: User) -> Draft:
    """Recruiter confirms they sent a LinkedIn note / DM themselves."""
    d.status = "sent"
    d.sent_at = now()
    c = db.get(Candidate, d.candidate_id) if d.candidate_id else None
    if c:
        itype = "linkedin_connection" if d.kind == "linkedin_note" else "linkedin_message"
        db.add(Interaction(candidate_id=c.id, user_id=user.id, type=itype, direction="out", subject=d.kind.replace("_", " ").title(), body=d.body))
        c.last_contact_at = now()
        if d.kind == "linkedin_note" and c.linkedin_status == "none":
            c.linkedin_status = "requested"
        from .stages import try_transition

        try_transition(db, c, "contacted", user_id=user.id, trigger="linkedin_sent")
    db.flush()
    return d


def send_draft(db: Session, d: Draft, user: User | None) -> bool:
    from ..mail import send_email
    from .events import emit

    c = db.get(Candidate, d.candidate_id)
    if not c or not c.email:
        raise OutreachError("Candidate has no email address")
    chk = compliance.check_outreach(db, c, d.body)
    if not chk.allowed:
        if "cap" in chk.reason and user:
            from .habits import raise_habit

            raise_habit(db, "excessive_contact", user_id=user.id, candidate_id=c.id, detail=chk.reason, key=f"cap:{c.id}:{now():%Y%W}")
        raise OutreachError(chk.reason)
    rec = send_email(db, c.email, d.subject, d.body, kind="candidate", candidate_id=c.id, user_id=user.id if user else d.owner_id, draft_id=d.id)
    if rec.status != "sent":
        raise OutreachError(rec.error or "Email not sent")
    d.status = "sent"
    d.sent_at = now()
    c.last_contact_at = now()
    db.add(Interaction(candidate_id=c.id, user_id=user.id if user else d.owner_id, type="email_out", direction="out", subject=d.subject, body=d.body, meta={"email_id": rec.id, "draft_id": d.id}))
    if d.requirement_id:
        m = db.query(Match).filter_by(candidate_id=c.id, requirement_id=d.requirement_id).one_or_none()
        if m:
            m.status = "contacted"
            thr = float(get_setting(db, "matching.irrelevant_threshold"))
            if m.score < thr and (user or d.owner_id):
                from .habits import raise_habit

                raise_habit(db, "irrelevant_outreach", user_id=user.id if user else d.owner_id, candidate_id=c.id, detail=f"Match score {m.score:.0f} for requirement #{d.requirement_id}", key=f"irrelevant:{c.id}:{d.requirement_id}")
    db.flush()
    emit(db, "email.sent", candidate_id=c.id, requirement_id=d.requirement_id, user_id=user.id if user else None, payload={"draft_id": d.id, "kind": d.kind})
    return True


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
def create_sequence(db: Session, c: Candidate, req: Requirement | None, owner: User | None) -> Sequence:
    active = db.query(Sequence).filter(Sequence.candidate_id == c.id, Sequence.status.in_(["draft", "active"])).first()
    if active:
        raise OutreachError("This candidate already has an open sequence")
    seq = Sequence(candidate_id=c.id, requirement_id=req.id if req else None, owner_id=owner.id if owner else c.owner_id)
    db.add(seq)
    db.flush()
    offsets = get_setting(db, "outreach.sequence_offsets_days")
    kinds = ["cold_email"] + ["follow_up"] * (len(offsets) - 1)
    for i, (kind, off) in enumerate(zip(kinds, offsets), start=1):
        d = create_draft(db, kind, c, req, owner, sequence=seq, step=i, offset_days=off)
        if i > 2:  # vary later follow-ups so no two messages are identical
            d.body = d.body.replace("Just following up on my note", "One last note from me").replace(
                "If you're open to it, a quick reply with a good time to talk is all I need.",
                "I'll leave it here for now so I don't crowd your inbox — my door is always open.",
            )
            d.subject = f"Last note — {req.title}" if req else "Last note"
    db.flush()
    return seq


def approve_sequence(db: Session, seq: Sequence, user: User) -> Sequence:
    drafts = db.query(Draft).filter_by(sequence_id=seq.id).order_by(Draft.step).all()
    for d in drafts:
        c = db.get(Candidate, d.candidate_id)
        d.compliance = _check(d, c)
        if d.compliance["blocked"]:
            d.status = "blocked"
            db.flush()
            raise OutreachError(f"Step {d.step} is blocked by compliance ({', '.join(d.compliance['categories'])})")
    for d in drafts:
        d.status = "approved"
        d.approved_at = now()
        d.approved_by = user.id
    seq.status = "active"
    seq.current_step = 0
    seq.next_send_at = now()
    audit(db, "sequence.approved", "sequence", seq.id, user.id, {"steps": len(drafts)})
    db.flush()
    return seq


def stop_sequences(db: Session, candidate_id: int, reason: str) -> int:
    n = 0
    for seq in db.query(Sequence).filter(Sequence.candidate_id == candidate_id, Sequence.status.in_(["active", "draft"])).all():
        seq.status = "stopped"
        seq.stop_reason = reason
        seq.next_send_at = None
        for d in db.query(Draft).filter(Draft.sequence_id == seq.id, Draft.status.in_(["approved", "pending_approval"])).all():
            d.status = "rejected"
        n += 1
    db.flush()
    return n


def process_sequences(db: Session) -> dict:
    sent = postponed = stopped = 0
    due = db.query(Sequence).filter(Sequence.status == "active", Sequence.next_send_at <= now()).all()
    for seq in due:
        c = db.get(Candidate, seq.candidate_id)
        if c is None or c.email_opt_out or c.stage in ("not_interested", "placed") or c.merged_into_id:
            stop_sequences(db, seq.candidate_id, "candidate_ineligible")
            stopped += 1
            continue
        nxt = db.query(Draft).filter(Draft.sequence_id == seq.id, Draft.step == seq.current_step + 1).one_or_none()
        if nxt is None:
            seq.status = "completed"
            seq.next_send_at = None
            continue
        owner = db.get(User, seq.owner_id) if seq.owner_id else None
        try:
            send_draft(db, nxt, owner)
            sent += 1
        except OutreachError as e:
            if "identical" in str(e):
                nxt.status = "rejected"
            else:
                seq.next_send_at = now() + timedelta(hours=24)
                postponed += 1
                continue
        seq.current_step += 1
        following = db.query(Draft).filter(Draft.sequence_id == seq.id, Draft.step == seq.current_step + 1).one_or_none()
        if following is None:
            seq.status = "completed"
            seq.next_send_at = None
        else:
            gap = following.send_offset_days - nxt.send_offset_days
            seq.next_send_at = now() + timedelta(days=max(gap, 1))
    db.flush()
    return {"sent": sent, "postponed": postponed, "stopped": stopped}
