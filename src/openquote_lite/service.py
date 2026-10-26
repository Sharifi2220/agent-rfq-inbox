"""Core service: accept quote requests, answer status lookups, run the inbox.

The service is transport-independent. The HTTP API and the MCP binding both
call :meth:`QuoteService.submit` with the raw JSON bytes, so every channel
passes exactly the same checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import PROTOCOL_VERSION, audit
from .errors import OpenQuoteError
from .profile import API_PREFIX, Profile
from .store import Store, count_rejection, get_setting, rate_check, rate_record, set_setting
from .validation import validate_request

REQUEST_ID = re.compile(r"^oqr_[A-Za-z0-9_-]{24}$")

INTERNAL_STATUSES = ("new", "in_review", "follow_up_planned", "declined", "spam", "closed")
TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"in_review", "follow_up_planned", "declined", "spam"}),
    "in_review": frozenset({"follow_up_planned", "declined", "spam", "closed"}),
    "follow_up_planned": frozenset({"closed", "declined"}),
    "declined": frozenset({"closed"}),
    "spam": frozenset(),
    "closed": frozenset(),
}
DECLINE_REASONS = ("outside_service_area", "service_not_offered", "no_capacity", "duplicate", "other")
PUBLIC_STATUS = {
    "new": "received",
    "in_review": "in_review",
    "follow_up_planned": "follow_up_planned",
    "declined": "declined",
    "spam": "declined",
    "closed": "closed",
}
PUBLIC_FLAGS = frozenset({"partially_supported"})

RECEIPT_TEXT = {
    "en": (
        "Request received. A person at {name} will review it and contact the requester directly. "
        "This receipt is not a quote, not a price, not an appointment and not an order confirmation."
    ),
    "de": (
        "Anfrage eingegangen. Eine Person bei {name} prüft sie und meldet sich direkt bei der anfragenden Person. "
        "Diese Eingangsbestätigung ist kein Angebot, kein Kostenvoranschlag, kein Preis, kein Termin "
        "und keine Auftragsbestätigung."
    ),
}
NOTICE_TEXT = {
    "en": "Not an emergency channel. In case of danger, call the local emergency number immediately.",
    "de": "Kein Notfallkanal. Bei Gefahr sofort den örtlichen Notruf wählen.",
}
STATUS_TEXT = {
    "received": {
        "en": "Received. Waiting for review by a person.",
        "de": "Eingegangen. Wartet auf Prüfung durch eine Person.",
    },
    "in_review": {
        "en": "A person is reviewing the request.",
        "de": "Eine Person prüft die Anfrage.",
    },
    "follow_up_planned": {
        "en": "The provider plans to contact the requester directly. This is not a quote and not an appointment.",
        "de": "Der Betrieb meldet sich direkt bei der anfragenden Person. Das ist kein Angebot und kein Termin.",
    },
    "declined": {
        "en": "The provider will not follow up on this request.",
        "de": "Der Betrieb verfolgt diese Anfrage nicht weiter.",
    },
    "closed": {
        "en": "The request is closed.",
        "de": "Die Anfrage ist abgeschlossen.",
    },
}


@dataclass(frozen=True)
class Limits:
    per_client_per_hour: int = 10
    per_contact_per_day: int = 5
    global_per_day: int = 200
    status_per_client_per_hour: int = 60
    duplicate_window_hours: int = 24
    idempotency_days: int = 7
    max_body_bytes: int = 32_768


@dataclass(frozen=True)
class Result:
    status: int
    body: dict[str, Any]
    headers: tuple[tuple[str, str], ...] = field(default=())


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _lang(language: str | None) -> str:
    return "de" if (language or "").lower().startswith("de") else "en"


def _normalize_contact(request: dict[str, Any]) -> str:
    requester = request["requester"]
    channel = requester["preferred_contact"]
    value = requester[channel]
    if channel == "email":
        return "email:" + value.strip().lower()
    return "phone:" + re.sub(r"[^\d+]", "", value)


class QuoteService:
    def __init__(
        self,
        store: Store,
        profile: Profile,
        secret: bytes,
        *,
        base_url: str,
        limits: Limits | None = None,
        retention_days: int = 180,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(secret) < 16:
            raise ValueError("secret must be at least 16 bytes")
        self.store = store
        self.profile = profile
        self._secret = secret
        self.base_url = base_url.rstrip("/")
        self.limits = limits or Limits()
        self.retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- helpers ------------------------------------------------------------
    def _now(self) -> datetime:
        return self._clock().astimezone(timezone.utc)

    def _hmac(self, label: str, data: bytes) -> str:
        return hmac.new(self._secret, label.encode("ascii") + b"\0" + data, hashlib.sha256).hexdigest()[:40]

    def status_url(self, request_id: str) -> str:
        return f"{self.base_url}{API_PREFIX}/quote-requests/{request_id}"

    def is_accepting(self) -> bool:
        with self.store.transaction(write=False) as conn:
            return get_setting(conn, "accepting_requests", "1") == "1"

    def _receipt(self, request_id: str, received_at: str, language: str | None, flags: list[str], replayed: bool) -> dict[str, Any]:
        lang = _lang(language)
        notice = NOTICE_TEXT[lang]
        if self.profile.emergency_note:
            notice = f"{notice} {self.profile.emergency_note}"
        receipt: dict[str, Any] = {
            "openquote": PROTOCOL_VERSION,
            "request_id": request_id,
            "status": "received",
            "received_at": received_at,
            "provider": {"id": self.profile.provider_id, "name": self.profile.name},
            "message": RECEIPT_TEXT[lang].format(name=self.profile.name),
            "notice": notice,
            "next_step": "human_review",
            "is_quote": False,
            "is_commitment": False,
            "status_url": self.status_url(request_id),
            "replayed": replayed,
        }
        if self.profile.response_time_hint:
            receipt["response_time_hint"] = self.profile.response_time_hint
        public_flags = [flag for flag in flags if flag in PUBLIC_FLAGS]
        if public_flags:
            receipt["flags"] = public_flags
        return receipt

    def _error(self, err: OpenQuoteError, day: str) -> Result:
        try:
            with self.store.transaction() as conn:
                count_rejection(conn, day, err.code)
        except Exception:  # counting must never mask the real answer
            pass
        headers: tuple[tuple[str, str], ...] = ()
        if err.retry_after is not None:
            headers = (("Retry-After", str(int(err.retry_after))),)
        return Result(err.http_status, err.to_body(), headers)

    def _paused_error(self, conn) -> OpenQuoteError:
        message = get_setting(conn, "pause_message")
        if message:
            return OpenQuoteError("paused", f"The provider is currently not accepting requests: {message}")
        return OpenQuoteError("paused")

    # -- public operations -----------------------------------------------------
    def public_profile(self) -> dict[str, Any]:
        return self.profile.public_document(self.base_url, self.is_accepting())

    def submit(self, raw: bytes, *, client_key: str, channel: str) -> Result:
        """Validate and store one request. ``channel`` is 'http' or 'mcp'."""
        now_dt = self._now()
        now = now_dt.timestamp()
        day = now_dt.date().isoformat()
        limits = self.limits
        try:
            if len(raw) > limits.max_body_bytes:
                raise OpenQuoteError("payload_too_large", f"The request body must not exceed {limits.max_body_bytes} bytes.")

            # Every attempt counts against the client's budget, valid or not.
            client_bucket = "c:" + self._hmac("client", client_key.encode("utf-8"))
            with self.store.transaction() as conn:
                if get_setting(conn, "accepting_requests", "1") != "1":
                    raise self._paused_error(conn)
                wait = rate_check(conn, client_bucket, 3600, limits.per_client_per_hour, now)
                if wait:
                    raise OpenQuoteError("rate_limited", retry_after=wait)
                rate_record(conn, client_bucket, now)

            request, flags = validate_request(raw, self.profile, now_dt.date())
            key = request["idempotency_key"]
            body_hash = self._hmac("body", _canonical(request))
            content = {
                "service": request["service"],
                "location": request["location"],
                "requester": {k: request["requester"].get(k) for k in ("name", "email", "phone")},
            }
            content_hash = self._hmac("content", _canonical(content))
            contact_bucket = "k:" + self._hmac("contact", _normalize_contact(request).encode("utf-8"))
            language = request["requester"].get("language")

            with self.store.transaction() as conn:
                if get_setting(conn, "accepting_requests", "1") != "1":
                    raise self._paused_error(conn)

                existing = conn.execute(
                    "SELECT i.request_id, i.body_hash, r.received_at, r.language, r.flags "
                    "FROM idempotency i JOIN requests r ON r.id = i.request_id WHERE i.key = ?",
                    (key,),
                ).fetchone()
                if existing:
                    if existing["body_hash"] != body_hash:
                        raise OpenQuoteError("idempotency_conflict")
                    receipt = self._receipt(
                        existing["request_id"], existing["received_at"], existing["language"],
                        json.loads(existing["flags"]), replayed=True,
                    )
                    return Result(200, receipt)

                wait = rate_check(conn, contact_bucket, 86_400, limits.per_contact_per_day, now)
                if wait:
                    raise OpenQuoteError("rate_limited", "Too many requests for this contact today.", retry_after=wait)
                wait = rate_check(conn, "global", 86_400, limits.global_per_day, now)
                if wait:
                    raise OpenQuoteError("rate_limited", "The provider's daily request capacity is reached.", retry_after=wait)
                since = _iso(now_dt - timedelta(hours=limits.duplicate_window_hours))
                if conn.execute(
                    "SELECT 1 FROM requests WHERE content_hash = ? AND received_at >= ? LIMIT 1", (content_hash, since)
                ).fetchone():
                    raise OpenQuoteError("duplicate_request")

                request_id = "oqr_" + secrets.token_urlsafe(18)
                received_at = _iso(now_dt)
                conn.execute(
                    "INSERT INTO requests (id, received_at, updated_at, status, channel, service_id, postal_code, "
                    "urgency, language, flags, content_hash, contact_hash, payload) "
                    "VALUES (?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request_id, received_at, received_at, channel,
                        request["service"]["service_id"], request["location"]["postal_code"],
                        request["service"]["urgency"], language, json.dumps(flags),
                        content_hash, contact_bucket,
                        json.dumps(request, ensure_ascii=False, sort_keys=True),
                    ),
                )
                conn.execute(
                    "INSERT INTO idempotency (key, request_id, body_hash, created_at) VALUES (?, ?, ?, ?)",
                    (key, request_id, body_hash, received_at),
                )
                rate_record(conn, contact_bucket, now)
                rate_record(conn, "global", now)
                audit.append(
                    conn,
                    ts=received_at,
                    event="request_received",
                    actor=f"channel:{channel}",
                    request_id=request_id,
                    details={"service_id": request["service"]["service_id"], "urgency": request["service"]["urgency"], "flags": flags},
                )
            return Result(201, self._receipt(request_id, received_at, language, flags, replayed=False))
        except OpenQuoteError as err:
            return self._error(err, day)

    def status(self, request_id: str, *, client_key: str) -> Result:
        now_dt = self._now()
        day = now_dt.date().isoformat()
        try:
            bucket = "s:" + self._hmac("status", client_key.encode("utf-8"))
            with self.store.transaction() as conn:
                wait = rate_check(conn, bucket, 3600, self.limits.status_per_client_per_hour, now_dt.timestamp())
                if wait:
                    raise OpenQuoteError("rate_limited", retry_after=wait)
                rate_record(conn, bucket, now_dt.timestamp())
                row = None
                if REQUEST_ID.match(request_id):
                    row = conn.execute(
                        "SELECT id, status, decline_reason, updated_at, language FROM requests WHERE id = ?", (request_id,)
                    ).fetchone()
            if row is None:
                raise OpenQuoteError("not_found", "Unknown request id.")
            public = PUBLIC_STATUS[row["status"]]
            body: dict[str, Any] = {
                "openquote": PROTOCOL_VERSION,
                "request_id": row["id"],
                "status": public,
                "updated_at": row["updated_at"],
                "message": STATUS_TEXT[public][_lang(row["language"])],
                "is_quote": False,
                "is_commitment": False,
            }
            if public == "declined":
                body["decline_reason"] = "other" if row["status"] == "spam" else (row["decline_reason"] or "other")
            return Result(200, body)
        except OpenQuoteError as err:
            return self._error(err, day)

    # -- inbox / operator operations --------------------------------------------
    def list_requests(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = (
            "SELECT id, received_at, updated_at, status, decline_reason, channel, service_id, "
            "postal_code, urgency, flags, erased_at FROM requests"
        )
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY received_at DESC, id LIMIT ?"
        params.append(int(limit))
        with self.store.transaction(write=False) as conn:
            rows = conn.execute(query, params).fetchall()
        return [{**dict(row), "flags": json.loads(row["flags"])} for row in rows]

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self.store.transaction(write=False) as conn:
            row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["flags"] = json.loads(record["flags"])
        record["payload"] = json.loads(record["payload"]) if record["payload"] else None
        record.pop("content_hash", None)
        record.pop("contact_hash", None)
        return record

    def set_status(self, request_id: str, new_status: str, *, actor: str, reason: str | None = None) -> dict[str, Any]:
        if new_status not in INTERNAL_STATUSES:
            raise ValueError(f"unknown status {new_status!r}; use one of {', '.join(INTERNAL_STATUSES)}")
        if new_status == "declined":
            if reason not in DECLINE_REASONS:
                raise ValueError(f"declining needs --reason, one of {', '.join(DECLINE_REASONS)}")
        elif reason is not None:
            raise ValueError("--reason is only used when declining")
        now = _iso(self._now())
        with self.store.transaction() as conn:
            row = conn.execute("SELECT status FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise ValueError(f"unknown request id {request_id}")
            current = row["status"]
            if new_status not in TRANSITIONS[current]:
                allowed = ", ".join(sorted(TRANSITIONS[current])) or "none"
                raise ValueError(f"cannot change status from {current!r} to {new_status!r}; allowed: {allowed}")
            conn.execute(
                "UPDATE requests SET status = ?, decline_reason = ?, updated_at = ? WHERE id = ?",
                (new_status, reason if new_status == "declined" else None, now, request_id),
            )
            audit.append(
                conn, ts=now, event="status_changed", actor=actor, request_id=request_id,
                details={"from": current, "to": new_status, "reason": reason},
            )
        return {"request_id": request_id, "from": current, "to": new_status, "updated_at": now}

    def pause(self, *, actor: str, message: str | None = None) -> None:
        now = _iso(self._now())
        with self.store.transaction() as conn:
            set_setting(conn, "accepting_requests", "0")
            set_setting(conn, "pause_message", (message or "").strip()[:200])
            audit.append(conn, ts=now, event="intake_paused", actor=actor, details={"has_message": bool(message)})

    def resume(self, *, actor: str) -> None:
        now = _iso(self._now())
        with self.store.transaction() as conn:
            set_setting(conn, "accepting_requests", "1")
            set_setting(conn, "pause_message", "")
            audit.append(conn, ts=now, event="intake_resumed", actor=actor)

    def erase(self, request_id: str, *, actor: str) -> bool:
        """Remove personal data of one request (right to erasure). Metadata stays."""
        now = _iso(self._now())
        with self.store.transaction() as conn:
            row = conn.execute("SELECT erased_at FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE requests SET payload = NULL, postal_code = '', flags = '[]', "
                "content_hash = '', contact_hash = '', language = NULL, erased_at = ?, updated_at = ? "
                "WHERE id = ?",
                (now, now, request_id),
            )
            conn.execute("DELETE FROM idempotency WHERE request_id = ?", (request_id,))
            audit.append(conn, ts=now, event="request_erased", actor=actor, request_id=request_id)
        return True

    def export(self, request_id: str) -> dict[str, Any] | None:
        """All stored data about one request (right of access)."""
        record = self.get_request(request_id)
        if record is None:
            return None
        return {"openquote": PROTOCOL_VERSION, "exported_at": _iso(self._now()), "request": record}

    def purge(self, *, actor: str) -> dict[str, int]:
        """Apply retention only when invoked/scheduled externally; audit entries remain pseudonymous."""
        now_dt = self._now()
        cutoff = _iso(now_dt - timedelta(days=self.retention_days))
        idem_cutoff = _iso(now_dt - timedelta(days=self.limits.idempotency_days))
        counter_cutoff = (now_dt - timedelta(days=400)).date().isoformat()
        with self.store.transaction() as conn:
            requests = conn.execute("DELETE FROM requests WHERE received_at < ?", (cutoff,)).rowcount
            conn.execute(
                "DELETE FROM idempotency WHERE created_at < ? OR request_id NOT IN (SELECT id FROM requests)",
                (idem_cutoff,),
            )
            conn.execute("DELETE FROM rate_events WHERE ts < ?", (now_dt.timestamp() - 2 * 86_400,))
            conn.execute("DELETE FROM counters WHERE day < ?", (counter_cutoff,))
            audit.append(
                conn, ts=_iso(now_dt), event="retention_purge", actor=actor,
                details={"requests_deleted": requests, "retention_days": self.retention_days},
            )
        return {"requests_deleted": requests}

    def stats(self, days: int = 30) -> dict[str, Any]:
        since_day = (self._now() - timedelta(days=days)).date().isoformat()
        with self.store.transaction(write=False) as conn:
            by_status = {row["status"]: row["n"] for row in conn.execute("SELECT status, COUNT(*) AS n FROM requests GROUP BY status")}
            rejections = {
                row["code"]: row["n"]
                for row in conn.execute("SELECT code, SUM(n) AS n FROM counters WHERE day >= ? GROUP BY code", (since_day,))
            }
            accepting = get_setting(conn, "accepting_requests", "1") == "1"
        return {"accepting_requests": accepting, "requests_by_status": by_status, f"rejections_last_{days}_days": rejections}

    def audit_verify(self) -> audit.VerifyResult:
        with self.store.transaction(write=False) as conn:
            return audit.verify(conn)

    def audit_head(self) -> tuple[int, str]:
        with self.store.transaction(write=False) as conn:
            return audit.head(conn)
