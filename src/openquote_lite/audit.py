"""Hash-chained audit log.

Each entry stores the SHA-256 hash of the previous entry, so any later edit,
deletion or reordering inside the chain is detected by ``verify``.

Limits, stated honestly: someone with write access to the database file can
rebuild the whole chain, and removing entries from the end leaves a valid
shorter chain. Export the current head hash regularly (``openquote-lite audit
head``) to a place the database cannot reach, e.g. a dated note in the project
records; comparing it later detects both cases.

Audit entries do not contain raw names or contact details by design.
However, request ids can be linked to stored requests or retained by clients, so
this audit trail is pseudonymous and may still be personal data under GDPR.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, TextIO

GENESIS = "0" * 64


def _canonical(entry: dict[str, Any]) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _entry_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + b"\n" + _canonical(entry)).hexdigest()


def append(
    conn: sqlite3.Connection,
    *,
    ts: str,
    event: str,
    actor: str,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    """Append one entry inside the caller's transaction. Returns its hash."""
    row = conn.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    seq = (row["seq"] + 1) if row else 1
    prev_hash = row["hash"] if row else GENESIS
    entry = {
        "seq": seq,
        "ts": ts,
        "event": event,
        "request_id": request_id,
        "actor": actor,
        "details": details or {},
    }
    digest = _entry_hash(prev_hash, entry)
    conn.execute(
        "INSERT INTO audit_log (seq, ts, event, request_id, actor, details, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (seq, ts, event, request_id, actor, json.dumps(entry["details"], sort_keys=True), prev_hash, digest),
    )
    return digest


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    entries: int
    head: str
    first_bad_seq: int | None = None
    reason: str | None = None


def _rows(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT seq, ts, event, request_id, actor, details, prev_hash, hash FROM audit_log ORDER BY seq"
    )


def verify(conn: sqlite3.Connection) -> VerifyResult:
    prev_hash = GENESIS
    expected_seq = 1
    count = 0
    for row in _rows(conn):
        if row["seq"] != expected_seq:
            return VerifyResult(False, count, prev_hash, row["seq"], "sequence gap")
        if row["prev_hash"] != prev_hash:
            return VerifyResult(False, count, prev_hash, row["seq"], "broken link to previous entry")
        entry = {
            "seq": row["seq"],
            "ts": row["ts"],
            "event": row["event"],
            "request_id": row["request_id"],
            "actor": row["actor"],
            "details": json.loads(row["details"]),
        }
        if _entry_hash(prev_hash, entry) != row["hash"]:
            return VerifyResult(False, count, prev_hash, row["seq"], "entry content changed")
        prev_hash = row["hash"]
        expected_seq += 1
        count += 1
    return VerifyResult(True, count, prev_hash)


def head(conn: sqlite3.Connection) -> tuple[int, str]:
    row = conn.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    return (row["seq"], row["hash"]) if row else (0, GENESIS)


def export_jsonl(conn: sqlite3.Connection, out: TextIO) -> int:
    count = 0
    for row in _rows(conn):
        out.write(
            json.dumps(
                {
                    "seq": row["seq"],
                    "ts": row["ts"],
                    "event": row["event"],
                    "request_id": row["request_id"],
                    "actor": row["actor"],
                    "details": json.loads(row["details"]),
                    "prev_hash": row["prev_hash"],
                    "hash": row["hash"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        count += 1
    return count
