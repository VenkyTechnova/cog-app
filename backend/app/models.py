"""SQLAlchemy ORM models. See docs/SCHEMA.md for the full description."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base
from .util import now as util_now


def utcnow() -> datetime:
    return util_now()


def uid() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetimes on every backend (SQLite drops tzinfo; values are stored as UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value is not None and dialect.name == "sqlite":
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


TS = UTCDateTime()


# ---------------------------------------------------------------------------
# People & access
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(30), index=True)  # see constants.ROLES
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ---------------------------------------------------------------------------
# Task map
# ---------------------------------------------------------------------------
class TaskItem(Base):
    __tablename__ = "task_items"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    playbook_section: Mapped[str] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(80), index=True)
    task_name: Mapped[str] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(String(40))
    current_owner: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(20), index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(Text, default="")
    automation_action: Mapped[str] = mapped_column(Text, default="")
    delegate_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_minutes_saved_per_week: Mapped[int] = mapped_column(Integer, default=0)
    baseline_minutes_per_week: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="live")
    workflow_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


# ---------------------------------------------------------------------------
# Requirements (job openings) and candidates
# ---------------------------------------------------------------------------
class Requirement(Base):
    __tablename__ = "requirements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    client: Mapped[str] = mapped_column(String(200))
    skills: Mapped[list] = mapped_column(JSON, default=list)
    location: Mapped[str] = mapped_column(String(120), default="")
    work_arrangement: Mapped[str] = mapped_column(String(20), default="Remote")
    employment_type: Mapped[str] = mapped_column(String(20), default="Either")  # W-2 / C2C / Either
    rate: Mapped[str] = mapped_column(String(80), default="")  # internal only, never auto-sent to candidates
    min_years: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(10), default="Medium")  # High / Medium / Low
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    accepted_work_auth: Mapped[list] = mapped_column(JSON, default=list)  # empty = any
    source: Mapped[str] = mapped_column(String(40), default="manual")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)

    owner = relationship("User")


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # --- 18 database fields ---
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(40), default="Other")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    years_experience: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_project_status: Mapped[str] = mapped_column(String(120), default="")
    work_authorization: Mapped[str] = mapped_column(String(40), default="")
    availability: Mapped[str] = mapped_column(String(80), default="")
    preferred_type: Mapped[str] = mapped_column(String(20), default="")
    expected_compensation: Mapped[str] = mapped_column(String(80), default="")
    work_arrangement: Mapped[str] = mapped_column(String(20), default="")
    stage: Mapped[str] = mapped_column(String(30), default="sourced", index=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(TS, nullable=True, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # --- qualification extras ---
    past_projects: Mapped[str] = mapped_column(Text, default="")
    interview_status: Mapped[str] = mapped_column(String(160), default="")
    career_goals: Mapped[str] = mapped_column(Text, default="")
    headline: Mapped[str] = mapped_column(String(240), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    university: Mapped[str] = mapped_column(String(160), default="")
    degree: Mapped[str] = mapped_column(String(160), default="")
    grad_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_text: Mapped[str] = mapped_column(Text, default="")
    # --- engagement state ---
    linkedin_status: Mapped[str] = mapped_column(String(20), default="none")  # none / requested / connected
    hot_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    hot_reply_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_reply_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    email_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # best current match score
    qualification_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # qualified / not_qualified
    vendor_conflict: Mapped[dict] = mapped_column(JSON, default=dict)
    comfort_check: Mapped[dict] = mapped_column(JSON, default=dict)  # {answers:[...], completed_at, by}
    process_explained_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    w2_c2c_explained: Mapped[bool] = mapped_column(Boolean, default=False)
    # --- governance ---
    retention_expires_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True)
    purged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    owner = relationship("User", foreign_keys=[owner_id])


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("candidate_id", "requirement_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="suggested")  # suggested/shortlisted/contacted/not_fit
    is_reengagement: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    candidate = relationship("Candidate")
    requirement = relationship("Requirement")


class Application(Base):
    """Inbound job-posting application (ATS / job board / email)."""

    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(60), default="job_board")
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    shortlist_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/shortlisted/rejected
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)

    candidate = relationship("Candidate")
    requirement = relationship("Requirement")


class Interaction(Base):
    """Timeline entry: every meaningful touchpoint is logged here."""

    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    # email_out, email_in, call, meeting, linkedin_connection, linkedin_message, note,
    # stage_change, document, consent, ticket, system
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    meaningful: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)

    user = relationship("User")


class StageTransition(Base):
    __tablename__ = "stage_transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger: Mapped[str] = mapped_column(String(80), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class FollowUp(Base):
    __tablename__ = "follow_ups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    due_at: Mapped[datetime] = mapped_column(TS, index=True)
    reason: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open/done/cancelled
    rule: Mapped[str] = mapped_column(String(60), default="stage_cadence")
    reminded_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    candidate = relationship("Candidate")


class CallListItem(Base):
    __tablename__ = "call_list_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    list_date: Mapped[date] = mapped_column(Date, index=True)
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")

    candidate = relationship("Candidate")
    requirement = relationship("Requirement")


# ---------------------------------------------------------------------------
# Outreach
# ---------------------------------------------------------------------------
class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), index=True, nullable=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    # linkedin_note, intro_message, cold_email, follow_up, reengagement, process_summary,
    # dm, check_in, offer_explainer
    channel: Mapped[str] = mapped_column(String(20), default="email")  # email / linkedin / dm
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending_approval", index=True)
    # pending_approval / approved / sent / rejected / blocked / manual_send
    compliance: Mapped[dict] = mapped_column(JSON, default=dict)
    sequence_id: Mapped[int | None] = mapped_column(ForeignKey("sequences.id"), nullable=True)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_offset_days: Mapped[int] = mapped_column(Integer, default=0)
    generated_by: Mapped[str] = mapped_column(String(40), default="template")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    candidate = relationship("Candidate")
    requirement = relationship("Requirement")


class Sequence(Base):
    __tablename__ = "sequences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/active/stopped/completed
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    next_send_at: Mapped[datetime | None] = mapped_column(TS, nullable=True, index=True)
    stop_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class OutboundEmail(Base):
    __tablename__ = "outbound_emails"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    to_email: Mapped[str] = mapped_column(String(200), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    html: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(30), index=True)  # candidate / system / digest / report / notification
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued/sent/failed/blocked
    body_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    click_count: Mapped[int] = mapped_column(Integer, default=0)


class EmailEvent(Base):
    __tablename__ = "email_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_id: Mapped[str] = mapped_column(ForeignKey("outbound_emails.id"), index=True)
    type: Mapped[str] = mapped_column(String(10))  # open / click
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class RecruitmentPost(Base):
    __tablename__ = "recruitment_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    channel: Mapped[str] = mapped_column(String(40), default="LinkedIn")
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="requested")  # requested/in_review/approved/published
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------
class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team: Mapped[str] = mapped_column(String(30), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    subject: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open/in_progress/resolved
    sla_hours: Mapped[int] = mapped_column(Integer, default=24)
    due_at: Mapped[datetime] = mapped_column(TS)
    breached: Mapped[bool] = mapped_column(Boolean, default=False)
    breach_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[str] = mapped_column(Text, default="")
    candidate_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    candidate = relationship("Candidate")


# ---------------------------------------------------------------------------
# Documents & consent
# ---------------------------------------------------------------------------
class DocumentRequest(Base):
    __tablename__ = "document_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, default=uid)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open/complete/verified/cancelled
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_reminder_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    items = relationship("DocumentItem", back_populates="request", order_by="DocumentItem.id")
    candidate = relationship("Candidate")


class DocumentItem(Base):
    __tablename__ = "document_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("document_requests.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(160))
    folder: Mapped[str] = mapped_column(String(60), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    handled_by: Mapped[str | None] = mapped_column(String(30), nullable=True)  # e.g. immigration
    status: Mapped[str] = mapped_column(String(20), default="missing")  # missing/uploaded/rejected/verified
    storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(260), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    uploaded_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")

    request = relationship("DocumentRequest", back_populates="items")


class CandidateFolder(Base):
    __tablename__ = "candidate_folders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)
    path: Mapped[str] = mapped_column(String(300))
    subfolders: Mapped[list] = mapped_column(JSON, default=list)
    acl: Mapped[list] = mapped_column(JSON, default=list)  # roles with access
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(40))  # proceed / data_processing / marketing_emails
    token: Mapped[str] = mapped_column(String(64), unique=True, default=uid)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/granted/declined/revoked
    text_version: Mapped[str] = mapped_column(String(20), default="v1")
    consent_text: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(30), default="e-consent")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    recorded_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    candidate = relationship("Candidate")


# ---------------------------------------------------------------------------
# Workflow engine
# ---------------------------------------------------------------------------
class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[str | None] = mapped_column(ForeignKey("task_items.id"), nullable=True)
    trigger_event: Mapped[str] = mapped_column(String(60), index=True)
    schedule: Mapped[str | None] = mapped_column(String(60), nullable=True)  # cron (for schedule.* triggers)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    system: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes_saved_per_run: Mapped[float] = mapped_column(Float, default=0)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # matched / skipped / completed / failed
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    requirement_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_due", "status", "run_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    run_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued/running/done/failed/cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), default="info")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Compliance, quality & audit
# ---------------------------------------------------------------------------
class ComplianceFlag(Base):
    __tablename__ = "compliance_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20))  # note / draft / email / post
    source_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category: Mapped[str] = mapped_column(String(30))  # immigration / pay_promise / tax / legal / pressure
    matched_text: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))  # block / review
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / reviewed / dismissed
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class HabitFlag(Base):
    __tablename__ = "habit_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / coached / dismissed
    coaching_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)

    candidate = relationship("Candidate")
    user = relationship("User", foreign_keys=[user_id])


class DuplicatePair(Base):
    __tablename__ = "duplicate_pairs"
    __table_args__ = (UniqueConstraint("candidate_a_id", "candidate_b_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_a_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    candidate_b_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    matched_on: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / merged / dismissed
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    candidate_a = relationship("Candidate", foreign_keys=[candidate_a_id])
    candidate_b = relationship("Candidate", foreign_keys=[candidate_b_id])


class DataQualitySnapshot(Base):
    __tablename__ = "dq_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    score: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)

    user = relationship("User")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(20), default="email")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    auto_send_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class DigestLog(Base):
    __tablename__ = "digest_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    digest_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="recruiter")  # recruiter / team_rollup
    status: Mapped[str] = mapped_column(String(20))  # sent / skipped / failed / empty_note
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    email_id: Mapped[str | None] = mapped_column(ForeignKey("outbound_emails.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    user = relationship("User")
    email = relationship("OutboundEmail")


class OfferLetter(Base):
    """An offer letter PDF uploaded by Onboarding and approved by a Payroll team member.

    Lifecycle: uploaded -> pending_approval -> approved | rejected; approved -> sent once it has been
    emailed to the candidate. The letter is uploaded once; a new version is only accepted after a rejection.
    (Letters from before that rule may be "superseded".)
    """

    __tablename__ = "offer_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)  # uploaded/pending_approval/approved/rejected/superseded/sent
    storage_key: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(250))
    content_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    decided_via: Mapped[str | None] = mapped_column(String(20), nullable=True)  # app / email
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    sent_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_id: Mapped[str | None] = mapped_column(ForeignKey("outbound_emails.id"), nullable=True)

    candidate = relationship("Candidate")
