"""Authentication primitives: password hashing, signed session cookies, API tokens.

Standard library only, so the security-sensitive code stays small and auditable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field

# scrypt parameters (n=2**15, r=8, p=1: ~32 MiB, ~50-100 ms per hash).
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    """Return a self-describing scrypt hash: ``scrypt$n$r$p$salt$hash``."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64d(salt), n=int(n), r=int(r), p=int(p),
            maxmem=_SCRYPT_MAXMEM, dklen=32,
        )
        return hmac.compare_digest(digest, _b64d(expected))
    except (ValueError, TypeError):
        return False


def is_password_hash(encoded: str) -> bool:
    """True when ``encoded`` has the shape produced by :func:`hash_password`."""
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        int(parts[1]), int(parts[2]), int(parts[3])
        return len(_b64d(parts[4])) == 16 and len(_b64d(parts[5])) == 32
    except (ValueError, TypeError):
        return False


def new_api_token() -> tuple[str, str]:
    """Return ``(token, token_hash)``. Only the hash is stored in the server config."""
    token = "pige_" + secrets.token_urlsafe(32)
    return token, hash_api_token(token)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_api_token(token: str, allowed_hashes: frozenset[str]) -> bool:
    candidate = hash_api_token(token).encode("ascii")
    # Compare against every hash so timing does not reveal which one matched.
    matched = False
    for allowed in allowed_hashes:
        if hmac.compare_digest(candidate, allowed.encode("ascii", "replace")):
            matched = True
    return matched


class SessionSigner:
    """Signed, expiring session cookie values (HMAC-SHA256).

    ``bound_to`` (the password hash) is mixed into the key, so changing the
    password invalidates every session. ``not_before`` (a Unix time) rejects
    sessions issued earlier: raise it to log out every device at once.
    """

    def __init__(
        self, secret: str, max_age_seconds: int, *, bound_to: str = "", not_before: int = 0
    ) -> None:
        if len(secret) < 32:
            raise ValueError("Session secret must be at least 32 characters")
        self._key = hashlib.sha256(secret.encode("utf-8") + b"\0" + bound_to.encode("utf-8")).digest()
        self.max_age_seconds = max_age_seconds
        self.not_before = not_before

    def _sign(self, payload: str) -> str:
        return _b64e(hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest())

    def issue(self, now: float | None = None) -> str:
        issued = int(now if now is not None else time.time())
        body = _b64e(json.dumps({"iat": issued, "nonce": secrets.token_hex(8)}).encode("utf-8"))
        return f"{body}.{self._sign(body)}"

    def is_valid(self, value: str | None, now: float | None = None) -> bool:
        if not value or value.count(".") != 1:
            return False
        body, signature = value.split(".")
        try:
            if not hmac.compare_digest(signature.encode("ascii"), self._sign(body).encode("ascii")):
                return False
            payload = json.loads(_b64d(body))
            issued = int(payload["iat"])
        except (ValueError, KeyError, TypeError, UnicodeError):
            return False
        current = now if now is not None else time.time()
        return issued >= self.not_before and 0 <= current - issued <= self.max_age_seconds


@dataclass
class LoginThrottle:
    """Limits failed logins: ``max_failures`` per client and ``max_global_failures``
    overall within ``window_seconds`` (the global cap resists address rotation).

    Use :meth:`acquire` before checking a password: it atomically refuses when the
    limit is reached and otherwise counts the attempt as a failure, which
    :meth:`succeeded` cancels. Concurrent attempts therefore cannot exceed the limit.
    """

    max_failures: int = 5
    max_global_failures: int = 50
    window_seconds: int = 15 * 60
    max_clients: int = 10_000
    _failures: dict[str, list[float]] = field(default_factory=dict)
    _global: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self, client: str, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        with self._lock:
            self._global = [t for t in self._global if current - t < self.window_seconds]
            if len(self._global) >= self.max_global_failures:
                return False
            if len(self._recent(client, current)) >= self.max_failures:
                return False
            if len(self._failures) >= self.max_clients:
                self._prune(current)
            self._failures.setdefault(client, []).append(current)
            self._global.append(current)
            return True

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)

    def _prune(self, now: float) -> None:
        for key in list(self._failures):
            self._recent(key, now)

    def _recent(self, client: str, now: float) -> list[float]:
        kept = [t for t in self._failures.get(client, []) if now - t < self.window_seconds]
        if kept:
            self._failures[client] = kept
        else:
            self._failures.pop(client, None)
        return kept
