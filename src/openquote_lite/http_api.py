"""Dependency-free WSGI application exposing the OpenQuote Lite HTTP API.

Endpoints (all JSON):

    GET  /.well-known/api-catalog          RFC 9727 API catalog (also HEAD)
    GET  /api/v0                           index
    GET  /api/v0/health                    liveness
    GET  /api/v0/profile                   public provider profile
    GET  /api/v0/profile.jsonld            schema.org JSON-LD for the website
    GET  /api/v0/openapi.json              OpenAPI 3.1 description
    GET  /api/v0/schemas/<file>            bundled JSON Schemas
    POST /api/v0/quote-requests            submit a quote request
    GET  /api/v0/quote-requests/<id>       status of one request

The built-in server (``serve``) is meant for local use and pilots behind a TLS
reverse proxy. For production use any WSGI server, e.g.
``waitress-serve --call openquote_lite.http_api:app_from_env``.
"""

from __future__ import annotations

import json
import logging
import socketserver
import sys
import traceback
from urllib.parse import urlsplit
from typing import Any, Callable, Iterable
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from . import PROTOCOL_VERSION, __version__
from .errors import OpenQuoteError
from .profile import API_PREFIX
from .schema_engine import load_schema
from .service import QuoteService, Result

log = logging.getLogger("openquote_lite.http")

SCHEMA_FILES = ("quote-request.schema.json", "provider-profile.schema.json", "responses.schema.json")
_STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request", 404: "Not Found",
    405: "Method Not Allowed", 409: "Conflict", 411: "Length Required", 413: "Content Too Large",
    415: "Unsupported Media Type", 422: "Unprocessable Content", 429: "Too Many Requests",
    500: "Internal Server Error", 503: "Service Unavailable",
}
_BASE_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
)
_PUBLIC_METADATA = (
    ("Access-Control-Allow-Origin", "*"),
    ("Cache-Control", "public, max-age=300"),
)
_NO_STORE = (("Cache-Control", "no-store"),)

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


def openapi_document(service: QuoteService) -> dict[str, Any]:
    base = service.base_url
    request_schema = load_schema("quote-request.schema.json")
    responses = load_schema("responses.schema.json")["$defs"]

    def error_response(description: str) -> dict[str, Any]:
        return {"description": description, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}

    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"OpenQuote Lite endpoint of {service.profile.name}",
            "version": __version__,
            "description": (
                "Send bounded quote requests to this provider. Every request is reviewed by a person. "
                "Receipts and status documents are never quotes, prices, appointments or order confirmations "
                "(is_quote=false, is_commitment=false). Not an emergency channel. Reuse the same idempotency_key "
                "when retrying."
            ),
        },
        "servers": [{"url": base}],
        "paths": {
            f"{API_PREFIX}/profile": {
                "get": {
                    "operationId": "getProviderProfile",
                    "summary": "Services, service area and accepted request types of this provider",
                    "responses": {"200": {"description": "Provider profile (self-declared)"}},
                }
            },
            f"{API_PREFIX}/quote-requests": {
                "post": {
                    "operationId": "requestQuote",
                    "summary": "Submit a quote request for human review",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/QuoteRequest"}}},
                    },
                    "responses": {
                        "201": {"description": "Received", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Receipt"}}}},
                        "200": {"description": "Retry with the same idempotency key: original receipt", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Receipt"}}}},
                        "400": error_response("Invalid JSON"),
                        "409": error_response("Idempotency conflict or duplicate request"),
                        "413": error_response("Body too large"),
                        "415": error_response("Wrong content type"),
                        "422": error_response("Request rejected (validation, commitment fields, service area, ...)"),
                        "429": error_response("Rate limited; see Retry-After"),
                        "503": error_response("Provider paused intake"),
                    },
                }
            },
            f"{API_PREFIX}/quote-requests/{{request_id}}": {
                "get": {
                    "operationId": "getRequestStatus",
                    "summary": "Status of a previously submitted request",
                    "parameters": [{"name": "request_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Status", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Status"}}}},
                        "404": error_response("Unknown request id"),
                        "429": error_response("Rate limited"),
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "QuoteRequest": request_schema,
                "Receipt": responses["receipt"],
                "Status": responses["status"],
                "Error": responses["error"],
            }
        },
    }


def _client_key(environ: dict[str, Any], trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            # The right-most entry was added by our own reverse proxy and cannot be forged by the client.
            return "ip:" + hops[-1]
    return "ip:" + environ.get("REMOTE_ADDR", "unknown")


def create_app(service: QuoteService, *, trust_proxy: bool = False) -> Callable[[dict[str, Any], StartResponse], Iterable[bytes]]:
    """Build the WSGI application for one provider."""

    def respond(start_response: StartResponse, status: int, body: dict[str, Any] | None, *extra: tuple[str, str], head: bool = False, content_type: str = "application/json; charset=utf-8") -> list[bytes]:
        payload = b"" if body is None else json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        headers = list(_BASE_HEADERS) + list(extra)
        if body is not None:
            headers.append(("Content-Type", content_type))
        headers.append(("Content-Length", str(len(payload))))
        start_response(f"{status} {_STATUS_TEXT.get(status, 'Unknown')}", headers)
        return [] if head else [payload]

    def error(start_response: StartResponse, code: str, message: str | None = None, *extra: tuple[str, str]) -> list[bytes]:
        err = OpenQuoteError(code, message)
        return respond(start_response, err.http_status, err.to_body(), *_NO_STORE, *extra)

    def from_result(start_response: StartResponse, result: Result) -> list[bytes]:
        return respond(start_response, result.status, result.body, *_NO_STORE, *result.headers)

    def app(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        try:
            return route(environ, start_response)
        except Exception:  # never leak internals to the caller
            log.error("unhandled error:\n%s", traceback.format_exc())
            return error(start_response, "internal_error")

    def route(environ: dict[str, Any], start_response: StartResponse) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "") or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        head = method == "HEAD"
        read_method = method in ("GET", "HEAD")

        if method == "OPTIONS" and (path == "/.well-known/api-catalog" or path.startswith(API_PREFIX)):
            return respond(
                start_response, 204, None,
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS"),
                ("Access-Control-Max-Age", "600"),
            )

        if path == "/.well-known/api-catalog":
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            return respond(
                start_response, 200, service.profile.api_catalog(service.base_url), *_PUBLIC_METADATA,
                ("Link", '</.well-known/api-catalog>; rel="api-catalog"'),
                head=head,
                content_type='application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"',
            )

        if path == API_PREFIX:
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            base = service.base_url + API_PREFIX
            index = {
                "openquote": PROTOCOL_VERSION,
                "software": {"name": "OpenQuote Lite", "version": __version__},
                "links": {
                    "profile": f"{base}/profile",
                    "profile_jsonld": f"{base}/profile.jsonld",
                    "openapi": f"{base}/openapi.json",
                    "quote_requests": f"{base}/quote-requests",
                    "schemas": [f"{base}/schemas/{name}" for name in SCHEMA_FILES],
                },
            }
            return respond(start_response, 200, index, *_PUBLIC_METADATA, head=head)

        if path == f"{API_PREFIX}/health":
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            return respond(start_response, 200, {"status": "ok", "accepting_requests": service.is_accepting()}, *_NO_STORE, head=head)

        if path == f"{API_PREFIX}/profile":
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            return respond(start_response, 200, service.public_profile(), *_PUBLIC_METADATA, head=head)

        if path == f"{API_PREFIX}/profile.jsonld":
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            return respond(
                start_response, 200, service.profile.jsonld(service.base_url), *_PUBLIC_METADATA,
                head=head, content_type="application/ld+json; charset=utf-8",
            )

        if path == f"{API_PREFIX}/openapi.json":
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            return respond(
                start_response, 200, openapi_document(service), *_PUBLIC_METADATA,
                head=head, content_type="application/openapi+json; charset=utf-8",
            )

        if path.startswith(f"{API_PREFIX}/schemas/"):
            name = path.rsplit("/", 1)[-1]
            if name not in SCHEMA_FILES:
                return error(start_response, "not_found")
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            return respond(
                start_response, 200, load_schema(name), *_PUBLIC_METADATA,
                head=head, content_type="application/schema+json; charset=utf-8",
            )

        if path == f"{API_PREFIX}/quote-requests":
            if method != "POST":
                return error(start_response, "method_not_allowed", None, ("Allow", "POST"))
            content_type = environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
            if content_type != "application/json":
                return error(start_response, "unsupported_media_type")
            raw_length = environ.get("CONTENT_LENGTH", "")
            if not raw_length:
                return error(start_response, "length_required")
            try:
                length = int(raw_length)
            except ValueError:
                return error(start_response, "length_required", "Content-Length must be an integer.")
            if length < 0:
                return error(start_response, "length_required", "Content-Length must not be negative.")
            if length > service.limits.max_body_bytes:
                return error(start_response, "payload_too_large", f"The request body must not exceed {service.limits.max_body_bytes} bytes.")
            raw = environ["wsgi.input"].read(length) if length else b""
            result = service.submit(raw, client_key=_client_key(environ, trust_proxy), channel="http")
            return from_result(start_response, result)

        if path.startswith(f"{API_PREFIX}/quote-requests/"):
            if not read_method:
                return error(start_response, "method_not_allowed", None, ("Allow", "GET, HEAD"))
            request_id = path.rsplit("/", 1)[-1]
            result = service.status(request_id, client_key=_client_key(environ, trust_proxy))
            body = from_result(start_response, result)
            return [] if head else body

        return error(start_response, "not_found")

    return app


class _QuietHandler(WSGIRequestHandler):
    """Logs method, path and status only - no client IP addresses."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # Handler diagnostics can contain raw request targets. Never log them.
        sys.stderr.write("[openquote-lite] request handler event\n")

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        line = self.requestline.split(" ")
        method = line[0] if line else "-"
        path = urlsplit(line[1]).path if len(line) > 1 else "-"
        known = (
            "/.well-known/api-catalog", "/api/v0", "/api/v0/health",
            "/api/v0/profile", "/api/v0/profile.jsonld", "/api/v0/openapi.json",
            "/api/v0/quote-requests",
        )
        if path.startswith("/api/v0/quote-requests/"):
            target = "/api/v0/quote-requests/<id>"
        elif path.startswith("/api/v0/schemas/"):
            target = "/api/v0/schemas/<schema>"
        elif path in known:
            target = path
        else:
            target = "<unknown-route>"
        sys.stderr.write(f"[openquote-lite] {method} {target} {code}\n")


class _ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


class _SilentHandler(_QuietHandler):
    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        pass


def make_http_server(
    service: QuoteService, host: str, port: int, *, trust_proxy: bool = False, log_requests: bool = True
) -> WSGIServer:
    app = create_app(service, trust_proxy=trust_proxy)
    handler = _QuietHandler if log_requests else _SilentHandler
    return make_server(host, port, app, server_class=_ThreadingWSGIServer, handler_class=handler)


def serve(service: QuoteService, host: str = "127.0.0.1", port: int = 8787, *, trust_proxy: bool = False) -> None:
    server = make_http_server(service, host, port, trust_proxy=trust_proxy)
    sys.stderr.write(
        f"[openquote-lite] serving {service.profile.name} on http://{host}:{server.server_port} "
        f"(public base URL: {service.base_url})\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def app_from_env() -> Callable[[dict[str, Any], StartResponse], Iterable[bytes]]:
    """WSGI factory for external servers. Reads the config path from OPENQUOTE_CONFIG."""
    import os

    from .config import build_service, load_config

    config = load_config(os.environ.get("OPENQUOTE_CONFIG", "openquote.toml"))
    return create_app(build_service(config), trust_proxy=config.trust_proxy)
