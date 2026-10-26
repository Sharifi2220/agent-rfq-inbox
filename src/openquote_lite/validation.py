"""Parsing, normalisation and validation of incoming quote requests.

Order of checks (each step can reject the whole request):

1. strict JSON parsing (single object, no duplicate keys, no NaN/Infinity,
   bounded nesting depth)
2. commitment scan: keys such as ``accepted_price`` or ``confirm_order``
   anywhere in the document reject the request with ``commitment_not_allowed``
3. text normalisation: Unicode NFC, trimming, rejection of control and
   bidirectional-override characters
4. JSON Schema validation against ``quote-request.schema.json``
5. semantic checks that a schema cannot express (contact present, real
   calendar dates, date window)
6. provider checks against the profile (service offered, service area,
   accepted response types)
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .errors import OpenQuoteError
from .schema_engine import Issue, load_schema, validate

if TYPE_CHECKING:  # pragma: no cover
    from .profile import Profile

REQUEST_SCHEMA = "quote-request.schema.json"
MAX_DEPTH = 8

# Free-text fields that may contain line breaks. All other strings are single-line.
MULTILINE_FIELDS = frozenset({"/service/details", "/service/object/notes", "/timing/notes"})

# Keys that would let an agent smuggle a commitment into a request. Compared
# after lower-casing and removing '_', '-' and spaces, so camelCase variants match.
COMMITMENT_KEYS = frozenset(
    {
        "acceptedprice", "priceaccepted", "acceptprice", "acceptquote", "quoteaccepted",
        "acceptoffer", "offeraccepted", "confirmorder", "orderconfirmed", "orderconfirmation",
        "placeorder", "order", "purchase", "payment", "paymenttoken", "paymentmethod",
        "card", "cardnumber", "iban", "bic", "bookingconfirmed", "confirmbooking", "booking",
        "appointmentconfirmed", "confirmappointment", "contract", "signature",
        "termsaccepted", "acceptterms", "bindingoffer", "binding",
    }
)

# C0/C1 controls (tab/newline handled separately), DEL, bidi embeddings and
# overrides (U+202A-U+202E), bidi isolates (U+2066-U+2069), line/paragraph
# separators and an embedded BOM. ZWJ/ZWNJ (U+200C/U+200D) and LRM/RLM stay
# allowed because Persian, Arabic and emoji text legitimately use them.
_FORBIDDEN_ANYWHERE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")
_LINE_BREAKS_OR_TABS = re.compile("[\t\n\r]")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)")


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _depth(value: Any, level: int = 1) -> int:
    if isinstance(value, dict):
        return max([level] + [_depth(v, level + 1) for v in value.values()])
    if isinstance(value, list):
        return max([level] + [_depth(v, level + 1) for v in value])
    return level


def parse_json_object(raw: bytes) -> dict[str, Any]:
    """Parse a request body strictly. Raises OpenQuoteError('invalid_json')."""
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise OpenQuoteError("invalid_json", f"The body is not valid JSON: {exc.__class__.__name__}.") from None
    if not isinstance(value, dict):
        raise OpenQuoteError("invalid_json", "The body must be a JSON object.")
    if _depth(value) > MAX_DEPTH:
        raise OpenQuoteError("invalid_json", f"The JSON document is nested deeper than {MAX_DEPTH} levels.")
    return value


def find_commitment_keys(value: Any, path: str = "") -> list[str]:
    """Return JSON pointers of keys that try to carry a commitment."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            pointer = f"{path}/{key}"
            if re.sub(r"[\s_\-]", "", key.lower()) in COMMITMENT_KEYS:
                found.append(pointer)
            found.extend(find_commitment_keys(child, pointer))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(find_commitment_keys(child, f"{path}/{i}"))
    return found


def normalize(value: Any, path: str = "") -> Any:
    """NFC-normalise and trim strings; reject dangerous characters.

    Raises OpenQuoteError('invalid_characters') with the offending paths.
    """
    problems: list[dict[str, str]] = []

    def walk(node: Any, pointer: str) -> Any:
        if isinstance(node, dict):
            return {key: walk(child, f"{pointer}/{key}") for key, child in node.items()}
        if isinstance(node, list):
            return [walk(child, f"{pointer}/{i}") for i, child in enumerate(node)]
        if isinstance(node, str):
            text = unicodedata.normalize("NFC", node).replace("\r\n", "\n")
            if _FORBIDDEN_ANYWHERE.search(text):
                problems.append({"path": pointer, "code": "invalid_characters", "message": "contains control or bidi override characters"})
            elif pointer not in MULTILINE_FIELDS and _LINE_BREAKS_OR_TABS.search(text):
                problems.append({"path": pointer, "code": "invalid_characters", "message": "must be a single line"})
            elif "\r" in text:
                problems.append({"path": pointer, "code": "invalid_characters", "message": "contains a carriage return"})
            return text.strip()
        if isinstance(node, float) and node.is_integer():
            return int(node)
        return node

    normalized = walk(value, path)
    if problems:
        raise OpenQuoteError("invalid_characters", details=problems)
    return normalized


def schema_issues(request: dict[str, Any]) -> list[Issue]:
    return validate(request, load_schema(REQUEST_SCHEMA))


def _parse_date(text: str, pointer: str, problems: list[dict[str, str]]) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        problems.append({"path": pointer, "code": "invalid_date", "message": "is not a real calendar date"})
        return None


def semantic_checks(request: dict[str, Any], today: date) -> None:
    """Checks a JSON Schema cannot express. Raises OpenQuoteError."""
    requester = request["requester"]
    channel = requester["preferred_contact"]
    if channel not in requester:
        raise OpenQuoteError(
            "missing_contact",
            details=[{"path": f"/requester/{channel}", "code": "required", "message": f"is required because preferred_contact is {channel!r}"}],
        )

    timing = request.get("timing")
    if timing:
        problems: list[dict[str, str]] = []
        earliest = _parse_date(timing["earliest_date"], "/timing/earliest_date", problems) if "earliest_date" in timing else None
        latest = _parse_date(timing["latest_date"], "/timing/latest_date", problems) if "latest_date" in timing else None
        # One day of tolerance for senders in other time zones.
        if latest is not None and latest < today - timedelta(days=1):
            problems.append({"path": "/timing/latest_date", "code": "invalid_date", "message": "lies in the past"})
        if earliest is not None and earliest > today + timedelta(days=730):
            problems.append({"path": "/timing/earliest_date", "code": "invalid_date", "message": "lies more than two years ahead"})
        if earliest is not None and latest is not None and earliest > latest:
            problems.append({"path": "/timing", "code": "invalid_date", "message": "earliest_date is after latest_date"})
        if problems:
            raise OpenQuoteError("invalid_date", details=problems)


def provider_checks(request: dict[str, Any], profile: Profile) -> list[str]:
    """Checks against the provider profile. Returns flags for partial matches."""
    service_id = request["service"]["service_id"]
    if not profile.offers(service_id):
        raise OpenQuoteError(
            "service_not_offered",
            details=[{"path": "/service/service_id", "code": "service_not_offered", "message": f"offered ids: {', '.join(profile.service_ids())}"}],
        )
    location = request["location"]
    if not profile.covers(location["country"], location["postal_code"]):
        raise OpenQuoteError(
            "outside_service_area",
            details=[{"path": "/location", "code": "outside_service_area", "message": "not covered by this provider"}],
        )
    wanted = set(request["wanted"])
    accepted = wanted & profile.accepts()
    if not accepted:
        raise OpenQuoteError(
            "wanted_not_supported",
            details=[{"path": "/wanted", "code": "wanted_not_supported", "message": f"accepted: {', '.join(sorted(profile.accepts()))}"}],
        )
    flags: list[str] = []
    if accepted != wanted:
        flags.append("partially_supported")
    return flags


def content_flags(request: dict[str, Any]) -> list[str]:
    """Heuristic signals for the human reviewer. They never reject a request."""
    texts: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)
        elif isinstance(node, str):
            texts.append(node)

    collect(request.get("service", {}))
    collect(request.get("timing", {}))
    flags: list[str] = []
    if sum(len(_URL.findall(t)) for t in texts) > 3:
        flags.append("many_links")
    return flags


def validate_request(raw: bytes, profile: Profile, today: date) -> tuple[dict[str, Any], list[str]]:
    """Full validation pipeline. Returns (normalized request, reviewer flags)."""
    document = parse_json_object(raw)
    commitment = find_commitment_keys(document)
    if commitment:
        raise OpenQuoteError(
            "commitment_not_allowed",
            details=[{"path": p, "code": "commitment_not_allowed", "message": "commitment fields are rejected, not ignored"} for p in commitment],
        )
    request = normalize(document)
    issues = schema_issues(request)
    if issues:
        raise OpenQuoteError("validation_failed", details=[issue.as_dict() for issue in issues[:50]])
    semantic_checks(request, today)
    flags = provider_checks(request, profile)
    flags.extend(content_flags(request))
    return request, flags
