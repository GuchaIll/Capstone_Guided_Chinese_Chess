import { useState, useCallback, useEffect, useMemo } from 'react';
import Piece from './Piece';
import {
  PieceType,
  Side,
  Position,
  SuggestedMove,
  EMPTY,
  BLACK,
  getPieceColor,
  fileToLetter,
  notationToPosition,
} from '../types';
import './ChessBoard.css';

interface ChessBoardProps {
  board: PieceType[][];
  sideToMove: Side;
  playerSide: Side;
  onMove: (from: string, to: string) => boolean;
  legalTargets: string[];
  suggestedMove: SuggestedMove | null;
  onPieceSelected: (square: string) => void;
  onPieceDeselected: (reason?: 'manual' | 'move' | 'system') => void;
  aiThinking: boolean;
  opponentMove?: { from: Position; to: Position };
  // Tentative move applied locally but not yet committed to the engine.
  // The board renders this overlay so the player can see their pending move.
  pendingMove: { from: string; to: string } | null;
  // Master interaction gate (controlled by App.tsx turnPhase). When false the
  // board ignores clicks/drags entirely — used to block input while the
  // engine is thinking or while the player needs to acknowledge an AI move.
  canInteract: boolean;
}

export default function ChessBoard({
  board,
  sideToMove,
  playerSide,
  onMove,
  legalTargets,
  suggestedMove,
  onPieceSelected,
  onPieceDeselected,
  aiThinking,
  opponentMove,
  pendingMove,
  canInteract,
}: ChessBoardProps) {
  const [selectedPosition, setSelectedPosition] = useState<Position | null>(null);
  const [draggedPiece, setDraggedPiece] = useState<{
    piece: PieceType;
    from: Position;
  } | null>(null);

  // Resolve pendingMove squares once per render so click/drag handlers can
  // reference them without re-parsing notation.
  const pendingFromPos = useMemo(
    () => (pendingMove ? notationToPosition(pendingMove.from) : null),
    [pendingMove],
  );
  const pendingToPos = useMemo(
    () => (pendingMove ? notationToPosition(pendingMove.to) : null),
    [pendingMove],
  );

  // Display board = committed board with the pending move overlaid. The
  // committed `board` prop remains the engine's truth; this derivation
  // keeps render and state cleanly separated.
  const displayBoard = useMemo(() => {
    if (!pendingFromPos || !pendingToPos) return board;
    const next = board.map((file) => [...file]);
    const piece = next[pendingFromPos.file][pendingFromPos.rank];
    if (piece === EMPTY) return board; // pendingMove out of sync with board
    next[pendingFromPos.file][pendingFromPos.rank] = EMPTY;
    next[pendingToPos.file][pendingToPos.rank] = piece;
    return next;
  }, [board, pendingFromPos, pendingToPos]);

  // Clear selection when side changes (e.g., after move or AI turn)
  useEffect(() => {
    setSelectedPosition(null);
    onPieceDeselected('system');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sideToMove]); // onPieceDeselected is stable; exclude to avoid misleading dep

  // If the pending move is cleared (committed or taken back), drop any
  // stale local selection so the board returns to a clean state.
  useEffect(() => {
    if (!pendingMove) {
      setSelectedPosition(null);
      setDraggedPiece(null);
    }
  }, [pendingMove]);

  useEffect(() => {
    if (!canInteract) {
      setSelectedPosition(null);
      setDraggedPiece(null);
      onPieceDeselected('system');
    }
  }, [canInteract, onPieceDeselected]);

  // Select a piece and notify parent
  const selectPiece = useCallback((file: number, rank: number) => {
    setSelectedPosition({ file, rank });
    const square = `${fileToLetter(file)}${rank}`;
    onPieceSelected(square);
  }, [onPieceSelected]);

  // Deselect
  const deselectPiece = useCallback((reason: 'manual' | 'move' | 'system' = 'manual') => {
    setSelectedPosition(null);
    onPieceDeselected(reason);
  }, [onPieceDeselected]);

  // Is the player's turn (not AI thinking, interaction allowed by App phase)?
  const isPlayerTurn = sideToMove === playerSide && !aiThinking && canInteract;

  // Handle clicking on an intersection
  const handleIntersectionClick = useCallback((file: number, rank: number) => {
    if (!isPlayerTurn) return;

    const clickedPiece = displayBoard[file][rank];
    const clickedPieceColor = getPieceColor(clickedPiece);

    if (selectedPosition) {
      // Clicking on same square - deselect
      if (selectedPosition.file === file && selectedPosition.rank === rank) {
        deselectPiece('manual');
        return;
      }

      // Clicking on another own piece - select it instead
      if (clickedPieceColor === playerSide) {
        selectPiece(file, rank);
        return;
      }

      // Attempt to move
      const fromStr = `${fileToLetter(selectedPosition.file)}${selectedPosition.rank}`;
      const toStr = `${fileToLetter(file)}${rank}`;

      const success = onMove(fromStr, toStr);
      deselectPiece('move');

      if (!success) {
        console.log('Move rejected');
      }
    } else {
      // No piece selected - select if it's current player's piece
      if (clickedPieceColor === playerSide) {
        selectPiece(file, rank);
      }
    }
  }, [displayBoard, selectedPosition, playerSide, onMove, isPlayerTurn, selectPiece, deselectPiece]);

  // Handle drag start
  const handleDragStart = useCallback((file: number, rank: number) => {
    if (!isPlayerTurn) return;

    const piece = displayBoard[file][rank];
    const pieceColor = getPieceColor(piece);

    if (pieceColor === playerSide) {
      setDraggedPiece({ piece, from: { file, rank } });
      selectPiece(file, rank);
    }
  }, [displayBoard, playerSide, isPlayerTurn, selectPiece]);

  // Handle drag end (drop)
  const handleDrop = useCallback((file: number, rank: number) => {
    if (!draggedPiece || !isPlayerTurn) return;

    const fromStr = `${fileToLetter(draggedPiece.from.file)}${draggedPiece.from.rank}`;
    const toStr = `${fileToLetter(file)}${rank}`;

    // Don't move to same position
    if (draggedPiece.from.file !== file || draggedPiece.from.rank !== rank) {
      onMove(fromStr, toStr);
    }

    setDraggedPiece(null);
    deselectPiece('move');
  }, [draggedPiece, onMove, deselectPiece, isPlayerTurn]);

  // Convert file/rank to notation for comparison
  const getNotation = (file: number, rank: number): string => {
    return `${fileToLetter(file)}${rank}`;
  };

  // Check if a square is a legal target
  const isLegalTarget = (file: number, rank: number): boolean => {
    return legalTargets.includes(getNotation(file, rank));
  };

  // Check if a square is the suggested move from/to
  const isSuggestedFrom = (file: number, rank: number): boolean => {
    if (!suggestedMove) return false;
    return suggestedMove.from === getNotation(file, rank);
  };

  const isSuggestedTo = (file: number, rank: number): boolean => {
    if (!suggestedMove) return false;
    return suggestedMove.to === getNotation(file, rank);
  };

  const isOpponentFrom = (file: number, rank: number): boolean => {
    if (!opponentMove) return false;
    return opponentMove.from.file === file && opponentMove.from.rank === rank;
  };

  const isOpponentTo = (file: number, rank: number): boolean => {
    if (!opponentMove) return false;
    return opponentMove.to.file === file && opponentMove.to.rank === rank;
  };

  return (
    <div className="chess-board-container">
      {aiThinking && <div className="ai-thinking-bar">Engine is thinking...</div>}
      <div className="chess-board">
        {/* Grid lines overlay — 56px cell spacing, 28px offset */}
        <svg className="grid-lines" viewBox="0 0 504 560">
          {/* Horizontal lines */}
          {Array.from({ length: 10 }, (_, i) => (
            <line
              key={`h-${i}`}
              x1="0"
              y1={i * 56 + 28}
              x2="504"
              y2={i * 56 + 28}
              stroke="rgba(180, 80, 80, 0.4)"
              strokeWidth="1"
            />
          ))}
          {/* Vertical lines */}
          {Array.from({ length: 9 }, (_, i) => (
            <g key={`v-${i}`}>
              {/* Top half (ranks 5-9) */}
              <line
                x1={i * 56 + 28}
                y1="28"
                x2={i * 56 + 28}
                y2={4 * 56 + 28}
                stroke="rgba(180, 80, 80, 0.4)"
                strokeWidth="1"
              />
              {/* Bottom half (ranks 0-4) */}
              <line
                x1={i * 56 + 28}
                y1={5 * 56 + 28}
                x2={i * 56 + 28}
                y2={9 * 56 + 28}
                stroke="rgba(180, 80, 80, 0.4)"
                strokeWidth="1"
              />
            </g>
          ))}
          {/* Edge vertical lines (cross the river) */}
          <line x1="28" y1={4 * 56 + 28} x2="28" y2={5 * 56 + 28} stroke="rgba(180, 80, 80, 0.4)" strokeWidth="1" />
          <line x1={8 * 56 + 28} y1={4 * 56 + 28} x2={8 * 56 + 28} y2={5 * 56 + 28} stroke="rgba(180, 80, 80, 0.4)" strokeWidth="1" />

          {/* Palace diagonal lines — Black palace (top): files d-f (3-5), ranks 7-9 (rows 0-2) */}
          <line x1={3 * 56 + 28} y1={0 * 56 + 28} x2={5 * 56 + 28} y2={2 * 56 + 28} stroke="rgba(180, 80, 80, 0.4)" strokeWidth="1" />
          <line x1={5 * 56 + 28} y1={0 * 56 + 28} x2={3 * 56 + 28} y2={2 * 56 + 28} stroke="rgba(180, 80, 80, 0.4)" strokeWidth="1" />

          {/* Palace diagonal lines — Red palace (bottom): files d-f (3-5), ranks 0-2 (rows 7-9) */}
          <line x1={3 * 56 + 28} y1={7 * 56 + 28} x2={5 * 56 + 28} y2={9 * 56 + 28} stroke="rgba(180, 80, 80, 0.4)" strokeWidth="1" />
          <line x1={5 * 56 + 28} y1={7 * 56 + 28} x2={3 * 56 + 28} y2={9 * 56 + 28} stroke="rgba(180, 80, 80, 0.4)" strokeWidth="1" />

          {/* River text — between rows 4 and 5 */}
          <text x="120" y={4.5 * 56 + 33} fill="rgba(180, 80, 80, 0.5)" fontSize="18" fontFamily="serif">
            楚 河
          </text>
          <text x="320" y={4.5 * 56 + 33} fill="rgba(180, 80, 80, 0.5)" fontSize="18" fontFamily="serif">
            漢 界
          </text>
        </svg>

        {/* Intersection points and pieces */}
        <div className="intersections">
          {Array.from({ length: 10 }, (_, rankIdx) => {
            const rank = playerSide === BLACK ? rankIdx : 9 - rankIdx;
            return (
              <div key={rank} className="rank-row">
                {Array.from({ length: 9 }, (_, fileIdx) => {
                  const file = playerSide === BLACK ? 8 - fileIdx : fileIdx;
                  const piece = displayBoard[file][rank];
                  const isSelected = selectedPosition?.file === file && selectedPosition?.rank === rank;
                  const isLegal = isLegalTarget(file, rank);
                  const isCaptureTarget = isLegal && piece !== EMPTY && getPieceColor(piece) !== playerSide;
                  const isSugFrom = isSuggestedFrom(file, rank);
                  const isSugTo = isSuggestedTo(file, rank);
                  const isOppFrom = isOpponentFrom(file, rank);
                  const isOppTo = isOpponentTo(file, rank);
                  const isPendFrom = pendingFromPos?.file === file && pendingFromPos?.rank === rank;
                  const isPendTo = pendingToPos?.file === file && pendingToPos?.rank === rank;

                  const classNames = [
                    'intersection',
                    isSelected ? 'selected' : '',
                    isLegal ? 'legal-target' : '',
                    isCaptureTarget ? 'capture-target' : '',
                    isSugFrom ? 'suggested-from' : '',
                    isSugTo ? 'suggested-to' : '',
                    isOppFrom ? 'opponent-from' : '',
                    isOppTo ? 'opponent-to' : '',
                    isPendFrom ? 'pending-from' : '',
                    isPendTo ? 'pending-to' : '',
                  ].filter(Boolean).join(' ');

                  return (
                    <div
                      key={`${file}-${rank}`}
                      className={classNames}
                      onClick={() => handleIntersectionClick(file, rank)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => handleDrop(file, rank)}
                    >
                      {piece !== EMPTY && (
                        <Piece
                          piece={piece}
                          draggable={isPlayerTurn && getPieceColor(piece) === playerSide}
                          onDragStart={() => handleDragStart(file, rank)}
                        />
                      )}
                      {/* Dot indicator for empty legal targets */}
                      {isLegal && piece === EMPTY && (
                        <span className="legal-dot" />
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* File labels (a-i) */}
        <div className="file-labels">
          {(playerSide === BLACK
            ? ['i', 'h', 'g', 'f', 'e', 'd', 'c', 'b', 'a']
            : ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']
          ).map((letter) => (
            <span key={letter} className="file-label">{letter}</span>
          ))}
        </div>

        {/* Rank labels (0-9) */}
        <div className="rank-labels">
          {(playerSide === BLACK
            ? Array.from({ length: 10 }, (_, i) => i)
            : Array.from({ length: 10 }, (_, i) => 9 - i)
          ).map((rank) => (
            <span key={rank} className="rank-label">{rank}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
