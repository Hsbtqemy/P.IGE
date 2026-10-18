"""Opening the model database and applying migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pige.model.schema import MIGRATIONS, SCHEMA_VERSION

DB_FILE_NAME = "pige.sqlite3"


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer P.IGE than this one."""


def connect(path: Path | str, *, wal: bool = False) -> sqlite3.Connection:
    """Open (and create or migrate) the model database.

    A connection belongs to one thread: use one per thread (see
    :class:`pige.model.store.ModelStore`, which does it for you).

    ``wal`` is off by default: WAL keeps side files (-wal, -shm) that cloud
    sync tools copy inconsistently. The server, whose data never sits in a
    synced folder, may turn it on.
    """
    conn = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        if wal:
            conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn)
        conn.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        conn.close()
        raise
    return conn


def _statements(script: str) -> list[str]:
    """Split a migration script into statements (trigger bodies stay whole)."""
    statements: list[str] = []
    buffer = ""
    for char in script:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    leftover = "\n".join(
        line for line in buffer.splitlines() if line.strip() and not line.strip().startswith("--")
    )
    if leftover.strip():
        raise ValueError(f"incomplete SQL statement in migration: {leftover.strip()[:80]}")
    return statements


def _version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each in its own transaction. Returns the final version.

    * Nothing is locked when the schema is already current (read-only copies open fine).
    * Safe if two processes open a fresh database at once: the version is re-read
      after taking the write lock, so a migration never runs twice.
    * Foreign keys are off while migrating (so a table can be rebuilt without
      cascading deletes) and checked before each commit.
    """
    current = _version(conn)
    if current > SCHEMA_VERSION:
        raise SchemaTooNewError(f"database schema version {current} is newer than this P.IGE ({SCHEMA_VERSION})")
    if current == SCHEMA_VERSION:
        return SCHEMA_VERSION
    conn.execute("PRAGMA foreign_keys = OFF")  # only effective outside a transaction
    while True:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _version(conn)
            if current > SCHEMA_VERSION:
                raise SchemaTooNewError(
                    f"database schema version {current} is newer than this P.IGE ({SCHEMA_VERSION})"
                )
            if current == SCHEMA_VERSION:
                conn.execute("COMMIT")
                return SCHEMA_VERSION
            for statement in _statements(MIGRATIONS[current]):
                conn.execute(statement)
            problems = conn.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise RuntimeError(f"migration {current + 1} broke foreign keys: {[tuple(p) for p in problems[:5]]}")
            conn.execute(f"PRAGMA user_version = {current + 1}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
