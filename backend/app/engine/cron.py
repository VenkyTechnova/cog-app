"""Minimal 5-field cron matcher (minute hour day-of-month month day-of-week), evaluated in local time."""
from __future__ import annotations

from datetime import datetime

DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _field(spec: str, value: int, lo: int, hi: int, names: dict | None = None) -> bool:
    for part in spec.lower().split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-")
            start, end = _num(a, names), _num(b, names)
        else:
            start = end = _num(part, names)
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def _num(s: str, names: dict | None) -> int:
    if names and s in names:
        return names[s]
    return int(s)


def matches(expr: str, dt: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr!r}")
    minute, hour, dom, month, dow = parts
    cron_dow = (dt.weekday() + 1) % 7  # python Mon=0 → cron Mon=1, Sun=0
    return (
        _field(minute, dt.minute, 0, 59)
        and _field(hour, dt.hour, 0, 23)
        and _field(dom, dt.day, 1, 31)
        and _field(month, dt.month, 1, 12)
        and (_field(dow, cron_dow, 0, 6, DOW) or (cron_dow == 0 and _field(dow, 7, 0, 7, DOW)))
    )


_RANGES = [(0, 59, None), (0, 23, None), (1, 31, None), (1, 12, None), (0, 7, DOW)]


def _check_field(spec: str, lo: int, hi: int, names: dict | None) -> None:
    for part in spec.lower().split(","):
        if not part:
            raise ValueError("empty field")
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) < 1:
                raise ValueError("bad step")
        if part == "*":
            continue
        bounds = part.split("-") if "-" in part else [part]
        if len(bounds) > 2:
            raise ValueError("bad range")
        vals = [_num(b, names) for b in bounds]  # raises ValueError on junk
        if any(v < lo or v > hi for v in vals) or (len(vals) == 2 and vals[0] > vals[1]):
            raise ValueError("out of range")


def validate(expr: str) -> bool:
    """Full syntax + range check of every field (not just the ones a sample time touches)."""
    parts = (expr or "").split()
    if len(parts) != 5:
        return False
    try:
        for spec, (lo, hi, names) in zip(parts, _RANGES):
            _check_field(spec, lo, hi, names)
        return True
    except (ValueError, KeyError):
        return False


def time_to_cron(hhmm: str, business_days_only: bool = True) -> str:
    h, m = hhmm.split(":")
    return f"{int(m)} {int(h)} * * {'mon-fri' if business_days_only else '*'}"
