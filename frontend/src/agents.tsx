import type { AgentId } from './types'

export interface AgentMeta {
  id: AgentId
  label: string
  role: string
  /** position on the agent floor, in a 1000 x 600 box */
  x: number
  y: number
}

export const AGENTS: AgentMeta[] = [
  { id: 'boss', label: 'Boss', role: 'Routes tickets · final call', x: 500, y: 110 },
  { id: 'inventory', label: 'Inventory', role: 'Stock · vendors · ETAs', x: 150, y: 300 },
  { id: 'accounting', label: 'Accounting', role: 'Cash · margins · approvals', x: 335, y: 480 },
  { id: 'facilities', label: 'Facilities', role: 'Lease · rent', x: 665, y: 480 },
  { id: 'customer_service', label: 'Customer Service', role: 'Customer drafts', x: 850, y: 300 },
]

export const AGENT_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a])) as Record<AgentId, AgentMeta>

export const isAgent = (x: string): x is AgentId => x in AGENT_BY_ID

export const agentLabel = (x: string) =>
  isAgent(x) ? AGENT_BY_ID[x].label : x === 'human' ? 'You' : x === 'board' ? 'Board' : x

const PATHS: Record<string, string> = {
  boss: 'M3 8.5l4.2 3.6L12 5l4.8 7.1L21 8.5 19.2 19H4.8L3 8.5z',
  inventory: 'M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9zM3 7.5l9 4.5 9-4.5M12 12v9',
  accounting: 'M12 3v18M16.5 7.5c0-1.9-2-3-4.5-3s-4.5 1.1-4.5 3 2 2.6 4.5 3 4.5 1.1 4.5 3-2 3-4.5 3-4.5-1.1-4.5-3',
  facilities: 'M4 21V6.5L12 3l8 3.5V21M9.5 21v-5h5v5M8 9h1.5M14.5 9H16M8 12.5h1.5M14.5 12.5H16',
  customer_service: 'M3.5 6h17v12h-17zM3.5 7l8.5 6 8.5-6',
  human: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 21c.6-3.9 3.7-6 7.5-6s6.9 2.1 7.5 6',
  board: 'M4 5h16v14H4zM4 9h16M9 9v10',
  tool: 'M14.7 6.3a4 4 0 0 0-5.3 5.3L3.5 17.5l3 3 5.9-5.9a4 4 0 0 0 5.3-5.3l-2.6 2.6-2.3-.6-.6-2.3 2.5-2.7z',
  tee: 'M8 3 3 6l2 4 2-1v12h10V9l2 1 2-4-5-3c-.5 1.5-2 2.5-4 2.5S8.5 4.5 8 3z',
  tag: 'M3 12V4h8l10 10-8 8L3 12zM7.5 8.5h.01',
  building: 'M4 21V6.5L12 3l8 3.5V21M9.5 21v-5h5v5',
}

export function Icon({ name, size = 18, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name] ?? PATHS.board} />
    </svg>
  )
}

export const money = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export const ticketIcon = (type: string) =>
  type === 'customer_order' ? 'tee' : type === 'rent_notice' ? 'building' : type === 'price_override' ? 'tag' : 'board'

export const ticketTypeLabel = (type: string) =>
  ({ customer_order: 'Customer order', rent_notice: 'Rent notice', price_override: 'Price override' })[type] ??
  type.replace(/_/g, ' ')
