# API reference

Base URL: `http://localhost:8000`. Interactive docs (Swagger UI): `/docs`. OpenAPI JSON: `/openapi.json`.

## Authentication

* **Dev** (`AUTH_MODE=dev`): `POST /api/auth/login {"email": "priya.raman@cognitech.example"}` → `{token}`. Send `Authorization: Bearer <token>`.
* **SSO** (`AUTH_MODE=oidc`): send the IdP ID token as the bearer token; it is verified against the issuer's JWKS and mapped to a user by email.
* **Public** endpoints (`/api/public/*`, `/api/t/*`) are authorised by unguessable tokens (portal, consent) or HMAC-signed tokens (digest actions, unsubscribe).
* **Webhooks** (`/api/webhooks/*`) need `X-Webhook-Secret: <WEBHOOK_SECRET>` or `X-Signature: sha256=<hex HMAC-SHA256 of the raw body>`.

## Roles

| Role | Access |
|---|---|
| recruiter | Own work queue; all candidates; drafts; documents of candidates they own |
| ta_lead | Everything a recruiter can do + Task Map / workflow / settings edits, compliance & habit review, team views |
| coordinator | Candidate + requirement work, coordinator tickets |
| payroll / immigration / onboarding / marketing | Their team's tickets and only the candidates linked to those tickets; onboarding verifies documents |
| admin | Everything, including users and deletes |

## Errors

Errors return `{"detail": ...}`. Guardrail refusals return **422** with `{"detail": {"message": "...", "code": "consent_required" | "comfort_check_required" | "documents_unverified" | "reason_required" | "qualification_incomplete" | ...}}`.

## Endpoints

### Auth

| Method | Path | Summary |
|---|---|---|
| GET | `/api/auth/config` | Auth Config |
| GET | `/api/auth/dev-users` | Dev Users |
| POST | `/api/auth/login` | Login |
| GET | `/api/me` | Me |
| GET | `/api/notifications` | Notifications |
| POST | `/api/notifications/read` | Read All |
| GET | `/api/users` | Users |
| POST | `/api/users` | Create User |
| PATCH | `/api/users/{uid}` | Update User |

### Task Map

| Method | Path | Summary |
|---|---|---|
| GET | `/api/tasks` | List Tasks |
| POST | `/api/tasks` | Create Task |
| GET | `/api/tasks/impact` | Impact Report |
| DELETE | `/api/tasks/{tid}` | Delete Task |
| PATCH | `/api/tasks/{tid}` | Update Task |

### Requirements

| Method | Path | Summary |
|---|---|---|
| GET | `/api/requirements` | List Requirements |
| POST | `/api/requirements` | Create |
| POST | `/api/requirements/import` | CSV or a Google Sheets 'Download as CSV' export. Columns: title, client, skills, location, |
| GET | `/api/requirements/{rid}` | Get |
| PATCH | `/api/requirements/{rid}` | Update |
| POST | `/api/requirements/{rid}/matches/{cid}` | Set Match Status |
| POST | `/api/requirements/{rid}/post-request` | Request Post |
| POST | `/api/requirements/{rid}/rematch` | Rematch |

### Candidates

| Method | Path | Summary |
|---|---|---|
| GET | `/api/candidates` | List Candidates |
| POST | `/api/candidates` | Create Candidate |
| POST | `/api/candidates/import` | Import LinkedIn profiles exported by the recruiter (CSV or JSON). Nothing is scraped or sent. |
| GET | `/api/candidates/meta` | Meta |
| POST | `/api/candidates/parse-resume` | Parse Resume |
| GET | `/api/candidates/{cid}` | Get 360 |
| PATCH | `/api/candidates/{cid}` | Update Fields |
| POST | `/api/candidates/{cid}/calls` | Log Call |
| POST | `/api/candidates/{cid}/comfort-check` | Comfort Check |
| POST | `/api/candidates/{cid}/consent/request` | Request Consent |
| POST | `/api/candidates/{cid}/decision` | Keep Human: the recruiter decides. The system only validates required fields. |
| POST | `/api/candidates/{cid}/delegate` | Delegate |
| GET | `/api/candidates/{cid}/documents/checklist-preview` | Checklist Preview |
| POST | `/api/candidates/{cid}/documents/request` | Request Docs |
| GET | `/api/candidates/{cid}/documents/{item_id}/download` | Download |
| POST | `/api/candidates/{cid}/documents/{item_id}/verify` | Verify |
| POST | `/api/candidates/{cid}/drafts` | New Draft |
| POST | `/api/candidates/{cid}/follow-ups` | Add Follow Up |
| POST | `/api/candidates/{cid}/follow-ups/{fid}/done` | Done Follow Up |
| POST | `/api/candidates/{cid}/linkedin-status` | Linkedin Status |
| POST | `/api/candidates/{cid}/notes` | Add Note |
| POST | `/api/candidates/{cid}/process-explained` | Process Explained |
| POST | `/api/candidates/{cid}/qualification` | Save Qualification |
| POST | `/api/candidates/{cid}/sequence` | New Sequence |
| POST | `/api/candidates/{cid}/snooze` | Snooze |
| POST | `/api/candidates/{cid}/stage` | Move Stage |
| POST | `/api/candidates/{cid}/summarize-call` | Summarize |
| GET | `/api/duplicates` | Duplicate Queue |
| POST | `/api/duplicates/{pid}/dismiss` | Dismiss Pair |
| POST | `/api/duplicates/{pid}/merge` | Merge Pair |

### Outreach

| Method | Path | Summary |
|---|---|---|
| POST | `/api/applications/{aid}/shortlist` | Shortlist |
| POST | `/api/call-list/rebuild` | Rebuild Call List |
| POST | `/api/call-list/{iid}` | Call List Status |
| GET | `/api/drafts` | List Drafts |
| PATCH | `/api/drafts/{did}` | Edit Draft |
| POST | `/api/drafts/{did}/approve` | Approve Draft |
| POST | `/api/drafts/{did}/mark-sent` | Mark Sent |
| POST | `/api/drafts/{did}/reject` | Reject Draft |
| GET | `/api/home` | Home |
| GET | `/api/pipeline` | Pipeline |
| GET | `/api/sequences/{sid}` | Get Sequence |
| POST | `/api/sequences/{sid}/stop` | Stop Sequence |

### Workflows

| Method | Path | Summary |
|---|---|---|
| GET | `/api/workflows` | List Workflows |
| POST | `/api/workflows` | Create Workflow |
| GET | `/api/workflows/catalog` | Catalog |
| DELETE | `/api/workflows/{wid}` | Delete Workflow |
| GET | `/api/workflows/{wid}` | Get Workflow |
| PATCH | `/api/workflows/{wid}` | Update Workflow |
| POST | `/api/workflows/{wid}/run-now` | Run Now |
| POST | `/api/workflows/{wid}/test` | Dry run: evaluate the conditions against a real candidate without executing any action. |

### Delegation

| Method | Path | Summary |
|---|---|---|
| GET | `/api/posts` | List Posts |
| PATCH | `/api/posts/{pid}` | Update Post |
| GET | `/api/tickets` | List Tickets |
| POST | `/api/tickets` | Create |
| PATCH | `/api/tickets/{tid}` | Update |

### Analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/analytics/data-quality/history` | Dq History |
| GET | `/api/analytics/impact` | Impact |
| GET | `/api/analytics/overview` | Overview |

### Compliance

| Method | Path | Summary |
|---|---|---|
| GET | `/api/compliance/audit` | Audit Log |
| GET | `/api/compliance/consent` | Consent Log |
| GET | `/api/compliance/flags` | Flags |
| POST | `/api/compliance/flags/{fid}` | Review Flag |
| GET | `/api/compliance/habits` | Habits |
| POST | `/api/compliance/habits/{hid}` | Review Habit |
| GET | `/api/compliance/retention` | Retention Queue |
| POST | `/api/compliance/retention/{cid}/extend` | Extend |
| POST | `/api/compliance/retention/{cid}/purge` | Anonymise personal data and delete stored documents. Aggregate metrics are preserved. |

### Settings

| Method | Path | Summary |
|---|---|---|
| GET | `/api/digest/logs` | Digest Logs |
| GET | `/api/digest/preview` | Preview |
| POST | `/api/digest/send-now` | Send Now |
| GET | `/api/emails` | Emails |
| GET | `/api/integrations` | Integrations |
| GET | `/api/jobs` | Jobs |
| POST | `/api/jobs/run-due` | Run Jobs |
| GET | `/api/settings` | Get All |
| PUT | `/api/settings/{key}` | Put |
| GET | `/api/templates` | Templates |
| PUT | `/api/templates/{key}` | Update Template |

### Public

| Method | Path | Summary |
|---|---|---|
| GET | `/api/public/consent/{token}` | Consent Get |
| POST | `/api/public/consent/{token}` | Consent Post |
| GET | `/api/public/digest-action/{token}` | Digest Action |
| GET | `/api/public/portal/{token}` | Portal |
| POST | `/api/public/portal/{token}/items/{item_id}` | Upload |
| GET | `/api/public/unsubscribe/{token}` | Unsubscribe |
| GET | `/api/t/c/{email_id}` | Track Click |
| GET | `/api/t/o/{email_id}.gif` | Track Open |

### Webhooks

| Method | Path | Summary |
|---|---|---|
| POST | `/api/webhooks/application` | Application |
| POST | `/api/webhooks/inbound-email` | Normalised inbound mail. Adapters for Gmail push (Pub/Sub) or Microsoft Graph change |
| POST | `/api/webhooks/post-engagement` | Post Engagement |
| POST | `/api/webhooks/requirement` | Requirement |

### Other

| Method | Path | Summary |
|---|---|---|
| GET | `/api/health` | Health |

## Key payloads

**Log a call** `POST /api/candidates/{id}/calls`
```json
{"outcome": "interested", "notes": "Open to hybrid in Dallas", "fields": {"availability": "2 weeks", "preferred_type": "W-2"}, "follow_up_days": 2}
```
Outcomes: connected, interested, call_back, not_interested, no_answer, voicemail, wrong_number. Emits `call.logged`.

**Manual stage move** `POST /api/candidates/{id}/stage`
```json
{"to": "hold", "reason": "Travelling for a month"}
```

**Comfort check** `POST /api/candidates/{id}/comfort-check`
```json
{"answers": [{"answer": "yes"}, {"answer": "yes"}, {"answer": "yes"}, {"answer": "yes"}, {"answer": "no", "note": "Wants to think it over"}]}
```

**Inbound application webhook** `POST /api/webhooks/application`
```json
{"resume_text": "...", "email": "a@b.com", "requirement_id": 3, "source": "Indeed"}
```

**Inbound email webhook** `POST /api/webhooks/inbound-email` — replies from candidates are matched by sender and classified; mail to `requirements@…` is parsed into a new requirement.
```json
{"from_email": "cand@example.com", "to_email": "priya@cognitech.example", "subject": "Re: role", "body": "Yes, interested!"}
```

**Create workflow** `POST /api/workflows`
```json
{"name": "Notify lead on high-priority reqs", "trigger_event": "requirement.created", "conditions": [{"field": "requirement.priority", "op": "eq", "value": "High"}], "actions": [{"type": "notify", "params": {"to": "role", "role": "ta_lead", "title": "New high-priority requirement"}}]}
```
