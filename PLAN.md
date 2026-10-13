# CartPilot: hackathon plan

**Deadline:** Fri Nov 13, 2026, 1:30 AM IST. Treat **Thu Nov 12** as the last working day.

**Prize targets:**

- Best Use of Agentic Commerce
- Best Use of PayPal + AI
- Best Use of Channel3
- Best Demo Delivery
- Overall prizes

## Pitch

- **Name:** CartPilot
- **Elevator pitch (under 200 characters):** An MCP shopping agent that finds, compares and buys products with PayPal, inside your budget rules, and never spends a cent until you approve.

## Week 1 (Oct 13–19): make it real

- [x] Scaffold the MCP server: search, compare, policy, propose, capture, refund, ledger
- [x] Tests with PayPal mocked
- [ ] Create the PayPal sandbox app, plus a sandbox business account and a sandbox personal account
- [ ] Get a Channel3 API key and confirm the real response shape matches `normalize_product`
- [ ] Run the full flow live in Claude Desktop: sandbox order → approve → capture → refund

## Week 2 (Oct 20–26): make it smart

- [ ] Price tracking: a `watch_price` tool using Channel3 price tracking that offers to buy when the price drops below a target (still needs approval)
- [ ] Better comparisons: let users set their own priorities (cheapest, best rated, fastest) in `compare_products`
- [ ] Add PayPal webhooks (`CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`) in HTTP mode as a backup to polling
- [ ] Error handling: expired orders, out-of-stock items at capture time, PayPal 422 errors

## Week 3 (Oct 27–Nov 2): make it shippable

- [ ] Deploy HTTP mode to Render (also a sponsor), then connect it to Claude as a remote MCP connector
- [ ] Optional: Recurring purchases with PayPal Subscriptions, e.g. "reorder coffee every month"
- [ ] Polish the README: screenshots, architecture diagram, judge quick start (under 5 minutes)
- [ ] Add a GitHub repo description and topics, and make the MIT license visible

## Week 4 (Nov 3–12): demo and submit

- [ ] Script the demo video (under 3 minutes):
  1. Problem (0:15)
  2. Set a budget (0:20)
  3. Search and compare (0:40)
  4. Approve on PayPal and capture (0:40)
  5. A blocked over-budget attempt (0:20)
  6. Refund (0:15)
  7. Why it matters (0:10)
- [ ] Record, upload to YouTube as public, and use no copyrighted music
- [ ] Fill in Devpost: description, built-with tools, repo link, video link
- [ ] Submit by **Nov 11** to leave a buffer day

## Judging criteria → evidence

| Criterion | What shows it |
|---|---|
| Technological implementation | Orders, capture, refunds and idempotency, a policy engine enforced in code, tests |
| Design | A complete flow from search to refund, clear approval and confirmation pages |
| Potential impact | Makes agent shopping safe: budgets, human approval, an audit trail |
| Innovation | Guardrails enforced server-side, which the model can't bypass, plus explainable ranking |
| Presentation | A tight 3-minute video that shows the blocked purchase and the refund, not only the happy path |
