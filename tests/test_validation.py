from __future__ import annotations

from datetime import date

import pytest

from openquote_lite.errors import OpenQuoteError
from openquote_lite.validation import (
    find_commitment_keys,
    normalize,
    parse_json_object,
    validate_request,
)

from .conftest import make_request, raw

TODAY = date(2026, 10, 26)


def reject_code(document, profile, *, body: bytes | None = None) -> str:
    with pytest.raises(OpenQuoteError) as info:
        validate_request(body if body is not None else raw(document), profile, TODAY)
    return info.value.code


def test_valid_request_passes(profile) -> None:
    request, flags = validate_request(raw(make_request()), profile, TODAY)
    assert request["service"]["service_id"] == "heating.repair"
    assert flags == []


@pytest.mark.parametrize(
    "body",
    [
        b'{"a": 1, "a": 2}',
        b'{"a": NaN}',
        b'{"a": Infinity}',
        b"[1, 2]",
        b"\xff\xfe",
        b"",
        b'{"a": ' * 20 + b"1" + b"}" * 20,
    ],
)
def test_strict_json_parsing(body: bytes) -> None:
    with pytest.raises(OpenQuoteError) as info:
        parse_json_object(body)
    assert info.value.code == "invalid_json"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(accepted_price=1200),
        lambda r: r["service"].update(confirmOrder=True),
        lambda r: r["requester"].update({"Payment-Token": "tok"}),
        lambda r: r.update(booking={"date": "2026-11-01"}),
        lambda r: r["service"]["object"].update(IBAN="AT00"),
    ],
)
def test_commitment_fields_reject_the_whole_request(profile, mutate) -> None:
    request = make_request()
    mutate(request)
    assert reject_code(request, profile) == "commitment_not_allowed"


def test_commitment_scan_reports_paths() -> None:
    assert find_commitment_keys({"a": [{"accept_offer": 1}], "b": {"Order": 2}}) == ["/a/0/accept_offer", "/b/Order"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary", "Therme \u202edefekt"),  # right-to-left override (spoofing)
        ("summary", "Therme\x00defekt"),
        ("summary", "Zeile eins\nZeile zwei"),  # single-line field
        ("summary", "Therme\u2066defekt\u2069"),
        ("details", "Text mit \x07 Steuerzeichen"),
    ],
)
def test_dangerous_characters_are_rejected(profile, field, value) -> None:
    request = make_request()
    request["service"][field] = value
    assert reject_code(request, profile) == "invalid_characters"


def test_persian_text_with_zwnj_and_line_breaks_in_details_is_allowed(profile) -> None:
    request = make_request()
    request["service"]["summary"] = "پکیج گرمایشی خاموش می\u200cشود"
    request["service"]["details"] = "خط اول\r\nخط دوم"
    normalized, _ = validate_request(raw(request), profile, TODAY)
    assert normalized["service"]["details"] == "خط اول\nخط دوم"


def test_unicode_is_normalized_to_nfc_and_trimmed() -> None:
    result = normalize({"service": {"summary": "  Cafe\u0301 Heizung  "}})
    assert result["service"]["summary"] == "Café Heizung"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.pop("authorization"),
        lambda r: r["authorization"].update(contact_allowed=False),
        lambda r: r.update(openquote="0.2"),
        lambda r: r.update(idempotency_key="short"),
        lambda r: r["service"].update(urgency="emergency"),
        lambda r: r["service"].update(summary="ab"),
        lambda r: r["service"].update(details="x" * 4001),
        lambda r: r.update(wanted=[]),
        lambda r: r.update(wanted=["quote", "quote"]),
        lambda r: r["location"].update(country="at"),
        lambda r: r["requester"].update(email="not-an-email"),
        lambda r: r.update(unexpected=True),
        lambda r: r["service"]["object"].update(year_installed=True),
    ],
)
def test_schema_violations(profile, mutate) -> None:
    request = make_request()
    mutate(request)
    assert reject_code(request, profile) == "validation_failed"


def test_missing_preferred_contact(profile) -> None:
    request = make_request()
    request["requester"]["preferred_contact"] = "phone"
    assert reject_code(request, profile) == "missing_contact"


@pytest.mark.parametrize(
    "timing",
    [
        {"earliest_date": "2026-02-30"},
        {"earliest_date": "2026-11-20", "latest_date": "2026-11-10"},
        {"latest_date": "2026-10-01"},
        {"earliest_date": "2029-01-01"},
    ],
)
def test_invalid_dates(profile, timing) -> None:
    assert reject_code(make_request(timing=timing), profile) == "invalid_date"


def test_yesterday_is_tolerated_for_other_time_zones(profile) -> None:
    validate_request(raw(make_request(timing={"latest_date": "2026-10-25"})), profile, TODAY)


def test_service_not_offered(profile) -> None:
    request = make_request()
    request["service"]["service_id"] = "roofing.repair"
    assert reject_code(request, profile) == "service_not_offered"


@pytest.mark.parametrize("location", [{"country": "DE", "postal_code": "1100"}, {"country": "AT", "postal_code": "1200"}])
def test_outside_service_area(profile, location) -> None:
    assert reject_code(make_request(location=location), profile) == "outside_service_area"


def test_postal_code_matching_ignores_spaces(profile) -> None:
    validate_request(raw(make_request(location={"country": "AT", "postal_code": "11 00"})), profile, TODAY)


def test_wanted_types(profile) -> None:
    assert reject_code(make_request(wanted=["documents"]), profile) == "wanted_not_supported"
    _, flags = validate_request(raw(make_request(wanted=["quote", "documents"])), profile, TODAY)
    assert flags == ["partially_supported"]


def test_many_links_flag(profile) -> None:
    request = make_request()
    request["service"]["details"] = " ".join(f"https://spam{i}.example" for i in range(4))
    _, flags = validate_request(raw(request), profile, TODAY)
    assert "many_links" in flags
