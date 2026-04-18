/**
 * AgentStateGraph — simplified inline graph view for the main App sidebar.
 * Shows live agent pipeline status without React Flow dependency.
 */
import type { AgentGraphState } from '../types/agentState';

interface Props {
  graphData: AgentGraphState | null;
}

export default function AgentStateGraph({ graphData }: Props) {
  if (!graphData) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-[10px] text-slate-500 uppercase tracking-widest">
          Waiting for agent data…
        </span>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-3 space-y-2">
      <div className="text-[9px] text-slate-500 uppercase tracking-widest font-bold mb-2">
        Agent Pipeline
      </div>

      {graphData.nodes.map((node) => {
        const statusColor =
          node.status === 'active'
            ? 'bg-emerald-500 shadow-[0_0_6px_rgba(52,211,153,0.6)]'
            : node.status === 'completed'
              ? 'bg-blue-500'
              : node.status === 'error'
                ? 'bg-red-500'
                : 'bg-slate-600';

        return (
          <div
            key={node.id}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-[10px] transition-colors ${
              node.status === 'active'
                ? 'bg-emerald-500/10 border-emerald-500/30'
                : 'bg-white/5 border-white/5'
            }`}
          >
            <span className={`w-2 h-2 rounded-full shrink-0 ${statusColor}`} />
            <span className="text-slate-200 font-bold truncate">{node.label}</span>
            <span className="ml-auto text-[8px] text-slate-500 uppercase">{node.status}</span>
          </div>
        );
      })}

      {graphData.active_agent && graphData.active_agent !== 'idle' && (
        <div className="mt-3 text-[9px] text-emerald-400 text-center">
          Active: {graphData.active_agent}
        </div>
      )}
    </div>
  );
}
