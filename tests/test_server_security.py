"""Signed-in devices and passkey sign-in, with a software authenticator."""

from __future__ import annotations

import base64
import hashlib
import json
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("webauthn")

import cbor2  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pige.server.app import CSRF_HEADER, SESSION_COOKIE, create_app  # noqa: E402
from pige.server.auth import SessionSigner, hash_password, new_api_token  # noqa: E402
from pige.server.config import ConfigError, Settings  # noqa: E402
from pige.server.security import Challenges, device_label  # noqa: E402

PASSWORD = "correct horse battery staple"
_HASH = hash_password(PASSWORD)
_TOKEN, _TOKEN_HASH = new_api_token()
ORIGIN = "https://pige.example.org"
WEB = {CSRF_HEADER: "web"}
FIREFOX_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:131.0) Gecko/20100101 Firefox/131.0"
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Mobile/15E148 Safari/604.1"
)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def settings(tmp_path, origin: str | None = ORIGIN) -> Settings:
    return Settings(
        data_dir=tmp_path, password_hash=_HASH, session_secret="s" * 48,
        api_token_hashes=frozenset({_TOKEN_HASH}), cookie_secure=False, public_origin=origin, background_jobs=False,
    )


@pytest.fixture()
def app(tmp_path):
    return create_app(settings(tmp_path))


def browser(app, agent: str = FIREFOX_MAC) -> TestClient:
    c = TestClient(app, base_url="https://pige.example.org")
    c.headers.update({"user-agent": agent})
    return c


def signed_in(app, agent: str = FIREFOX_MAC) -> TestClient:
    c = browser(app, agent)
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return c


class Authenticator:
    """A passkey on a pretend device: P-256 key, user verification always done."""

    def __init__(self, rp_id: str = "pige.example.org") -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.rp_hash = hashlib.sha256(rp_id.encode()).digest()
        self.count = 0

    def _cose(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    @staticmethod
    def _client_data(kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def create(self, options: dict, origin: str = ORIGIN) -> dict:
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self._cose()
        auth_data = self.rp_hash + bytes([0x45]) + (0).to_bytes(4, "big") + attested  # UP | UV | AT
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64u(self.credential_id), "rawId": b64u(self.credential_id), "type": "public-key",
            "response": {"clientDataJSON": b64u(client_data), "attestationObject": b64u(attestation),
                         "transports": ["internal", "hybrid", "bogus"]},
            "clientExtensionResults": {},
        }

    def get(self, options: dict, origin: str = ORIGIN, verified: bool = True) -> dict:
        self.count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        flags = 0x05 if verified else 0x01  # UP | UV
        auth_data = self.rp_hash + bytes([flags]) + self.count.to_bytes(4, "big")
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64u(self.credential_id), "rawId": b64u(self.credential_id), "type": "public-key",
            "response": {"clientDataJSON": b64u(client_data), "authenticatorData": b64u(auth_data),
                         "signature": b64u(signature), "userHandle": None},
            "clientExtensionResults": {},
        }


def register(c: TestClient, device: Authenticator, name: str = "MacBook") -> dict:
    options = c.post("/api/passkeys/register/options", headers=WEB).json()
    response = c.post("/api/passkeys/register/verify", json={"credential": device.create(options), "name": name},
                      headers=WEB)
    assert response.status_code == 201, response.text
    return response.json()


def passkey_login(c: TestClient, device: Authenticator, **kwargs):
    options = c.post("/api/passkeys/login/options").json()
    return c.post("/api/passkeys/login/verify", json={"credential": device.get(options, **kwargs)})


# ---------------------------------------------------------------- sessions


def test_each_sign_in_is_a_device_that_can_be_ended(app):
    mac = signed_in(app)
    phone = signed_in(app, SAFARI_IPHONE)
    listed = mac.get("/api/devices").json()["sessions"]
    assert {s["label"] for s in listed} == {"Firefox · macOS", "Safari · iPhone"}
    assert [s["current"] for s in listed if s["label"] == "Firefox · macOS"] == [True]
    other = next(s["id"] for s in listed if not s["current"])
    assert mac.delete(f"/api/sessions/{other}", headers=WEB).status_code == 204
    assert phone.get("/api/v2/tree").status_code == 401  # the lost phone is signed out
    assert phone.get("/api/session").json() == {"authenticated": False}
    assert mac.get("/api/v2/tree").status_code == 200
    mine = next(s["id"] for s in mac.get("/api/devices").json()["sessions"] if s["current"])
    assert mac.delete(f"/api/sessions/{mine}", headers=WEB).status_code == 409


def test_end_other_sessions_and_logout_really_end_the_session(app):
    mac, phone, tablet = signed_in(app), signed_in(app, SAFARI_IPHONE), signed_in(app)
    assert mac.post("/api/sessions/end-others", headers=WEB).json() == {"ended": 2}
    assert phone.get("/api/v2/tree").status_code == 401 and tablet.get("/api/v2/tree").status_code == 401
    cookie = mac.cookies.get(SESSION_COOKIE)
    assert mac.post("/api/logout", headers=WEB).status_code == 200
    replay = browser(app)
    replay.cookies.set(SESSION_COOKIE, cookie)  # a copied cookie is useless after logout
    assert replay.get("/api/v2/tree").status_code == 401


def test_cookies_without_a_session_are_refused(app, tmp_path):
    old = SessionSigner("s" * 48, 86400, bound_to=_HASH).issue()  # signed, but no session behind it
    c = browser(app)
    c.cookies.set(SESSION_COOKIE, old)
    assert c.get("/api/session").json() == {"authenticated": False}
    assert c.get("/api/v2/tree").status_code == 401


def test_security_needs_the_web_app_not_a_token(app):
    token = TestClient(app, headers={"Authorization": f"Bearer {_TOKEN}"})
    assert token.get("/api/v2/tree").status_code == 200
    assert token.get("/api/devices").status_code == 403
    assert token.post("/api/passkeys/register/options").status_code == 403
    mac = signed_in(app)
    assert mac.post("/api/passkeys/register/options").status_code == 403  # no client header (CSRF)
    assert browser(app).get("/api/devices").status_code == 401


# ---------------------------------------------------------------- passkeys


def test_passkey_registration_and_sign_in(app):
    mac = signed_in(app)
    assert browser(app).get("/api/passkeys/status").json() == {"configured": True, "registered": False}
    device = Authenticator()
    added = register(mac, device)
    assert added["name"] == "MacBook"
    assert browser(app).get("/api/passkeys/status").json() == {"configured": True, "registered": True}
    listed = mac.get("/api/devices").json()["passkeys"]
    assert [p["name"] for p in listed] == ["MacBook"] and listed[0]["last_used"] is None

    phone = browser(app, SAFARI_IPHONE)
    assert passkey_login(phone, device).status_code == 200
    assert phone.get("/api/v2/tree").status_code == 200
    sessions = mac.get("/api/devices").json()["sessions"]
    assert {(s["label"], s["method"]) for s in sessions} == {("Firefox · macOS", "password"), ("Safari · iPhone", "passkey")}
    assert mac.get("/api/devices").json()["passkeys"][0]["last_used"] is not None
    # the same passkey cannot be registered twice
    options = mac.post("/api/passkeys/register/options", headers=WEB).json()
    assert {c["id"] for c in options["excludeCredentials"]} == {added["id"]}


def test_passkey_sign_in_is_refused_when_anything_is_off(app):
    mac = signed_in(app)
    device = Authenticator()
    register(mac, device)
    assert passkey_login(browser(app), Authenticator()).status_code == 401  # unknown key
    assert passkey_login(browser(app), device, verified=False).status_code == 401  # no fingerprint / PIN
    assert passkey_login(browser(app), device, origin="https://evil.example").status_code == 401
    # a challenge is single use: replaying a good answer fails
    c = browser(app)
    options = c.post("/api/passkeys/login/options").json()
    answer = device.get(options)
    assert c.post("/api/passkeys/login/verify", json={"credential": answer}).status_code == 200
    c.cookies.clear()
    assert c.post("/api/passkeys/login/verify", json={"credential": answer}).status_code == 400
    # without the challenge cookie (another browser) nothing works
    other = browser(app)
    options = browser(app).post("/api/passkeys/login/options").json()
    assert other.post("/api/passkeys/login/verify", json={"credential": device.get(options)}).status_code == 400


def test_registration_needs_a_fresh_challenge_and_the_right_site(app):
    mac = signed_in(app)
    options = mac.post("/api/passkeys/register/options", headers=WEB).json()
    wrong_site = Authenticator().create(options, origin="https://evil.example")
    assert mac.post("/api/passkeys/register/verify", json={"credential": wrong_site}, headers=WEB).status_code == 400
    # the challenge was used up by the failed attempt
    again = Authenticator().create(options)
    assert mac.post("/api/passkeys/register/verify", json={"credential": again}, headers=WEB).status_code == 400


def test_removing_a_passkey_ends_its_sessions(app):
    mac = signed_in(app)
    device = Authenticator()
    added = register(mac, device, "iPhone")
    phone = browser(app, SAFARI_IPHONE)
    assert passkey_login(phone, device).status_code == 200
    # the phone cannot remove the key it is signed in with
    assert phone.delete(f"/api/passkeys/{added['id']}", headers=WEB).status_code == 409
    assert mac.patch(f"/api/passkeys/{added['id']}", json={"name": "iPhone de Hugo"}, headers=WEB).status_code == 200
    assert mac.delete(f"/api/passkeys/{added['id']}", headers=WEB).status_code == 204
    assert phone.get("/api/v2/tree").status_code == 401
    assert passkey_login(browser(app), device).status_code == 401


def test_passkeys_need_the_public_origin(tmp_path):
    app = create_app(settings(tmp_path, origin=None))
    mac = signed_in(app)
    assert browser(app).get("/api/passkeys/status").json() == {"configured": False, "registered": False}
    assert mac.post("/api/passkeys/register/options", headers=WEB).status_code == 404
    assert browser(app).post("/api/passkeys/login/options").status_code == 404


def test_public_origin_setting():
    base = {"PIGE_DATA_DIR": "/tmp/x", "PIGE_PASSWORD_HASH": _HASH, "PIGE_SESSION_SECRET": "s" * 48}
    s = Settings.from_env({**base, "PIGE_PUBLIC_ORIGIN": "https://Pige.Example.org/"})
    assert s.public_origin == "https://pige.example.org" and s.passkey_rp_id == "pige.example.org"
    assert Settings.from_env({**base, "PIGE_PUBLIC_ORIGIN": "http://localhost:8765"}).passkey_rp_id == "localhost"
    assert Settings.from_env(base).passkey_rp_id is None
    assert Settings.from_env({**base, "PIGE_PUBLIC_ORIGIN": "https://pige.example.org:443"}).public_origin == (
        "https://pige.example.org"
    )
    assert Settings.from_env({**base, "PIGE_PUBLIC_ORIGIN": "https://pige.example.org:8443"}).public_origin == (
        "https://pige.example.org:8443"
    )
    for bad in ("http://pige.example.org", "pige.example.org", "https://pige.example.org/path", "https://-.",
                "https://a..b", "https://localhost", "https://user@pige.example.org"):
        with pytest.raises(ConfigError):
            Settings.from_env({**base, "PIGE_PUBLIC_ORIGIN": bad})


# ---------------------------------------------------------------- helpers


def test_device_labels():
    assert device_label(FIREFOX_MAC) == "Firefox · macOS"
    assert device_label(SAFARI_IPHONE) == "Safari · iPhone"
    assert device_label("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36") == "Chrome · Android"
    assert device_label("") == "Navigateur"


def test_flooding_sign_in_challenges_does_not_block_the_owner(app):
    mac = signed_in(app)
    device = Authenticator()
    options = mac.post("/api/passkeys/register/options", headers=WEB).json()
    flood = browser(app)
    for _ in range(1200):
        flood.post("/api/passkeys/login/options")
    answer = device.create(options)
    response = mac.post("/api/passkeys/register/verify", json={"credential": answer, "name": "Mac"}, headers=WEB)
    assert response.status_code == 201  # registration challenges are kept apart


def test_odd_registration_input_is_refused_cleanly(app):
    mac = signed_in(app)
    device = Authenticator()
    options = mac.post("/api/passkeys/register/options", headers=WEB).json()
    credential = device.create(options)
    credential["response"]["transports"] = 5
    assert mac.post("/api/passkeys/register/verify", json={"credential": credential}, headers=WEB).status_code == 201
    assert mac.post("/api/passkeys/register/verify", json={"credential": "x"}, headers=WEB).status_code == 422


def test_signing_in_again_replaces_the_session(app):
    mac = signed_in(app)
    for _ in range(3):
        assert mac.post("/api/login", json={"password": PASSWORD}).status_code == 200
    assert len(mac.get("/api/devices").json()["sessions"]) == 1


def test_challenges_are_single_use_and_expire():
    c = Challenges()
    c.put("a", b"x", now=0)
    assert c.take("a", now=10) == b"x" and c.take("a", now=10) is None
    c.put("b", b"y", now=0)
    assert c.take("b", now=301) is None
    small = Challenges(per_owner=2)
    for i in range(5):
        small.put(f"k{i}", b"z", owner="flood", now=0)
    small.put("mine", b"m", owner="me", now=0)
    assert small.take("k0", now=1) is None and small.take("k4", now=1) == b"z" and small.take("mine", now=1) == b"m"
