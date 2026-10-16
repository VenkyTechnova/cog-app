"""Offer letters: Onboarding uploads a PDF, submits it to an internal approver, approver decides."""
from datetime import timedelta

from app.models import Interaction, OfferLetter, OutboundEmail, Ticket
from app.util import now

PDF = b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF"


def _onboarding_candidate(db, make_candidate):
    c = make_candidate(stage="onboarding")
    db.add(Ticket(team="onboarding", kind="onboarding", subject="Onboard", candidate_id=c.id, due_at=now() + timedelta(days=1)))
    db.commit()
    return c


def _upload(client, h, cid, data=PDF, ctype="application/pdf", notes="Rate $70/hr, start Nov 3"):
    return client.post(f"/api/candidates/{cid}/offer-letters", files={"file": ("offer.pdf", data, ctype)}, data={"notes": notes}, headers=h)


def _token_from_email(db, approver):
    e = db.query(OutboundEmail).filter_by(to_email=approver.email).order_by(OutboundEmail.created_at.desc()).first()
    assert e is not None and "Approval needed: offer letter" in e.subject
    url = next(w for w in e.text.split() if "/api/public/offer-approval/" in w)
    return url.split("/api/public/offer-approval/")[1]


def test_upload_requires_pdf_and_editor_role(client, auth, db, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    assert _upload(client, auth("recruiter"), c.id).status_code == 403
    r = _upload(client, auth("onboarding"), c.id, data=b"hello" * 100, ctype="text/plain")
    assert r.status_code == 422 and "PDF" in r.json()["detail"]
    r = _upload(client, auth("onboarding"), c.id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "uploaded" and "storage_key" not in r.json()


def test_submit_emails_approver_and_approve_from_email_link(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    h = auth("onboarding")
    oid = _upload(client, h, c.id).json()["id"]

    # The candidate page lists the letter and who can approve it.
    d = client.get(f"/api/candidates/{c.id}", headers=h).json()
    assert d["offer_letters"][0]["id"] == oid
    assert {a["role"] for a in d["offer_approvers"]} <= {"ta_lead", "admin"}

    approver = users["ta_lead"]
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": approver.id}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_approval"

    token = _token_from_email(db, approver)
    page = client.get(f"/api/public/offer-approval/{token}")
    assert page.status_code == 200 and "confirm my approval" in page.text
    f = client.get(f"/api/public/offer-approval/{token}/file")
    assert f.status_code == 200 and f.content.startswith(b"%PDF")

    # Approving without ticking the confirmation box is refused.
    r = client.post(f"/api/public/offer-approval/{token}", data={"decision": "approve"})
    assert "confirmation box" in r.text
    r = client.post(f"/api/public/offer-approval/{token}", data={"decision": "approve", "confirm": "1"})
    assert "approved" in r.text

    db.expire_all()
    o = db.get(OfferLetter, oid)
    assert o.status == "approved" and o.decided_via == "email"
    # The submitter is told by email; the decision is on the timeline.
    assert db.query(OutboundEmail).filter_by(to_email=users["onboarding"].email).filter(OutboundEmail.subject.like("Offer letter approved%")).count() == 1
    assert db.query(Interaction).filter_by(candidate_id=c.id, type="offer_letter").count() == 3
    # The link can't be used twice.
    r = client.post(f"/api/public/offer-approval/{token}", data={"decision": "reject", "note": "late"})
    assert "already approved" in r.text


def test_reject_in_app_requires_reason_and_only_assigned_approver(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    h = auth("onboarding")
    oid = _upload(client, h, c.id).json()["id"]
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["ta_lead"].id}, headers=h)

    assert client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": True}, headers=h).status_code == 403
    lead = auth("ta_lead")
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": False}, headers=lead)
    assert r.status_code == 422
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": False, "note": "Wrong start date"}, headers=lead)
    assert r.status_code == 200 and r.json()["status"] == "rejected"

    # A corrected version can be uploaded and submitted again.
    oid2 = _upload(client, h, c.id).json()["id"]
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid2}/submit", json={"approver_id": users["ta_lead"].id}, headers=h)
    assert r.status_code == 200


def test_new_upload_supersedes_pending_and_old_link_stops_working(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    h = auth("onboarding")
    oid = _upload(client, h, c.id).json()["id"]
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["ta_lead"].id}, headers=h)
    token = _token_from_email(db, users["ta_lead"])
    _upload(client, h, c.id)
    db.expire_all()
    assert db.get(OfferLetter, oid).status == "superseded"
    r = client.post(f"/api/public/offer-approval/{token}", data={"decision": "approve", "confirm": "1"})
    assert "already superseded" in r.text


def test_submit_rejects_non_approver_and_self_approval(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    oid = _upload(client, auth("onboarding"), c.id).json()["id"]
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["recruiter"].id}, headers=auth("onboarding"))
    assert r.status_code == 422
    lead = auth("ta_lead")
    oid = _upload(client, lead, c.id).json()["id"]
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["ta_lead"].id}, headers=lead)
    assert r.status_code == 422 and "own" in r.json()["detail"]


def test_tampered_link_is_rejected(client):
    r = client.get("/api/public/offer-approval/not-a-real-token")
    assert "not valid" in r.text
