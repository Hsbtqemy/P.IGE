"""Calendars followed by the server: reading ICS feeds, keeping their secrets, notes and time from events."""

from __future__ import annotations

import http.server
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("recurring_ical_events")

from fastapi.testclient import TestClient  # noqa: E402

from pige.server.agenda import CalendarError, Source, Vault, fetch, normalize_url, parse_events, shown_host  # noqa: E402
from pige.server.app import CSRF_HEADER, create_app  # noqa: E402
from pige.server.auth import hash_password, new_api_token  # noqa: E402
from pige.server.config import Settings  # noqa: E402

PASSWORD = "correct horse battery staple"
_HASH = hash_password(PASSWORD)
_TOKEN, _TOKEN_HASH = new_api_token()
PARIS = ZoneInfo("Europe/Paris")
WEB = {CSRF_HEADER: "web"}

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:weekly@x
DTSTART;TZID=Europe/Paris:20261019T100000
DTEND;TZID=Europe/Paris:20261019T113000
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Point FoReLLIS
LOCATION:MSHS salle 2
ORGANIZER;CN=Anne Martin:mailto:Anne.Martin@univ.fr
ATTENDEE;CN=Paul Durand:mailto:paul@univ.fr
ATTENDEE;CN=Hugo:mailto:hugo@univ.fr
END:VEVENT
BEGIN:VEVENT
UID:allday@x
DTSTART;VALUE=DATE:20261021
DTEND;VALUE=DATE:20261023
SUMMARY:Colloque
END:VEVENT
BEGIN:VEVENT
UID:floating@x
DTSTART:20261020T140000
SUMMARY:Sans fin
END:VEVENT
END:VCALENDAR
"""

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- pure parts


def test_addresses():
    assert normalize_url("webcal://cal.univ.fr/x.ics") == "https://cal.univ.fr/x.ics"
    assert normalize_url(" https://cal.univ.fr/x.ics ") == "https://cal.univ.fr/x.ics"
    for bad in ("http://cal.univ.fr/x.ics", "ftp://x/y", "https:///x", "https://user:pw@cal.univ.fr/x.ics"):
        with pytest.raises(CalendarError):
            normalize_url(bad)
    assert shown_host("https://cal.univ.fr/private/token123.ics?key=secret") == "https://cal.univ.fr/…"


def test_vault_keeps_sources_unreadable_without_the_key():
    vault = Vault("s" * 48)
    sealed = vault.seal(Source("https://cal.univ.fr/token.ics", "hugo", "motdepasse"))
    assert "motdepasse" not in sealed and "token" not in sealed
    assert vault.open(sealed) == Source("https://cal.univ.fr/token.ics", "hugo", "motdepasse")
    with pytest.raises(CalendarError):
        Vault("t" * 48).open(sealed)


def test_parse_expands_recurrences_and_reads_details():
    events = parse_events("cal", ICS, datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc), PARIS)
    weekly = sorted((e for e in events if e["uid"] == "weekly@x"), key=lambda e: e["start_at"])
    assert [e["start_at"][:16] for e in weekly] == ["2026-10-19T08:00", "2026-10-26T09:00", "2026-11-02T09:00"]  # DST
    assert weekly[0]["end_at"][:16] == "2026-10-19T09:30"
    assert weekly[0]["location"] == "MSHS salle 2"
    assert weekly[0]["organizer"] == "anne.martin@univ.fr"
    assert {a["email"] for a in weekly[0]["attendees"]} == {"paul@univ.fr", "hugo@univ.fr"}
    assert len({e["id"] for e in weekly}) == 3
    allday = next(e for e in events if e["uid"] == "allday@x")
    assert (allday["all_day"], allday["start_at"], allday["end_at"]) == (True, "2026-10-21", "2026-10-23")
    floating = next(e for e in events if e["uid"] == "floating@x")
    assert floating["start_at"][:16] == "2026-10-20T12:00" and floating["end_at"][:16] == "2026-10-20T13:00"
    with pytest.raises(CalendarError):
        parse_events("cal", b"BEGIN:VCALENDAR\nnot really", NOW, NOW, PARIS)


class _Feed(http.server.BaseHTTPRequestHandler):
    seen_auth: list[str | None] = []

    def do_GET(self):  # noqa: N802
        _Feed.seen_auth.append(self.headers.get("Authorization"))
        if self.path == "/locked.ics":
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/away.ics":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/ok.ics" % self.server.server_port)
            self.end_headers()
            return
        body = ICS if self.path == "/ok.ics" else b"<html>not a calendar</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def feed():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Feed)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Feed.seen_auth = []
    yield f"http://localhost:{server.server_port}"
    server.shutdown()


def test_fetch_rules(feed):
    assert fetch(Source(f"{feed}/ok.ics")).startswith(b"BEGIN:VCALENDAR")
    with pytest.raises(CalendarError, match="Accès refusé"):
        fetch(Source(f"{feed}/locked.ics"))
    with pytest.raises(CalendarError, match="pas un calendrier"):
        fetch(Source(f"{feed}/page.html"))
    with pytest.raises(CalendarError, match="hors HTTPS"):  # never a password over plain HTTP
        fetch(Source(f"{feed}/ok.ics", "hugo", "secret"))
    assert all(a is None for a in _Feed.seen_auth)
    with pytest.raises(CalendarError, match="injoignable"):
        fetch(Source("http://localhost:1/x.ics"))


# ---------------------------------------------------------------- API


@pytest.fixture()
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path, password_hash=_HASH, session_secret="s" * 48, api_token_hashes=frozenset({_TOKEN_HASH}),
        cookie_secure=False, background_jobs=False,
    )
    application = create_app(settings)
    feeds: dict[str, bytes] = {"https://cal.univ.fr/hugo.ics": ICS}

    def fake_fetch(source: Source, *_window) -> bytes:
        if source.url not in feeds:
            raise CalendarError("Calendrier introuvable à cette adresse (404).")
        return feeds[source.url]

    application.state.agenda.fetcher = fake_fetch
    application.state.feeds = feeds
    return application


def web(app) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return c


def test_calendar_secrets_never_leave_the_server(app):
    c = web(app)
    added = c.post("/api/v2/calendars", json={
        "name": "Université", "url": "webcal://cal.univ.fr/hugo.ics", "username": "hugo", "password": "motdepasse"},
        headers=WEB).json()
    assert added["sync"]["ok"] and added["sync"]["added"] >= 3
    listed = c.get("/api/v2/calendars").json()
    assert listed[0]["host"] == "https://cal.univ.fr/…" and listed[0]["has_password"] is True
    assert "hugo.ics" not in str(listed) and "motdepasse" not in str(listed)
    token = TestClient(app, headers={"Authorization": f"Bearer {_TOKEN}"})
    assert token.post("/api/v2/calendars", json={"name": "x", "url": "https://cal.univ.fr/hugo.ics"}).status_code == 403
    assert token.get("/api/v2/calendars").status_code == 200
    assert c.post("/api/v2/calendars", json={"name": "x", "url": "http://cal.univ.fr/x.ics"}, headers=WEB).status_code == 400


def test_sync_errors_are_kept_and_shown(app):
    c = web(app)
    added = c.post("/api/v2/calendars", json={"name": "Perdu", "url": "https://cal.univ.fr/nope.ics"}, headers=WEB).json()
    assert added["sync"] == {"ok": False, "error": "Calendrier introuvable à cette adresse (404)."}
    assert c.get("/api/v2/calendars").json()[0]["last_error"].startswith("Calendrier introuvable")
    cid = added["calendar"]["id"]
    assert c.post(f"/api/v2/calendars/{cid}/sync", headers=WEB).status_code == 502
    fixed = c.patch(f"/api/v2/calendars/{cid}", json={"url": "https://cal.univ.fr/hugo.ics"}, headers=WEB).json()
    assert fixed["sync"]["ok"] and fixed["calendar"]["last_error"] is None


def _agenda_with_meeting(app):
    c = web(app)
    space = c.post("/api/v2/spaces", json={"name": "FoReLLIS"}, headers=WEB).json()
    c.post("/api/v2/spaces", json={"name": "À trier"}, headers=WEB)
    project = c.post("/api/v2/projects", json={"space_id": space["id"], "name": "DICODIACHRO"}, headers=WEB).json()
    paul = c.post("/api/v2/people", json={"name": "Durand Paul"}, headers=WEB).json()
    c.patch(f"/api/v2/people/{paul['id']}", json={"email": "Paul@univ.fr"}, headers=WEB)
    c.post("/api/v2/calendars", json={"name": "Université", "url": "https://cal.univ.fr/hugo.ics"}, headers=WEB)
    week = c.get("/api/v2/agenda?start=2026-10-19&days=7&tz=Europe/Paris").json()
    return c, project, paul, week


def test_agenda_notes_and_time_from_a_meeting(app):
    c, project, paul, week = _agenda_with_meeting(app)
    titles = [(e["title"], e["all_day"]) for e in week]
    assert ("Colloque", True) in titles and titles.count(("Point FoReLLIS", False)) == 1
    meeting = next(e for e in week if e["title"] == "Point FoReLLIS")
    assert meeting["calendar"] == "Université" and meeting["entry_id"] is None

    noted = c.post(f"/api/v2/agenda/{meeting['id']}/note?tz=Europe/Paris", json={"project_id": project["id"]}, headers=WEB).json()
    assert noted["created"] is True
    entry = c.get(f"/api/v2/entries/{noted['entry_id']}").json()
    assert (entry["kind"], entry["entry_date"], entry["start_time"], entry["end_time"]) == ("meeting", "2026-10-19", "10:00", "11:30")
    assert entry["project_id"] == project["id"] and [p["id"] for p in entry["people"]] == [paul["id"]]
    assert "Lieu : MSHS salle 2" in entry["body"]
    again = c.post(f"/api/v2/agenda/{meeting['id']}/note", json={}, headers=WEB).json()
    assert (again["entry_id"], again["created"]) == (noted["entry_id"], False)
    assert again["event"]["place"] == {"project_id": project["id"], "space_id": project["space_id"]}

    counted = c.post(f"/api/v2/agenda/{meeting['id']}/count", json={"project_id": project["id"]}, headers=WEB).json()
    assert counted["created"] is True
    day = c.get("/api/v2/days/2026-10-19?tz=Europe/Paris").json()
    block = day["blocks"][0]["block"]
    assert (block["source"], block["overlap_mode"], block["entry_id"]) == ("agenda", "exclusive", noted["entry_id"])
    assert day["presence_seconds"] == 5400
    allday = next(e for e in week if e["all_day"])
    assert c.post(f"/api/v2/agenda/{allday['id']}/count", json={}, headers=WEB).status_code == 400
    # without a place: the meeting goes to « À trier »
    other = c.get("/api/v2/agenda?start=2026-10-26&days=1&tz=Europe/Paris").json()[0]
    loose = c.post(f"/api/v2/agenda/{other['id']}/note", json={}, headers=WEB).json()
    assert c.get(f"/api/v2/entries/{loose['entry_id']}").json()["project_id"] is None


def test_a_noted_meeting_is_filed_elsewhere_with_its_time(app):
    c, project, _paul, week = _agenda_with_meeting(app)
    meeting = next(e for e in week if e["title"] == "Point FoReLLIS")
    assert meeting["place"] is None
    assert c.post(f"/api/v2/agenda/{meeting['id']}/place", json={"project_id": project["id"]}, headers=WEB).status_code == 409
    noted = c.post(f"/api/v2/agenda/{meeting['id']}/note", json={}, headers=WEB).json()  # into « À trier »
    c.post(f"/api/v2/agenda/{meeting['id']}/count", json={}, headers=WEB)
    week = c.get("/api/v2/agenda?start=2026-10-19&days=7&tz=Europe/Paris").json()
    inbox = next(e for e in week if e["id"] == meeting["id"])["place"]
    assert inbox["project_id"] is None and inbox["space_id"]
    moved = c.post(f"/api/v2/agenda/{meeting['id']}/place", json={"project_id": project["id"]}, headers=WEB).json()
    assert moved["place"] == {"project_id": project["id"], "space_id": project["space_id"]}
    assert c.get(f"/api/v2/entries/{noted['entry_id']}").json()["project_id"] == project["id"]
    block = c.get("/api/v2/days/2026-10-19?tz=Europe/Paris").json()["blocks"][0]["block"]
    assert block["project_id"] == project["id"]
    back = c.post(f"/api/v2/agenda/{meeting['id']}/place", json={"space_id": inbox["space_id"]}, headers=WEB).json()
    assert back["place"] == inbox
    assert c.post(f"/api/v2/agenda/{meeting['id']}/place", json={}, headers=WEB).status_code == 400


def test_events_that_disappear_are_removed_unless_used(app):
    c, project, _paul, week = _agenda_with_meeting(app)
    meeting = next(e for e in week if e["title"] == "Point FoReLLIS")
    c.post(f"/api/v2/agenda/{meeting['id']}/note", json={"project_id": project["id"]}, headers=WEB)
    app.state.feeds["https://cal.univ.fr/hugo.ics"] = b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
    cid = c.get("/api/v2/calendars").json()[0]["id"]
    app.state.agenda.sync(cid, now=NOW)
    left = c.get("/api/v2/agenda?start=2026-10-19&days=21&tz=Europe/Paris").json()
    assert [(e["title"], e["status"]) for e in left] == [("Point FoReLLIS", "removed")]  # kept: a note was taken
    assert c.delete(f"/api/v2/calendars/{cid}", headers=WEB).status_code == 204
    assert c.get("/api/v2/agenda?start=2026-10-19&days=7").json() == []


# ---------------------------------------------------------------- review follow-ups


def test_odd_addresses_are_encoded_or_refused():
    assert normalize_url("https://cal.univ.fr/mon agenda.ics") == "https://cal.univ.fr/mon%20agenda.ics"
    assert normalize_url("https://cal.univ.fr/é.ics") == "https://cal.univ.fr/%C3%A9.ics"
    with pytest.raises(CalendarError):
        normalize_url("https://cal.univ.fr/a\nb.ics")


def test_unexpected_errors_are_recorded_without_their_text(app, caplog):
    c = web(app)

    def broken(source, *_window):
        raise RuntimeError(f"boom {source.url}")

    app.state.agenda.fetcher = broken
    r = c.post("/api/v2/calendars", json={"name": "x", "url": "https://cal.univ.fr/secret-token.ics"}, headers=WEB)
    assert r.status_code == 201 and r.json()["sync"] == {"ok": False, "error": "Lecture impossible (RuntimeError)."}
    assert "secret-token" not in caplog.text and "secret-token" not in str(c.get("/api/v2/calendars").json())


def test_failing_calendars_back_off():
    from pige.server.agenda import retry_delay

    assert [retry_delay(n).total_seconds() / 60 for n in range(6)] == [15, 15, 30, 60, 120, 240]
    assert retry_delay(20).total_seconds() == 6 * 3600


def test_background_sync_respects_the_back_off(app):
    c = web(app)
    calls = []

    def failing(source, *_window):
        calls.append(source.url)
        raise CalendarError("Accès refusé par le serveur du calendrier : vérifie l'identifiant et le mot de passe.")

    app.state.agenda.fetcher = failing
    c.post("/api/v2/calendars", json={"name": "x", "url": "https://cal.univ.fr/a.ics", "username": "h", "password": "p"},
           headers=WEB)
    assert len(calls) == 1
    agenda = app.state.agenda
    later = datetime.now(timezone.utc)
    from datetime import timedelta

    agenda.sync_due(now=later + timedelta(minutes=5))  # too early after a failure
    assert len(calls) == 1
    agenda.sync_due(now=later + timedelta(minutes=16))  # first retry after 15 min
    assert len(calls) == 2
    agenda.sync_due(now=later + timedelta(minutes=30))  # second failure: wait 30 min from then
    assert len(calls) == 2
    assert c.get("/api/v2/calendars").json()[0]["failures"] == 2


def test_a_moved_occurrence_keeps_its_note(app):
    c, project, _paul, week = _agenda_with_meeting(app)
    meeting = next(e for e in week if e["title"] == "Point FoReLLIS")
    c.post(f"/api/v2/agenda/{meeting['id']}/note", json={"project_id": project["id"]}, headers=WEB)
    moved = ICS.replace(b"END:VCALENDAR", b"""BEGIN:VEVENT
UID:weekly@x
RECURRENCE-ID;TZID=Europe/Paris:20261019T100000
DTSTART;TZID=Europe/Paris:20261019T160000
DTEND;TZID=Europe/Paris:20261019T170000
SUMMARY:Point FoReLLIS (d\\xc3\\xa9plac\\xc3\\xa9)
END:VEVENT
END:VCALENDAR""")
    app.state.feeds["https://cal.univ.fr/hugo.ics"] = moved
    cid = c.get("/api/v2/calendars").json()[0]["id"]
    app.state.agenda.sync(cid, now=NOW)
    day = c.get("/api/v2/agenda?start=2026-10-19&days=1&tz=Europe/Paris").json()
    points = [e for e in day if e["title"].startswith("Point")]
    assert len(points) == 1 and points[0]["id"] == meeting["id"] and points[0]["entry_id"]
    assert points[0]["start"].startswith("2026-10-19T14:00")


def test_a_new_server_never_gets_the_old_password(app):
    c = web(app)
    seen = []

    def record(source, *_window):
        seen.append(source)
        return ICS

    app.state.agenda.fetcher = record
    added = c.post("/api/v2/calendars", json={"name": "x", "url": "https://cal.univ.fr/a.ics", "username": "h", "password": "p"},
                   headers=WEB).json()
    c.patch(f"/api/v2/calendars/{added['calendar']['id']}", json={"url": "https://autre.example/a.ics"}, headers=WEB)
    assert (seen[0].username, seen[0].password) == ("h", "p")
    assert (seen[1].url, seen[1].username, seen[1].password) == ("https://autre.example/a.ics", None, None)
    same_host = c.patch(f"/api/v2/calendars/{added['calendar']['id']}", json={"url": "https://autre.example/b.ics",
                        "username": "h2", "password": "p2"}, headers=WEB).json()
    assert same_host["calendar"]["has_password"] is True and (seen[2].username, seen[2].password) == ("h2", "p2")


def test_too_many_occurrences_are_refused():
    flood = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:flood@x
DTSTART:20261018T000000Z
DTEND:20261018T000030Z
RRULE:FREQ=MINUTELY
SUMMARY:x
END:VEVENT
END:VCALENDAR
"""
    with pytest.raises(CalendarError, match="trop chargé"):
        parse_events("cal", flood, NOW, NOW.replace(year=2027), PARIS)


# ---------------------------------------------------------------- CalDAV (Zimbra, as Thunderbird shows it)

MULTISTATUS = """<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
 <D:response><D:href>/dav/hugo%40univ.fr/Calendar/1.ics</D:href><D:propstat><D:prop>
  <C:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:STANDARD
DTSTART:19701025T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700329T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:copil@zimbra
DTSTART;TZID=Europe/Paris:20261020T140000
DTEND;TZID=Europe/Paris:20261020T150000
SUMMARY:COPIL
END:VEVENT
END:VCALENDAR
</C:calendar-data></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
 <D:response><D:href>/dav/hugo%40univ.fr/Calendar/2.ics</D:href><D:propstat><D:prop>
  <C:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:STANDARD
DTSTART:19701025T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:cours@zimbra
DTSTART;TZID=Europe/Paris:20261021T090000
DTEND;TZID=Europe/Paris:20261021T120000
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:Cours L3
END:VEVENT
END:VCALENDAR
</C:calendar-data></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
</D:multistatus>
"""


class _Dav(http.server.BaseHTTPRequestHandler):
    requests: list[tuple[str, str, str, bytes]] = []

    def do_REPORT(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _Dav.requests.append((self.command, self.path, self.headers.get("Depth", ""), body))
        payload = MULTISTATUS.encode() if "Calendar" in self.path else b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "a">]><x/>'
        self.send_response(207)
        self.send_header("Content-Type", "application/xml")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture()
def dav():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Dav)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Dav.requests = []
    yield f"http://localhost:{server.server_port}"
    server.shutdown()


def test_caldav_collection_is_read_with_a_report(dav):
    from pige.server.agenda import is_caldav

    url = f"{dav}/dav/hugo%40univ.fr/Calendar/"
    assert is_caldav(url) and not is_caldav(f"{dav}/home/hugo/Calendar?fmt=ics")
    start, end = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc)
    ics = fetch(Source(url), start, end)
    method, path, depth, body = _Dav.requests[0]
    assert (method, path, depth) == ("REPORT", "/dav/hugo%40univ.fr/Calendar/", "1")
    assert b'time-range start="20261001T000000Z" end="20261201T000000Z"' in body
    events = parse_events("cal", ics, start, end, PARIS)
    assert sorted(e["title"] for e in events) == ["COPIL", "Cours L3", "Cours L3"]
    copil = next(e for e in events if e["title"] == "COPIL")
    assert copil["start_at"].startswith("2026-10-20T12:00")  # 14:00 Paris (summer time) in UTC
    assert ics.count(b"BEGIN:VTIMEZONE") == 1  # merged once
    with pytest.raises(CalendarError, match="déclarations XML"):
        fetch(Source(f"{dav}/dav/hugo/Other/"), start, end)
