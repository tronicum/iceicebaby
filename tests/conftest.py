"""A fake iceportal.de: serves recorded fixtures (tests/fixtures/*.json) via httpx.MockTransport.

The fixtures are snapshots of the real API (captured on an ICE on 2026-10-11, image URLs, positions
and order data stripped), so the tests exercise the server against real response shapes without
needing the train WiFi. `tests/test_live.py` checks the snapshots still match the live API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from iceicebaby import server

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakePortal:
    """Mutable fake backend. Tweak the attributes in a test to simulate other situations."""

    def __init__(self) -> None:
        self.products: list[dict[str, Any]] = load("products.json")
        self.availabilities: list[dict[str, Any]] = load("availabilities.json")
        self.config: dict[str, Any] = load("config.json")
        self.trip: dict[str, Any] = load("trip.json")
        self.service_status: dict[str, Any] = {"bapServiceStatus": "ACTIVE"}
        self.order_id = "11111111-2222-3333-4444-555555555555"
        self.order_response: dict[str, Any] = {
            "id": self.order_id,
            "createdAt": "2026-10-11T10:09:47.236082+02:00",
            "status": {"statusType": "OPEN", "description": "<p>Wir prüfen Ihre Bestellanfrage.</p>"},
        }
        self.order_status: dict[str, Any] = {"statusType": "ACCEPTED"}
        self.order_post_status = 200
        self.down = False  # simulate "not on the train WiFi"
        self.post_down = False  # connection drops exactly while the order is sent
        self.posted_orders: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str]] = []

    def set_available(self, ecm_id: int, available: bool = True) -> None:
        for a in self.availabilities:
            if a["ecmId"] == ecm_id:
                a["status"] = "AVAILABLE" if available else "UNAVAILABLE"
                a["visible"] = available
                return
        raise KeyError(ecm_id)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if self.down:
            raise httpx.ConnectError("no route to host", request=request)
        if request.method == "POST" and path == "/bap/api/orders":
            if self.post_down:
                raise httpx.ReadTimeout("timed out", request=request)
            self.posted_orders.append(json.loads(request.content))
            if self.order_post_status != 200:
                return httpx.Response(self.order_post_status, text="nope")
            return httpx.Response(200, json=self.order_response)
        routes = {
            "/bap/api/products": self.products,
            "/bap/api/availabilities": self.availabilities,
            "/bap/api/config": self.config,
            "/bap/api/bap-service-status": self.service_status,
            "/api1/rs/tripInfo/trip": self.trip,
            f"/bap/api/orders/{self.order_id}/status": self.order_status,
        }
        if request.method == "GET" and path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, text="not found")


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch) -> FakePortal:
    fake = FakePortal()
    client = httpx.AsyncClient(base_url=server.BASE_URL, transport=httpx.MockTransport(fake.handler))
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_last_order_id", None)
    server._cart.clear()
    server._location.clear()
    return fake


@pytest.fixture
async def mcp(portal: FakePortal):
    """An in-memory MCP client talking to the real server module (tools called like a real client would)."""
    async with Client(server.mcp) as c:
        yield c


async def call(mcp: Client, tool: str, **args: Any) -> Any:
    return (await mcp.call_tool(tool, args)).data


async def call_err(mcp: Client, tool: str, **args: Any) -> str:
    """Call a tool that must fail; returns the error message."""
    with pytest.raises(ToolError) as e:
        await mcp.call_tool(tool, args)
    return str(e.value)
