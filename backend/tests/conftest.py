"""Test fixtures.

By default tests run on a temporary SQLite database file. Set TEST_DATABASE_URL to run them on
PostgreSQL (CI does both), e.g.
    TEST_DATABASE_URL=postgresql+psycopg2://cognitech:cognitech@localhost:5432/cognitech_test pytest
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

_tmp = tempfile.mkdtemp(prefix="cognitech-test-")
os.environ.setdefault("STORAGE_PATH", os.path.join(_tmp, "storage"))
os.environ["EMBEDDED_WORKER"] = "false"
os.environ["MAIL_BACKEND"] = "console"
os.environ["LLM_PROVIDER"] = "template"
os.environ["AUTH_MODE"] = "dev"
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest  # noqa: E402

from app import util  # noqa: E402
from app.db import Base, SessionLocal, init_engine  # noqa: E402
from app.storage import reset_storage  # noqa: E402

TEST_URL = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")

# A Wednesday, 10:00 AM Eastern (14:00 UTC).
BASE_TIME = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        from datetime import timedelta

        self.t = self.t + timedelta(**kw)
        return self.t

    def set(self, t: datetime):
        self.t = t


@pytest.fixture()
def clock():
    c = Clock(BASE_TIME)
    util.set_clock(c)
    yield c
    util.set_clock(None)


@pytest.fixture()
def db(clock):
    from app import models  # noqa: F401
    from app.engine import events

    engine = init_engine(TEST_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_storage(os.path.join(_tmp, "storage"))
    events._depth = 0
    s = SessionLocal()
    from app.seed.run import seed_reference
    from app.seed.sample_data import seed_users

    seed_users(s)
    seed_reference(s)
    s.commit()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def users(db):
    from app.models import User

    by_role = {}
    for u in db.query(User).order_by(User.id).all():
        by_role.setdefault(u.role, u)
    by_role["recruiters"] = db.query(User).filter_by(role="recruiter").order_by(User.id).all()
    return by_role


@pytest.fixture()
def make_candidate(db, users):
    from app.models import Candidate

    counter = {"n": 0}

    def _make(**kw):
        counter["n"] += 1
        n = counter["n"]
        data = dict(
            full_name=f"Test Candidate{n}",
            email=f"cand{n}@example.com",
            phone=f"21455500{n:02d}",
            skills=["Java", "Spring Boot", "AWS"],
            years_experience=6,
            location="Dallas, TX",
            work_authorization="US Citizen",
            availability="2 weeks",
            preferred_type="W-2",
            work_arrangement="Hybrid",
            owner_id=users["recruiter"].id,
            stage="sourced",
            source="LinkedIn",
            university="Purdue University",
            grad_year=2019,
        )
        data.update(kw)
        c = Candidate(**data)
        db.add(c)
        db.flush()
        return c

    return _make


@pytest.fixture()
def make_requirement(db, users):
    from app.models import Requirement

    def _make(**kw):
        data = dict(title="Senior Java Engineer", client="Northwind Financial", skills=["Java", "Spring Boot", "Kafka", "AWS"], location="Dallas, TX",
                    work_arrangement="Hybrid", employment_type="W-2", rate="$65/hr", min_years=5, priority="High", owner_id=users["recruiter"].id)
        data.update(kw)
        r = Requirement(**data)
        db.add(r)
        db.flush()
        return r

    return _make


@pytest.fixture()
def run_jobs(db):
    from app.engine.queue import run_due_jobs

    def _run():
        db.commit()
        return run_due_jobs(db)

    return _run


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client, users):
    def _auth(role="recruiter"):
        u = users[role]
        r = client.post("/api/auth/login", json={"email": u.email})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    return _auth


def grant_consent(db, c, user_id=None):
    """Helper: complete the comfort check and record consent the way the product does."""
    from app.constants import COMFORT_CHECK_QUESTIONS
    from app.models import ConsentRecord
    from app.util import now

    c.comfort_check = {"answers": [{"q": q, "answer": "yes"} for q in COMFORT_CHECK_QUESTIONS], "completed_at": now().isoformat(), "all_yes": True, "by": user_id}
    db.add(ConsentRecord(candidate_id=c.id, consent_type="proceed", status="granted", recorded_at=now()))
    db.flush()
