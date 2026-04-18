import { Side, MoveRecord, GameResult, RED, PIECE_INFO, SuggestedMove } from '../types';
import './GameInfo.css';

interface GameInfoProps {
  sideToMove: Side;
  moveHistory: MoveRecord[];
  connectionStatus: 'connected' | 'disconnected';
  onReset: () => void;
  gameResult: GameResult;
  aiThinking: boolean;
  suggestedMove: SuggestedMove | null;
}

export default function GameInfo({
  sideToMove,
  moveHistory,
  connectionStatus,
  onReset,
  gameResult,
  aiThinking,
  suggestedMove,
}: GameInfoProps) {
  const getResultText = () => {
    switch (gameResult) {
      case 'red_wins': return 'Red Wins';
      case 'black_wins': return 'Black Wins';
      case 'draw': return 'Draw';
      default: return null;
    }
  };

  const resultText = getResultText();

  const getTurnText = () => {
    if (aiThinking) return 'Black is thinking...';
    return sideToMove === RED ? 'Red to Move' : 'Black to Move';
  };

  return (
    <div className="game-info">
      <div className="status-section">
        <div className={`connection-status ${connectionStatus}`}>
          <span className="status-dot"></span>
          <span className="status-text">
            {connectionStatus === 'connected' ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        {resultText ? (
          <div className="game-result">{resultText}</div>
        ) : (
          <div className={`turn-indicator ${sideToMove === RED ? 'red' : 'black'} ${aiThinking ? 'thinking' : ''}`}>
            {getTurnText()}
          </div>
        )}
      </div>

      {/* Suggestion panel — only visible during player's turn */}
      {suggestedMove && sideToMove === RED && !aiThinking && (
        <div className="suggestion-panel">
          <div className="suggestion-label">Engine Suggestion</div>
          <div className="suggestion-move">
            {suggestedMove.from} {'->'}  {suggestedMove.to}
            <span className="suggestion-score">
              (score: {suggestedMove.score > 0 ? '+' : ''}{suggestedMove.score})
            </span>
          </div>
        </div>
      )}

      <div className="controls">
        <button className="reset-btn" onClick={onReset}>
          New Game
        </button>
      </div>

      <div className="move-history">
        <h3>Move History</h3>
        <div className="move-list">
          {moveHistory.length === 0 ? (
            <p className="no-moves">No moves yet</p>
          ) : (
            moveHistory.map((move, index) => {
              const pieceInfo = PIECE_INFO[move.piece];
              const capturedInfo = move.captured ? PIECE_INFO[move.captured] : null;
              const captureText = capturedInfo
                ? `x ${capturedInfo.char} (${capturedInfo.name})`
                : '';
              return (
                <div key={index} className={`move-item ${index % 2 === 0 ? 'red-move' : 'black-move'}`}>
                  <span className="move-number">{Math.floor(index / 2) + 1}.</span>
                  <span className="move-piece">
                    <span className="move-piece-char">{pieceInfo?.char || '?'}</span>
                    <span className="move-piece-name">{pieceInfo?.name || '?'}</span>
                  </span>
                  <span className="move-notation">{move.from} {'->'} {move.to}</span>
                  {captureText && <span className="move-capture">{captureText}</span>}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
