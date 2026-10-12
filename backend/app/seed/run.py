"""Seed the database.

    python -m app.seed.run            # reference data + sample data
    python -m app.seed.run --no-sample
    python -m app.seed.run --reset    # drop and recreate all tables first (dev only)
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy.orm import Session

from ..db import Base, SessionLocal, create_all, get_engine
from ..engine.templates_default import TEMPLATES
from ..models import EmailTemplate, TaskItem, Workflow
from .task_map import task_rows
from .workflows import WORKFLOWS

log = logging.getLogger(__name__)


def seed_reference(db: Session) -> None:
    for row in task_rows():
        if db.get(TaskItem, row["id"]) is None:
            db.add(TaskItem(**row))
    for key, tpl in TEMPLATES.items():
        if db.get(EmailTemplate, key) is None:
            db.add(EmailTemplate(key=key, name=tpl["name"], channel=tpl["channel"], subject=tpl["subject"], body=tpl["body"],
                                 auto_send_allowed=tpl["auto_send_allowed"], description=tpl["description"]))
    db.flush()
    for wf in WORKFLOWS:
        if db.query(Workflow).filter_by(key=wf["key"]).one_or_none() is None:
            db.add(Workflow(key=wf["key"], name=wf["name"], description=wf.get("description", ""), task_id=wf.get("task_id"),
                            trigger_event=wf["trigger_event"], schedule=wf.get("schedule"), conditions=wf.get("conditions", []),
                            actions=wf["actions"], minutes_saved_per_run=wf.get("minutes_saved_per_run", 0), system=wf.get("system", False)))
    db.flush()


def run(sample: bool = True, reset: bool = False) -> dict:
    if reset:
        Base.metadata.drop_all(get_engine())
    create_all()
    db = SessionLocal()
    try:
        from .sample_data import seed_sample, seed_users

        seed_users(db)
        seed_reference(db)
        out = {"reference": True}
        from ..models import Candidate

        if sample and db.query(Candidate).count() == 0:
            out.update(seed_sample(db))
        db.commit()
        return out
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--no-sample", action="store_true")
    p.add_argument("--reset", action="store_true")
    a = p.parse_args()
    print(run(sample=not a.no_sample, reset=a.reset))
