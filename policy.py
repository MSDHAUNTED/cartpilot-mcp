"""Spending guardrails. Checked server-side before a PayPal order is ever created,
and again right before capture, so the model cannot talk its way past them."""
from __future__ import annotations

from typing import Any


def default_policy(per_order_limit: float, monthly_limit: float, currency: str) -> dict[str, Any]:
    return {
        "currency": currency,
        "per_order_limit": per_order_limit,
        "monthly_limit": monthly_limit,
        "blocked_categories": [],  # substrings matched against product category / title
        "max_quantity": 5,
    }


def check(
    policy: dict[str, Any],
    *,
    amount: float,
    quantity: int,
    currency: str,
    category: str | None,
    title: str,
    spent_this_month: float,
    pending: float = 0.0,
) -> list[str]:
    """Return a list of human-readable violations. Empty list means allowed."""
    problems: list[str] = []
    if currency != policy["currency"]:
        problems.append(f"Currency {currency} is not allowed (policy currency is {policy['currency']}).")
    if quantity > policy.get("max_quantity", 5):
        problems.append(f"Quantity {quantity} exceeds the max of {policy['max_quantity']} per order.")
    if amount > policy["per_order_limit"]:
        problems.append(
            f"Order total {amount:.2f} exceeds the per-order limit of {policy['per_order_limit']:.2f} {policy['currency']}."
        )
    projected = spent_this_month + pending + amount
    if projected > policy["monthly_limit"]:
        remaining = max(policy["monthly_limit"] - spent_this_month - pending, 0)
        problems.append(
            f"This would exceed the monthly budget of {policy['monthly_limit']:.2f} {policy['currency']} "
            f"(only {remaining:.2f} left, including orders awaiting approval)."
        )
    text = f"{category or ''} {title}".lower()
    for blocked in policy.get("blocked_categories", []):
        if blocked and blocked.lower() in text:
            problems.append(f"Category '{blocked}' is blocked by your spending policy.")
    return problems
