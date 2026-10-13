"""Deterministic product comparison so the agent's recommendation is explainable and repeatable."""
from __future__ import annotations

from typing import Any


def best_offer(product: dict[str, Any], merchant: str | None = None) -> dict[str, Any] | None:
    offers = product.get("offers") or []
    if merchant:
        offers = [o for o in offers if (o.get("merchant") or "").lower() == merchant.lower()]
    in_stock = [o for o in offers if o.get("in_stock")]
    pool = in_stock or offers
    return min(pool, key=lambda o: o["price"]) if pool else None


def compare(
    products: list[dict[str, Any]],
    must_have: list[str] | None = None,
    budget: float | None = None,
) -> dict[str, Any]:
    """Score products 0-100 on price (40), feature match (30), availability (15), discount (15)."""
    must_have = [m.lower() for m in (must_have or []) if m.strip()]
    rows = []
    for p in products:
        offer = best_offer(p)
        if not offer:
            continue
        text = " ".join([p["title"], p.get("description", ""), " ".join(p.get("key_features", []))]).lower()
        matched = [m for m in must_have if m in text]
        compare_at = offer.get("compare_at_price") or 0
        discount = (compare_at - offer["price"]) / compare_at if compare_at and compare_at > offer["price"] else 0.0
        rows.append(
            {
                "product_id": p["id"],
                "title": p["title"],
                "brand": p.get("brand"),
                "price": offer["price"],
                "currency": offer["currency"],
                "merchant": offer.get("merchant"),
                "in_stock": offer.get("in_stock", False),
                "discount_pct": round(discount * 100, 1),
                "features_matched": matched,
                "features_missing": [m for m in must_have if m not in matched],
                "over_budget": budget is not None and offer["price"] > budget,
            }
        )
    if not rows:
        return {"ranked": [], "recommended": None, "reason": "No comparable offers found."}

    prices = [r["price"] for r in rows]
    lo, hi = min(prices), max(prices)
    for r in rows:
        price_score = 1.0 if hi == lo else (hi - r["price"]) / (hi - lo)
        feature_score = len(r["features_matched"]) / len(must_have) if must_have else 1.0
        score = 40 * price_score + 30 * feature_score + 15 * r["in_stock"] + 15 * min(r["discount_pct"] / 30, 1)
        if r["features_missing"]:
            score -= 30  # a product missing a must-have should not win on price alone
        if r["over_budget"]:
            score -= 50
        r["score"] = round(score, 1)

    rows.sort(key=lambda r: -r["score"])
    top = rows[0]
    reason = (
        f"{top['title']} scores highest: {top['price']:.2f} {top['currency']} at {top['merchant']}"
        + (f", matches {len(top['features_matched'])}/{len(must_have)} must-haves" if must_have else "")
        + (", in stock" if top["in_stock"] else ", currently out of stock")
        + (f", {top['discount_pct']}% off" if top["discount_pct"] else "")
        + "."
    )
    return {
        "ranked": rows,
        "recommended": top["product_id"],
        "reason": reason,
        "weights": {"price": 40, "must_have_features": 30, "in_stock": 15, "discount": 15, "missing_must_have_penalty": -30, "over_budget_penalty": -50},
    }
