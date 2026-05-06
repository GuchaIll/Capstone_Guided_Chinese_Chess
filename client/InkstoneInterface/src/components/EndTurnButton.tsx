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
  player_pending: 'Submit Staged Move',
  awaiting_engine: 'Waiting for Engine',
  engine_done: 'Continue',
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
          text-[11px] uppercase tracking-[0.18em] leading-tight
          transition-all shadow-sm select-none
          ${canEndTurn
            ? 'border-black/15 bg-[rgba(24,24,24,0.92)] text-[hsl(40,15%,95%)] hover:-translate-y-0.5 hover:bg-black active:translate-y-0'
            : 'border-black/10 bg-[rgba(255,255,255,0.38)] text-stone-400 cursor-not-allowed'}
        `}
      >
        <span className="block text-[9px] tracking-[0.22em] text-current/70">Turn Control</span>
        <span className="font-calligraphy mt-1 block text-base normal-case tracking-[0.08em]">{PHASE_LABEL[turnPhase]}</span>
      </button>

      <button
        type="button"
        onClick={onTakeBack}
        disabled={!showTakeBack || busy}
        className={`
          min-h-[3.5rem] flex-1 rounded-2xl border px-4 py-3 text-left
          text-[11px] uppercase tracking-[0.18em] leading-tight
          transition-all shadow-sm select-none
          ${showTakeBack && !busy
            ? 'border-black/15 bg-[rgba(247,242,231,0.7)] text-stone-700 hover:-translate-y-0.5 hover:bg-[rgba(247,242,231,0.9)]'
            : 'border-black/10 bg-[rgba(255,255,255,0.38)] text-stone-400 cursor-not-allowed'}
        `}
        aria-label="Take back pending move"
      >
        <span className="block text-[9px] tracking-[0.22em] text-current/70">Staged Move</span>
        <span className="font-calligraphy mt-1 block text-base normal-case tracking-[0.08em]">Take Back</span>
      </button>
    </div>
  );
}
