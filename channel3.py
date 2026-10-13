"""Channel3 product search client, normalised to a small, agent-friendly shape.

API reference: https://docs.trychannel3.com/api-reference/v1/search
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

import httpx

API_BASE = "https://api.trychannel3.com/v1"


def _best_image(images: list[dict] | None) -> str | None:
    if not images:
        return None
    main = next((i for i in images if i.get("is_main_image")), images[0])
    return main.get("cleaned_url") or main.get("url")


def normalize_product(p: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Channel3 Product to the fields CartPilot needs."""
    offers = []
    for o in p.get("offers") or []:
        price = o.get("price") or {}
        offers.append(
            {
                "merchant": o.get("domain"),
                "url": o.get("url"),
                "price": float(price.get("price") or 0),
                "compare_at_price": price.get("compare_at_price"),
                "currency": price.get("currency") or "USD",
                "in_stock": o.get("availability") == "InStock",
                "condition": o.get("condition"),
            }
        )
    category = p.get("category") or {}
    return {
        "id": p["id"],
        "title": p.get("title", ""),
        "brand": ", ".join(b.get("name", "") for b in p.get("brands") or []) or None,
        "category": category.get("path") or category.get("title"),
        "key_features": p.get("key_features") or [],
        "description": (p.get("description") or "")[:400],
        "image": _best_image(p.get("images")),
        "offers": offers,
    }


def _demo_catalog() -> list[dict[str, Any]]:
    raw = resources.files("cartpilot.fixtures").joinpath("catalog.json").read_text()
    return json.loads(raw)


class Channel3Client:
    def __init__(self, api_key: str, currency: str = "USD", transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.currency = currency
        self._transport = transport

    @property
    def demo(self) -> bool:
        return not self.api_key

    async def search(
        self,
        query: str,
        min_price: float | None = None,
        max_price: float | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if self.demo:
            return self._demo_search(query, min_price, max_price, limit)

        body: dict[str, Any] = {
            "query": query,
            "limit": max(1, min(limit, 30)),
            "config": {"currency": self.currency},
        }
        price: dict[str, float] = {}
        if min_price is not None:
            price["min_price"] = min_price
        if max_price is not None:
            price["max_price"] = max_price
        if price:
            body["filters"] = {"price": price}

        async with httpx.AsyncClient(transport=self._transport, timeout=30) as client:
            r = await client.post(f"{API_BASE}/search", json=body, headers={"x-api-key": self.api_key})
            r.raise_for_status()
            return [normalize_product(p) for p in r.json().get("products", [])]

    def _demo_search(self, query, min_price, max_price, limit) -> list[dict[str, Any]]:
        words = [w for w in query.lower().split() if len(w) > 2]
        results = []
        for p in _demo_catalog():
            haystack = " ".join(
                [p["title"], p.get("description", ""), " ".join(p.get("key_features", [])), str(p.get("category"))]
            ).lower()
            hits = sum(w in haystack for w in words)
            if words and hits == 0:
                continue
            prod = normalize_product(p)
            prices = [o["price"] for o in prod["offers"] if o["in_stock"]] or [o["price"] for o in prod["offers"]]
            low = min(prices) if prices else 0
            if min_price is not None and low < min_price:
                continue
            if max_price is not None and low > max_price:
                continue
            results.append((hits, prod))
        results.sort(key=lambda t: -t[0])
        return [p for _, p in results[:limit]]
