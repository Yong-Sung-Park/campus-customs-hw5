export type AgentId = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
export type TicketStatus = 'open' | 'in_progress' | 'awaiting_approval' | 'resolved'

export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: TicketStatus
  notes: string | null
  created_at: string
  outcome: string | null
  resolved_by: string | null
  resolved_at: string | null
  pending_approvals: number
  running_run_id: string | null
  is_resolved: boolean
}

export interface TicketsResponse {
  date_today: string
  tickets: Ticket[]
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any

export interface AuditEvent {
  run_id: string
  ticket_id: number
  agent: string
  depth: number
  step: string
  detail: Record<string, Json>
  ts: string
  seq: number
}

export interface ApprovalRequest {
  id: number
  ticket_id: number | null
  kind: 'invoice' | 'rent' | 'purchase_order'
  ref_id: number
  payee: string
  amount: number
  reason: string | null
  requested_by: string
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  payment_id: number | null
}

export interface Payment {
  id: number
  kind: string
  ref_id: number | null
  amount: number
  account: string
  paid_at: string
  approved_by: string
}

export interface Obligation {
  kind: string
  ref_id: number
  payee: string
  amount: number
  due: string
}

export interface Cash {
  date_today: string
  checking_balance: number
  balance_as_of: string
  pending_approvals: ApprovalRequest[]
  pending_approvals_total: number
  available_after_pending: number
  unrequested_obligations: Obligation[]
  unrequested_obligations_total: number
  free_cash_after_obligations: number
  payments: Payment[]
  total_paid: number
}

export interface AgentSummary {
  agent: AgentId
  label: string
  runs: number
  tools_used: Record<string, number>
  delegated_to: string[]
  called_by: string[]
  summary: string
  facts: string[]
  actions_taken: string[]
  recommendation: string
}

export interface BossDecision {
  ticket_id: number
  first_call: AgentId
  why_first: string
  delegations: { to: AgentId; why: string }[]
  agent_contributions: Record<string, string>
  approval_request_ids: number[]
  customer_draft_id: number | null
  status: 'resolved' | 'awaiting_approval'
  outcome: string
}

export interface Draft {
  id: number
  ticket_id: number
  recipient: string
  subject: string
  body: string
  author: string
  status: string
  created_at: string
}

export interface PurchaseOrder {
  id: number
  vendor_id: number
  sku: string
  size: string
  qty: number
  unit_cost: number
  total: number
  status: string
  expected_arrival: string | null
}

export interface TicketDetail {
  found: boolean
  date_today: string
  ticket: Ticket
  linked_records_now: { invoice?: Record<string, Json>; lease?: Record<string, Json> }
  approval_requests: ApprovalRequest[]
  purchase_orders: PurchaseOrder[]
  customer_drafts: Draft[]
  outcome: { outcome: string; resolved_by: string; resolved_at: string } | null
  summary: {
    ticket_id: number
    run_ids: string[]
    agents: Partial<Record<AgentId, AgentSummary>>
    boss_decision: BossDecision | null
    human_approvals: Record<string, Json>[]
    guardrail_refusals?: { agent: string; tool: string; error: string }[]
  }
  running_run_id: string | null
}
