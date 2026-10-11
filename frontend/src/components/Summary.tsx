import { AGENTS, agentLabel, Icon, money } from '../agents'
import type { TicketDetail } from '../types'

export function Summary({ detail }: { detail: TicketDetail | null }) {
  if (!detail) return <div className="empty"><p>Loading…</p></div>
  const s = detail.summary
  const decision = s.boss_decision
  const outcome = detail.outcome?.outcome ?? decision?.outcome
  if (!s.run_ids.length) {
    return (
      <div className="empty">
        <Icon name="boss" size={28} />
        <p>Nobody has worked this ticket yet. When the team finishes, each agent's contribution shows up here.</p>
      </div>
    )
  }
  return (
    <div className="summary">
      <div className={`outcome-card st-${detail.ticket.status}`}>
        <div className="outcome-label">
          {detail.ticket.status === 'resolved' ? 'Resolved' : detail.ticket.status === 'awaiting_approval' ? 'Waiting on your approval' : 'In progress'}
          {detail.outcome && <span className="muted small"> · closed by {agentLabel(detail.outcome.resolved_by)}</span>}
        </div>
        <p>{outcome ?? 'The Boss has not made a final call yet.'}</p>
        {decision && (
          <div className="first-call small">
            <b>First call:</b> <span className={`who-inline c-${decision.first_call}`}>{agentLabel(decision.first_call)}</span>. {decision.why_first}
          </div>
        )}
        {decision?.delegations?.length ? (
          <div className="chain">
            <span className={`chip-agent c-boss`}>Boss</span>
            {decision.delegations.map((d, i) => (
              <span key={i} className="chain-step" title={d.why}>
                <span className="arrow">→</span>
                <span className={`chip-agent c-${d.to}`}>{agentLabel(d.to)}</span>
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="agent-cards">
        {AGENTS.map((a) => {
          const card = s.agents[a.id]
          if (!card) {
            return (
              <div key={a.id} className={`agent-card c-${a.id} off`}>
                <div className="ac-head"><span className="ac-ico"><Icon name={a.id} size={16} /></span>{a.label}</div>
                <p className="muted small">Not involved. The Boss kept {a.label} off this ticket.</p>
              </div>
            )
          }
          const contribution = decision?.agent_contributions?.[a.id]
          return (
            <div key={a.id} className={`agent-card c-${a.id}`}>
              <div className="ac-head">
                <span className="ac-ico"><Icon name={a.id} size={16} /></span>{a.label}
                <span className="muted small">{card.called_by.length ? `called by ${card.called_by.map(agentLabel).join(', ')}` : ''}</span>
              </div>
              <p>{contribution || card.summary}</p>
              {Object.keys(card.tools_used).length > 0 && (
                <div className="tool-chips">
                  {Object.entries(card.tools_used).map(([t, n]) => (
                    <span key={t} className="tool-chip">{t}{n > 1 ? ` ×${n}` : ''}</span>
                  ))}
                </div>
              )}
              {card.delegated_to.length > 0 && (
                <div className="small muted">handed off to {card.delegated_to.map(agentLabel).join(', ')}</div>
              )}
              {card.actions_taken.length > 0 && (
                <ul className="mini">{card.actions_taken.map((x, i) => <li key={i}>{x}</li>)}</ul>
              )}
            </div>
          )
        })}
      </div>

      {(s.guardrail_refusals?.length ?? 0) > 0 && (
        <div className="human-log guard">
          <h3>Guardrails that fired</h3>
          <ul>
            {s.guardrail_refusals!.map((g, i) => (
              <li key={i} className="hd st-rejected">
                <span><span className={`who-inline c-${g.agent}`}>{agentLabel(g.agent)}</span> · <code>{g.tool}</code> refused</span>
                <b>blocked</b>
                <span className="small">{g.error}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(detail.approval_requests.length > 0 || s.human_approvals.length > 0) && (
        <div className="human-log">
          <h3>Human decisions</h3>
          <ul>
            {detail.approval_requests.map((r) => (
              <li key={r.id} className={`hd st-${r.status}`}>
                <span>#{r.id} {r.kind.replace('_', ' ')} → {r.payee}</span>
                <b>{money(r.amount)}</b>
                <span className="small">{r.status === 'pending' ? 'waiting on you' : `${r.status} by ${r.decided_by}`}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.purchase_orders.length > 0 && (
        <div className="human-log">
          <h3>Purchase orders</h3>
          <ul>
            {detail.purchase_orders.map((p) => (
              <li key={p.id} className={`hd st-${p.status}`}>
                <span>PO {p.id}: {p.qty} × {p.sku} {p.size} @ {money(p.unit_cost)}</span>
                <b>{money(p.total)}</b>
                <span className="small">{p.status.replace('_', ' ')}{p.expected_arrival ? ` · arrives ${p.expected_arrival}` : ''}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function Drafts({ detail }: { detail: TicketDetail | null }) {
  const drafts = [...(detail?.customer_drafts ?? [])].reverse()
  if (!drafts.length) {
    return (
      <div className="empty">
        <Icon name="customer_service" size={28} />
        <p>No customer draft on this ticket. Customer Service only writes when an outside customer is waiting on an answer.</p>
      </div>
    )
  }
  return (
    <div className="drafts">
      {drafts.map((d, i) => (
        <article key={d.id} className={`letter ${i > 0 ? 'older' : ''}`}>
          <div className="letter-stamp">Draft · not sent</div>
          <div className="letter-meta small">
            <div><span>To</span> {d.recipient}</div>
            <div><span>Subject</span> {d.subject}</div>
            <div><span>Written by</span> {agentLabel(d.author)} · draft #{d.id}{i > 0 ? ' (earlier version)' : ''}</div>
          </div>
          <div className="letter-body">{d.body}</div>
        </article>
      ))}
    </div>
  )
}
