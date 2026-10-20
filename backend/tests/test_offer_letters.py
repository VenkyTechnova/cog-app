"""Offer letters: Onboarding uploads a PDF once, Payroll approves it, Onboarding emails it to the candidate."""
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
    assert _upload(client, auth("ta_lead"), c.id).status_code == 403
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
    assert {a["role"] for a in d["offer_approvers"]} == {"payroll"}

    approver = users["payroll"]
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
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["payroll"].id}, headers=h)

    # Only the assigned Payroll approver decides: not Onboarding, a TA lead or an admin.
    for role in ("onboarding", "ta_lead", "admin"):
        assert client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": True}, headers=auth(role)).status_code == 403
    payroll = auth("payroll")
    # The approver can open the candidate even without a Payroll ticket.
    assert client.get(f"/api/candidates/{c.id}", headers=payroll).status_code == 200
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": False}, headers=payroll)
    assert r.status_code == 422
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": False, "note": "Wrong start date"}, headers=payroll)
    assert r.status_code == 200 and r.json()["status"] == "rejected"

    # After a rejection a corrected version can be uploaded and submitted again.
    oid2 = _upload(client, h, c.id).json()["id"]
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid2}/submit", json={"approver_id": users["payroll"].id}, headers=h)
    assert r.status_code == 200


def test_offer_letter_is_uploaded_only_once(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    h = auth("onboarding")
    oid = _upload(client, h, c.id).json()["id"]
    r = _upload(client, h, c.id)
    assert r.status_code == 422 and "already been uploaded" in r.json()["detail"]
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["payroll"].id}, headers=h)
    assert _upload(client, h, c.id).status_code == 422
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": True}, headers=auth("payroll"))
    assert _upload(client, h, c.id).status_code == 422
    db.expire_all()
    assert db.query(OfferLetter).filter_by(candidate_id=c.id).count() == 1


def test_submit_requires_a_payroll_approver(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    oid = _upload(client, auth("onboarding"), c.id).json()["id"]
    for role in ("recruiter", "ta_lead", "admin"):
        r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users[role].id}, headers=auth("onboarding"))
        assert r.status_code == 422 and "Payroll" in r.json()["detail"]


def test_tampered_link_is_rejected(client):
    r = client.get("/api/public/offer-approval/not-a-real-token")
    assert "not valid" in r.text


def _approved(client, auth, db, users, make_candidate, **kw):
    c = _onboarding_candidate(db, make_candidate)
    if kw:
        for k, v in kw.items():
            setattr(c, k, v)
        db.commit()
    h = auth("onboarding")
    oid = _upload(client, h, c.id).json()["id"]
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["payroll"].id}, headers=h)
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": True}, headers=auth("payroll"))
    assert r.status_code == 200, r.text
    return c, oid


def test_send_approved_offer_letter_to_candidate_with_pdf_attached(client, auth, db, users, make_candidate):
    c = _onboarding_candidate(db, make_candidate)
    h = auth("onboarding")
    oid = _upload(client, h, c.id).json()["id"]
    # Not approved yet: can't be sent.
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={}, headers=h)
    assert r.status_code == 422 and "approved" in r.json()["detail"]
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/submit", json={"approver_id": users["payroll"].id}, headers=h)
    client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/decision", json={"approve": True}, headers=auth("payroll"))

    # Only Onboarding sends it to the candidate.
    for role in ("recruiter", "ta_lead", "payroll"):
        assert client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={}, headers=auth(role)).status_code == 403
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={"message": "Your start date is in the letter."}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent" and r.json()["sent_to"] == c.email

    e = db.query(OutboundEmail).filter_by(to_email=c.email, kind="candidate").one()
    assert e.status == "sent" and "offer letter" in e.subject.lower()
    assert e.attachments == [{"filename": "offer.pdf", "content_type": "application/pdf"}]
    assert "Your start date is in the letter." in e.text
    d = client.get(f"/api/candidates/{c.id}", headers=h).json()
    assert d["offer_letters"][0]["sent_by_name"] == users["onboarding"].name

    # Sending twice is refused.
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={}, headers=h)
    assert r.status_code == 422 and "already been sent" in r.json()["detail"]


def test_send_refused_when_candidate_unsubscribed_or_message_not_compliant(client, auth, db, users, make_candidate):
    c, oid = _approved(client, auth, db, users, make_candidate, email_opt_out=True)
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={}, headers=auth("onboarding"))
    assert r.status_code == 422 and "unsubscribed" in r.json()["detail"]

    c, oid = _approved(client, auth, db, users, make_candidate)
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={"message": "We guarantee your H-1B transfer."}, headers=auth("onboarding"))
    assert r.status_code == 422 and "Compliance" in r.json()["detail"]
    db.expire_all()
    assert db.get(OfferLetter, oid).status == "approved"


def test_sent_email_carries_the_approved_pdf_bytes(client, auth, db, users, make_candidate, monkeypatch):
    from app import mail

    sent = []
    monkeypatch.setattr(mail, "_transport", lambda to, subject, text, html, attachments, unsubscribe: sent.append((to, attachments)) or "test")
    c, oid = _approved(client, auth, db, users, make_candidate)
    sent.clear()
    r = client.post(f"/api/candidates/{c.id}/offer-letters/{oid}/send", json={}, headers=auth("onboarding"))
    assert r.status_code == 200, r.text
    assert len(sent) == 1
    to, attachments = sent[0]
    assert to == c.email
    assert attachments == [{"filename": "offer.pdf", "content": PDF, "content_type": "application/pdf"}]

    # The SMTP message built from it has the PDF as a real attachment.
    msg = mail.build_message("from@example.com", to, "Offer", "text", "<p>html</p>", attachments, None)
    att = list(msg.iter_attachments())
    assert [(a.get_filename(), a.get_content_type()) for a in att] == [("offer.pdf", "application/pdf")]
    assert att[0].get_content() == PDF
