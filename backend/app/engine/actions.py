"""Workflow action registry.

Each action is `fn(db, event, params, workflow) -> dict`. ACTION_CATALOG describes the
actions (and their parameters) for the visual Workflow Builder.

Guardrail: `send_template` refuses any template that isn't marked `auto_send_allowed`, so
personalized outreach can never be sent without a human approving it.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from ..audit import audit
from ..constants import TEAMS
from ..models import (
    Application,
    Candidate,
    ConsentRecord,
    Event,
    Interaction,
    Match,
    Requirement,
    User,
    Workflow,
)
from ..util import now
from . import analytics, calllist, compliance, dedupe, documents, followups, habits, matching, outreach, tickets
from .ai import generate_draft, get_template
from .notify import notify
from .queue import handler
from .stages import try_transition

log = logging.getLogger(__name__)

ACTIONS: dict = {}
ACTION_CATALOG: dict[str, dict] = {}


def action(name: str, label: str, params: dict | None = None, category: str = "Automate"):
    def deco(fn):
        ACTIONS[name] = fn
        ACTION_CATALOG[name] = {"label": label, "params": params or {}, "category": category}
        return fn

    return deco


def execute_action(db: Session, spec: dict, ev: Event, wf: Workflow | None = None) -> dict:
    fn = ACTIONS.get(spec["type"])
    if fn is None:
        raise ValueError(f"Unknown action {spec['type']}")
    return fn(db, ev, spec.get("params") or {}, wf) or {}


def _cand(db: Session, ev: Event) -> Candidate | None:
    return db.get(Candidate, ev.candidate_id) if ev.candidate_id else None


def _owner(db: Session, c: Candidate | None) -> User | None:
    if c and c.owner_id:
        return db.get(User, c.owner_id)
    return None


def _best_requirement(db: Session, c: Candidate, ev: Event) -> Requirement | None:
    if ev.requirement_id:
        return db.get(Requirement, ev.requirement_id)
    m = db.query(Match).join(Requirement).filter(Match.candidate_id == c.id, Requirement.status == "open").order_by(Match.score.desc()).first()
    return m.requirement if m else None


# ---------------------------------------------------------------------------
# Matching & intake
# ---------------------------------------------------------------------------
@action("score_candidate", "AI match score against open requirements")
def a_score_candidate(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {"skipped": "no candidate"}
    ms = matching.score_candidate_against_open(db, c)
    return {"matches": len(ms), "best": c.fit_score}


@action("dedupe_check", "Check for duplicates (email / phone / LinkedIn) and queue merges")
def a_dedupe(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    dups = dedupe.find_duplicates(db, c.email, c.phone, c.linkedin_url, exclude_id=c.id)
    for other, on in dups:
        dedupe.queue_pair(db, c.id, other.id, on)
    return {"duplicates": len(dups)}


@action("rank_application", "Score and rank inbound applicant into the shortlist queue")
def a_rank_application(db, ev, params, wf):
    c = _cand(db, ev)
    app = db.get(Application, (ev.payload or {}).get("application_id"))
    if not c or not app:
        return {}
    if app.requirement_id:
        m = matching.upsert_match(db, c, db.get(Requirement, app.requirement_id))
        app.fit_score = m.score
    else:
        ms = matching.score_candidate_against_open(db, c)
        app.fit_score = max((m.score for m in ms), default=0)
    c.fit_score = max(c.fit_score or 0, app.fit_score or 0)
    threshold = float(params.get("shortlist_threshold", 70))
    if app.fit_score >= threshold:
        app.shortlist_status = "suggested"
    db.flush()
    return {"fit_score": app.fit_score, "suggested": app.shortlist_status == "suggested"}


@action("match_requirement", "Match a new requirement against the database (incl. re-engagement)", {"top_n": "int"})
def a_match_requirement(db, ev, params, wf):
    r = db.get(Requirement, ev.requirement_id) if ev.requirement_id else None
    if not r:
        return {}
    top = matching.match_requirement(db, r, limit=int(params.get("top_n", 10)))
    return {"top": [{"candidate_id": m.candidate_id, "score": m.score, "reengagement": m.is_reengagement} for m in top]}


@action("create_reengagement_drafts", "Draft re-engagement emails for past candidates who match", {"min_score": "int"}, "Simplify")
def a_reengage(db, ev, params, wf):
    r = db.get(Requirement, ev.requirement_id) if ev.requirement_id else None
    if not r:
        return {}
    min_score = float(params.get("min_score", 60))
    created = 0
    for m in db.query(Match).filter(Match.requirement_id == r.id, Match.is_reengagement.is_(True), Match.score >= min_score).all():
        c = m.candidate
        if c.email_opt_out or not c.email:
            continue
        outreach.create_draft(db, "reengagement", c, r, _owner(db, c))
        created += 1
    return {"drafts": created}


@action("check_vendor_conflict", "Check for another-vendor / duplicate submission conflict")
def a_vendor_conflict(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    details = []
    for other, on in dedupe.find_duplicates(db, c.email, c.phone, c.linkedin_url, exclude_id=c.id):
        if other.owner_id and other.owner_id != c.owner_id and other.stage not in ("not_interested", "closed"):
            details.append(f"Duplicate record #{other.id} is active with another recruiter (matched on {', '.join(on)})")
    interview = (c.interview_status or "").lower()
    for m in db.query(Match).join(Requirement).filter(Match.candidate_id == c.id, Requirement.status == "open", Match.score >= 50).all():
        client = (m.requirement.client or "").lower()
        if client and client in interview and ("vendor" in interview or "submitted" in interview or "through" in interview):
            details.append(f"Already submitted to {m.requirement.client} through another vendor — do not submit for '{m.requirement.title}'")
            m.status = "not_fit"
    c.vendor_conflict = {"conflict": bool(details), "details": details, "checked_at": now().isoformat()}
    if details and c.owner_id:
        notify(db, f"Possible vendor conflict: {c.full_name}", "\n".join(details), user_ids=[c.owner_id], link=f"/candidates/{c.id}", kind="warning")
    return {"conflict": bool(details)}


# ---------------------------------------------------------------------------
# Drafts & outreach
# ---------------------------------------------------------------------------
@action("create_draft", "Create a draft for recruiter approval", {"kind": "draft_kind"}, "Simplify")
def a_create_draft(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    kind = params.get("kind", "follow_up")
    req = _best_requirement(db, c, ev)
    extra = {}
    if kind == "dm":
        extra["post_title"] = (ev.payload or {}).get("post_title", "our recent opening")
    d = outreach.create_draft(db, kind, c, req, _owner(db, c), extra)
    return {"draft_id": d.id, "status": d.status}


@action("send_template", "Send an approved system template (auto-send allowed only)", {"template": "template_key"})
def a_send_template(db, ev, params, wf):
    from ..mail import send_email

    c = _cand(db, ev)
    key = params.get("template")
    tpl = get_template(db, key)
    if not tpl.get("auto_send_allowed"):
        raise PermissionError(f"Template '{key}' requires human approval and cannot be auto-sent")
    if not c or not c.email or c.email_opt_out:
        return {"skipped": "no email / opted out"}
    subject, body, _ = generate_draft(db, key, c, None, _owner(db, c))
    body = compliance.with_disclaimer(body, c) if key in ("process_summary",) else body
    rec = send_email(db, c.email, subject, body, kind="candidate", candidate_id=c.id)
    db.add(Interaction(candidate_id=c.id, type="email_out", direction="out", subject=subject, body=body, meta={"email_id": rec.id, "auto": True, "template": key, "status": rec.status}))
    return {"email_id": rec.id, "status": rec.status}


@action("stop_sequences", "Stop active email sequences for the candidate")
def a_stop_sequences(db, ev, params, wf):
    return {"stopped": outreach.stop_sequences(db, ev.candidate_id, params.get("reason", ev.type))}


@action("apply_reply_class", "Update status from the reply classification")
def a_apply_reply(db, ev, params, wf):
    c = _cand(db, ev)
    cls = (ev.payload or {}).get("reply_class")
    if not c or not cls:
        return {}
    owner = c.owner_id
    if cls == "interested":
        c.hot_reply = True
        c.hot_reply_at = now()
        try_transition(db, c, "contacted", trigger="reply")
        try_transition(db, c, "interested", trigger="reply_interested")
        if owner:
            notify(db, f"Hot reply: {c.full_name} is interested", "Reach out today — they haven't been contacted since replying.", user_ids=[owner], link=f"/candidates/{c.id}", kind="hot")
    elif cls == "not_now":
        try_transition(db, c, "hold", trigger="reply_not_now", reason="Replied: not right now")
    elif cls == "not_interested":
        try_transition(db, c, "not_interested", trigger="reply_not_interested", reason="Replied: not interested")
    elif cls == "unsubscribe":
        c.email_opt_out = True
        outreach.stop_sequences(db, c.id, "unsubscribed")
        audit(db, "candidate.unsubscribed", "candidate", c.id, None, {"via": "reply"})
    elif cls == "question":
        last_in = db.query(Interaction).filter_by(candidate_id=c.id, type="email_in").order_by(Interaction.id.desc()).first()
        text = last_in.body if last_in else ""
        cats = compliance.scan(text).categories
        if any(x in cats for x in ("immigration", "legal")):
            tickets.create_ticket(db, "immigration", "candidate_question", f"Candidate question: {c.full_name}", text[:2000], c, owner, acknowledge_candidate=True)
        elif any(x in cats for x in ("pay_promise", "tax")) or "payroll" in text.lower() or "paid" in text.lower():
            tickets.create_ticket(db, "payroll", "candidate_question", f"Payroll question: {c.full_name}", text[:2000], c, owner, acknowledge_candidate=True)
        else:
            followups.schedule(db, c, 0, "Answer candidate's question", rule="reply_question")
            if owner:
                notify(db, f"{c.full_name} asked a question", text[:200], user_ids=[owner], link=f"/candidates/{c.id}")
    return {"reply_class": cls, "stage": c.stage}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
@action("advance_stage", "Move candidate to a stage (respects guardrails)", {"to": "stage"})
def a_advance(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    st = try_transition(db, c, params["to"], trigger=f"workflow:{wf.key if wf else 'manual'}")
    return {"moved": bool(st), "stage": c.stage}


@action("set_follow_up", "Schedule a follow-up", {"days": "int", "reason": "str"})
def a_follow_up(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    f = followups.schedule(db, c, float(params.get("days", 2)), params.get("reason", "Follow up"), rule=f"workflow:{wf.key if wf else ''}")
    return {"follow_up_id": f.id}


@action("apply_stage_cadence", "Set next follow-up from the stage cadence table")
def a_cadence(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    f = followups.schedule_for_stage(db, c)
    return {"follow_up_id": f.id if f else None}


@action("notify", "Notify a person or team (in-app, optional email)", {"to": "owner|role", "role": "role", "title": "str", "email": "bool"})
def a_notify(db, ev, params, wf):
    c = _cand(db, ev)
    title = params.get("title", "Update")
    if c:
        title = title.replace("{candidate}", c.full_name)
    ids = [c.owner_id] if (params.get("to", "owner") == "owner" and c and c.owner_id) else []
    notify(db, title, params.get("body", ""), user_ids=ids, role=params.get("role"), link=f"/candidates/{c.id}" if c else None, email=bool(params.get("email")))
    return {"notified": True}


@action("create_ticket", "Delegate: create a ticket with SLA", {"team": "team", "kind": "str", "subject": "str", "acknowledge_candidate": "bool"}, "Delegate")
def a_ticket(db, ev, params, wf):
    c = _cand(db, ev)
    subject = params.get("subject", "Request").replace("{candidate}", c.full_name if c else "")
    t = tickets.create_ticket(db, params["team"], params.get("kind", "request"), subject, params.get("description", ""), c, None, bool(params.get("acknowledge_candidate")))
    return {"ticket_id": t.id}


@action("mark_hot_reply", "Flag as hot reply")
def a_hot(db, ev, params, wf):
    c = _cand(db, ev)
    if c:
        c.hot_reply = True
        c.hot_reply_at = now()
    return {}


# ---------------------------------------------------------------------------
# Consent, documents & onboarding
# ---------------------------------------------------------------------------
@action("request_consent", "Send the e-consent link")
def a_request_consent(db, ev, params, wf):
    from ..config import get_settings
    from ..mail import send_email

    c = _cand(db, ev)
    if not c or not c.email:
        return {"skipped": True}
    existing = db.query(ConsentRecord).filter(ConsentRecord.candidate_id == c.id, ConsentRecord.consent_type == "proceed", ConsentRecord.status.in_(["pending", "granted"])).first()
    if existing:
        return {"skipped": "consent already requested"}
    from ..routers.public import CONSENT_TEXT

    rec = ConsentRecord(candidate_id=c.id, consent_type="proceed", consent_text=CONSENT_TEXT, requested_by=c.owner_id)
    db.add(rec)
    db.flush()
    link = f"{get_settings().app_url}/consent/{rec.token}"
    subject, body, _ = generate_draft(db, "consent_request", c, None, _owner(db, c), {"consent_link": link})
    em = send_email(db, c.email, subject, body, kind="candidate", candidate_id=c.id)
    db.add(Interaction(candidate_id=c.id, type="consent", subject="Consent requested", meta={"consent_id": rec.id, "email_id": em.id}))
    return {"consent_id": rec.id}


@action("request_documents", "Send personalized document checklist + secure portal link")
def a_request_docs(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    try:
        req = documents.create_request(db, c)
    except documents.DocumentRuleError as e:
        if c.owner_id:
            notify(db, f"Can't request documents for {c.full_name}", str(e), user_ids=[c.owner_id], link=f"/candidates/{c.id}", kind="warning")
        return {"error": str(e)}
    try_transition(db, c, "docs_requested", trigger="documents_requested")
    return {"request_id": req.id, "items": len(req.items)}


@action("create_folder", "Create the candidate folder (standard structure + access controls)")
def a_folder(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    f = documents.ensure_folder(db, c)
    return {"path": f.path}


@action("create_verification_tickets", "Delegate: queue document verification for Onboarding / HR", {}, "Delegate")
def a_verify_tickets(db, ev, params, wf):
    c = _cand(db, ev)
    if not c:
        return {}
    t = tickets.create_ticket(db, "onboarding", "document_verification", f"Verify documents: {c.full_name}", "All required documents are uploaded and passed automated checks. Please review content and verify.", c)
    return {"ticket_id": t.id}


# ---------------------------------------------------------------------------
# Scheduled system jobs (used by `schedule` workflows)
# ---------------------------------------------------------------------------
@action("run_daily_digest", "Send the daily New Opportunities digest")
def a_digest(db, ev, params, wf):
    from ..digest.sender import send_all_digests

    return send_all_digests(db)


@action("build_call_lists", "Build today's ranked cold-call lists")
def a_call_lists(db, ev, params, wf):
    return {"items": calllist.build_all(db)}


@action("follow_up_reminders", "Remind recruiters about follow-ups due today")
def a_followup_reminders(db, ev, params, wf):
    n = 0
    for u in db.query(User).filter(User.role == "recruiter", User.is_active.is_(True)).all():
        due = followups.due_for_user(db, u)
        total = len(due["today"]) + len(due["overdue"])
        if total:
            notify(db, f"{len(due['today'])} follow-ups due today, {len(due['overdue'])} overdue", "Open Recruiter Home to work through them.", user_ids=[u.id], link="/", kind="reminder", email=bool(params.get("email", False)))
            for f in due["today"] + due["overdue"]:
                f.reminded_at = now()
            n += 1
    return {"recruiters_reminded": n}


@action("document_reminders", "Send missing-document reminders and escalate")
def a_doc_reminders(db, ev, params, wf):
    return documents.process_reminders(db)


@action("process_sequences", "Send due email-sequence steps")
def a_sequences(db, ev, params, wf):
    return outreach.process_sequences(db)


@action("check_slas", "Check delegation ticket SLAs")
def a_slas(db, ev, params, wf):
    return {"breached": tickets.check_slas(db)}


@action("data_quality_snapshot", "Nightly data-quality score")
def a_dq(db, ev, params, wf):
    s = analytics.snapshot_data_quality(db)
    return {"score": s.score}


@action("habit_monitor", "Flag 'habits worth breaking' for manager review")
def a_habits(db, ev, params, wf):
    return habits.run_monitor(db)


@action("duplicate_scan", "Weekly duplicate scan → merge queue")
def a_dupscan(db, ev, params, wf):
    return {"new_pairs": dedupe.scan_all(db)}


@action("retention_sweep", "Queue records past retention for purge review")
def a_retention(db, ev, params, wf):
    due = db.query(Candidate).filter(Candidate.retention_expires_at <= now(), Candidate.purged.is_(False)).count()
    if due:
        notify(db, f"{due} candidate records are past their retention date", "Review the purge queue in Compliance & Audit.", role="admin", link="/compliance?tab=retention")
    return {"due": due}


@action("weekly_report", "Email the weekly management report (PDF)")
def a_weekly(db, ev, params, wf):
    from ..reports.weekly import send_weekly_report

    return send_weekly_report(db)


@action("nurture_checkins", "Draft periodic check-ins for long-term relationships", {"days_since_contact": "int"}, "Simplify")
def a_nurture(db, ev, params, wf):
    days = int(params.get("days_since_contact", 60))
    cutoff = now() - timedelta(days=days)
    n = 0
    q = db.query(Candidate).filter(
        Candidate.stage.in_(["placed", "hold", "marketing_pipeline"]),
        Candidate.email_opt_out.is_(False),
        Candidate.merged_into_id.is_(None),
        Candidate.purged.is_(False),
        (Candidate.last_contact_at.is_(None)) | (Candidate.last_contact_at < cutoff),
    )
    from ..models import Draft

    for c in q.limit(int(params.get("max", 25))).all():
        if db.query(Draft).filter(Draft.candidate_id == c.id, Draft.kind == "check_in", Draft.status == "pending_approval").first():
            continue
        outreach.create_draft(db, "check_in", c, None, _owner(db, c))
        n += 1
    return {"drafts": n}


# ---------------------------------------------------------------------------
# Job handler for scheduled workflows (emitted by the scheduler tick)
# ---------------------------------------------------------------------------
@handler("scheduled_workflow")
def _job_scheduled(db: Session, payload: dict) -> dict:
    from .events import dispatch

    wf = db.get(Workflow, payload["workflow_id"])
    if not wf or not wf.enabled:
        return {"skipped": True}
    ev = Event(type="schedule", payload={"workflow_key": wf.key, "fired_at": payload.get("fired_at")}, occurred_at=now())
    db.add(ev)
    db.flush()
    runs = dispatch(db, ev, only_workflow_id=wf.id)
    return {"runs": [r.detail for r in runs]}


# Ensure queue handler module is loaded.
from . import events as _events  # noqa: E402,F401

__all__ = ["ACTIONS", "ACTION_CATALOG", "execute_action", "TEAMS"]
