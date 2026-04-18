/**
 * /agents — Agent Pipeline Inspector page
 *
 * Full-page view for monitoring the multi-agent orchestration workflow.
 * Features:
 *  - Live React Flow graph of all agents and their current status
 *  - Transition log with LLM output and reasoning
 *  - Live-polling every 2s from GET /agent-state/graph
 *  - Stats bar: requests processed, avg latency, active agent
 *  - Agents registry table (GET /agents) with enable/disable toggles
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
import type { AgentGraphState, StateTransition } from '../types/agentState';

// ========================
//   CONSTANTS
// ========================

const API_BASE =
  import.meta.env.VITE_COACH_URL ||
  `${window.location.protocol}//${window.location.hostname}:5001`;

const NODE_POSITIONS: Record<string, { x: number; y: number }> = {
  UserInput:             { x: 0,    y: 200 },
  IntentClassifierAgent: { x: 240,  y: 200 },
  GameEngineAgent:       { x: 520,  y: 60  },
  CoachAgent:            { x: 520,  y: 200 },
  PuzzleMasterAgent:     { x: 520,  y: 340 },
  RAGManagerAgent:       { x: 800,  y: 100 },
  MemoryAgent:           { x: 800,  y: 280 },
  TokenLimiterAgent:     { x: 800,  y: 420 },
  OutputAgent:           { x: 1060, y: 200 },
  OnboardingAgent:       { x: 240,  y: 380 },
};

const nodeTypes = { agentNode: AgentNodeComponent };

// ========================
//   TYPES
// ========================

interface AgentRegistryEntry {
  name: string;
  enabled: boolean;
}

type ActiveTab = 'graph' | 'log' | 'registry';

// ========================
//   HELPERS
// ========================

function buildNodes(graphState: AgentGraphState): Node[] {
  return graphState.nodes.map((n) => ({
    id: n.id,
    type: 'agentNode',
    position: NODE_POSITIONS[n.id] || { x: 0, y: 0 },
    data: {
      label: n.label,
      status: n.status,
      visited: n.visited,
      group: n.group,
      agentType: n.type,
    },
  }));
}

function buildEdges(graphState: AgentGraphState): Edge[] {
  return graphState.edges.map((e, i) => ({
    id: `e-${i}-${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    label: e.active ? e.label : '',
    type: 'smoothstep',
    animated: e.active,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    style: {
      stroke: e.active ? '#34d399' : '#334155',
      strokeWidth: e.active ? 2.5 : 1.5,
      opacity: e.active ? 1 : 0.35,
    },
    labelStyle: {
      fill: e.active ? '#34d399' : '#64748b',
      fontSize: 9,
      fontWeight: e.active ? 700 : 400,
    },
  }));
}

function getDefaultNodes(): Node[] {
  const defaults = [
    { id: 'UserInput', label: 'User Input', type: 'input', group: 'io' },
    { id: 'IntentClassifierAgent', label: 'Intent Classifier', type: 'classifier', group: 'core' },
    { id: 'GameEngineAgent', label: 'Game Engine', type: 'agent', group: 'core' },
    { id: 'CoachAgent', label: 'Coach', type: 'agent', group: 'core' },
    { id: 'PuzzleMasterAgent', label: 'Puzzle Master', type: 'agent', group: 'core' },
    { id: 'RAGManagerAgent', label: 'RAG Manager', type: 'agent', group: 'support' },
    { id: 'MemoryAgent', label: 'Memory', type: 'agent', group: 'support' },
    { id: 'TokenLimiterAgent', label: 'Token Limiter', type: 'agent', group: 'support' },
    { id: 'OutputAgent', label: 'Output', type: 'output', group: 'io' },
    { id: 'OnboardingAgent', label: 'Onboarding', type: 'agent', group: 'core' },
  ] as const;

  return defaults.map((d) => ({
    id: d.id,
    type: 'agentNode',
    position: NODE_POSITIONS[d.id] || { x: 0, y: 0 },
    data: { label: d.label, status: 'idle', visited: false, group: d.group, agentType: d.type },
  }));
}

function getDefaultEdges(): Edge[] {
  const defs = [
    { source: 'UserInput', target: 'IntentClassifierAgent', label: 'classify' },
    { source: 'UserInput', target: 'OnboardingAgent', label: 'onboarding' },
    { source: 'IntentClassifierAgent', target: 'GameEngineAgent', label: 'MOVE/UNDO/RESIGN' },
    { source: 'IntentClassifierAgent', target: 'CoachAgent', label: 'WHY/HINT/TEACH/CHAT' },
    { source: 'IntentClassifierAgent', target: 'PuzzleMasterAgent', label: 'puzzle_mode' },
    { source: 'GameEngineAgent', target: 'CoachAgent', label: 'blunder' },
    { source: 'CoachAgent', target: 'RAGManagerAgent', label: 'retrieve' },
    { source: 'CoachAgent', target: 'MemoryAgent', label: 'profile' },
    { source: 'PuzzleMasterAgent', target: 'GameEngineAgent', label: 'validate' },
    { source: 'GameEngineAgent', target: 'OutputAgent', label: 'format' },
    { source: 'CoachAgent', target: 'OutputAgent', label: 'format' },
    { source: 'PuzzleMasterAgent', target: 'OutputAgent', label: 'format' },
    { source: 'OnboardingAgent', target: 'MemoryAgent', label: 'save profile' },
  ];
  return defs.map((d, i) => ({
    id: `e-def-${i}`,
    source: d.source,
    target: d.target,
    label: '',
    type: 'smoothstep',
    animated: false,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    style: { stroke: '#334155', strokeWidth: 1.5, opacity: 0.35 },
  }));
}

// ========================
//   MAIN PAGE COMPONENT
// ========================

export default function AgentsPage() {
  const [graphState, setGraphState] = useState<AgentGraphState | null>(null);
  const [registry, setRegistry] = useState<Record<string, AgentRegistryEntry>>({});
  const [activeTab, setActiveTab] = useState<ActiveTab>('graph');
  const [liveLog, setLiveLog] = useState<StateTransition[]>([]);
  const [requestCount, setRequestCount] = useState(0);
  const [avgLatency, setAvgLatency] = useState(0);
  const [serverOnline, setServerOnline] = useState(false);
  const [togglingAgent, setTogglingAgent] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const requestCountRef = useRef(0);

  // ---- Live polling ----
  const fetchGraph = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/agent-state/graph`);
      if (!res.ok) { setServerOnline(false); return; }
      const data: AgentGraphState = await res.json();
      setGraphState(data);
      setServerOnline(true);

      // Accumulate log entries (deduplicate by id)
      if (data.transitions.length > 0) {
        setLiveLog(prev => {
          const existingIds = new Set(prev.map(t => t.id));
          const newOnes = data.transitions.filter(t => !existingIds.has(t.id));
          if (newOnes.length === 0) return prev;
          const merged = [...prev, ...newOnes].slice(-200);
          return merged;
        });
      }
    } catch {
      setServerOnline(false);
    }
  }, []);

  const fetchLog = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/agent-state/log?last_n=200`);
      if (!res.ok) return;
      const data = await res.json();
      setLiveLog(data.transitions || []);
    } catch { /* silent */ }
  }, []);

  const fetchRegistry = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/agents`);
      if (!res.ok) return;
      const data = await res.json();
      setRegistry(data);
    } catch { /* silent */ }
  }, []);

  // Initial load + polling
  useEffect(() => {
    fetchGraph();
    fetchLog();
    fetchRegistry();
    const poll = setInterval(fetchGraph, 2000);
    const logPoll = setInterval(fetchLog, 5000);
    const regPoll = setInterval(fetchRegistry, 10000);
    return () => { clearInterval(poll); clearInterval(logPoll); clearInterval(regPoll); };
  }, [fetchGraph, fetchLog, fetchRegistry]);

  // Track stats from log
  useEffect(() => {
    const requestEnds = liveLog.filter(t => t.trigger === 'request_end' || t.to_agent === 'OutputAgent');
    if (requestEnds.length > requestCountRef.current) {
      requestCountRef.current = requestEnds.length;
      setRequestCount(requestEnds.length);
      const durations = requestEnds.filter(t => t.duration_ms > 0).map(t => t.duration_ms);
      if (durations.length > 0) {
        setAvgLatency(Math.round(durations.reduce((a, b) => a + b, 0) / durations.length));
      }
    }
  }, [liveLog]);

  // Auto-scroll log
  useEffect(() => {
    if (activeTab === 'log') {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [liveLog, activeTab]);

  // Agent toggle
  const toggleAgent = useCallback(async (name: string, currentlyEnabled: boolean) => {
    setTogglingAgent(name);
    try {
      const enable = !currentlyEnabled;
      await fetch(`${API_BASE}/agents/${name}/toggle?enable=${enable}`, { method: 'POST' });
      await fetchRegistry();
    } catch { /* silent */ }
    setTogglingAgent(null);
  }, [fetchRegistry]);

  // React Flow data
  const nodes: Node[] = useMemo(
    () => graphState ? buildNodes(graphState) : getDefaultNodes(),
    [graphState]
  );
  const edges: Edge[] = useMemo(
    () => graphState ? buildEdges(graphState) : getDefaultEdges(),
    [graphState]
  );

  const activeAgent = graphState?.active_agent;
  const requestId = graphState?.request_id;

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
              value={activeAgent && activeAgent !== 'idle' ? activeAgent.replace('Agent', '') : 'Idle'}
              highlight={!!activeAgent && activeAgent !== 'idle'}
            />
            {requestId && (
              <Stat label="Last Req" value={`REQ:${requestId}`} mono />
            )}
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
            {(['graph', 'log', 'registry'] as ActiveTab[]).map(tab => (
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
              {liveLog.length === 0 ? (
                <div className="text-slate-500 text-xs text-center mt-16">
                  No transitions recorded yet. Send a message in the coaching chat to see the pipeline.
                </div>
              ) : (
                <>
                  {liveLog.slice().reverse().map((t) => (
                    <TransitionCard key={t.id} t={t} />
                  ))}
                  <div ref={logEndRef} />
                </>
              )}
            </div>
          )}

          {activeTab === 'registry' && (
            <RegistryPanel
              registry={registry}
              onToggle={toggleAgent}
              toggling={togglingAgent}
            />
          )}
        </div>

        {/* Right sidebar: live transition feed (always visible on graph tab) */}
        {activeTab === 'graph' && (
          <aside className="w-80 border-l border-white/10 bg-slate-900/50 flex flex-col overflow-hidden shrink-0">
            <div className="px-4 py-2.5 border-b border-white/10 flex items-center justify-between">
              <span className="text-[9px] font-bold text-slate-400 uppercase tracking-widest">Live Transitions</span>
              <span className="text-[9px] text-slate-600">{liveLog.length} total</span>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {liveLog.length === 0 ? (
                <div className="text-slate-600 text-[10px] text-center mt-8">Waiting for pipeline activity...</div>
              ) : (
                liveLog.slice().reverse().slice(0, 50).map((t) => (
                  <MiniTransitionCard key={t.id} t={t} />
                ))
              )}
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

function TransitionCard({ t }: { t: StateTransition }) {
  const [expanded, setExpanded] = useState(false);
  const hasExtra = !!(t.llm_output || t.reasoning || t.error);
  const ts = t.timestamp ? (t.timestamp < 1e12 ? t.timestamp * 1000 : t.timestamp) : 0;
  const timeLabel = ts ? new Date(ts).toLocaleTimeString() : '';
  const metaEntries = t.metadata ? Object.entries(t.metadata) : [];
  const hasMetadata = metaEntries.length > 0;

  return (
    <div
      className={`rounded-lg border p-3 text-[10px] font-mono cursor-pointer transition-colors ${
        t.error
          ? 'bg-red-950/40 border-red-500/30 hover:bg-red-950/60'
          : 'bg-slate-900/60 border-white/10 hover:bg-slate-800/60'
      }`}
      onClick={() => hasExtra && setExpanded(x => !x)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-slate-500 text-[9px]">{t.from_agent}</span>
          <span className="text-emerald-400">→</span>
          <span className="text-slate-100 font-bold">{t.to_agent}</span>
        </div>
        <div className="flex items-center gap-2">
          {timeLabel && <span className="text-slate-600">{timeLabel}</span>}
          {t.duration_ms > 0 && <span className="text-slate-600">{t.duration_ms.toFixed(0)}ms</span>}
          {hasExtra && (
            <span className="text-purple-400 text-[8px]">{expanded ? '▲' : '▼'}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3 mt-1 text-[9px]">
        <span className="text-purple-400">{t.trigger}</span>
        {t.intent && <span className="text-yellow-500/80">intent:{t.intent}</span>}
        {t.response_type && <span className="text-blue-400/80">{t.response_type}</span>}
        {t.user_input_preview && <span className="text-slate-400/80">input:{t.user_input_preview}</span>}
      </div>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          {hasMetadata && (
            <div className="p-2 bg-slate-900/60 rounded text-[9px] leading-relaxed">
              <span className="text-slate-300 font-bold">Metadata: </span>
              <span className="text-slate-400">
                {metaEntries.map(([key, value]) => `${key}=${String(value)}`).join("  ")}
              </span>
            </div>
          )}
          {t.llm_output && (
            <div className="p-2 bg-black/30 rounded text-[9px] leading-relaxed">
              <span className="text-purple-300 font-bold">LLM: </span>
              <span className="text-slate-400">{t.llm_output}</span>
            </div>
          )}
          {t.reasoning && (
            <div className="p-2 bg-black/20 rounded text-[9px] leading-relaxed">
              <span className="text-amber-300 font-bold">Reasoning: </span>
              <span className="text-amber-400/70">{t.reasoning}</span>
            </div>
          )}
          {t.error && (
            <div className="p-2 bg-red-950/40 rounded text-[9px] text-red-400">
              Error: {t.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MiniTransitionCard({ t }: { t: StateTransition }) {
  return (
    <div className={`p-2 rounded border text-[9px] font-mono ${
      t.error ? 'bg-red-950/30 border-red-500/20' : 'bg-white/5 border-white/5'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-slate-500 truncate max-w-[70px]">{t.from_agent.replace('Agent', '')}</span>
          <span className="text-emerald-400">→</span>
          <span className="text-slate-200 font-bold truncate max-w-[80px]">{t.to_agent.replace('Agent', '')}</span>
        </div>
        {t.duration_ms > 0 && (
          <span className="text-slate-600 shrink-0">{t.duration_ms.toFixed(0)}ms</span>
        )}
      </div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className="text-purple-400/80">{t.trigger}</span>
        {t.intent && <span className="text-yellow-500/60">·{t.intent}</span>}
        {t.error && <span className="text-red-400">·ERROR</span>}
      </div>
    </div>
  );
}

function RegistryPanel({
  registry,
  onToggle,
  toggling,
}: {
  registry: Record<string, AgentRegistryEntry>;
  onToggle: (name: string, enabled: boolean) => void;
  toggling: string | null;
}) {
  const entries = Object.values(registry);

  // Sort: enabled first, then by name
  const sorted = [...entries].sort((a, b) => {
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto">
        <h2 className="text-sm font-bold text-slate-200 mb-1">Agent Registry</h2>
        <p className="text-xs text-slate-500 mb-6">
          Enable or disable individual agents in the pipeline. Disabled agents are skipped and return a no-op response.
        </p>

        {entries.length === 0 ? (
          <div className="text-slate-500 text-xs text-center py-12">
            No agents registered. Is the coaching server running?
          </div>
        ) : (
          <div className="space-y-3">
            {sorted.map((agent) => (
              <div
                key={agent.name}
                className={`flex items-center justify-between p-4 rounded-xl border transition-colors ${
                  agent.enabled
                    ? 'bg-white/5 border-white/10'
                    : 'bg-slate-900/40 border-white/5 opacity-60'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${agent.enabled ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                  <div>
                    <p className="text-sm font-bold text-slate-200">{agent.name}</p>
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      {agent.enabled ? 'Active in pipeline' : 'Disabled — skipped during dispatch'}
                    </p>
                  </div>
                </div>

                <button
                  onClick={() => onToggle(agent.name, agent.enabled)}
                  disabled={toggling === agent.name}
                  className={`px-4 h-8 rounded-lg text-[10px] font-bold uppercase tracking-widest border transition-all active:scale-95 ${
                    toggling === agent.name
                      ? 'opacity-50 cursor-not-allowed bg-slate-700 border-slate-600 text-slate-400'
                      : agent.enabled
                      ? 'bg-red-900/30 border-red-500/30 text-red-400 hover:bg-red-900/60'
                      : 'bg-emerald-900/30 border-emerald-500/30 text-emerald-400 hover:bg-emerald-900/60'
                  }`}
                >
                  {toggling === agent.name ? '...' : agent.enabled ? 'Disable' : 'Enable'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
