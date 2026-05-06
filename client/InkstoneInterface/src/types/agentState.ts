/** Types for the Go agent framework dashboard visualization. */

// ---- Go Dashboard SSE Event ----

export interface DashboardEvent {
  type: string;
  ts: number;
  graph?: string;
  agent?: string;
  session?: string;
  status?: string;
  sub_process?: string;
  sub_kind?: string;
  duration_ms?: number;
  message?: string;
  detail?: Record<string, unknown>;
}

// ---- Go /dashboard/graph response ----

export interface GraphNodeInfo {
  id: string;
  description?: string;
  tools?: string[];
  skills?: string[];
  rag?: string[];
  agents?: string[];
  model?: string;
}

export interface GraphEdgeInfo {
  source: string;
  target: string;
  parallel: boolean;
}

export interface GraphInfo {
  name: string;
  nodes: GraphNodeInfo[];
  edges: GraphEdgeInfo[];
}

// ---- ReactFlow presentation types ----

export interface AgentNodeState {
  id: string;
  label: string;
  status: 'idle' | 'active' | 'completed' | 'error';
  visited: boolean;
  group: string;
  type: string;
}

export interface AgentEdgeState {
  source: string;
  target: string;
  label: string;
  active: boolean;
}

export interface StateTransition {
  id: string;
  from_agent: string;
  to_agent: string;
  trigger: string;
  timestamp: number;
  duration_ms: number;
  intent?: string;
  response_type?: string;
  user_input_preview?: string;
  llm_output?: string;
  reasoning?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface AgentGraphState {
  nodes: AgentNodeState[];
  edges: AgentEdgeState[];
  transitions: StateTransition[];
  active_agent: string | null;
  request_id: string | null;
}
