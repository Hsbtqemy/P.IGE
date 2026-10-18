"""Signed-in devices and passkeys, kept in ``auth.sqlite3`` next to the data.

* Every sign-in (password or passkey) opens a **session** row; the cookie carries its
  id, signed. A session can be ended from another device (lost phone) and the list
  shows where P.IGE is open. Only a hash of the id is stored.
* **Passkeys** (WebAuthn) replace the password on devices that support them: the
  private key never leaves the device; the server keeps the public key.

Nothing here is personal data of third parties; still, the file stays in the data
directory (mode of the service user), never in the repository.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

AUTH_FILE_NAME = "auth.sqlite3"
LAST_SEEN_EVERY = 300  # seconds: "last seen" is refreshed at most this often
CHALLENGE_SECONDS = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id_hash     TEXT PRIMARY KEY,
    created_at  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    method      TEXT NOT NULL CHECK (method IN ('password', 'passkey')),
    label       TEXT NOT NULL DEFAULT '',
    passkey_id  TEXT
);
CREATE TABLE IF NOT EXISTS passkeys (
    id          TEXT PRIMARY KEY,
    public_key  BLOB NOT NULL,
    sign_count  INTEGER NOT NULL DEFAULT 0,
    name        TEXT NOT NULL,
    transports  TEXT NOT NULL DEFAULT '[]',
    backed_up   INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    last_used   INTEGER
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Session:
    id_hash: str
    created_at: int
    last_seen: int
    expires_at: int
    method: str
    label: str
    passkey_id: str | None


@dataclass(frozen=True)
class Passkey:
    id: str
    public_key: bytes
    sign_count: int
    name: str
    transports: list[str]
    backed_up: bool
    created_at: int
    last_used: int | None


class AuthStore:
    """Sessions and passkeys. Thread-safe: one short connection per call, writes serialised."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A short connection: committed (or rolled back) and always closed."""
        with closing(sqlite3.connect(str(self.path), timeout=10.0)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def _write(self, sql: str, params: tuple[object, ...] = ()) -> int:
        with self._lock, self._connect() as conn:
            return conn.execute(sql, params).rowcount

    # ------------------------------------------------------------ sessions

    def open_session(
        self, method: str, label: str, lifetime: int, *, passkey_id: str | None = None, now: int | None = None
    ) -> str:
        """Create a session; returns its id (to sign into the cookie), stored only hashed."""
        current = int(now if now is not None else time.time())
        session_id = secrets.token_urlsafe(32)
        self._write(
            "INSERT INTO sessions(id_hash, created_at, last_seen, expires_at, method, label, passkey_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_hash(session_id), current, current, current + lifetime, method, label[:120], passkey_id),
        )
        return session_id

    def check_session(self, session_id: str, *, now: int | None = None) -> Session | None:
        """The live session with this id (refreshing "last seen"), or None if ended or expired."""
        current = int(now if now is not None else time.time())
        id_hash = _hash(session_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id_hash = ?", (id_hash,)).fetchone()
        if row is None or row["expires_at"] <= current:
            return None
        if current - row["last_seen"] >= LAST_SEEN_EVERY:
            self._write("UPDATE sessions SET last_seen = ? WHERE id_hash = ?", (current, id_hash))
        return Session(**dict(row))

    def sessions(self, *, now: int | None = None) -> list[Session]:
        current = int(now if now is not None else time.time())
        self._write("DELETE FROM sessions WHERE expires_at <= ?", (current,))
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY last_seen DESC").fetchall()
        return [Session(**dict(r)) for r in rows]

    def end_session(self, id_hash: str) -> bool:
        return self._write("DELETE FROM sessions WHERE id_hash = ?", (id_hash,)) > 0

    def end_session_by_id(self, session_id: str) -> None:
        self._write("DELETE FROM sessions WHERE id_hash = ?", (_hash(session_id),))

    def end_other_sessions(self, keep_session_id: str) -> int:
        return self._write("DELETE FROM sessions WHERE id_hash <> ?", (_hash(keep_session_id),))

    @staticmethod
    def hash_of(session_id: str) -> str:
        return _hash(session_id)

    # ------------------------------------------------------------ passkeys

    def user_handle(self) -> bytes:
        """The single user's WebAuthn handle: random, stable, never shown."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'user_handle'").fetchone()
            if row is not None:
                return bytes.fromhex(row["value"])
            handle = secrets.token_bytes(32)
            conn.execute("INSERT INTO meta(key, value) VALUES ('user_handle', ?)", (handle.hex(),))
            return handle

    def passkeys(self) -> list[Passkey]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM passkeys ORDER BY created_at").fetchall()
        return [self._passkey(r) for r in rows]

    def passkey(self, credential_id: str) -> Passkey | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM passkeys WHERE id = ?", (credential_id,)).fetchone()
        return self._passkey(row) if row is not None else None

    @staticmethod
    def _passkey(row: sqlite3.Row) -> Passkey:
        data = dict(row)
        data["transports"] = json.loads(data["transports"] or "[]")
        data["backed_up"] = bool(data["backed_up"])
        return Passkey(**data)

    def add_passkey(
        self, credential_id: str, public_key: bytes, sign_count: int, name: str, transports: list[str],
        backed_up: bool, *, now: int | None = None,
    ) -> bool:
        """Store a passkey; False if this credential is already registered."""
        current = int(now if now is not None else time.time())
        try:
            self._write(
                "INSERT INTO passkeys(id, public_key, sign_count, name, transports, backed_up, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (credential_id, public_key, sign_count, name[:80], json.dumps(transports[:10]), int(backed_up),
                 current),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def passkey_used(self, credential_id: str, sign_count: int, *, now: int | None = None) -> None:
        current = int(now if now is not None else time.time())
        self._write(
            # max(): two sign-ins at once must not move the counter backwards.
            "UPDATE passkeys SET sign_count = max(sign_count, ?), last_used = ? WHERE id = ?",
            (sign_count, current, credential_id),
        )

    def rename_passkey(self, credential_id: str, name: str) -> bool:
        return self._write("UPDATE passkeys SET name = ? WHERE id = ?", (name[:80], credential_id)) > 0

    def remove_passkey(self, credential_id: str) -> bool:
        """Remove a passkey and end the sessions it opened."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE passkey_id = ?", (credential_id,))
            return conn.execute("DELETE FROM passkeys WHERE id = ?", (credential_id,)).rowcount > 0


class Challenges:
    """WebAuthn challenges waiting for their answer: single use, short-lived, in memory.

    Each owner (a session, or a client address for sign-in) holds at most ``per_owner``
    pending challenges: someone asking for many only pushes out their own.
    """

    def __init__(self, max_items: int = 1000, per_owner: int = 5) -> None:
        self._items: OrderedDict[str, tuple[bytes, float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_items
        self._per_owner = per_owner

    def put(self, key: str, challenge: bytes, owner: str = "", now: float | None = None) -> None:
        current = now if now is not None else time.time()
        with self._lock:
            while self._items:  # oldest first: drop the expired ones at the front
                first = next(iter(self._items.values()))
                if first[1] > current:
                    break
                self._items.popitem(last=False)
            mine = [k for k, v in self._items.items() if v[2] == owner]
            for old in mine[: max(0, len(mine) - self._per_owner + 1)]:
                del self._items[old]
            if len(self._items) >= self._max:
                self._items.popitem(last=False)
            self._items[key] = (challenge, current + CHALLENGE_SECONDS, owner)

    def take(self, key: str, now: float | None = None) -> bytes | None:
        current = now if now is not None else time.time()
        with self._lock:
            item = self._items.pop(key, None)
        if item is None or item[1] <= current:
            return None
        return item[0]


def device_label(user_agent: str) -> str:
    """« Firefox · macOS », « Safari · iPhone »: enough to recognise a device in a list."""
    ua = user_agent or ""
    if "Thunderbird" in ua:
        browser = "Thunderbird"
    elif re.search(r"Edg/", ua):
        browser = "Edge"
    elif re.search(r"(Firefox|FxiOS)/", ua):
        browser = "Firefox"
    elif re.search(r"(Chrome|CriOS)/", ua):
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "Navigateur"
    if "iPhone" in ua:
        system = "iPhone"
    elif "iPad" in ua:
        system = "iPad"
    elif "Android" in ua:
        system = "Android"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        system = "macOS"
    elif "Windows" in ua:
        system = "Windows"
    elif "Linux" in ua:
        system = "Linux"
    else:
        system = ""
    return f"{browser} · {system}" if system else browser
