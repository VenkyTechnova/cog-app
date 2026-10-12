"""Reminders, sequences, SLAs and the scheduler."""
from datetime import datetime, timedelta, timezone

from app.engine import documents, outreach, tickets
from app.engine.followups import due_for_user
from app.engine.intake import handle_inbound_email
from app.models import DocumentRequest, FollowUp, Job, Notification, OutboundEmail, Sequence, Ticket, Workflow
from app.scheduler import tick
from app.settings_store import set_setting
from app.util import now
from tests.conftest import grant_consent


def _doc_request(db, c):
    grant_consent(db, c)
    return documents.create_request(db, c)


def test_document_reminders_every_48h_then_escalate(db, make_candidate, clock, users):
    c = make_candidate(stage="process_explained")
    req = _doc_request(db, c)
    base_emails = db.query(OutboundEmail).filter_by(candidate_id=c.id).count()
    assert documents.process_reminders(db) == {"reminders_sent": 0, "escalated": 0}  # too early
    for n in range(1, 4):
        clock.advance(hours=48)
        assert documents.process_reminders(db)["reminders_sent"] == 1
        assert req.reminders_sent == n
        clock.advance(hours=12)
        assert documents.process_reminders(db)["reminders_sent"] == 0  # not before 48h
        clock.advance(hours=-12)
    assert db.query(OutboundEmail).filter_by(candidate_id=c.id).count() == base_emails + 3
    clock.advance(hours=48)
    res = documents.process_reminders(db)
    assert res == {"reminders_sent": 0, "escalated": 1}
    assert req.escalated
    n = db.query(Notification).filter_by(user_id=c.owner_id, kind="escalation").one()
    assert c.full_name in n.title
    clock.advance(hours=48)
    assert documents.process_reminders(db) == {"reminders_sent": 0, "escalated": 0}  # escalates once


def test_reminder_lists_only_missing_documents(db, make_candidate, clock):
    c = make_candidate(stage="process_explained")
    req = _doc_request(db, c)
    resume = next(i for i in req.items if i.doc_type == "resume")
    documents.store_upload(db, resume, "cv.pdf", "application/pdf", b"%PDF" + b" " * 2048, None)
    clock.advance(hours=49)
    documents.process_reminders(db)
    reminder = db.query(OutboundEmail).filter_by(candidate_id=c.id).order_by(OutboundEmail.created_at.desc()).first()
    assert "Updated resume" not in reminder.text
    assert "photo ID" in reminder.text


def test_no_reminders_once_complete(db, make_candidate, clock):
    c = make_candidate(stage="process_explained")
    req = _doc_request(db, c)
    req.status = "complete"
    clock.advance(hours=100)
    assert documents.process_reminders(db)["reminders_sent"] == 0


def test_upload_validation_rules(db, make_candidate):
    c = make_candidate(stage="process_explained")
    req = _doc_request(db, c)
    photo_id = next(i for i in req.items if i.doc_type == "photo_id")
    bad_type = documents.store_upload(db, photo_id, "id.exe", "application/x-msdownload", b"x" * 5000, None)
    assert not bad_type["ok"] and "type" in bad_type["errors"][0]
    no_exp = documents.store_upload(db, photo_id, "id.pdf", "application/pdf", b"x" * 5000, None)
    assert any("expiry" in e for e in no_exp["errors"])
    expired = documents.store_upload(db, photo_id, "id.pdf", "application/pdf", b"x" * 5000, (now() - timedelta(days=1)).date())
    assert any("expired" in e for e in expired["errors"])
    soon = documents.store_upload(db, photo_id, "id.pdf", "application/pdf", b"x" * 5000, (now() + timedelta(days=20)).date())
    assert soon["ok"] and soon["warnings"]
    assert photo_id.status == "uploaded"


def test_follow_up_reminders_notify_recruiters(db, make_candidate, users, run_jobs):
    from app.engine import followups

    c = make_candidate(stage="contacted")
    followups.schedule(db, c, -2, "Overdue check-in")
    f = FollowUp(candidate_id=c.id, owner_id=c.owner_id, due_at=now() + timedelta(hours=2), reason="Today")
    db.add(f)
    db.flush()
    due = due_for_user(db, users["recruiter"])
    assert len(due["today"]) == 1 and len(due["overdue"]) == 1
    wf = db.query(Workflow).filter_by(key="follow_up_reminders").one()
    from app.engine.queue import enqueue

    enqueue(db, "scheduled_workflow", {"workflow_id": wf.id})
    run_jobs()
    n = db.query(Notification).filter_by(user_id=users["recruiter"].id, kind="reminder").one()
    assert "1 follow-ups due today, 1 overdue" in n.title


def test_sequence_sends_on_schedule_and_stops_on_reply(db, make_candidate, make_requirement, users, clock):
    r = make_requirement()
    c = make_candidate()
    seq = outreach.create_sequence(db, c, r, users["recruiter"])
    drafts = sorted(db.query(outreach.Draft).filter_by(sequence_id=seq.id).all(), key=lambda d: d.step)
    assert [d.send_offset_days for d in drafts] == [0, 3, 7]
    assert len({d.body for d in drafts}) == 3  # no identical messages
    outreach.approve_sequence(db, seq, users["recruiter"])
    assert outreach.process_sequences(db)["sent"] == 1
    assert c.stage == "contacted"  # email.sent → stage_on_outreach workflow
    clock.advance(days=1)
    assert outreach.process_sequences(db)["sent"] == 0
    clock.advance(days=2, minutes=1)
    assert outreach.process_sequences(db)["sent"] == 1
    handle_inbound_email(db, c.email, "Re:", "Thanks — can you tell me more about the team?")
    assert seq.status == "stopped"
    clock.advance(days=10)
    assert outreach.process_sequences(db)["sent"] == 0
    sent = db.query(OutboundEmail).filter_by(candidate_id=c.id, kind="candidate", status="sent").all()
    assert len(sent) == 2
    assert all("unsubscribe" in e.text.lower() for e in sent)


def test_outreach_cap_and_identical_block(db, make_candidate, users, clock):
    from app.engine.compliance import check_outreach

    c = make_candidate()
    d = outreach.create_draft(db, "follow_up", c, None, users["recruiter"])
    outreach.approve(db, d, users["recruiter"])
    assert d.status == "sent"
    chk = check_outreach(db, c, "A different message entirely")
    assert not chk.allowed and "48h" in chk.reason
    clock.advance(hours=49)
    assert not check_outreach(db, c, d.body).allowed  # identical
    set_setting(db, "outreach.max_per_candidate_7d", 1)
    assert "cap" in check_outreach(db, c, "new text").reason


def test_sla_breach_notifies_once(db, make_candidate, users, clock):
    c = make_candidate()
    t = tickets.create_ticket(db, "payroll", "candidate_question", "Pay schedule question", "", c, users["recruiter"].id)
    assert tickets.check_slas(db) == 0
    clock.advance(hours=25)
    assert tickets.check_slas(db) == 1
    assert t.breached
    assert tickets.check_slas(db) == 0
    assert db.query(Notification).filter(Notification.kind == "sla", Notification.user_id == users["ta_lead"].id).count() == 1


def test_scheduler_fires_digest_at_730_et_on_weekdays_only(db, clock):
    # Wednesday 07:30 ET = 11:30 UTC (EDT)
    clock.set(datetime(2026, 9, 23, 11, 30, tzinfo=timezone.utc))
    assert "daily_digest" in tick(db)
    assert "daily_digest" not in tick(db)  # deduped within the same minute
    clock.set(datetime(2026, 9, 23, 11, 31, tzinfo=timezone.utc))
    assert "daily_digest" not in tick(db)
    # Saturday
    clock.set(datetime(2026, 9, 26, 11, 30, tzinfo=timezone.utc))
    assert "daily_digest" not in tick(db)
    # Monday 08:00 ET → weekly report
    clock.set(datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc))
    assert "weekly_report" in tick(db)


def test_digest_time_setting_updates_schedule(db, client, auth, clock):
    h = auth("ta_lead")
    r = client.put("/api/settings/digest.time", json={"value": "06:45"}, headers=h)
    assert r.status_code == 200
    db.expire_all()
    assert db.query(Workflow).filter_by(key="daily_digest").one().schedule == "45 6 * * mon-fri"
    clock.set(datetime(2026, 9, 23, 10, 45, tzinfo=timezone.utc))
    assert "daily_digest" in tick(db)


def test_job_retry_backoff_and_permanent_failure(db, clock):
    from app.engine.queue import enqueue, handler, run_due_jobs

    @handler("always_fails")
    def _boom(db_, payload):
        raise ValueError("nope")

    j = enqueue(db, "always_fails", {}, max_attempts=2)
    db.commit()
    run_due_jobs(db)
    db.refresh(j)
    assert j.status == "queued" and j.attempts == 1
    clock.advance(minutes=3)
    run_due_jobs(db)
    db.refresh(j)
    assert j.status == "failed" and j.attempts == 2 and "nope" in j.last_error
