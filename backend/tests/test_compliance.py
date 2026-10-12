"""Compliance guardrails."""
import pytest

from app.constants import OFFER_DISCLAIMER
from app.engine import compliance, outreach
from app.mail import send_email
from app.models import ComplianceFlag, HabitFlag


@pytest.mark.parametrize(
    "text,category",
    [
        ("Your H-1B transfer will be approved", "immigration"),
        ("We'll handle your I-983 for STEM OPT", "immigration"),
        ("You will be paid every Friday", "pay_promise"),
        ("The pay date is the 15th", "pay_promise"),
        ("The rate is $65/hr", "pay_promise"),
        ("C2C will save you a lot on taxes", "tax"),
        ("You are eligible for the extension", "legal"),
        ("Please decide today, last chance!", "pressure"),
    ],
)
def test_scan_catches_sensitive_statements(text, category):
    res = compliance.scan(text)
    assert category in res.categories


@pytest.mark.parametrize(
    "text",
    [
        "Hi Maya, I noticed your Kafka work at Contoso. Are you open to hearing about new projects?",
        "Our Payroll team will answer payroll questions in writing.",
        "You can opt out at any time.",
        OFFER_DISCLAIMER,
    ],
)
def test_scan_allows_neutral_text(text):
    assert not compliance.scan(text).blocked


def test_pressure_is_reviewed_not_blocked():
    res = compliance.scan("Act now!")
    assert res.hits and not res.blocked


def test_blocked_draft_cannot_be_approved_and_is_flagged(db, make_candidate, users):
    c = make_candidate()
    d = outreach.create_draft(db, "follow_up", c, None, users["recruiter"])
    outreach.update_draft(db, d, None, d.body + "\nDon't worry, your green card process is guaranteed.")
    assert d.status == "blocked" and "immigration" in d.compliance["categories"]
    assert d.compliance["route_to"]["immigration"]
    with pytest.raises(outreach.OutreachError):
        outreach.approve(db, d, users["recruiter"])
    assert db.query(ComplianceFlag).filter_by(source_type="draft", source_id=str(d.id)).count() >= 1
    assert db.query(HabitFlag).filter_by(habit="immigration_advice", user_id=users["recruiter"].id).count() == 1


def test_system_email_gate_blocks_even_direct_sends(db, make_candidate):
    c = make_candidate()
    rec = send_email(db, c.email, "Hello", "Your pay date will be the 1st.", kind="candidate", candidate_id=c.id)
    assert rec.status == "blocked"
    assert db.query(ComplianceFlag).filter_by(source_type="email").count() == 1


def test_opportunity_drafts_carry_not_final_label(db, make_candidate, make_requirement, users):
    c = make_candidate()
    d = outreach.create_draft(db, "cold_email", c, make_requirement(), users["recruiter"])
    assert OFFER_DISCLAIMER in d.body
    assert not d.compliance["blocked"]
    placed = make_candidate(stage="placed")
    d2 = outreach.create_draft(db, "check_in", placed, None, users["recruiter"])
    assert OFFER_DISCLAIMER not in d2.body


def test_linkedin_note_rules_and_no_auto_send(db, make_candidate, make_requirement, users):
    c = make_candidate()
    d = outreach.create_draft(db, "linkedin_note", c, make_requirement(), users["recruiter"])
    lines = [l for l in d.body.splitlines() if l.strip()]
    assert len(lines) <= 5 and d.body.count("?") == 1
    assert "Purdue" in d.body or "Java" in d.body  # one specific detail
    outreach.approve(db, d, users["recruiter"])
    assert d.status == "manual_send"  # never sent by the platform
    outreach.update_draft(db, d, None, "\n".join(["line"] * 7))
    with pytest.raises(outreach.OutreachError):
        outreach.approve(db, d, users["recruiter"])


def test_generic_message_flagged_as_habit(db, make_candidate, users):
    c = make_candidate()
    d = outreach.create_draft(db, "follow_up", c, None, users["recruiter"])
    outreach.update_draft(db, d, None, "Dear candidate, we have jobs. Reply if interested.")
    outreach.approve(db, d, users["recruiter"])
    assert db.query(HabitFlag).filter_by(habit="generic_message").count() == 1


def test_templates_cannot_contain_pay_statements(client, auth):
    h = auth("ta_lead")
    r = client.put("/api/templates/follow_up", json={"body": "Hi {{first_name}}, you'll be paid on Fridays."}, headers=h)
    assert r.status_code == 422


def test_notes_are_flagged_not_blocked(client, auth, db, make_candidate):
    c = make_candidate()
    db.commit()
    r = client.post(f"/api/candidates/{c.id}/notes", json={"body": "Candidate asked about their H-1B transfer timeline."}, headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["compliance_flags"] and body["route_to"]["immigration"]
    db.expire_all()
    f = db.query(ComplianceFlag).filter_by(source_type="note").one()
    assert f.severity == "review"


def test_workflow_cannot_auto_send_personalized_template(client, auth):
    h = auth("ta_lead")
    r = client.post("/api/workflows", headers=h, json={"name": "Blast", "trigger_event": "candidate.created", "actions": [{"type": "send_template", "params": {"template": "cold_email"}}]})
    assert r.status_code == 422
    r = client.post("/api/workflows", headers=h, json={"name": "Summary", "trigger_event": "process.explained", "actions": [{"type": "send_template", "params": {"template": "process_summary"}}]})
    assert r.status_code == 200
