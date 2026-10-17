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

    ``wal`` is off by default: WAL keeps side files (-wal, -shm) that cloud
    sync tools copy inconsistently. The server, whose data never sits in a
    synced folder, may turn it on.
    """
    conn = sqlite3.connect(str(path), timeout=10.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def _statements(script: str) -> list[str]:
    """Split a migration script into statements (trigger bodies stay whole)."""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError(f"incomplete SQL statement in migration: {buffer.strip()[:80]}")
    return statements


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each in its own transaction. Returns the final version.

    Safe if two processes open a fresh database at once: the version is
    re-read after taking the write lock, so a migration never runs twice.
    """
    while True:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise SchemaTooNewError(
                    f"database schema version {current} is newer than this P.IGE ({SCHEMA_VERSION})"
                )
            if current == SCHEMA_VERSION:
                conn.execute("COMMIT")
                return SCHEMA_VERSION
            for statement in _statements(MIGRATIONS[current]):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {current + 1}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
