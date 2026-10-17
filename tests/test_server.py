"""HTTP API tests (skipped when the optional server dependencies are missing)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    from pige.server.app import CSRF_HEADER, SESSION_COOKIE, create_app
    from pige.server.auth import (
        LoginThrottle,
        SessionSigner,
        hash_password,
        new_api_token,
        verify_api_token,
        verify_password,
    )
    from pige.server.config import ConfigError, Settings

    HAVE_SERVER = True
except ImportError:  # pragma: no cover - depends on installed extras
    HAVE_SERVER = False

PASSWORD = "correct horse battery staple"
SECRET = "s" * 48
WEB = {CSRF_HEADER: "web"}


@unittest.skipUnless(HAVE_SERVER, "server extras not installed (pip install .[server])")
class AuthPrimitivesTests(unittest.TestCase):
    def test_password_hash_roundtrip(self) -> None:
        encoded = hash_password("abc def ghi jkl")
        self.assertTrue(verify_password("abc def ghi jkl", encoded))
        self.assertFalse(verify_password("abc def ghi jkm", encoded))
        self.assertFalse(verify_password("x", "not-a-hash"))

    def test_session_expiry_and_tampering(self) -> None:
        signer = SessionSigner(SECRET, max_age_seconds=60)
        value = signer.issue(now=1000)
        self.assertTrue(signer.is_valid(value, now=1030))
        self.assertFalse(signer.is_valid(value, now=1061))
        body, sig = value.split(".")
        self.assertFalse(signer.is_valid(body + "." + sig[:-2] + "AA", now=1030))
        self.assertFalse(SessionSigner("t" * 48, 60).is_valid(value, now=1030))

    def test_short_secret_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SessionSigner("short", 60)

    def test_throttle_window(self) -> None:
        throttle = LoginThrottle(max_failures=2, window_seconds=10)
        self.assertTrue(throttle.acquire("a", now=100))
        self.assertTrue(throttle.acquire("a", now=101))
        self.assertFalse(throttle.acquire("a", now=105))
        self.assertTrue(throttle.acquire("b", now=105))
        self.assertTrue(throttle.acquire("a", now=112))

    def test_throttle_success_clears_client(self) -> None:
        throttle = LoginThrottle(max_failures=2, window_seconds=10)
        throttle.acquire("a", now=100)
        throttle.succeeded("a")
        self.assertTrue(throttle.acquire("a", now=101))
        self.assertTrue(throttle.acquire("a", now=102))

    def test_throttle_global_cap_resists_address_rotation(self) -> None:
        throttle = LoginThrottle(max_failures=5, max_global_failures=3, window_seconds=10)
        for i in range(3):
            self.assertTrue(throttle.acquire(f"ip{i}", now=100))
        self.assertFalse(throttle.acquire("fresh", now=101))

    def test_session_bound_to_password_and_epoch(self) -> None:
        value = SessionSigner(SECRET, 60, bound_to="hash-1").issue(now=1000)
        self.assertTrue(SessionSigner(SECRET, 60, bound_to="hash-1").is_valid(value, now=1001))
        self.assertFalse(SessionSigner(SECRET, 60, bound_to="hash-2").is_valid(value, now=1001))
        self.assertFalse(SessionSigner(SECRET, 60, bound_to="hash-1", not_before=1500).is_valid(value, now=1600))

    def test_garbage_cookie_and_token_are_rejected_not_crashing(self) -> None:
        signer = SessionSigner(SECRET, 60)
        for junk in ("é.é", "a.b", "", "x" * 5000 + ".y", "Zm9v.\u00ff"):
            self.assertFalse(signer.is_valid(junk))
        self.assertFalse(verify_api_token("pige_é", frozenset({"0" * 64})))

    def test_token_hashes_are_validated(self) -> None:
        env = {"PIGE_DATA_DIR": "/tmp/x", "PIGE_PASSWORD_HASH": "h", "PIGE_SESSION_SECRET": SECRET}
        with self.assertRaises(ConfigError):
            Settings.from_env({**env, "PIGE_API_TOKEN_HASHES": "not-a-hash"})
        ok = Settings.from_env({**env, "PIGE_API_TOKEN_HASHES": "A" * 64})
        self.assertEqual(ok.api_token_hashes, frozenset({"a" * 64}))

    def test_settings_require_secrets(self) -> None:
        with self.assertRaises(ConfigError):
            Settings.from_env({"PIGE_DATA_DIR": "/tmp/x"})


@unittest.skipUnless(HAVE_SERVER, "server extras not installed (pip install .[server])")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.password_hash = hash_password(PASSWORD)
        cls.token, token_hash = new_api_token()
        cls.token_hashes = frozenset({token_hash})

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            data_dir=Path(self._tmp.name),
            password_hash=self.password_hash,
            session_secret=SECRET,
            api_token_hashes=self.token_hashes,
            cookie_secure=False,
        )
        self.client = TestClient(create_app(settings))

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def login(self) -> None:
        response = self.client.post("/api/login", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def test_everything_requires_auth(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.post("/api/tasks", json={"title": "x"}).status_code, 401)
        bad = {"Authorization": "Bearer pige_nope"}
        self.assertEqual(self.client.get("/api/tasks", headers=bad).status_code, 401)

    def test_wrong_password_and_throttling(self) -> None:
        for _ in range(5):
            self.assertEqual(self.client.post("/api/login", json={"password": "nope"}).status_code, 401)
        blocked = self.client.post("/api/login", json={"password": PASSWORD})
        self.assertEqual(blocked.status_code, 429)

    def test_session_cookie_flags(self) -> None:
        response = self.client.post("/api/login", json={"password": PASSWORD})
        cookie = response.headers["set-cookie"].lower()
        self.assertIn(SESSION_COOKIE, cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertTrue(self.client.get("/api/session").json()["authenticated"])
        self.assertEqual(self.client.post("/api/logout").status_code, 403)
        self.assertTrue(self.client.get("/api/session").json()["authenticated"])
        self.client.post("/api/logout", headers=WEB)
        self.assertFalse(self.client.get("/api/session").json()["authenticated"])

    def test_cookie_writes_need_client_header(self) -> None:
        self.login()
        self.assertEqual(self.client.post("/api/tasks", json={"title": "x"}).status_code, 403)
        self.assertEqual(self.client.post("/api/tasks", json={"title": "x"}, headers=WEB).status_code, 201)

    def test_quick_capture_goes_to_inbox_and_is_idempotent(self) -> None:
        self.login()
        payload = {"id": "0123456789abcdef0123456789abcdef", "title": "Rappeler Paul"}
        first = self.client.post("/api/tasks", json=payload, headers=WEB)
        again = self.client.post("/api/tasks", json=payload, headers=WEB)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.json()["id"], first.json()["id"])
        self.assertEqual(first.json()["project_name"], "Boîte de réception")
        tasks = self.client.get("/api/tasks").json()
        self.assertEqual([t["title"] for t in tasks], ["Rappeler Paul"])
        projects = self.client.get("/api/projects").json()
        self.assertEqual([p["inbox"] for p in projects], [True])

    def test_reading_projects_creates_nothing(self) -> None:
        self.login()
        self.assertEqual(self.client.get("/api/projects").json(), [])

    def test_forged_cookie_is_401_not_500(self) -> None:
        self.client.cookies.set(SESSION_COOKIE, "eyJpYXQiOjF9.forged")
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.assertFalse(self.client.get("/api/session").json()["authenticated"])

    def test_extension_creates_task_from_mail_with_token(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json={"title": "Re: budget", "mail_message_id": "<xyz@example.org>"},
            headers=self.bearer(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["mail_message_id"], "<xyz@example.org>")

    def test_update_status(self) -> None:
        created = self.client.post("/api/tasks", json={"title": "Faire"}, headers=self.bearer()).json()
        done = self.client.patch(f"/api/tasks/{created['id']}", json={"status": "done"}, headers=self.bearer())
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["status"], "done")
        self.assertEqual(self.client.get("/api/tasks", headers=self.bearer()).json(), [])
        all_tasks = self.client.get("/api/tasks?status=all", headers=self.bearer()).json()
        self.assertEqual(len(all_tasks), 1)

    def test_validation_errors(self) -> None:
        h = self.bearer()
        self.assertEqual(self.client.post("/api/tasks", json={"title": ""}, headers=h).status_code, 422)
        self.assertEqual(self.client.post("/api/tasks", json={"title": "x", "id": "../x"}, headers=h).status_code, 422)
        self.assertEqual(self.client.post("/api/tasks", json={"title": "x", "extra": 1}, headers=h).status_code, 422)
        unknown_project = {"title": "x", "project_id": "f" * 32}
        self.assertEqual(self.client.post("/api/tasks", json=unknown_project, headers=h).status_code, 404)
        self.assertEqual(self.client.patch("/api/tasks/" + "f" * 32, json={"status": "done"}, headers=h).status_code, 404)
        self.assertEqual(self.client.patch("/api/tasks/" + "f" * 32, json={}, headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/nope", headers=h).status_code, 404)

    def test_security_headers(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
