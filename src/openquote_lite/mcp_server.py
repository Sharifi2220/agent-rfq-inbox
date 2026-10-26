"""MCP binding (optional dependency: ``pip install "openquote-lite[mcp]"``).

Exposes three tools to any MCP client (Claude, ChatGPT apps, IDE agents, ...):

* ``get_provider_profile`` - services, service area, accepted request types
* ``request_quote``        - submit one request for human review
* ``get_request_status``   - status of a submitted request

The tools build the same JSON document an HTTP client would send and pass it
through :meth:`QuoteService.submit`, so MCP requests get identical checks.
Free text written by the requester is never echoed back to the calling agent.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from . import PROTOCOL_VERSION
from .service import QuoteService

INSTRUCTIONS = """\
This server sends quote requests to one service provider on behalf of a person.
Rules for agents:
1. Only call request_quote after the person has seen the request content and asked you to send it.
2. Generate one idempotency_key (e.g. a UUID) per request and reuse it unchanged when you retry.
3. A receipt is never a quote, price, appointment or order confirmation (is_quote=false,
   is_commitment=false). Never tell the person otherwise.
4. This is not an emergency channel. In danger, tell the person to call the local emergency number.
5. Call get_provider_profile first to pick a valid service_id and to check the service area.
"""


def create_mcp_server(service: QuoteService, *, client_key: str = "mcp"):
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp.types import ToolAnnotations
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RuntimeError(
            'The MCP binding needs the MCP Python SDK 2.x: pip install "openquote-lite[mcp]"'
        ) from exc

    def _check(result) -> dict[str, Any]:
        # ToolError keeps its message, so the agent sees the protocol error code and reason.
        if result.status >= 400:
            raise ToolError(json.dumps(result.body, ensure_ascii=False))
        return result.body

    server = MCPServer(
        name=f"openquote-lite-{service.profile.provider_id}",
        title=f"Quote requests to {service.profile.name}",
        instructions=INSTRUCTIONS,
        version=PROTOCOL_VERSION,
    )

    @server.tool(
        name="get_provider_profile",
        description="Services, service area and accepted request types of this provider. Self-declared data.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def get_provider_profile() -> dict[str, Any]:
        return service.public_profile()

    @server.tool(
        name="request_quote",
        description=(
            "Send one quote request to this provider for human review. The result is a receipt, "
            "never a quote or commitment. Requires that the person asked for this request and agreed to be contacted."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def request_quote(
        idempotency_key: str,
        service_id: str,
        summary: str,
        urgency: Literal["as_soon_as_possible", "within_2_weeks", "flexible"],
        country: str,
        postal_code: str,
        wanted: list[Literal["quote", "site_visit", "callback", "availability", "documents"]],
        requester_name: str,
        preferred_contact: Literal["email", "phone"],
        person_requested_this: bool,
        person_agreed_to_be_contacted: bool,
        requester_email: str | None = None,
        requester_phone: str | None = None,
        requester_language: str | None = None,
        requester_is_business: bool | None = None,
        details: str | None = None,
        requirements: list[str] | None = None,
        object_kind: str | None = None,
        object_manufacturer: str | None = None,
        object_model: str | None = None,
        object_year_installed: int | None = None,
        locality: str | None = None,
        earliest_date: str | None = None,
        latest_date: str | None = None,
        timing_notes: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        if not (person_requested_this and person_agreed_to_be_contacted):
            raise ToolError("Not sent: the person must have asked for this request and agreed to be contacted about it.")
        service_part: dict[str, Any] = {"service_id": service_id, "summary": summary, "urgency": urgency}
        if details is not None:
            service_part["details"] = details
        if requirements:
            service_part["requirements"] = requirements
        obj = {
            key: value
            for key, value in (
                ("kind", object_kind),
                ("manufacturer", object_manufacturer),
                ("model", object_model),
                ("year_installed", object_year_installed),
            )
            if value is not None
        }
        if obj:
            service_part["object"] = obj
        location: dict[str, Any] = {"country": country, "postal_code": postal_code}
        if locality is not None:
            location["locality"] = locality
        requester: dict[str, Any] = {"name": requester_name, "preferred_contact": preferred_contact}
        for key, value in (
            ("email", requester_email),
            ("phone", requester_phone),
            ("language", requester_language),
            ("is_business", requester_is_business),
        ):
            if value is not None:
                requester[key] = value
        document: dict[str, Any] = {
            "openquote": PROTOCOL_VERSION,
            "idempotency_key": idempotency_key,
            "service": service_part,
            "location": location,
            "wanted": wanted,
            "requester": requester,
            "submitted_via": {"channel": "agent"},
            "authorization": {"requested_by_person": True, "contact_allowed": True},
        }
        if agent_name is not None:
            document["submitted_via"]["agent_name"] = agent_name
        timing = {
            key: value
            for key, value in (("earliest_date", earliest_date), ("latest_date", latest_date), ("notes", timing_notes))
            if value is not None
        }
        if timing:
            document["timing"] = timing
        raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
        return _check(service.submit(raw, client_key=client_key, channel="mcp"))

    @server.tool(
        name="get_request_status",
        description="Status of a request sent earlier. Never a quote or commitment.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def get_request_status(request_id: str) -> dict[str, Any]:
        return _check(service.status(request_id, client_key=client_key))

    return server
