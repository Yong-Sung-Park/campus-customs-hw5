import type { ApprovalRequest, AuditEvent, Cash, TicketDetail, TicketsResponse } from './types'

// The board talks straight to the FastAPI backend (CORS allows http://localhost:5173).
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? body)
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  return body as T
}

export const api = {
  tickets: () => call<TicketsResponse>('/api/tickets'),
  ticket: (id: number) => call<TicketDetail>(`/api/tickets/${id}`),
  run: (id: number) => call<{ run_id: string }>(`/api/tickets/${id}/run`, { method: 'POST' }),
  events: (ticketId: number, since: number) =>
    call<{ events: AuditEvent[]; last_seq: number }>(`/api/events?ticket_id=${ticketId}&since=${since}&limit=1000`),
  approvals: (status = 'pending') => call<{ approval_requests: ApprovalRequest[] }>(`/api/approvals?status=${status}`),
  approve: (id: number, approved_by: string) =>
    call<{ result: Record<string, unknown>; checking_balance: number; close_out_run_id: string | null }>(
      `/api/approvals/${id}/approve`,
      { method: 'POST', body: JSON.stringify({ approved_by }) },
    ),
  reject: (id: number, rejected_by: string, reason: string) =>
    call<{ result: Record<string, unknown> }>(`/api/approvals/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ rejected_by, reason }),
    }),
  cash: () => call<Cash>('/api/cash'),
  reset: () => call<{ ok: boolean; checking_balance: number }>('/api/reset', { method: 'POST' }),
}
