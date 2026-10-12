"""API-level tests: auth, roles, task map, candidate flows, portal, webhooks, impact."""
import hashlib
import hmac
import json
import os
from datetime import timedelta

from app.models import Candidate, DocumentItem, DocumentRequest, TaskItem, Ticket
from app.util import now
from tests.conftest import grant_consent


def test_auth_required(client):
    assert client.get("/api/tasks").status_code == 401


def test_task_map_seeded_every_task_in_one_category(client, auth):
    r = client.get("/api/tasks", headers=auth())
    data = r.json()
    items = data["items"]
    assert len(items) == 56
    assert {i["category"] for i in items} == {"Automate", "Delegate", "Simplify", "Keep Human"}
    # Every Automate task has an implementation (workflow, guardrail or built-in dashboard).
    for t in items:
        if t["category"] == "Automate":
            assert t["implementation"], t["id"]
        if t["category"] == "Delegate":
            assert t["delegate_to"] and t["sla_hours"]
    assert data["summary"]["per_recruiter_week"]["hours_saved"] > 0


def test_task_edit_permissions_and_validation(client, auth, db):
    r = client.patch("/api/tasks/A01", json={"category": "Automate"}, headers=auth("recruiter"))
    assert r.status_code == 403
    h = auth("ta_lead")
    r = client.patch("/api/tasks/A01", json={"category": "Delegate"}, headers=h)
    assert r.status_code == 422  # Delegate needs a team
    r = client.patch("/api/tasks/A01", json={"category": "Delegate", "delegate_to": "coordinator", "sla_hours": 24}, headers=h)
    assert r.status_code == 200 and r.json()["delegate_to"] == "coordinator"
    r = client.patch("/api/tasks/A01", json={"category": "Simplify"}, headers=h)
    assert r.json()["delegate_to"] is None
    r = client.patch("/api/tasks/A01", json={"est_minutes_saved_per_week": 99}, headers=h)
    assert r.json()["est_minutes_saved_per_week"] == 99


def test_impact_report(client, auth):
    r = client.get("/api/analytics/impact", headers=auth())
    d = r.json()
    assert {k: v["count"] for k, v in d["by_category"].items()} == {"Automate": 29, "Delegate": 4, "Simplify": 13, "Keep Human": 10}
    pr = d["per_recruiter_week"]
    assert pr["baseline_hours"] > pr["after_hours"] > 0
    assert round(pr["baseline_hours"] - pr["hours_saved"], 1) == pr["after_hours"]


def test_role_based_candidate_access(client, auth, db, make_candidate, users):
    c = make_candidate()
    db.commit()
    assert client.get(f"/api/candidates/{c.id}", headers=auth("payroll")).status_code == 403
    db.add(Ticket(team="payroll", kind="q", subject="s", candidate_id=c.id, due_at=now() + timedelta(hours=5)))
    db.commit()
    assert client.get(f"/api/candidates/{c.id}", headers=auth("payroll")).status_code == 200
    assert client.get("/api/candidates", headers=auth("payroll")).status_code == 403


def test_candidate_360_and_access_is_audited(client, auth, db, make_candidate):
    from app.models import AuditLog

    c = make_candidate()
    db.commit()
    r = client.get(f"/api/candidates/{c.id}", headers=auth())
    d = r.json()
    assert d["candidate"]["full_name"] == c.full_name
    assert set(d["gates"]) == {"comfort_check_complete", "consent_granted", "documents_verified", "missing_qualification_fields"}
    db.expire_all()
    assert db.query(AuditLog).filter_by(action="candidate.viewed", entity_id=str(c.id)).count() == 1


def test_manual_stage_move_api(client, auth, db, make_candidate):
    c = make_candidate(stage="process_explained")
    db.commit()
    h = auth()
    r = client.post(f"/api/candidates/{c.id}/stage", json={"to": "docs_requested", "reason": "Skip please"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "comfort_check_required"
    r = client.post(f"/api/candidates/{c.id}/stage", json={"to": "hold", "reason": ""}, headers=h)
    assert r.json()["detail"]["code"] == "reason_required"
    r = client.post(f"/api/candidates/{c.id}/stage", json={"to": "hold", "reason": "Candidate travelling for a month"}, headers=h)
    assert r.status_code == 200 and r.json()["stage"] == "hold"


def test_call_logging_updates_fields_and_stage(client, auth, db, make_candidate):
    c = make_candidate(availability="", preferred_type="")
    db.commit()
    r = client.post(
        f"/api/candidates/{c.id}/calls",
        headers=auth(),
        json={"outcome": "interested", "notes": "Great call, open to hybrid in Dallas, wants W-2.", "checkpoints": list(range(10)), "fields": {"availability": "Immediate", "preferred_type": "W-2"}},
    )
    assert r.status_code == 200
    db.expire_all()
    c = db.get(Candidate, c.id)
    assert c.availability == "Immediate" and c.preferred_type == "W-2"
    assert c.stage == "interested" and c.last_contact_at is not None


def test_summarize_call_prefills(client, auth, db, make_candidate):
    c = make_candidate()
    db.commit()
    r = client.post(f"/api/candidates/{c.id}/summarize-call", headers=auth(), json={"transcript": "She's based in Austin, TX, prefers W-2, remote, available in 2 weeks. 7 years of Python and AWS."})
    s = r.json()["suggestions"]
    assert s["preferred_type"] == "W-2" and s["work_arrangement"] == "Remote" and s["years_experience"] == 7.0
    assert "Python" in s["skills"]


def test_comfort_check_and_consent_via_api(client, auth, db, make_candidate):
    c = make_candidate(stage="process_explained")
    db.commit()
    h = auth()
    r = client.post(f"/api/candidates/{c.id}/comfort-check", headers=h, json={"answers": [{"answer": "yes"}] * 4 + [{"answer": "no", "note": "Wants to think"}]})
    assert r.json()["complete"] is False
    r = client.post(f"/api/candidates/{c.id}/comfort-check", headers=h, json={"answers": [{"answer": "yes"}] * 5})
    assert r.json()["complete"] is True
    db.expire_all()
    from app.models import ConsentRecord

    rec = db.query(ConsentRecord).filter_by(candidate_id=c.id).one()
    r = client.get(f"/api/public/consent/{rec.token}")
    assert "not a final employment commitment" in r.json()["text"]
    r = client.post(f"/api/public/consent/{rec.token}", json={"granted": True})
    assert r.json()["status"] == "granted"
    db.expire_all()
    c = db.get(Candidate, c.id)
    assert c.stage == "docs_requested"
    assert db.query(DocumentRequest).filter_by(candidate_id=c.id).count() == 1
    assert client.post(f"/api/public/consent/{rec.token}", json={"granted": True}).status_code == 409


def test_portal_upload_is_encrypted_at_rest(client, db, make_candidate):
    from app.engine import documents

    c = make_candidate(stage="process_explained")
    grant_consent(db, c)
    req = documents.create_request(db, c)
    db.commit()
    r = client.get(f"/api/public/portal/{req.token}")
    items = r.json()["items"]
    resume = next(i for i in items if i["label"] == "Updated resume")
    secret = b"%PDF-1.4 SECRET-RESUME-CONTENT" + b" " * 2000
    r = client.post(f"/api/public/portal/{req.token}/items/{resume['id']}", files={"file": ("cv.pdf", secret, "application/pdf")})
    assert r.status_code == 200 and r.json()["ok"]
    db.expire_all()
    item = db.get(DocumentItem, resume["id"])
    path = os.path.join(os.environ["STORAGE_PATH"], item.storage_key)
    assert b"SECRET-RESUME-CONTENT" not in open(path, "rb").read()
    from app.storage import get_storage

    assert get_storage().get(item.storage_key) == secret
    # bad type rejected
    photo = next(i for i in items if "photo ID" in i["label"])
    r = client.post(f"/api/public/portal/{req.token}/items/{photo['id']}", files={"file": ("x.exe", b"x" * 3000, "application/octet-stream")})
    assert r.json()["ok"] is False
    # expired link
    db.get(DocumentRequest, req.id).expires_at = now() - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/public/portal/{req.token}").status_code == 410


def test_document_download_restricted_and_audited(client, auth, db, make_candidate, users):
    from app.engine import documents
    from app.models import AuditLog

    c = make_candidate(stage="process_explained", owner_id=users["recruiters"][1].id)
    grant_consent(db, c)
    req = documents.create_request(db, c)
    item = req.items[0]
    documents.store_upload(db, item, "cv.pdf", "application/pdf", b"%PDF" + b" " * 3000, None)
    db.commit()
    assert client.get(f"/api/candidates/{c.id}/documents/{item.id}/download", headers=auth("recruiter")).status_code == 403  # not owner
    r = client.get(f"/api/candidates/{c.id}/documents/{item.id}/download", headers=auth("onboarding"))
    assert r.status_code == 403  # onboarding needs a ticket for this candidate
    db.add(Ticket(team="onboarding", kind="document_verification", subject="Verify", candidate_id=c.id, due_at=now() + timedelta(hours=24)))
    db.commit()
    r = client.get(f"/api/candidates/{c.id}/documents/{item.id}/download", headers=auth("onboarding"))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    db.expire_all()
    assert db.query(AuditLog).filter_by(action="document.downloaded").count() == 1


def test_webhooks_require_signature(client, db, make_requirement):
    r = make_requirement()
    db.commit()
    payload = {"full_name": "Hook Person", "email": "hook@example.com", "skills": ["Java"], "requirement_id": r.id}
    assert client.post("/api/webhooks/application", json=payload).status_code == 401
    raw = json.dumps(payload).encode()
    sig = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    resp = client.post("/api/webhooks/application", content=raw, headers={"X-Signature": f"sha256={sig}", "content-type": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidate_id"]


def test_inbound_requirement_email_parsed(client, db):
    body = "Client: Litware Insurance\nRole: Python Data Engineer\nLocation: Remote\nSkills: Python, Airflow, Snowflake\n6+ years\nType: W2 only\nRate: $60/hr\nPriority: High"
    r = client.post("/api/webhooks/inbound-email", headers={"X-Webhook-Secret": "test-secret"}, json={"from_email": "am@litware.example.com", "to_email": "requirements@cognitech.example", "subject": "Req: Python Data Engineer", "body": body})
    assert r.json()["type"] == "requirement"
    from app.models import Requirement

    db.expire_all()
    req = db.get(Requirement, r.json()["requirement_id"])
    assert req.client == "Litware Insurance" and req.employment_type == "W-2" and req.min_years == 6 and req.work_arrangement == "Remote"
    assert req.priority == "High" and "Airflow" in ",".join(req.skills)


def test_home_endpoint_builds_call_list(client, auth, db, make_candidate):
    make_candidate(stage="contacted", last_contact_at=now() - timedelta(days=20))
    db.commit()
    d = client.get("/api/home", headers=auth()).json()
    assert d["call_list"] and d["call_list"][0]["rank"] == 1
    for key in ("follow_ups_today", "follow_ups_overdue", "hot_replies", "drafts", "tickets", "applicants"):
        assert key in d


def test_workflow_dry_run(client, auth, db, make_candidate):
    c = make_candidate(stage="process_explained")
    db.commit()
    h = auth("ta_lead")
    wfs = client.get("/api/workflows", headers=h).json()
    wid = next(w["id"] for w in wfs if w["key"] == "request_documents_on_consent")
    r = client.post(f"/api/workflows/{wid}/test", headers=h, json={"candidate_id": c.id})
    d = r.json()
    assert d["matched"] is False and "comfort_check_complete" in d["reasons"][0]


def test_openapi_available(client):
    assert client.get("/openapi.json").status_code == 200
