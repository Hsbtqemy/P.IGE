"""Calendar subscriptions: credentials, redirects, size limits, logs and empty feeds."""

from __future__ import annotations

import logging
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from pige.core import calendar_sync
from pige.core.calendar_sync import (
    MAX_ICS_BYTES,
    CalendarSyncManager,
    _normalize_calendar_url,
    _redact_url,
    _SafeRedirectHandler,
)
from pige.core.service import PigeService
from pige.core.storage import Storage, read_calendar_events

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
{events}END:VCALENDAR
"""
EVENT = """BEGIN:VEVENT
UID:{uid}
DTSTART;VALUE=DATE:20991010
DTEND;VALUE=DATE:20991011
SUMMARY:Réunion {uid}
END:VEVENT
"""


class UrlHelpersTests(unittest.TestCase):
    def test_webcal_becomes_https(self) -> None:
        self.assertEqual(_normalize_calendar_url("webcal://cal.example/x.ics"), "https://cal.example/x.ics")
        self.assertEqual(_normalize_calendar_url("webcals://cal.example/x.ics"), "https://cal.example/x.ics")

    def test_redacted_url_hides_path_and_token(self) -> None:
        secret = "https://calendar.google.com/calendar/ical/me%40x/private-abc123/basic.ics?k=1"
        self.assertEqual(_redact_url(secret), "https://calendar.google.com/…")
        self.assertEqual(_redact_url("/home/me/agenda.ics"), "agenda.ics")


class FetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        service = PigeService(Storage(Path(self._tmp.name) / "data"))
        service.init_storage()
        self.manager = CalendarSyncManager(service)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_credentials_never_sent_over_http(self) -> None:
        with mock.patch.object(urllib.request.OpenerDirector, "open") as opened:
            result = self.manager._fetch_ics("http://cal.example/x.ics", "me", "secret")
        self.assertIsNone(result)
        opened.assert_not_called()

    def test_oversized_calendar_is_refused(self) -> None:
        big = Path(self._tmp.name) / "big.ics"
        big.write_bytes(b"x" * (MAX_ICS_BYTES + 1))
        self.assertIsNone(self.manager._fetch_ics(str(big)))

    def test_logs_do_not_contain_the_secret_url(self) -> None:
        url = "https://cal.example/private-token-123/basic.ics"
        error = urllib.error.URLError("unreachable")
        with mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=error):
            with self.assertLogs(calendar_sync.logger, level=logging.INFO) as logs:
                self.manager._fetch_ics(url, "me", "pw")
        joined = "\n".join(logs.output)
        self.assertNotIn("private-token-123", joined)
        self.assertNotIn("pw", joined.replace("https", ""))
        self.assertIn("cal.example", joined)


class RedirectTests(unittest.TestCase):
    def _redirect(self, old: str, new: str, auth: bool = True) -> urllib.request.Request | None:
        req = urllib.request.Request(old, headers={"Authorization": "Basic abc"} if auth else {})
        return _SafeRedirectHandler().redirect_request(req, None, 302, "Found", {}, new)

    def test_same_host_keeps_credentials(self) -> None:
        new = self._redirect("https://cal.example/a", "https://cal.example/b")
        self.assertEqual(new.get_header("Authorization"), "Basic abc")

    def test_other_host_drops_credentials(self) -> None:
        new = self._redirect("https://cal.example/a", "https://evil.example/b")
        self.assertIsNone(new.get_header("Authorization"))

    def test_downgrade_to_http_refused_with_credentials(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self._redirect("https://cal.example/a", "http://cal.example/b")

    def test_non_http_redirect_refused(self) -> None:
        with self.assertRaises(urllib.error.HTTPError):
            self._redirect("https://cal.example/a", "ftp://cal.example/b", auth=False)


class EmptyFeedTests(unittest.TestCase):
    def test_empty_feed_does_not_wipe_local_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = PigeService(Storage(Path(tmp) / "data"))
            service.init_storage()
            manager = CalendarSyncManager(service)
            feed = Path(tmp) / "agenda.ics"
            feed.write_text(ICS.format(events=EVENT.format(uid="a") + EVENT.format(uid="b")), encoding="utf-8")
            sub = manager.create_subscription("Agenda", str(feed))
            first = manager.sync_subscription(sub.id)
            self.assertEqual(first["added"], 2, first)
            feed.write_text(ICS.format(events=""), encoding="utf-8")
            second = manager.sync_subscription(sub.id)
            self.assertEqual(second["deleted"], 0)
            self.assertEqual(len(read_calendar_events(service.storage)), 2)
            # A real removal of one event is still applied.
            feed.write_text(ICS.format(events=EVENT.format(uid="a")), encoding="utf-8")
            third = manager.sync_subscription(sub.id)
            self.assertEqual(third["deleted"], 1)

    def test_feed_with_only_past_events_is_a_real_change(self) -> None:
        past = EVENT.replace("20991010", "20000101").replace("20991011", "20000102")
        with tempfile.TemporaryDirectory() as tmp:
            service = PigeService(Storage(Path(tmp) / "data"))
            service.init_storage()
            manager = CalendarSyncManager(service)
            feed = Path(tmp) / "agenda.ics"
            feed.write_text(ICS.format(events=EVENT.format(uid="a")), encoding="utf-8")
            sub = manager.create_subscription("Agenda", str(feed))
            manager.sync_subscription(sub.id)
            feed.write_text(ICS.format(events=past.format(uid="old")), encoding="utf-8")
            result = manager.sync_subscription(sub.id)
            self.assertEqual(result["deleted"], 1, result)
            self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
