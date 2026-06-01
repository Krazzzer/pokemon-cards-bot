import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_DATE_PATTERNS = [
    re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:\s+(\d{1,2}):(\d{2}))?$"),
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$"),
]

_TZ_OFFSETS: dict[str, timezone] = {
    "europe/chisinau": timezone(timedelta(hours=2)),
    "chisinau": timezone(timedelta(hours=2)),
    "utc": timezone.utc,
    "gmt": timezone.utc,
}


def _normalize_input(text: str) -> str:
    text = text.strip().replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _resolve_timezone(timezone_name: str) -> timezone | ZoneInfo:
    name = (timezone_name or "Europe/Chisinau").strip().strip('"').strip("'")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError):
        fallback = _TZ_OFFSETS.get(name.lower())
        if fallback is not None:
            return fallback
        if "chisinau" in name.lower():
            return _TZ_OFFSETS["europe/chisinau"]
        raise


def _parse_parts(text: str) -> tuple[int, int, int, int, int] | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        g = match.groups()
        if len(g[0]) == 4:
            year, month, day = int(g[0]), int(g[1]), int(g[2])
        else:
            day, month, year = int(g[0]), int(g[1]), int(g[2])
        hour = int(g[3]) if g[3] is not None else 23
        minute = int(g[4]) if g[4] is not None else 59
        return day, month, year, hour, minute
    return None


def parse_auction_end(text: str, timezone_name: str) -> datetime | None:
    """Parse DD.MM.YYYY or DD.MM.YYYY HH:MM in local TZ; return UTC naive datetime."""
    normalized = _normalize_input(text)
    parts = _parse_parts(normalized)
    if parts is None:
        return None

    day, month, year, hour, minute = parts
    try:
        tz = _resolve_timezone(timezone_name)
        local_dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    except (ValueError, KeyError, ZoneInfoNotFoundError):
        return None

    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def format_ends_at_local(ends_at: datetime, timezone_name: str) -> str:
    try:
        tz = _resolve_timezone(timezone_name)
        local = ends_at.replace(tzinfo=timezone.utc).astimezone(tz)
        return local.strftime("%d.%m.%Y %H:%M")
    except (ValueError, KeyError, ZoneInfoNotFoundError):
        return ends_at.strftime("%d.%m.%Y %H:%M")
