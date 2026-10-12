"""Event → workflow → action triggers."""
from datetime import timedelta

import pytest

from app.engine import intake, stages
from app.engine.events import emit
from app.models import (
    Application,
    Candidate,
    ConsentRecord,
    DocumentItem,
    DocumentRequest,
    Draft,
    Job,
    Match,
    Notification,
    OutboundEmail,
    Sequence,
    Ticket,
    Workflow,
    WorkflowRun,
)
from app.util import now
from tests.conftest import grant_consent


def test_candidate_created_triggers_match_scoring(db, make_requirement, users):
    r = make_requirement()
    c, created = intake.upsert_candidate(db, {"full_name": "Ana Lopez", "email": "ana@example.com", "skills": ["Java", "Spring Boot", "Kafka"], "years_experience": 7, "location": "Dallas, TX"})
    assert created
    m = db.query(Match).filter_by(candidate_id=c.id, requirement_id=r.id).one()
    assert m.score >= 70
    assert c.fit_score == m.score
    assert db.query(WorkflowRun).join(Workflow).filter(Workflow.key == "match_on_create").count() == 1


def test_dedupe_on_create_merges_into_existing(db, make_candidate):
    c = make_candidate(email="dup@example.com", skills=["Java"])
    c2, created = intake.upsert_candidate(db, {"full_name": "Someone", "email": "DUP@example.com ", "skills": ["Kafka"], "source": "Job Posting"})
    assert not created and c2.id == c.id
    assert set(c.skills) == {"Java", "Kafka"}
    assert db.query(Candidate).count() == 1


def test_application_webhook_parses_scores_and_shortlists(db, make_requirement):
    r = make_requirement()
    resume = "PRIYA NAIR\npriya.nair@example.com | (469) 555-0101 | linkedin.com/in/priya-nair\n8 years building Java, Spring Boot, Kafka and AWS microservices."
    app = intake.receive_application(db, {"resume_text": resume, "location": "Dallas, TX", "work_authorization": "US Citizen"}, r.id, "Indeed")
    c = db.get(Candidate, app.candidate_id)
    assert c.full_name == "Priya Nair" and c.email == "priya.nair@example.com"
    assert {"Java", "Spring Boot", "Kafka", "AWS"} <= set(c.skills)
    assert app.fit_score >= 70 and app.shortlist_status == "suggested"


def test_reply_interested_marks_hot_and_advances_and_stops_sequence(db, make_candidate, make_requirement, users):
    r = make_requirement()
    c = make_candidate(stage="contacted")
    seq = Sequence(candidate_id=c.id, requirement_id=r.id, status="active", next_send_at=now())
    db.add(seq)
    db.flush()
    res = intake.handle_inbound_email(db, c.email, "Re: role", "Yes, I'm interested — let's talk tomorrow.")
    assert res["reply_class"] == "interested"
    assert c.hot_reply and c.stage == "interested"
    assert seq.status == "stopped"
    assert db.query(Notification).filter_by(user_id=c.owner_id, kind="hot").count() == 1


@pytest.mark.parametrize(
    "text,cls,stage",
    [
        ("Not right now, maybe in a few months.", "not_now", "hold"),
        ("No thanks, I'm not interested.", "not_interested", "not_interested"),
    ],
)
def test_reply_classes_update_stage(db, make_candidate, text, cls, stage):
    c = make_candidate(stage="contacted")
    res = intake.handle_inbound_email(db, c.email, "Re:", text)
    assert res["reply_class"] == cls
    assert c.stage == stage


def test_unsubscribe_reply_opts_out(db, make_candidate):
    c = make_candidate(stage="contacted")
    intake.handle_inbound_email(db, c.email, "Re:", "Please remove me from your list.")
    assert c.email_opt_out is True


def test_payroll_question_is_delegated_with_acknowledgment(db, make_candidate):
    c = make_candidate(stage="interested")
    intake.handle_inbound_email(db, c.email, "Question", "When would I get paid and how does payroll work for W-2?")
    t = db.query(Ticket).filter_by(candidate_id=c.id).one()
    assert t.team == "payroll" and t.candidate_acknowledged
    ack = db.query(OutboundEmail).filter_by(candidate_id=c.id, kind="candidate").one()
    assert ack.status == "sent" and "Payroll" in ack.text


def test_immigration_question_is_delegated_and_ack_never_mentions_immigration(db, make_candidate):
    c = make_candidate(stage="interested")
    intake.handle_inbound_email(db, c.email, "Question", "Can you help with my I-983 for STEM OPT?")
    t = db.query(Ticket).filter_by(candidate_id=c.id).one()
    assert t.team == "immigration"
    ack = db.query(OutboundEmail).filter_by(candidate_id=c.id, kind="candidate").one()
    assert ack.status == "sent"
    assert "immigration" not in ack.text.lower()


def test_process_explained_sends_summary_and_moves_stage(db, make_candidate):
    c = make_candidate(stage="qualified")
    emit(db, "process.explained", candidate_id=c.id)
    assert c.stage == "process_explained"
    e = db.query(OutboundEmail).filter_by(candidate_id=c.id).one()
    assert e.status == "sent" and "summary" in e.subject.lower()
    assert "not a final employment commitment" in e.text


def test_full_consent_to_documents_flow(db, make_candidate):
    c = make_candidate(stage="process_explained", work_authorization="H-1B", preferred_type="C2C")
    emit(db, "comfort_check.completed", candidate_id=c.id)  # sends consent link
    rec = db.query(ConsentRecord).filter_by(candidate_id=c.id).one()
    assert rec.status == "pending"
    # Documents cannot be requested yet: consent not granted, comfort check not stored.
    assert c.stage == "process_explained"
    grant_consent(db, c)
    emit(db, "consent.recorded", candidate_id=c.id)
    assert c.stage == "docs_requested"
    req = db.query(DocumentRequest).filter_by(candidate_id=c.id).one()
    types = [i.doc_type for i in req.items]
    assert types == ["resume", "passport", "work_permit_notice", "travel_record", "offer_letter", "w9", "vendor_agreement", "coi"]
    assert "w4" not in types  # payroll forms depend on W-2 vs C2C
    mails = db.query(OutboundEmail).filter_by(candidate_id=c.id).all()
    assert any("checklist" in m.subject.lower() and m.status == "sent" for m in mails)


def test_documents_request_checklist_us_citizen_w2(db, make_candidate):
    from app.engine.documents import build_checklist

    c = make_candidate(work_authorization="US Citizen", preferred_type="W-2")
    assert build_checklist(c) == ["resume", "photo_id", "offer_letter", "w4", "direct_deposit"]
    c.work_authorization = "STEM OPT EAD"
    items = build_checklist(c)
    assert "training_plan" in items and "ead_card" in items


def test_documents_complete_then_verified_moves_to_onboarding(db, make_candidate, users):
    from app.engine import documents

    c = make_candidate(stage="process_explained")
    grant_consent(db, c)
    emit(db, "consent.recorded", candidate_id=c.id)
    req = db.query(DocumentRequest).filter_by(candidate_id=c.id).one()
    pdf = b"%PDF-1.4 test" + b" " * 2000
    for item in req.items:
        exp = (now() + timedelta(days=400)).date() if item.needs_expiry else None
        res = documents.store_upload(db, item, f"{item.doc_type}.pdf", "application/pdf", pdf, exp)
        assert res["ok"], res
    assert req.status == "complete"
    assert c.stage == "docs_received"
    t = db.query(Ticket).filter_by(candidate_id=c.id, team="onboarding").one()
    assert t.kind == "document_verification"
    for item in req.items:
        documents.verify_item(db, item, users["onboarding"].id, True)
    assert c.stage == "onboarding"
    assert any("verified" in e.subject.lower() for e in db.query(OutboundEmail).filter_by(candidate_id=c.id).all())
    assert db.query(Notification).filter_by(user_id=users["onboarding"].id).count() >= 1


def test_new_requirement_reengages_only_old_past_candidates(db, make_candidate, make_requirement):
    old = make_candidate(stage="hold", last_contact_at=now() - timedelta(days=120))
    recent = make_candidate(stage="not_interested", last_contact_at=now() - timedelta(days=10))
    r = intake.create_requirement(db, {"title": "Java Engineer", "client": "Contoso", "skills": ["Java", "Spring Boot", "AWS"], "location": "Dallas, TX", "work_arrangement": "Hybrid", "min_years": 3})
    drafts = db.query(Draft).filter_by(kind="reengagement").all()
    assert [d.candidate_id for d in drafts] == [old.id]
    assert db.query(Match).filter_by(candidate_id=recent.id, requirement_id=r.id).count() == 0
    assert drafts[0].status == "pending_approval"  # never auto-sent


def test_disabled_workflow_does_not_run(db, make_requirement):
    make_requirement()
    db.query(Workflow).filter_by(key="match_on_create").one().enabled = False
    c, _ = intake.upsert_candidate(db, {"full_name": "No Match", "email": "nm@example.com", "skills": ["Java"]})
    assert db.query(Match).filter_by(candidate_id=c.id).count() == 0


def test_send_template_refuses_personalized_templates(db, make_candidate):
    from app.engine.actions import a_send_template
    from app.models import Event

    c = make_candidate()
    with pytest.raises(PermissionError):
        a_send_template(db, Event(type="x", candidate_id=c.id), {"template": "cold_email"}, None)


def test_failed_inline_action_is_retried_via_queue(db, make_candidate, monkeypatch, run_jobs):
    from app.engine import actions

    calls = {"n": 0}
    orig = actions.ACTIONS["score_candidate"]

    def flaky(db_, ev, params, wf):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return orig(db_, ev, params, wf)

    monkeypatch.setitem(actions.ACTIONS, "score_candidate", flaky)
    c, _ = intake.upsert_candidate(db, {"full_name": "Retry Me", "email": "retry@example.com", "skills": ["Java"]})
    job = db.query(Job).filter_by(type="workflow_action").one()
    assert job.status == "queued"
    from app import util

    util._clock.advance(minutes=2)
    run_jobs()
    db.refresh(job)
    assert job.status == "done" and calls["n"] == 2


def test_call_logged_advances_stage(db, make_candidate):
    c = make_candidate()
    emit(db, "call.logged", candidate_id=c.id, payload={"outcome": "interested", "connected": True})
    assert c.stage == "interested"
    c2 = make_candidate()
    emit(db, "call.logged", candidate_id=c2.id, payload={"outcome": "no_answer", "connected": False})
    assert c2.stage == "sourced"


def test_linkedin_connected_queues_intro_draft_for_manual_send(db, make_candidate):
    c = make_candidate()
    emit(db, "linkedin.connected", candidate_id=c.id)
    d = db.query(Draft).filter_by(candidate_id=c.id).one()
    assert d.kind == "intro_message" and d.channel == "linkedin"


def test_vendor_conflict_detected(db, make_candidate, make_requirement):
    from app.engine import matching

    r = make_requirement(client="Northwind Financial")
    c = make_candidate(interview_status="Already submitted to Northwind Financial through another vendor")
    matching.score_candidate_against_open(db, c)
    emit(db, "qualification.saved", candidate_id=c.id)
    assert c.vendor_conflict["conflict"] is True
    assert db.query(Match).filter_by(candidate_id=c.id, requirement_id=r.id).one().status == "not_fit"
