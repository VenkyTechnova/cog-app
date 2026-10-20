"""Unsubscribe links: link scanners can't unsubscribe anyone, and mail clients can one-click."""
from urllib.parse import urlparse

from app.mail import build_message, unsubscribe_url
from app.models import Candidate


def test_get_never_unsubscribes_candidate_but_post_does(client, db, make_candidate):
    c = make_candidate()
    db.commit()
    path = urlparse(unsubscribe_url("candidate", c.id)).path
    for _ in range(3):  # e.g. Outlook Safe Links pre-fetching the link
        r = client.get(path)
        assert r.status_code == 200 and "Unsubscribe from Cognitech emails?" in r.text
    db.expire_all()
    assert db.get(Candidate, c.id).email_opt_out is False

    # RFC 8058 one-click request from a mail client.
    r = client.post(path, data={"List-Unsubscribe": "One-Click"})
    assert r.status_code == 200 and "unsubscribed" in r.text
    db.expire_all()
    assert db.get(Candidate, c.id).email_opt_out is True
    # Repeating is harmless, and the page now says so.
    assert client.post(path).status_code == 200
    assert "already unsubscribed" in client.get(path).text


def test_invalid_token(client):
    assert "invalid" in client.get("/api/public/unsubscribe/nope").text
    assert "invalid" in client.post("/api/public/unsubscribe/nope").text


def test_headers_are_not_folded_or_encoded():
    unsub = "http://localhost:8000/api/public/unsubscribe/eyJpZCI6NzMsImsiOiJjYW5kaWRhdGUifQ.ZGDfGjK08Uxay4vvi7qFGIIoGChOdnU_3djAsgGpGbk"
    subject = "A new Senior Java Microservices Engineer role that made me think of you"
    msg = build_message("Cognitech <talent@cognitech.example>", "a@example.com", subject, "hi", "<p>hi</p>", [], unsub)
    raw = msg.as_bytes().decode()
    assert f"List-Unsubscribe: <{unsub}>\n" in raw
    assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click\n" in raw
    assert f"Subject: {subject}\n" in raw
    assert "=?utf-8?" not in raw.split("\n\n", 1)[0]
