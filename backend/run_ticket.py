"""Run the agent team on one ticket from the command line (smoke test before the API).

    cd backend
    ../.venv/Scripts/python run_ticket.py 102                       # work phase only
    ../.venv/Scripts/python run_ticket.py 102 --approve-as "Yong"   # + approve pending requests as a human, then close out

Approving here is still a human action: you type your own name on the command line.
"""

import argparse
import asyncio
import json

import audit
import team
from mcp_link import TOOLSET, call_tool


def show(events: list[dict]) -> None:
    for e in events:
        pad = "  " * e["depth"]
        d = e["detail"]
        if e["step"] == "tool_call":
            print(f"{pad}[{e['agent']}] -> {d['tool']}({json.dumps(d['args'])[:160]})")
        elif e["step"] == "tool_result":
            print(f"{pad}[{e['agent']}] <- {d['tool']}: {json.dumps(d['result'])[:160]}")
        elif e["step"] == "delegate":
            print(f"{pad}[{e['agent']}] DELEGATE -> {d['to']}: {d['task'][:200]}")
        elif e["step"] == "said":
            print(f"{pad}[{e['agent']}] says: {d['text'][:200]}")
        elif e["step"] == "final":
            print(f"{pad}[{e['agent']}] FINAL: {json.dumps(d['output'])[:600]}")
        elif e["step"] in ("error", "delegate_refused", "run_finished", "approval"):
            print(f"{pad}[{e['agent']}] {e['step'].upper()}: {json.dumps(d)[:300]}")


async def main(ticket_id: int, approve_as: str | None) -> None:
    async with TOOLSET:
        run_id = team.new_run(ticket_id, "work")
        await team.work_ticket(ticket_id, run_id)
        show(audit.recent(run_id=run_id))
        if not approve_as:
            return
        pending = (await call_tool("list_approval_requests", {"ticket_id": ticket_id, "status": "pending"}))["approval_requests"]
        for req in pending:  # oldest first, so an invoice clears before its vendor's PO
            res = await call_tool("execute_approved_payment", {"approval_id": req["id"], "approved_by": approve_as})
            audit.record(run_id, ticket_id, "human", 0, "approval", {"approval_id": req["id"], "result": res})
            print(f"HUMAN APPROVE #{req['id']} ({req['kind']} ${req['amount']:,.2f}): {json.dumps(res)[:300]}")
        if pending:
            close_id = team.new_run(ticket_id, "close_out")
            await team.close_out_ticket(ticket_id, close_id)
            show(audit.recent(run_id=close_id))
        print("CASH:", json.dumps(await call_tool("get_cash_position"))[:300])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ticket_id", type=int)
    ap.add_argument("--approve-as", default=None, help="your (human) name, to approve pending requests")
    a = ap.parse_args()
    asyncio.run(main(a.ticket_id, a.approve_as))
