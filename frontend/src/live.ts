import { agentLabel, isAgent } from './agents'
import type { AgentId, AuditEvent, Json } from './types'

export type LiveStatus = 'idle' | 'active' | 'waiting' | 'done' | 'error'

export interface AgentLive {
  status: LiveStatus
  line: string
  bubble?: string
}

export interface FloorState {
  agents: Record<AgentId, AgentLive>
  edges: Record<string, number> // "a|b" (sorted) -> delegation count this ticket
  activeEdge: { from: AgentId; to: AgentId } | null
  worked: Set<AgentId>
  runId: string | null
  speaker: AgentId | null // the agent who acted last: only they get a speech bubble
}

const idle = (): AgentLive => ({ status: 'idle', line: 'At their desk' })

export const edgeKey = (a: string, b: string) => [a, b].sort().join('|')

const runIds = (events: AuditEvent[]) =>
  [...new Set(events.filter((e) => !e.run_id.startsWith('human') && e.run_id !== 'reset').map((e) => e.run_id))]

/** Fold the audit events of one ticket into what the agent floor should show right now. */
export function deriveFloor(events: AuditEvent[], running: boolean): FloorState {
  const agents = {
    boss: idle(), inventory: idle(), accounting: idle(), facilities: idle(), customer_service: idle(),
  } as Record<AgentId, AgentLive>
  const edges: Record<string, number> = {}
  const worked = new Set<AgentId>()
  for (const e of events) {
    if (e.step === 'delegate' && isAgent(e.agent) && isAgent(e.detail.to)) {
      const k = edgeKey(e.agent, e.detail.to)
      edges[k] = (edges[k] ?? 0) + 1
    }
    if (isAgent(e.agent) && e.step === 'run_start') worked.add(e.agent)
  }

  const ids = runIds(events)
  const latest = ids[ids.length - 1] ?? null
  let activeEdge: FloorState['activeEdge'] = null
  let speaker: AgentId | null = null
  for (const e of events) {
    if (e.run_id !== latest || !isAgent(e.agent)) continue
    if (e.step !== 'model_request' && e.step !== 'model_response' && e.step !== 'run_end') speaker = e.agent
    const a = agents[e.agent]
    const d = e.detail
    switch (e.step) {
      case 'run_start':
        a.status = 'active'
        a.line = d.called_by && d.called_by !== 'board' ? `Took a task from ${agentLabel(d.called_by)}` : 'Reading the ticket'
        a.bubble = undefined
        break
      case 'tool_call':
        if (d.tool !== 'delegate') {
          a.status = 'active'
          a.line = `Calling ${d.tool}…`
        }
        break
      case 'tool_result':
        a.line = `Got ${d.tool}`
        break
      case 'delegate':
        a.status = 'waiting'
        a.line = `Waiting on ${agentLabel(d.to)}`
        if (isAgent(d.to)) activeEdge = { from: e.agent, to: d.to }
        break
      case 'delegate_result':
        a.status = 'active'
        a.line = `Reading ${agentLabel(d.from)}'s report`
        if (activeEdge && activeEdge.from === e.agent && activeEdge.to === d.from) activeEdge = null
        break
      case 'delegate_refused':
        a.line = `Hand-off refused: ${d.reason}`
        break
      case 'said':
        a.bubble = String(d.text ?? '').slice(0, 160)
        break
      case 'final': {
        a.status = 'done'
        const out = d.output ?? {}
        a.line = 'Done'
        a.bubble = String(out.summary ?? out.outcome ?? '').slice(0, 170)
        break
      }
      case 'error':
        a.status = 'error'
        a.line = String(d.error ?? 'error').slice(0, 120)
        break
    }
  }
  if (!running) {
    activeEdge = null
    for (const id of Object.keys(agents) as AgentId[]) {
      if (agents[id].status === 'active' || agents[id].status === 'waiting') agents[id].status = 'done'
    }
  }
  return { agents, edges, activeEdge, worked, runId: latest, speaker }
}

/** Short one-line preview of a tool result. */
export function previewResult(result: Json): string {
  if (result == null) return ''
  if (typeof result !== 'object') return String(result).slice(0, 180)
  if (result.error) return `⚠ ${result.error}`
  const pairs = Object.entries(result)
    .filter(([, v]) => v !== null && typeof v !== 'object')
    .slice(0, 6)
    .map(([k, v]) => `${k}: ${typeof v === 'number' && /amount|balance|price|cost|total|margin|rent/.test(k) ? `$${v}` : v}`)
  return pairs.join(' · ') || JSON.stringify(result).slice(0, 180)
}

export function fmtTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

export function argsInline(args: Record<string, Json> | undefined) {
  if (!args) return ''
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? (v.length > 60 ? JSON.stringify(v.slice(0, 60) + '…') : JSON.stringify(v)) : JSON.stringify(v)}`)
    .join(', ')
}
