# Architecture

```
            ┌──────────────────────────── React (Vite + Tailwind) ────────────────────────────┐
            │ Task Map · Workflow Builder · Recruiter Home · Candidate 360 · Pipeline ·       │
            │ Delegation · Analytics · Impact · Compliance · Settings · Portal · Consent      │
            └──────────────────────────────────────┬──────────────────────────────────────────┘
                                                   │ REST (JSON), bearer token (dev or OIDC SSO)
┌──────────────────────────────────────────────────▼──────────────────────────────────────────────────┐
│ FastAPI                                                                                              │
│  routers/  → thin HTTP layer, role checks, audit logging                                             │
│  engine/   → domain logic                                                                            │
│    events.py     event bus: emit(type, …) → matching workflows → actions (inline in a SAVEPOINT,     │
│                  or queued when delayed / on failure)                                                │
│    actions.py    action registry (score, draft, send_template, advance_stage, create_ticket, …)      │
│    queue.py      Postgres job queue (SKIP LOCKED, retries with backoff, dedupe keys)                 │
│    stages.py     10-stage state machine + non-negotiable guardrails                                  │
│    compliance.py pay / tax / immigration scanner, outreach caps, disclaimer                          │
│    matching.py   explainable 0-100 match score                                                       │
│    documents.py  rule-based checklists, validation, reminders, verification                          │
│    outreach.py   drafts, approval, sequences                                                         │
│    habits.py     13 "habits worth breaking"                                                          │
│    analytics.py  activity / quality / pipeline / data-quality / impact                              │
│    ai.py         template provider (default) or Claude; parsing, drafts, reply classification        │
│  digest/   → daily digest builder + Jinja HTML/text templates + sender                              │
│  reports/  → weekly PDF (ReportLab)                                                                  │
│  scheduler.py → minute tick: fires `schedule` workflows whose cron matches (local time), runs queue  │
└───────┬───────────────────────────────┬───────────────────────────────┬─────────────────────────────┘
        │                               │                               │
   PostgreSQL                 Encrypted document store          Email transport
 (all state, queue,          (local Fernet, or S3 with SSE      (console / SMTP / SendGrid / SES)
  audit, events)               + client-side Fernet)
```

## Why these choices

* **Everything is an event.** Intake, replies, calls, consent, uploads and verifications all `emit()`. Workflows subscribe to events, so every Automate task in the Task Map has a visible, pausable, testable implementation in the Workflow Builder instead of hidden code paths.
* **Guardrails live in code, not in workflows.** The consent gate, compliance scanner, outreach caps, rule-based checklists and LinkedIn "draft only" rule are enforced in the engine for every caller (API, workflow, job). An admin can't switch them off from the UI; they're listed read-only as "Guardrails".
* **Postgres queue instead of Redis/Celery.** One less moving part for a team this size. `enqueue()` / `run_due_jobs()` is a small interface: swapping in Celery, BullMQ or Temporal means reimplementing two functions.
* **Deterministic AI by default.** Match scores are a transparent formula; drafts come from editable templates. Turning on `LLM_PROVIDER=anthropic` improves personalization, but output still goes through the compliance scanner and human approval, and the numbers never change.
* **Inline + retry.** Immediate actions run inside a SAVEPOINT so the UI reflects them instantly. If one fails, only that action is rolled back and re-queued with backoff.

## Event catalogue

| Event | Emitted when |
|---|---|
| candidate.created / candidate.imported / candidate.updated | Intake from any channel (after dedupe) |
| application.received | ATS / job-board webhook, careers page |
| requirement.created | UI, ATS webhook, CSV import, `requirements@` email parser |
| stage.changed | Every transition (auto or manual) |
| linkedin.connected | Recruiter marks the connection accepted |
| email.sent / email.reply_received | Outreach sent / inbox webhook (classified) |
| call.logged, qualification.saved, process.explained, comfort_check.completed | Recruiter actions |
| consent.recorded | Candidate grants e-consent |
| document.uploaded, documents.complete, document.verified, documents.verified | Portal + Onboarding |
| ticket.created, post.engagement, note.saved | Delegation / posts / notes |
| schedule | Cron tick for scheduled workflows |

## Scheduled workflows (defaults, America/New_York)

| Workflow | Cron |
|---|---|
| Daily call lists | `30 6 * * mon-fri` |
| Follow-up reminders | `0 7 * * mon-fri` |
| **Daily New Opportunities digest** | `30 7 * * mon-fri` (Settings → Digest time) |
| Email sequence sender | `*/15 7-18 * * mon-fri` |
| Document reminders | `0 * * * *` |
| SLA monitor | `*/15 * * * *` |
| Retention sweep | `30 1 * * *` |
| Nightly data-quality score | `0 2 * * *` |
| Habit monitor | `15 2 * * *` |
| Weekly management report | `0 8 * * mon` |
| Weekly duplicate scan | `0 6 * * sun` |
| Nurture check-in drafts | `0 9 * * tue` |

The scheduler dedupes per workflow per minute, so running more than one worker is safe.

## Security & privacy

* Documents encrypted at rest (Fernet; S3 also uses SSE-KMS). Files are never emailed; candidates upload through a personal, expiring portal link.
* Role-based access to candidates (team roles only see candidates linked to their tickets); documents readable only by the owning recruiter, Onboarding and TA leads.
* Audit log for every write and every sensitive read (candidate views, document downloads, logins, overrides).
* Consent is recorded with timestamp, IP and user agent. Retention dates are set on create; the nightly sweep queues expired records; purge anonymises personal fields and deletes stored files.
* Signed, expiring tokens for digest actions and unsubscribe links; the click tracker refuses non-app URLs (no open redirects).
