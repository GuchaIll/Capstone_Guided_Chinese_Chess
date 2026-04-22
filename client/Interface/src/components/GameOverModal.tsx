import type { GameResult } from '../types';

interface GameOverModalProps {
  result: GameResult;
  playerSide: 'red' | 'black';
  onNewGame: () => void;
  onAnalyze: () => void;
}

export default function GameOverModal({ result, playerSide, onNewGame, onAnalyze }: GameOverModalProps) {
  if (result === 'in_progress') return null;

  const playerWon =
    (playerSide === 'red' && result === 'red_wins') ||
    (playerSide === 'black' && result === 'black_wins');

  const isDraw = result === 'draw';

  const title = isDraw ? 'Draw!' : playerWon ? 'You Win!' : 'You Lose!';
  const subtitle = isDraw
    ? 'The game ended in a draw.'
    : playerWon
    ? 'Congratulations — you defeated the AI.'
    : 'Better luck next time!';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-slate-900 border border-white/10 rounded-2xl shadow-2xl p-8 max-w-sm w-full mx-4 flex flex-col items-center gap-6">
        <div className="text-5xl">{isDraw ? '🤝' : playerWon ? '🏆' : '💀'}</div>
        <div className="text-center">
          <h2 className="text-2xl font-bold text-white mb-1">{title}</h2>
          <p className="text-slate-400 text-sm">{subtitle}</p>
        </div>
        <div className="flex gap-3 w-full">
          <button
            onClick={onAnalyze}
            className="flex-1 px-4 py-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm font-semibold transition-all"
          >
            Analyze
          </button>
          <button
            onClick={onNewGame}
            className="flex-1 px-4 py-2.5 rounded-lg bg-primary hover:bg-primary/80 text-white text-sm font-semibold transition-all"
          >
            New Game
          </button>
        </div>
      </div>
    </div>
  );
}
