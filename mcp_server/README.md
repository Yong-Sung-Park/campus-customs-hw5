# Campus Customs MCP server

**What it is for.** This FastMCP server is the one place the Campus Customs agent team gets shop facts, and the only way anything gets written. All five agents (Boss, Inventory, Accounting, Facilities, Customer Service), the FastAPI routes, and Claude Code call these tools over MCP. Nothing else opens the database, so every number an agent quotes comes from the DB, and every money rule is enforced in one place.

**Database.** It reads and writes the working copy `data/campus_customs_new.db` (path resolved from the repo root, overridable with the `CAMPUS_CUSTOMS_DB` env var). It never opens the original `data/campus_customs.db`. That file stays clean so you can reset by copying it over the working copy. On first use the server adds four workflow tables to the working copy: `approval_requests`, `purchase_orders`, `message_drafts`, `ticket_outcomes`. A reset removes them again.

**Run it** (stdio transport; the backend and `.mcp.json` start it for you):

```bash
.venv/Scripts/python mcp_server/server.py      # Windows
.venv/bin/python mcp_server/server.py          # macOS / Linux
```

## Tools (23)

### Read-only
| Tool | Reads | Returns |
|---|---|---|
| `get_shop_date()` | `desk` | The shop's "today" (`date_today`) |
| `list_tickets()` | `tickets`, `ticket_outcomes` | All tickets with status and outcome |
| `get_ticket(ticket_id)` | `tickets`, `invoices`, `leases`, workflow tables | One ticket, the live invoice/lease it links to, and its requests / POs / drafts / outcome |
| `check_stock(sku, size)` | `inventory` | On-hand qty + aisle, plus every other size of the SKU |
| `get_pricing(sku, discount_pct?)` | `pricing` | Unit cost, list price, margin; with a discount, the discounted price and margin left |
| `quote_bulk_order(sku, size, qty, discount_pct)` | `pricing`, `inventory` | Order revenue, cost of goods, gross margin, on-hand vs shortfall, restock cost |
| `list_vendors()` | `vendors`, `invoices` | Specialty, lead days, open invoices, can_ship, ETA if ordered today |
| `get_vendor_status(vendor_id)` | `vendors`, `invoices`, `desk` | Open invoices with days overdue, `can_ship`, why it's blocked, ETA |
| `get_invoice(invoice_id)` | `invoices`, `vendors`, `desk` | Amount, due date, days overdue, pending request |
| `get_lease(lease_id)` | `leases`, `desk` | Landlord, rent, next due date, days until due |
| `get_cash_position()` | `cash_accounts`, `approval_requests`, `invoices`, `leases` | Balance, pending approvals, obligations not yet requested, free cash |
| `list_payments()` | `payments` | Every payment and who approved it |
| `list_approval_requests(ticket_id?, status?)` | `approval_requests` | Requests waiting on / decided by a human |
| `list_purchase_orders(ticket_id?)` | `purchase_orders`, `vendors` | POs with status and expected arrival |
| `list_drafts(ticket_id?)` | `message_drafts` | Customer drafts on the board |

### Agent writes (no cash moves)
| Tool | Writes | What it does |
|---|---|---|
| `prepare_invoice_payment(invoice_id, ticket_id, requested_by, reason)` | `approval_requests` | Queues an open invoice for human approval (amount from `invoices`) |
| `prepare_rent_payment(lease_id, ticket_id, requested_by, reason)` | `approval_requests` | Queues this month's rent (amount from `leases`) |
| `prepare_purchase_order(vendor_id, sku, size, qty, ticket_id, requested_by, reason)` | `purchase_orders`, `approval_requests` | Drafts a restock PO at qty × `pricing.unit_cost` and queues it |
| `save_customer_draft(ticket_id, recipient, subject, body, author)` | `message_drafts` | Saves a customer message as a draft. Nothing is sent. |
| `resolve_ticket(ticket_id, outcome, resolved_by)` | `tickets`, `ticket_outcomes` | Closes a ticket. Refuses while any of its requests are still pending. |

### Human / backend only (never given to an agent)
| Tool | Writes | What it does |
|---|---|---|
| `execute_approved_payment(approval_id, approved_by)` | `payments`, `cash_accounts`, `approval_requests`, `invoices` / `leases` / `purchase_orders` | Moves the money after a human clicks approve. Refuses if cash would go negative, if the approver is an agent name, or if a PO's vendor still has an open invoice. |
| `reject_approval_request(approval_id, rejected_by, reason)` | `approval_requests`, `purchase_orders` | A human declines a request. No cash moves. |
| `set_ticket_status(ticket_id, status)` | `tickets` | Backend moves a ticket between open / in_progress / awaiting_approval |

If an ID, SKU or size isn't in the database, a tool returns `found: false` / `ok: false` with an error. It never guesses.
