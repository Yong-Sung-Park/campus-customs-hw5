import { useEffect, useRef, useState } from 'react'
import { money } from '../agents'
import type { Cash } from '../types'

function useCountTo(target: number, ready: boolean) {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  const primed = useRef(false)
  useEffect(() => {
    // First real balance: show it as-is. Only later changes (a payment clearing) count down.
    if (!primed.current) {
      if (ready) primed.current = true
      from.current = target
      setValue(target)
      return
    }
    const start = performance.now()
    const a = from.current
    const dur = 900
    let raf = 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / dur)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(a + (target - a) * eased)
      if (t < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ready])
  return value
}

const KIND = { invoice: 'Invoice', rent: 'Rent', purchase_order: 'PO' } as Record<string, string>

export function CashDrawer({ cash }: { cash: Cash | null }) {
  const balance = cash?.checking_balance ?? 0
  const shown = useCountTo(balance, cash !== null)
  const [flash, setFlash] = useState(false)
  const prev = useRef(balance)
  useEffect(() => {
    if (balance < prev.current) {
      setFlash(true)
      const t = setTimeout(() => setFlash(false), 1400)
      prev.current = balance
      return () => clearTimeout(t)
    }
    prev.current = balance
  }, [balance])

  if (!cash) return <section className="panel cash"><div className="panel-head"><h2>Cash drawer</h2></div><p className="muted">Loading…</p></section>

  const opening = cash.checking_balance + cash.total_paid
  const spentPct = opening ? (cash.total_paid / opening) * 100 : 0
  const pendingPct = opening ? (cash.pending_approvals_total / opening) * 100 : 0

  return (
    <section className={`panel cash ${flash ? 'flash' : ''}`} aria-label="Cash drawer">
      <div className="panel-head">
        <h2>Cash drawer</h2>
        <span className="muted small">checking · as of {cash.balance_as_of}</span>
      </div>
      <div className="balance" aria-live="polite">{money(shown)}</div>
      <div className="meter" title="Opening balance split into paid out, pending and remaining">
        <span className="m-spent" style={{ width: `${spentPct}%` }} />
        <span className="m-pending" style={{ width: `${pendingPct}%` }} />
      </div>
      <div className="meter-legend small">
        <span><i className="m-spent" /> paid {money(cash.total_paid)}</span>
        <span><i className="m-pending" /> pending {money(cash.pending_approvals_total)}</span>
        <span><i className="m-left" /> opening {money(opening)}</span>
      </div>
      <dl className="cash-facts small">
        <div><dt>After pending approvals</dt><dd>{money(cash.available_after_pending)}</dd></div>
        <div><dt>Bills not yet requested</dt><dd>{money(cash.unrequested_obligations_total)}</dd></div>
        <div><dt>Free after known bills</dt><dd className={cash.free_cash_after_obligations < 0 ? 'bad' : ''}>{money(cash.free_cash_after_obligations)}</dd></div>
      </dl>
      <h3 className="ledger-title">Ledger</h3>
      {cash.payments.length === 0 ? (
        <p className="small muted">No money has left the drawer yet. Cash only goes out in this shop.</p>
      ) : (
        <ul className="ledger">
          {cash.payments.map((p) => (
            <li key={p.id}>
              <span className="lk">{KIND[p.kind] ?? p.kind} {p.ref_id}</span>
              <span className="lby small muted">✓ {p.approved_by}</span>
              <span className="lamt">−{money(p.amount)}</span>
            </li>
          ))}
        </ul>
      )}
      {cash.unrequested_obligations.length > 0 && (
        <>
          <h3 className="ledger-title">Coming due</h3>
          <ul className="ledger due">
            {cash.unrequested_obligations.map((o) => (
              <li key={`${o.kind}-${o.ref_id}`}>
                <span className="lk">{o.kind === 'rent' ? 'Rent' : `Invoice ${o.ref_id}`} · {o.payee}</span>
                <span className="lby small muted">due {o.due}</span>
                <span className="lamt">{money(o.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
