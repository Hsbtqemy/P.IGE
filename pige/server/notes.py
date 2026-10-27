"""Notes taken for something of the agenda: a long text (« Écrire ») linked to a planned
entry of the journal or to a calendar event.

A text about a planned entry points to it (``about_entry_id``). For a calendar event, the
event's own note is the text when it had none, else the text points to that short note.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pige.model import ModelStore
from pige.model.store import CalendarEvent, Entry, NotFoundError

_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]


def long_day(day: date) -> str:
    """« mardi 27 octobre »."""
    return f"{_DAYS[day.weekday()]} {'1er' if day.day == 1 else day.day} {_MONTHS[day.month - 1]}"


def clock(hhmm: str) -> str:
    """« 09:30 » -> « 9h30 », « 14:00 » -> « 14h »."""
    h, m = hhmm.split(":")[:2]
    return f"{int(h)}h{m if m != '00' else ''}"


def template(title: str, day: date, start: str | None, end: str | None, location: str | None,
             people: list[str]) -> str:
    """The head of the notes: what, when, where, with whom; the rest is the user's."""
    when = long_day(day) + (f", {clock(start)}{f'–{clock(end)}' if end else ''}" if start else "")
    lines = [f"# {title}", "", f"**Date :** {when}"]
    if location:
        lines.append(f"**Lieu :** {location}")
    lines.append(f"**Présent·es :** {', '.join(people[:30])}".rstrip())
    return "\n".join(lines) + "\n\n"


def _local(stamp: str, tz: ZoneInfo) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).astimezone(tz)


def event_times(event: CalendarEvent, tz: ZoneInfo) -> tuple[date, str | None, str | None]:
    if event.all_day:
        return date.fromisoformat(event.start_at), None, None
    begin, end = _local(event.start_at, tz), _local(event.end_at, tz)
    return begin.date(), begin.strftime("%H:%M"), end.strftime("%H:%M") if end.date() == begin.date() else None


def attendee_names(event: CalendarEvent) -> list[str]:
    return [a.get("name") or a.get("email") or "" for a in event.attendees if a.get("name") or a.get("email")]


def notes_of_event(store: ModelStore, event: CalendarEvent) -> Entry | None:
    """The long text of notes for a calendar event, if one was written."""
    if event.entry_id is None:
        return None
    try:
        own = store.get_entry(event.entry_id)
    except NotFoundError:
        return None
    if own.source == "writing":
        return own
    return store.notes_for([own.id]).get(own.id)


def about_view(store: ModelStore, entry: Entry, tz: ZoneInfo) -> dict[str, Any] | None:
    """What these notes are about, to show it with them (heading of the editor, journal)."""
    target = None
    if entry.about_entry_id:
        try:
            target = store.get_entry(entry.about_entry_id)
        except NotFoundError:
            target = None
    event = store.event_of_entry(target.id if target else entry.id)
    if event is not None:
        day, start, end = event_times(event, tz)
        return {"kind": "event", "event_id": event.id, "entry_id": target.id if target else None,
                "title": event.title, "day": day.isoformat(), "start_time": start, "end_time": end,
                "location": event.location, "people": attendee_names(event)}
    if target is not None:
        return {"kind": "entry", "event_id": None, "entry_id": target.id, "title": target.title or target.body[:120],
                "day": target.entry_date, "start_time": target.start_time, "end_time": target.end_time,
                "location": None, "people": []}
    return None


def notes_ref(entry: Entry | None) -> dict[str, str] | None:
    return {"id": entry.id, "title": entry.title} if entry else None
