"""SQLite persistence: spending policy, product cache and the purchase ledger (audit trail)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  cached_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  title TEXT NOT NULL,
  category TEXT,
  merchant TEXT,
  merchant_url TEXT,
  unit_price REAL NOT NULL,
  quantity INTEGER NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL,
  paypal_order_id TEXT,
  capture_id TEXT,
  approve_url TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchases_order ON purchases(paypal_order_id);
"""

# Purchase lifecycle
BLOCKED = "BLOCKED_BY_POLICY"
PENDING = "AWAITING_APPROVAL"
COMPLETED = "COMPLETED"
CANCELLED = "CANCELLED"
REFUNDED = "REFUNDED"
FAILED = "FAILED"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = "cartpilot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- policy ----
    def get_policy(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM policy WHERE id = 1").fetchone()
        return json.loads(row["data"]) if row else None

    def save_policy(self, policy: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO policy (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (json.dumps(policy),),
        )
        self.conn.commit()

    # ---- product cache ----
    def cache_products(self, products: list[dict[str, Any]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO products (id, data, cached_at) VALUES (?, ?, ?)",
            [(p["id"], json.dumps(p), now()) for p in products],
        )
        self.conn.commit()

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM products WHERE id = ?", (product_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    # ---- purchases ----
    def create_purchase(self, **fields: Any) -> dict[str, Any]:
        pid = "pur_" + uuid.uuid4().hex[:10]
        ts = now()
        row = {"id": pid, "created_at": ts, "updated_at": ts, **fields}
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.conn.execute(f"INSERT INTO purchases ({cols}) VALUES ({marks})", tuple(row.values()))
        self.conn.commit()
        return self.get_purchase(pid)

    def update_purchase(self, purchase_id: str, **fields: Any) -> dict[str, Any]:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE purchases SET {sets} WHERE id = ?", (*fields.values(), purchase_id))
        self.conn.commit()
        return self.get_purchase(purchase_id)

    def get_purchase(self, purchase_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,)).fetchone()
        return dict(row) if row else None

    def get_purchase_by_order(self, order_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM purchases WHERE paypal_order_id = ?", (order_id,)).fetchone()
        return dict(row) if row else None

    def list_purchases(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM purchases ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def spent_this_month(self, currency: str) -> float:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM purchases "
            "WHERE status = ? AND currency = ? AND substr(created_at, 1, 7) = ?",
            (COMPLETED, currency, month),
        ).fetchone()
        return float(row["s"])

    def pending_total(self, currency: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM purchases WHERE status = ? AND currency = ?",
            (PENDING, currency),
        ).fetchone()
        return float(row["s"])
