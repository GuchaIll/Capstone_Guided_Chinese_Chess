/** Types for the agent state graph visualization. */

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
