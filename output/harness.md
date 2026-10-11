# Harness — Campus Customs Multi-Agent Operations

This is the design doc for the HW5 build, grown one problem at a time. It covers tables (§1), MCP tools (§2, §4), the five agents (§3), safety (§5), API routes (§6), the dashboard (§7), and the full run (§8).

```
React board (frontend/, :5173) --HTTP--> FastAPI (backend/main.py, :8000) --MCP stdio--> FastMCP server (mcp_server/server.py) --> data/campus_customs_new.db
                                               |
                                               +-- PydanticAI team (backend/team.py): Boss, Inventory, Accounting, Facilities, Customer Service
                                                   (gpt-6-luna via Portkey; every agent's tools are filtered views of the same MCP server)
```

- **Original DB (never written):** `data/campus_customs.db`
- **Working copy (MCP server + backend read/write this):** `data/campus_customs_new.db`
- **"Today" for the shop:** `desk.date_today` = **2026-08-31**

---

## 1. Database

Nine tables. All dates are ISO text (`YYYY-MM-DD`), all money is a REAL in dollars.

### `desk` — 1 row
| Field | Type | Notes |
|---|---|---|
| `date_today` | TEXT | The shop's "today" (2026-08-31). |
| `notes` | TEXT | Free-text desk note (NULL at start). |

**Why it matters:** every "is this overdue / how many days until due / when does a restock land" question is measured against `date_today`, never the real clock.

### `tickets` — 3 rows (101, 102, 103, all `open`)
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 101 / 102 / 103 |
| `type` | TEXT | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT | Who asked (customer, landlord, student org) |
| `subject` | TEXT | Short title |
| `sku`, `size`, `qty` | TEXT, TEXT, INTEGER | Product line the ticket is about (NULL for rent) |
| `lease_id` | INTEGER FK → `leases.id` | Set on the rent ticket |
| `invoice_id` | INTEGER FK → `invoices.id` | Set on the tee order — the vendor's unpaid bill |
| `status` | TEXT | `open` → `resolved` |
| `notes` | TEXT | Request in plain words |
| `created_at` | TEXT | ISO timestamp |

**Why it matters:** the Boss's inbox. The foreign keys tell the Boss which specialist owns the next step (SKU → Inventory, lease → Facilities, invoice → Accounting).

### `inventory` — 10 rows, PK (`sku`, `size`)
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT | e.g. `CC-TEE-WHITE` |
| `name` | TEXT | Display name |
| `size` | TEXT | S/M/L/XL, or `OS` (one size) |
| `qty` | INTEGER | Units on hand |
| `location` | TEXT | Aisle |

**Why it matters:** Inventory's ground truth for "can we fill this order?" Two lines are at zero: `CC-TEE-WHITE` size S (ticket 101) and `CC-MUG-CREST` OS (no ticket — a distractor).

### `pricing` — 4 rows
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT PK | Matches `inventory.sku` |
| `unit_cost` | REAL | What a unit costs the shop (and what a restock costs per unit) |
| `list_price` | REAL | Normal selling price |

**Why it matters:** Accounting checks margins here before any discount, and multiplies `unit_cost` × qty to price a restock purchase order.

### `vendors` — 3 rows
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 1 / 2 / 3 |
| `name` | TEXT | Bulldog Print Co, Elm City Gifts, QuickShip CT |
| `specialty` | TEXT | apparel reprint / mugs and small goods / local courier |
| `lead_days` | INTEGER | 5 / 3 / 1 days from order to delivery |

**Why it matters:** Inventory picks the restock vendor by specialty (apparel → Bulldog Print Co) and computes the arrival date as `date_today + lead_days`. There is no SKU → vendor column, so the match comes from `specialty` and from invoice 501's description.

### `leases` — 1 row
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 1 |
| `space_name` | TEXT | Chapel Street shop |
| `landlord` | TEXT | Elm City Properties |
| `monthly_rent` | REAL | 2,400.00 |
| `next_due` | TEXT | 2026-09-02 (2 days after today) |
| `notes` | TEXT | NULL |

**Why it matters:** Facilities' only record. After rent is paid, `next_due` must roll forward one month.

### `cash_accounts` — 1 row
| Field | Type | Notes |
|---|---|---|
| `name` | TEXT PK | `checking` |
| `balance` | REAL | 3,400.00 at start |
| `date` | TEXT | As-of date of the balance |

**Why it matters:** the only money the shop has. Cash only goes out in this homework, and no payment may push it below zero.

### `payments` — 0 rows at start
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `kind` | TEXT | e.g. `invoice`, `rent`, `purchase_order` |
| `ref_id` | INTEGER | The invoice / lease / PO id the money was for |
| `amount` | REAL | Dollars out |
| `account` | TEXT | `checking` |
| `paid_at` | TEXT | Date paid |
| `approved_by` | TEXT | **The human** who clicked approve |

**Why it matters:** the ledger of every dollar that left. Every row must have a human in `approved_by`; Accounting reads it to avoid paying twice.

### `invoices` — 1 row
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | 501 |
| `vendor_id` | INTEGER FK → `vendors.id` | 1 (Bulldog Print Co) |
| `amount` | REAL | 840.00 |
| `due_date` | TEXT | 2026-08-28 — **3 days overdue** on 2026-08-31 |
| `status` | TEXT | `open` |
| `description` | TEXT | "Rush reprint CC-TEE-WHITE S" |

**Why it matters:** a vendor won't ship while it has an open unpaid invoice, so this bill blocks any reprint from Bulldog Print Co — including the tee ticket 101 needs.

### How the three open tickets link into the tables

| Ticket | What it asks | Links | What it really needs |
|---|---|---|---|
| **101** customer_order — Tauhid Zaman | 1 × `CC-TEE-WHITE` size S | `inventory` (S qty = **0**), `invoice_id` 501 → `vendors` 1 Bulldog Print Co (apparel, 5 lead days) | Stock is out. The only apparel vendor is blocked by **overdue invoice 501 ($840)**. Pay 501 (human approval) → order the reprint ($8 unit cost) → the tee lands 2026-09-05 → draft a note to the customer. |
| **102** rent_notice — Elm City Properties | Rent due in 2 days | `lease_id` 1 → `leases` ($2,400, due 2026-09-02), `cash_accounts` | Confirm the amount and due date, check cash, pay $2,400 (human approval), roll `next_due` to 2026-10-02. |
| **103** price_override — Yale AI Club | 20 × `CC-HOOD-NAVY` size M with a bulk discount | `inventory` (M qty = **8**), `pricing` (cost $22, list $58), `vendors` (Bulldog Print Co for a reprint) | Decide a discount that keeps a healthy margin; only 8 of the 20 are on hand. A 12-unit reprint costs $264. |

**Cash pressure:** $3,400 − $840 (invoice 501) − $2,400 (rent) = **$160** before any restock. That is not enough for a 12-hoodie reprint ($264), so the pay tool has to refuse rather than go negative.

---

## 2. MCP tools (Problem 3 — first three)

Server: `mcp_server/server.py` (FastMCP, stdio). It opens `data/campus_customs_new.db` only.

| Tool | Table(s) read | Ticket it unlocks | Why it's the right tool for that ticket |
|---|---|---|---|
| `check_stock(sku, size)` | `inventory` | **101** (tee order) | Ticket 101 asks for 1 × `CC-TEE-WHITE` size **S**; this returns qty **0** for that exact line (with M=5, L=3, XL=2 beside it), which is the fact that turns a simple order into a restock problem. It is also how 103 learns only 8 size-M hoodies are on hand. |
| `get_lease(lease_id)` | `leases`, `desk` | **102** (rent notice) | The landlord's email only says "due in 2 days"; this pulls the real rent (**$2,400**), the due date (**2026-09-02**) and computes **2 days until due** from `desk.date_today`, so Facilities pays the right amount on time instead of trusting the email. |
| `get_pricing(sku, discount_pct)` | `pricing` | **103** (bulk hoodie discount) | The Yale AI Club wants a bulk discount on `CC-HOOD-NAVY`; this gives cost **$22** vs list **$58** and the margin left at any proposed discount (e.g. 15% → $49.30, still 55.4% margin), so Accounting can approve a discount without selling below cost. |

---

## 3. Agent team (Problem 5)

Five PydanticAI agents, all on **`gpt-6-luna` via Portkey** (`OpenAIResponsesModel`, reasoning effort `low`). The code is in `backend/team.py`, the prompts are in `backend/prompts/<agent>.md` (one file per agent), and the data types are in `backend/models.py`.

| Agent | Role | Output type | MCP tools it can see |
|---|---|---|---|
| **Boss** (`boss.md`) | Reads the ticket, picks who goes first, delegates only to who's needed, approves discounts, makes the final call, resolves the ticket | `BossDecision` | `get_ticket`, `get_shop_date`, `list_tickets`, `get_cash_position`, `list_approval_requests`, `list_purchase_orders`, `list_drafts`, `list_payments`, `resolve_ticket` |
| **Inventory** (`inventory.md`) | Stock by SKU/size, shortfall, which vendor can restock, lead time/ETA, PO spec | `SpecialistReport` | `get_ticket`, `get_shop_date`, `check_stock`, `list_vendors`, `get_vendor_status`, `get_pricing`, `list_purchase_orders` |
| **Accounting** (`accounting.md`) | Cash, invoices, margins/discount math, **prepares every payment and PO for human approval** | `SpecialistReport` | `get_ticket`, `get_shop_date`, `get_cash_position`, `get_invoice`, `get_vendor_status`, `get_pricing`, `quote_bulk_order`, `list_payments`, `list_approval_requests`, `list_purchase_orders`, `prepare_invoice_payment`, `prepare_rent_payment`, `prepare_purchase_order` |
| **Facilities** (`facilities.md`) | Lease, rent, landlord; checks the notice against `leases`, then asks Accounting to prepare rent | `SpecialistReport` | `get_ticket`, `get_shop_date`, `get_lease`, `get_cash_position`, `list_payments`, `list_approval_requests` |
| **Customer Service** (`customer_service.md`) | Writes the customer-facing **draft** (never sent) | `SpecialistReport` | `get_ticket`, `get_shop_date`, `check_stock`, `list_purchase_orders`, `list_approval_requests`, `list_drafts`, `save_customer_draft` |

**Full connectivity.** Every agent has a `delegate(to_agent, task)` tool that can reach any of the other four. The teammate runs its own loop with its own tools and returns a structured `SpecialistReport`. Peer-to-peer delegation is normal, e.g. Facilities → Accounting for rent or Inventory → Accounting for a PO.

**Two phases per ticket.**
1. **Work.** Boss → specialists. Money requests are *prepared* (pending). If any are pending, the ticket goes to `awaiting_approval`.
2. **Close-out.** Runs automatically once a human has approved or rejected every request for the ticket. The Boss gets its work-phase decision plus the human decisions, verifies them with tools, updates the customer draft if needed, and calls `resolve_ticket`.

**Audit trail.** `backend/audit.py` appends every agent-loop step to `output/audit_trail.json`:
- `run_start`, `model_request`, `thinking`, `said`
- `tool_call` with its args, then `tool_result`
- `delegate`, `delegate_result`, `delegate_refused`, `retry`
- `final`, `run_end` with token use, `approval`, `run_finished`

Each event carries `run_id`, `ticket_id`, `agent`, `depth`, `ts` and `seq`. The file is a JSON array that is only ever appended to. Nothing wipes it, not even a DB reset.

## 4. MCP tools — full list (Problem 5)

| Tool | Table(s) | Used by | Ticket(s) |
|---|---|---|---|
| `get_shop_date` | `desk` | all agents | 101, 102, 103 |
| `list_tickets` | `tickets`, `ticket_outcomes` | Boss, API | all |
| `get_ticket` | `tickets`, `invoices`, `leases`, workflow tables | all agents, API | all |
| `check_stock` | `inventory` | Inventory, Customer Service | 101, 103 |
| `get_pricing` | `pricing` | Inventory, Accounting | 101 (PO cost), 103 (margin) |
| `quote_bulk_order` | `pricing`, `inventory` | Accounting | 103 |
| `list_vendors` | `vendors`, `invoices` | Inventory | 101, 103 |
| `get_vendor_status` | `vendors`, `invoices`, `desk` | Inventory, Accounting | 101, 103 |
| `get_invoice` | `invoices`, `vendors`, `desk` | Accounting | 101 |
| `get_lease` | `leases`, `desk` | Facilities | 102 |
| `get_cash_position` | `cash_accounts`, `approval_requests`, `invoices`, `leases` | Boss, Accounting, Facilities, API | all |
| `list_payments` | `payments` | Boss, Accounting, Facilities, API | all |
| `list_approval_requests` | `approval_requests` | Boss, Accounting, Facilities, Customer Service, API | all |
| `list_purchase_orders` | `purchase_orders`, `vendors` | Boss, Inventory, Accounting, Customer Service | 101, 103 |
| `list_drafts` | `message_drafts` | Boss, Customer Service, API | 101, 103 |
| `prepare_invoice_payment` | writes `approval_requests` (reads `invoices`, `cash_accounts`) | Accounting | 101 |
| `prepare_rent_payment` | writes `approval_requests` (reads `leases`, `cash_accounts`) | Accounting | 102 |
| `prepare_purchase_order` | writes `purchase_orders`, `approval_requests` (reads `vendors`, `pricing`, `inventory`, `invoices`, `cash_accounts`) | Accounting | 101, 103 |
| `save_customer_draft` | writes `message_drafts` | Customer Service | 101, 103 |
| `resolve_ticket` | writes `tickets`, `ticket_outcomes` | Boss | all |
| `execute_approved_payment` | writes `payments`, `cash_accounts`, `approval_requests`, `invoices` / `leases` / `purchase_orders` | **human approve route only** | 101, 102, 103 |
| `reject_approval_request` | writes `approval_requests`, `purchase_orders` | **human reject route only** | any |
| `set_ticket_status` | writes `tickets` | **backend only** | all |

The MCP server creates four new workflow tables, in the working copy only:
- `approval_requests`: money requests that are pending, approved or rejected
- `purchase_orders`: restock orders with an ETA
- `message_drafts`: customer drafts, never sent
- `ticket_outcomes`: the final outcome per ticket

## 5. Safety

**Money and customers: guardrails a real business would want**
- **Agents can't move money.** `execute_approved_payment` is not in any agent's toolset (`TOOL_ACCESS` in `team.py`, checked by an `assert` at import time). Only the human approve route calls it. It refuses an `approved_by` that is an agent's name, and every `payments` row records the human who approved it.
- **Amounts come from the DB, not the model.** The prepare tools take an invoice ID, a lease ID, or a SKU × qty and look up the dollars themselves. An agent can't type "$84" for an $840 bill.
- **Cash can't go negative, and that's checked twice.** The prepare tools refuse when a request is more than the balance minus what's already pending. The pay tool checks again inside the same DB transaction and refuses if checking would drop below $0.
- **The vendor-hold rule is in code.** A PO to a vendor with an open invoice can be drafted but not paid. The approve step refuses it until the invoice is paid.
- **No double payments.** A second pending request for the same invoice or lease is refused. Rent more than a month away is refused. A paid invoice can't be paid again.
- **No closing a ticket with money in limbo.** `resolve_ticket` refuses while the ticket still has pending requests.
- **Customers only get drafts.** `save_customer_draft` stores text with status `draft`. No tool can email, text or call anyone. The Customer Service prompt keeps internal matters like unpaid bills and cash out of customer messages.
- **Least privilege per role** (see the table above). Facilities can't touch stock, Customer Service can't touch money, and the Boss can't prepare payments.
- **One source of truth.** Every fact comes through MCP over `campus_customs_new.db`. The prompts forbid inventing data, and tools return `found: false` instead of guessing.
- **Full audit.** Every step, tool argument, result, delegation and human approval is appended to `output/audit_trail.json`.
- **Resettable.** The server never opens the original DB. A reset copies it over the working copy and leaves the audit trail alone.

**Token and cost limits**
- One `UsageLimits` is shared by the whole ticket run, the Boss and every delegate together: at most 60 model requests, 90 tool calls and 400k tokens. Hitting the limit stops the run instead of letting it loop.
- Delegation guards:
  - no delegating to yourself
  - no calling an agent already above you in the chain (no A→B→A loops)
  - max depth 2
  - max 8 delegations per ticket run
- Only `gpt-6-luna`, with **low** reasoning effort. The Boss prompt aims for at most 4 delegations and no repeated tool calls for the same fact.
- Structured outputs (`BossDecision`, `SpecialistReport`) keep hand-offs short. Large tool payloads are truncated in the audit trail.
- One run per ticket at a time: the API refuses a second run while one is in progress.
- Measured cost: a smoke run of ticket 102 on a scratch DB took 9 model requests and about 24k tokens for the whole team.

---

## 6. API routes (Problem 7)

`backend/main.py` (FastAPI). Start it from `backend/` with `uvicorn main:app --reload --port 8000`. It opens one MCP connection at startup and every route goes through it. CORS allows `http://localhost:5173`.

| Method & URL | What it does |
|---|---|
| `GET /api/health` | Liveness, plus the model name and which DB file is in use |
| `GET /api/tickets` | The three tickets with status (open / in_progress / awaiting_approval / resolved), outcome, pending-approval count, and any running run id |
| `GET /api/tickets/{id}` | One ticket in full: linked invoice/lease, approval requests, POs, full customer draft text, and a per-agent summary |
| `POST /api/tickets/{id}/run` | Starts the agent team on that ticket in the background and returns `run_id`. 409 if it is already running, resolved, or waiting on approval |
| `GET /api/events?ticket_id=&run_id=&since=&limit=` | Recent agent events since the last reset (what each agent said, tool calls/results, delegations, approvals); `since` lets the board poll |
| `GET /api/runs?ticket_id=` | Status of work and close-out runs (running / done / failed) |
| `GET /api/tickets/{id}/summary` | Short summary of what each agent did: tools used, delegations, its own summary line, the Boss's decision, the human approvals |
| `GET /api/approvals?status=&ticket_id=` | Payment / PO requests waiting on a human (or already decided) |
| `POST /api/approvals/{id}/approve` `{approved_by}` | **Human approve.** The only route that changes cash, via MCP `execute_approved_payment`. 409 if refused (cash would go negative, vendor blocked, approver is an agent). Auto-starts the Boss close-out when the ticket's last request is decided |
| `POST /api/approvals/{id}/reject` `{rejected_by, reason}` | Human reject. No cash moves. Also triggers close-out when it was the last pending request |
| `GET /api/cash` | Current checking balance from `cash_accounts`, plus pending requests, unrequested obligations and the `payments` ledger |
| `GET /api/drafts?ticket_id=` | Customer drafts (never sent) |
| `GET /api/agents` | The five agents, their labels, and the MCP tools each can use |
| `POST /api/reset` | Copies `data/campus_customs.db` over `data/campus_customs_new.db` for a fresh run. Refused while a run is going; the audit trail is kept |

---

## 7. Dashboard (Problem 8)

`frontend/` is React + Vite + TypeScript. It calls `http://localhost:8000` directly; CORS on the backend allows `http://localhost:5173`. Start it with `npm run dev`. Full design write-up: `output/design.md`.

| Area | What it shows | Routes it polls |
|---|---|---|
| Ticket board (left) | Three paper "ticket stubs" with status, **Start the team** on open tickets, and a RESOLVED stamp plus the outcome when done | `GET /api/tickets`, `POST /api/tickets/{id}/run` |
| Agent floor (center) | The five agents with the Boss at the head, all ten possible links (full connectivity), used hand-offs with counts, an animated packet stream on the hand-off in flight, and each agent's live status and speech bubble | `GET /api/events?ticket_id=&since=` |
| Live feed tab | Every audit step as it happens: hand-offs, tool calls in mono, expandable tool results, reports, human approvals, run dividers with token counts | `GET /api/events` |
| Who did what tab | Boss outcome, first call, delegation chain, one card per agent (summary, MCP tools ×count, hand-offs), "not involved" cards, guardrails that fired, human decisions, POs | `GET /api/tickets/{id}` |
| Customer draft tab | Customer Service's message as a lined letter stamped **DRAFT · NOT SENT** | `GET /api/tickets/{id}` |
| Cash drawer (right) | Checking balance that counts down when a payment clears, a paid/pending meter, the ledger with each approver, and bills coming due | `GET /api/cash` |
| Approvals inbox (right) | Pending payment/PO requests. Each shows payee, amount, ticket, which agent prepared it and why, and an "approve the invoice first" hint. The approver must type a name before Approve or Reject works | `GET /api/approvals`, `POST /api/approvals/{id}/approve`, `/reject` |
| Header | Shop date, model, backend status, theme toggle, Reset DB (with confirm) | `POST /api/reset` |

Polling runs every 1s while a ticket is running and every 3.5s when idle. Deep links like `?ticket=103&tab=summary` open a given view, which is how the screenshots in `output/resolved_board.html` were captured.

---

## 8. Full run results (Problem 9)

The DB was reset with `POST /api/reset` (2026-10-11 09:00:51), which left checking at **$3,400.00**. Tickets ran in order 101 → 102 → 103 from the board. Details are in `output/desk_tickets.html` (Actual and Cash tabs), `output/resolved_tickets.json` and `output/resolved_board.html`.

| Ticket | First call | Delegations (in order) | Human approvals | Cash | Model calls / tokens |
|---|---|---|---|---|---|
| 101 tee | Inventory | Boss→Inventory, **Inventory→Accounting**, Boss→Customer Service | #1 invoice 501 $840, #2 PO $8 | −$848 | 16 / ~48k (work + close-out) |
| 102 rent | Facilities | Boss→Facilities, **Facilities→Accounting** | #3 rent $2,400 | −$2,400 | 13 / ~35k |
| 103 hoodies | Accounting | Boss→Accounting, Boss→Inventory, **Inventory→Accounting**, Boss→Customer Service | none. The $264 PO was refused by the cash guard | $0 | 19 / ~52k |

Ending checking balance **$152.00** = `cash_accounts.balance`, and $3,400 − $3,248 of payments = $152. The whole run took 48 model calls and about 135k tokens. Facilities stayed off 101 and 103, and Inventory and Customer Service stayed off 102, so no ticket got "send everyone".

