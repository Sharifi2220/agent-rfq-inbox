from __future__ import annotations

import io
import json
import sqlite3

import pytest

from openquote_lite import audit
from openquote_lite.schema_engine import load_schema
from openquote_lite.service import Limits

from .conftest import make_request, raw

jsonschema = pytest.importorskip("jsonschema")
DEFS = load_schema("responses.schema.json")["$defs"]


def submit(service, request, client="ip:198.51.100.7"):
    return service.submit(raw(request), client_key=client, channel="http")


def test_receipt_is_never_a_quote(service) -> None:
    request = make_request()
    result = submit(service, request)
    assert result.status == 201
    jsonschema.validate(result.body, DEFS["receipt"])
    body = result.body
    assert body["is_quote"] is False and body["is_commitment"] is False
    assert body["next_step"] == "human_review"
    assert body["status_url"] == f"https://anfragen.example/api/v0/quote-requests/{body['request_id']}"
    assert "kein Angebot" in body["message"] and "Kein Notfallkanal" in body["notice"]
    # Free text from the requester is never echoed back to the agent.
    text = json.dumps(body, ensure_ascii=False)
    assert request["service"]["summary"] not in text and "Erika" not in text


def test_english_receipt_for_non_german_requester(service) -> None:
    request = make_request()
    request["requester"]["language"] = "fa"
    body = submit(service, request).body
    assert body["message"].startswith("Request received.")


def test_idempotent_retry_returns_the_original_receipt(service) -> None:
    request = make_request()
    first = submit(service, request)
    again = submit(service, request)
    assert again.status == 200
    assert again.body["request_id"] == first.body["request_id"]
    assert again.body["replayed"] is True
    changed = json.loads(json.dumps(request))
    changed["service"]["summary"] = "Etwas anderes"
    conflict = submit(service, changed)
    assert conflict.status == 409 and conflict.body["error"]["code"] == "idempotency_conflict"
    assert len(service.list_requests()) == 1


def test_copied_request_with_new_key_is_a_duplicate(service, clock) -> None:
    request = make_request()
    assert submit(service, request).status == 201
    copy = json.loads(json.dumps(request))
    copy["idempotency_key"] = "11111111-1111-4111-8111-111111111111"
    result = submit(service, copy)
    assert result.status == 409 and result.body["error"]["code"] == "duplicate_request"
    assert request["idempotency_key"] not in json.dumps(result.body)
    clock.advance(hours=25)
    assert submit(service, copy).status == 201


def test_every_attempt_counts_against_the_client_budget(make_service) -> None:
    service = make_service(Limits(per_client_per_hour=3))
    assert submit(service, {"invalid": True}).status == 422
    assert submit(service, make_request()).status == 201
    assert submit(service, make_request(location={"country": "AT", "postal_code": "1110"})).status == 201
    limited = submit(service, make_request(location={"country": "AT", "postal_code": "1120"}))
    assert limited.status == 429
    assert dict(limited.headers)["Retry-After"] == "3600"
    assert limited.body["error"]["retry_after_seconds"] == 3600
    other_client = submit(service, make_request(location={"country": "AT", "postal_code": "1120"}), client="ip:203.0.113.9")
    assert other_client.status == 201


def test_contact_and_global_daily_limits(make_service, clock) -> None:
    service = make_service(Limits(per_contact_per_day=2, global_per_day=3))
    for code in ("1100", "1110"):
        assert submit(service, make_request(location={"country": "AT", "postal_code": code})).status == 201
    third = submit(service, make_request(location={"country": "AT", "postal_code": "1120"}))
    assert third.status == 429 and "contact" in third.body["error"]["message"]
    other = make_request()
    other["requester"] = {"name": "Max Muster", "phone": "+43 1 234567", "preferred_contact": "phone"}
    assert submit(service, other, client="ip:203.0.113.1").status == 201
    fourth = make_request()
    fourth["requester"] = {"name": "Eva Test", "email": "eva@example.org", "preferred_contact": "email"}
    capped = submit(service, fourth, client="ip:203.0.113.2")
    assert capped.status == 429 and "capacity" in capped.body["error"]["message"]
    clock.advance(hours=24, seconds=1)
    assert submit(service, fourth, client="ip:203.0.113.2").status == 201


def test_kill_switch(service) -> None:
    service.pause(actor="test", message="Betriebsurlaub bis 7. Jänner")
    result = submit(service, make_request())
    assert result.status == 503 and "Betriebsurlaub" in result.body["error"]["message"]
    assert service.public_profile()["endpoint"]["accepting_requests"] is False
    service.resume(actor="test")
    assert submit(service, make_request()).status == 201


def test_body_size_limit(make_service) -> None:
    service = make_service(Limits(max_body_bytes=200))
    assert submit(service, make_request()).status == 413


def test_status_lifecycle_and_public_mapping(service) -> None:
    request_id = submit(service, make_request()).body["request_id"]
    check = lambda: service.status(request_id, client_key="ip:1").body  # noqa: E731
    assert check()["status"] == "received"
    jsonschema.validate(check(), DEFS["status"])
    service.set_status(request_id, "in_review", actor="test")
    assert check()["status"] == "in_review"
    with pytest.raises(ValueError):
        service.set_status(request_id, "declined", actor="test")  # reason missing
    service.set_status(request_id, "declined", actor="test", reason="no_capacity")
    body = check()
    assert body["status"] == "declined" and body["decline_reason"] == "no_capacity"
    jsonschema.validate(body, DEFS["status"])
    service.set_status(request_id, "closed", actor="test")
    with pytest.raises(ValueError):
        service.set_status(request_id, "in_review", actor="test")


def test_spam_is_reported_as_declined_other(service) -> None:
    request_id = submit(service, make_request()).body["request_id"]
    service.set_status(request_id, "spam", actor="test")
    body = service.status(request_id, client_key="ip:1").body
    assert body["status"] == "declined" and body["decline_reason"] == "other"


@pytest.mark.parametrize("request_id", ["oqr_doesnotexist000000000000", "../../etc/passwd", "oqr_"])
def test_unknown_or_malformed_ids(service, request_id) -> None:
    result = service.status(request_id, client_key="ip:1")
    assert result.status == 404 and result.body["error"]["code"] == "not_found"


def test_status_lookups_are_rate_limited(make_service) -> None:
    service = make_service(Limits(status_per_client_per_hour=2))
    for _ in range(2):
        assert service.status("oqr_x", client_key="ip:1").status == 404
    assert service.status("oqr_x", client_key="ip:1").status == 429


def test_erase_export_and_purge(service, clock) -> None:
    request_id = submit(service, make_request()).body["request_id"]
    exported = service.export(request_id)
    assert exported["request"]["payload"]["requester"]["email"] == "erika@example.org"
    assert service.erase(request_id, actor="test")
    record = service.get_request(request_id)
    assert record["payload"] is None and record["postal_code"] == "" and record["erased_at"]
    assert service.status(request_id, client_key="ip:1").status == 200
    clock.advance(days=181)
    assert service.purge(actor="test") == {"requests_deleted": 1}
    assert service.status(request_id, client_key="ip:1").status == 404
    assert service.audit_verify().ok


def test_audit_chain_detects_tampering(service) -> None:
    ids = [submit(service, make_request(location={"country": "AT", "postal_code": code})).body["request_id"] for code in ("1100", "1110", "1120")]
    service.set_status(ids[0], "in_review", actor="test")
    result = service.audit_verify()
    assert result.ok and result.entries == 4
    seq, head = service.audit_head()
    assert seq == 4 and head == result.head

    conn = sqlite3.connect(service.store.path)
    conn.execute("UPDATE audit_log SET details = '{\"service_id\": \"forged\"}' WHERE seq = 2")
    conn.commit()
    broken = service.audit_verify()
    assert not broken.ok and broken.first_bad_seq == 2 and broken.reason == "entry content changed"

    conn.execute("DELETE FROM audit_log WHERE seq = 2")
    conn.commit()
    conn.close()
    assert service.audit_verify().reason == "sequence gap"


def test_audit_log_contains_no_personal_data(service) -> None:
    request_id = submit(service, make_request()).body["request_id"]
    service.set_status(request_id, "follow_up_planned", actor="cli:office")
    service.erase(request_id, actor="cli:office")
    out = io.StringIO()
    with service.store.transaction(write=False) as conn:
        assert audit.export_jsonl(conn, out) == 3
    text = out.getvalue()
    for personal in ("Erika", "erika@example.org", "1100", "Gastherme", "Wien"):
        assert personal not in text


def test_rejections_are_counted_not_audited(service) -> None:
    submit(service, {"bad": 1})
    submit(service, make_request(accepted_price=10))
    stats = service.stats()
    assert stats["rejections_last_30_days"] == {"validation_failed": 1, "commitment_not_allowed": 1}
    assert service.audit_verify().entries == 0


def test_concurrent_submissions_keep_the_audit_chain_intact(make_service) -> None:
    import threading

    service = make_service(Limits(per_client_per_hour=100, per_contact_per_day=100))
    errors: list[int] = []

    def worker(index: int) -> None:
        request = make_request()
        request["requester"]["name"] = f"Person {index}"
        result = submit(service, request, client=f"ip:10.0.0.{index}")
        if result.status != 201:
            errors.append(result.status)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    verified = service.audit_verify()
    assert verified.ok and verified.entries == 20
