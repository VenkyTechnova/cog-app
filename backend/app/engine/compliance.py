"""Compliance guardrails.

* Scans candidate-facing text for immigration/legal advice, pay promises and tax statements.
  - Outbound messages containing a blocking pattern cannot be approved or sent.
  - Notes are never blocked (recruiters must be able to record what a candidate asked),
    but they are flagged for review.
* Enforces outreach caps and blocks repeated identical messages.
* Appends the "not a final employment commitment" disclaimer to opportunity messages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from ..constants import OFFER_DISCLAIMER
from ..models import Candidate, ComplianceFlag, OutboundEmail
from ..settings_store import get_setting
from ..util import aware, body_hash, now

# (category, severity, regex). Severity "block" = cannot be sent to a candidate.
PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # Immigration / legal — always routed to the Immigration team.
    ("immigration", "block", re.compile(r"\bi-?983\b", re.I)),
    ("immigration", "block", re.compile(r"\bh-?1b\b", re.I)),
    ("immigration", "block", re.compile(r"\bstem[\s-]*opt\b", re.I)),
    ("immigration", "block", re.compile(r"\bopt\b(?!\s*(?:out|-out|in))", re.I)),
    ("immigration", "block", re.compile(r"\bcpt\b", re.I)),
    ("immigration", "block", re.compile(r"\bgreen\s*card\b", re.I)),
    ("immigration", "block", re.compile(r"\b(uscis|sevis|i-?797|i-?94|i-?20)\b", re.I)),
    ("immigration", "block", re.compile(r"\bvisa\s+(transfer|sponsor\w*|status|approval|stamp\w*|extension)\b", re.I)),
    ("immigration", "block", re.compile(r"\bimmigration\b", re.I)),
    ("immigration", "block", re.compile(r"\bead\s+(extension|renewal)\b", re.I)),
    ("legal", "block", re.compile(r"\b(legal advice|you are eligible|you will be eligible|you('| wi)ll be approved)\b", re.I)),
    ("legal", "block", re.compile(r"\bguarantee[sd]?\s+(your\s+)?(approval|status|extension|eligibility)\b", re.I)),
    # Pay promises — dates, amounts, guarantees.
    ("pay_promise", "block", re.compile(r"\bpay\s*-?\s*(date|day|schedule)\b", re.I)),
    ("pay_promise", "block", re.compile(r"\b(be|get|getting)\s+paid\s+(on|by|every|within|before)\b", re.I)),
    ("pay_promise", "block", re.compile(r"\b(guarantee[sd]?|promise[sd]?|will)\b[^.\n]{0,30}\b(pay|paid|salary|payment|rate)\b", re.I)),
    ("pay_promise", "block", re.compile(r"\$\s?\d[\d,]*(\.\d+)?\s*(k\b|/\s*(hr|hour|h|yr|year|month)|per\s+(hour|year|annum|month)|an?\s+hour)", re.I)),
    # Tax statements.
    ("tax", "block", re.compile(r"\btax(es|ation)?\b[^.\n]{0,40}\b(save|saving|savings|benefit|lower|less|free|advantage|deduct\w*)\b", re.I)),
    ("tax", "block", re.compile(r"\b(save|saving|savings|lower|less)\b[^.\n]{0,30}\btax(es)?\b", re.I)),
    # Pressure (habit worth breaking) — reviewed, not blocked.
    ("pressure", "review", re.compile(r"\b(act now|last chance|only today|immediately or|decide (today|now)|don'?t miss out|limited time)\b", re.I)),
]

# Words that make a note or a draft "sensitive" enough to suggest routing to a team.
ROUTE_HINTS = {
    "immigration": ("immigration", "Route to the Immigration / authorized team"),
    "legal": ("immigration", "Route to the Immigration / authorized team"),
    "pay_promise": ("payroll", "Route payroll questions to the Payroll team"),
    "tax": ("payroll", "Cognitech does not give tax advice — route to Payroll / suggest a tax professional"),
}


@dataclass
class ScanResult:
    hits: list[dict] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(h["severity"] == "block" for h in self.hits)

    @property
    def categories(self) -> list[str]:
        return sorted({h["category"] for h in self.hits})

    def as_dict(self) -> dict:
        routes = {}
        for c in self.categories:
            if c in ROUTE_HINTS:
                team, msg = ROUTE_HINTS[c]
                routes[team] = msg
        return {"blocked": self.blocked, "hits": self.hits, "categories": self.categories, "route_to": routes}


def scan(text: str, ignore: str | None = None) -> ScanResult:
    """Scan text. `ignore` removes a known-safe fragment (e.g. the offer disclaimer)."""
    body = text or ""
    if ignore:
        body = body.replace(ignore, "")
    res = ScanResult()
    seen = set()
    for category, severity, pat in PATTERNS:
        for m in pat.finditer(body):
            key = (category, m.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            res.hits.append({"category": category, "severity": severity, "match": m.group(0)})
    return res


def record_flags(
    db: Session,
    result: ScanResult,
    source_type: str,
    source_id,
    candidate_id: int | None,
    user_id: int | None,
    severity_override: str | None = None,
) -> list[ComplianceFlag]:
    flags = []
    for h in result.hits:
        f = ComplianceFlag(
            candidate_id=candidate_id,
            user_id=user_id,
            source_type=source_type,
            source_id=str(source_id) if source_id is not None else None,
            category=h["category"],
            matched_text=h["match"],
            severity=severity_override or h["severity"],
        )
        db.add(f)
        flags.append(f)
    db.flush()
    # Feed the "habits worth breaking" monitor for outbound content.
    if source_type in ("draft", "email") and user_id:
        from .habits import raise_habit

        for c in result.categories:
            habit = {"immigration": "immigration_advice", "legal": "immigration_advice", "pay_promise": "pay_promise", "tax": "pay_promise", "pressure": "pressuring_language"}.get(c)
            if habit:
                raise_habit(db, habit, user_id=user_id, candidate_id=candidate_id, detail=f"{c} language in {source_type} #{source_id}", key=f"{habit}:{source_type}:{source_id}")
    return flags


# ---------------------------------------------------------------------------
# Outreach caps
# ---------------------------------------------------------------------------
@dataclass
class OutreachCheck:
    allowed: bool
    reason: str = ""


def check_outreach(db: Session, candidate: Candidate, body: str) -> OutreachCheck:
    if candidate.email_opt_out:
        return OutreachCheck(False, "Candidate has unsubscribed from emails")
    if candidate.purged:
        return OutreachCheck(False, "Candidate record has been purged")
    t = now()
    cap = int(get_setting(db, "outreach.max_per_candidate_7d"))
    min_gap = int(get_setting(db, "outreach.min_hours_between"))
    recent = (
        db.query(OutboundEmail)
        .filter(
            OutboundEmail.candidate_id == candidate.id,
            OutboundEmail.kind == "candidate",
            OutboundEmail.status == "sent",
            OutboundEmail.sent_at >= t - timedelta(days=7),
        )
        .order_by(OutboundEmail.sent_at.desc())
        .all()
    )
    if len(recent) >= cap:
        return OutreachCheck(False, f"Outreach cap reached ({cap} emails in 7 days)")
    if recent and aware(recent[0].sent_at) > t - timedelta(hours=min_gap):
        return OutreachCheck(False, f"Last email was sent less than {min_gap}h ago")
    h = body_hash(body)
    dup = (
        db.query(OutboundEmail)
        .filter(OutboundEmail.candidate_id == candidate.id, OutboundEmail.body_hash == h, OutboundEmail.status == "sent")
        .first()
    )
    if dup:
        return OutreachCheck(False, "An identical message was already sent to this candidate")
    return OutreachCheck(True)


GENERIC_MARKERS = [r"\{\{", r"\[(first name|name|company|skill|detail)\]", r"dear candidate", r"to whom it may concern"]


def is_generic(body: str, candidate: Candidate | None) -> bool:
    """A message is generic if it has unfilled placeholders or mentions nothing specific to the candidate."""
    b = (body or "").lower()
    if any(re.search(p, b) for p in GENERIC_MARKERS):
        return True
    if candidate is None:
        return False
    specifics = [s.lower() for s in (candidate.skills or [])[:6]]
    specifics += [candidate.full_name.split(" ")[0].lower()] if candidate.full_name else []
    if candidate.university:
        specifics.append(candidate.university.lower())
    return not any(s and s in b for s in specifics)


def with_disclaimer(body: str, candidate: Candidate | None) -> str:
    if candidate is not None and candidate.stage == "placed":
        return body
    if OFFER_DISCLAIMER in body:
        return body
    return f"{body.rstrip()}\n\n—\n{OFFER_DISCLAIMER}"
