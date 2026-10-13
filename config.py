from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    paypal_client_id: str
    paypal_client_secret: str
    paypal_base_url: str
    channel3_api_key: str
    currency: str
    public_base_url: str
    db_path: str
    default_per_order_limit: float
    default_monthly_limit: float

    @property
    def demo_catalog(self) -> bool:
        """No Channel3 key -> use the bundled demo catalog."""
        return not self.channel3_api_key


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        paypal_client_id=os.getenv("PAYPAL_CLIENT_ID", ""),
        paypal_client_secret=os.getenv("PAYPAL_CLIENT_SECRET", ""),
        paypal_base_url=os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/"),
        channel3_api_key=os.getenv("CHANNEL3_API_KEY", ""),
        currency=os.getenv("CARTPILOT_CURRENCY", "USD").upper(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        db_path=os.getenv("CARTPILOT_DB", "cartpilot.db"),
        default_per_order_limit=float(os.getenv("DEFAULT_PER_ORDER_LIMIT", "500")),
        default_monthly_limit=float(os.getenv("DEFAULT_MONTHLY_LIMIT", "1500")),
    )
