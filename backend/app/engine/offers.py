"""Offer letters: Onboarding uploads a finished PDF and submits it to an internal approver.

The approver (a TA lead or admin) gets an email with a signed link to a review page where they can
open the PDF and approve or reject it. They can also decide from the candidate's Offer letter tab.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..models import Candidate, Interaction, OfferLetter, User
from ..settings_store import get_setting
from ..storage import get_storage
from ..util import now, sign, unsign
from .documents import ensure_folder

APPROVER_ROLES = ("ta_lead", "admin")
LINK_TTL_DAYS = 14


class OfferError(Exception):
    pass


def approvers(db: Session) -> list[User]:
    return db.query(User).filter(User.role.in_(APPROVER_ROLES), User.is_active.is_(True)).order_by(User.name).all()


def upload(db: Session, c: Candidate, user: User, filename: str, content_type: str, data: bytes, notes: str = "") -> OfferLetter:
    max_mb = float(get_setting(db, "documents.max_file_mb"))
    if content_type != "application/pdf" or not data.startswith(b"%PDF"):
        raise OfferError("Please upload the offer letter as a PDF")
    if len(data) > max_mb * 1024 * 1024:
        raise OfferError(f"File is larger than {max_mb:g} MB")
    if len(data) < 200:
        raise OfferError("File looks empty or unreadable")
    # A new version replaces any earlier letter that hasn't been approved yet.
    for old in db.query(OfferLetter).filter(OfferLetter.candidate_id == c.id, OfferLetter.status.in_(["uploaded", "pending_approval"])).all():
        old.status = "superseded"
    folder = ensure_folder(db, c)
    key = f"{folder.path}/04_Offer/offer_letter_draft-{now():%Y%m%d%H%M%S}.pdf"
    get_storage().put(key, data)
    o = OfferLetter(
        candidate_id=c.id,
        storage_key=key,
        filename=(filename or "offer_letter.pdf")[:250],
        content_type=content_type,
        size_bytes=len(data),
        notes=(notes or "").strip(),
        uploaded_by=user.id,
        uploaded_at=now(),
    )
    db.add(o)
    db.flush()
    db.add(Interaction(candidate_id=c.id, user_id=user.id, type="offer_letter", subject="Offer letter uploaded", body=o.filename, meta={"offer_id": o.id}, occurred_at=now()))
    audit(db, "offer.uploaded", "candidate", c.id, user.id, {"offer_id": o.id, "filename": o.filename})
    db.flush()
    return o


def approval_token(o: OfferLetter) -> str:
    return sign({"t": "offer", "id": o.id, "a": o.approver_id}, ttl_seconds=LINK_TTL_DAYS * 86400)


def from_token(db: Session, token: str) -> OfferLetter | None:
    body = unsign(token)
    if not body or body.get("t") != "offer":
        return None
    o = db.get(OfferLetter, body.get("id"))
    # A token is only valid for the approver it was issued to.
    if o is None or o.approver_id != body.get("a"):
        return None
    return o


def submit(db: Session, o: OfferLetter, user: User, approver_id: int) -> OfferLetter:
    if o.status != "uploaded":
        raise OfferError(f"This offer letter is already {o.status.replace('_', ' ')}")
    approver = db.get(User, approver_id)
    if approver is None or not approver.is_active or approver.role not in APPROVER_ROLES:
        raise OfferError("Choose a TA lead or admin as the approver")
    if approver.id == user.id:
        raise OfferError("You can't approve your own offer letter; choose another approver")
    c = db.get(Candidate, o.candidate_id)
    o.status = "pending_approval"
    o.submitted_by = user.id
    o.submitted_at = now()
    o.approver_id = approver.id
    db.flush()
    _email_approver(db, o, c, user, approver)
    from .notify import notify

    notify(db, f"Offer letter to approve: {c.full_name}", f"{user.name} submitted an offer letter for your approval.", user_ids=[approver.id], link=f"/candidates/{c.id}?tab=offer")
    db.add(Interaction(candidate_id=c.id, user_id=user.id, type="offer_letter", subject=f"Offer letter sent to {approver.name} for approval", meta={"offer_id": o.id}, occurred_at=now()))
    audit(db, "offer.submitted", "candidate", c.id, user.id, {"offer_id": o.id, "approver_id": approver.id})
    db.flush()
    return o


def _email_approver(db: Session, o: OfferLetter, c: Candidate, submitter: User, approver: User) -> None:
    from ..mail import send_email

    s = get_settings()
    review = f"{s.api_url}/api/public/offer-approval/{approval_token(o)}"
    in_app = f"{s.app_url}/candidates/{c.id}?tab=offer"
    notes = f"\nNotes from {submitter.name}:\n{o.notes}\n" if o.notes else ""
    text = (
        f"Hi {approver.name.split(' ')[0]},\n\n"
        f"{submitter.name} has prepared an offer letter for {c.full_name} and needs your approval before it is issued.\n"
        f"{notes}\n"
        f"Review the offer letter and confirm your approval here:\n{review}\n\n"
        f"Or open the candidate in the app:\n{in_app}\n\n"
        f"This link expires in {LINK_TTL_DAYS} days."
    )
    rec = send_email(db, approver.email, f"Approval needed: offer letter for {c.full_name}", text, kind="notification", user_id=approver.id, track=False)
    if rec.status != "sent":
        raise OfferError("The approval email could not be sent: " + (rec.error or "unknown error"))


def decide(db: Session, o: OfferLetter, approve: bool, note: str, user: User | None, via: str) -> OfferLetter:
    if o.status != "pending_approval":
        raise OfferError(f"This offer letter is already {o.status.replace('_', ' ')}")
    if not approve and not (note or "").strip():
        raise OfferError("Please give a reason for rejecting the offer letter")
    approver = db.get(User, o.approver_id)
    actor = user or approver
    o.status = "approved" if approve else "rejected"
    o.decided_at = now()
    o.decision_note = (note or "").strip()
    o.decided_via = via
    c = db.get(Candidate, o.candidate_id)
    verb = "approved" if approve else "rejected"
    db.add(
        Interaction(
            candidate_id=c.id,
            user_id=actor.id if actor else None,
            type="offer_letter",
            subject=f"Offer letter {verb} by {actor.name if actor else 'approver'}",
            body=o.decision_note,
            meta={"offer_id": o.id, "via": via},
            occurred_at=now(),
        )
    )
    audit(db, f"offer.{verb}", "candidate", c.id, actor.id if actor else None, {"offer_id": o.id, "via": via, "note": o.decision_note})
    if o.submitted_by:
        from .notify import notify

        body = f"{actor.name if actor else 'The approver'} {verb} the offer letter for {c.full_name}."
        if o.decision_note:
            body += f"\n\nNote: {o.decision_note}"
        notify(db, f"Offer letter {verb}: {c.full_name}", body, user_ids=[o.submitted_by], link=f"/candidates/{c.id}?tab=offer", kind="success" if approve else "warning", email=True)
    db.flush()
    return o
