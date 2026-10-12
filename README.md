# Cognitech Recruiter Workflow Automation Platform

A web app for Cognitech Technologies' Talent Acquisition team. It maps every recurring task in the Recruiter Playbook to **Automate / Delegate / Simplify / Keep Human**, runs the workflows that go with each category, and sends every recruiter a **daily "New Opportunities" digest**.

> *Standardize, so the conversation can be human.* The platform automates the admin around the recruiter. It never automates trust, judgment, or compliance-sensitive explanations.

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL · Postgres-backed job queue + cron scheduler · React 18 · Vite · Tailwind · Recharts.

---

## Quick start

### Option A — Docker (everything)

```bash
cp .env.example .env
docker compose up --build
```

* App: http://localhost:5173 (pick a demo user on the sign-in screen)
* API docs: http://localhost:8000/docs
* Outgoing email (Mailhog): http://localhost:8025

The API container seeds the task map, workflows, templates and sample data on first start. The `worker` container runs the scheduler and job queue.

### Option B — local dev

```bash
# Postgres running locally with a cognitech/cognitech user and a `cognitech` database
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env
python -m app.seed.run                 # --reset to rebuild, --no-sample for reference data only
uvicorn app.main:app --reload          # EMBEDDED_WORKER=true runs the scheduler in-process

cd ../frontend
npm install
npm run dev                            # http://localhost:5173 (proxies /api to :8000)
```

### Demo users (dev sign-in)

| User | Role |
|---|---|
| Priya Raman, Marcus Bell, Sofia Alvarez | Recruiter |
| Dana Whitfield | TA Lead (gets the team rollup digest + weekly report) |
| Ravi Menon | Coordinator |
| Olivia Chen / Jordan Brooks / Grace Kim / Leo Park | Payroll / Immigration / Onboarding / Marketing |
| Sam Ortiz | Admin |

All sample people, clients and addresses are fictional (`example.com`, `cognitech.example`).

---

## What's in the box

| Brief item | Where |
|---|---|
| Task map (56 tasks, one category each, editable) | **Task Map** — table + kanban, "why" rationale, inline editor, hours saved. Seed: `backend/app/seed/task_map.py` |
| Workflows for every Automate task | **Workflow Builder** — 32 pre-built workflows + template gallery + read-only guardrails. Seed: `backend/app/seed/workflows.py` |
| Visual trigger → condition → action editor | **Workflow Builder → workflow** — dry-run against a real candidate, run-now for scheduled flows, run log |
| Recruiter Home | Call list, hot replies, follow-ups (today / overdue), drafts awaiting approval, new applicants, delegated tickets |
| Candidate 360 | 18 fields, 10-stage progress with consent/document gates, timeline, call guide (10 checkpoints / 11 topics / W-2 vs C2C talking points), call-outcome form with transcript pre-fill, 12-field qualification + human decision, process → comfort check → e-consent, documents, drafts & sequences, tickets |
| Pipeline board | 10-stage kanban, drag-and-drop, required reason on manual moves |
| Delegation Center | Payroll / Immigration / Onboarding / Marketing / Coordinator tickets with live SLA timers; recruitment-post checklist gate |
| Analytics | Activity, quality, pipeline, data-quality dashboards (+ per-recruiter) |
| Automation Impact report | **Impact** — tasks by category, hours before vs after per recruiter per week, measured hours from workflow runs |
| Compliance & Audit | Consent log, flagged advice keywords, habits review queue, retention/purge queue, access & audit log |
| Settings | Digest time & rules, personal digest preferences + preview + test send + delivery log, email templates, follow-up cadences, guardrail limits, integrations, users & roles |
| Daily digest | `backend/app/digest/` — per-recruiter + TA-lead rollup, HTML + plain text, one-click actions, tracking, unsubscribe |
| Weekly management report | `backend/app/reports/weekly.py` — Monday 8 AM PDF + email |
| Document portal / e-consent | `/portal/:token`, `/consent/:token` (public, mobile-first) |
| Schema, API docs | [`docs/SCHEMA.md`](docs/SCHEMA.md), [`docs/API.md`](docs/API.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Tests | `backend/tests/` — 95 tests: triggers, stage transitions, reminders, digest, compliance, API |

### Automation impact (seed estimates)

| Category | Tasks |
|---|---|
| Automate | 29 |
| Simplify | 13 |
| Keep Human | 10 |
| Delegate | 4 |

Estimated recurring task time per recruiter: **39.8 h/week → 19.6 h/week (20.2 h saved, ~51%)**. These are editable estimates in the Task Map; the Impact page also shows *measured* hours from workflow runs (runs × minutes saved per run). Keep Human tasks save little by design.

---

## The daily "New Opportunities" digest

* **When:** every business day at **7:30 AM ET** (Settings → Digest; stored as the `daily_digest` workflow's cron).
* **Who:** each recruiter gets their own digest; TA leads get a team rollup (per-recruiter due/overdue/hot/docs table, breached tickets, data-quality score).
* **Sections, in order:** new requirements (last 24h; since the last digest on Mondays, max 72h) → top 5 matches per requirement from the database, including re-engagement candidates → new inbound applicants ranked by fit → hot replies not yet contacted → follow-ups due today + overdue → pending documents past SLA → one-click **Call / Draft Email / Snooze / Not a Fit** buttons on every candidate.
* **Rules:** nothing new → a short "no new opportunities" note, or skip (setting `digest.when_empty`). HTML + plain-text fallback, mobile-friendly. Delivery is logged; opens (pixel) and clicks (redirector) are tracked; per-user section preferences and an unsubscribe link.
* **Sources:** requirements table fed by the UI, ATS/job-board webhook, CSV / Google Sheets import, and the email parser for client requirement emails sent to `requirements@…`.
* Preview any time: Settings → Digest → *Preview my digest*, or `GET /api/digest/preview`.

---

## Guardrails (enforced in code for every caller)

1. **No automated pay / tax / immigration statements.** Outbound drafts and every automated email are scanned (`engine/compliance.py`). Immigration or legal advice, pay dates or amounts, and tax statements block the message and suggest routing to Payroll or the authorized team (one click creates the ticket and an acknowledgment that says who will reply and when, without answering the question). Notes are flagged for review, never blocked.
2. **Comfort check + consent gate.** No stage from Docs Requested onward until the 5-question comfort check is complete and e-consent is recorded. Manual overrides included; attempts are flagged as a "habit worth breaking". Onboarding also requires every required document to be verified.
3. **Outreach caps.** Max emails per candidate per 7 days, minimum gap, identical messages blocked, sequences stop on any reply, unsubscribe honoured everywhere.
4. **Human approval for personalized outreach.** Workflows can only auto-send templates marked `auto_send_allowed` (process summary, document checklist/reminders, consent link, acknowledgments, onboarding notice). LinkedIn messages are never sent by the system (LinkedIn ToS): the recruiter copies the draft and marks it sent.
5. **"Not a final employment commitment"** is appended to opportunity and offer-related messages until the candidate is Placed.
6. **Data protection.** Documents encrypted at rest; role-based access; audit log for writes and sensitive reads; retention dates and a purge queue; rule-based document checklists (no free-form requests).

---

## Integrations

| Integration | How |
|---|---|
| ATS / job boards | `POST /api/webhooks/application`, `POST /api/webhooks/requirement` (HMAC or shared secret) |
| Recruiter mailboxes (Gmail / Microsoft 365) | A push adapter (Gmail Pub/Sub watch, or Graph change notifications) fetches each new message and posts it to `POST /api/webhooks/inbound-email`. SendGrid Inbound Parse can post directly. Replies are classified; mail to `requirements@` becomes a requirement. |
| System email | `MAIL_BACKEND=smtp` (Microsoft 365 relay, Mailhog), `sendgrid` or `ses` |
| LinkedIn | Profile import (CSV/JSON the recruiter exports) + manual sending only |
| Google Sheets / CSV | Requirements → Import CSV |
| AI | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` for richer drafts; default `template` needs no external calls |
| Storage | Local encrypted, or S3/MinIO (`STORAGE_BACKEND=s3`) |
| SSO | `AUTH_MODE=oidc` with issuer / client id (Okta, Entra ID, Google Workspace) |
| Calendar, e-signature, telephony | Hooks are in place (`meeting` interactions, offer-letter document item, call logging API); connectors are not included in this build |

---

## Tests

```bash
cd backend
pytest                                                                                   # SQLite
TEST_DATABASE_URL=postgresql+psycopg2://cognitech:cognitech@localhost:5432/cognitech_test pytest   # PostgreSQL
```

Covers: event → workflow triggers (matching, dedupe, applications, reply classes, delegation, consent → documents → onboarding, re-engagement, retries), the stage machine and every guardrail, document reminders and escalation, sequences, SLA breaches, the scheduler (7:30 ET weekdays only, dedupe, settings change), digest content/scoping/rollup/empty rules/idempotency/tracking/one-click actions/unsubscribe, compliance scanning, and API roles, portal encryption, webhooks and audit logging.

---

## Assumptions to confirm with the TA team

The brief summarised some playbook sections rather than listing them. These are the readings used; each lives in one place and is easy to change:

* **The 18 database fields and 12 qualification fields**: `backend/app/constants.py` (`DATABASE_FIELDS`, `QUALIFICATION_FIELDS`).
* **The 13 "habits worth breaking"**, the **5 comfort-check questions**, the **10 cold-call checkpoints** and the **8 process items**: `constants.py`.
* **Document rules** by work authorization × W-2/C2C: `engine/documents.py` (`WORK_AUTH_DOCS`, `TYPE_DOCS`). Candidate-facing labels avoid immigration form names; Immigration coordinates the training-plan form.
* **SLAs:** Payroll 24h, Immigration 48h, Onboarding 24h, Marketing 72h, Coordinator 24h (`constants.TEAMS`).
* **Minute estimates** per task are editable starting points, not measurements.
* W-2 / C2C talking points and all templates should be reviewed by Cognitech's legal and payroll owners before go-live.
