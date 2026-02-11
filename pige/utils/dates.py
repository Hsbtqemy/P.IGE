from __future__ import annotations

from datetime import date, datetime, time, timezone


UTC_Z_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT = "%Y-%m-%d"


def utc_now_iso() -> str:
    dt = datetime.now(timezone.utc).replace(microsecond=0)
    return dt.strftime(UTC_Z_FORMAT)


def parse_utc_z(value: str) -> datetime:
    dt = datetime.strptime(value, UTC_Z_FORMAT)
    return dt.replace(tzinfo=timezone.utc)


def local_now_iso() -> str:
    dt = datetime.now().astimezone().replace(microsecond=0)
    return dt.isoformat()


def parse_date(value: str) -> date:
    return datetime.strptime(value, DATE_FORMAT).date()


def local_day_range_utc(day: date | None = None) -> tuple[datetime, datetime]:
    local_tz = datetime.now().astimezone().tzinfo
    if day is None:
        day = datetime.now().astimezone().date()
    start_local = datetime.combine(day, time.min, tzinfo=local_tz)
    end_local = datetime.combine(day, time.max, tzinfo=local_tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_date_range_to_utc(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    local_tz = datetime.now().astimezone().tzinfo
    start_local = datetime.combine(from_date, time.min, tzinfo=local_tz)
    end_local = datetime.combine(to_date, time.max, tzinfo=local_tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_date_midday_to_utc_z(day: date) -> str:
    local_tz = datetime.now().astimezone().tzinfo
    local_dt = datetime.combine(day, time(12, 0), tzinfo=local_tz)
    utc_dt = local_dt.astimezone(timezone.utc).replace(microsecond=0)
    return utc_dt.strftime(UTC_Z_FORMAT)
