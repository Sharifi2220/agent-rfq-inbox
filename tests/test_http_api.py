from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from openquote_lite.http_api import create_app, make_http_server
from openquote_lite.profile import Profile
from openquote_lite.schema_engine import load_schema
from openquote_lite.service import Limits

from .conftest import WSGIClient, example_profile_data, make_request


@pytest.fixture
def client(service) -> WSGIClient:
    return WSGIClient(create_app(service))


def test_submit_and_status(client) -> None:
    status, headers, body = client.request("POST", "/api/v0/quote-requests", make_request())
    assert status == 201
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["content-type"].startswith("application/json")
    status, _, polled = client.request("GET", f"/api/v0/quote-requests/{body['request_id']}")
    assert status == 200 and polled["status"] == "received"


@pytest.mark.parametrize(
    ("kwargs", "expected_status", "code"),
    [
        ({"content_type": "text/plain"}, 415, "unsupported_media_type"),
        ({"content_length": ""}, 411, "length_required"),
        ({"content_length": "abc"}, 411, "length_required"),
        ({"content_length": "999999"}, 413, "payload_too_large"),
        ({"raw_body": b"{not json"}, 400, "invalid_json"),
    ],
)
def test_transport_errors(client, kwargs, expected_status, code) -> None:
    status, _, body = client.request("POST", "/api/v0/quote-requests", make_request(), **kwargs)
    assert status == expected_status and body["error"]["code"] == code


def test_method_and_path_errors(client) -> None:
    status, headers, body = client.request("GET", "/api/v0/quote-requests")
    assert status == 405 and headers["allow"] == "POST"
    status, headers, _ = client.request("POST", "/api/v0/profile", {})
    assert status == 405 and headers["allow"] == "GET, HEAD"
    status, _, body = client.request("GET", "/admin")
    assert status == 404 and body["error"]["code"] == "not_found"


def test_api_catalog_rfc9727(client) -> None:
    status, headers, body = client.request("GET", "/.well-known/api-catalog")
    assert status == 200
    assert headers["content-type"] == 'application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"'
    entry = body["linkset"][0]
    assert entry["anchor"] == "https://anfragen.example/api/v0/quote-requests"
    assert entry["service-desc"][0]["href"].endswith("/api/v0/openapi.json")
    status, headers, body = client.request("HEAD", "/.well-known/api-catalog")
    assert status == 200 and body is None
    assert headers["link"] == '</.well-known/api-catalog>; rel="api-catalog"'


def test_public_profile_marks_self_declared_data(client) -> None:
    status, headers, body = client.request("GET", "/api/v0/profile")
    assert status == 200 and headers["access-control-allow-origin"] == "*"
    assert body["verification"] == {"status": "self_declared"}
    assert body["endpoint"]["receipts_are_quotes"] is False
    assert body["endpoint"]["not_for_emergencies"] is True


def test_jsonld_uses_schema_org_quote_action(client) -> None:
    status, headers, body = client.request("GET", "/api/v0/profile.jsonld")
    assert status == 200 and headers["content-type"].startswith("application/ld+json")
    action = body["potentialAction"]
    assert action["@type"] == "AskAction"
    assert action["target"] == {
        "@type": "EntryPoint",
        "urlTemplate": "https://anfragen.example/api/v0/quote-requests",
        "httpMethod": "POST",
        "contentType": "application/json",
        "encodingType": "application/json",
    }
    assert {offer["itemOffered"]["identifier"] for offer in body["makesOffer"]} == {
        "heating.repair", "heating.maintenance", "plumbing.repair",
    }


def test_jsonld_script_cannot_break_out_of_the_script_tag() -> None:
    data = example_profile_data()
    data["provider"]["description"] = "Beste Firma</script><script>alert(1)</script>"
    snippet = Profile.from_dict(data).jsonld_script("https://anfragen.example")
    assert snippet.count("</script>") == 1


def test_openapi_and_schema_endpoints(client) -> None:
    status, headers, body = client.request("GET", "/api/v0/openapi.json")
    assert status == 200 and body["openapi"] == "3.1.0"
    assert body["components"]["schemas"]["QuoteRequest"] == load_schema("quote-request.schema.json")
    assert set(body["paths"]) == {"/api/v0/profile", "/api/v0/quote-requests", "/api/v0/quote-requests/{request_id}"}
    status, _, schema = client.request("GET", "/api/v0/schemas/quote-request.schema.json")
    assert status == 200 and schema["$id"] == "urn:openquote-lite:schema:0.1:quote-request"
    assert client.request("GET", "/api/v0/schemas/../../config.toml")[0] == 404


def test_cors_preflight_only_for_reading(client) -> None:
    status, headers, _ = client.request("OPTIONS", "/api/v0/profile")
    assert status == 204 and headers["access-control-allow-methods"] == "GET, HEAD, OPTIONS"


def test_proxy_header_only_trusted_when_configured(make_service) -> None:
    service = make_service(Limits(per_client_per_hour=1))
    untrusting = WSGIClient(create_app(service))
    first = untrusting.request("POST", "/api/v0/quote-requests", make_request(), headers={"X-Forwarded-For": "203.0.113.1"})
    spoofed = untrusting.request(
        "POST", "/api/v0/quote-requests", make_request(location={"country": "AT", "postal_code": "1110"}),
        headers={"X-Forwarded-For": "203.0.113.2"},
    )
    assert first[0] == 201 and spoofed[0] == 429  # same REMOTE_ADDR, header ignored

    service2 = make_service(Limits(per_client_per_hour=1))
    trusting = WSGIClient(create_app(service2, trust_proxy=True))
    a = trusting.request("POST", "/api/v0/quote-requests", make_request(), headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.1"})
    b = trusting.request(
        "POST", "/api/v0/quote-requests", make_request(location={"country": "AT", "postal_code": "1110"}),
        headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.2"},
    )
    assert a[0] == 201 and b[0] == 201  # right-most hop identifies the client


def test_internal_errors_do_not_leak(service, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("secret detail /var/lib/openquote")

    monkeypatch.setattr(service, "submit", boom)
    status, _, body = WSGIClient(create_app(service)).request("POST", "/api/v0/quote-requests", make_request())
    assert status == 500 and body["error"]["code"] == "internal_error"
    assert "secret detail" not in json.dumps(body)


def test_real_http_roundtrip(service) -> None:
    server = make_http_server(service, "127.0.0.1", 0, log_requests=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v0/quote-requests"
        data = json.dumps(make_request()).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 201
            receipt = json.loads(response.read())
        assert receipt["is_commitment"] is False
        bad = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as info:
            urllib.request.urlopen(bad, timeout=10)
        assert info.value.code == 422
    finally:
        server.shutdown()
        server.server_close()
