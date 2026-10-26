"""Error type shared by the service, the HTTP API and the MCP binding."""

from __future__ import annotations

from typing import Any

from . import PROTOCOL_VERSION

# code -> (HTTP status, default message)
ERROR_CODES: dict[str, tuple[int, str]] = {
    "invalid_json": (400, "The body is not a single valid JSON object."),
    "not_found": (404, "Not found."),
    "method_not_allowed": (405, "Method not allowed."),
    "length_required": (411, "A Content-Length header is required."),
    "payload_too_large": (413, "The request body is too large."),
    "unsupported_media_type": (415, "Content-Type must be application/json."),
    "validation_failed": (422, "The request does not match the OpenQuote Lite 0.1 schema."),
    "invalid_characters": (422, "The request contains control or bidirectional override characters."),
    "commitment_not_allowed": (
        422,
        "Quote requests cannot accept prices, confirm orders, book appointments or carry payment data.",
    ),
    "missing_contact": (422, "The preferred contact channel must be provided."),
    "invalid_date": (422, "A date is invalid, in the past, or the window is reversed."),
    "service_not_offered": (422, "The provider does not offer this service."),
    "outside_service_area": (422, "The location is outside the provider's service area."),
    "wanted_not_supported": (422, "The provider accepts none of the requested response types."),
    "idempotency_conflict": (409, "This idempotency key was already used for a different request."),
    "duplicate_request": (409, "An identical request was received recently. Reuse the original idempotency key."),
    "rate_limited": (429, "Too many requests. Try again later."),
    "paused": (503, "The provider is currently not accepting requests."),
    "internal_error": (500, "Internal error."),
}


class OpenQuoteError(Exception):
    """A protocol-level rejection with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: list[dict[str, str]] | None = None,
        retry_after: int | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code {code!r}")
        self.code = code
        self.http_status = ERROR_CODES[code][0]
        self.message = message or ERROR_CODES[code][1]
        self.details = details or []
        self.retry_after = retry_after
        super().__init__(f"{code}: {self.message}")

    def to_body(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            error["retry_after_seconds"] = int(self.retry_after)
        if self.details:
            error["details"] = self.details
        return {"openquote": PROTOCOL_VERSION, "error": error}
