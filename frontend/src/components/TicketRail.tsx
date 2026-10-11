import { Icon, ticketIcon, ticketTypeLabel } from '../agents'
import type { Ticket } from '../types'

const STATUS_LABEL: Record<string, string> = {
  open: 'Open',
  in_progress: 'Team working',
  awaiting_approval: 'Needs your approval',
  resolved: 'Resolved',
}

export function TicketRail({
  tickets, selected, onSelect, onStart, starting,
}: {
  tickets: Ticket[]
  selected: number
  onSelect: (id: number) => void
  onStart: (id: number) => void
  starting: number | null
}) {
  const done = tickets.filter((t) => t.status === 'resolved').length
  return (
    <aside className="rail" aria-label="Tickets">
      <div className="rail-head">
        <h2>Ticket board</h2>
        <span className="progress-pill">{done}/{tickets.length || 3} resolved</span>
      </div>
      {tickets.map((t) => {
        const running = Boolean(t.running_run_id) || t.status === 'in_progress'
        return (
          <article
            key={t.id}
            className={`ticket ${selected === t.id ? 'selected' : ''} st-${t.status} ${running ? 'running' : ''}`}
            onClick={() => onSelect(t.id)}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(t.id)}
            tabIndex={0}
            aria-current={selected === t.id}
          >
            <div className="ticket-top">
              <span className="ticket-ico"><Icon name={ticketIcon(t.type)} size={18} /></span>
              <span className="ticket-id">#{t.id}</span>
              <span className="ticket-type">{ticketTypeLabel(t.type)}</span>
            </div>
            <h3>{t.subject}</h3>
            <div className="ticket-from">from <b>{t.requester}</b></div>
            <p className="ticket-notes">{t.notes}</p>
            <div className="chips">
              {t.sku && <span className="chip mono">{t.sku}</span>}
              {t.size && <span className="chip">size {t.size}</span>}
              {t.qty && <span className="chip">qty {t.qty}</span>}
              {t.invoice_id && <span className="chip">invoice {t.invoice_id}</span>}
              {t.lease_id && <span className="chip">lease {t.lease_id}</span>}
            </div>
            <div className="ticket-foot">
              <span className={`status-chip st-${t.status}`}>
                {STATUS_LABEL[t.status] ?? t.status}
                {t.status === 'awaiting_approval' && t.pending_approvals ? ` (${t.pending_approvals})` : ''}
              </span>
              {t.status === 'resolved' && <div className="stamp" aria-hidden="true">Resolved</div>}
              {t.status === 'open' && !running && (
                <button
                  className="btn primary small"
                  disabled={starting !== null}
                  onClick={(e) => { e.stopPropagation(); onStart(t.id) }}
                >
                  {starting === t.id ? 'Starting…' : 'Start the team'}
                </button>
              )}
            </div>
            {running && <div className="working-bar" aria-hidden="true" />}
            {t.status === 'resolved' && (
              t.outcome && <p className="outcome-snippet">{t.outcome}</p>
            )}
          </article>
        )
      })}
    </aside>
  )
}
