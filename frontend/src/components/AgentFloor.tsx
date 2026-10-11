import { AGENTS, AGENT_BY_ID, Icon } from '../agents'
import { edgeKey, type FloorState } from '../live'
import type { Ticket } from '../types'

const W = 1000
const H = 600

const STATUS_TEXT = { idle: 'idle', active: 'working', waiting: 'waiting', done: 'done', error: 'error' } as const

export function AgentFloor({ floor, ticket, running }: { floor: FloorState; ticket: Ticket | undefined; running: boolean }) {
  const pairs: [string, string][] = []
  for (let i = 0; i < AGENTS.length; i++) for (let j = i + 1; j < AGENTS.length; j++) pairs.push([AGENTS[i].id, AGENTS[j].id])
  const anyWork = floor.worked.size > 0

  return (
    <section className="panel floor-panel" aria-label="Agent floor">
      <div className="panel-head">
        <h2>Agent floor</h2>
        <span className="muted small">
          {running ? 'Live: the team is working this ticket' : anyWork ? `Ticket ${ticket?.id}: who worked it` : 'Pick a ticket and start the team'}
        </span>
        <span className="legend small">
          <i className="lg-mesh" /> any agent can call any agent
          <i className="lg-used" /> hand-offs on this ticket
        </span>
      </div>
      <div className="floor" style={{ aspectRatio: `${W} / ${H}` }}>
        <svg className="floor-svg" viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
          {pairs.map(([a, b]) => {
            const A = AGENT_BY_ID[a as keyof typeof AGENT_BY_ID]
            const B = AGENT_BY_ID[b as keyof typeof AGENT_BY_ID]
            const n = floor.edges[edgeKey(a, b)] ?? 0
            return (
              <g key={`${a}-${b}`}>
                <line x1={A.x} y1={A.y} x2={B.x} y2={B.y} className={n ? 'edge used' : 'edge'} style={{ strokeWidth: n ? 3 + Math.min(n, 4) : 1.2 }} />
                {n > 0 && (
                  <g transform={`translate(${(A.x + B.x) / 2} ${(A.y + B.y) / 2})`}>
                    <circle r="15" className="edge-badge" />
                    <text textAnchor="middle" dy="5" className="edge-badge-text">{n}</text>
                  </g>
                )}
              </g>
            )
          })}
          {floor.activeEdge && (() => {
            const A = AGENT_BY_ID[floor.activeEdge.from]
            const B = AGENT_BY_ID[floor.activeEdge.to]
            const d = `M ${A.x} ${A.y} L ${B.x} ${B.y}`
            return (
              <g className={`active-edge c-${floor.activeEdge.from}`}>
                <path d={d} className="edge-flow" />
                {[0, 0.4, 0.8].map((delay) => (
                  <circle key={delay} r="9" className="packet">
                    <animateMotion dur="1.2s" begin={`${delay}s`} repeatCount="indefinite" path={d} />
                  </circle>
                ))}
              </g>
            )
          })()}
        </svg>

        {AGENTS.map((a) => {
          const live = floor.agents[a.id]
          const touched = floor.worked.has(a.id)
          const dim = anyWork && !touched
          const bubbleBelow = a.id === 'boss'
          return (
            <div
              key={a.id}
              className={`node c-${a.id} s-${live.status} ${dim ? 'dim' : ''}`}
              style={{ left: `${(a.x / W) * 100}%`, top: `${(a.y / H) * 100}%` }}
            >
              {live.bubble && live.status !== 'idle' && floor.speaker === a.id && (
                <div className={`bubble ${bubbleBelow ? 'below' : ''}`}><span className="bubble-text">{live.bubble}</span></div>
              )}
              <div className="avatar">
                <Icon name={a.id} size={30} />
                <span className="ring" />
                {live.status === 'done' && touched && <span className="tick">✓</span>}
              </div>
              <div className="node-label">{a.label}</div>
              <div className="node-line">
                <span className={`dot s-${live.status}`} />
                {dim ? (running ? 'standing by' : 'not on this ticket') : live.status === 'idle' ? a.role : `${STATUS_TEXT[live.status]} · ${live.line}`}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
