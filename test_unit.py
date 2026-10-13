from cartpilot import policy
from cartpilot.channel3 import normalize_product
from cartpilot.ranking import best_offer, compare


def _pol(**kw):
    p = policy.default_policy(100, 300, "USD")
    p.update(kw)
    return p


def test_policy_allows_small_order():
    assert policy.check(_pol(), amount=50, quantity=1, currency="USD", category="Audio", title="x", spent_this_month=0) == []


def test_policy_blocks_per_order_monthly_category_currency():
    v = policy.check(
        _pol(blocked_categories=["vape"]), amount=150, quantity=1, currency="EUR",
        category="Tobacco > Vapes", title="CloudX Disposable Vape", spent_this_month=200,
    )
    text = " ".join(v)
    assert "per-order limit" in text and "monthly budget" in text and "vape" in text and "Currency" in text


def test_pending_counts_toward_monthly():
    v = policy.check(_pol(), amount=90, quantity=1, currency="USD", category=None, title="x",
                     spent_this_month=100, pending=150)
    assert any("monthly budget" in s for s in v)


def test_normalize_and_best_offer_prefers_cheapest_in_stock():
    p = normalize_product({
        "id": "p1", "title": "T", "offers": [
            {"domain": "a", "url": "u1", "price": {"price": 10, "currency": "USD"}, "availability": "OutOfStock"},
            {"domain": "b", "url": "u2", "price": {"price": 12, "currency": "USD"}, "availability": "InStock"},
        ],
    })
    assert best_offer(p)["merchant"] == "b"


def test_compare_ranks_and_penalises_over_budget():
    mk = lambda i, price, feats: normalize_product({
        "id": i, "title": i, "key_features": feats,
        "offers": [{"domain": "m", "url": "u", "price": {"price": price, "currency": "USD"}, "availability": "InStock"}],
    })
    res = compare([mk("cheap", 50, ["anc"]), mk("pricey", 300, ["anc"])], must_have=["anc"], budget=200)
    assert res["recommended"] == "cheap"
    assert res["ranked"][1]["over_budget"] is True
