from __future__ import annotations

import copy
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from importlib import resources
from typing import Any

import pytest

from openquote_lite.profile import Profile
from openquote_lite.service import Limits, QuoteService
from openquote_lite.store import Store

START = datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now = self.now + timedelta(**delta)


def example_profile_data() -> dict[str, Any]:
    text = resources.files("openquote_lite").joinpath("examples", "provider-profile.example.json").read_text("utf-8")
    return json.loads(text)


BASE_REQUEST: dict[str, Any] = {
    "openquote": "0.1",
    "idempotency_key": "00000000-0000-4000-8000-000000000000",
    "service": {
        "service_id": "heating.repair",
        "summary": "Gastherme zeigt Störung F28",
        "details": "Kein Warmwasser.\nNeustart hat nicht geholfen.",
        "urgency": "as_soon_as_possible",
        "object": {"kind": "gas_boiler", "manufacturer": "Beispielwerk", "model": "BW 24", "year_installed": 2015},
        "requirements": ["Termin bitte vormittags"],
    },
    "location": {"country": "AT", "postal_code": "1100", "locality": "Wien"},
    "timing": {"earliest_date": "2026-10-28", "latest_date": "2026-11-15", "notes": "Wochentags"},
    "wanted": ["quote", "site_visit"],
    "requester": {"name": "Erika Beispiel", "email": "erika@example.org", "preferred_contact": "email", "language": "de"},
    "submitted_via": {"channel": "agent", "agent_name": "test-agent"},
    "authorization": {"requested_by_person": True, "contact_allowed": True},
}


def make_request(**overrides: Any) -> dict[str, Any]:
    """A valid request with a fresh idempotency key. Overrides replace top-level keys."""
    request = copy.deepcopy(BASE_REQUEST)
    request["idempotency_key"] = str(uuid.uuid4())
    request.update(copy.deepcopy(overrides))
    return request


def raw(document: Any) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def profile() -> Profile:
    return Profile.from_dict(example_profile_data())


@pytest.fixture
def make_service(tmp_path, clock, profile):
    def factory(limits: Limits | None = None, retention_days: int = 180, profile_obj: Profile | None = None) -> QuoteService:
        store = Store(tmp_path / f"db-{uuid.uuid4().hex}.sqlite3")
        return QuoteService(
            store,
            profile_obj or profile,
            b"test-secret-0123456789abcdef",
            base_url="https://anfragen.example",
            limits=limits,
            retention_days=retention_days,
            clock=clock,
        )

    return factory


@pytest.fixture
def service(make_service) -> QuoteService:
    return make_service()


class WSGIClient:
    def __init__(self, app) -> None:
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        content_type: str = "application/json",
        remote_addr: str = "198.51.100.7",
        headers: dict[str, str] | None = None,
        raw_body: bytes | None = None,
        content_length: str | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        data = raw_body if raw_body is not None else (b"" if body is None else raw(body))
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "REMOTE_ADDR": remote_addr,
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(len(data)) if content_length is None else content_length,
            "wsgi.input": io.BytesIO(data),
        }
        for key, value in (headers or {}).items():
            environ["HTTP_" + key.upper().replace("-", "_")] = value
        captured: dict[str, Any] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            captured["status"] = int(status.split(" ", 1)[0])
            captured["headers"] = {k.lower(): v for k, v in response_headers}

        payload = b"".join(self.app(environ, start_response))
        parsed = json.loads(payload) if payload else None
        return captured["status"], captured["headers"], parsed
