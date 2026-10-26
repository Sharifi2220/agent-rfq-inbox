"""Provider profile: the single source of truth for one OpenQuote Lite endpoint.

From one profile file the endpoint derives
* the public profile document (``GET /api/v0/profile``),
* a schema.org JSON-LD snippet for the provider's website, using the existing
  ``AskAction`` / ``EntryPoint`` vocabulary instead of a new format,
* the RFC 9727 API catalog (``/.well-known/api-catalog``).

Everything in a profile is self-declared. Published documents therefore carry
``"verification": {"status": "self_declared"}``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION, __version__
from .schema_engine import load_schema, validate

PROFILE_SCHEMA = "provider-profile.schema.json"
API_PREFIX = "/api/v0"


class ProfileError(ValueError):
    """The provider profile file is missing or invalid."""


def _compact_postal(code: str) -> str:
    return code.replace(" ", "").replace("-", "").upper()


@dataclass(frozen=True)
class Profile:
    data: dict[str, Any]

    # -- loading ---------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        issues = validate(data, load_schema(PROFILE_SCHEMA))
        if issues:
            text = "; ".join(f"{i.path or '/'}: {i.message}" for i in issues[:20])
            raise ProfileError(f"invalid provider profile: {text}")
        ids = [service["id"] for service in data["services"]]
        if len(ids) != len(set(ids)):
            raise ProfileError("invalid provider profile: service ids must be unique")
        for service in data["services"]:
            hint = service.get("price_hint")
            if hint and "min" in hint and "max" in hint and hint["min"] > hint["max"]:
                raise ProfileError(f"invalid provider profile: price_hint min > max for {service['id']!r}")
        area = data["service_area"]
        if not area.get("postal_codes") and not area.get("postal_code_prefixes"):
            raise ProfileError("invalid provider profile: service_area needs postal_codes or postal_code_prefixes")
        return cls(copy.deepcopy(data))

    @classmethod
    def from_file(cls, path: str | Path) -> Profile:
        try:
            text = Path(path).read_text("utf-8")
            data = json.loads(text)
        except FileNotFoundError:
            raise ProfileError(f"profile file not found: {path}") from None
        except (OSError, ValueError) as exc:
            raise ProfileError(f"cannot read profile {path}: {exc}") from None
        if not isinstance(data, dict):
            raise ProfileError("invalid provider profile: top level must be an object")
        return cls.from_dict(data)

    # -- queries -----------------------------------------------------------
    @property
    def provider_id(self) -> str:
        return self.data["provider"]["id"]

    @property
    def name(self) -> str:
        return self.data["provider"]["name"]

    @property
    def emergency_note(self) -> str | None:
        return self.data["provider"].get("emergency_note")

    @property
    def response_time_hint(self) -> str | None:
        return self.data["request_policy"].get("response_time_hint")

    def service_ids(self) -> list[str]:
        return [service["id"] for service in self.data["services"]]

    def offers(self, service_id: str) -> bool:
        return service_id in self.service_ids()

    def service_name(self, service_id: str) -> str:
        for service in self.data["services"]:
            if service["id"] == service_id:
                return service["name"]
        return service_id

    def accepts(self) -> set[str]:
        return set(self.data["request_policy"]["accepts"])

    def covers(self, country: str, postal_code: str) -> bool:
        area = self.data["service_area"]
        if country.upper() != area["country"]:
            return False
        code = _compact_postal(postal_code)
        if code in {_compact_postal(c) for c in area.get("postal_codes", [])}:
            return True
        return any(code.startswith(_compact_postal(p)) for p in area.get("postal_code_prefixes", []))

    # -- published documents -----------------------------------------------
    def public_document(self, base_url: str, accepting_requests: bool) -> dict[str, Any]:
        document = copy.deepcopy(self.data)
        document["verification"] = {"status": "self_declared"}
        document["endpoint"] = {
            "quote_requests": f"{base_url}{API_PREFIX}/quote-requests",
            "accepting_requests": accepting_requests,
            "request_schema": f"{base_url}{API_PREFIX}/schemas/quote-request.schema.json",
            "openapi": f"{base_url}{API_PREFIX}/openapi.json",
            "not_for_emergencies": True,
            "receipts_are_quotes": False,
        }
        document["software"] = {"name": "OpenQuote Lite", "version": __version__}
        return document

    def jsonld(self, base_url: str) -> dict[str, Any]:
        provider = self.data["provider"]
        offers = []
        for service in self.data["services"]:
            item: dict[str, Any] = {"@type": "Service", "identifier": service["id"], "name": service["name"]}
            if "description" in service:
                item["description"] = service["description"]
            offer: dict[str, Any] = {"@type": "Offer", "itemOffered": item}
            hint = service.get("price_hint")
            if hint:
                spec: dict[str, Any] = {
                    "@type": "PriceSpecification",
                    "priceCurrency": hint["currency"],
                    "description": "Indicative, non-binding price range ({}). Not a quote.".format(hint["unit"].replace("_", " ")),
                }
                if "min" in hint:
                    spec["minPrice"] = hint["min"]
                if "max" in hint:
                    spec["maxPrice"] = hint["max"]
                offer["priceSpecification"] = spec
            offers.append(offer)

        area = self.data["service_area"]
        served: list[Any] = [
            {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": area["country"], "postalCode": code}}
            for code in area.get("postal_codes", [])
        ]
        for prefix in area.get("postal_code_prefixes", []):
            served.append(f"{area['country']} postal codes starting with {prefix}")

        document: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "identifier": provider["id"],
            "name": provider["name"],
            "areaServed": served,
            "makesOffer": offers,
            "potentialAction": {
                "@type": "AskAction",
                "name": f"Request a quote (OpenQuote Lite {PROTOCOL_VERSION})",
                "description": (
                    "Machine-readable quote request endpoint. Every request is reviewed by a person. "
                    "Receipts are not quotes, prices, appointments or order confirmations. "
                    "Not an emergency channel."
                ),
                "target": {
                    "@type": "EntryPoint",
                    "urlTemplate": f"{base_url}{API_PREFIX}/quote-requests",
                    "httpMethod": "POST",
                    "contentType": "application/json",
                    "encodingType": "application/json",
                },
            },
        }
        for source, target in (("legal_name", "legalName"), ("description", "description"), ("website", "url")):
            if source in provider:
                document[target] = provider[source]
        if "languages" in provider:
            document["knowsLanguage"] = provider["languages"]
        return document

    def jsonld_script(self, base_url: str) -> str:
        body = json.dumps(self.jsonld(base_url), ensure_ascii=False, indent=2)
        # HTML parses end tags case-insensitively. Escape every '<' so profile
        # text cannot close the script element with e.g. '</SCRIPT>'.
        body = body.replace("<", "\\u003c")
        return f'<script type="application/ld+json">\n{body}\n</script>\n'

    def api_catalog(self, base_url: str) -> dict[str, Any]:
        api = f"{base_url}{API_PREFIX}"
        return {
            "linkset": [
                {
                    "anchor": f"{api}/quote-requests",
                    "service-desc": [{"href": f"{api}/openapi.json", "type": "application/openapi+json"}],
                    "service-meta": [{"href": f"{api}/profile", "type": "application/json"}],
                    "status": [{"href": f"{api}/health", "type": "application/json"}],
                }
            ]
        }
