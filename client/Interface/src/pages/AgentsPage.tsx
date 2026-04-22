/**
 * /agents — Agent Pipeline Inspector page  (Go Orchestration)
 *
 * Full-page view for monitoring the Go multi-agent orchestration workflow.
 * Features:
 *  - Live React Flow graph of all agents and their current status
 *  - Transition log with real-time SSE events
 *  - Graph topology from GET /dashboard/graph
 *  - SSE event stream from GET /dashboard/events
 *  - Stats bar: requests processed, avg latency, active agent
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  ConnectionLineType,
  MarkerType,
  Panel,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Link } from 'react-router-dom';
import AgentNodeComponent from '../components/AgentNode';
import type { DashboardEvent, GraphInfo } from '../types/agentState';

// ========================
//   CONSTANTS
// ========================

const DASHBOARD_BASE =
  import.meta.env.VITE_DASHBOARD_URL ||
  `${window.location.protocol}//${window.location.hostname}:5002/dashboard`;

const nodeTypes = { agentNode: AgentNodeComponent };

// ========================
//   TYPES
// ========================

type ActiveTab = 'graph' | 'log';

interface NodeStatus {
  status: 'idle' | 'active' | 'completed' | 'error';
  visited: boolean;
  subProcess?: string | null;
}

// ========================
//   HELPERS
// ========================

/** Auto-layout: simple left-to-right with parallel agents stacked vertically. */
function autoLayout(graphInfo: GraphInfo): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};
  if (!graphInfo.nodes?.length) return positions;

  // Build adjacency from edges to determine topological order
  const nodeIds = graphInfo.nodes.map(n => n.id);
  const inDeg: Record<string, number> = {};
  const adj: Record<string, string[]> = {};
  nodeIds.forEach(id => { inDeg[id] = 0; adj[id] = []; });
  (graphInfo.edges || []).forEach(e => {
    adj[e.source]?.push(e.target);
    inDeg[e.target] = (inDeg[e.target] || 0) + 1;
  });

  // BFS-based layering
  const layers: string[][] = [];
  const queue = nodeIds.filter(id => (inDeg[id] || 0) === 0);
  const visited = new Set<string>();
  while (queue.length > 0) {
    const layer = [...queue];
    layers.push(layer);
    queue.length = 0;
    for (const nid of layer) {
      visited.add(nid);
      for (const child of (adj[nid] || [])) {
        inDeg[child]--;
        if (inDeg[child] <= 0 && !visited.has(child)) {
          queue.push(child);
        }
      }
    }
  }
  // Place any unvisited nodes in a final layer
  const remaining = nodeIds.filter(id => !visited.has(id));
  if (remaining.length) layers.push(remaining);

  const xStep = 260;
  const yStep = 120;
  layers.forEach((layer, col) => {
    const yOffset = -((layer.length - 1) * yStep) / 2;
    layer.forEach((id, row) => {
      positions[id] = { x: col * xStep, y: 200 + yOffset + row * yStep };
    });
  });

  return positions;
}

function buildNodes(
  graphInfo: GraphInfo,
  nodeStatuses: Record<string, NodeStatus>,
  positions: Record<string, { x: number; y: number }>,
): Node[] {
  return graphInfo.nodes.map((n) => {
    const st = nodeStatuses[n.id] || { status: 'idle', visited: false };
    return {
      id: n.id,
      type: 'agentNode',
      position: positions[n.id] || { x: 0, y: 0 },
      data: {
        label: n.id,
        status: st.status === 'completed' ? 'completed' : st.status === 'active' ? 'active' : st.status === 'error' ? 'error' : 'idle',
        visited: st.visited,
        group: 'core',
        agentType: 'agent',
      },
    };
  });
}

function buildEdges(graphInfo: GraphInfo, activeAgents: Set<string>): Edge[] {
  return (graphInfo.edges || []).map((e, i) => {
    const isActive = activeAgents.has(e.source) || activeAgents.has(e.target);
    return {
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: e.parallel ? 'parallel' : '',
      type: 'smoothstep',
      animated: isActive,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      style: {
        stroke: isActive ? '#34d399' : e.parallel ? '#6c8ebf' : '#334155',
        strokeWidth: isActive ? 2.5 : 1.5,
        strokeDasharray: e.parallel ? '6 3' : undefined,
        opacity: isActive ? 1 : 0.45,
      },
      labelStyle: {
        fill: isActive ? '#34d399' : '#64748b',
        fontSize: 9,
        fontWeight: isActive ? 700 : 400,
      },
    };
  });
}

// ========================
//   MAIN PAGE COMPONENT
// ========================

export default function AgentsPage() {
  const [graphInfo, setGraphInfo] = useState<GraphInfo | null>(null);
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, NodeStatus>>({});
  const [activeTab, setActiveTab] = useState<ActiveTab>('graph');
  const [eventLog, setEventLog] = useState<DashboardEvent[]>([]);
  const [requestCount, setRequestCount] = useState(0);
  const [avgLatency, setAvgLatency] = useState(0);
  const [serverOnline, setServerOnline] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const latenciesRef = useRef<number[]>([]);
  const positions = useMemo(() => graphInfo ? autoLayout(graphInfo) : {}, [graphInfo]);

  // ---- Fetch graph topology once ----
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`${DASHBOARD_BASE}/graph`);
        if (!res.ok) { setServerOnline(false); return; }
        const info: GraphInfo = await res.json();
        if (!active) return;
        setGraphInfo(info);
        setServerOnline(true);
      } catch {
        setServerOnline(false);
      }
    })();
    return () => { active = false; };
  }, []);

  // ---- SSE event stream ----
  useEffect(() => {
    const es = new EventSource(`${DASHBOARD_BASE}/events`);

    es.onopen = () => setServerOnline(true);
    es.onerror = () => setServerOnline(false);

    es.onmessage = (msg) => {
      try {
        const evt: DashboardEvent = JSON.parse(msg.data);
        // Accumulate log (keep last 300 events)
        setEventLog(prev => [...prev, evt].slice(-300));

        switch (evt.type) {
          case 'graph_start':
            // Reset all nodes to idle for new request
            setNodeStatuses({});
            setRequestCount(c => c + 1);
            break;
          case 'graph_end':
            if (evt.duration_ms) {
              latenciesRef.current.push(evt.duration_ms);
              const arr = latenciesRef.current;
              setAvgLatency(Math.round(arr.reduce((a, b) => a + b, 0) / arr.length));
            }
            // Mark all as idle (or keep completed)
            setNodeStatuses(prev => {
              const next = { ...prev };
              Object.keys(next).forEach(k => {
                if (next[k].status === 'active') {
                  next[k] = { ...next[k], status: 'completed' };
                }
              });
              return next;
            });
            break;
          case 'agent_start':
            if (evt.agent) {
              setNodeStatuses(prev => ({
                ...prev,
                [evt.agent!]: { status: 'active', visited: true },
              }));
            }
            break;
          case 'agent_end':
            if (evt.agent) {
              const status = evt.status === 'error' ? 'error' as const : 'completed' as const;
              setNodeStatuses(prev => ({
                ...prev,
                [evt.agent!]: { status, visited: true, subProcess: null },
              }));
            }
            break;
          case 'subprocess_start':
            if (evt.agent) {
              setNodeStatuses(prev => ({
                ...prev,
                [evt.agent!]: {
                  ...prev[evt.agent!],
                  status: 'active',
                  visited: true,
                  subProcess: evt.sub_process || null,
                },
              }));
            }
            break;
          case 'subprocess_end':
            if (evt.agent) {
              setNodeStatuses(prev => ({
                ...prev,
                [evt.agent!]: {
                  ...prev[evt.agent!],
                  subProcess: null,
                },
              }));
            }
            break;
          default:
            break;
        }
      } catch { /* ignore malformed */ }
    };

    return () => {
      es.close();
      setServerOnline(false);
    };
  }, []);

  // Auto-scroll log
  useEffect(() => {
    if (activeTab === 'log') {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [eventLog, activeTab]);

  // ---- Send chat from inspector ----
  const handleSendChat = useCallback(async () => {
    if (!chatInput.trim() || chatSending) return;
    const text = chatInput.trim();
    setChatInput('');
    setChatSending(true);
    try {
      await fetch(`${DASHBOARD_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
    } catch { /* silent */ }
    setChatSending(false);
  }, [chatInput, chatSending]);

  // Active agents set for edge highlighting
  const activeAgents = useMemo(() => {
    const s = new Set<string>();
    Object.entries(nodeStatuses).forEach(([k, v]) => {
      if (v.status === 'active') s.add(k);
    });
    return s;
  }, [nodeStatuses]);

  // React Flow data
  const nodes: Node[] = useMemo(
    () => graphInfo ? buildNodes(graphInfo, nodeStatuses, positions) : [],
    [graphInfo, nodeStatuses, positions],
  );
  const edges: Edge[] = useMemo(
    () => graphInfo ? buildEdges(graphInfo, activeAgents) : [],
    [graphInfo, activeAgents],
  );

  const activeAgent = Object.entries(nodeStatuses).find(([, v]) => v.status === 'active')?.[0] ?? null;

  return (
    <div className="h-screen w-screen bg-slate-950 text-slate-100 flex flex-col overflow-hidden font-display">

      {/* ---- Top Nav Bar ---- */}
      <header className="h-12 bg-slate-900 border-b border-white/10 flex items-center px-6 gap-6 shrink-0">
        <Link
          to="/"
          className="flex items-center gap-2 text-slate-400 hover:text-slate-200 transition-colors"
        >
          <span className="material-icons text-sm">arrow_back</span>
          <span className="text-[10px] font-bold uppercase tracking-widest">Back to Game</span>
        </Link>

        <div className="w-px h-5 bg-white/10" />

        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-purple-400 text-lg">account_tree</span>
          <span className="text-sm font-bold tracking-tight">Agent Pipeline Inspector</span>
        </div>

        <div className="ml-auto flex items-center gap-4">
          {/* Stats */}
          <div className="hidden md:flex items-center gap-6">
            <Stat label="Requests" value={requestCount.toString()} />
            <Stat label="Avg Latency" value={avgLatency > 0 ? `${avgLatency}ms` : '--'} />
            <Stat
              label="Active Agent"
              value={activeAgent || 'Idle'}
              highlight={!!activeAgent}
            />
            <Stat label="Events" value={eventLog.length.toString()} mono />
          </div>

          {/* Online indicator */}
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${serverOnline ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]' : 'bg-red-500'}`} />
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              {serverOnline ? 'Live' : 'Offline'}
            </span>
          </div>
        </div>
      </header>

      {/* ---- Main layout ---- */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left: React Flow Graph (takes most space) */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="h-9 bg-slate-900/60 border-b border-white/10 flex items-center px-4 gap-1 shrink-0">
            {(['graph', 'log'] as ActiveTab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-1 text-[10px] font-bold uppercase tracking-widest rounded transition-colors ${
                  activeTab === tab
                    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === 'graph' && (
            <div className="flex-1 min-h-0">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                connectionLineType={ConnectionLineType.SmoothStep}
                fitView
                fitViewOptions={{ padding: 0.25 }}
                proOptions={{ hideAttribution: true }}
                minZoom={0.3}
                maxZoom={2}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
              >
                <Background color="#1e293b" gap={24} size={1} />
                <Controls
                  showInteractive={false}
                  className="!bg-slate-800 !border-slate-600 [&>button]:!bg-slate-700 [&>button]:!border-slate-600 [&>button]:!text-slate-300"
                />
                <MiniMap
                  nodeColor={(node) => {
                    const status = (node.data as Record<string, unknown>)?.status as string;
                    if (status === 'active') return '#34d399';
                    if (status === 'completed') return '#60a5fa';
                    if (status === 'error') return '#f87171';
                    return '#334155';
                  }}
                  maskColor="rgba(0,0,0,0.75)"
                  className="!bg-slate-900 !border-slate-700"
                />
                <Panel position="top-right">
                  <div className="flex flex-col gap-2 bg-slate-900/90 border border-white/10 rounded-lg p-3 text-[9px]">
                    <span className="text-slate-400 font-bold uppercase tracking-widest mb-1">Legend</span>
                    {[
                      { color: 'bg-emerald-500', label: 'Active' },
                      { color: 'bg-blue-500', label: 'Completed' },
                      { color: 'bg-red-500', label: 'Error' },
                      { color: 'bg-slate-600', label: 'Idle' },
                    ].map(({ color, label }) => (
                      <div key={label} className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded-full ${color}`} />
                        <span className="text-slate-400">{label}</span>
                      </div>
                    ))}
                  </div>
                </Panel>
              </ReactFlow>
            </div>
          )}

          {activeTab === 'log' && (
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {eventLog.length === 0 ? (
                <div className="text-slate-500 text-xs text-center mt-16">
                  No events recorded yet. Send a message below or use the coaching chat to see the pipeline.
                </div>
              ) : (
                <>
                  {eventLog.slice().reverse().map((evt, idx) => (
                    <EventCard key={`${evt.ts}-${idx}`} evt={evt} />
                  ))}
                  <div ref={logEndRef} />
                </>
              )}
            </div>
          )}
        </div>

        {/* Right sidebar: live event feed + chat input (always visible on graph tab) */}
        {activeTab === 'graph' && (
          <aside className="w-80 border-l border-white/10 bg-slate-900/50 flex flex-col overflow-hidden shrink-0">
            <div className="px-4 py-2.5 border-b border-white/10 flex items-center justify-between">
              <span className="text-[9px] font-bold text-slate-400 uppercase tracking-widest">Live Events</span>
              <span className="text-[9px] text-slate-600">{eventLog.length} total</span>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {eventLog.length === 0 ? (
                <div className="text-slate-600 text-[10px] text-center mt-8">Waiting for pipeline activity...</div>
              ) : (
                eventLog.slice().reverse().slice(0, 50).map((evt, idx) => (
                  <MiniEventCard key={`${evt.ts}-${idx}`} evt={evt} />
                ))
              )}
            </div>
            {/* Inline chat input to trigger pipeline */}
            <div className="border-t border-white/10 p-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSendChat()}
                  placeholder="Send to pipeline..."
                  className="flex-1 bg-slate-800 border border-white/10 rounded px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-purple-500/50"
                  disabled={chatSending}
                />
                <button
                  onClick={handleSendChat}
                  disabled={chatSending || !chatInput.trim()}
                  className="px-3 py-1.5 bg-purple-600 text-white text-xs font-bold rounded hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Send
                </button>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

// ========================
//   SUB-COMPONENTS
// ========================

function Stat({ label, value, highlight = false, mono = false }: {
  label: string; value: string; highlight?: boolean; mono?: boolean;
}) {
  return (
    <div className="flex flex-col items-center">
      <span className="text-[8px] text-slate-500 uppercase tracking-widest">{label}</span>
      <span className={`text-[11px] font-bold ${highlight ? 'text-emerald-400' : 'text-slate-300'} ${mono ? 'font-mono' : ''}`}>
        {value}
      </span>
    </div>
  );
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  graph_start: 'text-cyan-400',
  graph_end: 'text-cyan-400',
  agent_start: 'text-emerald-400',
  agent_end: 'text-emerald-400',
  subprocess_start: 'text-amber-400',
  subprocess_end: 'text-amber-400',
  thought: 'text-purple-400',
  tool_call: 'text-blue-400',
  tool_result: 'text-blue-400',
  skill_use: 'text-yellow-400',
  delegation: 'text-pink-400',
  chat_response: 'text-green-400',
};

function EventCard({ evt }: { evt: DashboardEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasExtra = !!(evt.message || evt.detail);
  const ts = evt.ts ? (evt.ts < 1e12 ? evt.ts * 1000 : evt.ts) : 0;
  const timeLabel = ts ? new Date(ts).toLocaleTimeString() : '';
  const isError = evt.status === 'error';

  return (
    <div
      className={`rounded-lg border p-3 text-[10px] font-mono cursor-pointer transition-colors ${
        isError
          ? 'bg-red-950/40 border-red-500/30 hover:bg-red-950/60'
          : 'bg-slate-900/60 border-white/10 hover:bg-slate-800/60'
      }`}
      onClick={() => hasExtra && setExpanded(x => !x)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-bold ${EVENT_TYPE_COLORS[evt.type] || 'text-slate-400'}`}>
            {evt.type}
          </span>
          {evt.agent && (
            <>
              <span className="text-slate-500">·</span>
              <span className="text-slate-100 font-bold">{evt.agent}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {timeLabel && <span className="text-slate-600">{timeLabel}</span>}
          {evt.duration_ms != null && evt.duration_ms > 0 && (
            <span className="text-slate-600">{evt.duration_ms.toFixed(0)}ms</span>
          )}
          {evt.status && (
            <span className={`text-[8px] px-1.5 py-0.5 rounded ${
              evt.status === 'error' ? 'bg-red-500/20 text-red-400' : 'bg-emerald-500/20 text-emerald-400'
            }`}>
              {evt.status}
            </span>
          )}
          {hasExtra && (
            <span className="text-purple-400 text-[8px]">{expanded ? '▲' : '▼'}</span>
          )}
        </div>
      </div>
      {evt.sub_process && (
        <div className="flex items-center gap-2 mt-1 text-[9px]">
          <span className="text-amber-400">subprocess: {evt.sub_process}</span>
          {evt.sub_kind && <span className="text-amber-300/60">({evt.sub_kind})</span>}
        </div>
      )}
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {evt.message && (
            <div className="p-2 bg-black/30 rounded text-[9px] leading-relaxed">
              <span className="text-purple-300 font-bold">Message: </span>
              <span className="text-slate-400">{evt.message}</span>
            </div>
          )}
          {evt.detail && (
            <div className="p-2 bg-black/20 rounded text-[9px] leading-relaxed">
              <span className="text-amber-300 font-bold">Detail: </span>
              <span className="text-slate-400">
                {JSON.stringify(evt.detail, null, 2)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MiniEventCard({ evt }: { evt: DashboardEvent }) {
  const isError = evt.status === 'error';
  return (
    <div className={`p-2 rounded border text-[9px] font-mono ${
      isError ? 'bg-red-950/30 border-red-500/20' : 'bg-white/5 border-white/5'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className={`font-bold ${EVENT_TYPE_COLORS[evt.type] || 'text-slate-400'}`}>
            {evt.type.replace('_', ' ')}
          </span>
          {evt.agent && (
            <>
              <span className="text-slate-500">·</span>
              <span className="text-slate-200 font-bold truncate max-w-[80px]">{evt.agent}</span>
            </>
          )}
        </div>
        {evt.duration_ms != null && evt.duration_ms > 0 && (
          <span className="text-slate-600 shrink-0">{evt.duration_ms.toFixed(0)}ms</span>
        )}
      </div>
      {evt.message && (
        <div className="mt-0.5 text-slate-500 truncate max-w-full">{evt.message}</div>
      )}
    </div>
  );
}
