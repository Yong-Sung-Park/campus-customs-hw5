"""Campus Customs MCP server (FastMCP).

The single source of shop facts for every agent. All tools read and write the
WORKING copy `data/campus_customs_new.db`; the original `campus_customs.db` is
never opened here, so it stays clean for resets.

Run over stdio (what Claude Code and the backend agents use):
    python mcp_server/server.py

Money rules enforced here (not just in prompts):
  * Agents can only PREPARE a payment (an `approval_requests` row). Amounts are
    read from the DB, never typed in by an agent.
  * `execute_approved_payment` is the only tool that moves cash. The backend's
    human approve route is its only caller, and it refuses to go below $0.
  * A purchase order cannot be paid while its vendor has an open invoice.
"""

import calendar
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from fastmcp import FastMCP

REPO_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_DB", REPO_DIR / "data" / "campus_customs_new.db"))

AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer_service", "customer service"}
MAX_PO_QTY = 100  # sanity cap on a single purchase order line
RENT_EARLY_WINDOW_DAYS = 31  # don't prepay rent that is more than a month out

mcp = FastMCP(
    "campus-customs",
    instructions=(
        "Shop tools for Campus Customs. Every number comes straight from "
        "data/campus_customs_new.db. 'Today' is desk.date_today, not the real clock. "
        "Agents prepare payments; only a human approval executes them."
    ),
)

# Workflow tables the agents write to. The original DB doesn't have them, so they
# are created on demand (and disappear on reset, which is what we want).
WORKFLOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    kind TEXT NOT NULL,              -- invoice | rent | purchase_order
    ref_id INTEGER NOT NULL,         -- invoices.id | leases.id | purchase_orders.id
    payee TEXT NOT NULL,
    amount REAL NOT NULL,
    reason TEXT,
    requested_by TEXT NOT NULL,      -- agent that prepared it
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    payment_id INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    vendor_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_approval',  -- awaiting_approval | ordered | cancelled
    created_at TEXT NOT NULL,
    ordered_at TEXT,
    expected_arrival TEXT
);
CREATE TABLE IF NOT EXISTS message_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- always 'draft': nothing is ever sent
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_outcomes (
    ticket_id INTEGER PRIMARY KEY,
    outcome TEXT NOT NULL,
    resolved_by TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- db helpers

def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Working DB not found at {DB_PATH}. Copy data/campus_customs.db to data/campus_customs_new.db first."
        )
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(WORKFLOW_SCHEMA)
    return con


def query(sql: str, params: tuple = ()) -> list[dict]:
    with closing(connect()) as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def today() -> date:
    row = query_one("SELECT date_today FROM desk LIMIT 1")
    return date.fromisoformat(row["date_today"])


def now_stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def money(x: float) -> float:
    return round(float(x), 2)


def add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def checking_balance() -> float:
    return float(query_one("SELECT balance FROM cash_accounts WHERE name = 'checking'")["balance"])


def pending_total() -> float:
    row = query_one("SELECT COALESCE(SUM(amount), 0) AS t FROM approval_requests WHERE status = 'pending'")
    return float(row["t"])


def open_invoices_for(vendor_id: int) -> list[dict]:
    t = today()
    rows = query("SELECT * FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY due_date", (vendor_id,))
    for r in rows:
        r["days_overdue"] = max(0, (t - date.fromisoformat(r["due_date"])).days)
    return rows


def pending_request_for(kind: str, ref_id: int) -> dict | None:
    return query_one(
        "SELECT * FROM approval_requests WHERE kind = ? AND ref_id = ? AND status = 'pending'", (kind, ref_id)
    )


def cash_guard(amount: float) -> dict | None:
    """Refuse to queue a request the shop could not pay after everything already pending."""
    bal, pend = checking_balance(), pending_total()
    available = bal - pend
    if amount > available + 1e-9:
        return {
            "ok": False,
            "refused": True,
            "error": (
                f"Not enough cash: this needs ${amount:,.2f} but checking has ${bal:,.2f} "
                f"with ${pend:,.2f} already pending approval (available ${available:,.2f}). "
                "Cash cannot go negative."
            ),
            "checking_balance": money(bal),
            "pending_approvals_total": money(pend),
            "available_after_pending": money(available),
        }
    return None


def is_agent_name(name: str) -> bool:
    return name.strip().lower().replace("-", "_") in AGENT_NAMES or name.strip().lower() in AGENT_NAMES


# ============================================================ read-only tools

@mcp.tool
def get_shop_date() -> dict:
    """The shop's 'today' (reads `desk`). Use this for every due/overdue/ETA question — never the real clock."""
    row = query_one("SELECT date_today, notes FROM desk LIMIT 1")
    return {"date_today": row["date_today"], "desk_notes": row["notes"]}


@mcp.tool
def list_tickets() -> dict:
    """Every ticket on the board with its status and, once resolved, its outcome (reads `tickets`, `ticket_outcomes`)."""
    rows = query(
        """SELECT t.id, t.type, t.requester, t.subject, t.sku, t.size, t.qty, t.lease_id, t.invoice_id,
                  t.status, t.notes, t.created_at, o.outcome, o.resolved_by, o.resolved_at
           FROM tickets t LEFT JOIN ticket_outcomes o ON o.ticket_id = t.id ORDER BY t.id"""
    )
    return {"date_today": today().isoformat(), "tickets": rows}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """One ticket in full (reads `tickets`, plus the current `invoices`/`leases` row it links to), and what is already in flight for it:
    pending/decided approval requests, purchase orders, customer drafts, and the outcome if resolved.

    The `links` block says which specialist owns the next step: sku/size -> Inventory,
    invoice_id -> Accounting, lease_id -> Facilities.
    """
    t = query_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if t is None:
        return {"found": False, "error": f"No ticket {ticket_id}."}
    linked = {}
    if t["invoice_id"] is not None:
        linked["invoice"] = query_one(
            "SELECT i.id, i.vendor_id, v.name AS vendor_name, i.amount, i.due_date, i.status, i.description "
            "FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?", (t["invoice_id"],))
    if t["lease_id"] is not None:
        linked["lease"] = query_one("SELECT id, space_name, landlord, monthly_rent, next_due FROM leases WHERE id = ?", (t["lease_id"],))
    return {
        "found": True,
        "date_today": today().isoformat(),
        "ticket": t,
        "linked_records_now": linked,
        "links": {
            "sku": t["sku"], "size": t["size"], "qty": t["qty"],
            "invoice_id": t["invoice_id"], "lease_id": t["lease_id"],
        },
        "approval_requests": query("SELECT * FROM approval_requests WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
        "purchase_orders": query("SELECT * FROM purchase_orders WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
        "customer_drafts": query("SELECT id, recipient, subject, author, status FROM message_drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
        "outcome": query_one("SELECT * FROM ticket_outcomes WHERE ticket_id = ?", (ticket_id,)),
    }


@mcp.tool
def check_stock(sku: str, size: str) -> dict:
    """Units on hand for one SKU in one size (reads `inventory`).

    Returns the requested line (name, qty, location) plus every other size of the
    same SKU, so you can see a shortfall and what sizes are in stock instead.
    Use this before promising any customer an item. Example: check_stock("CC-TEE-WHITE", "S").
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    lines = query("SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? ORDER BY rowid", (sku,))
    if not lines:
        known = [r["sku"] for r in query("SELECT DISTINCT sku FROM inventory ORDER BY sku")]
        return {"found": False, "error": f"No SKU {sku} in inventory.", "known_skus": known}
    match = next((l for l in lines if l["size"] == size), None)
    if match is None:
        return {
            "found": False,
            "error": f"{sku} has no size {size}.",
            "sizes": [{"size": l["size"], "qty": l["qty"]} for l in lines],
        }
    return {
        "found": True,
        "sku": sku,
        "name": match["name"],
        "size": size,
        "qty_on_hand": match["qty"],
        "in_stock": match["qty"] > 0,
        "location": match["location"],
        "all_sizes": [{"size": l["size"], "qty": l["qty"]} for l in lines],
    }


@mcp.tool
def get_pricing(sku: str, discount_pct: float | None = None) -> dict:
    """Unit cost, list price, and margin for one SKU (reads `pricing`).

    Pass discount_pct (e.g. 15 for 15% off list) to also get the discounted unit
    price and the margin that price leaves. Use this before agreeing to any
    price override so the shop never sells below cost.
    """
    sku = sku.strip().upper()
    p = query_one("SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,))
    if p is None:
        return {"found": False, "error": f"No pricing row for {sku}."}
    cost, list_price = float(p["unit_cost"]), float(p["list_price"])
    out = {
        "found": True,
        "sku": sku,
        "unit_cost": money(cost),
        "list_price": money(list_price),
        "margin_per_unit_at_list": money(list_price - cost),
        "margin_pct_at_list": round((list_price - cost) / list_price * 100, 1),
    }
    if discount_pct is not None:
        if not 0 <= discount_pct < 100:
            return {**out, "error": "discount_pct must be between 0 and 100."}
        price = list_price * (1 - discount_pct / 100)
        out.update(
            discount_pct=discount_pct,
            discounted_price=money(price),
            margin_per_unit_at_discount=money(price - cost),
            margin_pct_at_discount=round((price - cost) / price * 100, 1),
            below_cost=price < cost,
        )
    return out


@mcp.tool
def quote_bulk_order(sku: str, size: str, qty: int, discount_pct: float = 0) -> dict:
    """Price a bulk order end to end (reads `pricing` and `inventory`).

    Returns the discounted unit price, order revenue, cost of goods, gross margin,
    how many units are on hand vs the shortfall, and what restocking the
    shortfall would cost at unit_cost. Use it to judge a bulk-discount request.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    p = query_one("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,))
    inv = query_one("SELECT name, qty FROM inventory WHERE sku = ? AND size = ?", (sku, size))
    if p is None or inv is None:
        return {"found": False, "error": f"No pricing or inventory row for {sku} size {size}."}
    if qty <= 0 or not 0 <= discount_pct < 100:
        return {"found": True, "error": "qty must be > 0 and discount_pct between 0 and 100."}
    cost, list_price = float(p["unit_cost"]), float(p["list_price"])
    unit_price = list_price * (1 - discount_pct / 100)
    revenue, cogs = unit_price * qty, cost * qty
    shortfall = max(0, qty - inv["qty"])
    return {
        "found": True,
        "sku": sku, "name": inv["name"], "size": size, "qty_requested": qty,
        "list_price": money(list_price), "discount_pct": discount_pct,
        "unit_price": money(unit_price), "unit_cost": money(cost),
        "order_revenue": money(revenue), "cost_of_goods": money(cogs),
        "gross_margin": money(revenue - cogs),
        "gross_margin_pct": round((revenue - cogs) / revenue * 100, 1) if revenue else None,
        "below_cost": unit_price < cost,
        "qty_on_hand": inv["qty"], "shortfall": shortfall,
        "restock_cost_for_shortfall": money(shortfall * cost),
    }


@mcp.tool
def list_vendors() -> dict:
    """Every vendor with specialty, lead time, open-invoice count and whether it can ship now (reads `vendors`, `invoices`)."""
    t = today()
    out = []
    for v in query("SELECT * FROM vendors ORDER BY id"):
        open_inv = open_invoices_for(v["id"])
        out.append({
            **v,
            "open_invoices": len(open_inv),
            "can_ship": not open_inv,
            "eta_if_ordered_today": (t + timedelta(days=v["lead_days"])).isoformat(),
        })
    return {"date_today": t.isoformat(), "vendors": out}


@mcp.tool
def get_vendor_status(vendor_id: int) -> dict:
    """Can this vendor ship right now? (reads `vendors`, `invoices`, `desk`).

    A vendor will NOT ship new product while it has any open unpaid invoice.
    Returns the vendor, its open invoices (with days overdue vs desk.date_today),
    can_ship, lead_days, and the arrival date if an order were placed today.
    """
    v = query_one("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
    if v is None:
        return {"found": False, "error": f"No vendor {vendor_id}."}
    t = today()
    open_inv = open_invoices_for(vendor_id)
    for inv in open_inv:
        req = pending_request_for("invoice", inv["id"])
        inv["payment_request_pending"] = req["id"] if req else None
    return {
        "found": True,
        "vendor": v,
        "date_today": t.isoformat(),
        "open_invoices": open_inv,
        "can_ship": not open_inv,
        "blocked_reason": None if not open_inv else
            f"{v['name']} will not ship until invoice(s) {', '.join(str(i['id']) for i in open_inv)} are paid.",
        "lead_days": v["lead_days"],
        "eta_if_ordered_today": (t + timedelta(days=v["lead_days"])).isoformat(),
    }


@mcp.tool
def get_invoice(invoice_id: int) -> dict:
    """One vendor invoice with vendor name, status and days overdue vs desk.date_today (reads `invoices`, `vendors`)."""
    inv = query_one(
        "SELECT i.*, v.name AS vendor_name, v.lead_days FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
        (invoice_id,),
    )
    if inv is None:
        return {"found": False, "error": f"No invoice {invoice_id}."}
    t = today()
    days = (t - date.fromisoformat(inv["due_date"])).days
    req = pending_request_for("invoice", invoice_id)
    return {
        "found": True, "invoice": inv, "date_today": t.isoformat(),
        "is_open": inv["status"] == "open",
        "days_overdue": max(0, days) if inv["status"] == "open" else 0,
        "overdue": inv["status"] == "open" and days > 0,
        "payment_request_pending": req["id"] if req else None,
    }


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Rent details for one lease (reads `leases` and `desk.date_today`).

    Returns the space, landlord, monthly rent, next due date, and how many days
    until it is due (negative = overdue) measured from the shop's date_today.
    """
    lease = query_one("SELECT * FROM leases WHERE id = ?", (lease_id,))
    if lease is None:
        return {"found": False, "error": f"No lease with id {lease_id}."}
    t = today()
    days = (date.fromisoformat(lease["next_due"]) - t).days
    req = pending_request_for("rent", lease_id)
    return {
        "found": True,
        "lease_id": lease["id"],
        "space_name": lease["space_name"],
        "landlord": lease["landlord"],
        "monthly_rent": money(lease["monthly_rent"]),
        "next_due": lease["next_due"],
        "date_today": t.isoformat(),
        "days_until_due": days,
        "overdue": days < 0,
        "notes": lease["notes"],
        "payment_request_pending": req["id"] if req else None,
    }


@mcp.tool
def get_cash_position() -> dict:
    """Cash picture for decisions (reads `cash_accounts`, `approval_requests`, `invoices`, `leases`).

    Returns the checking balance, everything pending human approval, cash left
    after those, and known obligations not yet requested (open vendor invoices,
    rent due within 30 days) so you never spend money that a bill already needs.
    Cash only goes out in this shop — there is no incoming revenue to count on.
    """
    t = today()
    acct = query_one("SELECT * FROM cash_accounts WHERE name = 'checking'")
    pending = query("SELECT id, ticket_id, kind, ref_id, payee, amount, requested_by FROM approval_requests WHERE status = 'pending' ORDER BY id")
    pend_total = sum(p["amount"] for p in pending)
    obligations = []
    for inv in query("SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.status = 'open'"):
        if not pending_request_for("invoice", inv["id"]):
            obligations.append({"kind": "invoice", "ref_id": inv["id"], "payee": inv["vendor_name"],
                                "amount": money(inv["amount"]), "due": inv["due_date"]})
    for l in query("SELECT * FROM leases"):
        due = date.fromisoformat(l["next_due"])
        if (due - t).days <= 30 and not pending_request_for("rent", l["id"]):
            obligations.append({"kind": "rent", "ref_id": l["id"], "payee": l["landlord"],
                                "amount": money(l["monthly_rent"]), "due": l["next_due"]})
    obl_total = sum(o["amount"] for o in obligations)
    return {
        "date_today": t.isoformat(),
        "account": "checking",
        "checking_balance": money(acct["balance"]),
        "balance_as_of": acct["date"],
        "pending_approvals": pending,
        "pending_approvals_total": money(pend_total),
        "available_after_pending": money(acct["balance"] - pend_total),
        "unrequested_obligations": obligations,
        "unrequested_obligations_total": money(obl_total),
        "free_cash_after_obligations": money(acct["balance"] - pend_total - obl_total),
    }


@mcp.tool
def list_payments() -> dict:
    """Every payment already made, with who approved it (reads `payments`). Check this to avoid paying anything twice."""
    rows = query("SELECT * FROM payments ORDER BY id")
    return {"payments": rows, "total_paid": money(sum(r["amount"] for r in rows))}


@mcp.tool
def list_approval_requests(ticket_id: int | None = None, status: str | None = None) -> dict:
    """Payment / purchase requests waiting on (or decided by) a human (reads `approval_requests`).
    Filter by ticket_id and/or status ('pending', 'approved', 'rejected')."""
    sql, params = "SELECT * FROM approval_requests WHERE 1=1", []
    if ticket_id is not None:
        sql += " AND ticket_id = ?"; params.append(ticket_id)
    if status:
        sql += " AND status = ?"; params.append(status)
    rows = query(sql + " ORDER BY id", tuple(params))
    return {"approval_requests": rows, "count": len(rows)}


@mcp.tool
def list_purchase_orders(ticket_id: int | None = None) -> dict:
    """Purchase orders with vendor, qty, total, status and expected arrival (reads `purchase_orders`, `vendors`)."""
    sql = "SELECT p.*, v.name AS vendor_name, v.lead_days FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id"
    rows = query(sql + (" WHERE p.ticket_id = ?" if ticket_id is not None else "") + " ORDER BY p.id",
                 (ticket_id,) if ticket_id is not None else ())
    return {"purchase_orders": rows}


@mcp.tool
def list_drafts(ticket_id: int | None = None) -> dict:
    """Customer message drafts saved on the board (reads `message_drafts`). Drafts are never sent."""
    rows = query("SELECT * FROM message_drafts" + (" WHERE ticket_id = ?" if ticket_id is not None else "") + " ORDER BY id",
                 (ticket_id,) if ticket_id is not None else ())
    return {"drafts": rows}


# ============================================== agent write tools (no cash moves)

@mcp.tool
def prepare_invoice_payment(invoice_id: int, ticket_id: int, requested_by: str, reason: str) -> dict:
    """Queue a vendor invoice for HUMAN approval (writes `approval_requests`; reads `invoices`, `cash_accounts`).

    The amount is the invoice amount from the DB. No cash moves until a human
    approves on the board. Refuses if the invoice is not open, is already queued,
    or cash (after other pending requests) can't cover it.
    """
    inv = query_one("SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?", (invoice_id,))
    if inv is None:
        return {"ok": False, "error": f"No invoice {invoice_id}."}
    if inv["status"] != "open":
        return {"ok": False, "error": f"Invoice {invoice_id} is '{inv['status']}', not open — nothing to pay."}
    if (req := pending_request_for("invoice", invoice_id)):
        return {"ok": False, "error": f"Invoice {invoice_id} already has pending request #{req['id']}.", "request": req}
    if (refusal := cash_guard(inv["amount"])):
        return refusal
    with closing(connect()) as con, con:
        cur = con.execute(
            """INSERT INTO approval_requests (ticket_id, kind, ref_id, payee, amount, reason, requested_by, created_at)
               VALUES (?, 'invoice', ?, ?, ?, ?, ?, ?)""",
            (ticket_id, invoice_id, inv["vendor_name"], inv["amount"], reason, requested_by, now_stamp()),
        )
        rid = cur.lastrowid
    return {"ok": True, "status": "pending_human_approval",
            "request": query_one("SELECT * FROM approval_requests WHERE id = ?", (rid,)),
            "note": "Nothing is paid yet. A human must approve this on the board."}


@mcp.tool
def prepare_rent_payment(lease_id: int, ticket_id: int, requested_by: str, reason: str) -> dict:
    """Queue this month's rent for HUMAN approval (writes `approval_requests`; reads `leases`, `cash_accounts`).

    The amount is leases.monthly_rent. Refuses if already queued, if the rent is
    more than a month away, or if cash (after other pending requests) can't cover it.
    """
    lease = query_one("SELECT * FROM leases WHERE id = ?", (lease_id,))
    if lease is None:
        return {"ok": False, "error": f"No lease {lease_id}."}
    if (req := pending_request_for("rent", lease_id)):
        return {"ok": False, "error": f"Rent for lease {lease_id} already has pending request #{req['id']}.", "request": req}
    days = (date.fromisoformat(lease["next_due"]) - today()).days
    if days > RENT_EARLY_WINDOW_DAYS:
        return {"ok": False, "error": f"Rent is not due until {lease['next_due']} ({days} days) — too early to pay."}
    if (refusal := cash_guard(lease["monthly_rent"])):
        return refusal
    with closing(connect()) as con, con:
        cur = con.execute(
            """INSERT INTO approval_requests (ticket_id, kind, ref_id, payee, amount, reason, requested_by, created_at)
               VALUES (?, 'rent', ?, ?, ?, ?, ?, ?)""",
            (ticket_id, lease_id, lease["landlord"], lease["monthly_rent"], reason, requested_by, now_stamp()),
        )
        rid = cur.lastrowid
    return {"ok": True, "status": "pending_human_approval",
            "request": query_one("SELECT * FROM approval_requests WHERE id = ?", (rid,)),
            "rent_due": lease["next_due"], "days_until_due": days,
            "note": "Nothing is paid yet. A human must approve this on the board."}


@mcp.tool
def prepare_purchase_order(vendor_id: int, sku: str, size: str, qty: int, ticket_id: int, requested_by: str, reason: str) -> dict:
    """Draft a restock purchase order and queue it for HUMAN approval
    (writes `purchase_orders`, `approval_requests`; reads `vendors`, `pricing`, `inventory`, `invoices`, `cash_accounts`).

    Total = qty x pricing.unit_cost. Arrival = approval date + vendors.lead_days.
    If the vendor has an open invoice the PO is still drafted but flagged as
    blocked: the approve step will refuse it until that invoice is paid.
    Refuses if cash (after other pending requests) can't cover the total.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    v = query_one("SELECT * FROM vendors WHERE id = ?", (vendor_id,))
    p = query_one("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,))
    inv = query_one("SELECT name FROM inventory WHERE sku = ? AND size = ?", (sku, size))
    if v is None:
        return {"ok": False, "error": f"No vendor {vendor_id}."}
    if p is None or inv is None:
        return {"ok": False, "error": f"No pricing/inventory row for {sku} size {size}."}
    if not 0 < qty <= MAX_PO_QTY:
        return {"ok": False, "error": f"qty must be between 1 and {MAX_PO_QTY}."}
    total = money(p["unit_cost"] * qty)
    if (refusal := cash_guard(total)):
        refusal["max_affordable_qty"] = int(max(0, refusal["available_after_pending"]) // p["unit_cost"])
        refusal["unit_cost"] = money(p["unit_cost"])
        return refusal
    with closing(connect()) as con, con:
        cur = con.execute(
            """INSERT INTO purchase_orders (ticket_id, vendor_id, sku, size, qty, unit_cost, total, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticket_id, vendor_id, sku, size, qty, p["unit_cost"], total, now_stamp()),
        )
        po_id = cur.lastrowid
        cur = con.execute(
            """INSERT INTO approval_requests (ticket_id, kind, ref_id, payee, amount, reason, requested_by, created_at)
               VALUES (?, 'purchase_order', ?, ?, ?, ?, ?, ?)""",
            (ticket_id, po_id, v["name"], total, reason, requested_by, now_stamp()),
        )
        rid = cur.lastrowid
    blockers = open_invoices_for(vendor_id)
    return {
        "ok": True, "status": "pending_human_approval",
        "purchase_order": query_one("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)),
        "request": query_one("SELECT * FROM approval_requests WHERE id = ?", (rid,)),
        "expected_arrival_if_approved_today": (today() + timedelta(days=v["lead_days"])).isoformat(),
        "blocked_by_open_invoices": [b["id"] for b in blockers],
        "note": ("Vendor has an open invoice: the human must approve that invoice payment FIRST, "
                 "or this PO will be refused.") if blockers else "Nothing is paid yet. A human must approve this on the board.",
    }


@mcp.tool
def save_customer_draft(ticket_id: int, recipient: str, subject: str, body: str, author: str) -> dict:
    """Save a customer-facing message as a DRAFT on the board (writes `message_drafts`).
    Nothing is emailed or sent — a human copies it out if they choose to."""
    if not body.strip():
        return {"ok": False, "error": "Draft body is empty."}
    with closing(connect()) as con, con:
        cur = con.execute(
            "INSERT INTO message_drafts (ticket_id, recipient, subject, body, author, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, recipient, subject, body, author, now_stamp()),
        )
        did = cur.lastrowid
    return {"ok": True, "draft_id": did, "status": "draft", "note": "Saved on the board only — not sent."}


@mcp.tool
def resolve_ticket(ticket_id: int, outcome: str, resolved_by: str) -> dict:
    """Close a ticket with a short outcome (writes `tickets.status`, `ticket_outcomes`).

    Refuses while any of this ticket's payment requests are still pending a human
    decision — the ticket can only close once the money side is settled.
    """
    t = query_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if t is None:
        return {"ok": False, "error": f"No ticket {ticket_id}."}
    pending = query("SELECT id, kind, amount FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,))
    if pending:
        return {"ok": False, "error": "Ticket still has payment requests waiting on a human.", "pending": pending}
    with closing(connect()) as con, con:
        con.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
        con.execute(
            """INSERT INTO ticket_outcomes (ticket_id, outcome, resolved_by, resolved_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(ticket_id) DO UPDATE SET outcome = excluded.outcome,
                 resolved_by = excluded.resolved_by, resolved_at = excluded.resolved_at""",
            (ticket_id, outcome, resolved_by, now_stamp()),
        )
    return {"ok": True, "ticket_id": ticket_id, "status": "resolved", "outcome": outcome}


# ================================== human-only tools (backend routes, never agents)

@mcp.tool
def set_ticket_status(ticket_id: int, status: str) -> dict:
    """[backend only] Move a ticket between open / in_progress / awaiting_approval (writes `tickets`).
    Resolving goes through resolve_ticket."""
    if status not in {"open", "in_progress", "awaiting_approval"}:
        return {"ok": False, "error": "status must be open, in_progress or awaiting_approval."}
    with closing(connect()) as con, con:
        n = con.execute("UPDATE tickets SET status = ? WHERE id = ? AND status != 'resolved'", (status, ticket_id)).rowcount
    return {"ok": bool(n), "ticket_id": ticket_id, "status": status if n else "unchanged (missing or already resolved)"}


@mcp.tool
def execute_approved_payment(approval_id: int, approved_by: str) -> dict:
    """[HUMAN APPROVAL ONLY — called by the backend approve route, never by an agent]
    Pay one pending request (writes `payments`, `cash_accounts`, `approval_requests`,
    and the invoice / lease / purchase order it pays for).

    Refuses if: the request isn't pending, the approver looks like an agent,
    checking would go below $0, or a PO's vendor still has an open invoice.
    """
    if not approved_by or not approved_by.strip() or is_agent_name(approved_by):
        return {"ok": False, "refused": True, "error": "A named human must approve payments."}
    req = query_one("SELECT * FROM approval_requests WHERE id = ?", (approval_id,))
    if req is None:
        return {"ok": False, "error": f"No approval request {approval_id}."}
    if req["status"] != "pending":
        return {"ok": False, "error": f"Request {approval_id} is already {req['status']}."}

    t = today()
    po = None
    if req["kind"] == "invoice":
        inv = query_one("SELECT * FROM invoices WHERE id = ?", (req["ref_id"],))
        if inv is None or inv["status"] != "open":
            return {"ok": False, "refused": True, "error": f"Invoice {req['ref_id']} is not open."}
    elif req["kind"] == "rent":
        if query_one("SELECT id FROM leases WHERE id = ?", (req["ref_id"],)) is None:
            return {"ok": False, "refused": True, "error": f"Lease {req['ref_id']} not found."}
    elif req["kind"] == "purchase_order":
        po = query_one("SELECT p.*, v.lead_days, v.name AS vendor_name FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id WHERE p.id = ?", (req["ref_id"],))
        if po is None or po["status"] != "awaiting_approval":
            return {"ok": False, "refused": True, "error": f"PO {req['ref_id']} is not awaiting approval."}
        blockers = open_invoices_for(po["vendor_id"])
        if blockers:
            return {"ok": False, "refused": True,
                    "error": f"{po['vendor_name']} still has open invoice(s) {[b['id'] for b in blockers]} — "
                             "it will not ship. Approve the invoice payment first."}
    else:
        return {"ok": False, "error": f"Unknown request kind {req['kind']}."}

    with closing(connect()) as con, con:
        bal = float(con.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"])
        if bal - req["amount"] < -1e-9:
            return {"ok": False, "refused": True,
                    "error": f"Refused: paying ${req['amount']:,.2f} would take checking (${bal:,.2f}) negative.",
                    "checking_balance": money(bal)}
        new_bal = money(bal - req["amount"])
        cur = con.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, 'checking', ?, ?)",
            (req["kind"], req["ref_id"], req["amount"], t.isoformat(), approved_by.strip()),
        )
        pay_id = cur.lastrowid
        con.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'", (new_bal, t.isoformat()))
        effect = {}
        if req["kind"] == "invoice":
            con.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (req["ref_id"],))
            effect = {"invoice_id": req["ref_id"], "invoice_status": "paid"}
        elif req["kind"] == "rent":
            lease = con.execute("SELECT next_due FROM leases WHERE id = ?", (req["ref_id"],)).fetchone()
            nxt = add_month(date.fromisoformat(lease["next_due"])).isoformat()
            con.execute("UPDATE leases SET next_due = ? WHERE id = ?", (nxt, req["ref_id"]))
            effect = {"lease_id": req["ref_id"], "paid_period_due": lease["next_due"], "next_due_now": nxt}
        else:
            eta = (t + timedelta(days=po["lead_days"])).isoformat()
            con.execute("UPDATE purchase_orders SET status = 'ordered', ordered_at = ?, expected_arrival = ? WHERE id = ?",
                        (t.isoformat(), eta, po["id"]))
            effect = {"purchase_order_id": po["id"], "po_status": "ordered", "expected_arrival": eta}
        con.execute(
            "UPDATE approval_requests SET status = 'approved', decided_by = ?, decided_at = ?, payment_id = ? WHERE id = ?",
            (approved_by.strip(), now_stamp(), pay_id, approval_id),
        )
    return {"ok": True, "approval_id": approval_id, "payment_id": pay_id, "kind": req["kind"],
            "amount": money(req["amount"]), "balance_before": money(bal), "balance_after": new_bal,
            "approved_by": approved_by.strip(), "paid_at": t.isoformat(), **effect}


@mcp.tool
def reject_approval_request(approval_id: int, rejected_by: str, reason: str = "") -> dict:
    """[HUMAN ONLY — backend reject route] Decline a pending request; no cash moves (writes `approval_requests`, `purchase_orders`)."""
    req = query_one("SELECT * FROM approval_requests WHERE id = ?", (approval_id,))
    if req is None or req["status"] != "pending":
        return {"ok": False, "error": f"Request {approval_id} is not pending."}
    with closing(connect()) as con, con:
        con.execute(
            "UPDATE approval_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (rejected_by, now_stamp(), reason, approval_id),
        )
        if req["kind"] == "purchase_order":
            con.execute("UPDATE purchase_orders SET status = 'cancelled' WHERE id = ?", (req["ref_id"],))
    return {"ok": True, "approval_id": approval_id, "status": "rejected"}


if __name__ == "__main__":
    mcp.run(show_banner=False)
