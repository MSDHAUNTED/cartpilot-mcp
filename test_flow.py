"""End-to-end tool flow against the demo catalog with PayPal sandbox calls mocked by respx."""
import json

import httpx
import pytest
import respx
from fastmcp import Client

from cartpilot.channel3 import Channel3Client
from cartpilot.config import Settings
from cartpilot.paypal import PayPalClient
from cartpilot.server import build_server
from cartpilot.store import Store

PP = "https://api-m.sandbox.paypal.com"


def settings(tmp_path):
    return Settings("id", "secret", PP, "", "USD", "http://localhost:8000", str(tmp_path / "t.db"), 200, 400)


def data(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.fixture
def server(tmp_path):
    s = settings(tmp_path)
    return build_server(s, Store(s.db_path), Channel3Client("", "USD"), PayPalClient("id", "secret", PP))


@respx.mock
async def test_search_compare_buy_capture_refund(server):
    respx.post(f"{PP}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600}))
    respx.post(f"{PP}/v2/checkout/orders").mock(return_value=httpx.Response(201, json={
        "id": "ORDER1", "status": "PAYER_ACTION_REQUIRED",
        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}],
    }))
    respx.get(f"{PP}/v2/checkout/orders/ORDER1").mock(return_value=httpx.Response(200, json={"id": "ORDER1", "status": "APPROVED"}))
    respx.post(f"{PP}/v2/checkout/orders/ORDER1/capture").mock(return_value=httpx.Response(201, json={
        "id": "ORDER1", "status": "COMPLETED",
        "purchase_units": [{"payments": {"captures": [{"id": "CAP1", "status": "COMPLETED"}]}}],
    }))
    respx.post(f"{PP}/v2/payments/captures/CAP1/refund").mock(return_value=httpx.Response(201, json={"id": "REF1", "status": "COMPLETED"}))

    async with Client(server) as c:
        found = data(await c.call_tool("search_products", {"query": "noise cancelling headphones", "max_price": 200}))
        ids = [p["product_id"] for p in found["products"]]
        assert "demo_hp1" in ids and "demo_hp4" not in ids  # 299 is over max_price

        cmp = data(await c.call_tool("compare_products", {"product_ids": ids, "must_have": ["active noise cancelling", "40-hour battery"]}))
        assert cmp["recommended"] == "demo_hp1"

        prop = data(await c.call_tool("propose_purchase", {"product_id": "demo_hp1"}))
        assert prop["allowed"] is True
        pur = prop["purchase"]
        assert pur["approve_url"].endswith("ORDER1") and pur["status"] == "AWAITING_APPROVAL"

        done = data(await c.call_tool("check_purchase", {"purchase_id": pur["id"]}))
        assert done["purchase"]["status"] == "COMPLETED" and done["purchase"]["capture_id"] == "CAP1"

        pol = data(await c.call_tool("get_spending_policy", {}))
        assert pol["spent_this_month"] == 129.0

        ref = data(await c.call_tool("refund_purchase", {"purchase_id": pur["id"], "reason": "changed mind"}))
        assert ref["purchase"]["status"] == "REFUNDED"


async def test_policy_blocks_before_paypal_is_called(server):
    async with Client(server) as c:
        await c.call_tool("search_products", {"query": "headphones vape"})
        over = data(await c.call_tool("propose_purchase", {"product_id": "demo_hp4"}))  # 299 > 200 per-order
        assert over["allowed"] is False and "per-order limit" in over["violations"][0]

        await c.call_tool("set_spending_policy", {"blocked_categories": ["vapes"]})
        blocked = data(await c.call_tool("propose_purchase", {"product_id": "demo_vape1"}))
        assert blocked["allowed"] is False

        hist = data(await c.call_tool("list_purchases", {}))
        assert all(p["status"] == "BLOCKED_BY_POLICY" for p in hist["purchases"])
