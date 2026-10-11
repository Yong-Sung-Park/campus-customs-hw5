"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, Customer Service.

* Every agent is a PydanticAI Agent on gpt-6-luna through Portkey (Responses API).
* Shop facts and writes come only from the MCP server (mcp_link.TOOLSET), filtered
  per role by TOOL_ACCESS. No agent can see the tools that move cash.
* Full connectivity: every agent has a `delegate` tool that can reach any other
  agent. Guards: no self-delegation, no cycles inside one chain, a max depth, a
  delegation budget, and one UsageLimits shared by the whole ticket run.
* Every agent-loop step is appended to output/audit_trail.json (audit.record).
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import RetryPromptPart, TextPart, ThinkingPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage, UsageLimits

import audit
from mcp_link import TOOLSET, call_tool
from models import AGENT_LABELS, AGENT_NAMES, AgentName, BossDecision, RunState, SpecialistReport, TeamDeps

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR.parent / ".env")

# --------------------------------------------------------------------- model
MODEL_NAME = "gpt-6-luna"  # the ONLY model used anywhere in this project
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
# Chat Completions rejects function tools + reasoning on gpt-6-luna, so we use the
# Responses API. Low reasoning effort keeps multi-agent token burn down.
MODEL_SETTINGS = OpenAIResponsesModelSettings(openai_reasoning_effort="low")

# -------------------------------------------------------------------- limits
RUN_LIMITS = UsageLimits(request_limit=60, tool_calls_limit=90, total_tokens_limit=400_000)
MAX_DEPTH = 2          # Boss is depth 0; a specialist it calls is 1; that specialist's helper is 2 (can't delegate further)
MAX_DELEGATIONS = 8    # per ticket run, across all agents
OUTPUT_RETRIES = 2

PROMPTS_DIR = BACKEND_DIR / "prompts"

# Least privilege: each role sees only the MCP tools its job needs.
# execute_approved_payment / reject_approval_request / set_ticket_status are never listed: humans/backend only.
COMMON = {"get_ticket", "get_shop_date"}
TOOL_ACCESS: dict[str, set[str]] = {
    "boss": COMMON | {"list_tickets", "get_cash_position", "list_approval_requests", "list_purchase_orders",
                      "list_drafts", "list_payments", "resolve_ticket"},
    "inventory": COMMON | {"check_stock", "list_vendors", "get_vendor_status", "get_pricing", "list_purchase_orders"},
    "accounting": COMMON | {"get_cash_position", "get_invoice", "get_vendor_status", "get_pricing", "quote_bulk_order",
                            "list_payments", "list_approval_requests", "list_purchase_orders",
                            "prepare_invoice_payment", "prepare_rent_payment", "prepare_purchase_order"},
    "facilities": COMMON | {"get_lease", "get_cash_position", "list_payments", "list_approval_requests"},
    "customer_service": COMMON | {"check_stock", "list_purchase_orders", "list_approval_requests", "list_drafts",
                                  "save_customer_draft"},
}
HUMAN_ONLY_TOOLS = {"execute_approved_payment", "reject_approval_request", "set_ticket_status"}
assert not any(HUMAN_ONLY_TOOLS & tools for tools in TOOL_ACCESS.values())


class AgentNotConfigured(RuntimeError):
    pass


def make_model() -> OpenAIResponsesModel:
    key = os.environ.get("PORTKEY_API_KEY")
    if not key:
        raise AgentNotConfigured("PORTKEY_API_KEY is not set in .env")
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL, default_headers={"x-portkey-api-key": key})
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# ------------------------------------------------------------- the team

def _runtime_context(ctx: RunContext[TeamDeps]) -> str:
    d = ctx.deps
    caller = AGENT_LABELS[d.chain[-2]] if len(d.chain) > 1 else "the human operator (board)"
    others = ", ".join(f"{n} ({AGENT_LABELS[n]})" for n in AGENT_NAMES if n != d.agent)
    can_delegate = d.depth < MAX_DEPTH
    return (
        "## Run context\n"
        f"- You are **{AGENT_LABELS[d.agent]}** (`{d.agent}`). Ticket: **{d.state.ticket_id}**. Phase: `{d.state.phase}`.\n"
        f"- You were called by: {caller}. Delegation chain so far: {' -> '.join(d.chain)} (depth {d.depth}).\n"
        f"- Teammates you can delegate to with `delegate(to_agent, task)`: {others}.\n"
        f"- Delegation {'is available' if can_delegate else 'is NOT available at your depth — answer with what you have'}; "
        f"budget used {d.state.delegations_used}/{MAX_DELEGATIONS}. Agents already above you in the chain can't be called back — return your findings to them instead.\n"
        "- Always pass `requested_by` / `author` / `resolved_by` as your own agent id when a tool asks for it."
    )


def _build_agent(name: str, model: OpenAIResponsesModel) -> Agent:
    allowed = TOOL_ACCESS[name]
    toolset = TOOLSET.filtered(lambda ctx, tool_def, allowed=allowed: tool_def.name in allowed)
    agent = Agent(
        model,
        name=name,
        output_type=BossDecision if name == "boss" else SpecialistReport,
        deps_type=TeamDeps,
        toolsets=[toolset],
        model_settings=MODEL_SETTINGS,
        retries=OUTPUT_RETRIES,
    )

    @agent.instructions
    def role_prompt(ctx: RunContext[TeamDeps]) -> str:
        # Re-read every request so prompt edits apply without a restart.
        return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")

    agent.instructions(_runtime_context)

    @agent.tool
    async def delegate(ctx: RunContext[TeamDeps], to_agent: AgentName, task: str) -> str:
        """Hand a focused sub-task to a teammate and get their structured report back.

        to_agent: one of boss, inventory, accounting, facilities, customer_service.
        task: a self-contained instruction with the ticket id and every fact the
        teammate needs (SKU, size, qty, invoice id, amounts you already know).
        """
        return await _delegate(ctx, to_agent, task)

    return agent


AGENTS: dict[str, Agent] = {}


def get_agents() -> dict[str, Agent]:
    if not AGENTS:
        model = make_model()
        for n in AGENT_NAMES:
            AGENTS[n] = _build_agent(n, model)
    return AGENTS


async def _delegate(ctx: RunContext[TeamDeps], to_agent: str, task: str) -> str:
    d, st = ctx.deps, ctx.deps.state
    refuse = None
    if to_agent not in AGENT_NAMES:
        refuse = f"Unknown agent '{to_agent}'."
    elif to_agent == d.agent:
        refuse = "You cannot delegate to yourself."
    elif to_agent in d.chain:
        refuse = f"{AGENT_LABELS[to_agent]} is already above you in this chain ({' -> '.join(d.chain)}). Return your findings instead."
    elif d.depth >= MAX_DEPTH:
        refuse = f"Delegation depth limit ({MAX_DEPTH}) reached. Finish with what you have."
    elif st.delegations_used >= MAX_DELEGATIONS:
        refuse = f"Delegation budget ({MAX_DELEGATIONS} per ticket run) is used up. Finish with what you have."
    if refuse:
        audit.record(st.run_id, st.ticket_id, d.agent, d.depth, "delegate_refused", {"to": to_agent, "task": task, "reason": refuse})
        return f"REFUSED: {refuse}"

    st.delegations_used += 1
    audit.record(st.run_id, st.ticket_id, d.agent, d.depth, "delegate", {"to": to_agent, "task": task})
    child = TeamDeps(agent=to_agent, depth=d.depth + 1, chain=[*d.chain, to_agent], state=st)
    prompt = f"Ticket {st.ticket_id}. Task from {AGENT_LABELS[d.agent]}:\n{task}"
    try:
        report = await run_agent(to_agent, prompt, child, usage=ctx.usage)
    except UsageLimitExceeded:
        raise  # stop the whole ticket run — the shared token budget is gone
    except Exception as e:  # a teammate failing shouldn't crash the delegator
        audit.record(st.run_id, st.ticket_id, to_agent, child.depth, "error", {"error": f"{type(e).__name__}: {e}"})
        return f"{AGENT_LABELS[to_agent]} failed: {type(e).__name__}: {e}"
    payload = report.model_dump_json() if hasattr(report, "model_dump_json") else json.dumps(report, default=str)
    audit.record(st.run_id, st.ticket_id, d.agent, d.depth, "delegate_result", {"from": to_agent, "report": json.loads(payload)})
    return payload


def _parse_tool_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


async def run_agent(name: str, prompt: str, deps: TeamDeps, usage: RunUsage | None = None):
    """Run one agent loop and audit every step (model request, thinking, text, tool call, tool result, final)."""
    agent = get_agents()[name]
    st = deps.state
    rec = lambda step, detail: audit.record(st.run_id, st.ticket_id, name, deps.depth, step, detail)
    rec("run_start", {"prompt": prompt, "called_by": deps.chain[-2] if len(deps.chain) > 1 else "board"})
    keys = ("requests", "tool_calls", "input_tokens", "output_tokens")
    before = [getattr(usage, k) for k in keys] if usage else [0, 0, 0, 0]
    step_no = 0
    async with agent.iter(prompt, deps=deps, usage=usage, usage_limits=RUN_LIMITS) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                step_no += 1
                for part in node.request.parts:
                    if isinstance(part, ToolReturnPart) and part.tool_name != "delegate" and not part.tool_name.startswith("final_result"):
                        rec("tool_result", {"tool": part.tool_name, "result": _parse_tool_content(part.content)})
                    elif isinstance(part, RetryPromptPart):
                        rec("retry", {"tool": part.tool_name, "message": str(part.content)})
                rec("model_request", {"step": step_no})
            elif Agent.is_call_tools_node(node):
                resp = node.model_response
                u = resp.usage
                for part in resp.parts:
                    if isinstance(part, ThinkingPart) and part.content:
                        rec("thinking", {"text": part.content})
                    elif isinstance(part, TextPart) and part.content.strip():
                        rec("said", {"text": part.content})
                    elif isinstance(part, ToolCallPart):
                        if part.tool_name.startswith("final_result"):
                            continue
                        rec("tool_call", {"tool": part.tool_name, "args": part.args_as_dict()})
                rec("model_response", {"step": step_no, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens})
            elif Agent.is_end_node(node):
                out = node.data.output
                rec("final", {"output": out.model_dump() if hasattr(out, "model_dump") else out})
    # Usage is shared across the ticket run: report this agent's own share (including
    # teammates it delegated to) and the running total for the whole ticket.
    now = [getattr(run.usage, k) for k in keys]
    rec("run_end", {"this_agent_incl_delegates": dict(zip(keys, (a - b for a, b in zip(now, before)))),
                    "ticket_run_total": dict(zip(keys, now))})
    return run.result.output


# ------------------------------------------------------------ orchestration

RUNS: dict[str, dict] = {}  # run_id -> status for the API


def new_run(ticket_id: int, phase: str) -> str:
    label = os.environ.get("CAMPUS_RUN_LABEL", "")  # e.g. "smoke-" for test runs on a scratch DB
    run_id = f"{label}{ticket_id}-{phase}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    RUNS[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "phase": phase, "status": "running",
                    "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "finished_at": None, "decision": None, "error": None}
    return run_id


def last_boss_decision(ticket_id: int, phase: str) -> dict | None:
    """The Boss's most recent final decision for a ticket phase (from memory, else the audit trail)."""
    for r in reversed(list(RUNS.values())):
        if r["ticket_id"] == ticket_id and r["phase"] == phase and r["decision"]:
            return r["decision"]
    for e in reversed(audit.recent(ticket_id=ticket_id, limit=5000)):
        if e["agent"] == "boss" and e["depth"] == 0 and e["step"] == "final" and f"-{phase}-" in e["run_id"]:
            return e["detail"].get("output")
    return None


def running_for(ticket_id: int) -> str | None:
    return next((r["run_id"] for r in RUNS.values() if r["ticket_id"] == ticket_id and r["status"] == "running"), None)


async def _finish(run_id: str, ticket_id: int, decision: BossDecision | None, error: str | None = None) -> None:
    r = RUNS[run_id]
    r["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if error:
        r["status"], r["error"] = "failed", error
        audit.record(run_id, ticket_id, "boss", 0, "error", {"error": error})
    else:
        r["status"], r["decision"] = "done", decision.model_dump()
    pending = (await call_tool("list_approval_requests", {"ticket_id": ticket_id, "status": "pending"}))["approval_requests"]
    ticket = (await call_tool("get_ticket", {"ticket_id": ticket_id}))["ticket"]
    if pending:
        await call_tool("set_ticket_status", {"ticket_id": ticket_id, "status": "awaiting_approval"})
    elif ticket["status"] != "resolved":
        if decision is not None and not error:
            # Boss said it's done but didn't call resolve_ticket: record its outcome.
            await call_tool("resolve_ticket", {"ticket_id": ticket_id, "outcome": decision.outcome, "resolved_by": "boss"})
        else:
            await call_tool("set_ticket_status", {"ticket_id": ticket_id, "status": "open"})
    final_status = (await call_tool("get_ticket", {"ticket_id": ticket_id}))["ticket"]["status"]
    r["ticket_status"] = final_status
    audit.record(run_id, ticket_id, "board", 0, "run_finished",
                 {"run_status": r["status"], "ticket_status": final_status,
                  "pending_approvals": [p["id"] for p in pending]})


async def work_ticket(ticket_id: int, run_id: str) -> None:
    """Phase 1: the Boss reads the ticket, delegates, specialists prepare approvals/drafts."""
    st = RunState(run_id=run_id, ticket_id=ticket_id, phase="work")
    decision, error = None, None
    try:
        await call_tool("set_ticket_status", {"ticket_id": ticket_id, "status": "in_progress"})
        prompt = (
            f"A human on the board started a run on ticket {ticket_id}. Read it with get_ticket, decide which "
            "specialist goes first, delegate only to the agents this ticket needs, and make the final call."
        )
        decision = await run_agent("boss", prompt, TeamDeps("boss", 0, ["boss"], st))
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    await _finish(run_id, ticket_id, decision, error)


async def close_out_ticket(ticket_id: int, run_id: str) -> None:
    """Phase 2: after a human decided every approval, the Boss verifies and closes the ticket."""
    st = RunState(run_id=run_id, ticket_id=ticket_id, phase="close_out")
    decision, error = None, None
    try:
        decided = (await call_tool("list_approval_requests", {"ticket_id": ticket_id}))["approval_requests"]
        lines = "\n".join(
            f"- request #{a['id']} {a['kind']} ref {a['ref_id']} to {a['payee']} ${a['amount']:,.2f}: "
            f"{a['status'].upper()} by {a['decided_by']}" + (f" ({a['decision_note']})" if a.get("decision_note") else "")
            for a in decided
        )
        work = last_boss_decision(ticket_id, "work")
        prompt = (
            f"Close-out for ticket {ticket_id}. Your work-phase decision was:\n"
            f"{json.dumps(work, indent=1) if work else '(not available)'}\n\n"
            f"A human has now decided every payment request for it:\n{lines}\n\n"
            "Verify the result with your tools (get_ticket shows the live invoice/lease rows; get_cash_position / "
            "list_payments / list_purchase_orders). If anything was rejected or the plan changed, have Customer Service "
            "update the customer draft. Then call resolve_ticket with a final outcome that states what was paid (dollars), "
            "new dates, and what the requester gets. In your BossDecision keep first_call / delegations / "
            "agent_contributions from the work phase and add what happened in close-out."
        )
        decision = await run_agent("boss", prompt, TeamDeps("boss", 0, ["boss"], st))
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    await _finish(run_id, ticket_id, decision, error)
