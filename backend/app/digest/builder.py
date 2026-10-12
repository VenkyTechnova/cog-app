"""Builds the daily "New Opportunities" digest data for a recruiter or the TA-lead rollup."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Application,
    Candidate,
    DigestLog,
    DocumentRequest,
    Interaction,
    Match,
    Requirement,
    Ticket,
    User,
)
from ..settings_store import get_setting
from ..util import aware, now, sign, to_local
from ..engine import followups, matching

SECTIONS = ["new_requirements", "applicants", "hot_replies", "follow_ups", "pending_documents"]


@dataclass
class Digest:
    user: User
    kind: str
    since: datetime
    generated_at: datetime
    requirements: list[dict] = field(default_factory=list)
    applicants: list[dict] = field(default_factory=list)
    hot_replies: list[dict] = field(default_factory=list)
    follow_ups_today: list[dict] = field(default_factory=list)
    follow_ups_overdue: list[dict] = field(default_factory=list)
    pending_documents: list[dict] = field(default_factory=list)
    team: list[dict] = field(default_factory=list)
    breached_tickets: list[dict] = field(default_factory=list)
    data_quality: float | None = None

    @property
    def counts(self) -> dict:
        return {
            "new_requirements": len(self.requirements),
            "matches": sum(len(r["matches"]) for r in self.requirements),
            "applicants": len(self.applicants),
            "hot_replies": len(self.hot_replies),
            "follow_ups_today": len(self.follow_ups_today),
            "follow_ups_overdue": len(self.follow_ups_overdue),
            "pending_documents": len(self.pending_documents),
            "breached_tickets": len(self.breached_tickets),
        }

    @property
    def is_empty(self) -> bool:
        c = self.counts
        return not any(c[k] for k in ("new_requirements", "applicants", "hot_replies", "follow_ups_today", "follow_ups_overdue", "pending_documents", "breached_tickets"))


def action_links(c: Candidate, user: User, requirement_id: int | None = None) -> dict:
    s = get_settings()
    base = f"{s.app_url}/candidates/{c.id}"
    ttl = 7 * 86400

    def signed(act):
        tok = sign({"a": act, "c": c.id, "u": user.id, "r": requirement_id}, ttl_seconds=ttl)
        return f"{s.api_url}/api/public/digest-action/{tok}"

    return {
        "call": f"{base}?action=call",
        "draft": f"{base}?action=draft" + (f"&requirement={requirement_id}" if requirement_id else ""),
        "snooze": signed("snooze"),
        "not_fit": signed("not_fit"),
        "open": base,
    }


def _cand_row(c: Candidate, user: User, requirement_id: int | None = None, **extra) -> dict:
    last = aware(c.last_contact_at)
    return {
        "id": c.id,
        "name": c.full_name,
        "headline": c.headline or ", ".join((c.skills or [])[:3]),
        "location": c.location,
        "stage": c.stage,
        "last_contact": f"{to_local(last):%b %d}" if last else "Never",
        "links": action_links(c, user, requirement_id),
        **extra,
    }


def _window_start(db: Session, user: User, kind: str) -> datetime:
    last = (
        db.query(DigestLog)
        .filter(DigestLog.user_id == user.id, DigestLog.kind == kind, DigestLog.status.in_(["sent", "empty_note", "skipped"]))
        .order_by(DigestLog.created_at.desc())
        .first()
    )
    t = now()
    default = t - timedelta(hours=24)
    if last is None:
        return default
    return max(min(aware(last.created_at), default), t - timedelta(hours=72))


def _visible(q, user: User, team: bool):
    if team:
        return q
    return q.filter((Candidate.owner_id == user.id) | (Candidate.owner_id.is_(None)))


def build(db: Session, user: User, kind: str = "recruiter", since: datetime | None = None) -> Digest:
    team = kind == "team_rollup"
    t = now()
    since = since or _window_start(db, user, kind)
    d = Digest(user=user, kind=kind, since=since, generated_at=t)
    top_n = int(get_setting(db, "digest.top_matches"))

    # 1 + 2. New requirements and top matches (existing DB + re-engagement candidates).
    for r in db.query(Requirement).filter(Requirement.created_at >= since, Requirement.status == "open").order_by(Requirement.priority, Requirement.created_at.desc()).all():
        matching.match_requirement(db, r, limit=1)  # ensures matches exist for every eligible candidate
        q = (
            db.query(Match)
            .join(Candidate, Candidate.id == Match.candidate_id)
            .filter(Match.requirement_id == r.id, Match.status != "not_fit", Candidate.merged_into_id.is_(None), Candidate.purged.is_(False))
        )
        q = _visible(q, user, team)
        ms = q.order_by(Match.score.desc()).limit(top_n).all()
        d.requirements.append(
            {
                "id": r.id,
                "title": r.title,
                "client": r.client,
                "skills": r.skills,
                "location": r.location if r.work_arrangement != "Remote" else "Remote",
                "arrangement": r.work_arrangement,
                "rate_type": " · ".join(x for x in [r.employment_type, r.rate] if x),
                "priority": r.priority,
                "matches": [
                    _cand_row(m.candidate, user, r.id, score=round(m.score), reengagement=m.is_reengagement, matched=m.breakdown.get("skills", {}).get("matched", []))
                    for m in ms
                ],
            }
        )
    prio = {"High": 0, "Medium": 1, "Low": 2}
    d.requirements.sort(key=lambda x: prio.get(x["priority"], 3))

    # 3. New inbound applicants, ranked by fit.
    q = db.query(Application).join(Candidate, Candidate.id == Application.candidate_id).filter(Application.created_at >= since, Candidate.merged_into_id.is_(None))
    q = _visible(q, user, team)
    for a in q.order_by(Application.fit_score.desc().nullslast()).limit(15).all():
        d.applicants.append(_cand_row(a.candidate, user, a.requirement_id, score=round(a.fit_score or 0), applied_for=a.requirement.title if a.requirement else "General application", source=a.source))

    # 4. Hot replies not yet contacted.
    q = db.query(Candidate).filter(Candidate.hot_reply.is_(True), Candidate.merged_into_id.is_(None))
    q = q if team else q.filter(Candidate.owner_id == user.id)
    for c in q.order_by(Candidate.hot_reply_at.desc()).all():
        # hot_reply is cleared as soon as the recruiter personally calls or emails the candidate;
        # this double-checks against the timeline in case it was logged elsewhere.
        outs = db.query(Interaction).filter(Interaction.candidate_id == c.id, Interaction.direction == "out").all()
        contacted_since = any(
            (i.meta or {}).get("auto") is not True and c.hot_reply_at and aware(i.occurred_at) > aware(c.hot_reply_at) for i in outs
        )
        if not contacted_since:
            last_in = db.query(Interaction).filter_by(candidate_id=c.id, type="email_in").order_by(Interaction.id.desc()).first()
            d.hot_replies.append(_cand_row(c, user, None, snippet=(last_in.body[:140] if last_in else ""), replied=f"{to_local(aware(c.hot_reply_at)):%b %d %I:%M %p}" if c.hot_reply_at else ""))

    # 5. Follow-ups due today + overdue.
    if team:
        for u in db.query(User).filter(User.role == "recruiter", User.is_active.is_(True)).all():
            due = followups.due_for_user(db, u)
            hot = db.query(Candidate).filter(Candidate.owner_id == u.id, Candidate.hot_reply.is_(True)).count()
            docs = _pending_docs(db, u, False)
            d.team.append({"name": u.name, "today": len(due["today"]), "overdue": len(due["overdue"]), "hot": hot, "pending_docs": len(docs)})
        due = {"today": [], "overdue": []}
    else:
        due = followups.due_for_user(db, user)
    d.follow_ups_today = [_cand_row(f.candidate, user, None, reason=f.reason, due=f"{to_local(aware(f.due_at)):%I:%M %p}") for f in due["today"]]
    d.follow_ups_overdue = [_cand_row(f.candidate, user, None, reason=f.reason, due=f"{to_local(aware(f.due_at)):%b %d}") for f in due["overdue"]]

    # 6. Pending documents past SLA.
    d.pending_documents = _pending_docs(db, user, team)

    _apply_section_prefs(d, user)
    if team:
        for tk in db.query(Ticket).filter(Ticket.status != "resolved", Ticket.breached.is_(True)).all():
            d.breached_tickets.append({"id": tk.id, "team": tk.team, "subject": tk.subject, "due": f"{to_local(aware(tk.due_at)):%b %d %I:%M %p}"})
        from ..engine.analytics import data_quality

        d.data_quality = data_quality(db)["score"]
    return d


def _apply_section_prefs(d: Digest, user: User) -> None:
    """Honour the recruiter's digest section preferences (Settings → Digest)."""
    prefs = ((user.digest_prefs or {}).get("sections")) or {}
    if prefs.get("new_requirements") is False:
        d.requirements = []
    if prefs.get("applicants") is False:
        d.applicants = []
    if prefs.get("hot_replies") is False:
        d.hot_replies = []
    if prefs.get("follow_ups") is False:
        d.follow_ups_today, d.follow_ups_overdue = [], []
    if prefs.get("pending_documents") is False:
        d.pending_documents = []


def _pending_docs(db: Session, user: User, team: bool) -> list[dict]:
    sla = int(get_setting(db, "documents.sla_hours"))
    cutoff = now() - timedelta(hours=sla)
    q = db.query(DocumentRequest).join(Candidate, Candidate.id == DocumentRequest.candidate_id).filter(DocumentRequest.status == "open", DocumentRequest.created_at <= cutoff)
    if not team:
        q = q.filter(Candidate.owner_id == user.id)
    out = []
    for r in q.all():
        missing = [i.label for i in r.items if i.required and i.status in ("missing", "rejected")]
        days = (now() - aware(r.created_at)).days
        out.append(_cand_row(r.candidate, user, None, missing=missing, days_open=days, reminders=r.reminders_sent))
    return out
