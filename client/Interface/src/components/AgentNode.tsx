/**
 * AgentNode — custom ReactFlow node for the Agent Pipeline Inspector.
 */
import { Handle, Position, type NodeProps } from '@xyflow/react';

interface AgentNodeData {
  label: string;
  status: string;
  visited: boolean;
  group: string;
  agentType: string;
  [key: string]: unknown;
}

export default function AgentNode({ data }: NodeProps) {
  const { label, status, visited, group } = data as unknown as AgentNodeData;

  const borderColor =
    status === 'active'
      ? 'border-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.3)]'
      : status === 'completed'
        ? 'border-blue-400'
        : status === 'error'
          ? 'border-red-400'
          : visited
            ? 'border-slate-500'
            : 'border-slate-700';

  const bgColor =
    status === 'active'
      ? 'bg-emerald-500/10'
      : status === 'error'
        ? 'bg-red-500/10'
        : 'bg-slate-900';

  const groupBadgeColor =
    group === 'core'
      ? 'bg-purple-500/20 text-purple-300'
      : group === 'support'
        ? 'bg-amber-500/20 text-amber-300'
        : 'bg-slate-500/20 text-slate-400';

  return (
    <div
      className={`rounded-xl border-2 px-4 py-3 min-w-[140px] transition-all ${borderColor} ${bgColor}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-500 !w-2 !h-2" />

      <div className="flex items-center gap-2 mb-1">
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${
            status === 'active'
              ? 'bg-emerald-400 animate-pulse'
              : status === 'completed'
                ? 'bg-blue-400'
                : status === 'error'
                  ? 'bg-red-400'
                  : 'bg-slate-600'
          }`}
        />
        <span className="text-[11px] font-bold text-slate-100 leading-tight">{label as string}</span>
      </div>

      <div className="flex items-center gap-1.5">
        <span className={`text-[8px] px-1.5 py-0.5 rounded font-bold uppercase ${groupBadgeColor}`}>
          {group as string}
        </span>
        <span className="text-[8px] text-slate-500 uppercase">{status as string}</span>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-slate-500 !w-2 !h-2" />
    </div>
  );
}
