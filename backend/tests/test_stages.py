"""Stage transitions and the playbook guardrails."""
import pytest

from app.engine import stages
from app.models import FollowUp, HabitFlag, StageTransition, DocumentRequest, DocumentItem
from tests.conftest import grant_consent


def test_event_driven_forward_move(db, make_candidate):
    c = make_candidate()
    stages.transition(db, c, "contacted", trigger="test")
    assert c.stage == "contacted"
    st = db.query(StageTransition).filter_by(candidate_id=c.id).one()
    assert (st.from_stage, st.to_stage, st.manual) == ("sourced", "contacted", False)


def test_event_driven_cannot_skip_stages(db, make_candidate):
    c = make_candidate()
    with pytest.raises(stages.TransitionError):
        stages.transition(db, c, "qualified")
    assert c.stage == "sourced"


def test_outcome_stages_allowed_from_anywhere(db, make_candidate):
    c = make_candidate(stage="interested")
    stages.transition(db, c, "hold", reason="Not now")
    assert c.stage == "hold"
    # and re-engagement goes back to contacted
    stages.transition(db, c, "contacted")
    assert c.stage == "contacted"


def test_manual_move_requires_reason(db, make_candidate):
    c = make_candidate(stage="contacted")
    with pytest.raises(stages.TransitionError) as e:
        stages.transition(db, c, "qualified", manual=True, reason="")
    assert e.value.code == "reason_required"
    stages.transition(db, c, "qualified", manual=True, reason="Screened on phone, strong fit", user_id=1)
    assert c.stage == "qualified"
    assert db.query(StageTransition).filter_by(candidate_id=c.id).one().manual is True


def test_qualified_requires_fields(db, make_candidate):
    c = make_candidate(stage="interested", work_authorization="", availability="")
    with pytest.raises(stages.TransitionError) as e:
        stages.transition(db, c, "qualified")
    assert e.value.code == "qualification_incomplete"
    assert "work_authorization" in str(e.value)


@pytest.mark.parametrize("target", ["docs_requested", "docs_received", "onboarding", "marketing_pipeline", "placed"])
def test_consent_gate_blocks_even_manual_override(db, make_candidate, users, target):
    c = make_candidate(stage="process_explained")
    with pytest.raises(stages.TransitionError) as e:
        stages.transition(db, c, target, manual=True, reason="Trying to skip", user_id=users["recruiter"].id)
    assert e.value.code == "comfort_check_required"
    # The attempt is flagged as a habit worth breaking.
    assert db.query(HabitFlag).filter_by(habit="skipped_consent", candidate_id=c.id).count() == 1


def test_comfort_check_alone_is_not_enough(db, make_candidate):
    from app.constants import COMFORT_CHECK_QUESTIONS
    from app.util import now

    c = make_candidate(stage="process_explained")
    c.comfort_check = {"answers": [{"q": q, "answer": "yes"} for q in COMFORT_CHECK_QUESTIONS], "completed_at": now().isoformat(), "all_yes": True}
    with pytest.raises(stages.TransitionError) as e:
        stages.transition(db, c, "docs_requested")
    assert e.value.code == "consent_required"


def test_docs_requested_allowed_after_comfort_check_and_consent(db, make_candidate):
    c = make_candidate(stage="process_explained")
    grant_consent(db, c)
    stages.transition(db, c, "docs_requested")
    assert c.stage == "docs_requested"


def test_onboarding_requires_all_documents_verified(db, make_candidate):
    c = make_candidate(stage="docs_received")
    grant_consent(db, c)
    from datetime import timedelta
    from app.util import now

    req = DocumentRequest(candidate_id=c.id, status="complete", expires_at=now() + timedelta(days=5))
    db.add(req)
    db.flush()
    item = DocumentItem(request_id=req.id, candidate_id=c.id, doc_type="resume", label="Resume", status="uploaded")
    db.add(item)
    db.flush()
    with pytest.raises(stages.TransitionError) as e:
        stages.transition(db, c, "onboarding", manual=True, reason="HR said fine")
    assert e.value.code == "documents_unverified"
    item.status = "verified"
    db.flush()
    stages.transition(db, c, "onboarding")
    assert c.stage == "onboarding"


def test_stage_change_sets_follow_up_by_cadence(db, make_candidate, clock):
    c = make_candidate()
    stages.transition(db, c, "contacted")
    f = db.query(FollowUp).filter_by(candidate_id=c.id, status="open").one()
    # Contacted cadence is 3 days → Saturday rolls to Monday 9:00 local.
    from app.util import to_local

    local = to_local(f.due_at)
    assert local.weekday() == 0 and local.hour == 9
    assert c.next_follow_up_at == f.due_at
    # Moving again cancels the old cadence follow-up and creates a new one.
    stages.transition(db, c, "interested")
    assert db.query(FollowUp).filter_by(candidate_id=c.id, status="open").count() == 1
    assert db.query(FollowUp).filter_by(candidate_id=c.id, status="cancelled").count() == 1


def test_disabled_cadence_workflow_means_no_follow_up(db, make_candidate):
    from app.models import Workflow

    db.query(Workflow).filter_by(key="stage_follow_up_cadence").one().enabled = False
    c = make_candidate()
    stages.transition(db, c, "contacted")
    assert db.query(FollowUp).filter_by(candidate_id=c.id).count() == 0
