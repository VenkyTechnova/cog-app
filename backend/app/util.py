"""Small shared helpers: time zones, signed tokens, text utilities."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import get_settings

UTC = timezone.utc


def now() -> datetime:
    """Current UTC time. Tests monkeypatch `app.util._clock` to freeze time."""
    return _clock()


def _real_clock() -> datetime:
    return datetime.now(UTC)


_clock = _real_clock


def set_clock(fn):
    global _clock
    _clock = fn or _real_clock


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def to_local(dt: datetime) -> datetime:
    return aware(dt).astimezone(local_tz())


def local_today() -> date:
    return to_local(now()).date()


def aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive datetimes as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5


def add_business_days(dt: datetime, days: int) -> datetime:
    cur = dt
    added = 0
    while added < days:
        cur += timedelta(days=1)
        if is_business_day(cur.date()):
            added += 1
    return cur


def start_of_local_day(d: date | None = None) -> datetime:
    d = d or local_today()
    return datetime(d.year, d.month, d.day, tzinfo=local_tz()).astimezone(UTC)


# ---------------------------------------------------------------------------
# Signed tokens (digest action links, unsubscribe, auth)
# ---------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict, ttl_seconds: int | None = None) -> str:
    body = dict(payload)
    if ttl_seconds:
        body["exp"] = int(time.time()) + ttl_seconds
    raw = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(get_settings().secret_key.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def unsign(token: str) -> dict | None:
    try:
        raw, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64(hmac.new(get_settings().secret_key.encode(), raw.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        body = json.loads(_unb64(raw))
    except Exception:
        return None
    if "exp" in body and body["exp"] < time.time():
        return None
    return body


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def normalize_email(e: str | None) -> str | None:
    return e.strip().lower() if e else None


def normalize_phone(p: str | None) -> str | None:
    if not p:
        return None
    digits = re.sub(r"\D", "", p)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits or None


def normalize_linkedin(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u).rstrip("/")
    return u


def body_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode()).hexdigest()


def first_name(full_name: str) -> str:
    return (full_name or "").split(" ")[0] or "there"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]
