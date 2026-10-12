"""Domain constants derived from the Cognitech Recruiter Playbook.

Where the playbook sections were summarised rather than enumerated in the brief
(e.g. the 18 database fields, the 13 "habits worth breaking"), the lists below are
a best reading of the brief. Everything here is surfaced in the UI and can be
adjusted in one place.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Task categories
# ---------------------------------------------------------------------------
CATEGORIES = ["Automate", "Delegate", "Simplify", "Keep Human"]
CATEGORY_RULES = {
    "Automate": "System does it end-to-end with no human step. Rule-based, repetitive, data-driven, low risk.",
    "Delegate": "Routed to a specific person/team with an SLA and tracking. Needs expertise or authority the recruiter doesn't have.",
    "Simplify": "Human still does it; the system does ~80% (drafts, templates, checklists, one-click actions).",
    "Keep Human": "Recruiter-owned conversation or judgment. The system only supports it (context, call guide, notes).",
}

TASK_STATUSES = ["planned", "configured", "live", "paused"]

# ---------------------------------------------------------------------------
# Candidate pipeline (10 stages; the 10th is an outcome group)
# ---------------------------------------------------------------------------
STAGES = [
    "sourced",
    "contacted",
    "interested",
    "qualified",
    "process_explained",
    "docs_requested",
    "docs_received",
    "onboarding",
    "marketing_pipeline",
]
OUTCOME_STAGES = ["placed", "closed", "hold", "not_interested"]
ALL_STAGES = STAGES + OUTCOME_STAGES
ACTIVE_STAGES = STAGES  # anything not in an outcome
STAGE_LABELS = {
    "sourced": "Sourced",
    "contacted": "Contacted",
    "interested": "Interested",
    "qualified": "Qualified",
    "process_explained": "Process Explained",
    "docs_requested": "Docs Requested",
    "docs_received": "Docs Received",
    "onboarding": "Onboarding",
    "marketing_pipeline": "Marketing / Opportunity Pipeline",
    "placed": "Placed",
    "closed": "Closed",
    "hold": "Hold",
    "not_interested": "Not Interested",
}
# Stages that may only be entered once the comfort check is complete AND consent is recorded.
CONSENT_GATED_STAGES = ["docs_requested", "docs_received", "onboarding", "marketing_pipeline", "placed"]

# Natural (event-driven) forward transitions.
FORWARD_TRANSITIONS = {
    "sourced": ["contacted"],
    "contacted": ["interested"],
    "interested": ["qualified"],
    "qualified": ["process_explained"],
    "process_explained": ["docs_requested"],
    "docs_requested": ["docs_received"],
    "docs_received": ["onboarding"],
    "onboarding": ["marketing_pipeline"],
    "marketing_pipeline": ["placed"],
    "hold": ["contacted"],
    "not_interested": ["contacted"],
    "closed": ["contacted"],
    "placed": [],
}

# Default follow-up cadence (days until next follow-up after entering a stage). Editable in Settings.
DEFAULT_FOLLOW_UP_DAYS = {
    "sourced": 2,
    "contacted": 3,
    "interested": 1,
    "qualified": 2,
    "process_explained": 2,
    "docs_requested": 2,
    "docs_received": 1,
    "onboarding": 3,
    "marketing_pipeline": 7,
    "hold": 60,
    "not_interested": 180,
    "closed": 120,
    "placed": 30,
}

# ---------------------------------------------------------------------------
# The 18 candidate database fields (§12)
# ---------------------------------------------------------------------------
DATABASE_FIELDS = [
    ("full_name", "Full name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("linkedin_url", "LinkedIn URL"),
    ("location", "Location"),
    ("source", "Source channel"),
    ("skills", "Primary skills / tech stack"),
    ("years_experience", "Years of experience"),
    ("current_project_status", "Current employment / project status"),
    ("work_authorization", "Work authorization"),
    ("availability", "Availability"),
    ("preferred_type", "Preferred employment type (W-2 / C2C)"),
    ("expected_compensation", "Expected compensation"),
    ("work_arrangement", "Work arrangement (remote / hybrid / onsite)"),
    ("stage", "Pipeline stage"),
    ("last_contact_at", "Last contact date"),
    ("next_follow_up_at", "Next follow-up date"),
    ("owner_id", "Recruiter owner"),
]

# The 12 qualification fields (§4)
QUALIFICATION_FIELDS = [
    ("skills", "Skills / tech stack"),
    ("years_experience", "Years of experience"),
    ("current_project_status", "Current project status"),
    ("past_projects", "Past projects"),
    ("location", "Location"),
    ("work_authorization", "Work authorization"),
    ("availability", "Availability"),
    ("preferred_type", "Preferred employment type"),
    ("expected_compensation", "Compensation expectations"),
    ("work_arrangement", "Work arrangement"),
    ("interview_status", "Interview status elsewhere"),
    ("career_goals", "Career goals"),
]
REQUIRED_FOR_QUALIFIED = ["skills", "years_experience", "location", "work_authorization", "availability", "preferred_type"]

WORK_AUTHORIZATIONS = [
    "US Citizen",
    "Green Card",
    "GC EAD",
    "H-1B",
    "H-4 EAD",
    "L-2 EAD",
    "OPT EAD",
    "STEM OPT EAD",
    "TN",
    "Other",
]
EMPLOYMENT_TYPES = ["W-2", "C2C", "Either"]
WORK_ARRANGEMENTS = ["Remote", "Hybrid", "Onsite", "Flexible"]
SOURCES = ["LinkedIn", "Job Posting", "Cold Call", "Cold Email", "Recruitment Post", "Referral", "Database", "Other"]

# ---------------------------------------------------------------------------
# Call guides
# ---------------------------------------------------------------------------
COLD_CALL_CHECKPOINTS = [
    "Introduce yourself and Cognitech Technologies",
    "Ask whether now is a convenient time (offer to reschedule)",
    "Current employment / project status",
    "Tech stack and most recent work",
    "What they are looking for next (needs)",
    "Location and work-arrangement preference",
    "Present the opportunity (why it's relevant to them)",
    "Answer questions — route payroll / immigration questions, never improvise",
    "Confirm interest level",
    "Agree next steps and a follow-up date",
]

FIRST_CONVERSATION_TOPICS = [
    "Introduction",
    "Company overview",
    "Candidate background",
    "Current status",
    "Skills",
    "Expectations",
    "Opportunity",
    "Work arrangement",
    "Pay / tax structure (approved talking points only)",
    "Candidate questions",
    "Next steps",
]

W2_C2C_TALKING_POINTS = [
    "W-2: the candidate is an employee of Cognitech; payroll, withholding and benefits eligibility are handled through Cognitech payroll.",
    "C2C: the candidate works through their own registered company, which invoices Cognitech under a vendor agreement.",
    "Which structure fits depends on the candidate's situation; Cognitech does not advise on which is better for their taxes.",
    "For tax implications, please consult your own tax professional.",
    "Specific payroll schedules and amounts are confirmed in writing by the Payroll team — not on this call.",
]

COMPANY_PROCESS_ITEMS = [
    "Initial conversation and qualification",
    "Explanation of employment structure (W-2 / C2C)",
    "Comfort check and consent to proceed",
    "Document collection through the secure portal",
    "Document verification by Onboarding / HR",
    "Onboarding and offer documentation",
    "Marketing to matching opportunities / client interviews",
    "Placement, with ongoing recruiter check-ins",
]

COMFORT_CHECK_QUESTIONS = [
    "Are you comfortable with the employment structure we discussed?",
    "Do you understand the steps and what happens next?",
    "Are you comfortable sharing the required documents through our secure portal?",
    "Have all your payroll, tax or immigration questions been routed to the right team?",
    "Do you want to proceed — with no pressure and knowing nothing is final yet?",
]

OFFER_DISCLAIMER = (
    "This message is preliminary and is not a final employment commitment. "
    "Any offer is subject to completion of Cognitech's documentation and onboarding process."
)

# ---------------------------------------------------------------------------
# Delegation teams
# ---------------------------------------------------------------------------
TEAMS = {
    "payroll": {"label": "Payroll", "sla_hours": 24},
    "immigration": {"label": "Immigration / Legal", "sla_hours": 48},
    "onboarding": {"label": "Onboarding / HR", "sla_hours": 24},
    "marketing": {"label": "Marketing", "sla_hours": 72},
    "coordinator": {"label": "Recruiting Coordinator", "sla_hours": 24},
}

ROLES = ["recruiter", "ta_lead", "coordinator", "payroll", "immigration", "onboarding", "marketing", "admin"]
ROLE_TEAM = {"payroll": "payroll", "immigration": "immigration", "onboarding": "onboarding", "marketing": "marketing", "coordinator": "coordinator"}

# ---------------------------------------------------------------------------
# Reply classification
# ---------------------------------------------------------------------------
REPLY_CLASSES = ["interested", "not_now", "not_interested", "question", "unsubscribe"]

# ---------------------------------------------------------------------------
# The 13 "habits worth breaking" (§20)
# ---------------------------------------------------------------------------
HABITS = {
    "irrelevant_outreach": "Outreach to a candidate who doesn't match the requirement (match score < 40)",
    "missed_follow_up": "Follow-up overdue by more than 2 days",
    "duplicate_record": "Created a record that duplicates an existing candidate",
    "pressuring_language": "Pressuring or urgency language in candidate messages",
    "oversharing_data": "Candidate data sent outside authorized channels",
    "generic_message": "Generic message with no personalization",
    "excessive_contact": "Exceeded the outreach cap for a candidate",
    "pay_promise": "Promised a pay date, amount or tax outcome",
    "immigration_advice": "Gave legal or immigration advice instead of routing it",
    "incomplete_record": "Qualified candidate missing required fields",
    "stale_record": "Active candidate with no activity for 30+ days",
    "unnecessary_documents": "Requested documents outside the rule-based checklist",
    "skipped_consent": "Tried to move a candidate forward without comfort check / consent",
}
