# CartPilot MCP

**Let Claude shop for you, without handing it your wallet.**

CartPilot is an MCP server that turns Claude (or any MCP client) into a shopping agent. Claude can search products across online stores, compare them and buy one with PayPal. Every purchase passes your spending rules and needs your explicit approval on PayPal before any money moves.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/).

## Why

AI agents can now browse and decide, but paying is where trust breaks down. Users don't want an agent holding card details or spending without limits. CartPilot splits the job:

- **The agent decides.** It searches, compares and recommends a product, and explains why.
- **Your rules constrain it.** The server enforces per-order limits, a monthly budget, blocked categories and a quantity cap. These checks run in code, not in the prompt.
- **You pay.** The agent only creates a PayPal order. You approve it in PayPal's own checkout, and only then does CartPilot capture the payment.
- **Everything is logged.** Every attempt is kept in an audit trail, including blocked and cancelled ones.

## How it works

```
User ──chat──▶ Claude ──MCP──▶ CartPilot server
                                 │
             search / compare ───┼──▶ Channel3 product API (or the demo catalog)
                                 │
   propose_purchase ── policy ───┼──▶ PayPal Orders v2: create order (intent CAPTURE)
                       check     │        │
                                 │        ▼
                                 │   User approves on PayPal (human in the loop)
                                 │        │
   check_purchase ── re-check ───┼──▶ PayPal: get order ▶ capture
                     policy      │
   refund_purchase ──────────────┴──▶ PayPal: refund capture
                                 │
                            SQLite ledger (policy, product cache, purchases)
```

## Tools

| Tool | What it does |
|---|---|
| `search_products` | Searches stores through Channel3, with optional min and max price |
| `get_product` | Returns full details and every merchant offer for a product |
| `compare_products` | Ranks products by price, must-have features, stock and discount, and returns a recommendation with a reason |
| `get_spending_policy` | Shows the current limits, what you've spent this month, what's awaiting approval and what's left |
| `set_spending_policy` | Changes the per-order limit, monthly limit, blocked categories or max quantity |
| `propose_purchase` | Checks the policy, then creates a PayPal order and returns an **approval link** |
| `check_purchase` | Captures the payment once the user has approved on PayPal (the policy is checked again first) |
| `cancel_purchase` | Cancels a purchase that hasn't been paid yet |
| `refund_purchase` | Refunds a completed purchase in full |
| `list_purchases` | Shows the purchase history and audit trail |

## Quick start

Requirements: Python 3.10+ and a free [PayPal Developer](https://developer.paypal.com) account.

```bash
git clone https://github.com/<you>/cartpilot-mcp.git
cd cartpilot-mcp
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `.env`:

1. **PayPal:** in the PayPal Developer Dashboard, go to Apps & Credentials, select Sandbox, create an app, and paste the Client ID and Secret.
2. **Channel3 (optional):** add `CHANNEL3_API_KEY` to search real stores. Leave it empty to use the built-in demo catalog.
3. To pay during a demo, use a **sandbox personal account** (Dashboard > Testing Tools > Sandbox Accounts).

### Run with Claude Desktop (stdio)

Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cartpilot": {
      "command": "/absolute/path/to/cartpilot-mcp/.venv/bin/cartpilot",
      "env": { "CARTPILOT_DB": "/absolute/path/to/cartpilot-mcp/cartpilot.db" }
    }
  }
}
```

The `.env` file is read from the working directory. You can also put the PayPal keys straight into `env` above.

### Run over HTTP (recommended for demos)

```bash
cartpilot --http --port 8000
```

- MCP endpoint: `http://localhost:8000/mcp`
- PayPal redirect pages: `/paypal/return` and `/paypal/cancel`. After the user approves, the return page captures the payment immediately.
- Health check: `/health`

In stdio mode the return page isn't served. The user approves on PayPal, comes back to Claude and says "done", and Claude calls `check_purchase`.

### Tests

```bash
pytest
```

The tests cover the policy engine, the ranking, and the full flow search → compare → propose → capture → refund, with PayPal sandbox calls mocked.

## Try it

> "Find me noise-cancelling headphones under $200 with at least 40 hours of battery, compare the options and buy the best one."

> "Set my monthly shopping budget to $300 and block anything in vapes or tobacco."

> "What did I buy this month? Refund the headphones, I changed my mind."

## PayPal APIs used

- OAuth 2.0 client credentials: `POST /v1/oauth2/token`
- Orders v2:
  - `POST /v2/checkout/orders` with `payment_source.paypal.experience_context` for return and cancel URLs and `PAY_NOW`
  - `GET /v2/checkout/orders/{id}`
  - `POST /v2/checkout/orders/{id}/capture`
- Payments v2: `POST /v2/payments/captures/{id}/refund`
- A `PayPal-Request-Id` idempotency key on every write

## Limitations

- **Sandbox only.** No real money moves.
- **The retailer side is simulated.** PayPal collects the payment into the developer's sandbox business account. After capture, CartPilot returns the retailer's product link as the fulfilment step. Native retailer checkout would replace this once it's available (Channel3 has announced a checkout API).

## License

MIT
