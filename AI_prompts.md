# AI Prompts Log — Homework 5: Campus Customs Multi-Agent Operations

This file logs what I typed to my vibe coder (Claude Code), one section per problem.
I wrote each prompt before the work on that problem started, then ran it.

---

## Problem 1: Vibe coder prompts

**Prompt:**

> I'm starting Homework 5. The idea: Campus Customs has a ticket board (customer orders, rent, unpaid bills, discount requests), and I'm going to build three pieces that talk to each other — an MCP server over the shop database, a FastAPI backend that runs a team of five PydanticAI agents (Boss, Inventory, Accounting, Facilities, Customer Service), and a React dashboard where a person can watch the agents work and approve payments. Don't write any app code yet.
>
> First, set up the project. Make a folder called `hw5` and put the course database at `hw5/data/campus_customs.db`. Add a `.gitignore` that keeps `.env`, `.venv`, `node_modules`, build output, and Python caches out of git — but do **not** ignore `data/` or `.db` files this time, because both database files have to be in the final public repo. Add a `.env.example` with a `PORTKEY_API_KEY` placeholder, copy my real Portkey key from my HW4 `.env` into a new `hw5/.env`, and create a `.venv` for Python.
>
> Then create `AI_prompts.md` at the project root. This is my log of what I type to you. One section per problem (Problems 1–11), each with the problem number and title, the prompt I typed, and a follow-up prompt if I needed one, with one sentence on what was missing after the first try. Put this prompt under Problem 1. From now on, before you start each problem, add my prompt to its section first, then do the work. Don't rewrite earlier sections.

**Follow-up:** None needed. The folder, `.gitignore`, `.env`/`.env.example`, `.venv`, and this log were set up on the first pass.

---

## Problem 2: Study the Campus Customs database

**Prompt:**

> Before we build anything, I want to understand the data. Open `data/campus_customs.db` and walk through every table — `desk`, `tickets`, `inventory`, `pricing`, `vendors`, `leases`, `cash_accounts`, `payments`, `invoices`, and anything else in there. For each one, show me the columns, types, keys, and the actual rows (they're small), and point out anything odd I should know before agents start touching it.
>
> Then make the working copy: copy the original to `data/campus_customs_new.db`. Everything later reads and writes the copy; the original stays untouched so I can reset.
>
> Pay special attention to the three open tickets. For each one, trace how it links into the other tables — which SKU/size, which vendor, which lease, which invoice, which cash account — and what "today" (`desk.date_today`) means for anything overdue. Tell me what each ticket actually needs to get resolved.
>
> Last, start `output/harness.md`. Add a "Database" section with one small table per DB table: every field, and one short line on why that table matters for the agents.

**Follow-up:** None needed. The walkthrough also found the cash squeeze: $3,400 − $840 invoice − $2,400 rent leaves only $160, which can't cover a 12-hoodie reprint for ticket 103.

---

## Problem 3: Build the MCP server

**Prompt:**

> Now write an MCP server in `mcp_server/server.py` using FastMCP. It talks to the working copy `data/campus_customs_new.db` (resolve the path relative to the repo, not my current folder), never the original. Every agent will get its shop facts from this server, so it is the single source of truth. No made-up data: if a SKU or lease isn't in the DB, the tool should say so, not guess.
>
> For now, just three read-only tools, one aimed at each open ticket:
> 1. `check_stock(sku, size)` — reads `inventory` and returns the on-hand qty and location for that SKU/size, plus the other sizes of the same SKU. This is how we find out ticket 101's size-S tee is at zero (and how many size-M hoodies exist for 103).
> 2. `get_lease(lease_id)` — reads `leases` plus `desk.date_today` and returns the rent, landlord, next due date, and how many days until it's due or how many days overdue. That's what ticket 102 needs.
> 3. `get_pricing(sku)` — reads `pricing` and returns unit cost, list price, and the margin at list. If I pass an optional discount percent, it also returns the discounted price and the margin at that price. That's the math ticket 103's bulk-discount request needs.
>
> Keep the tool names and docstrings clear, because the agents will read the docstrings to decide when to call them. You don't need to connect or run it yet.
>
> Then add the three tools to `output/harness.md`: for each one, which table it reads, which ticket (101, 102, or 103) it unlocks, and one sentence on why it's the right tool for that ticket. Be specific, not just "reads inventory". Also write a short `mcp_server/README.md`: what the server is for, which DB file it uses, and the three tools.

**Follow-up:** None needed. All three tools returned real DB values on a quick local check (tee S = 0, rent $2,400 due in 2 days, hoodie 15% off = $49.30 at 55.4% margin).

---

## Problem 4: Add the MCP server to my vibe coder and test each tool

**Prompt:**

> Hook the MCP server up to you (Claude Code) for this project only. Put the connection in `.mcp.json` at the project root. Name the server `campus-customs`, and run `mcp_server/server.py` with the project's `.venv` Python over stdio so it doesn't depend on whatever Python is first on my PATH.
>
> Once it's connected, test every tool through MCP. Don't import the Python file directly. Use these three asks:
> - "Using the campus-customs MCP tools, how many Classic Bulldog Tees in size S do we have, and what other sizes are in stock?"
> - "Using the campus-customs MCP tools, when is the rent due on lease 1, how much is it, and how many days do we have?"
> - "Using the campus-customs MCP tools, what are the cost, list price, and margin on CC-HOOD-NAVY, and what's left if we give a 15% bulk discount?"
>
> Save the evidence in `output/mcp_smoke.json`: for each tool, the prompt, the tool name, the arguments, and the raw tool output. Then check every number against `data/campus_customs_new.db` with a plain SQL query and record whether it matches.

**Follow-up:**

> The server shows up as "Pending approval" in `claude mcp list` and the tools aren't available yet. Load `.mcp.json` explicitly for each test session (`--mcp-config .mcp.json`) and only allow the one tool each test is about, so we can see exactly which tool answered.

*What was lacking:* project-scoped MCP servers need a one-time approval before Claude Code will start them, so the first attempt never reached the tools.

---

## Problem 5: Build the agent team and grow the MCP tools

**Prompt:**

> Time for the agent team. Use PydanticAI to build five agents — **Boss, Inventory, Accounting, Facilities, Customer Service** — on `gpt-6-luna` through Portkey (same Portkey pattern as HW4, key from `.env`, no custom temperature). That is the only model allowed anywhere in the code. Full connectivity: give every agent a `delegate` tool so it can hand a sub-task to any other agent and get the answer back. Guard it, though: no delegating to yourself, a max delegation depth, and a usage limit shared by the whole ticket run so a delegation loop can't burn tokens.
>
> Layout: one prompt file per agent in `backend/prompts/` (`boss.md`, `inventory.md`, `accounting.md`, `facilities.md`, `customer_service.md`), data types in `backend/models.py`, agent code under `backend/`. Write each prompt as a real job description with the shop rules that agent needs: who it is, what it owns and what it must NOT touch, which tools to use and in what order, when to delegate and to whom, and what to hand back. The rules to bake in:
> - "today" is `desk.date_today`
> - vendor lead times come from `vendors`
> - a vendor won't ship while it has an open unpaid invoice
> - every payment needs a human approval, and agents only prepare it
> - no payment may push cash negative
> - cash only goes out
> - no inventing data
> - customer messages are drafts only, never sent
>
> Boss decides who works the ticket (no "send everyone") and makes the final call. Inventory finds shortfalls and the right restock vendor and timing. Accounting owns cash, invoices, margins, and preparing every payment or purchase order. Facilities owns leases and rent. Customer Service writes the customer-facing draft.
>
> Grow the MCP server so the agents can actually work the three tickets. Every shop fact and every write goes through MCP; don't build a second tools layer that hits SQLite directly. Add tools for: reading a ticket and the shop date, vendor status (open invoices, can it ship, ETA from lead days), invoices, a cash position (balance, pending approvals, upcoming obligations), a bulk-quote calculator, preparing an invoice payment / rent payment / purchase order as a *pending approval request* (amounts pulled from the DB, never typed in by the agent), saving a customer draft, and resolving a ticket. The tool that actually moves money (`execute_approved_payment`) must only be callable by the human approve route, never by an agent. It refuses if cash would go negative or if a PO's vendor still has an open invoice, and when it pays it updates `payments`, `cash_accounts`, and the invoice / lease / PO row. Give each agent only the MCP tools its job needs.
>
> Audit: every agent-loop step (model request, model text, tool call with args, tool result, delegation, final output) gets appended to `output/audit_trail.json` with run id, ticket id, agent, depth, and timestamp. Append, never wipe.
>
> Update `output/harness.md` with each agent and every MCP tool and the table(s) it uses, plus a **Safety** section: guardrails a real business would want when agents touch real customers and real money, and the limits that keep token use in check. Update `mcp_server/README.md` to match the new tool list. Give me a small CLI script to run the team on one ticket so we can smoke-test it before the API exists.

**Follow-up:**

> The first test call failed with a 400 from Portkey: "Function tools with reasoning_effort are not supported for gpt-6-luna in /v1/chat/completions." Keep `gpt-6-luna`, but switch the PydanticAI model to the Responses API, which does allow tools with reasoning, and set reasoning effort to low to save tokens. Then smoke-test tickets 102 and 101 end to end on a scratch copy of the DB, so the real working copy stays clean. Approve as me from the CLI. Also, in close-out the Boss said "no later rent due date is recorded" because it can't see the lease. Make `get_ticket` include the live linked invoice/lease row, and hand the Boss its work-phase decision when close-out starts.

*What was lacking:* the HW4 Chat Completions pattern doesn't work for tool calling on gpt-6-luna, and the Boss had no way to see the rolled-forward due date after rent was paid.

---

## Problem 6: Plan the three tickets

**Prompt:**

> Before we wire the backend, I want to write down what I *expect* the team to do, so I can compare it to reality later. Make `output/desk_tickets.html`: a single page I can double-click (no server, no build, inline CSS/JS) with tabs **101, 102, 103, Cash, Reflection**. Cash and Reflection just say "coming later" for now.
>
> Each ticket tab should show the ticket card (requester, ask, linked rows from the DB) and then an **Expected** section and an empty **Actual** placeholder for after the real run. In Expected, write in plain words:
> - who the Boss calls **first** and why
> - **every** delegation I expect, in order, including specialist-to-specialist hand-offs (not "Boss calls everyone")
> - which MCP tools I expect each agent to use
> - who should **not** be involved and why
> - the money I expect to move, and the approvals the human has to click
>
> My expectations, based on the DB:
> - **101:** Inventory first (the S tee is at 0), Inventory finds Bulldog Print Co is blocked by overdue invoice 501, Accounting preps the $840 invoice plus an $8 one-tee PO, Customer Service drafts the note to Tauhid. Facilities stays out.
> - **102:** Facilities first to verify the lease, then Facilities hands off to Accounting to prep the $2,400 rent. No Inventory, no Customer Service (the landlord isn't a customer).
> - **103:** Accounting first for margin, Inventory for the 8-vs-20 shortfall, then the cash squeeze: about $152 left after 101 and 102 can't buy 12 more hoodies ($264). Customer Service drafts the reply to the Yale AI Club. Facilities stays out.
>
> Include a running expected-cash line ($3,400 → $2,552 → $152 → ?) so the plan is concrete. Make it look clean, since it's going in my submission.

**Follow-up:**

> In the little linked-record cards at the top of each ticket, the bold numbers ("0", "open, 3 days overdue") break onto their own line like headings. Only the card's label should be on its own line.

*What was lacking:* the CSS styled every `<b>` in a card as a label, not just the first one.

---

## Problem 7: Backend routes

**Prompt:**

> Now the API the dashboard will call. In `backend/main.py`, make a FastAPI app that opens the MCP connection once at startup and does everything through it. No direct SQLite in the routes, except the reset, which is just a file copy. Routes:
> - list the three tickets with status (open / in_progress / awaiting_approval / resolved), plus pending approvals and whether a run is going
> - one ticket in detail: the ticket, its approval requests, POs, the full customer draft text, and a per-agent summary (what each agent did and which tools it used)
> - start the team on a ticket. Run it in the background and return a run id right away, so the board can watch live. Refuse with a 409 if that ticket is already running or resolved.
> - recent agent events (what each agent said, tool calls/results, delegations), filterable by ticket, run, and "since" sequence number, so the board can poll
> - list approval requests, **approve** one (the human types their name; this is the only route that changes cash, via `execute_approved_payment`), and reject one. When the last pending request on a ticket is decided, automatically kick off the Boss's close-out run.
> - the checking balance from `cash_accounts`, with the payments ledger
> - reset: copy `data/campus_customs.db` over `data/campus_customs_new.db` for a fresh run. Refuse while a run is in progress, and do **not** touch the audit trail.
>
> Allow CORS from the Vite dev origin (`http://localhost:5173`). It should start with `uvicorn main:app --reload --port 8000` from `backend/`. Test every route with real calls on a scratch DB, so the working copy stays clean, and add a one-line-per-route list to `output/harness.md`.

**Follow-up:**

> While testing the routes on ticket 103, the team approved a **36%** discount ($37.12 a hoodie) because the Boss asked Accounting for "the maximum discount that keeps 40% margin". Accounting then called `get_pricing` four times (39%, 38%, 37%, 36%) hunting for it. That's way too generous. Put a real bulk-discount policy in the Boss and Accounting prompts (10% for 12–19 units, 15% for 20+, 20% max). Make it clear the 40% margin is a safety floor, not a target. Tell Accounting to quote the policy rates with `quote_bulk_order` instead of looping a tool.

*What was lacking:* the first prompts gave a margin floor but no target rate, so the agents treated the floor as the goal.

---

## Problem 8: Agent dashboard

**Prompt:**

> Build the board in `frontend/` with React + Vite + TypeScript, calling the backend directly at `http://localhost:8000` (we already allowed the 5173 origin in CORS). It should feel like a real operations desk someone would want to sit at, not a default admin template. What I want on it:
> - **Ticket rail:** all three tickets as cards (who, what, status). A clear "Start the team" button only on open tickets. Resolved tickets get a big rubber-stamp "RESOLVED" look.
> - **Agent floor:** the five agents as a little seating chart / network with Boss at the head. Each agent has its own color and icon. While a ticket runs, the active agent lights up, shows what it's doing right now ("calling check_stock…", "waiting on Accounting"), and a delegation line animates between the two agents. I want to *see* the hand-offs.
> - **Live feed:** the running conversation. Delegations, tool calls, short tool results, what each agent says, final reports, human approvals. Each agent's lines look different (its color, its icon, tool calls in mono). Poll `/api/events` with the `since` cursor every second while a run is going.
> - **Approvals inbox:** pending payments and POs with payee, amount, ticket, who prepared it and why. Approve / Reject buttons that need my name (remember it in localStorage). If the backend refuses (e.g. the PO before its invoice), show the reason nicely.
> - **Cash drawer:** the checking balance, big, animating down when a payment clears, plus a mini ledger of payments and what's pending.
> - **Summary:** when the ticket is done, the Boss's outcome and one card per agent that worked it: their summary, the tools they used (with counts), and who they delegated to. Show the customer draft as a letter marked "DRAFT — not sent".
> - Header with the shop date and a Reset button (with a confirm) that calls the reset route.
>
> Make it look good: warm "paper desk" background, Yale blue, a serif for headings, mono for tools, light and dark mode, and it should still work on a laptop-width screen. Add `npm run dev` instructions. Then write `output/design.md` explaining the layout, how the agents read differently, how resolved tickets and cash show up, and the creative choices that make it feel like a desk humans would enjoy using.

**Follow-up:**

> I ran ticket 102 on the board as a test. It works, but a few things look off:
> - Accounting's and Facilities' speech bubbles overlap each other. Only the agent who spoke last should get a bubble.
> - During the run, agents that haven't been called yet already say "not on this ticket". Accounting was called a few seconds later. Say "standing by" while it's running.
> - The RESOLVED stamp covers the requester's name. Move it to the empty top-right corner.
> - In system dark mode the stamp almost disappears.
>
> Fix those, check phone width, then write `design.md`.

*What was lacking:* the first floor layout put a bubble on every agent and judged "not involved" before the run was over, and the stamp's blend mode only worked in light mode.

---

## Problem 9: Resolve the tickets

**Prompt:**

> Now the real run. First reset the working DB through the board's reset route so we start clean, and note the starting checking balance. That test run of 102 we just did shouldn't count. Then run **101, 102, 103 in order** from the board. When payment requests show up in the Approvals inbox, check each one against the DB (right amount, right payee, invoice before its PO) and approve it in the board as "Yong Sung Park (via Claude)", since I asked you to click for me. Wait for each Boss close-out to resolve the ticket before starting the next one.
>
> Afterwards, using only what actually happened (the audit trail and the DB):
> - Fill the **Actual** section on each ticket tab of `output/desk_tickets.html`: which agents worked, who the Boss called first, every delegation in order (including specialist-to-specialist), which MCP tools each agent used, the approvals, and a short Expected-vs-Actual note. Keep the Expected sections.
> - Fill the **Cash** tab: starting balance after reset, then for each ticket how cash changed and why (which payment, dollar amount), then the ending balance. Prove it matches `cash_accounts` in the working DB.
> - Write `output/resolved_tickets.json`: per ticket, the id, final status, short outcome, what each agent contributed, and the human approvals.
> - Make `output/resolved_board.html`: a double-clickable page with a screenshot of the React board for each resolved ticket (101, 102, 103). Add a deep link like `?ticket=103&tab=summary` to the board so each one can be captured cleanly.
> - Finish `output/harness.md` so it covers tables, MCP tools, the five agents, API routes, the dashboard, and safety rules.

**Follow-up:**

> The full-page screenshot of ticket 101 shows the cash drawer at **$120.34**. The balance animation starts from $0 on page load and the capture caught it mid-count, so the first load should show the real number with no animation. The RESOLVED stamp also covers the ticket type, so move it into the card's footer row. And on ticket 103 the most important thing that happened, the cash guard refusing the $264 PO, isn't visible in "Who did what". Add a "Guardrails that fired" panel, then recapture all the screenshots.

*What was lacking:* the count-down animation also ran on first load, and the summary only showed successful actions, not the guardrail that actually decided ticket 103.

---

## Problem 10: Reflection

**Prompt:**

> Last writing piece: fill the **Reflection** tab in `output/desk_tickets.html`. Write it in my voice, be thorough, and back every point with evidence from *this* run: the ticket tabs, the Cash tab, the audit trail numbers (model calls, tokens, which tools, which hand-offs). No generic AI essay. Cover:
> 1. How I'd grade the agents on each ticket and why. Include what they did well, what they got wrong or wasted, and what it cost in tokens.
> 2. For each ticket, Actual vs my Expected plan. Where it matched and where it surprised me.
> 3. What would have been simpler as one agent with tools, and **why**. Use the real numbers (e.g. ticket 102 took 13 model calls for what is basically three tool calls) and say where the multi-agent split actually earned its keep.
> 4. Three **new** Campus Customs problems this team could solve with the tools we already have. Walk through which agent and which MCP tools, using real rows from the DB (the mug at 0, the caps, Tauhid following up).
> 5. Three **new** problems it could **not** solve, and for each one the tools and agents I'd add. Tie them to what we saw: ticket 103's $112 gap, the tee PO arriving 9/5 with no way to receive it, and the $152 left against $2,400 of rent due 10/02.

**Follow-up:** None needed. The first draft used the run's own numbers: 48 calls / about 135k tokens, ticket 102's 13 calls, the 36% → 15% discount fix, the $112 gap, and $152 against $2,400 due 10/02.

---

## Problem 11: Submit to GitHub

**Prompt:**

> Let's ship it. Write a `README.md` at the root that explains how to run everything:
> - copy the original DB over the working copy when you want a clean run
> - set up `.venv` and `.env`
> - the MCP server (and how `.mcp.json` hooks it into Claude Code)
> - the FastAPI backend
> - the React board
> - **reset the DB before a full three-ticket run**
>
> Add a map of the files and the outputs. Before committing, make sure the real `.env` is ignored and that my Portkey key doesn't appear in any tracked file. Both DB files under `data/` must be in the repo.
>
> Then `git init`, commit, and create a **public** GitHub repo `campus-customs-hw5` under my account with `gh`, and push. Put the repo URL in `output/github_url.txt`, commit, and push again. Finally, clone the repo into a temp folder and check that the files match the expected layout and there's no `.env` in it.
