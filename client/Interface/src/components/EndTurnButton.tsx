import { TurnPhase } from '../types/turnPhase';

interface EndTurnButtonProps {
  turnPhase: TurnPhase;
  hasPendingMove: boolean;
  busy?: boolean;
  onEndTurn: () => void;
  onTakeBack: () => void;
}

const PHASE_LABEL: Record<TurnPhase, string> = {
  player_idle: 'End My Turn',
  player_pending: 'End My Turn',
  awaiting_engine: 'Engine Thinking...',
  engine_done: "End Engine's Turn",
};

export default function EndTurnButton({
  turnPhase,
  hasPendingMove,
  busy = false,
  onEndTurn,
  onTakeBack,
}: EndTurnButtonProps) {
  const canEndTurn =
    !busy &&
    (
      turnPhase === 'player_idle' ||
      (turnPhase === 'player_pending' && hasPendingMove) ||
      turnPhase === 'engine_done'
    );
  const showTakeBack = turnPhase === 'player_pending' && hasPendingMove;

  return (
    <div className="flex w-full flex-row gap-3 md:flex-col md:items-stretch">
      <button
        type="button"
        onClick={onEndTurn}
        disabled={!canEndTurn}
        aria-label={PHASE_LABEL[turnPhase]}
        className={`
          min-h-[3.5rem] flex-1 rounded-2xl border px-4 py-3 text-left
          font-bold text-[11px] uppercase tracking-[0.18em] leading-tight
          transition-all shadow-lg select-none
          ${canEndTurn
            ? 'border-primary/70 bg-primary text-white hover:-translate-y-0.5 hover:shadow-2xl active:translate-y-0'
            : 'border-white/10 bg-white/5 text-slate-500 cursor-not-allowed'}
        `}
      >
        <span className="block text-[9px] text-white/70">Turn Control</span>
        <span className="mt-1 block">{PHASE_LABEL[turnPhase]}</span>
      </button>

      <button
        type="button"
        onClick={onTakeBack}
        disabled={!showTakeBack || busy}
        className={`
          min-h-[3.5rem] flex-1 rounded-2xl border px-4 py-3 text-left
          font-bold text-[11px] uppercase tracking-[0.18em] leading-tight
          transition-all shadow-lg select-none
          ${showTakeBack && !busy
            ? 'border-slate-500/50 bg-slate-100/10 text-slate-100 hover:-translate-y-0.5 hover:bg-slate-100/15'
            : 'border-white/10 bg-white/5 text-slate-500 cursor-not-allowed'}
        `}
        aria-label="Take back pending move"
      >
        <span className="block text-[9px] text-white/70">Staged Move</span>
        <span className="mt-1 block">Take Back</span>
      </button>
    </div>
  );
}
