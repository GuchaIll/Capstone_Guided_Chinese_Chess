'use client';

import ensoCircle from '../../assets/capture-circle.png';
import type { GameResult } from '../../types';

interface Props {
  result: GameResult;
  lang: 'zh' | 'en';
  onRestart: () => void;
  onQuit: () => void;
}

interface CopyEntry {
  zhTitle: string;
  enTitle: string;
  zhSub: string;
  enSub: string;
}

const COPY: Record<Exclude<GameResult, 'in_progress'>, CopyEntry> = {
  red_wins: {
    zhTitle: '胜',
    enTitle: 'YOU WIN',
    zhSub: '红方胜',
    enSub: 'Red wins',
  },
  black_wins: {
    zhTitle: '负',
    enTitle: 'YOU LOSE',
    zhSub: '黑方胜',
    enSub: 'Black wins',
  },
  draw: {
    zhTitle: '和',
    enTitle: 'DRAW',
    zhSub: '和局',
    enSub: 'Stalemate',
  },
};

export function GameOverModal({ result, lang, onRestart, onQuit }: Props) {
  if (result === 'in_progress') return null;
  const copy = COPY[result];

  const restartLabel = lang === 'zh' ? '重新对弈' : 'Restart';
  const quitLabel = lang === 'zh' ? '返回' : 'Home';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(247, 242, 231, 0.55)', backdropFilter: 'blur(8px)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="game-over-title"
    >
      <div
        className="relative flex flex-col items-center justify-center"
        style={{
          width: 'min(78vw, 520px)',
          height: 'min(78vw, 520px)',
          animation: 'game-over-enter 0.7s cubic-bezier(0.22, 1, 0.36, 1) both',
        }}
      >
        <img
          src={ensoCircle.src}
          alt=""
          aria-hidden
          className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none"
          style={{ animation: 'enso-reveal 0.8s cubic-bezier(0.22, 1, 0.36, 1) both' }}
        />

        <div
          className="relative z-10 flex flex-col items-center justify-center text-center"
          style={{ animation: 'modal-text-in 0.6s 0.35s ease-out both' }}
        >
          <p
            id="game-over-title"
            className="font-calligraphy text-ink leading-none"
            style={{ fontSize: 'clamp(5rem, 14vw, 9rem)' }}
          >
            {lang === 'zh' ? copy.zhTitle : copy.enTitle}
          </p>
          <p className="font-calligraphy text-ink/60 mt-2 tracking-[0.4em] text-sm sm:text-base uppercase">
            {lang === 'zh' ? copy.zhSub : copy.enSub}
          </p>

          <div className="mt-8 sm:mt-10 flex gap-4 sm:gap-6">
            <button
              type="button"
              onClick={onRestart}
              className="px-6 sm:px-8 py-2 border border-ink/40 text-ink font-calligraphy text-base sm:text-lg tracking-widest hover:bg-ink hover:text-rice-paper transition-colors duration-300"
            >
              {restartLabel}
            </button>
            <button
              type="button"
              onClick={onQuit}
              className="px-6 sm:px-8 py-2 border border-ink/40 text-ink/70 font-calligraphy text-base sm:text-lg tracking-widest hover:bg-ink/80 hover:text-rice-paper transition-colors duration-300"
            >
              {quitLabel}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes game-over-enter {
          0% { opacity: 0; transform: scale(0.85); filter: blur(6px); }
          100% { opacity: 1; transform: scale(1); filter: blur(0); }
        }
        @keyframes enso-reveal {
          0% { opacity: 0; transform: scale(0.65) rotate(-22deg); filter: blur(8px); }
          60% { opacity: 0.95; filter: blur(2px); }
          100% { opacity: 1; transform: scale(1) rotate(0deg); filter: blur(0); }
        }
        @keyframes modal-text-in {
          0% { opacity: 0; transform: translateY(10px); filter: blur(4px); }
          100% { opacity: 1; transform: translateY(0); filter: blur(0); }
        }
      `}</style>
    </div>
  );
}
