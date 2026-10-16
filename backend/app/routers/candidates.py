"""Candidates: list, create/import, Candidate 360, calls, qualification, process, consent, documents, drafts."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import (
    ALL_STAGES,
    COLD_CALL_CHECKPOINTS,
    COMFORT_CHECK_QUESTIONS,
    COMPANY_PROCESS_ITEMS,
    DATABASE_FIELDS,
    FIRST_CONVERSATION_TOPICS,
    OFFER_DISCLAIMER,
    QUALIFICATION_FIELDS,
    REQUIRED_FOR_QUALIFIED,
    STAGE_LABELS,
    STAGES,
    TEAMS,
    W2_C2C_TALKING_POINTS,
)
from ..db import get_db
from ..deps import client_ip, current_user, get_candidate_for, require_roles
from ..engine import ai, compliance, dedupe, documents, followups, matching, offers, outreach, stages, tickets
from ..engine.events import emit
from ..engine.intake import upsert_candidate
from ..models import (
    Application,
    Candidate,
    CandidateFolder,
    ConsentRecord,
    DocumentItem,
    DocumentRequest,
    Draft,
    DuplicatePair,
    FollowUp,
    Interaction,
    Match,
    OfferLetter,
    Requirement,
    Sequence,
    StageTransition,
    Ticket,
    User,
)
from ..serializers import candidate_card, candidate_full, row
from ..storage import get_storage
from ..util import now

router = APIRouter(prefix="/api/candidates", tags=["candidates"])
dup_router = APIRouter(prefix="/api/duplicates", tags=["candidates"])
STAFF = ("recruiter", "ta_lead", "coordinator")


# ---------------------------------------------------------------------------
# Listing & creation
# ---------------------------------------------------------------------------
@router.get("")
def list_candidates(
    stage: str | None = None,
    owner_id: int | None = None,
    q: str | None = None,
    source: str | None = None,
    hot: bool | None = None,
    mine: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
    u: User = Depends(require_roles(*STAFF)),
):
    qry = db.query(Candidate).filter(Candidate.merged_into_id.is_(None), Candidate.purged.is_(False))
    if stage:
        qry = qry.filter(Candidate.stage.in_(stage.split(",")))
    if owner_id:
        qry = qry.filter(Candidate.owner_id == owner_id)
    if mine:
        qry = qry.filter(Candidate.owner_id == u.id)
    if source:
        qry = qry.filter(Candidate.source == source)
    if hot is not None:
        qry = qry.filter(Candidate.hot_reply.is_(hot))
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func

        qry = qry.filter(or_(func.lower(Candidate.full_name).like(like), func.lower(Candidate.email).like(like), func.lower(Candidate.headline).like(like), Candidate.phone.like(like)))
    rows = qry.order_by(Candidate.updated_at.desc()).limit(min(limit, 1000)).all()
    return [candidate_card(c) for c in rows]


class CandidateIn(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    source: str | None = None
    skills: list[str] | str | None = None
    years_experience: float | None = None
    current_project_status: str | None = None
    work_authorization: str | None = None
    availability: str | None = None
    preferred_type: str | None = None
    expected_compensation: str | None = None
    work_arrangement: str | None = None
    owner_id: int | None = None
    past_projects: str | None = None
    interview_status: str | None = None
    career_goals: str | None = None
    headline: str | None = None
    summary: str | None = None
    university: str | None = None
    degree: str | None = None
    grad_year: int | None = None
    resume_text: str | None = None


@router.post("")
def create_candidate(body: CandidateIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    data = body.model_dump(exclude_none=True)
    if data.get("resume_text"):
        parsed = ai.parse_resume(data["resume_text"])
        data = {**parsed, **data}
    if not data.get("full_name"):
        raise HTTPException(422, "full_name is required")
    data.setdefault("owner_id", u.id)
    data.setdefault("source", "Other")
    c, created = upsert_candidate(db, data, u.id)
    db.commit()
    return {"candidate": candidate_card(c), "created": created, "deduplicated": not created}


@router.post("/import")
async def import_profiles(file: UploadFile = File(...), db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    """Import LinkedIn profiles exported by the recruiter (CSV or JSON). Nothing is scraped or sent."""
    raw = (await file.read()).decode("utf-8-sig")
    records = json.loads(raw) if file.filename.endswith(".json") else list(csv.DictReader(io.StringIO(raw)))
    created = updated = 0
    for rec in records:
        rec = {k.strip().lower().replace(" ", "_"): v for k, v in rec.items() if k}
        rec.setdefault("source", "LinkedIn")
        rec.setdefault("owner_id", u.id)
        if rec.get("years_experience"):
            try:
                rec["years_experience"] = float(rec["years_experience"])
            except ValueError:
                rec.pop("years_experience")
        if rec.get("grad_year"):
            try:
                rec["grad_year"] = int(rec["grad_year"])
            except ValueError:
                rec.pop("grad_year")
        _, was_created = upsert_candidate(db, rec, u.id, event="candidate.imported")
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated_existing": updated}


@router.post("/parse-resume")
def parse_resume(body: dict, u: User = Depends(require_roles(*STAFF))):
    return ai.parse_resume(body.get("text", ""))


# ---------------------------------------------------------------------------
# Candidate 360
# ---------------------------------------------------------------------------
@router.get("/meta")
def meta(u: User = Depends(current_user)):
    return {
        "stages": STAGES,
        "all_stages": ALL_STAGES,
        "stage_labels": STAGE_LABELS,
        "database_fields": DATABASE_FIELDS,
        "qualification_fields": QUALIFICATION_FIELDS,
        "required_for_qualified": REQUIRED_FOR_QUALIFIED,
        "cold_call_checkpoints": COLD_CALL_CHECKPOINTS,
        "first_conversation_topics": FIRST_CONVERSATION_TOPICS,
        "w2_c2c_talking_points": W2_C2C_TALKING_POINTS,
        "company_process": COMPANY_PROCESS_ITEMS,
        "comfort_check_questions": COMFORT_CHECK_QUESTIONS,
        "teams": {k: v["label"] for k, v in TEAMS.items()},
        "offer_disclaimer": OFFER_DISCLAIMER,
    }


@router.get("/{cid}")
def get_360(cid: int, request: Request, db: Session = Depends(get_db), u: User = Depends(current_user)):
    c = get_candidate_for(db, u, cid)
    audit(db, "candidate.viewed", "candidate", cid, u.id, {}, client_ip(request))
    matches = db.query(Match).join(Requirement).filter(Match.candidate_id == cid, Requirement.status == "open").order_by(Match.score.desc()).all()
    best_req = matches[0].requirement if matches else None
    req = documents.active_request(db, c)
    consent = db.query(ConsentRecord).filter_by(candidate_id=cid).order_by(ConsentRecord.id.desc()).all()
    folder = db.query(CandidateFolder).filter_by(candidate_id=cid).one_or_none()
    timeline = db.query(Interaction).filter_by(candidate_id=cid).order_by(Interaction.occurred_at.desc()).limit(200).all()
    users = {x.id: x.name for x in db.query(User).all()}
    result = {
        "candidate": candidate_full(c),
        "owner": users.get(c.owner_id),
        "stage_index": STAGES.index(c.stage) if c.stage in STAGES else len(STAGES),
        "gates": {
            "comfort_check_complete": stages.comfort_check_complete(c),
            "consent_granted": stages.consent_granted(db, c),
            "documents_verified": stages.all_docs_verified(db, c),
            "missing_qualification_fields": stages.missing_qualification_fields(c),
        },
        "profile_summary": ai.profile_summary(c, best_req),
        "matches": [{"requirement_id": m.requirement_id, "title": m.requirement.title, "client": m.requirement.client, "score": m.score, "breakdown": m.breakdown, "status": m.status, "reengagement": m.is_reengagement} for m in matches[:8]],
        "timeline": [{**row(i), "user_name": users.get(i.user_id)} for i in timeline],
        "follow_ups": [row(f) for f in db.query(FollowUp).filter_by(candidate_id=cid).order_by(FollowUp.due_at.desc()).limit(20).all()],
        "drafts": [row(d) for d in db.query(Draft).filter_by(candidate_id=cid).order_by(Draft.id.desc()).limit(20).all()],
        "sequences": [row(s) for s in db.query(Sequence).filter_by(candidate_id=cid).order_by(Sequence.id.desc()).all()],
        "documents": {
            "request": row(req) if req else None,
            "portal_url": documents.portal_url(req) if req else None,
            "items": [row(i, exclude={"storage_key"}) for i in (req.items if req else [])],
            "folder": row(folder) if folder else None,
        },
        "consent": [row(x, exclude={"token"}) for x in consent],
        "offer_letters": [
            {**row(o, exclude={"storage_key"}), "uploaded_by_name": users.get(o.uploaded_by), "submitted_by_name": users.get(o.submitted_by), "approver_name": users.get(o.approver_id)}
            for o in db.query(OfferLetter).filter_by(candidate_id=cid).order_by(OfferLetter.id.desc()).all()
        ],
        "offer_approvers": [{"id": a.id, "name": a.name, "role": a.role} for a in offers.approvers(db)],
        "tickets": [row(t) for t in db.query(Ticket).filter_by(candidate_id=cid).order_by(Ticket.id.desc()).all()],
        "applications": [row(a) for a in db.query(Application).filter_by(candidate_id=cid).all()],
        "transitions": [row(t) for t in db.query(StageTransition).filter_by(candidate_id=cid).order_by(StageTransition.at).all()],
        "duplicates": [
            {"pair_id": p.id, "other_id": p.candidate_b_id if p.candidate_a_id == cid else p.candidate_a_id, "matched_on": p.matched_on}
            for p in db.query(DuplicatePair).filter(or_(DuplicatePair.candidate_a_id == cid, DuplicatePair.candidate_b_id == cid), DuplicatePair.status == "open").all()
        ],
    }
    db.commit()
    return result


@router.patch("/{cid}")
def update_fields(cid: int, body: CandidateIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    data = body.model_dump(exclude_unset=True)
    if isinstance(data.get("skills"), str):
        data["skills"] = [s.strip() for s in data["skills"].split(",") if s.strip()]
    for k, v in data.items():
        setattr(c, k, v)
    audit(db, "candidate.updated", "candidate", cid, u.id, {k: str(v)[:100] for k, v in data.items()})
    if {"skills", "years_experience", "location", "work_authorization", "availability", "preferred_type"} & set(data):
        matching.score_candidate_against_open(db, c)
    emit(db, "candidate.updated", candidate_id=cid, user_id=u.id, payload={"fields": list(data)})
    db.commit()
    return candidate_full(c)


# ---------------------------------------------------------------------------
# Stage moves (manual override with reason)
# ---------------------------------------------------------------------------
class StageIn(BaseModel):
    to: str
    reason: str = ""


@router.post("/{cid}/stage")
def move_stage(cid: int, body: StageIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    try:
        stages.transition(db, c, body.to, user_id=u.id, reason=body.reason, manual=True, trigger="manual")
    except stages.TransitionError as e:
        db.commit()  # keep any habit flag raised by the attempt
        raise HTTPException(422, {"message": str(e), "code": e.code})
    db.commit()
    return candidate_card(c)


# ---------------------------------------------------------------------------
# Calls, notes, qualification
# ---------------------------------------------------------------------------
class CallIn(BaseModel):
    outcome: str  # connected / no_answer / voicemail / call_back / interested / not_interested / wrong_number
    notes: str = ""
    checkpoints: list[int] = []
    fields: dict = {}
    duration_minutes: float | None = None
    follow_up_days: float | None = None
    kind: str = "cold_call"  # cold_call / first_conversation / screening


CONNECTED = {"connected", "interested", "not_interested", "call_back"}


@router.post("/{cid}/calls")
def log_call(cid: int, body: CallIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    allowed = set(CandidateIn.model_fields) - {"resume_text", "owner_id"}
    updates = {k: v for k, v in (body.fields or {}).items() if k in allowed and v not in (None, "")}
    if isinstance(updates.get("skills"), str):
        updates["skills"] = [s.strip() for s in updates["skills"].split(",") if s.strip()]
    for k, v in updates.items():
        setattr(c, k, v)
    connected = body.outcome in CONNECTED
    meaningful = connected and (len(body.notes) > 20 or len(body.checkpoints) >= 5)
    db.add(Interaction(candidate_id=cid, user_id=u.id, type="call", direction="out", subject=body.kind.replace("_", " ").title(), body=body.notes,
                       outcome=body.outcome, meaningful=meaningful, meta={"checkpoints": body.checkpoints, "duration": body.duration_minutes, "fields_updated": list(updates)}))
    c.last_contact_at = now()
    if connected:
        c.hot_reply = False
    if c.owner_id is None:
        c.owner_id = u.id
    flags = _scan_note(db, c, u, body.notes, "note")
    if body.follow_up_days is not None:
        followups.schedule(db, c, body.follow_up_days, f"Call back ({body.outcome.replace('_', ' ')})", rule="call_outcome")
    if body.outcome == "not_interested":
        stages.try_transition(db, c, "not_interested", user_id=u.id, reason="Not interested (call)", trigger="call")
    if updates:
        matching.score_candidate_against_open(db, c)
    emit(db, "call.logged", candidate_id=cid, user_id=u.id, payload={"outcome": body.outcome, "connected": connected, "meaningful": meaningful})
    db.commit()
    return {"candidate": candidate_card(c), "compliance_flags": flags}


@router.post("/{cid}/summarize-call")
def summarize(cid: int, body: dict, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    get_candidate_for(db, u, cid)
    return {"suggestions": ai.summarize_call(body.get("transcript", ""))}


def _scan_note(db: Session, c: Candidate, u: User, text: str, source: str) -> list[dict]:
    res = compliance.scan(text)
    if res.hits:
        compliance.record_flags(db, res, source, None, c.id, u.id, severity_override="review")
    return res.as_dict()["hits"]


class NoteIn(BaseModel):
    body: str


@router.post("/{cid}/notes")
def add_note(cid: int, body: NoteIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    db.add(Interaction(candidate_id=cid, user_id=u.id, type="note", body=body.body))
    flags = _scan_note(db, c, u, body.body, "note")
    emit(db, "note.saved", candidate_id=cid, user_id=u.id, payload={"flagged": bool(flags)})
    db.commit()
    return {"ok": True, "compliance_flags": flags, "route_to": compliance.scan(body.body).as_dict()["route_to"]}


class QualificationIn(BaseModel):
    fields: dict


@router.post("/{cid}/qualification")
def save_qualification(cid: int, body: QualificationIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    keys = {k for k, _ in QUALIFICATION_FIELDS}
    for k, v in body.fields.items():
        if k in keys:
            if k == "skills" and isinstance(v, str):
                v = [s.strip() for s in v.split(",") if s.strip()]
            if k == "years_experience" and v not in (None, ""):
                v = float(v)
            setattr(c, k, v)
    audit(db, "qualification.saved", "candidate", cid, u.id, {"fields": list(body.fields)})
    matching.score_candidate_against_open(db, c)
    emit(db, "qualification.saved", candidate_id=cid, user_id=u.id)
    db.commit()
    return {"candidate": candidate_full(c), "missing": stages.missing_qualification_fields(c), "vendor_conflict": c.vendor_conflict, "suggested_fit": c.fit_score}


class DecisionIn(BaseModel):
    decision: str  # qualified / not_qualified
    reason: str = ""


@router.post("/{cid}/decision")
def decide(cid: int, body: DecisionIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    """Keep Human: the recruiter decides. The system only validates required fields."""
    c = get_candidate_for(db, u, cid)
    c.qualification_decision = body.decision
    audit(db, "qualification.decision", "candidate", cid, u.id, {"decision": body.decision, "reason": body.reason})
    try:
        if body.decision == "qualified":
            if c.stage in ("sourced", "contacted"):
                stages.try_transition(db, c, "contacted", user_id=u.id, trigger="decision")
                stages.try_transition(db, c, "interested", user_id=u.id, trigger="decision")
            stages.transition(db, c, "qualified", user_id=u.id, reason=body.reason or "Recruiter decision", trigger="decision", manual=c.stage not in ("interested",))
        else:
            stages.transition(db, c, "closed", user_id=u.id, reason=body.reason or "Not qualified", trigger="decision")
    except stages.TransitionError as e:
        raise HTTPException(422, {"message": str(e), "code": e.code})
    db.commit()
    return candidate_card(c)


# ---------------------------------------------------------------------------
# Process explanation, comfort check, consent
# ---------------------------------------------------------------------------
class ProcessIn(BaseModel):
    w2_c2c_explained: bool = True
    items_covered: list[int] = []
    notes: str = ""


@router.post("/{cid}/process-explained")
def process_explained(cid: int, body: ProcessIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    if c.stage not in ("qualified", "process_explained"):
        raise HTTPException(422, {"message": "Candidate must be Qualified first", "code": "not_qualified"})
    c.w2_c2c_explained = body.w2_c2c_explained
    c.process_explained_at = now()
    db.add(Interaction(candidate_id=cid, user_id=u.id, type="meeting", direction="out", subject="Process explained", body=body.notes, meaningful=True, meta={"items_covered": body.items_covered}))
    _scan_note(db, c, u, body.notes, "note")
    emit(db, "process.explained", candidate_id=cid, user_id=u.id)
    db.commit()
    return candidate_card(c)


class ComfortIn(BaseModel):
    answers: list[dict]  # [{answer: yes|no, note}]


@router.post("/{cid}/comfort-check")
def comfort_check(cid: int, body: ComfortIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    if len(body.answers) != len(COMFORT_CHECK_QUESTIONS) or any(a.get("answer") not in ("yes", "no") for a in body.answers):
        raise HTTPException(422, "All 5 comfort-check questions must be answered yes or no")
    all_yes = all(a["answer"] == "yes" for a in body.answers)
    c.comfort_check = {
        "answers": [{"q": q, **a} for q, a in zip(COMFORT_CHECK_QUESTIONS, body.answers)],
        "completed_at": now().isoformat() if all_yes else None,
        "by": u.id,
        "all_yes": all_yes,
        "recorded_at": now().isoformat(),
    }
    audit(db, "comfort_check.saved", "candidate", cid, u.id, {"all_yes": all_yes})
    db.add(Interaction(candidate_id=cid, user_id=u.id, type="note", subject="Comfort check " + ("completed" if all_yes else "— concerns raised"), body="; ".join(a.get("note", "") for a in body.answers if a.get("note"))))
    if all_yes:
        emit(db, "comfort_check.completed", candidate_id=cid, user_id=u.id)
    else:
        followups.schedule(db, c, 2, "Revisit comfort-check concerns (no pressure)", rule="comfort_check")
    db.commit()
    return {"complete": all_yes, "comfort_check": c.comfort_check}


@router.post("/{cid}/consent/request")
def request_consent(cid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    if not stages.comfort_check_complete(c):
        raise HTTPException(422, {"message": "Complete the comfort check first", "code": "comfort_check_required"})
    from ..engine.actions import a_request_consent
    from ..models import Event

    res = a_request_consent(db, Event(type="manual", candidate_id=cid), {}, None)
    db.commit()
    return res


# ---------------------------------------------------------------------------
# LinkedIn status, drafts, sequences, delegation, follow-ups
# ---------------------------------------------------------------------------
@router.post("/{cid}/linkedin-status")
def linkedin_status(cid: int, body: dict, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    status = body.get("status")
    if status not in ("none", "requested", "connected"):
        raise HTTPException(422)
    prev, c.linkedin_status = c.linkedin_status, status
    if status == "connected" and prev != "connected":
        db.add(Interaction(candidate_id=cid, user_id=u.id, type="linkedin_connection", subject="LinkedIn connection accepted", meaningful=False))
        emit(db, "linkedin.connected", candidate_id=cid, user_id=u.id)
    db.commit()
    return candidate_card(c)


class DraftReq(BaseModel):
    kind: str
    requirement_id: int | None = None


DRAFT_KINDS = {"linkedin_note", "intro_message", "cold_email", "follow_up", "reengagement", "offer_explainer", "check_in", "dm", "process_summary"}


@router.post("/{cid}/drafts")
def new_draft(cid: int, body: DraftReq, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    if body.kind not in DRAFT_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(DRAFT_KINDS)}")
    req = db.get(Requirement, body.requirement_id) if body.requirement_id else None
    if req is None and body.kind in ("cold_email", "reengagement", "linkedin_note", "follow_up"):
        m = db.query(Match).join(Requirement).filter(Match.candidate_id == cid, Requirement.status == "open").order_by(Match.score.desc()).first()
        req = m.requirement if m else None
    d = outreach.create_draft(db, body.kind, c, req, u)
    db.commit()
    return row(d)


@router.post("/{cid}/sequence")
def new_sequence(cid: int, body: DraftReq, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    if not c.email:
        raise HTTPException(422, "Candidate has no email address")
    req = db.get(Requirement, body.requirement_id) if body.requirement_id else None
    try:
        seq = outreach.create_sequence(db, c, req, u)
    except outreach.OutreachError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return {"sequence": row(seq), "drafts": [row(d) for d in db.query(Draft).filter_by(sequence_id=seq.id).order_by(Draft.step).all()]}


class DelegateIn(BaseModel):
    team: str
    subject: str
    description: str = ""
    acknowledge_candidate: bool = True


@router.post("/{cid}/delegate")
def delegate(cid: int, body: DelegateIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    if body.team not in TEAMS:
        raise HTTPException(422)
    t = tickets.create_ticket(db, body.team, "candidate_question", body.subject, body.description, c, u.id, body.acknowledge_candidate)
    db.commit()
    return row(t)


class FollowUpIn(BaseModel):
    days: float = 1
    reason: str = "Follow up"


@router.post("/{cid}/follow-ups")
def add_follow_up(cid: int, body: FollowUpIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    f = followups.schedule(db, c, body.days, body.reason, rule="manual", owner_id=c.owner_id or u.id)
    db.commit()
    return row(f)


@router.post("/{cid}/follow-ups/{fid}/done")
def done_follow_up(cid: int, fid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    get_candidate_for(db, u, cid)
    f = db.get(FollowUp, fid)
    if f is None or f.candidate_id != cid:
        raise HTTPException(404)
    followups.complete(db, f)
    db.commit()
    return row(f)


@router.post("/{cid}/snooze")
def snooze(cid: int, days: int = 1, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    followups.snooze(db, c, days)
    audit(db, "candidate.snoozed", "candidate", cid, u.id, {"days": days})
    db.commit()
    return candidate_card(c)


# ---------------------------------------------------------------------------
# Documents (staff side)
# ---------------------------------------------------------------------------
@router.post("/{cid}/documents/request")
def request_docs(cid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    try:
        stages.check(db, c, "docs_requested", manual=True, reason="document request")
    except stages.TransitionError as e:
        if e.code in ("comfort_check_required", "consent_required"):
            raise HTTPException(422, {"message": str(e), "code": e.code})
    try:
        req = documents.create_request(db, c, u.id)
    except documents.DocumentRuleError as e:
        raise HTTPException(422, {"message": str(e), "code": "document_rules"})
    stages.try_transition(db, c, "docs_requested", user_id=u.id, trigger="documents_requested")
    db.commit()
    return {"request": row(req), "items": [row(i, exclude={"storage_key"}) for i in req.items], "portal_url": documents.portal_url(req)}


@router.get("/{cid}/documents/checklist-preview")
def checklist_preview(cid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    c = get_candidate_for(db, u, cid)
    try:
        return {"items": [{"doc_type": d, "label": documents.DOC_TYPES[d][0]} for d in documents.build_checklist(c)]}
    except documents.DocumentRuleError as e:
        return {"items": [], "error": str(e)}


@router.get("/{cid}/documents/{item_id}/download")
def download(cid: int, item_id: int, request: Request, db: Session = Depends(get_db), u: User = Depends(require_roles("recruiter", "ta_lead", "onboarding"))):
    c = get_candidate_for(db, u, cid)
    item = db.get(DocumentItem, item_id)
    if item is None or item.candidate_id != cid or not item.storage_key:
        raise HTTPException(404)
    if u.role == "recruiter" and c.owner_id != u.id:
        raise HTTPException(403, "Only the owning recruiter, Onboarding or TA leads can open documents")
    audit(db, "document.downloaded", "document", item_id, u.id, {"candidate_id": cid}, client_ip(request))
    db.commit()
    data = get_storage().get(item.storage_key)
    return Response(data, media_type=item.content_type or "application/octet-stream", headers={"Content-Disposition": f'inline; filename="{item.filename}"'})


class VerifyIn(BaseModel):
    approve: bool
    note: str = ""


@router.post("/{cid}/documents/{item_id}/verify")
def verify(cid: int, item_id: int, body: VerifyIn, db: Session = Depends(get_db), u: User = Depends(require_roles("onboarding", "ta_lead"))):
    get_candidate_for(db, u, cid)
    item = db.get(DocumentItem, item_id)
    if item is None or item.candidate_id != cid:
        raise HTTPException(404)
    try:
        documents.verify_item(db, item, u.id, body.approve, body.note)
    except documents.DocumentRuleError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return row(item, exclude={"storage_key"})


# ---------------------------------------------------------------------------
# Offer letters: Onboarding uploads a PDF and submits it to an internal approver
# ---------------------------------------------------------------------------
OFFER_EDITORS = ("onboarding", "ta_lead")


def _offer(db: Session, cid: int, oid: int) -> OfferLetter:
    o = db.get(OfferLetter, oid)
    if o is None or o.candidate_id != cid:
        raise HTTPException(404, "Offer letter not found")
    return o


@router.post("/{cid}/offer-letters")
async def upload_offer_letter(cid: int, file: UploadFile = File(...), notes: str = Form(""), db: Session = Depends(get_db), u: User = Depends(require_roles(*OFFER_EDITORS))):
    c = get_candidate_for(db, u, cid)
    data = await file.read()
    try:
        o = offers.upload(db, c, u, file.filename or "offer_letter.pdf", file.content_type or "", data, notes)
    except offers.OfferError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return row(o, exclude={"storage_key"})


class OfferSubmitIn(BaseModel):
    approver_id: int


@router.post("/{cid}/offer-letters/{oid}/submit")
def submit_offer_letter(cid: int, oid: int, body: OfferSubmitIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*OFFER_EDITORS))):
    get_candidate_for(db, u, cid)
    o = _offer(db, cid, oid)
    try:
        offers.submit(db, o, u, body.approver_id)
    except offers.OfferError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    return row(o, exclude={"storage_key"})


class OfferDecisionIn(BaseModel):
    approve: bool
    note: str = ""


@router.post("/{cid}/offer-letters/{oid}/decision")
def decide_offer_letter(cid: int, oid: int, body: OfferDecisionIn, db: Session = Depends(get_db), u: User = Depends(current_user)):
    get_candidate_for(db, u, cid)
    o = _offer(db, cid, oid)
    if u.id != o.approver_id and u.role != "admin":
        raise HTTPException(403, "Only the assigned approver can approve or reject this offer letter")
    try:
        offers.decide(db, o, body.approve, body.note, u, via="app")
    except offers.OfferError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return row(o, exclude={"storage_key"})


@router.get("/{cid}/offer-letters/{oid}/download")
def download_offer_letter(cid: int, oid: int, request: Request, db: Session = Depends(get_db), u: User = Depends(current_user)):
    c = get_candidate_for(db, u, cid)
    o = _offer(db, cid, oid)
    allowed = u.role in ("onboarding", "ta_lead", "admin") or u.id == o.approver_id or (u.role == "recruiter" and c.owner_id == u.id)
    if not allowed:
        raise HTTPException(403, "Only Onboarding, TA leads, the approver or the owning recruiter can open offer letters")
    audit(db, "offer.downloaded", "candidate", cid, u.id, {"offer_id": oid}, client_ip(request))
    db.commit()
    return Response(get_storage().get(o.storage_key), media_type=o.content_type, headers={"Content-Disposition": f'inline; filename="{o.filename}"'})


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------
@dup_router.get("")
def duplicate_queue(db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    pairs = db.query(DuplicatePair).filter_by(status="open").order_by(DuplicatePair.created_at.desc()).all()
    return [{"id": p.id, "matched_on": p.matched_on, "a": candidate_card(p.candidate_a), "b": candidate_card(p.candidate_b), "created_at": row(p)["created_at"]} for p in pairs]


class MergeIn(BaseModel):
    keep_id: int


@dup_router.post("/{pid}/merge")
def merge_pair(pid: int, body: MergeIn, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    p = db.get(DuplicatePair, pid)
    if p is None or p.status != "open":
        raise HTTPException(404)
    ids = {p.candidate_a_id, p.candidate_b_id}
    if body.keep_id not in ids:
        raise HTTPException(422)
    drop_id = (ids - {body.keep_id}).pop()
    keep = dedupe.merge(db, db.get(Candidate, body.keep_id), db.get(Candidate, drop_id))
    p.status = "merged"
    audit(db, "candidate.merged", "candidate", keep.id, u.id, {"merged": drop_id})
    db.commit()
    return candidate_card(keep)


@dup_router.post("/{pid}/dismiss")
def dismiss_pair(pid: int, db: Session = Depends(get_db), u: User = Depends(require_roles(*STAFF))):
    p = db.get(DuplicatePair, pid)
    if p is None:
        raise HTTPException(404)
    p.status = "dismissed"
    audit(db, "duplicate.dismissed", "duplicate_pair", pid, u.id, {})
    db.commit()
    return {"ok": True}
