# Campus Customs: Multi-Agent Operations (HW5)

An agent team runs the Campus Customs ticket board. Five **PydanticAI** agents (Boss, Inventory, Accounting, Facilities, Customer Service) work the shop's open tickets. They get every fact from, and make every write through, a **FastMCP** server over the shop's SQLite database. A **FastAPI** backend runs the team. A **React + Vite + TypeScript** board lets a person watch the agents and approve payments.

```
React board (frontend/, :5173) ──HTTP──▶ FastAPI (backend/main.py, :8000) ──MCP stdio──▶ FastMCP (mcp_server/server.py) ──▶ data/campus_customs_new.db
                                                 │
                                                 └─ PydanticAI team (backend/team.py) · gpt-6-luna via Portkey for every agent
```

- **Model:** every agent uses `gpt-6-luna` through Portkey (Responses API). No other model appears in the code.
- **Money rule:** agents only *prepare* payments. A human approves each one on the board, and that approve route is the only thing that moves cash. The MCP pay tool refuses to take checking below $0.
- **Customer messages:** drafts only. Nothing is ever emailed or sent.

---

## 1. Setup (once)

Requires Python 3.12+ and Node 20+.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
# .venv/bin/python -m pip install -r requirements.txt       # macOS / Linux
cp .env.example .env                                         # then put your real PORTKEY_API_KEY in .env
cd frontend && npm install && cd ..
```

## 2. Databases: copy the original to the working copy

- `data/campus_customs.db` is the **original**. Nothing ever writes to it.
- `data/campus_customs_new.db` is the **working copy**. The MCP server and backend read and write only this file. The repo ships it in its state *after* my full Problem 9 run (all 3 tickets resolved, checking $152).

For a clean start, copy the original over the working copy:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

Or, with the backend running, click **Reset DB** on the board (or `curl -X POST http://localhost:8000/api/reset`). That does the same copy. The audit trail is kept.

## 3. Start the MCP server

The backend launches the server itself over stdio when it starts, so you don't need a separate terminal for the app. To run it by hand:

```bash
.venv/Scripts/python mcp_server/server.py        # Windows
# .venv/bin/python mcp_server/server.py          # macOS / Linux
```

**Claude Code:** `.mcp.json` registers it as `campus-customs` for this project. Open Claude Code in the repo root and approve the server, and its 23 tools become available. On macOS/Linux, change `command` in `.mcp.json` to `.venv/bin/python`. Tool list: `mcp_server/README.md`. Smoke-test evidence: `output/mcp_smoke.json`.

## 4. Start the FastAPI backend

```bash
cd backend
../.venv/Scripts/python -m uvicorn main:app --reload --port 8000    # or: uvicorn main:app --reload --port 8000 (with .venv active)
```

The backend runs at `http://localhost:8000`, and CORS allows the board at `http://localhost:5173`. Routes are listed in `output/harness.md` §6.

Optional CLI smoke test of the team on one ticket: `cd backend && ../.venv/Scripts/python run_ticket.py 102`.

## 5. Start the React board

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`. Pick a ticket, press **Start the team**, and watch the agent floor and live feed. When requests land in the **Approvals inbox**, type your name and approve them (invoice before its PO). After the last approval, the Boss closes the ticket out. Deep links such as `?ticket=103&tab=summary` open a specific view.

## 6. Full three-ticket run: reset first

1. With the backend running, **reset the database** (Reset DB button, `POST /api/reset`, or the `cp` in §2). Checking should read **$3,400.00** and all three tickets should be **open**.
2. Run **101 → 102 → 103** from the board. Approve each pending request after checking it against the DB:
   - 101: invoice 501 ($840), then PO #1 ($8)
   - 102: rent ($2,400)
   - 103: there is nothing to approve. The $264 restock gets refused by the cash guard.
3. The ending checking balance should be **$152.00**, matching `cash_accounts`. My run's results are in `output/`.

---

## Repo map

```
hw5/
├── AI_prompts.md              # what I typed to the vibe coder, problem by problem
├── requirements.txt  .env.example  .gitignore  .mcp.json  README.md
├── data/
│   ├── campus_customs.db      # original (never written)
│   └── campus_customs_new.db  # working copy (state after the Problem 9 run)
├── mcp_server/
│   ├── server.py              # FastMCP: 23 tools + money guardrails
│   └── README.md
├── backend/
│   ├── main.py                # FastAPI routes
│   ├── team.py                # the five PydanticAI agents, delegation, run/close-out
│   ├── models.py              # data types
│   ├── mcp_link.py            # one MCP connection shared by agents + routes
│   ├── audit.py               # append-only output/audit_trail.json
│   ├── run_ticket.py          # CLI smoke test
│   └── prompts/               # boss.md, inventory.md, accounting.md, facilities.md, customer_service.md
├── frontend/                  # React + Vite + TS board
└── output/
    ├── harness.md             # tables, MCP tools, agents, safety, routes, dashboard, run results
    ├── mcp_smoke.json         # Problem 4 MCP tool tests from Claude Code
    ├── desk_tickets.html      # plan vs actual per ticket + Cash + Reflection tabs
    ├── design.md              # dashboard design choices
    ├── resolved_tickets.json  # per-ticket outcome, agent contributions, human approvals
    ├── resolved_board.html    # screenshots of the board for each resolved ticket
    ├── board_screenshots/
    ├── audit_trail.json       # every agent-loop step, appended across all runs
    └── github_url.txt
```

> **Note on approvals in my run:** I asked Claude Code to click Approve on the board for me during the Problem 9 run, so payments are recorded as `approved_by = "Yong Sung Park (via Claude)"`.
