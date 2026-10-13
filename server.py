"""CartPilot MCP server.

Flow:  search_products -> compare_products -> propose_purchase (policy check + PayPal order)
       -> user approves on PayPal -> check_purchase (capture) -> list_purchases / refund_purchase
"""
from __future__ import annotations

import argparse
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

from . import policy as policy_mod
from .channel3 import Channel3Client
from .config import Settings, load_settings
from .paypal import PayPalClient, PayPalError
from .ranking import best_offer, compare
from .store import BLOCKED, CANCELLED, COMPLETED, FAILED, PENDING, REFUNDED, Store

INSTRUCTIONS = """CartPilot lets you shop for the user and pay with PayPal.
Rules you must follow:
1. Search, then compare. Show the user a short comparison and your recommendation before buying.
2. Only call propose_purchase after the user clearly says which product to buy.
3. propose_purchase returns a PayPal approval link. Give it to the user; you can never pay on their behalf.
4. After the user says they approved, call check_purchase to capture payment and confirm.
5. If a purchase is blocked by policy, explain why. Never try to split an order to get around a limit.
"""


def _public(purchase: dict[str, Any] | None) -> dict[str, Any] | None:
    if not purchase:
        return None
    keys = [
        "id", "status", "title", "merchant", "quantity", "unit_price", "amount", "currency",
        "paypal_order_id", "capture_id", "approve_url", "note", "created_at", "updated_at",
    ]
    return {k: purchase.get(k) for k in keys}


def build_server(
    settings: Settings | None = None,
    store: Store | None = None,
    channel3: Channel3Client | None = None,
    paypal: PayPalClient | None = None,
) -> FastMCP:
    settings = settings or load_settings()
    store = store or Store(settings.db_path)
    channel3 = channel3 or Channel3Client(settings.channel3_api_key, settings.currency)
    paypal = paypal or PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url)

    if store.get_policy() is None:
        store.save_policy(
            policy_mod.default_policy(settings.default_per_order_limit, settings.default_monthly_limit, settings.currency)
        )

    mcp = FastMCP("CartPilot", instructions=INSTRUCTIONS)

    # ------------------------------------------------------------------ discovery
    @mcp.tool
    async def search_products(
        query: str,
        max_price: float | None = None,
        min_price: float | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Search products across online stores (Channel3). Returns products with their offers per merchant."""
        products = await channel3.search(query, min_price=min_price, max_price=max_price, limit=limit)
        store.cache_products(products)
        summary = []
        for p in products:
            o = best_offer(p)
            summary.append(
                {
                    "product_id": p["id"],
                    "title": p["title"],
                    "brand": p.get("brand"),
                    "best_price": o["price"] if o else None,
                    "currency": o["currency"] if o else None,
                    "merchant": o.get("merchant") if o else None,
                    "in_stock": o.get("in_stock") if o else False,
                    "offers": len(p["offers"]),
                    "key_features": p.get("key_features", [])[:4],
                    "image": p.get("image"),
                }
            )
        return {
            "source": "demo catalog" if channel3.demo else "Channel3",
            "count": len(summary),
            "products": summary,
        }

    @mcp.tool
    async def get_product(product_id: str) -> dict[str, Any]:
        """Full details and every merchant offer for a product returned by search_products."""
        p = store.get_product(product_id)
        if not p:
            return {"error": f"Unknown product_id {product_id}. Run search_products first."}
        return p

    @mcp.tool
    async def compare_products(
        product_ids: list[str],
        must_have: list[str] | None = None,
        budget: float | None = None,
    ) -> dict[str, Any]:
        """Rank 2-10 products by price, must-have features, stock and discount. Returns a recommendation and reason."""
        products = [p for pid in product_ids if (p := store.get_product(pid))]
        missing = [pid for pid in product_ids if not store.get_product(pid)]
        result = compare(products, must_have=must_have, budget=budget)
        if missing:
            result["unknown_product_ids"] = missing
        return result

    # ------------------------------------------------------------------ guardrails
    @mcp.tool
    async def get_spending_policy() -> dict[str, Any]:
        """Current spending rules plus how much has been spent and is pending this month."""
        pol = store.get_policy()
        spent = store.spent_this_month(pol["currency"])
        pending = store.pending_total(pol["currency"])
        return {
            "policy": pol,
            "spent_this_month": round(spent, 2),
            "awaiting_approval": round(pending, 2),
            "remaining_this_month": round(max(pol["monthly_limit"] - spent - pending, 0), 2),
        }

    @mcp.tool
    async def set_spending_policy(
        per_order_limit: float | None = None,
        monthly_limit: float | None = None,
        blocked_categories: list[str] | None = None,
        max_quantity: int | None = None,
    ) -> dict[str, Any]:
        """Update spending rules. Only call when the user explicitly asks to change their limits."""
        pol = store.get_policy()
        if per_order_limit is not None:
            pol["per_order_limit"] = max(float(per_order_limit), 0)
        if monthly_limit is not None:
            pol["monthly_limit"] = max(float(monthly_limit), 0)
        if blocked_categories is not None:
            pol["blocked_categories"] = [c.strip() for c in blocked_categories if c.strip()]
        if max_quantity is not None:
            pol["max_quantity"] = max(int(max_quantity), 1)
        store.save_policy(pol)
        return {"updated": True, "policy": pol}

    # ------------------------------------------------------------------ checkout
    @mcp.tool
    async def propose_purchase(product_id: str, quantity: int = 1, merchant: str | None = None) -> dict[str, Any]:
        """Check the spending policy and, if allowed, create a PayPal order the USER must approve.
        Returns an approval link. No money moves until the user approves on PayPal."""
        p = store.get_product(product_id)
        if not p:
            return {"error": f"Unknown product_id {product_id}. Run search_products first."}
        offer = best_offer(p, merchant)
        if not offer:
            return {"error": "No offer available for this product" + (f" at {merchant}" if merchant else "") + "."}
        if not offer.get("in_stock"):
            return {"error": f"{p['title']} is out of stock at {offer.get('merchant')}."}

        quantity = max(int(quantity), 1)
        amount = round(offer["price"] * quantity, 2)
        pol = store.get_policy()
        base = dict(
            product_id=p["id"], title=p["title"], category=p.get("category"), merchant=offer.get("merchant"),
            merchant_url=offer.get("url"), unit_price=offer["price"], quantity=quantity, amount=amount,
            currency=offer["currency"],
        )
        violations = policy_mod.check(
            pol, amount=amount, quantity=quantity, currency=offer["currency"], category=p.get("category"),
            title=p["title"], spent_this_month=store.spent_this_month(pol["currency"]),
            pending=store.pending_total(pol["currency"]),
        )
        if violations:
            rec = store.create_purchase(**base, status=BLOCKED, note=" ".join(violations))
            return {"allowed": False, "violations": violations, "purchase": _public(rec)}

        rec = store.create_purchase(**base, status=PENDING)
        try:
            order = await paypal.create_order(
                reference_id=rec["id"],
                item_name=p["title"],
                sku=p["id"],
                unit_price=offer["price"],
                quantity=quantity,
                currency=offer["currency"],
                return_url=f"{settings.public_base_url}/paypal/return",
                cancel_url=f"{settings.public_base_url}/paypal/cancel",
                description=f"{p['title']} via {offer.get('merchant')}",
            )
        except PayPalError as e:
            store.update_purchase(rec["id"], status=FAILED, note=str(e))
            return {"allowed": True, "error": str(e)}

        rec = store.update_purchase(rec["id"], paypal_order_id=order["id"], approve_url=order["approve_url"])
        return {
            "allowed": True,
            "purchase": _public(rec),
            "next_step": "Send the user the approve_url. After they approve on PayPal, call check_purchase.",
        }

    async def _settle(purchase: dict[str, Any]) -> dict[str, Any]:
        """Pull PayPal order status; capture if the buyer approved. Re-checks policy before capture."""
        if purchase["status"] != PENDING:
            return purchase
        order = await paypal.get_order(purchase["paypal_order_id"])
        status = order.get("status")
        if status == "APPROVED":
            pol = store.get_policy()
            violations = policy_mod.check(
                pol, amount=purchase["amount"], quantity=purchase["quantity"], currency=purchase["currency"],
                category=purchase.get("category"), title=purchase["title"],
                spent_this_month=store.spent_this_month(pol["currency"]),
            )
            if violations:
                return store.update_purchase(purchase["id"], status=BLOCKED, note=" ".join(violations))
            cap = await paypal.capture_order(purchase["paypal_order_id"])
            if cap["status"] == "COMPLETED":
                return store.update_purchase(purchase["id"], status=COMPLETED, capture_id=cap["capture_id"])
            return store.update_purchase(purchase["id"], note=f"Capture status: {cap['capture_status']}")
        if status == "COMPLETED":
            cap = order["purchase_units"][0]["payments"]["captures"][0]
            return store.update_purchase(purchase["id"], status=COMPLETED, capture_id=cap["id"])
        if status == "VOIDED":
            return store.update_purchase(purchase["id"], status=CANCELLED, note="Order voided or expired on PayPal.")
        return store.update_purchase(purchase["id"], note=f"PayPal order status: {status}")

    @mcp.tool
    async def check_purchase(purchase_id: str) -> dict[str, Any]:
        """Check a purchase. If the user approved on PayPal, capture the payment and confirm the order."""
        rec = store.get_purchase(purchase_id)
        if not rec:
            return {"error": f"Unknown purchase {purchase_id}."}
        try:
            rec = await _settle(rec)
        except PayPalError as e:
            return {"error": str(e), "purchase": _public(rec)}
        out: dict[str, Any] = {"purchase": _public(rec)}
        if rec["status"] == COMPLETED:
            out["fulfilment_link"] = rec["merchant_url"]
            out["message"] = f"Paid {rec['amount']:.2f} {rec['currency']} for {rec['title']}."
        elif rec["status"] == PENDING:
            out["message"] = "Still waiting for the user to approve on PayPal."
        return out

    @mcp.tool
    async def cancel_purchase(purchase_id: str) -> dict[str, Any]:
        """Cancel a purchase that has not been paid yet."""
        rec = store.get_purchase(purchase_id)
        if not rec:
            return {"error": f"Unknown purchase {purchase_id}."}
        if rec["status"] != PENDING:
            return {"error": f"Only purchases awaiting approval can be cancelled (status is {rec['status']})."}
        return {"purchase": _public(store.update_purchase(purchase_id, status=CANCELLED, note="Cancelled by user."))}

    @mcp.tool
    async def refund_purchase(purchase_id: str, reason: str | None = None) -> dict[str, Any]:
        """Refund a completed purchase in full. Only call when the user explicitly asks for a refund."""
        rec = store.get_purchase(purchase_id)
        if not rec:
            return {"error": f"Unknown purchase {purchase_id}."}
        if rec["status"] != COMPLETED or not rec.get("capture_id"):
            return {"error": f"Only completed purchases can be refunded (status is {rec['status']})."}
        try:
            r = await paypal.refund_capture(rec["capture_id"], reason)
        except PayPalError as e:
            return {"error": str(e)}
        rec = store.update_purchase(purchase_id, status=REFUNDED, note=f"Refund {r['refund_id']} {r['status']}")
        return {"purchase": _public(rec), "refund": r}

    @mcp.tool
    async def list_purchases(limit: int = 10) -> dict[str, Any]:
        """Purchase history and audit trail, newest first (includes blocked and cancelled attempts)."""
        return {"purchases": [_public(p) for p in store.list_purchases(limit)]}

    # ------------------------------------------------------------------ PayPal redirect pages (HTTP mode)
    @mcp.custom_route("/paypal/return", methods=["GET"])
    async def paypal_return(request: Request) -> HTMLResponse:
        order_id = request.query_params.get("token", "")
        rec = store.get_purchase_by_order(order_id)
        if not rec:
            return HTMLResponse(_page("Order not found", "Go back to Claude and ask it to check your purchase."), 404)
        try:
            rec = await _settle(rec)
        except PayPalError as e:
            return HTMLResponse(_page("Payment issue", str(e)), 502)
        if rec["status"] == COMPLETED:
            body = f"Paid {rec['amount']:.2f} {rec['currency']} for {rec['title']}. You can return to Claude."
            return HTMLResponse(_page("Payment complete", body))
        return HTMLResponse(_page("Not completed", f"Status: {rec['status']}. {rec.get('note') or ''}"))

    @mcp.custom_route("/paypal/cancel", methods=["GET"])
    async def paypal_cancel(request: Request) -> HTMLResponse:
        rec = store.get_purchase_by_order(request.query_params.get("token", ""))
        if rec and rec["status"] == PENDING:
            store.update_purchase(rec["id"], status=CANCELLED, note="Buyer cancelled on PayPal.")
        return HTMLResponse(_page("Payment cancelled", "Nothing was charged. You can return to Claude."))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> HTMLResponse:
        return HTMLResponse("ok")

    return mcp


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{title}</title><body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1>{title}</h1><p>{body}</p></body>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CartPilot MCP server")
    parser.add_argument("--http", action="store_true", help="Serve over streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = build_server()
    if args.http:
        server.run(transport="http", host=args.host, port=args.port)
    else:
        server.run()


if __name__ == "__main__":
    main()
