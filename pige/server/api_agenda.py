"""/api/v2/calendars and /api/v2/agenda: followed calendars, their events, notes and time taken from them.

Adding, changing or removing a calendar (its address and password) needs the web app
signed in with a session; reading the agenda and taking notes also work with a token.
"""

from __future__ import annotations

import urllib.parse
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from pige.model import ModelStore
from pige.model.store import Calendar, CalendarEvent, NotFoundError
from pige.server import notes as notes_
from pige.server.agenda import Agenda, CalendarError, Source, Vault, normalize_url, shown_host

HEX = r"^[0-9a-f]{32}$"
COLOR = r"^#[0-9a-fA-F]{6}$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarIn(_In):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2000)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    color: str = Field(default="#3b5168", pattern=COLOR)
    project_id: str | None = Field(default=None, pattern=HEX)


class CalendarPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=COLOR)
    active: bool | None = None
    project_id: str | None = Field(default=None, pattern=HEX)  # null: no default project
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    username: str | None = Field(default=None, max_length=200)  # "": no credentials
    password: str | None = Field(default=None, max_length=500)


class TargetIn(_In):
    project_id: str | None = Field(default=None, pattern=HEX)
    space_id: str | None = Field(default=None, pattern=HEX)
    task_id: str | None = Field(default=None, pattern=HEX)


class PlaceIn(_In):
    project_id: str | None = Field(default=None, pattern=HEX)
    space_id: str | None = Field(default=None, pattern=HEX)
    series: bool = False  # every occurrence of the recurring event, those to come included


def calendar_view(c: Calendar) -> dict[str, Any]:
    """A calendar as the browser sees it: never the address path nor the password."""
    return {
        "id": c.id, "name": c.name, "color": c.color, "host": c.source_host, "has_password": c.has_password,
        "project_id": c.project_id, "active": c.active, "last_sync": c.last_sync, "last_error": c.last_error,
        "failures": c.failures,
    }


def build_agenda_router(
    store: ModelStore,
    agenda: Agenda,
    vault: Vault,
    default_timezone: str,
    require_auth: Callable[..., str],
    require_session: Callable[..., str],
) -> APIRouter:
    router = APIRouter(prefix="/api/v2")

    def zone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown time zone {name!r}") from exc

    def safe_sync(calendar_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, **agenda.sync(calendar_id)}
        except CalendarError as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------ calendars

    @router.get("/calendars")
    def calendars(_auth: str = Depends(require_auth)) -> list[dict[str, Any]]:
        return [calendar_view(c) for c in store.list_calendars()]

    @router.post("/calendars", status_code=status.HTTP_201_CREATED)
    def add_calendar(body: CalendarIn, _sid: str = Depends(require_session)) -> dict[str, Any]:
        try:
            url = normalize_url(body.url)
        except CalendarError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        username = (body.username or "").strip() or None
        password = body.password or None
        source = Source(url, username, password if username else None)
        calendar = store.create_calendar(
            body.name, source_enc=vault.seal(source), source_host=shown_host(url),
            has_password=bool(username and password), color=body.color, project_id=body.project_id,
        )
        result = safe_sync(calendar.id)
        return {"calendar": calendar_view(store.get_calendar(calendar.id)), "sync": result}

    @router.patch("/calendars/{calendar_id}")
    def change_calendar(calendar_id: str, body: CalendarPatch, _sid: str = Depends(require_session)) -> dict[str, Any]:
        current = store.get_calendar(calendar_id)
        fields: dict[str, Any] = {}
        sent = body.model_fields_set
        if body.name is not None:
            fields["name"] = body.name
        if body.color is not None:
            fields["color"] = body.color
        if body.active is not None:
            fields["active"] = body.active
        if "project_id" in sent:
            fields["project_id"] = body.project_id
        if sent & {"url", "username", "password"}:
            try:
                source = vault.open(current.source_enc)
            except CalendarError:
                if body.url is None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Saisis de nouveau l'adresse du calendrier.")
                source = Source(body.url)
            url = source.url
            if body.url is not None:
                try:
                    url = normalize_url(body.url)
                except CalendarError as exc:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            username = source.username
            password = source.password
            moved = urllib.parse.urlsplit(url).hostname != urllib.parse.urlsplit(source.url).hostname
            if moved and not sent & {"username", "password"}:
                username = password = None  # never send the old credentials to another server
            if "username" in sent:
                username = (body.username or "").strip() or None
                if username is None:
                    password = None
            if "password" in sent and body.password:
                password = body.password
            new = Source(url, username, password if username else None)
            fields.update(
                source_enc=vault.seal(new), source_host=shown_host(url), has_password=bool(new.username and new.password)
            )
        calendar = store.update_calendar(calendar_id, **fields)
        result = safe_sync(calendar_id) if "source_enc" in fields or body.active else None
        return {"calendar": calendar_view(store.get_calendar(calendar.id)), "sync": result}

    @router.delete("/calendars/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_calendar(calendar_id: str, _sid: str = Depends(require_session)) -> Response:
        store.delete_calendar(calendar_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/calendars/{calendar_id}/sync")
    def sync_calendar(calendar_id: str, _sid: str = Depends(require_session)) -> dict[str, Any]:
        store.get_calendar(calendar_id)
        result = safe_sync(calendar_id)
        if not result["ok"]:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, result["error"])
        return result

    # ------------------------------------------------------------ agenda

    def local_bounds(first: date, days: int, tz: ZoneInfo) -> tuple[str, str]:
        start = datetime.combine(first, time.min, tz).astimezone(timezone.utc)
        end = datetime.combine(first + timedelta(days=days), time.min, tz).astimezone(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        return start.strftime(fmt), end.strftime(fmt)

    class Context:
        """What the views of several events share (read once per request)."""

        def __init__(self) -> None:
            self.calendars = {c.id: c for c in store.list_calendars()}
            self.series = store.series_places()
            self.recurring = store.recurring_uids()

    def planned(e: CalendarEvent, ctx: Context) -> tuple[dict[str, str | None], str] | None:
        """Where the meeting was filed before any note: the occurrence itself, else its series."""
        if e.project_id or e.space_id:
            return {"project_id": e.project_id, "space_id": e.space_id}, "event"
        key = store.series_key(e, ctx.recurring)
        rule = ctx.series.get((e.calendar_id, key)) if key else None
        if rule is not None:
            return {"project_id": rule[0], "space_id": rule[1]}, "series"
        return None

    def event_view(e: CalendarEvent, ctx: Context) -> dict[str, Any]:
        c = ctx.calendars.get(e.calendar_id)
        key = store.series_key(e, ctx.recurring)
        filed = placed(e)
        plan = None if filed else planned(e, ctx)
        place: dict[str, str | None] | None = filed or (plan[0] if plan else None)
        if place is not None and place["project_id"] and not place["space_id"]:
            try:
                place = {"project_id": place["project_id"], "space_id": store.get_project(place["project_id"]).space_id}
            except NotFoundError:
                place = None
        return {
            "id": e.id, "calendar_id": e.calendar_id, "calendar": c.name if c else "", "color": c.color if c else "",
            "start": e.start_at, "end": e.end_at, "all_day": e.all_day, "title": e.title, "location": e.location,
            "description": e.description, "organizer": e.organizer, "attendees": e.attendees, "status": e.status,
            "entry_id": e.entry_id, "block_id": e.block_id, "project_id": c.project_id if c else None,
            "place": place,
            "place_source": "filed" if filed else (plan[1] if plan else None),
            "recurring": key is not None,
            "series_filed": key is not None and (e.calendar_id, key) in ctx.series,
            "notes": notes_.notes_ref(notes_.notes_of_event(store, e)),
        }

    def placed(e: CalendarEvent) -> dict[str, str | None] | None:
        """Where the meeting's note (else its time) is filed, once noted or counted."""
        for get, item_id in ((store.get_entry, e.entry_id), (store.get_block, e.block_id)):
            if item_id is None:
                continue
            try:
                item = get(item_id)
            except NotFoundError:
                continue
            return {"project_id": item.project_id, "space_id": item.space_id}
        return None

    @router.get("/agenda")
    def agenda_days(
        start: date,
        days: int = Query(default=7, ge=1, le=62),
        tz: str = Query(default=default_timezone, max_length=64),
        _auth: str = Depends(require_auth),
    ) -> list[dict[str, Any]]:
        start_utc, end_utc = local_bounds(start, days, zone(tz))
        events = store.events_between(start_utc, end_utc, start.isoformat(), (start + timedelta(days=days)).isoformat())
        ctx = Context()
        return [event_view(e, ctx) for e in events]

    def where(event: CalendarEvent, body: TargetIn) -> dict[str, str | None]:
        if body.project_id or body.space_id or body.task_id:
            return {"project_id": body.project_id, "space_id": body.space_id, "task_id": body.task_id}
        plan = planned(event, Context())
        if plan is not None:
            return {**plan[0], "task_id": None}
        calendar = store.get_calendar(event.calendar_id)
        if calendar.project_id:
            return {"project_id": calendar.project_id, "space_id": None, "task_id": None}
        spaces = store.list_spaces()
        if not spaces:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Crée d'abord un espace")
        inbox = next((s for s in spaces if s.name.strip().lower() == "à trier"), spaces[0])
        return {"project_id": None, "space_id": inbox.id, "task_id": None}

    def local_times(event: CalendarEvent, tz: ZoneInfo) -> tuple[str, str | None, str | None]:
        if event.all_day:
            return event.start_at, None, None
        begin = datetime.strptime(event.start_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).astimezone(tz)
        end = datetime.strptime(event.end_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).astimezone(tz)
        same_day = end.date() == begin.date()
        return begin.date().isoformat(), begin.strftime("%H:%M"), end.strftime("%H:%M") if same_day else None

    @router.post("/agenda/{event_id}/note")
    def note_event(
        event_id: str, body: TargetIn, tz: str = Query(default=default_timezone, max_length=64),
        _auth: str = Depends(require_auth),
    ) -> dict[str, Any]:
        """A journal entry for the meeting (once: the same event gives the same entry)."""
        with store.transaction():
            event = store.get_event(event_id)
            if event.entry_id is not None:
                return {"entry_id": event.entry_id, "created": False, "event": current(event_id)}
            day, start_time, end_time = local_times(event, zone(tz))
            emails = {a["email"] for a in event.attendees if a.get("email")} | ({event.organizer} if event.organizer else set())
            known = [p for p in store.list_people() if p.email and p.email.lower() in emails]
            lines = [f"Réunion : {event.title}"]
            if event.location:
                lines.append(f"Lieu : {event.location}")
            names = [a["name"] or a["email"] for a in event.attendees if a.get("name") or a.get("email")]
            if names:
                lines.append("Avec : " + ", ".join(names[:30]))
            target = where(event, body)
            entry = store.create_entry(
                entry_date=day, project_id=target["project_id"], space_id=target["space_id"], task_id=target["task_id"],
                kind="meeting", title=event.title[:500], body="\n".join(lines) + "\n\n", start_time=start_time,
                end_time=end_time, source="journal", person_ids=[p.id for p in known],
            )
            store.link_event(event_id, entry_id=entry.id)
            return {"entry_id": entry.id, "created": True, "event": current(event_id)}

    @router.post("/agenda/{event_id}/notes")
    def event_notes(
        event_id: str, body: TargetIn, tz: str = Query(default=default_timezone, max_length=64),
        _auth: str = Depends(require_auth),
    ) -> dict[str, Any]:
        """Notes for the meeting, in a long text: the one already written, else a new one."""
        with store.transaction():
            event = store.get_event(event_id)
            existing = notes_.notes_of_event(store, event)
            if existing is not None:
                return {"entry_id": existing.id, "created": False, "event": current(event_id)}
            day, start, end = notes_.event_times(event, zone(tz))
            target = where(event, body)
            text = store.create_entry(
                entry_date=day.isoformat(), project_id=target["project_id"],
                space_id=None if target["project_id"] else target["space_id"], title=(event.title or "Notes")[:500],
                body=notes_.template(event.title or "Notes", day, start, end, event.location,
                                     notes_.attendee_names(event)),
                source="writing",
            )
            if event.entry_id is None:
                store.link_event(event_id, entry_id=text.id)
            else:
                store.set_about(text.id, event.entry_id)
            return {"entry_id": text.id, "created": True, "event": current(event_id)}

    @router.post("/agenda/{event_id}/place")
    def place_event(event_id: str, body: PlaceIn, _auth: str = Depends(require_auth)) -> dict[str, Any]:
        """File the meeting: this occurrence, or the whole series (``series``). Its note and its
        counted time, if already taken, move along. No place: back to the default."""
        target = {"project_id": body.project_id, "space_id": None if body.project_id else body.space_id}
        with store.transaction():
            event = store.get_event(event_id)
            key = store.series_key(event, store.recurring_uids()) if body.series else None
            if body.series and key is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cet événement ne fait pas partie d'une série")
            events = store.series_events(event.calendar_id, key) if key else [event]
            if key:
                store.plan_series(event.calendar_id, key, **target)
            else:
                store.plan_event(event_id, **target)
            if target["project_id"] or target["space_id"]:
                for e in events:
                    if e.entry_id is not None:
                        store.move_entry(e.entry_id, **target)
                    if e.block_id is not None:
                        store.reassign_block(e.block_id, **target)
            return current(event_id)

    def current(event_id: str) -> dict[str, Any]:
        """The event as the agenda shows it (after a note, a count or a move)."""
        return event_view(store.get_event(event_id), Context())

    @router.post("/agenda/{event_id}/count")
    def count_event(event_id: str, body: TargetIn, _auth: str = Depends(require_auth)) -> dict[str, Any]:
        """Time block for the meeting, counted alone (« ne compter qu'ici »), once per event."""
        with store.transaction():
            event = store.get_event(event_id)
            if event.all_day:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Un événement sur la journée entière ne se compte pas")
            if event.block_id is not None:
                return {"block_id": event.block_id, "created": False, "event": current(event_id)}
            own = store.entry_block(event.entry_id) if event.entry_id else None
            if own is not None:
                # The note's time range already counts it: that block becomes the meeting's.
                store.link_event(event_id, block_id=own.id)
                return {"block_id": own.id, "created": False, "event": current(event_id)}
            target = where(event, body)
            begin = datetime.strptime(event.start_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            end = datetime.strptime(event.end_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            block = store.add_block(
                begin, end, project_id=target["project_id"], space_id=target["space_id"], task_id=target["task_id"],
                entry_id=event.entry_id, source="agenda", overlap_mode="exclusive", note=event.title[:200],
            )
            store.link_event(event_id, block_id=block.id)
            return {"block_id": block.id, "created": True, "event": current(event_id)}

    return router

