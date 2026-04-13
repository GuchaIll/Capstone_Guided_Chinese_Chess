import { useState, useCallback, useEffect } from 'react';
import Piece from './Piece';
import {
  PieceType,
  Side,
  Position,
  SuggestedMove,
  EMPTY,
  RED,
  getPieceColor,
  fileToLetter,
} from '../types';
import './ChessBoard.css';

interface ChessBoardProps {
  board: PieceType[][];
  sideToMove: Side;
  onMove: (from: string, to: string) => boolean;
  lastMove?: { from: Position; to: Position };
  legalTargets: string[];
  suggestedMove: SuggestedMove | null;
  onPieceSelected: (square: string) => void;
  onPieceDeselected: () => void;
  aiThinking: boolean;
}

export default function ChessBoard({
  board,
  sideToMove,
  onMove,
  lastMove,
  legalTargets,
  suggestedMove,
  onPieceSelected,
  onPieceDeselected,
  aiThinking,
}: ChessBoardProps) {
  const [selectedPosition, setSelectedPosition] = useState<Position | null>(null);
  const [draggedPiece, setDraggedPiece] = useState<{
    piece: PieceType;
    from: Position;
  } | null>(null);

  // Clear selection when side changes (e.g., after move or AI turn)
  useEffect(() => {
    setSelectedPosition(null);
    onPieceDeselected();
  }, [sideToMove, onPieceDeselected]);

  // Select a piece and notify parent
  const selectPiece = useCallback((file: number, rank: number) => {
    setSelectedPosition({ file, rank });
    const square = `${fileToLetter(file)}${rank}`;
    onPieceSelected(square);
  }, [onPieceSelected]);

  // Deselect
  const deselectPiece = useCallback(() => {
    setSelectedPosition(null);
    onPieceDeselected();
  }, [onPieceDeselected]);

  // Is the player's turn (not AI thinking)?
  const isPlayerTurn = sideToMove === RED && !aiThinking;

  // Handle clicking on an intersection
  const handleIntersectionClick = useCallback((file: number, rank: number) => {
    if (!isPlayerTurn) return;

    const clickedPiece = board[file][rank];
    const clickedPieceColor = getPieceColor(clickedPiece);

    if (selectedPosition) {
      // Clicking on same square - deselect
      if (selectedPosition.file === file && selectedPosition.rank === rank) {
        deselectPiece();
        return;
      }

      // Clicking on another own piece - select it instead
      if (clickedPieceColor === sideToMove) {
        selectPiece(file, rank);
        return;
      }

      // Attempt to move
      const fromStr = `${fileToLetter(selectedPosition.file)}${selectedPosition.rank}`;
      const toStr = `${fileToLetter(file)}${rank}`;

      const success = onMove(fromStr, toStr);
      deselectPiece();

      if (!success) {
        console.log('Move rejected');
      }
    } else {
      // No piece selected - select if it's current player's piece
      if (clickedPieceColor === sideToMove) {
        selectPiece(file, rank);
      }
    }
  }, [board, selectedPosition, sideToMove, onMove, isPlayerTurn, selectPiece, deselectPiece]);

  // Handle drag start
  const handleDragStart = useCallback((file: number, rank: number) => {
    if (!isPlayerTurn) return;

    const piece = board[file][rank];
    const pieceColor = getPieceColor(piece);

    if (pieceColor === sideToMove) {
      setDraggedPiece({ piece, from: { file, rank } });
      selectPiece(file, rank);
    }
  }, [board, sideToMove, isPlayerTurn, selectPiece]);

  // Handle drag end (drop)
  const handleDrop = useCallback((file: number, rank: number) => {
    if (!draggedPiece) return;

    const fromStr = `${fileToLetter(draggedPiece.from.file)}${draggedPiece.from.rank}`;
    const toStr = `${fileToLetter(file)}${rank}`;

    // Don't move to same position
    if (draggedPiece.from.file !== file || draggedPiece.from.rank !== rank) {
      onMove(fromStr, toStr);
    }

    setDraggedPiece(null);
    deselectPiece();
  }, [draggedPiece, onMove, deselectPiece]);

  // Check if a position is part of the last move
  const isLastMovePosition = useCallback((file: number, rank: number): boolean => {
    if (!lastMove) return false;
    return (
      (lastMove.from.file === file && lastMove.from.rank === rank) ||
      (lastMove.to.file === file && lastMove.to.rank === rank)
    );
  }, [lastMove]);

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
          {Array.from({ length: 10 }, (_, rankFromTop) => {
            const rank = 9 - rankFromTop;
            return (
              <div key={rank} className="rank-row">
                {Array.from({ length: 9 }, (_, file) => {
                  const piece = board[file][rank];
                  const isSelected = selectedPosition?.file === file && selectedPosition?.rank === rank;
                  const isLastMove = isLastMovePosition(file, rank);
                  const isLegal = isLegalTarget(file, rank);
                  const isSugFrom = isSuggestedFrom(file, rank);
                  const isSugTo = isSuggestedTo(file, rank);

                  const classNames = [
                    'intersection',
                    isSelected ? 'selected' : '',
                    isLastMove ? 'last-move' : '',
                    isLegal ? 'legal-target' : '',
                    isSugFrom ? 'suggested-from' : '',
                    isSugTo ? 'suggested-to' : '',
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
                          draggable={isPlayerTurn && getPieceColor(piece) === sideToMove}
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
          {['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i'].map((letter) => (
            <span key={letter} className="file-label">{letter}</span>
          ))}
        </div>

        {/* Rank labels (0-9) */}
        <div className="rank-labels">
          {Array.from({ length: 10 }, (_, i) => 9 - i).map((rank) => (
            <span key={rank} className="rank-label">{rank}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
