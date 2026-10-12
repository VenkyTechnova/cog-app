"""Daily 'New Opportunities' digest generation and delivery."""
from datetime import timedelta
from urllib.parse import urlparse

from app.digest.builder import build
from app.digest.sender import render, send_all_digests, send_digest
from app.engine import matching
from app.models import Application, Candidate, DigestLog, DocumentItem, DocumentRequest, FollowUp, Interaction, OutboundEmail, Requirement, User
from app.settings_store import set_setting
from app.util import now


def _scenario(db, users, make_candidate, make_requirement):
    rec = users["recruiter"]
    other = users["recruiters"][1]
    new_req = make_requirement(title="Kafka Platform Engineer", created_at=now() - timedelta(hours=3))
    make_requirement(title="Old Req", created_at=now() - timedelta(days=5))
    cands = [make_candidate(full_name=f"Match {i}", years_experience=3 + i) for i in range(7)]
    past = make_candidate(full_name="Past Pat", stage="hold", last_contact_at=now() - timedelta(days=150))
    foreign = make_candidate(full_name="Other Owner", owner_id=other.id, skills=["Java", "Spring Boot", "Kafka", "AWS"], years_experience=12)
    # Applicant in window
    app_c = make_candidate(full_name="Applicant Amy", owner_id=None, source="Job Posting")
    db.add(Application(candidate_id=app_c.id, requirement_id=new_req.id, fit_score=81, created_at=now() - timedelta(hours=2)))
    # Hot reply
    hot = make_candidate(full_name="Hot Harper", stage="interested", hot_reply=True, hot_reply_at=now() - timedelta(hours=4))
    db.add(Interaction(candidate_id=hot.id, type="email_in", direction="in", body="Yes, interested!", occurred_at=now() - timedelta(hours=4)))
    # Follow-ups today and overdue
    db.add(FollowUp(candidate_id=cands[0].id, owner_id=rec.id, due_at=now() + timedelta(hours=1), reason="Today FU"))
    db.add(FollowUp(candidate_id=cands[1].id, owner_id=rec.id, due_at=now() - timedelta(days=2), reason="Late FU"))
    # Pending docs past SLA
    docs_c = make_candidate(full_name="Docs Dana", stage="docs_requested")
    req = DocumentRequest(candidate_id=docs_c.id, created_at=now() - timedelta(days=6), expires_at=now() + timedelta(days=8))
    db.add(req)
    db.flush()
    db.add(DocumentItem(request_id=req.id, candidate_id=docs_c.id, doc_type="passport", label="Passport (photo page)"))
    db.flush()
    return new_req, past, foreign


def test_digest_sections_in_order_and_scoped(db, users, make_candidate, make_requirement):
    new_req, past, foreign = _scenario(db, users, make_candidate, make_requirement)
    d = build(db, users["recruiter"])
    assert [r["title"] for r in d.requirements] == ["Kafka Platform Engineer"]  # only last-24h reqs
    matches = d.requirements[0]["matches"]
    assert len(matches) == 5
    assert matches == sorted(matches, key=lambda m: -m["score"])
    names = [m["name"] for m in matches]
    assert "Other Owner" not in names  # scoped to the recruiter's own / unassigned candidates
    assert [a["name"] for a in d.applicants] == ["Applicant Amy"]
    assert [h["name"] for h in d.hot_replies] == ["Hot Harper"]
    assert [f["reason"] for f in d.follow_ups_today] == ["Today FU"]
    assert [f["reason"] for f in d.follow_ups_overdue] == ["Late FU"]
    assert d.pending_documents[0]["missing"] == ["Passport (photo page)"]
    subject, html, text = render(d)
    order = [html.find(s) for s in ("1–2 · New requirements", "3 · New inbound applicants", "4 · Hot replies", "5 · Follow-ups", "6 · Pending documents")]
    assert order == sorted(order) and -1 not in order
    for label in ("Call", "Draft Email", "Snooze", "Not a Fit"):
        assert label in html
    assert "Unsubscribe" in html and "viewport" in html
    assert "Kafka Platform Engineer" in text and "Snooze:" in text


def test_reengagement_candidates_flagged(db, users, make_candidate, make_requirement):
    r = make_requirement(created_at=now() - timedelta(hours=1))
    past = make_candidate(full_name="Past Pat", stage="closed", last_contact_at=now() - timedelta(days=200), skills=["Java", "Spring Boot", "Kafka", "AWS"], years_experience=9)
    d = build(db, users["recruiter"])
    m = next(m for m in d.requirements[0]["matches"] if m["name"] == "Past Pat")
    assert m["reengagement"] is True


def test_hot_reply_disappears_after_recruiter_contact(db, users, make_candidate):
    hot = make_candidate(stage="interested", hot_reply=True, hot_reply_at=now() - timedelta(hours=3))
    assert len(build(db, users["recruiter"]).hot_replies) == 1
    db.add(Interaction(candidate_id=hot.id, user_id=users["recruiter"].id, type="call", direction="out", occurred_at=now()))
    db.flush()
    assert build(db, users["recruiter"]).hot_replies == []


def test_team_rollup_for_ta_lead(db, users, make_candidate, make_requirement):
    _scenario(db, users, make_candidate, make_requirement)
    d = build(db, users["ta_lead"], "team_rollup")
    assert {t["name"] for t in d.team} == {u.name for u in users["recruiters"]}
    assert "Other Owner" in [m["name"] for m in d.requirements[0]["matches"]]  # rollup sees everyone
    assert d.data_quality is not None
    _, html, _ = render(d)
    assert "Team at a glance" in html


def test_send_logs_delivery_and_is_idempotent(db, users, make_candidate, make_requirement):
    _scenario(db, users, make_candidate, make_requirement)
    entry = send_digest(db, users["recruiter"])
    assert entry.status == "sent" and entry.counts["new_requirements"] == 1
    email = db.get(OutboundEmail, entry.email_id)
    assert email.kind == "digest" and email.status == "sent"
    assert "/api/t/o/" in email.html  # open-tracking pixel
    assert "/api/t/c/" in email.html  # click tracking
    assert email.text  # plain-text fallback
    again = send_digest(db, users["recruiter"])
    assert again.id == entry.id
    assert db.query(DigestLog).count() == 1


def test_empty_digest_note_vs_skip(db, users):
    rec = users["recruiter"]
    entry = send_digest(db, rec)
    assert entry.status == "empty_note"
    assert "nothing new" in db.get(OutboundEmail, entry.email_id).subject
    set_setting(db, "digest.when_empty", "skip")
    entry2 = send_digest(db, users["recruiters"][1])
    assert entry2.status == "skipped" and entry2.email_id is None


def test_send_all_respects_preferences(db, users):
    users["recruiters"][2].digest_enabled = False
    out = send_all_digests(db)
    assert out["disabled"] == 1
    assert out["empty_note"] == 3  # 2 recruiters + TA lead rollup
    kinds = {l.kind for l in db.query(DigestLog).all()}
    assert kinds == {"recruiter", "team_rollup"}


def test_one_click_actions_and_unsubscribe(db, client, users, make_candidate, make_requirement):
    r = make_requirement(created_at=now() - timedelta(hours=1))
    c = make_candidate()
    matching.upsert_match(db, c, r)
    db.commit()
    d = build(db, users["recruiter"])
    links = d.requirements[0]["matches"][0]["links"]
    assert links["call"].endswith(f"/candidates/{c.id}?action=call")
    resp = client.get(urlparse(links["not_fit"]).path, follow_redirects=False)
    assert resp.status_code == 303 and "done=not_fit" in resp.headers["location"]
    db.expire_all()
    from app.models import Match

    assert db.query(Match).filter_by(candidate_id=c.id, requirement_id=r.id).one().status == "not_fit"
    resp = client.get(urlparse(links["snooze"]).path, follow_redirects=False)
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(Candidate, c.id).snoozed_until is not None
    # Tampered token is rejected
    bad = client.get(urlparse(links["snooze"]).path[:-3] + "xyz")
    assert "expired" in bad.text.lower()
    # Unsubscribe from digest
    from app.mail import unsubscribe_url

    resp = client.get(urlparse(unsubscribe_url("digest", users["recruiter"].id)).path)
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(User, users["recruiter"].id).digest_enabled is False


def test_open_and_click_tracking(db, client, users, make_requirement):
    make_requirement(created_at=now() - timedelta(hours=1))
    entry = send_digest(db, users["recruiter"])
    db.commit()
    email = db.get(OutboundEmail, entry.email_id)
    assert client.get(f"/api/t/o/{email.id}.gif").headers["content-type"] == "image/gif"
    import re

    href = re.search(r'href="(http://localhost:8000/api/t/c/[^"]+)"', email.html).group(1)
    r = client.get(urlparse(href).path + "?" + urlparse(href).query, follow_redirects=False)
    assert r.status_code == 302
    db.expire_all()
    email = db.get(OutboundEmail, entry.email_id)
    assert email.open_count == 1 and email.click_count == 1
    # Open-redirect protection
    assert client.get(f"/api/t/c/{email.id}?u=https%3A%2F%2Fevil.example.com", follow_redirects=False).status_code == 400


def test_section_preferences_respected(db, users, make_candidate, make_requirement):
    _scenario(db, users, make_candidate, make_requirement)
    u = users["recruiter"]
    u.digest_prefs = {"sections": {"applicants": False, "follow_ups": False}}
    d = build(db, u)
    assert d.applicants == [] and d.follow_ups_today == [] and d.follow_ups_overdue == []
    assert d.requirements and d.hot_replies


def test_cron_validation_checks_every_field():
    from app.engine.cron import validate

    assert validate("30 7 * * mon-fri") and validate("*/15 7-18 * * mon-fri")
    assert not validate("99 * * * *") and not validate("5 x * * *") and not validate("0 25 * * *") and not validate("* * *")
