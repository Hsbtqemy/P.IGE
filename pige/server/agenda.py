"""Calendars followed by the server: ICS feeds and CalDAV collections (Zimbra, Google…).

* The feed address often embeds a private token, and some feeds need a user name and
  password: all three are stored **encrypted** (Fernet, key derived from the session
  secret) and never sent back to the browser, never logged (only ``https://host/…``).
* Credentials only ever travel over HTTPS; a redirect may not downgrade to HTTP and
  credentials are dropped if it leaves the host. Responses are capped in size.
* Events are expanded (recurrences) over a sliding window and stored in the model, so
  the journal and « Ma journée » can show them and take notes or time from them.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import threading
import time as clock
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from pige.model import ModelStore

logger = logging.getLogger(__name__)

MAX_ICS_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 30  # per network operation
TOTAL_SECONDS = 90  # for the whole download
MAX_OCCURRENCES = 5_000
WINDOW_PAST = timedelta(days=60)
WINDOW_FUTURE = timedelta(days=240)
SYNC_EVERY = timedelta(minutes=15)
MAX_RETRY_DELAY = timedelta(hours=6)


def retry_delay(failures: int) -> timedelta:
    """After n failures in a row: 15 min, 30 min, 1 h… up to 6 h (a wrong password must not
    hammer the university server and get the account locked)."""
    if failures <= 0:
        return SYNC_EVERY
    return min(SYNC_EVERY * (2 ** (failures - 1)), MAX_RETRY_DELAY)


class CalendarError(Exception):
    """A calendar could not be read; the message is safe to show (no secret in it)."""


@dataclass(frozen=True)
class Source:
    url: str
    username: str | None = None
    password: str | None = None


# ---------------------------------------------------------------- secrets


class Vault:
    """Encrypts calendar sources with a key derived from the session secret."""

    def __init__(self, secret: str) -> None:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"pige-calendars", info=b"calendar sources v1").derive(
            secret.encode("utf-8")
        )
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def seal(self, source: Source) -> str:
        data = {"url": source.url, "username": source.username, "password": source.password}
        return self._fernet.encrypt(json.dumps(data).encode("utf-8")).decode("ascii")

    def open(self, sealed: str) -> Source:
        try:
            data = json.loads(self._fernet.decrypt(sealed.encode("ascii")))
        except (InvalidToken, ValueError) as exc:
            raise CalendarError(
                "Adresse illisible : la clé du serveur a changé. Saisis de nouveau l'adresse du calendrier."
            ) from exc
        return Source(url=data["url"], username=data.get("username"), password=data.get("password"))


# ---------------------------------------------------------------- addresses


def normalize_url(text: str) -> str:
    """webcal(s):// becomes https://; only https is accepted (http only for localhost tests)."""
    url = text.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise CalendarError("Adresse de calendrier invalide (caractère de contrôle).")
    # Spaces and accents are percent-encoded, as a browser would.
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    for prefix in ("webcals://", "webcal://"):
        if url.lower().startswith(prefix):
            url = "https://" + url[len(prefix):]
    parts = urllib.parse.urlsplit(url)
    local = parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme != "https" and not local:
        raise CalendarError("L'adresse du calendrier doit commencer par https:// (ou webcal://).")
    if not parts.hostname:
        raise CalendarError("Adresse de calendrier invalide.")
    if parts.username or parts.password:
        raise CalendarError("Mets l'identifiant et le mot de passe dans leurs champs, pas dans l'adresse.")
    return url


def shown_host(url: str) -> str:
    """What may be displayed or logged of a feed address: scheme and host only."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or '?'}/…"


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """No downgrade to HTTP when credentials are sent; credentials dropped when the host changes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if new.scheme not in ("http", "https"):
            raise urllib.error.HTTPError(newurl, code, "redirect to a non-HTTP address refused", headers, fp)
        if old.scheme == "https" and new.scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "redirect from HTTPS to HTTP refused", headers, fp)
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        same = (new.hostname or "").lower() == (old.hostname or "").lower() and (new.port or 0) == (old.port or 0)
        if new_req is not None and not same:
            new_req.headers.pop("Authorization", None)
            new_req.unredirected_hdrs.pop("Authorization", None)
        return new_req


def _download(url: str, headers: dict[str, str], *, method: str = "GET", body: bytes | None = None) -> bytes:
    """One HTTP exchange with the safety rules (size, total time, redirects, safe messages)."""
    host = shown_host(url)
    opener = urllib.request.build_opener(_SafeRedirects())
    deadline = clock.monotonic() + TOTAL_SECONDS
    request = urllib.request.Request(url, headers=headers, data=body, method=method)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_ICS_BYTES:
                    break
                if clock.monotonic() > deadline:
                    raise CalendarError(f"Le serveur du calendrier est trop lent ({host}).")
            data = b"".join(chunks)
    except urllib.error.HTTPError as exc:
        logger.warning("Calendar %s: HTTP %s", host, exc.code)
        if exc.code in (401, 403):
            raise CalendarError("Accès refusé par le serveur du calendrier : vérifie l'identifiant et le mot de passe.") from exc
        if exc.code == 404:
            raise CalendarError("Calendrier introuvable à cette adresse (404).") from exc
        raise CalendarError(f"Le serveur du calendrier répond {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as exc:
        # Never the exception text: it may quote the address path, which holds the private token.
        logger.warning("Calendar %s: network error %s", host, type(exc).__name__)
        raise CalendarError(f"Serveur du calendrier injoignable ({host}).") from exc
    if len(data) > MAX_ICS_BYTES:
        raise CalendarError("Calendrier trop volumineux (plus de 10 Mo).")
    return data


def is_caldav(url: str) -> bool:
    """A CalDAV collection (as Thunderbird shows it: « …/dav/…/Calendar/ ») rather than an .ics file."""
    path = urllib.parse.urlsplit(url).path
    return path.endswith("/") and not urllib.parse.urlsplit(url).query


_CALDAV_QUERY = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>
"""


def merge_caldav(xml: bytes) -> bytes:
    """The events of a CalDAV « multistatus » answer, as one ICS calendar."""
    import xml.etree.ElementTree as ET

    import icalendar

    head = xml[:2048].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in xml.upper():
        raise CalendarError("Réponse CalDAV refusée (déclarations XML).")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CalendarError("Ce n'est pas une réponse CalDAV lisible.") from exc
    merged = icalendar.Calendar()
    merged.add("prodid", "-//P.IGE//CalDAV//FR")
    merged.add("version", "2.0")
    zones: set[str] = set()
    found = 0
    for node in root.iter("{urn:ietf:params:xml:ns:caldav}calendar-data"):
        if not node.text or "BEGIN:VCALENDAR" not in node.text.upper():
            continue
        try:
            part = icalendar.Calendar.from_ical(node.text)
        except Exception as exc:  # one broken event must not hide the others
            logger.warning("CalDAV: unreadable event skipped (%s)", type(exc).__name__)
            continue
        for component in part.subcomponents:
            if component.name == "VTIMEZONE":
                tzid = str(component.get("TZID", ""))
                if tzid in zones:
                    continue
                zones.add(tzid)
            merged.add_component(component)
        found += 1
    if not found and root.tag != "{DAV:}multistatus":
        raise CalendarError("Ce n'est pas un calendrier CalDAV (réponse inattendue).")
    data: bytes = merged.to_ical()
    return data


def fetch(source: Source, start: datetime | None = None, end: datetime | None = None) -> bytes:
    """Download a calendar as ICS: an .ics address directly, a CalDAV collection by a REPORT
    limited to the window (raises CalendarError with a message safe to show)."""
    url = normalize_url(source.url)
    headers = {"User-Agent": "PIGE-Agenda/1.0", "Accept": "text/calendar, text/plain;q=0.8, */*;q=0.1"}
    if source.username and source.password:
        if not url.startswith("https://"):
            raise CalendarError("Identifiants refusés hors HTTPS.")
        token = base64.b64encode(f"{source.username}:{source.password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    if is_caldav(url):
        now = datetime.now(timezone.utc)
        first, last = start or now - WINDOW_PAST, end or now + WINDOW_FUTURE
        query = _CALDAV_QUERY.format(
            start=first.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            end=last.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        )
        headers.update({"Depth": "1", "Content-Type": "application/xml; charset=utf-8", "Accept": "application/xml, text/xml"})
        return merge_caldav(_download(url, headers, method="REPORT", body=query.encode("utf-8")))
    data = _download(url, headers)
    if b"BEGIN:VCALENDAR" not in data[:4096].upper():
        raise CalendarError(
            "Ce n'est pas un calendrier (format ICS attendu). Pour une adresse CalDAV, garde la barre « / » finale."
        )
    return data


# ---------------------------------------------------------------- reading


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _address(value: Any) -> str:
    text = str(value or "")
    return text[7:] if text.lower().startswith("mailto:") else text


def parse_events(
    calendar_id: str, data: bytes, window_start: datetime, window_end: datetime, local_zone: Any
) -> list[dict[str, Any]]:
    """The events of an ICS feed inside the window, recurrences expanded, as store dicts."""
    import icalendar
    import recurring_ical_events

    def occurrences() -> Any:
        cal = icalendar.Calendar.from_ical(data)
        for count, component in enumerate(recurring_ical_events.of(cal).after(window_start)):
            if count >= MAX_OCCURRENCES:
                raise CalendarError("Calendrier trop chargé (plus de 5 000 événements sur la période).")
            begin = component.get("DTSTART")
            if begin is not None:
                moment = begin.dt
                if not isinstance(moment, datetime):
                    moment = datetime.combine(moment, datetime.min.time(), local_zone)
                elif moment.tzinfo is None:
                    moment = moment.replace(tzinfo=local_zone)
                if moment >= window_end:
                    return
            yield component

    out: dict[str, dict[str, Any]] = {}
    try:
        for event in occurrences():
            if event.name != "VEVENT":
                continue
            _read_event(event, calendar_id, local_zone, out)
    except CalendarError:
        raise
    except Exception as exc:  # malformed feeds raise many different errors
        raise CalendarError(f"Calendrier illisible ({type(exc).__name__}).") from exc
    return list(out.values())


def _recurrence_key(event: Any, local_zone: Any) -> str:
    """The occurrence's original date (RECURRENCE-ID): stays the same when one occurrence is moved."""
    rid = event.get("RECURRENCE-ID")
    if rid is None:
        return ""
    value = rid.dt
    if isinstance(value, datetime):
        return _utc_text(value if value.tzinfo else value.replace(tzinfo=local_zone))
    return value.isoformat()


def _read_event(event: Any, calendar_id: str, local_zone: Any, out: dict[str, dict[str, Any]]) -> None:
    start = event.get("DTSTART")
    if start is None:
        return
    start_value = start.dt
    end_field = event.get("DTEND")
    end_value = end_field.dt if end_field is not None else None
    all_day = isinstance(start_value, date) and not isinstance(start_value, datetime)
    if all_day:
        first: date = start_value
        last: date = end_value if isinstance(end_value, date) and not isinstance(end_value, datetime) else first + timedelta(days=1)
        start_at, end_at = first.isoformat(), max(last, first + timedelta(days=1)).isoformat()
    else:
        begin = start_value if start_value.tzinfo else start_value.replace(tzinfo=local_zone)
        finish = end_value if isinstance(end_value, datetime) else begin + timedelta(hours=1)
        if finish.tzinfo is None:
            finish = finish.replace(tzinfo=local_zone)
        if finish <= begin:
            finish = begin + timedelta(hours=1)  # no end given: an hour, like most meetings
        start_at, end_at = _utc_text(begin), _utc_text(finish)
    uid = str(event.get("UID") or "") or hashlib.sha256(f"{start_at}{event.get('SUMMARY')}".encode()).hexdigest()
    # Same meeting, same id: by UID, and for a recurring one by its original date, so a
    # moved occurrence keeps its notes and time.
    key = _recurrence_key(event, local_zone)
    event_id = hashlib.sha256(f"{calendar_id}|{uid}|{key}".encode("utf-8")).hexdigest()[:32]
    attendees = []
    raw = event.get("ATTENDEE")
    for item in raw if isinstance(raw, list) else ([raw] if raw is not None else []):
        name = str(getattr(item, "params", {}).get("CN", "") or "")
        attendees.append({"name": name[:120], "email": _address(item).lower()[:200]})
    organizer = event.get("ORGANIZER")
    status = _text(event.get("STATUS"), 20)
    out[event_id] = {
        "id": event_id,
        "uid": uid[:500],
        "start_at": start_at,
        "end_at": end_at,
        "all_day": all_day,
        "title": _text(event.get("SUMMARY"), 300) or "(sans titre)",
        "location": _text(event.get("LOCATION"), 300),
        "description": _text(event.get("DESCRIPTION"), 2000),
        "organizer": _address(organizer).lower()[:200] if organizer is not None else None,
        "attendees": attendees[:100],
        "status": status.lower() if status else None,
    }


# ---------------------------------------------------------------- syncing


class Agenda:
    """Syncs the calendars, one sync per calendar at a time, also on a timer in the background."""

    def __init__(
        self, store: ModelStore, vault: Vault, local_zone: Any,
        fetcher: Callable[[Source, datetime, datetime], bytes] = fetch,
    ) -> None:
        self.store = store
        self.vault = vault
        self.zone = local_zone
        self.fetcher = fetcher
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._stop = threading.Event()

    def _lock_for(self, calendar_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(calendar_id, threading.Lock())

    def sync(self, calendar_id: str, *, now: datetime | None = None) -> dict[str, int]:
        """Fetch one calendar and store its events; records (and re-raises) a readable error."""
        moment = now or datetime.now(timezone.utc)
        start, end = moment - WINDOW_PAST, moment + WINDOW_FUTURE
        with self._lock_for(calendar_id):
            calendar = self.store.get_calendar(calendar_id)  # read under the lock: never a stale address
            try:
                source = self.vault.open(calendar.source_enc)
                events = parse_events(calendar_id, self.fetcher(source, start, end), start, end, self.zone)
            except CalendarError as exc:
                self.store.calendar_synced(calendar_id, error=str(exc))
                raise
            except Exception as exc:
                # Unknown failure: only its type is kept, never its text (it could quote the address).
                logger.warning("Calendar %s: unexpected %s", calendar.source_host, type(exc).__name__)
                error = CalendarError(f"Lecture impossible ({type(exc).__name__}).")
                self.store.calendar_synced(calendar_id, error=str(error))
                raise error from None
            counts = self.store.replace_calendar_events(
                calendar_id, events, window_start=_utc_text(start), window_end=_utc_text(end)
            )
            self.store.calendar_synced(calendar_id)
            logger.info("Calendar %s synced: %s", calendar.name, counts)
            return counts

    def sync_due(self, now: datetime | None = None) -> None:
        """Sync every active calendar whose next attempt is due (backing off after failures)."""
        moment = now or datetime.now(timezone.utc)
        for calendar in self.store.list_calendars():
            if not calendar.active:
                continue
            last = calendar.last_attempt or calendar.last_sync
            if last:
                when = datetime.strptime(last, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                if moment - when < retry_delay(calendar.failures):
                    continue
            try:
                self.sync(calendar.id, now=moment)
            except CalendarError:
                pass  # recorded on the calendar, shown in Réglages

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(60):
                try:
                    self.sync_due()
                except Exception as exc:  # the loop must survive anything (e.g. database busy)
                    logger.warning("Calendar loop: %s", type(exc).__name__)

        threading.Thread(target=loop, name="pige-agenda", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
