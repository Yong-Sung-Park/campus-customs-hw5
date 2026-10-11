"""Data types shared by the agent team, the audit trail and the FastAPI routes."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[str, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

AGENT_LABELS: dict[str, str] = {
    "boss": "Boss",
    "inventory": "Inventory",
    "accounting": "Accounting",
    "facilities": "Facilities",
    "customer_service": "Customer Service",
}

TicketStatus = Literal["open", "in_progress", "awaiting_approval", "resolved"]


# ------------------------------------------------------------ agent outputs

class SpecialistReport(BaseModel):
    """What a specialist hands back to whoever delegated to it."""

    agent: AgentName
    summary: str = Field(description="Two or three sentences: what you found and what you did.")
    facts: list[str] = Field(default_factory=list, description="Key facts, each tied to the tool that returned it, e.g. 'check_stock: CC-TEE-WHITE S qty 0'.")
    actions_taken: list[str] = Field(default_factory=list, description="Writes you made, e.g. 'prepared approval #1 for invoice 501 ($840)'.")
    approval_request_ids: list[int] = Field(default_factory=list, description="IDs of payment/PO approval requests you created.")
    draft_ids: list[int] = Field(default_factory=list, description="IDs of customer drafts you saved.")
    blockers: list[str] = Field(default_factory=list, description="Anything stopping the ticket, with the reason.")
    recommendation: str = Field(description="What you recommend the delegator does next.")


class Delegation(BaseModel):
    to: AgentName
    why: str


class BossDecision(BaseModel):
    """The Boss's final structured call on a ticket."""

    ticket_id: int
    first_call: AgentName = Field(description="The specialist you delegated to first.")
    why_first: str
    delegations: list[Delegation] = Field(default_factory=list, description="Every delegation you made, in order.")
    agent_contributions: dict[str, str] = Field(
        default_factory=dict,
        description="One line per agent that worked the ticket (keys: boss, inventory, accounting, facilities, customer_service).",
    )
    approval_request_ids: list[int] = Field(default_factory=list, description="Payment/PO requests now waiting on a human.")
    customer_draft_id: int | None = None
    status: Literal["resolved", "awaiting_approval"] = Field(
        description="'awaiting_approval' if any payment request is pending a human; otherwise 'resolved' (after calling resolve_ticket)."
    )
    outcome: str = Field(description="Short outcome for the board: what happens for the requester, dates, dollars.")


# ------------------------------------------------------------ run plumbing

@dataclass
class RunState:
    """Shared by every agent in one ticket run (the Boss and all delegations)."""

    run_id: str
    ticket_id: int
    phase: Literal["work", "close_out"] = "work"
    delegations_used: int = 0


@dataclass
class TeamDeps:
    """Per-agent dependencies: who I am, how deep in the delegation chain, the shared run state."""

    agent: str
    depth: int
    chain: list[str]
    state: RunState


@dataclass
class AuditEvent:
    run_id: str
    ticket_id: int
    agent: str
    depth: int
    step: str  # run_start | model_request | thinking | said | tool_call | tool_result | delegate | delegate_result | final | error | approval | run_end
    detail: dict[str, Any] = field(default_factory=dict)
    ts: str = ""
    seq: int = 0


# ------------------------------------------------------------ API bodies

class ApproveBody(BaseModel):
    approved_by: str = Field(min_length=1, description="Name of the human clicking approve.")


class RejectBody(BaseModel):
    rejected_by: str = Field(min_length=1)
    reason: str = ""


class RunStarted(BaseModel):
    run_id: str
    ticket_id: int
    status: str
