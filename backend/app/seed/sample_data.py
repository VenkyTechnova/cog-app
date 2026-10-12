"""Deterministic sample data: users, requirements, ~80 candidates across all stages, history.

All names, clients and contact details are fictional (example.com / cognitech.example domains).
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..constants import COMFORT_CHECK_QUESTIONS, STAGES
from ..engine import documents as docsvc
from ..engine import matching
from ..engine.outreach import create_draft
from ..models import (
    Application,
    Candidate,
    CandidateFolder,
    ComplianceFlag,
    ConsentRecord,
    DataQualitySnapshot,
    DocumentItem,
    DocumentRequest,
    DuplicatePair,
    FollowUp,
    HabitFlag,
    Interaction,
    OutboundEmail,
    RecruitmentPost,
    Requirement,
    StageTransition,
    Ticket,
    User,
    Workflow,
    WorkflowRun,
)
from ..storage import get_storage
from ..models import uid
from ..util import body_hash, normalize_linkedin, now

USERS = [
    ("Dana Whitfield", "dana.whitfield@cognitech.example", "ta_lead"),
    ("Priya Raman", "priya.raman@cognitech.example", "recruiter"),
    ("Marcus Bell", "marcus.bell@cognitech.example", "recruiter"),
    ("Sofia Alvarez", "sofia.alvarez@cognitech.example", "recruiter"),
    ("Ravi Menon", "ravi.menon@cognitech.example", "coordinator"),
    ("Olivia Chen", "olivia.chen@cognitech.example", "payroll"),
    ("Jordan Brooks", "jordan.brooks@cognitech.example", "immigration"),
    ("Grace Kim", "grace.kim@cognitech.example", "onboarding"),
    ("Leo Park", "leo.park@cognitech.example", "marketing"),
    ("Sam Ortiz", "sam.ortiz@cognitech.example", "admin"),
]

ARCHETYPES = {
    "java": (["Java", "Spring Boot", "Microservices", "Kafka", "AWS", "SQL", "Docker"], "Java Backend Engineer"),
    "python_data": (["Python", "SQL", "Spark", "Airflow", "AWS", "Snowflake", "dbt"], "Data Engineer"),
    "react": (["JavaScript", "TypeScript", "React", "Node.js", "GraphQL", "REST"], "Frontend Engineer"),
    "devops": (["AWS", "Kubernetes", "Terraform", "Docker", "Jenkins", "Linux", "Python"], "DevOps Engineer"),
    "dotnet": ([".NET", "C#", "Azure", "SQL", "Microservices", "REST"], ".NET Developer"),
    "qa": (["Selenium", "Java", "Cypress", "Playwright", "REST", "Jenkins"], "QA Automation Engineer"),
    "ml": (["Python", "Machine Learning", "PyTorch", "NLP", "LLM", "AWS", "SQL"], "ML Engineer"),
    "salesforce": (["Salesforce", "REST", "JavaScript", "SQL"], "Salesforce Developer"),
}

FIRST = ["Aarav", "Maya", "Ethan", "Nia", "Kenji", "Lucia", "Omar", "Hannah", "Diego", "Mei", "Samuel", "Aisha", "Noah", "Zara", "Victor",
         "Ananya", "Liam", "Fatima", "Mateo", "Chloe", "Rohan", "Grace", "Tariq", "Elena", "Jamal", "Sakura", "Arjun", "Isabel", "Kwame",
         "Leah", "Hugo", "Divya", "Owen", "Amara", "Felix", "Yara", "Nikhil", "Sophie", "Andre", "Ling"]
LAST = ["Patel", "Nguyen", "Okafor", "Garcia", "Kim", "Rossi", "Haddad", "Schmidt", "Silva", "Chen", "Mensah", "Kapoor", "Johnson",
        "Ahmed", "Novak", "Reddy", "Walsh", "Hussain", "Lopez", "Dubois", "Iyer", "Tanaka", "Osei", "Fischer", "Brown", "Sato", "Menon",
        "Moreno", "Boateng", "Levi"]
CITIES = ["Dallas, TX", "Austin, TX", "Charlotte, NC", "Atlanta, GA", "Chicago, IL", "Jersey City, NJ", "Seattle, WA", "Phoenix, AZ",
          "Columbus, OH", "Raleigh, NC", "Tampa, FL", "Denver, CO", "Edison, NJ", "Irving, TX", "Boston, MA"]
UNIS = ["University of Texas at Dallas", "Arizona State University", "Northeastern University", "University of Illinois Chicago",
        "Georgia Institute of Technology", "University of North Carolina at Charlotte", "Stevens Institute of Technology", "Purdue University"]
AUTHS = ["US Citizen", "Green Card", "H-1B", "H-4 EAD", "OPT EAD", "STEM OPT EAD", "GC EAD", "L-2 EAD"]
AVAIL = ["Immediate", "2 weeks", "1 month", "After current project (6 weeks)"]
STATUS = ["Between projects", "On a project ending next month", "Employed full-time, open to change", "Completing master's program",
          "Currently on a contract through Q4"]

REQUIREMENTS = [
    # title, client, skills, location, arrangement, type, rate, min_years, priority, hours_ago, accepted_auth
    ("Senior Java Microservices Engineer", "Northwind Financial", ["Java", "Spring Boot", "Microservices", "Kafka", "AWS"], "Charlotte, NC", "Hybrid", "W-2", "$65–72/hr", 6, "High", 5, []),
    ("Data Engineer (Snowflake / Airflow)", "Tailspin Logistics", ["Python", "SQL", "Airflow", "Snowflake", "dbt"], "Remote", "Remote", "Either", "$60–68/hr", 4, "High", 9, []),
    ("React / TypeScript Frontend Developer", "Fabrikam Retail", ["React", "TypeScript", "JavaScript", "GraphQL"], "Dallas, TX", "Onsite", "C2C", "$55–62/hr", 3, "Medium", 20, []),
    ("DevOps Engineer — Kubernetes & Terraform", "Contoso Health", ["Kubernetes", "Terraform", "AWS", "Docker", "Jenkins"], "Remote", "Remote", "W-2", "$70–78/hr", 5, "Medium", 60, ["US Citizen", "Green Card", "GC EAD", "H-1B"]),
    ("ML Engineer (NLP / LLM)", "Adventure Works AI", ["Python", "Machine Learning", "NLP", "LLM", "PyTorch"], "Seattle, WA", "Hybrid", "Either", "$80–95/hr", 4, "High", 110, []),
    ("QA Automation Engineer", "Litware Insurance", ["Selenium", "Java", "Playwright", "REST"], "Columbus, OH", "Hybrid", "W-2", "$45–52/hr", 3, "Low", 200, []),
    (".NET Core Developer (Azure)", "Proseware Energy", [".NET", "C#", "Azure", "SQL"], "Irving, TX", "Onsite", "Either", "$58–64/hr", 5, "Medium", 300, []),
    ("Salesforce Developer", "Wide World Importers", ["Salesforce", "JavaScript", "REST"], "Remote", "Remote", "C2C", "$60–66/hr", 3, "Low", 480, []),
]

STAGE_PLAN = (
    ["sourced"] * 20 + ["contacted"] * 14 + ["interested"] * 8 + ["qualified"] * 6 + ["process_explained"] * 5
    + ["docs_requested"] * 5 + ["docs_received"] * 3 + ["onboarding"] * 3 + ["marketing_pipeline"] * 4 + ["placed"] * 3
    + ["hold"] * 4 + ["not_interested"] * 3 + ["closed"] * 2
)

TINY_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n" + b" " * 1200


def seed_users(db: Session) -> dict[str, User]:
    out = {}
    for name, email, role in USERS:
        u = db.query(User).filter_by(email=email).one_or_none()
        if u is None:
            u = User(name=name, email=email, role=role)
            db.add(u)
        out[role if role not in out else email] = u
    db.flush()
    return out


def seed_sample(db: Session) -> dict:
    rnd = random.Random(42)
    t = now()
    users = {u.email: u for u in db.query(User).all()}
    recruiters = [u for u in users.values() if u.role == "recruiter"]
    lead = next(u for u in users.values() if u.role == "ta_lead")

    reqs = []
    for i, (title, client, skills, loc, arr, et, rate, yrs, prio, hours_ago, auth) in enumerate(REQUIREMENTS):
        r = Requirement(title=title, client=client, skills=skills, location=loc, work_arrangement=arr, employment_type=et, rate=rate,
                        min_years=yrs, priority=prio, accepted_work_auth=auth, owner_id=recruiters[i % 3].id,
                        description=f"{client} is looking for a {title.lower()}. Must-have: {', '.join(skills)}.",
                        created_at=t - timedelta(hours=hours_ago), source=["ats", "email_parser", "manual"][i % 3])
        db.add(r)
        reqs.append(r)
    reqs[-1].status = "filled"
    db.flush()

    names = set()
    cands: list[Candidate] = []
    for i, stage in enumerate(STAGE_PLAN):
        while True:
            fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
            if (fn, ln) not in names:
                names.add((fn, ln))
                break
        arche = rnd.choice(list(ARCHETYPES))
        pool, headline = ARCHETYPES[arche]
        skills = pool[:3] + rnd.sample(pool[3:], k=min(len(pool) - 3, rnd.randint(1, 3)))
        yrs = rnd.choice([2, 3, 4, 5, 6, 7, 8, 10, 12])
        owner = recruiters[i % 3] if stage != "sourced" or i % 4 else None
        created = t - timedelta(days=rnd.randint(2, 120))
        grad = t.year - rnd.randint(1, 8)
        auth = rnd.choice(AUTHS)
        c = Candidate(
            full_name=f"{fn} {ln}",
            email=f"{fn.lower()}.{ln.lower()}{i}@example.com",
            phone=f"{rnd.choice(['214', '469', '704', '404', '312', '201', '206', '480'])}555{rnd.randint(1000, 9999)}",
            linkedin_url=normalize_linkedin(f"linkedin.com/in/{fn.lower()}-{ln.lower()}-{i}"),
            location=rnd.choice(CITIES),
            source=rnd.choice(["LinkedIn", "LinkedIn", "Job Posting", "Cold Call", "Cold Email", "Referral", "Recruitment Post"]),
            skills=skills,
            years_experience=yrs,
            current_project_status=rnd.choice(STATUS) if stage != "sourced" else "",
            work_authorization=auth if stage not in ("sourced",) or i % 2 else "",
            availability=rnd.choice(AVAIL) if stage != "sourced" else "",
            preferred_type=rnd.choice(["W-2", "C2C", "W-2"]) if stage not in ("sourced", "contacted") else "",
            expected_compensation=rnd.choice(["$55/hr", "$60/hr", "$65/hr", "$70/hr", "$120k"]) if stage not in ("sourced", "contacted") else "",
            work_arrangement=rnd.choice(["Remote", "Hybrid", "Onsite", "Flexible"]),
            stage=stage,
            owner_id=owner.id if owner else None,
            headline=f"{headline} · {yrs} yrs",
            university=rnd.choice(UNIS),
            degree=rnd.choice(["MS Computer Science", "MS Information Systems", "BS Computer Engineering", "MS Data Science"]),
            grad_year=grad,
            past_projects=f"Built {skills[0]} services for a {rnd.choice(['banking', 'healthcare', 'retail', 'logistics'])} client. "
                          f"Migrated workloads to {rnd.choice(['AWS', 'Azure', 'Kubernetes'])}. Led a team of {rnd.randint(2, 6)} engineers.",
            career_goals=rnd.choice(["Wants to grow into a lead role", "Looking to work on cloud-native systems", "Open to relocation for the right project", "Prefers long-term contracts"]),
            created_at=created,
            retention_expires_at=created + timedelta(days=730),
        )
        if stage in ("qualified", "process_explained", "docs_requested", "docs_received", "onboarding", "marketing_pipeline", "placed"):
            c.work_authorization = c.work_authorization or auth
            c.availability = c.availability or "2 weeks"
            c.preferred_type = c.preferred_type or "W-2"
            c.qualification_decision = "qualified"
        if stage == "sourced" and i % 5 == 0:
            c.phone = None
        db.add(c)
        cands.append(c)
    db.flush()

    # Seed a few intentional duplicates (for the merge queue).
    dup_src = [cands[3], cands[17]]
    for src in dup_src:
        d = Candidate(full_name=src.full_name, email=src.email.upper().lower(), phone=None, location=src.location, source="Job Posting",
                      skills=src.skills[:2], stage="sourced", created_at=t - timedelta(days=1), retention_expires_at=t + timedelta(days=729))
        db.add(d)
        db.flush()
        db.add(DuplicatePair(candidate_a_id=src.id, candidate_b_id=d.id, matched_on=["email"]))

    # Matches for every open requirement.
    for r in reqs:
        if r.status == "open":
            for c in cands:
                matching.upsert_match(db, c, r, reengagement=c.stage in ("hold", "not_interested", "closed"))
    for c in cands:
        best = max((matching.score(c, r)[0] for r in reqs if r.status == "open"), default=None)
        c.fit_score = best
    db.flush()

    stage_index = {s: i for i, s in enumerate(STAGES)}
    for c in cands:
        owner_id = c.owner_id
        created = c.created_at
        # Stage history.
        path = []
        if c.stage in STAGES:
            path = STAGES[1 : stage_index[c.stage] + 1]
        elif c.stage == "placed":
            path = STAGES[1:] + ["placed"]
        else:
            path = ["contacted", "interested"][: rnd.randint(1, 2)] + [c.stage]
        span = max((t - created).days - 1, len(path) + 1)
        prev = "sourced"
        for j, s in enumerate(path):
            at = created + timedelta(days=int(span * (j + 1) / (len(path) + 1)))
            db.add(StageTransition(candidate_id=c.id, from_stage=prev, to_stage=s, trigger="seed", user_id=owner_id, at=at))
            db.add(Interaction(candidate_id=c.id, user_id=owner_id, type="stage_change", subject=f"{prev} → {s}", meta={"from": prev, "to": s}, occurred_at=at))
            prev = s
        # Touchpoints.
        if c.stage != "sourced":
            for k in range(rnd.randint(1, 4)):
                at = t - timedelta(days=rnd.randint(0, 25), hours=rnd.randint(0, 8))
                kind = rnd.choice(["call", "call", "email_out", "linkedin_connection", "linkedin_message"])
                meaningful = kind == "call" and rnd.random() > 0.35
                db.add(Interaction(candidate_id=c.id, user_id=owner_id, type=kind, direction="out",
                                   subject={"call": "Call", "email_out": "Intro email", "linkedin_connection": "LinkedIn connection request", "linkedin_message": "LinkedIn message"}[kind],
                                   body="Discussed current project and interest in new roles." if meaningful else "",
                                   outcome="connected" if meaningful else ("no_answer" if kind == "call" else None), meaningful=meaningful, occurred_at=at))
                if kind == "email_out":
                    db.add(OutboundEmail(id=uid(), to_email=c.email, subject="Intro from Cognitech", text="…", kind="candidate", candidate_id=c.id, user_id=owner_id,
                                         status="sent", body_hash=body_hash(f"seed{c.id}{k}"), sent_at=at, created_at=at,
                                         opened_at=at + timedelta(hours=2) if rnd.random() > 0.4 else None))
                c.last_contact_at = max(filter(None, [c.last_contact_at, at]))
        # Comfort check + consent for gated stages.
        if c.stage in ("docs_requested", "docs_received", "onboarding", "marketing_pipeline", "placed"):
            c.w2_c2c_explained = True
            c.process_explained_at = created + timedelta(days=5)
            c.comfort_check = {"answers": [{"q": q, "answer": "yes"} for q in COMFORT_CHECK_QUESTIONS], "completed_at": (created + timedelta(days=5)).isoformat(), "by": owner_id, "all_yes": True}
            db.add(ConsentRecord(candidate_id=c.id, consent_type="proceed", status="granted", method="e-consent", ip="203.0.113.10",
                                 user_agent="Mozilla/5.0", requested_by=owner_id, requested_at=created + timedelta(days=5), recorded_at=created + timedelta(days=6),
                                 consent_text="I confirm I would like to proceed with Cognitech's process."))
        elif c.stage == "process_explained":
            c.w2_c2c_explained = True
            c.process_explained_at = t - timedelta(days=1)

    db.flush()

    # Documents for doc stages.
    storage = get_storage()
    for idx, c in enumerate([c for c in cands if c.stage in ("docs_requested", "docs_received", "onboarding", "marketing_pipeline", "placed")]):
        folder = docsvc.ensure_folder(db, c)
        days_ago = 5 if c.stage == "docs_requested" and idx % 2 == 0 else 1
        req = DocumentRequest(candidate_id=c.id, created_at=t - timedelta(days=days_ago), expires_at=t + timedelta(days=14 - days_ago))
        db.add(req)
        db.flush()
        for n, d in enumerate(docsvc.build_checklist(c)):
            label, fold, exp, handled = docsvc.DOC_TYPES[d]
            item = DocumentItem(request_id=req.id, candidate_id=c.id, doc_type=d, label=label, folder=fold, needs_expiry=exp, handled_by=handled)
            uploaded = c.stage != "docs_requested" or n < 2
            if uploaded:
                key = f"{folder.path}/{fold}/{d}-seed.pdf"
                storage.put(key, TINY_PDF)
                item.storage_key, item.filename, item.content_type, item.size_bytes = key, f"{d}.pdf", "application/pdf", len(TINY_PDF)
                item.uploaded_at = t - timedelta(days=days_ago - 0.5)
                item.expiry_date = date(t.year + 3, 6, 30) if exp else None
                item.status = "verified" if c.stage in ("onboarding", "marketing_pipeline", "placed") else "uploaded"
                item.validation = {"ok": True, "errors": [], "warnings": []}
            db.add(item)
        if c.stage == "docs_requested":
            req.reminders_sent = 2 if days_ago == 5 else 0
            req.last_reminder_at = t - timedelta(days=1) if days_ago == 5 else None
        elif c.stage == "docs_received":
            req.status = "complete"
            req.completed_at = t - timedelta(hours=10)
        else:
            req.status = "verified"
            req.completed_at = t - timedelta(days=3)
    db.flush()

    # Follow-ups: due today, overdue and upcoming; plus some completed last week.
    for n, c in enumerate([c for c in cands if c.stage in STAGES and c.stage != "sourced" and c.owner_id]):
        choice = n % 5
        if choice == 0:
            due = t.replace(hour=15, minute=0, second=0, microsecond=0)  # today (UTC afternoon ≈ late morning ET)
        elif choice == 1:
            due = t - timedelta(days=rnd.randint(1, 5))
        else:
            due = t + timedelta(days=rnd.randint(1, 6))
        db.add(FollowUp(candidate_id=c.id, owner_id=c.owner_id, due_at=due, reason=f"{c.stage.replace('_', ' ').title()} follow-up", rule="stage_cadence"))
        c.next_follow_up_at = due
        past_due = t - timedelta(days=rnd.randint(1, 6))
        done_on_time = rnd.random() > 0.25
        db.add(FollowUp(candidate_id=c.id, owner_id=c.owner_id, due_at=past_due, reason="Check-in", rule="stage_cadence", status="done",
                        completed_at=past_due + timedelta(hours=3 if done_on_time else 60)))

    # Hot replies (interested, not yet contacted).
    hot = [c for c in cands if c.stage == "interested"][:3]
    for k, c in enumerate(hot):
        at = t - timedelta(hours=6 + k * 5)
        c.hot_reply, c.hot_reply_at, c.last_reply_class, c.last_reply_at = True, at, "interested", at
        body = ["Hi, yes I'm interested — can we talk tomorrow afternoon?", "Sounds great, please share the details. I'm open to a call.", "Thanks for reaching out! I'd love to hear more about the role."][k]
        db.add(Interaction(candidate_id=c.id, type="email_in", direction="in", subject="Re: opportunity", body=body, outcome="interested", meaningful=True, occurred_at=at))

    # New inbound applicants in the last 24h + a couple older.
    applicants = [c for c in cands if c.stage == "sourced"][:8]
    for k, c in enumerate(applicants):
        r = reqs[k % 3]
        c.source = "Job Posting"
        c.created_at = t - timedelta(hours=2 + k * 3) if k < 6 else t - timedelta(days=3)
        m = matching.score(c, r)[0]
        db.add(Application(candidate_id=c.id, requirement_id=r.id, source=rnd.choice(["Indeed", "Dice", "LinkedIn Jobs", "Company careers page"]),
                           fit_score=m, shortlist_status="suggested" if m >= 70 else "pending", created_at=c.created_at))

    # Past candidates last contacted long ago → re-engagement candidates.
    for c in cands:
        if c.stage in ("hold", "not_interested", "closed"):
            c.last_contact_at = t - timedelta(days=rnd.randint(100, 200))

    # Tickets.
    by_stage = lambda s: [c for c in cands if c.stage == s]
    pc = by_stage("process_explained")[0]
    db.add(Ticket(team="payroll", kind="candidate_question", subject=f"Payroll question: {pc.full_name}", description="Candidate asked how the payroll schedule works for W-2 consultants.",
                  candidate_id=pc.id, requested_by=pc.owner_id, sla_hours=24, due_at=t + timedelta(hours=9), candidate_acknowledged=True, created_at=t - timedelta(hours=15)))
    ic = by_stage("qualified")[0]
    db.add(Ticket(team="immigration", kind="candidate_question", subject=f"Candidate question: {ic.full_name}", description="Candidate asked about training-plan paperwork for their work authorization.",
                  candidate_id=ic.id, requested_by=ic.owner_id, sla_hours=48, due_at=t - timedelta(hours=3), breached=True, breach_notified=True, created_at=t - timedelta(hours=51)))
    for c in by_stage("docs_received"):
        db.add(Ticket(team="onboarding", kind="document_verification", subject=f"Verify documents: {c.full_name}", description="All required documents uploaded and passed automated checks.",
                      candidate_id=c.id, sla_hours=24, due_at=t + timedelta(hours=14), created_at=t - timedelta(hours=10)))
    mk = Ticket(team="marketing", kind="recruitment_post", subject="LinkedIn post: Data Engineer (Snowflake / Airflow)", description="Remote data engineering role — please create a post.",
                requested_by=recruiters[1].id, sla_hours=72, due_at=t + timedelta(hours=60), created_at=t - timedelta(hours=12))
    db.add(mk)
    db.flush()
    db.add(RecruitmentPost(title="We're hiring: Data Engineer (Snowflake / Airflow) — Remote", channel="LinkedIn", requirement_id=reqs[1].id, status="in_review", ticket_id=mk.id,
                           requested_by=recruiters[1].id,
                           body="Cognitech Technologies is hiring a Data Engineer to build modern data pipelines with Python, Airflow, Snowflake and dbt. Remote (US). Interested? Comment or message us.",
                           checklist={"accurate": True, "clear": True, "consistent_with_process": False, "no_pay_or_immigration_claims": True, "disclaimer": False}))
    db.flush()

    # Drafts awaiting approval (created through the normal draft service so compliance runs).
    for c in cands[20:24]:
        create_draft(db, "cold_email", c, reqs[0] if "Java" in c.skills else reqs[1], db.get(User, c.owner_id) if c.owner_id else recruiters[0])
    for c in [x for x in cands if x.stage == "sourced" and x.owner_id][:3]:
        create_draft(db, "linkedin_note", c, reqs[1], db.get(User, c.owner_id))
    for c in [x for x in cands if x.stage in ("hold", "closed")][:2]:
        create_draft(db, "reengagement", c, reqs[0], db.get(User, c.owner_id) if c.owner_id else recruiters[0])
    bad = create_draft(db, "follow_up", cands[25], reqs[1], recruiters[0])
    bad.body = bad.body.replace("Just following up", "Good news — your H-1B transfer will be approved quickly and you will be paid every Friday. Just following up")
    from ..engine.outreach import update_draft

    update_draft(db, bad, None, bad.body)
    db.add(ComplianceFlag(candidate_id=cands[25].id, user_id=recruiters[0].id, source_type="draft", source_id=str(bad.id), category="immigration", matched_text="H-1B", severity="block"))
    db.add(ComplianceFlag(candidate_id=cands[26].id, user_id=recruiters[1].id, source_type="note", source_id="seed", category="pay_promise", matched_text="paid every two weeks", severity="review"))

    # Habit flags for the manager queue.
    samples = [
        ("missed_follow_up", recruiters[0], cands[30], "Follow-up 'Contacted follow-up' overdue since last Tuesday"),
        ("generic_message", recruiters[1], cands[31], "Cold email approved with no personal detail"),
        ("pressuring_language", recruiters[2], cands[32], "'decide today' in a follow-up draft"),
        ("stale_record", recruiters[1], cands[33], "No activity in 34 days"),
        ("immigration_advice", recruiters[0], cands[25], "Immigration language in draft (blocked)"),
    ]
    for h, u, c, detail in samples:
        db.add(HabitFlag(habit=h, user_id=u.id, candidate_id=c.id, detail=detail, dedupe_key=f"seed:{h}:{c.id}", created_at=t - timedelta(days=rnd.randint(0, 5))))

    # Data-quality trend.
    for k in range(14, 0, -1):
        db.add(DataQualitySnapshot(snapshot_date=(t - timedelta(days=k)).date(), score=round(71 + (14 - k) * 0.9 + rnd.uniform(-1.5, 1.5), 1),
                                   metrics={"accuracy": 0.9, "duplicate_rate": 0.02, "stale_rate": 0.12, "follow_up_compliance": 0.78, "document_completeness": 0.6}))

    # Workflow run history (last 7 days) so the automation-impact panel has measured data.
    wfs = {w.key: w for w in db.query(Workflow).all()}
    volume = {"match_on_create": 60, "save_and_dedupe": 60, "inbound_application_intake": 25, "shortlist_inbound": 25, "daily_call_list": 5,
              "reply_classification": 30, "sequence_sender": 200, "stage_follow_up_cadence": 70, "stage_on_outreach": 45, "stage_on_call": 40,
              "follow_up_reminders": 5, "document_reminders": 120, "request_documents_on_consent": 5, "documents_complete": 3, "verification_queue": 3,
              "move_to_onboarding": 2, "reengage_on_requirement": 4, "process_summary_email": 5, "consent_after_comfort_check": 5, "daily_digest": 5,
              "sla_monitor": 600, "nightly_data_quality": 7, "habit_monitor": 7, "vendor_conflict_check": 8, "intro_on_connect": 12}
    for key, n in volume.items():
        w = wfs.get(key)
        if not w:
            continue
        for _ in range(n):
            db.add(WorkflowRun(workflow_id=w.id, status="completed", detail={"seeded": True}, at=t - timedelta(hours=rnd.uniform(1, 160))))
        w.run_count = (w.run_count or 0) + n
        w.last_run_at = t - timedelta(hours=1)
    db.flush()
    return {"candidates": len(cands) + len(dup_src), "requirements": len(reqs)}
