import { useEffect, useRef, useState } from 'react'
import { agentLabel, Icon, isAgent, money } from '../agents'
import { argsInline, fmtTime, previewResult } from '../live'
import type { AuditEvent } from '../types'

const QUIET = new Set(['model_request', 'model_response', 'run_end', 'reset'])

export function Feed({ events, running }: { events: AuditEvent[]; running: boolean }) {
  const [showResults, setShowResults] = useState(true)
  const [showThinking, setShowThinking] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [events.length])

  const visible = events.filter(
    (e) =>
      !QUIET.has(e.step) &&
      (showResults || e.step !== 'tool_result') &&
      (showThinking || e.step !== 'thinking') &&
      !(e.step === 'tool_call' && e.detail.tool === 'delegate'),
  )
  const usage = new Map<string, Record<string, number>>()
  for (const e of events) if (e.step === 'run_end' && e.depth === 0) usage.set(e.run_id, e.detail.ticket_run_total)

  return (
    <div className="feed-wrap">
      <div className="feed-tools small">
        <label><input type="checkbox" checked={showResults} onChange={(e) => setShowResults(e.target.checked)} /> tool results</label>
        <label><input type="checkbox" checked={showThinking} onChange={(e) => setShowThinking(e.target.checked)} /> reasoning notes</label>
        <span className="muted">{events.length} events logged to audit_trail.json</span>
      </div>
      <div
        className="feed"
        ref={box}
        onScroll={(ev) => {
          const el = ev.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
        }}
      >
        {visible.length === 0 && (
          <div className="empty">
            <Icon name="board" size={28} />
            <p>No chatter yet on this ticket. Press <b>Start the team</b> and the conversation streams in here.</p>
          </div>
        )}
        {visible.map((e) => (
          <FeedItem key={e.seq} e={e} usage={usage.get(e.run_id)} />
        ))}
        {running && (
          <div className="typing"><span /><span /><span /> the team is working</div>
        )}
      </div>
    </div>
  )
}

function Who({ id, depth }: { id: string; depth?: number }) {
  return (
    <span className={`who c-${id}`}>
      <span className="who-icon"><Icon name={isAgent(id) ? id : id === 'human' ? 'human' : 'board'} size={14} /></span>
      {agentLabel(id)}
      {depth ? <span className="depth">depth {depth}</span> : null}
    </span>
  )
}

function FeedItem({ e, usage }: { e: AuditEvent; usage?: Record<string, number> }) {
  const d = e.detail
  const indent = { marginLeft: `${Math.min(e.depth, 3) * 18}px` }
  const time = <time className="ts">{fmtTime(e.ts)}</time>

  switch (e.step) {
    case 'run_start':
      if (e.depth === 0)
        return (
          <div className="divider">
            <span>{e.run_id.includes('close_out') ? 'Close-out run: Boss checks the human decisions' : 'Work run started'} · {fmtTime(e.ts)}</span>
          </div>
        )
      return null
    case 'delegate':
      return (
        <div className={`item handoff c-${e.agent}`} style={indent}>
          <div className="item-head"><Who id={e.agent} /> <span className="arrow">hands off to</span> <Who id={d.to} /> {time}</div>
          <p className="task">{d.task}</p>
        </div>
      )
    case 'delegate_refused':
      return (
        <div className={`item warn c-${e.agent}`} style={indent}>
          <div className="item-head"><Who id={e.agent} /> <span className="arrow">tried</span> <Who id={d.to} /> {time}</div>
          <p>Refused by the guardrail: {d.reason}</p>
        </div>
      )
    case 'delegate_result':
      return (
        <div className={`item back c-${d.from}`} style={indent}>
          <div className="item-head"><Who id={d.from} /> <span className="arrow">reports back to</span> <Who id={e.agent} /> {time}</div>
        </div>
      )
    case 'tool_call':
      return (
        <div className={`item tool c-${e.agent}`} style={indent}>
          <Icon name="tool" size={14} className="tool-ico" />
          <code><b>{d.tool}</b>({argsInline(d.args)})</code>
          {time}
        </div>
      )
    case 'tool_result':
      return (
        <details className={`item result c-${e.agent}`} style={indent}>
          <summary>
            <span className="ret">↳ {d.tool}</span> <span className="muted">{previewResult(d.result)}</span>
          </summary>
          <pre>{JSON.stringify(d.result, null, 2)}</pre>
        </details>
      )
    case 'said':
      return (
        <div className={`item said c-${e.agent}`} style={indent}>
          <div className="item-head"><Who id={e.agent} depth={e.depth} /> {time}</div>
          <p>{d.text}</p>
        </div>
      )
    case 'thinking':
      return (
        <div className={`item thinking c-${e.agent}`} style={indent}>
          <div className="item-head"><Who id={e.agent} /> <span className="muted">reasoning</span> {time}</div>
          <p>{d.text}</p>
        </div>
      )
    case 'retry':
      return (
        <div className={`item warn c-${e.agent}`} style={indent}>
          <div className="item-head"><Who id={e.agent} /> <span className="muted">retry {d.tool ?? ''}</span> {time}</div>
          <p>{String(d.message).slice(0, 300)}</p>
        </div>
      )
    case 'final': {
      const out = d.output ?? {}
      const isBoss = e.agent === 'boss' && e.depth === 0
      return (
        <div className={`item report c-${e.agent} ${isBoss ? 'boss-call' : ''}`} style={indent}>
          <div className="item-head">
            <Who id={e.agent} depth={e.depth} /> <span className="muted">{isBoss ? 'final call' : 'report'}</span> {time}
          </div>
          <p className="report-text">{out.summary ?? out.outcome}</p>
          {Array.isArray(out.actions_taken) && out.actions_taken.length > 0 && (
            <ul className="mini">{out.actions_taken.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
          )}
          {out.recommendation && <p className="rec">→ {out.recommendation}</p>}
          {isBoss && out.status && <span className={`status-chip st-${out.status}`}>{out.status.replace('_', ' ')}</span>}
        </div>
      )
    }
    case 'approval': {
      const ok = d.result?.ok
      const verb = d.decision === 'reject' ? 'rejected' : ok ? 'approved' : 'tried to approve'
      return (
        <div className={`item human ${ok ? '' : 'refused'}`}>
          <div className="item-head"><Who id="human" /> <span className="muted">{d.by}</span> {time}</div>
          <p>
            {verb} request #{d.approval_id}: {d.kind?.replace('_', ' ')} to {d.payee}, <b>{money(d.amount)}</b>
            {ok && d.result?.balance_after !== undefined && <> · checking now <b>{money(d.result.balance_after)}</b></>}
            {!ok && d.decision !== 'reject' && <> · <span className="bad">{d.result?.error}</span></>}
          </p>
        </div>
      )
    }
    case 'run_finished':
      return (
        <div className="divider end">
          <span>
            Run finished · ticket {String(d.ticket_status).replace('_', ' ')}
            {usage ? ` · ${usage.requests} model calls · ${Math.round((usage.input_tokens + usage.output_tokens) / 1000)}k tokens` : ''}
          </span>
        </div>
      )
    case 'error':
      return (
        <div className={`item error c-${e.agent}`} style={indent}>
          <div className="item-head"><Who id={e.agent} /> {time}</div>
          <p>{d.error}</p>
        </div>
      )
    default:
      return null
  }
}
