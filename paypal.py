"""Minimal async PayPal REST client (OAuth, Orders v2, Refunds).

Docs: https://developer.paypal.com/docs/api/orders/v2/
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx


class PayPalError(RuntimeError):
    pass


def money(value: float, currency: str) -> dict[str, str]:
    return {"currency_code": currency, "value": f"{value:.2f}"}


class PayPalClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://api-m.sandbox.paypal.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self._token: str | None = None
        self._token_expiry = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        r = await client.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
        )
        if r.status_code != 200:
            raise PayPalError(f"PayPal auth failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3000))
        return self._token

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        if not self.configured:
            raise PayPalError("PayPal is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET.")
        async with httpx.AsyncClient(transport=self._transport, timeout=30) as client:
            token = await self._access_token(client)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": str(uuid.uuid4()),  # idempotency
            }
            r = await client.request(method, f"{self.base_url}{path}", json=json, headers=headers)
            if r.status_code >= 400:
                raise PayPalError(f"PayPal {method} {path} failed ({r.status_code}): {r.text[:500]}")
            return r.json() if r.content else {}

    async def create_order(
        self,
        *,
        reference_id: str,
        item_name: str,
        sku: str,
        unit_price: float,
        quantity: int,
        currency: str,
        return_url: str,
        cancel_url: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        total = unit_price * quantity
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "custom_id": reference_id,
                    "description": (description or item_name)[:127],
                    "amount": {
                        **money(total, currency),
                        "breakdown": {"item_total": money(total, currency)},
                    },
                    "items": [
                        {
                            "name": item_name[:127],
                            "sku": sku[:127],
                            "quantity": str(quantity),
                            "unit_amount": money(unit_price, currency),
                            "category": "PHYSICAL_GOODS",
                        }
                    ],
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": "CartPilot",
                        "user_action": "PAY_NOW",
                        "shipping_preference": "GET_FROM_FILE",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        order = await self._request("POST", "/v2/checkout/orders", json=body)
        return {
            "id": order["id"],
            "status": order.get("status"),
            "approve_url": approve_link(order),
        }

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/checkout/orders/{order_id}")

    async def capture_order(self, order_id: str) -> dict[str, Any]:
        order = await self._request("POST", f"/v2/checkout/orders/{order_id}/capture", json={})
        capture = order["purchase_units"][0]["payments"]["captures"][0]
        return {"status": order.get("status"), "capture_id": capture["id"], "capture_status": capture.get("status")}

    async def refund_capture(self, capture_id: str, note: str | None = None) -> dict[str, Any]:
        body = {"note_to_payer": note[:255]} if note else {}
        r = await self._request("POST", f"/v2/payments/captures/{capture_id}/refund", json=body)
        return {"refund_id": r.get("id"), "status": r.get("status")}


def approve_link(order: dict[str, Any]) -> str | None:
    for link in order.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link.get("href")
    return None
