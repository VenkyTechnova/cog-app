"""Rule-based document checklists, the secure upload portal, validation, reminders and verification.

The checklist is built only from rules (work authorization + employment type). There is no
free-form document request, so recruiters can't collect documents that aren't needed.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..models import Candidate, CandidateFolder, DocumentItem, DocumentRequest, Interaction, User
from ..settings_store import get_setting
from ..storage import get_storage
from ..util import aware, now, slugify, to_local

FOLDERS = ["01_Resume", "02_Identity", "03_Work_Authorization", "04_Offer", "05_Payroll", "06_Correspondence"]
FOLDER_ACL = ["recruiter:owner", "onboarding", "ta_lead", "admin"]

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# doc_type: (label, folder, needs_expiry, handled_by)
DOC_TYPES = {
    "resume": ("Updated resume", "01_Resume", False, None),
    "photo_id": ("Government-issued photo ID (driver's license or state ID)", "02_Identity", True, None),
    "passport": ("Passport (photo page)", "02_Identity", True, None),
    "green_card": ("Permanent resident card (front and back)", "03_Work_Authorization", True, None),
    "ead_card": ("EAD card (front and back)", "03_Work_Authorization", True, None),
    "work_permit_notice": ("Current approval notice", "03_Work_Authorization", True, None),
    "travel_record": ("Most recent arrival/departure record", "03_Work_Authorization", False, None),
    "training_plan": ("Training plan form — coordinated with our authorized team", "03_Work_Authorization", False, "immigration"),
    "tn_letter": ("Current TN approval document", "03_Work_Authorization", True, None),
    "offer_letter": ("Signed offer letter", "04_Offer", False, None),
    "w4": ("Federal withholding form (W-4)", "05_Payroll", False, None),
    "direct_deposit": ("Direct deposit form", "05_Payroll", False, None),
    "w9": ("W-9 for your company", "05_Payroll", False, None),
    "vendor_agreement": ("Signed vendor agreement (MSA)", "05_Payroll", False, None),
    "coi": ("Certificate of insurance", "05_Payroll", True, None),
}

WORK_AUTH_DOCS = {
    "US Citizen": ["photo_id"],
    "Green Card": ["photo_id", "green_card"],
    "GC EAD": ["photo_id", "ead_card"],
    "H-1B": ["passport", "work_permit_notice", "travel_record"],
    "H-4 EAD": ["passport", "ead_card"],
    "L-2 EAD": ["passport", "ead_card"],
    "OPT EAD": ["passport", "ead_card"],
    "STEM OPT EAD": ["passport", "ead_card", "training_plan"],
    "TN": ["passport", "tn_letter", "travel_record"],
}

TYPE_DOCS = {"W-2": ["w4", "direct_deposit"], "C2C": ["w9", "vendor_agreement", "coi"]}


class DocumentRuleError(Exception):
    pass


def build_checklist(c: Candidate) -> list[str]:
    if not c.work_authorization:
        raise DocumentRuleError("Work authorization must be captured before requesting documents")
    if c.preferred_type not in ("W-2", "C2C"):
        raise DocumentRuleError("Confirm W-2 or C2C before requesting documents (payroll forms depend on it)")
    docs = ["resume"]
    docs += WORK_AUTH_DOCS.get(c.work_authorization, ["passport"])
    docs += ["offer_letter"]
    docs += TYPE_DOCS[c.preferred_type]
    seen, out = set(), []
    for d in docs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def ensure_folder(db: Session, c: Candidate) -> CandidateFolder:
    f = db.query(CandidateFolder).filter_by(candidate_id=c.id).one_or_none()
    if f:
        return f
    path = f"candidates/{c.id:06d}-{slugify(c.full_name)}"
    get_storage().makedirs(path, FOLDERS)
    f = CandidateFolder(candidate_id=c.id, path=path, subfolders=FOLDERS, acl=FOLDER_ACL)
    db.add(f)
    audit(db, "folder.created", "candidate", c.id, None, {"path": path})
    db.flush()
    return f


def portal_url(req: DocumentRequest) -> str:
    return f"{get_settings().app_url}/portal/{req.token}"


def active_request(db: Session, c: Candidate) -> DocumentRequest | None:
    return (
        db.query(DocumentRequest)
        .filter(DocumentRequest.candidate_id == c.id, DocumentRequest.status.in_(["open", "complete", "verified"]))
        .order_by(DocumentRequest.id.desc())
        .first()
    )


def create_request(db: Session, c: Candidate, user_id: int | None = None, send: bool = True) -> DocumentRequest:
    existing = active_request(db, c)
    if existing and existing.status == "open":
        return existing
    docs = build_checklist(c)
    ensure_folder(db, c)
    ttl = int(get_setting(db, "documents.portal_ttl_days"))
    req = DocumentRequest(candidate_id=c.id, expires_at=now() + timedelta(days=ttl))
    db.add(req)
    db.flush()
    for d in docs:
        label, folder, exp, handled = DOC_TYPES[d]
        db.add(DocumentItem(request_id=req.id, candidate_id=c.id, doc_type=d, label=label, folder=folder, needs_expiry=exp, handled_by=handled, required=True))
    db.flush()
    audit(db, "documents.requested", "candidate", c.id, user_id, {"docs": docs})
    if send:
        send_request_email(db, c, req, "doc_request")
    return req


def _checklist_text(items: list[DocumentItem]) -> str:
    return "\n".join(f"• {i.label}" for i in items)


def send_request_email(db: Session, c: Candidate, req: DocumentRequest, template: str) -> bool:
    from ..mail import send_email
    from .ai import generate_draft

    if not c.email or c.email_opt_out:
        return False
    items = [i for i in req.items if i.required and i.status in ("missing", "rejected")] if template == "doc_reminder" else list(req.items)
    checklist = _checklist_text(items)
    recruiter = db.get(User, c.owner_id) if c.owner_id else None
    subject, body, _ = generate_draft(
        db, template, c, None, recruiter, {"checklist": checklist, "portal_link": portal_url(req), "portal_expiry": f"{to_local(aware(req.expires_at)):%B %d, %Y}"}
    )
    # The checklist labels come from rule config, not free text, so they're a trusted fragment.
    rec = send_email(db, c.email, subject, body, kind="candidate", candidate_id=c.id, trusted_fragments=[checklist])
    db.add(Interaction(candidate_id=c.id, type="email_out", direction="out", subject=subject, body=body, meta={"email_id": rec.id, "auto": True, "template": template, "status": rec.status}))
    c.last_contact_at = now()
    db.flush()
    return rec.status == "sent"


# ---------------------------------------------------------------------------
# Upload + validation
# ---------------------------------------------------------------------------
def validate_upload(db: Session, item: DocumentItem, filename: str, content_type: str, size: int, expiry: date | None) -> dict:
    errors, warnings = [], []
    max_mb = float(get_setting(db, "documents.max_file_mb"))
    if content_type not in ALLOWED_TYPES:
        errors.append("File type not accepted (PDF, JPG, PNG or DOCX only)")
    elif item.doc_type != "resume" and ALLOWED_TYPES[content_type] == "docx":
        errors.append("Please upload a PDF or image for this document")
    if size > max_mb * 1024 * 1024:
        errors.append(f"File is larger than {max_mb:g} MB")
    if size < 1024:
        errors.append("File looks empty or unreadable")
    if item.needs_expiry:
        if not expiry:
            errors.append("Please enter the document's expiry date")
        else:
            today = to_local(now()).date()
            if expiry <= today:
                errors.append("This document has expired")
            elif expiry <= today + timedelta(days=int(get_setting(db, "documents.expiry_warning_days"))):
                warnings.append(f"Expires soon ({expiry:%b %d, %Y})")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def store_upload(db: Session, item: DocumentItem, filename: str, content_type: str, data: bytes, expiry: date | None) -> dict:
    req = db.get(DocumentRequest, item.request_id)
    if req.status == "cancelled" or aware(req.expires_at) < now():
        raise DocumentRuleError("This upload link has expired. Please ask your recruiter for a new one.")
    result = validate_upload(db, item, filename, content_type, len(data), expiry)
    if not result["ok"]:
        item.status = "rejected" if item.status != "verified" else item.status
        item.validation = result
        db.flush()
        return result
    folder = ensure_folder(db, db.get(Candidate, item.candidate_id))
    ext = ALLOWED_TYPES[content_type]
    key = f"{folder.path}/{item.folder}/{item.doc_type}-{now():%Y%m%d%H%M%S}.{ext}"
    get_storage().put(key, data)
    item.storage_key = key
    item.filename = filename[:250]
    item.content_type = content_type
    item.size_bytes = len(data)
    item.expiry_date = expiry
    item.status = "uploaded"
    item.uploaded_at = now()
    item.validation = result
    db.add(Interaction(candidate_id=item.candidate_id, type="document", subject=f"Uploaded: {item.label}", meta={"item_id": item.id}))
    audit(db, "document.uploaded", "document", item.id, None, {"candidate_id": item.candidate_id, "doc_type": item.doc_type})
    db.flush()
    from .events import emit

    emit(db, "document.uploaded", candidate_id=item.candidate_id, payload={"item_id": item.id, "doc_type": item.doc_type})
    check_complete(db, req)
    return result


def check_complete(db: Session, req: DocumentRequest) -> bool:
    required = [i for i in req.items if i.required]
    if req.status == "open" and required and all(i.status in ("uploaded", "verified") for i in required):
        req.status = "complete"
        req.completed_at = now()
        db.flush()
        from .events import emit

        emit(db, "documents.complete", candidate_id=req.candidate_id, payload={"request_id": req.id})
        return True
    return False


def verify_item(db: Session, item: DocumentItem, user_id: int, approve: bool, note: str = "") -> DocumentItem:
    if item.status not in ("uploaded", "verified", "rejected"):
        raise DocumentRuleError("Nothing uploaded to verify yet")
    item.status = "verified" if approve else "rejected"
    item.verified_by = user_id if approve else None
    item.verified_at = now() if approve else None
    item.review_note = note
    audit(db, "document.verified" if approve else "document.rejected", "document", item.id, user_id, {"note": note})
    req = db.get(DocumentRequest, item.request_id)
    if not approve and req.status == "complete":
        req.status = "open"
    db.flush()
    from .events import emit

    emit(db, "document.verified", candidate_id=item.candidate_id, user_id=user_id, payload={"item_id": item.id, "approved": approve})
    required = [i for i in req.items if i.required]
    if approve and all(i.status == "verified" for i in required):
        req.status = "verified"
        db.flush()
        emit(db, "documents.verified", candidate_id=item.candidate_id, user_id=user_id, payload={"request_id": req.id})
    return item


def reminder_due(db: Session, req: DocumentRequest) -> bool:
    interval = int(get_setting(db, "documents.reminder_interval_hours"))
    last = aware(req.last_reminder_at) or aware(req.created_at)
    return req.status == "open" and now() - last >= timedelta(hours=interval)


def process_reminders(db: Session) -> dict:
    """Every 48h until complete, up to 3 reminders, then escalate to the recruiter."""
    from .notify import notify

    max_rem = int(get_setting(db, "documents.max_reminders"))
    sent = escalated = 0
    for req in db.query(DocumentRequest).filter(DocumentRequest.status == "open").all():
        if not reminder_due(db, req):
            continue
        c = db.get(Candidate, req.candidate_id)
        if req.reminders_sent < max_rem:
            if send_request_email(db, c, req, "doc_reminder"):
                req.reminders_sent += 1
                req.last_reminder_at = now()
                sent += 1
        elif not req.escalated:
            req.escalated = True
            req.last_reminder_at = now()
            missing = [i.label for i in req.items if i.required and i.status in ("missing", "rejected")]
            if c.owner_id:
                notify(
                    db,
                    f"Documents still missing: {c.full_name}",
                    f"{max_rem} reminders sent. Missing: {', '.join(missing)}. A personal call may help.",
                    user_ids=[c.owner_id],
                    link=f"/candidates/{c.id}",
                    kind="escalation",
                    email=True,
                )
            escalated += 1
    db.flush()
    return {"reminders_sent": sent, "escalated": escalated}
