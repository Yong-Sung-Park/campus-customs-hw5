"""Campus Customs desk API (FastAPI).

Start from backend/:
    uvicorn main:app --reload --port 8000

Every shop read/write goes through the MCP server (mcp_link.call_tool). The one
exception is /api/reset, which is a file copy of the original DB over the working copy.
"""

import asyncio
import os
import shutil
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import audit
import team
from mcp_link import TOOLSET, call_tool
from models import AGENT_LABELS, AGENT_NAMES, ApproveBody, RejectBody, RunStarted

REPO_DIR = Path(__file__).resolve().parent.parent
ORIGINAL_DB = REPO_DIR / "data" / "campus_customs.db"
WORKING_DB = Path(os.environ.get("CAMPUS_CUSTOMS_DB", REPO_DIR / "data" / "campus_customs_new.db"))

_tasks: set[asyncio.Task] = set()  # keep background runs referenced until they finish


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not WORKING_DB.exists():
        shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    async with TOOLSET:  # one MCP server process for the app's lifetime
        try:
            team.get_agents()
        except team.AgentNotConfigured as e:
            print(f"[warn] {e} — the board loads, but runs will fail until .env is set.")
        yield


app = FastAPI(title="Campus Customs Desk API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- helpers

def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _last_reset_seq() -> int:
    return max((e["seq"] for e in audit.recent(limit=5000) if e["step"] == "reset"), default=0)


def _ticket_events(ticket_id: int) -> list[dict]:
    """Events for a ticket since the last DB reset (older runs belong to an earlier DB state)."""
    floor = _last_reset_seq()
    return [e for e in audit.recent(ticket_id=ticket_id, limit=5000) if e["seq"] > floor]


def _run_ids(events: list[dict]) -> list[str]:
    seen: list[str] = []
    for e in events:
        if e["run_id"] not in seen and not e["run_id"].startswith("human"):
            seen.append(e["run_id"])
    return seen


def _agent_summary(ticket_id: int) -> dict:
    """What each agent did on this ticket: tools used, delegations, its own summary line."""
    events = _ticket_events(ticket_id)
    agents: dict[str, dict] = {}
    for name in AGENT_NAMES:
        mine = [e for e in events if e["agent"] == name]
        if not mine:
            continue
        tools = Counter(e["detail"]["tool"] for e in mine if e["step"] == "tool_call" and e["detail"]["tool"] != "delegate")
        finals = [e["detail"].get("output") or {} for e in mine if e["step"] == "final"]
        last = finals[-1] if finals else {}
        agents[name] = {
            "agent": name,
            "label": AGENT_LABELS[name],
            "runs": sum(1 for e in mine if e["step"] == "run_start"),
            "tools_used": dict(tools),
            "delegated_to": [e["detail"]["to"] for e in mine if e["step"] == "delegate"],
            "called_by": sorted({e["detail"].get("called_by") for e in mine if e["step"] == "run_start"} - {None}),
            "summary": last.get("summary") or last.get("outcome") or "",
            "facts": last.get("facts", []),
            "actions_taken": last.get("actions_taken", []),
            "recommendation": last.get("recommendation", ""),
        }
    decision = None
    for e in reversed(events):
        if e["agent"] == "boss" and e["depth"] == 0 and e["step"] == "final":
            decision = e["detail"].get("output")
            break
    approvals = [e["detail"] for e in events if e["step"] == "approval"]
    # Times a safety rule said no: an MCP tool refused (e.g. not enough cash) or a hand-off was blocked.
    refusals = [
        {"agent": e["agent"], "tool": e["detail"]["tool"], "error": e["detail"]["result"].get("error")}
        for e in events
        if e["step"] == "tool_result" and isinstance(e["detail"].get("result"), dict) and e["detail"]["result"].get("refused")
    ] + [
        {"agent": e["agent"], "tool": "delegate", "error": e["detail"].get("reason")}
        for e in events if e["step"] == "delegate_refused"
    ] + [
        {"agent": "human", "tool": "execute_approved_payment", "error": (e["detail"].get("result") or {}).get("error")}
        for e in events if e["step"] == "approval" and not (e["detail"].get("result") or {}).get("ok")
        and e["detail"].get("decision") == "approve"
    ]
    return {"ticket_id": ticket_id, "run_ids": _run_ids(events), "agents": agents,
            "boss_decision": decision, "human_approvals": approvals, "guardrail_refusals": refusals}


async def _pending(ticket_id: int | None = None) -> list[dict]:
    args = {"status": "pending"} | ({"ticket_id": ticket_id} if ticket_id is not None else {})
    return (await call_tool("list_approval_requests", args))["approval_requests"]


# ------------------------------------------------------------------ routes

@app.get("/api/health")
async def health() -> dict:
    db = WORKING_DB.relative_to(REPO_DIR) if WORKING_DB.is_relative_to(REPO_DIR) else WORKING_DB
    return {"ok": True, "model": team.MODEL_NAME, "db": str(db).replace("\\", "/")}


@app.get("/api/tickets")
async def list_tickets() -> dict:
    """The three tickets and whether each is open / in progress / awaiting approval / resolved."""
    data = await call_tool("list_tickets")
    pending = await _pending()
    for t in data["tickets"]:
        t["pending_approvals"] = sum(1 for p in pending if p["ticket_id"] == t["id"])
        t["running_run_id"] = team.running_for(t["id"])
        t["is_resolved"] = t["status"] == "resolved"
    return data


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    data = await call_tool("get_ticket", {"ticket_id": ticket_id})
    if not data.get("found"):
        raise HTTPException(404, data.get("error", "ticket not found"))
    data["customer_drafts"] = (await call_tool("list_drafts", {"ticket_id": ticket_id}))["drafts"]
    data["summary"] = _agent_summary(ticket_id)
    data["running_run_id"] = team.running_for(ticket_id)
    return data


@app.post("/api/tickets/{ticket_id}/run", response_model=RunStarted)
async def run_ticket(ticket_id: int) -> RunStarted:
    """Start the agent team on one ticket (runs in the background; poll /api/events)."""
    t = await call_tool("get_ticket", {"ticket_id": ticket_id})
    if not t.get("found"):
        raise HTTPException(404, t.get("error"))
    if team.running_for(ticket_id):
        raise HTTPException(409, "The team is already working this ticket.")
    status = t["ticket"]["status"]
    if status == "resolved":
        raise HTTPException(409, "Ticket is already resolved. Reset the database to run it again.")
    if status == "awaiting_approval":
        raise HTTPException(409, "Ticket is waiting on a human approval. Approve or reject its requests first.")
    try:
        team.get_agents()
    except team.AgentNotConfigured as e:
        raise HTTPException(503, str(e))
    run_id = team.new_run(ticket_id, "work")
    _spawn(team.work_ticket(ticket_id, run_id))
    return RunStarted(run_id=run_id, ticket_id=ticket_id, status="running")


@app.get("/api/runs")
async def runs(ticket_id: int | None = None) -> dict:
    rows = [r for r in team.RUNS.values() if ticket_id is None or r["ticket_id"] == ticket_id]
    return {"runs": rows}


@app.get("/api/events")
async def events(
    ticket_id: int | None = None,
    run_id: str | None = None,
    since: int = Query(0, description="Only events with seq greater than this"),
    limit: int = Query(400, le=2000),
) -> dict:
    """Recent agent events: what each agent said, tool calls + results, delegations, approvals."""
    floor = max(since, _last_reset_seq())
    rows = audit.recent(ticket_id=ticket_id, run_id=run_id, since=floor, limit=limit)
    return {"events": rows, "last_seq": rows[-1]["seq"] if rows else floor}


@app.get("/api/tickets/{ticket_id}/summary")
async def ticket_summary(ticket_id: int) -> dict:
    """Short summary of what each agent did on this ticket."""
    return _agent_summary(ticket_id)


@app.get("/api/approvals")
async def approvals(status: str | None = None, ticket_id: int | None = None) -> dict:
    args = ({"status": status} if status else {}) | ({"ticket_id": ticket_id} if ticket_id is not None else {})
    return await call_tool("list_approval_requests", args)


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: ApproveBody) -> dict:
    """A human approved a prepared payment/purchase. This is the only route that moves cash."""
    req = next((r for r in (await call_tool("list_approval_requests"))["approval_requests"] if r["id"] == approval_id), None)
    if req is None:
        raise HTTPException(404, f"No approval request {approval_id}.")
    result = await call_tool("execute_approved_payment", {"approval_id": approval_id, "approved_by": body.approved_by})
    ticket_id = req["ticket_id"]
    audit.record(_latest_run(ticket_id), ticket_id, "human", 0, "approval",
                 {"decision": "approve", "approval_id": approval_id, "kind": req["kind"], "amount": req["amount"],
                  "payee": req["payee"], "by": body.approved_by, "result": result})
    if not result.get("ok"):
        raise HTTPException(409, result.get("error", "Payment refused."))
    close_out = await _maybe_close_out(ticket_id)
    cash = await call_tool("get_cash_position")
    return {"result": result, "checking_balance": cash["checking_balance"], "close_out_run_id": close_out}


@app.post("/api/approvals/{approval_id}/reject")
async def reject(approval_id: int, body: RejectBody) -> dict:
    req = next((r for r in (await call_tool("list_approval_requests"))["approval_requests"] if r["id"] == approval_id), None)
    if req is None:
        raise HTTPException(404, f"No approval request {approval_id}.")
    result = await call_tool("reject_approval_request",
                             {"approval_id": approval_id, "rejected_by": body.rejected_by, "reason": body.reason})
    audit.record(_latest_run(req["ticket_id"]), req["ticket_id"], "human", 0, "approval",
                 {"decision": "reject", "approval_id": approval_id, "kind": req["kind"], "amount": req["amount"],
                  "payee": req["payee"], "by": body.rejected_by, "reason": body.reason, "result": result})
    if not result.get("ok"):
        raise HTTPException(409, result.get("error", "Could not reject."))
    return {"result": result, "close_out_run_id": await _maybe_close_out(req["ticket_id"])}


def _latest_run(ticket_id: int) -> str:
    ids = _run_ids(_ticket_events(ticket_id))
    return ids[-1] if ids else f"human-{ticket_id}"


async def _maybe_close_out(ticket_id: int | None) -> str | None:
    """When the last pending request on a ticket is decided, the Boss closes it out."""
    if ticket_id is None or await _pending(ticket_id) or team.running_for(ticket_id):
        return None
    t = await call_tool("get_ticket", {"ticket_id": ticket_id})
    if t["ticket"]["status"] == "resolved":
        return None
    run_id = team.new_run(ticket_id, "close_out")
    _spawn(team.close_out_ticket(ticket_id, run_id))
    return run_id


@app.get("/api/cash")
async def cash() -> dict:
    """Current checking balance from cash_accounts, plus the payments ledger and pending requests."""
    pos = await call_tool("get_cash_position")
    pays = await call_tool("list_payments")
    return {**pos, "payments": pays["payments"], "total_paid": pays["total_paid"]}


@app.get("/api/drafts")
async def drafts(ticket_id: int | None = None) -> dict:
    return await call_tool("list_drafts", {"ticket_id": ticket_id} if ticket_id is not None else {})


@app.get("/api/agents")
async def agents() -> dict:
    return {"agents": [{"id": n, "label": AGENT_LABELS[n], "tools": sorted(team.TOOL_ACCESS[n])} for n in AGENT_NAMES],
            "model": team.MODEL_NAME}


@app.post("/api/reset")
async def reset() -> dict:
    """Copy the original DB over the working copy for a fresh run. The audit trail is kept."""
    if any(r["status"] == "running" for r in team.RUNS.values()):
        raise HTTPException(409, "A run is in progress. Wait for it to finish before resetting.")
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    team.RUNS.clear()
    cash = await call_tool("get_cash_position")
    audit.record("reset", 0, "board", 0, "reset",
                 {"copied": f"{ORIGINAL_DB.name} -> {WORKING_DB.name}", "checking_balance": cash["checking_balance"]})
    return {"ok": True, "checking_balance": cash["checking_balance"], "tickets": (await call_tool("list_tickets"))["tickets"]}
