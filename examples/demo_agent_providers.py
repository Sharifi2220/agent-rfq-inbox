"""End-to-end demo: one requesting agent, four fictional providers.

Runs entirely on this machine with fictional data:

1. starts four OpenQuote Lite endpoints on free local ports,
2. a minimal "agent" reads each public profile and only contacts providers
   whose profile covers the service and the postal code,
3. it sends the same request (one idempotency key per provider),
4. provider A reviews its inbox and plans a follow-up,
5. the agent polls the status and prints a comparison.

Usage:  pip install -e .   then   python examples/demo_agent_providers.py
"""

from __future__ import annotations

import copy
import json
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta
from importlib import resources
from pathlib import Path

from openquote_lite.http_api import make_http_server
from openquote_lite.profile import Profile
from openquote_lite.service import QuoteService
from openquote_lite.store import Store


def base_profile() -> dict:
    text = resources.files("openquote_lite").joinpath("examples", "provider-profile.example.json").read_text("utf-8")
    return json.loads(text)


def variant(provider_id: str, name: str, postal_codes: list[str]) -> dict:
    profile = copy.deepcopy(base_profile())
    profile["provider"]["id"] = provider_id
    profile["provider"]["name"] = name
    profile["provider"]["legal_name"] = f"{name} (fiktiver Beispielbetrieb)"
    profile["service_area"]["postal_codes"] = postal_codes
    return profile


def start_provider(workdir: Path, profile_data: dict) -> tuple[QuoteService, object, str]:
    store = Store(workdir / profile_data["provider"]["id"] / "openquote.sqlite3")
    # Placeholder base URL; replaced below once the port is known.
    service = QuoteService(store, Profile.from_dict(profile_data), uuid.uuid4().hex.encode(), base_url="http://127.0.0.1")
    server = make_http_server(service, "127.0.0.1", 0, log_requests=False)
    url = f"http://127.0.0.1:{server.server_port}"
    service.base_url = url
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return service, server, url


def http(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        providers = [
            start_provider(workdir, variant("beispiel-haustechnik", "Beispiel Haustechnik", ["1100", "1110"])),
            start_provider(workdir, variant("muster-waermetechnik", "Muster Wärmetechnik", ["1100", "1120"])),
            start_provider(workdir, variant("west-heizung", "West Heizung", ["1140", "1150"])),
            start_provider(workdir, variant("nord-installationen", "Nord Installationen", ["1100", "1210"])),
        ]
        providers[3][0].pause(actor="demo", message="Betriebsurlaub")

        need = {"service_id": "heating.maintenance", "country": "AT", "postal_code": "1100"}
        print("Agent task: ask local providers for a gas boiler service in 1100 Wien\n")

        receipts = []
        for service, _server, url in providers:
            status, profile = http("GET", f"{url}/api/v0/profile")
            name = profile["provider"]["name"]
            offered = {s["id"] for s in profile["services"]}
            area = profile["service_area"]
            covers = need["postal_code"] in area.get("postal_codes", []) and area["country"] == need["country"]
            if need["service_id"] not in offered or not covers:
                print(f"- {name}: skipped (profile does not cover the service area)")
                continue
            if not profile["endpoint"]["accepting_requests"]:
                print(f"- {name}: profile says intake is paused; trying anyway to show the answer")
            request = {
                "openquote": "0.1",
                "idempotency_key": str(uuid.uuid4()),
                "service": {
                    "service_id": need["service_id"],
                    "summary": "Jährliche Wartung der Gastherme",
                    "details": "Gerät läuft, letzte Wartung vor 14 Monaten.",
                    "urgency": "within_2_weeks",
                    "object": {"kind": "gas_boiler", "manufacturer": "Beispielwerk", "model": "BW 24", "year_installed": 2015},
                },
                "location": {"country": "AT", "postal_code": "1100", "locality": "Wien"},
                "timing": {
                    "earliest_date": (date.today() + timedelta(days=3)).isoformat(),
                    "latest_date": (date.today() + timedelta(days=21)).isoformat(),
                },
                "wanted": ["quote", "availability"],
                "requester": {"name": "Erika Beispiel", "email": "erika@example.org", "preferred_contact": "email", "language": "de"},
                "submitted_via": {"channel": "agent", "agent_name": "demo-agent"},
                "authorization": {"requested_by_person": True, "contact_allowed": True},
            }
            status, body = http("POST", f"{url}/api/v0/quote-requests", request)
            if status in (200, 201):
                print(f"- {name}: HTTP {status}, receipt {body['request_id']} (is_quote={body['is_quote']})")
                receipts.append((service, name, body))
            else:
                print(f"- {name}: HTTP {status}, {body['error']['code']}: {body['error']['message']}")

        # Provider A works its inbox: a person decides to follow up.
        service_a, name_a, receipt_a = receipts[0]
        service_a.set_status(receipt_a["request_id"], "in_review", actor="demo:office")
        service_a.set_status(receipt_a["request_id"], "follow_up_planned", actor="demo:office")

        print("\nAgent polls the status pages:")
        for _service, name, receipt in receipts:
            status, body = http("GET", receipt["status_url"])
            print(f"- {name}: {body['status']} - {body['message']}")

        print("\nAudit chains:", ", ".join(
            f"{name}: {'OK' if service.audit_verify().ok else 'BROKEN'}" for service, name, _ in receipts
        ))
        for _service, server, _url in providers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
