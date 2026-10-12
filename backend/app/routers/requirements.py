"""Requirements (job openings): CRUD, CSV / Google Sheets import, matches, LinkedIn search strings, post requests."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user, require_roles
from ..engine import ai, matching, tickets
from ..engine.intake import create_requirement
from ..models import Match, RecruitmentPost, Requirement, User
from ..serializers import candidate_card, row

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


class RequirementIn(BaseModel):
    title: str | None = None
    client: str | None = None
    skills: list[str] | str | None = None
    location: str | None = None
    work_arrangement: str | None = None
    employment_type: str | None = None
    rate: str | None = None
    min_years: int | None = None
    priority: str | None = None
    status: str | None = None
    description: str | None = None
    accepted_work_auth: list[str] | None = None
    owner_id: int | None = None


def _ser(r: Requirement, db: Session) -> dict:
    d = row(r)
    d["match_count"] = db.query(Match).filter(Match.requirement_id == r.id, Match.score >= 60).count()
    return d


@router.get("")
def list_requirements(status: str | None = "open", db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(Requirement)
    if status and status != "all":
        q = q.filter(Requirement.status == status)
    return [_ser(r, db) for r in q.order_by(Requirement.created_at.desc()).all()]


@router.post("")
def create(body: RequirementIn, db: Session = Depends(get_db), u: User = Depends(require_roles("recruiter", "ta_lead", "coordinator"))):
    data = body.model_dump(exclude_none=True)
    if not data.get("title") or not data.get("client"):
        raise HTTPException(422, "title and client are required")
    data.setdefault("owner_id", u.id)
    data["source"] = "manual"
    r = create_requirement(db, data, u.id)
    db.commit()
    return _ser(r, db)


@router.get("/{rid}")
def get(rid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    r = db.get(Requirement, rid)
    if r is None:
        raise HTTPException(404)
    matches = (
        db.query(Match).filter(Match.requirement_id == rid, Match.status != "not_fit").order_by(Match.score.desc()).limit(25).all()
    )
    return {
        **_ser(r, db),
        "boolean_queries": ai.boolean_queries(r),
        "matches": [{**candidate_card(m.candidate), "score": m.score, "breakdown": m.breakdown, "match_status": m.status, "reengagement": m.is_reengagement} for m in matches if not m.candidate.merged_into_id],
        "posts": [row(p) for p in db.query(RecruitmentPost).filter_by(requirement_id=rid).all()],
    }


@router.patch("/{rid}")
def update(rid: int, body: RequirementIn, db: Session = Depends(get_db), u: User = Depends(require_roles("recruiter", "ta_lead", "coordinator"))):
    r = db.get(Requirement, rid)
    if r is None:
        raise HTTPException(404)
    data = body.model_dump(exclude_none=True)
    if isinstance(data.get("skills"), str):
        data["skills"] = [s.strip() for s in data["skills"].split(",") if s.strip()]
    for k, v in data.items():
        setattr(r, k, v)
    audit(db, "requirement.updated", "requirement", rid, u.id, data)
    if {"skills", "location", "min_years", "accepted_work_auth", "employment_type", "work_arrangement"} & set(data):
        matching.match_requirement(db, r, limit=1)
    db.commit()
    return _ser(r, db)


@router.post("/{rid}/rematch")
def rematch(rid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    r = db.get(Requirement, rid)
    if r is None:
        raise HTTPException(404)
    top = matching.match_requirement(db, r, limit=10)
    db.commit()
    return {"top": [{"candidate_id": m.candidate_id, "score": m.score} for m in top]}


@router.post("/{rid}/matches/{cid}")
def set_match_status(rid: int, cid: int, status: str, db: Session = Depends(get_db), u: User = Depends(current_user)):
    m = db.query(Match).filter_by(requirement_id=rid, candidate_id=cid).one_or_none()
    if m is None:
        raise HTTPException(404)
    if status not in ("suggested", "shortlisted", "contacted", "not_fit", "submitted"):
        raise HTTPException(422)
    m.status = status
    audit(db, "match.status", "match", m.id, u.id, {"status": status})
    db.commit()
    return {"ok": True}


@router.post("/import")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), u: User = Depends(require_roles("recruiter", "ta_lead", "coordinator"))):
    """CSV or a Google Sheets 'Download as CSV' export. Columns: title, client, skills, location,
    work_arrangement, employment_type, rate, min_years, priority, description."""
    text = (await file.read()).decode("utf-8-sig")
    created = []
    for rec in csv.DictReader(io.StringIO(text)):
        rec = {k.strip().lower(): (v or "").strip() for k, v in rec.items() if k}
        if not rec.get("title"):
            continue
        rec["min_years"] = int(rec["min_years"]) if rec.get("min_years", "").isdigit() else 0
        rec["source"] = "csv_import"
        rec.setdefault("owner_id", u.id)
        created.append(create_requirement(db, rec, u.id).id)
    db.commit()
    return {"created": len(created), "ids": created}


class PostRequestIn(BaseModel):
    title: str
    body: str = ""
    channel: str = "LinkedIn"


@router.post("/{rid}/post-request")
def request_post(rid: int, body: PostRequestIn, db: Session = Depends(get_db), u: User = Depends(require_roles("recruiter", "ta_lead"))):
    r = db.get(Requirement, rid)
    if r is None:
        raise HTTPException(404)
    t = tickets.create_ticket(db, "marketing", "recruitment_post", f"{body.channel} post: {r.title}", body.body or r.description, None, u.id)
    p = RecruitmentPost(title=body.title, body=body.body, channel=body.channel, requirement_id=rid, status="requested", ticket_id=t.id, requested_by=u.id, checklist={})
    db.add(p)
    db.commit()
    return row(p)
