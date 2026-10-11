import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { Icon, money } from './agents'
import { AgentFloor } from './components/AgentFloor'
import { Approvals } from './components/Approvals'
import { CashDrawer } from './components/CashDrawer'
import { Feed } from './components/Feed'
import { Drafts, Summary } from './components/Summary'
import { TicketRail } from './components/TicketRail'
import { deriveFloor } from './live'
import type { ApprovalRequest, AuditEvent, Cash, Ticket, TicketDetail } from './types'

type Tab = 'feed' | 'summary' | 'draft'
interface Toast { id: number; tone: 'ok' | 'bad' | 'info'; text: string }

const loadSigner = () => {
  try { return localStorage.getItem('desk-signer') ?? '' } catch { return '' }
}

// Deep links: ?ticket=103&tab=summary opens the board on that ticket and tab.
const params = new URLSearchParams(window.location.search)
const INITIAL_TICKET = Number(params.get('ticket')) || 101
const INITIAL_TAB: Tab = (['feed', 'summary', 'draft'] as const).find((t) => t === params.get('tab')) ?? 'feed'

function prettyDate(iso: string) {
  if (!iso) return '…'
  const d = new Date(`${iso}T12:00:00`)
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [today, setToday] = useState('')
  const [selected, setSelected] = useState(INITIAL_TICKET)
  const [detail, setDetail] = useState<TicketDetail | null>(null)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [cash, setCash] = useState<Cash | null>(null)
  const [pending, setPending] = useState<ApprovalRequest[]>([])
  const [online, setOnline] = useState(true)
  const [tab, setTab] = useState<Tab>(INITIAL_TAB)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [signer, setSignerState] = useState(loadSigner)
  const [starting, setStarting] = useState<number | null>(null)
  const [busyApproval, setBusyApproval] = useState<number | null>(null)
  const [theme, setTheme] = useState<string | null>(() => {
    try { return localStorage.getItem('desk-theme') } catch { return null }
  })

  const cursor = useRef(0)
  const selRef = useRef(selected)
  const prevStatus = useRef<Record<number, string>>({})

  const toast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tone, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200)
  }, [])

  const setSigner = (s: string) => {
    setSignerState(s)
    try { localStorage.setItem('desk-signer', s) } catch { /* private mode */ }
  }

  useEffect(() => {
    if (theme) document.documentElement.setAttribute('data-theme', theme)
    else document.documentElement.removeAttribute('data-theme')
  }, [theme])

  const refresh = useCallback(async () => {
    try {
      const [t, c, p] = await Promise.all([api.tickets(), api.cash(), api.approvals('pending')])
      setTickets(t.tickets)
      setToday(t.date_today)
      setCash(c)
      setPending(p.approval_requests)
      setOnline(true)
      // celebrate status changes
      for (const tk of t.tickets) {
        const before = prevStatus.current[tk.id]
        if (before && before !== tk.status) {
          if (tk.status === 'resolved') {
            toast(`Ticket ${tk.id} resolved`, 'ok')
            if (tk.id === selRef.current) setTab('summary')
          } else if (tk.status === 'awaiting_approval') toast(`Ticket ${tk.id} needs your approval`, 'info')
        }
        prevStatus.current[tk.id] = tk.status
      }
      const sel = selRef.current
      const [ev, d] = await Promise.all([api.events(sel, cursor.current), api.ticket(sel)])
      if (selRef.current !== sel) return
      if (ev.events.length) {
        setEvents((prev) => {
          const seen = new Set(prev.map((e) => e.seq))
          return [...prev, ...ev.events.filter((e) => !seen.has(e.seq))]
        })
      }
      cursor.current = Math.max(cursor.current, ev.last_seq)
      setDetail(d)
    } catch {
      setOnline(false)
    }
  }, [toast])

  const active = tickets.some((t) => t.running_run_id)
  useEffect(() => {
    refresh()
    const id = setInterval(refresh, active ? 1000 : 3500)
    return () => clearInterval(id)
  }, [refresh, active])

  const select = (id: number) => {
    if (id === selRef.current) return
    selRef.current = id
    cursor.current = 0
    setSelected(id)
    setEvents([])
    setDetail(null)
    refresh()
  }

  const start = async (id: number) => {
    setStarting(id)
    try {
      await api.run(id)
      toast(`The team picked up ticket ${id}`, 'info')
      select(id)
      setTab('feed')
      await refresh()
    } catch (e) {
      toast((e as Error).message, 'bad')
    } finally {
      setStarting(null)
    }
  }

  const approve = async (r: ApprovalRequest) => {
    setBusyApproval(r.id)
    try {
      const res = await api.approve(r.id, signer.trim())
      toast(`Paid ${money(r.amount)} to ${r.payee}. Checking is now ${money(res.checking_balance)}.`, 'ok')
      if (res.close_out_run_id) toast(`Boss is closing out ticket ${r.ticket_id}`, 'info')
      if (r.ticket_id && r.ticket_id !== selRef.current) select(r.ticket_id)
      await refresh()
    } catch (e) {
      toast(`Refused: ${(e as Error).message}`, 'bad')
      await refresh()
    } finally {
      setBusyApproval(null)
    }
  }

  const reject = async (r: ApprovalRequest, reason: string) => {
    try {
      await api.reject(r.id, signer.trim(), reason)
      toast(`Rejected request #${r.id}. No money moved.`, 'info')
      await refresh()
    } catch (e) {
      toast((e as Error).message, 'bad')
    }
  }

  const reset = async () => {
    if (!window.confirm('Reset the working database to the original values? Tickets reopen and cash goes back to the start. The audit trail is kept.')) return
    try {
      const r = await api.reset()
      cursor.current = 0
      prevStatus.current = {}
      setEvents([])
      setDetail(null)
      setTab('feed')
      toast(`Database reset. Checking is back to ${money(r.checking_balance)}.`, 'ok')
      await refresh()
    } catch (e) {
      toast((e as Error).message, 'bad')
    }
  }

  const ticket = tickets.find((t) => t.id === selected)
  const running = Boolean(ticket?.running_run_id) || ticket?.status === 'in_progress'
  const floor = useMemo(() => deriveFloor(events, running), [events, running])
  const draftCount = detail?.customer_drafts.length ?? 0

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="crest" aria-hidden="true">CC</span>
          <div>
            <div className="eyebrow">Campus Customs · Chapel Street</div>
            <h1>Operations Desk</h1>
          </div>
        </div>
        <div className="top-meta">
          <span className="meta-chip" title="desk.date_today — the shop's 'today'">
            <Icon name="board" size={14} /> {prettyDate(today)}
          </span>
          <span className="meta-chip">5 agents · gpt-6-luna</span>
          <span className={`meta-chip ${online ? 'ok' : 'bad'}`}>
            <span className={`live-dot ${online ? 'on' : ''}`} /> {online ? 'backend :8000' : 'backend offline'}
          </span>
          <button
            className="btn ghost small"
            onClick={() => setTheme((t) => {
              const dark = t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
              const next = dark ? 'light' : 'dark'
              try { localStorage.setItem('desk-theme', next) } catch { /* ignore */ }
              return next
            })}
            aria-label="Toggle theme"
          >◐</button>
          <button className="btn outline small" onClick={reset} disabled={active}>Reset DB</button>
        </div>
      </header>

      {!online && (
        <div className="offline">Can't reach the backend at http://localhost:8000. Start it from <code>backend/</code> with <code>uvicorn main:app --reload --port 8000</code>.</div>
      )}

      <main className="layout">
        <TicketRail tickets={tickets} selected={selected} onSelect={select} onStart={start} starting={starting} />

        <div className="center">
          <AgentFloor floor={floor} ticket={ticket} running={running} />
          <section className="panel tabs-panel">
            <div className="tabbar" role="tablist">
              <button role="tab" aria-selected={tab === 'feed'} className={tab === 'feed' ? 'on' : ''} onClick={() => setTab('feed')}>
                Live feed {running && <span className="live-dot on" />}
              </button>
              <button role="tab" aria-selected={tab === 'summary'} className={tab === 'summary' ? 'on' : ''} onClick={() => setTab('summary')}>
                Who did what
              </button>
              <button role="tab" aria-selected={tab === 'draft'} className={tab === 'draft' ? 'on' : ''} onClick={() => setTab('draft')}>
                Customer draft {draftCount > 0 && <span className="count-badge">{draftCount}</span>}
              </button>
              <span className="tab-ticket muted small">Ticket #{selected}{ticket ? ` · ${ticket.requester}` : ''}</span>
            </div>
            {tab === 'feed' && <Feed events={events} running={running} />}
            {tab === 'summary' && <Summary detail={detail} />}
            {tab === 'draft' && <Drafts detail={detail} />}
          </section>
        </div>

        <div className="right">
          <CashDrawer cash={cash} />
          <Approvals
            pending={pending}
            signer={signer}
            setSigner={setSigner}
            onApprove={approve}
            onReject={reject}
            busy={busyApproval}
            selectedTicket={selected}
          />
        </div>
      </main>

      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.text}</div>)}
      </div>
    </div>
  )
}
