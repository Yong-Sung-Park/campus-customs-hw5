import { useState } from 'react'
import { agentLabel, Icon, money } from '../agents'
import type { ApprovalRequest } from '../types'

const KIND_LABEL = { invoice: 'Vendor invoice', rent: 'Rent', purchase_order: 'Purchase order' } as const

export function Approvals({
  pending, signer, setSigner, onApprove, onReject, busy, selectedTicket,
}: {
  pending: ApprovalRequest[]
  signer: string
  setSigner: (s: string) => void
  onApprove: (r: ApprovalRequest) => void
  onReject: (r: ApprovalRequest, reason: string) => void
  busy: number | null
  selectedTicket: number
}) {
  const [rejecting, setRejecting] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const total = pending.reduce((s, r) => s + r.amount, 0)

  return (
    <section className="panel inbox" aria-label="Approvals inbox">
      <div className="panel-head">
        <h2>Approvals inbox</h2>
        {pending.length > 0 && <span className="count-badge">{pending.length}</span>}
      </div>
      <label className="signer">
        <span>Signing as</span>
        <input value={signer} onChange={(e) => setSigner(e.target.value)} placeholder="your name" aria-label="Your name for approvals" />
      </label>
      {pending.length === 0 ? (
        <div className="inbox-empty">
          <Icon name="human" size={22} />
          <p>Nothing is waiting on you. Agents can only <i>prepare</i> payments. Every dollar waits here for a human.</p>
        </div>
      ) : (
        <>
          <p className="small muted">{money(total)} waiting on a human decision. Approve top to bottom.</p>
          {pending.map((r) => {
            const blockedBy = r.kind === 'purchase_order'
              ? pending.find((p) => p.kind === 'invoice' && p.payee === r.payee && p.id !== r.id)
              : undefined
            return (
              <article key={r.id} className={`approval k-${r.kind} ${r.ticket_id === selectedTicket ? 'mine' : ''}`}>
                <div className="approval-top">
                  <span className="kind">{KIND_LABEL[r.kind]}</span>
                  <span className="muted small">#{r.id} · ticket {r.ticket_id}</span>
                </div>
                <div className="approval-main">
                  <div>
                    <div className="payee">{r.payee}</div>
                    <div className="small muted">prepared by <span className={`who-inline c-${r.requested_by}`}>{agentLabel(r.requested_by)}</span></div>
                  </div>
                  <div className="amount">{money(r.amount)}</div>
                </div>
                {r.reason && <p className="reason">“{r.reason}”</p>}
                {blockedBy && (
                  <p className="order-hint">Approve invoice request #{blockedBy.id} first. {r.payee} won't ship while it's unpaid.</p>
                )}
                {rejecting === r.id ? (
                  <div className="reject-box">
                    <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why are you rejecting?" autoFocus />
                    <button className="btn danger small" disabled={!signer.trim()} onClick={() => { onReject(r, reason); setRejecting(null); setReason('') }}>Reject</button>
                    <button className="btn ghost small" onClick={() => setRejecting(null)}>Cancel</button>
                  </div>
                ) : (
                  <div className="approval-actions">
                    <button className="btn approve" disabled={!signer.trim() || busy !== null} onClick={() => onApprove(r)}>
                      {busy === r.id ? 'Paying…' : `Approve ${money(r.amount)}`}
                    </button>
                    <button className="btn ghost small" disabled={busy !== null} onClick={() => setRejecting(r.id)}>Reject</button>
                  </div>
                )}
                {!signer.trim() && <p className="small muted">Type your name above to sign.</p>}
              </article>
            )
          })}
        </>
      )}
    </section>
  )
}
