from __future__ import annotations

import asyncio
import json
import uuid

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from openquote_lite.mcp_server import create_mcp_server  # noqa: E402


def call(server, name: str, arguments: dict | None = None):
    async def run():
        async with Client(server) as client:
            if name == "__list__":
                return await client.list_tools()
            return await client.call_tool(name, arguments or {})

    return asyncio.run(run())


def text_of(result) -> str:
    return "".join(part.text for part in result.content if getattr(part, "text", None))


ARGS = {
    "service_id": "heating.maintenance",
    "summary": "Jährliche Thermenwartung",
    "urgency": "within_2_weeks",
    "country": "AT",
    "postal_code": "1110",
    "wanted": ["quote", "availability"],
    "requester_name": "Erika Beispiel",
    "preferred_contact": "email",
    "requester_email": "erika@example.org",
    "requester_language": "de",
    "person_requested_this": True,
    "person_agreed_to_be_contacted": True,
    "object_kind": "gas_boiler",
    "object_year_installed": 2015,
    "agent_name": "pytest-agent",
}


def test_tools_and_annotations(service) -> None:
    tools = {tool.name: tool for tool in call(create_mcp_server(service), "__list__").tools}
    assert set(tools) == {"get_provider_profile", "request_quote", "get_request_status"}
    assert tools["get_provider_profile"].annotations.read_only_hint is True
    assert tools["request_quote"].annotations.read_only_hint is False
    assert tools["request_quote"].annotations.idempotent_hint is True
    required = set(tools["request_quote"].input_schema["required"])
    assert {"idempotency_key", "person_requested_this", "person_agreed_to_be_contacted"} <= required


def test_request_quote_and_status(service) -> None:
    server = create_mcp_server(service)
    result = call(server, "request_quote", {**ARGS, "idempotency_key": str(uuid.uuid4())})
    assert not result.is_error, text_of(result)
    receipt = json.loads(text_of(result))
    assert receipt["is_quote"] is False and receipt["status"] == "received"
    assert "Thermenwartung" not in text_of(result)  # free text is not echoed
    stored = service.get_request(receipt["request_id"])
    assert stored["channel"] == "mcp"
    assert stored["payload"]["submitted_via"] == {"channel": "agent", "agent_name": "pytest-agent"}
    status = call(server, "get_request_status", {"request_id": receipt["request_id"]})
    assert json.loads(text_of(status))["status"] == "received"


def test_request_without_the_persons_confirmation_is_refused(service) -> None:
    result = call(create_mcp_server(service), "request_quote", {**ARGS, "idempotency_key": str(uuid.uuid4()), "person_agreed_to_be_contacted": False})
    assert result.is_error
    assert service.list_requests() == []


def test_protocol_errors_reach_the_agent(service) -> None:
    result = call(create_mcp_server(service), "request_quote", {**ARGS, "idempotency_key": str(uuid.uuid4()), "postal_code": "1200"})
    assert result.is_error and "outside_service_area" in text_of(result)


def test_profile_tool(service) -> None:
    result = call(create_mcp_server(service), "get_provider_profile")
    profile = json.loads(text_of(result))
    assert profile["verification"]["status"] == "self_declared"
