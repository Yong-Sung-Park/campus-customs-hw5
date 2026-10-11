# Design: Campus Customs Operations Desk

The board in `frontend/` (React + Vite + TypeScript) is meant to feel like the desk of a small shop on Chapel Street on a busy Monday: paper tickets on the left, the team in the middle, the cash drawer and the "sign here" pile on the right. It calls the FastAPI backend directly at `http://localhost:8000`, which allows the Vite origin `http://localhost:5173`. Start it with `npm run dev` inside `frontend/`.

## Layout: three columns, read left to right like a desk

| Column | What lives there | Why |
|---|---|---|
| **Left: Ticket board** | The three tickets as paper "ticket stubs": perforated left edge, ticket number in mono, type, requester, the ask, and chips for SKU / size / qty / invoice / lease. **Start the team** appears only on open tickets. | This is the inbox. You pick work here, and the order matches how a person scans: what came in, who asked, what they want. |
| **Center: Agent floor + tabs** | A seating chart of the five agents with the Boss at the head. Below it are three tabs: **Live feed**, **Who did what**, **Customer draft**. | The middle of the desk is where the action is. You watch the team work, then read the result. |
| **Right: Cash drawer + Approvals inbox** | The checking balance in large type, a spent/pending meter, a ledger, bills coming due, and the stack of payments waiting for a human signature. | Money and signatures are the two things only a human controls, so they sit apart in their own column and are always visible, whichever ticket is selected. |

Under 1280px the right column drops below the center as two side-by-side cards. Under 860px everything stacks into one column with 16px gutters and no sideways scrolling. The floor shrinks to just icons and names.

## How the agents read differently

Each agent has a **color, an icon, and a seat**, and those three stay the same in every part of the board: floor, feed, summary cards, approval cards and chips.

| Agent | Color | Icon | Seat |
|---|---|---|---|
| Boss | Yale blue | crown | head of the table, slightly larger avatar |
| Inventory | teal | box | left |
| Accounting | amber | dollar | bottom left |
| Facilities | violet | building | bottom right |
| Customer Service | rose | envelope | right |
| You (human) | slate / green | person | the Approvals inbox |

- **Floor:** all ten possible links are drawn as faint dashed lines. That's the "full connectivity" from the assignment, made visible: anyone can call anyone. When a hand-off actually happens, its line turns solid and gets a count badge. While it is in flight, an animated stream of colored "packets" travels from the delegator to the delegate in the delegator's color. The working agent's avatar pulses. A waiting agent gets a slowly turning dashed ring with "waiting on Accounting" under it. Finished agents get a green check. Agents the Boss never called fade out: "standing by" during the run, "not on this ticket" after. Only the agent who spoke last gets a speech bubble, so the floor never turns into a pile of overlapping text.
- **Feed:** each line is drawn in its agent's color, with a different shape for each kind of step:
  - **Hand-offs** are bold cards ("Boss *hands off to* Facilities" plus the task text).
  - **Tool calls** are one dotted-border line in monospace, like `prepare_rent_payment(lease_id=1, …)`.
  - **Tool results** are one-line previews that expand to the full JSON.
  - **What an agent says** is a normal sentence bubble.
  - **Final reports** are tinted cards with the actions the agent took. The Boss's final call has a heavier edge and a status chip.
  - **Human approvals** are green, and refusals are red.
  - Sub-agent lines are indented by delegation depth, so you can read the chain of command at a glance.
  - Each run starts with a divider ("Work run started", "Close-out run: Boss checks the human decisions") and ends with "Run finished · 9 model calls · 24k tokens", so the token cost shows on every run.

## How resolved tickets show up
- The ticket stub's perforated edge turns **green**, and a rubber-stamp **RESOLVED** lands on the card with a small "thunk" animation (it scales down from 2× and settles at an angle). The Boss's final outcome is printed under a dashed tear line. A ticket waiting on a human gets an **amber** edge and a "Needs your approval (n)" chip.
- The header counter goes from **0/3 resolved** to 3/3.
- When the selected ticket resolves, the center switches by itself to **Who did what**:
  - An outcome banner shows the Boss's final call, *who it called first and why*, and the delegation chain as colored chips (Boss → Facilities → Accounting).
  - Below it is a card for each of the five agents with its own summary, the MCP tools it used with counts (`check_stock ×2`), and who it handed off to. Agents the Boss didn't use show as faded dashed cards ("The Boss kept Inventory off this ticket"). That makes the "don't send everyone" rule visible.
  - Then the human decisions (who approved what, and when) and any purchase orders with their arrival dates.
- **Customer draft** shows Customer Service's message as a lined-paper letter with a pink **DRAFT · NOT SENT** stamp. Earlier versions sit behind it, faded, so you can see when close-out rewrote the draft.

## How cash shows up
- The **balance is the biggest number on the screen** (42px serif). When a payment clears, it **counts down** from the old value to the new one over about a second, and the drawer flashes green. You *see* the $2,400 leave.
- A **meter** splits the opening balance into *paid* (amber), *pending approval* (striped amber) and *left*. Below it, three lines answer the questions a manager actually asks: what's left after pending approvals, which bills haven't been requested yet, and what's free after known bills. That last line is what tells you ticket 103 can't afford a restock.
- The **ledger** lists every payment with the human who approved it (`✓ Yong Sung Park`). **Coming due** lists bills nobody has queued yet (invoice 501, rent).
- The **Approvals inbox** is the only place money moves:
  - Each card shows the kind, payee, amount, ticket, which agent prepared it, and the agent's reason in quotes.
  - Approving requires a typed name ("Signing as …", remembered in `localStorage`). The button reads "Approve $840.00", so you know exactly what you're signing.
  - If a PO is queued behind its vendor's unpaid invoice, the card warns you to approve the invoice first.
  - If the backend refuses anyway (cash would go negative, vendor still blocked), a red toast explains why and the refusal is written to the feed.

## Creative choices that make it a desk people enjoy
- **Paper and ink, not admin chrome.** A warm dotted "desk blotter" background, serif headings (Fraunces), sans for UI (Inter), mono for tools (JetBrains Mono), and Yale blue as the house color. It looks like something a campus shop would own, not a generic dashboard template.
- **Physical metaphors that carry meaning:** ticket stubs with perforations, a rubber stamp for done, a lined letter for drafts, a cash drawer that flashes when money leaves. Each one tells you something at a glance without reading.
- **You can watch the team think.** The floor and the live feed update every second while a run is going (they poll `/api/events?since=` with a cursor). The hand-off animation makes delegation, the core idea of a multi-agent team, something you can see, not just a line in a log.
- **The human stays in charge.** Approvals have their own column, buttons that name the dollar amount, and a required signature. The empty inbox says it plainly: "Agents can only *prepare* payments. Every dollar waits here for a human."
- **Honest feedback.** Toasts confirm every action in plain words ("Paid $840.00 to Bulldog Print Co. Checking is now $2,560.00."). Errors from the guardrails are shown, not hidden. An offline banner tells you exactly which command starts the backend.
- **Light and dark mode** follow the system, with a ◐ toggle in the header. Every color is a CSS variable, and agent colors are re-tuned for dark backgrounds so they stay readable.
- **Small, calm motion.** A pulse on the active agent, sliding feed lines, the stamp landing, the balance counting down. Nothing loops forever except while work is actually happening.
