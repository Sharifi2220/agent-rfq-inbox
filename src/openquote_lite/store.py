"""SQLite storage: requests, idempotency keys, rate-limit events, counters,
settings and the hash-chained audit log.

Every public operation runs in its own short ``BEGIN IMMEDIATE`` transaction,
so the HTTP server, the MCP server and the CLI can share one database file.
Keep the data directory on a local disk: SQLite's WAL mode does not work on
network or cloud-synchronised folders.
"""

from __future__ import annotations

import math
import os
import stat
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = "1"

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id             TEXT PRIMARY KEY,
    received_at    TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    status         TEXT NOT NULL,
    decline_reason TEXT,
    channel        TEXT NOT NULL,
    service_id     TEXT NOT NULL,
    postal_code    TEXT NOT NULL,
    urgency        TEXT NOT NULL,
    language       TEXT,
    flags          TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    contact_hash   TEXT NOT NULL,
    payload        TEXT,
    erased_at      TEXT
);
CREATE INDEX IF NOT EXISTS requests_received ON requests (received_at);
CREATE INDEX IF NOT EXISTS requests_content ON requests (content_hash, received_at);
CREATE TABLE IF NOT EXISTS idempotency (
    key        TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    body_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_events (
    bucket TEXT NOT NULL,
    ts     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_events_bucket ON rate_events (bucket, ts);
CREATE TABLE IF NOT EXISTS counters (
    day  TEXT NOT NULL,
    code TEXT NOT NULL,
    n    INTEGER NOT NULL,
    PRIMARY KEY (day, code)
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq        INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,
    request_id TEXT,
    actor      TEXT NOT NULL,
    details    TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            # A normal umask can otherwise leave the SQLite database world-readable.
            if stat.S_IMODE(self.path.parent.stat().st_mode) & 0o077:
                raise PermissionError(f"data directory must be private (chmod 700): {self.path.parent}")
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        if os.name == "posix" and stat.S_IMODE(self.path.stat().st_mode) & 0o077:
            raise PermissionError(f"database file must be private (chmod 600): {self.path}")
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_DDL)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,)
            )
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('accepting_requests', '1')")
        finally:
            conn.close()

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 10000")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN DEFERRED")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


# -- settings ---------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# -- rate limiting ------------------------------------------------------------

def rate_check(conn: sqlite3.Connection, bucket: str, window_s: float, limit: int, now: float) -> int | None:
    """Return seconds to wait if ``bucket`` already holds ``limit`` events in the window."""
    conn.execute("DELETE FROM rate_events WHERE bucket = ? AND ts < ?", (bucket, now - window_s))
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(ts) AS oldest FROM rate_events WHERE bucket = ? AND ts >= ?",
        (bucket, now - window_s),
    ).fetchone()
    if row["n"] >= limit:
        return max(1, math.ceil(row["oldest"] + window_s - now))
    return None


def rate_record(conn: sqlite3.Connection, bucket: str, now: float) -> None:
    conn.execute("INSERT INTO rate_events (bucket, ts) VALUES (?, ?)", (bucket, now))


def count_rejection(conn: sqlite3.Connection, day: str, code: str) -> None:
    conn.execute(
        "INSERT INTO counters (day, code, n) VALUES (?, ?, 1) "
        "ON CONFLICT(day, code) DO UPDATE SET n = n + 1",
        (day, code),
    )
