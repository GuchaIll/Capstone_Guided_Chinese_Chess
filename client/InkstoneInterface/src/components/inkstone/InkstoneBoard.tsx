import { useState, useCallback, useEffect, useMemo } from 'react';
import brushStroke from '../../assets/brush-stroke.png';
import { useInkSounds } from '../../hooks/useInkSounds';
import {
  type PieceType,
  type Side,
  type Position,
  type SuggestedMove,
  EMPTY,
  RED,
  BLACK,
  PIECE_INFO,
  getPieceColor,
  fileToLetter,
  notationToPosition,
} from '../../types';

interface InkstoneBoardProps {
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
  pendingMove: { from: string; to: string } | null;
  canInteract: boolean;
}

const generateBlobPath = (seed: number): string => {
  const points: string[] = [];
  const steps = 12;
  for (let i = 0; i < steps; i += 1) {
    const angle = (i / steps) * Math.PI * 2;
    const wobble = 3 + Math.sin(seed * 7.3 + i * 2.1) * 4 + Math.cos(seed * 3.7 + i * 1.3) * 3;
    const radius = 50 - wobble;
    const x = 50 + radius * Math.cos(angle);
    const y = 50 + radius * Math.sin(angle);
    points.push(`${x}% ${y}%`);
  }
  return `polygon(${points.join(', ')})`;
};

const brushLine = (x1: number, y1: number, x2: number, y2: number, seed: number): string => {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  const steps = Math.max(4, Math.floor(len / 30));
  const points: string[] = [`M ${x1} ${y1}`];
  for (let i = 1; i < steps; i += 1) {
    const t = i / steps;
    const wobbleX = Math.sin(seed + i * 2.7) * 1.2;
    const wobbleY = Math.cos(seed + i * 3.1) * 1.2;
    points.push(`L ${x1 + dx * t + wobbleX} ${y1 + dy * t + wobbleY}`);
  }
  points.push(`L ${x2} ${y2}`);
  return points.join(' ');
};

const turnLabel = (side: Side): string => (side === RED ? '红方执棋' : '黑方执棋');

export default function InkstoneBoard({
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
}: InkstoneBoardProps) {
  const { playBrush, playWhoosh } = useInkSounds();
  const [selectedPosition, setSelectedPosition] = useState<Position | null>(null);
  const [hintPulseKey, setHintPulseKey] = useState(0);

  const pendingFromPos = useMemo(
    () => (pendingMove ? notationToPosition(pendingMove.from) : null),
    [pendingMove],
  );
  const pendingToPos = useMemo(
    () => (pendingMove ? notationToPosition(pendingMove.to) : null),
    [pendingMove],
  );

  const displayBoard = useMemo(() => {
    if (!pendingFromPos || !pendingToPos) return board;
    const next = board.map((file) => [...file]);
    const piece = next[pendingFromPos.file][pendingFromPos.rank];
    if (piece === EMPTY) return board;
    next[pendingFromPos.file][pendingFromPos.rank] = EMPTY;
    next[pendingToPos.file][pendingToPos.rank] = piece;
    return next;
  }, [board, pendingFromPos, pendingToPos]);

  useEffect(() => {
    setSelectedPosition(null);
    onPieceDeselected('system');
  }, [sideToMove, onPieceDeselected]);

  useEffect(() => {
    if (!pendingMove) {
      setSelectedPosition(null);
    }
  }, [pendingMove]);

  useEffect(() => {
    if (!canInteract) {
      setSelectedPosition(null);
      onPieceDeselected('system');
    }
  }, [canInteract, onPieceDeselected]);

  useEffect(() => {
    if (suggestedMove) {
      setHintPulseKey((current) => current + 1);
    }
  }, [suggestedMove]);

  const isPlayerTurn = sideToMove === playerSide && !aiThinking && canInteract;

  const selectPiece = useCallback((file: number, rank: number) => {
    setSelectedPosition({ file, rank });
    onPieceSelected(`${fileToLetter(file)}${rank}`);
    playBrush();
  }, [onPieceSelected, playBrush]);

  const deselectPiece = useCallback((reason: 'manual' | 'move' | 'system' = 'manual') => {
    setSelectedPosition(null);
    onPieceDeselected(reason);
  }, [onPieceDeselected]);

  const isLegalTarget = useCallback((file: number, rank: number): boolean => (
    legalTargets.includes(`${fileToLetter(file)}${rank}`)
  ), [legalTargets]);

  const handleCellClick = useCallback((file: number, rank: number) => {
    if (!isPlayerTurn) return;

    const clickedPiece = displayBoard[file][rank];
    const clickedPieceColor = getPieceColor(clickedPiece);

    if (selectedPosition) {
      if (selectedPosition.file === file && selectedPosition.rank === rank) {
        deselectPiece('manual');
        return;
      }

      if (clickedPieceColor === playerSide) {
        selectPiece(file, rank);
        return;
      }

      const fromStr = `${fileToLetter(selectedPosition.file)}${selectedPosition.rank}`;
      const toStr = `${fileToLetter(file)}${rank}`;

      const success = onMove(fromStr, toStr);
      deselectPiece('move');
      if (success) {
        playWhoosh();
      }
      return;
    }

    if (clickedPieceColor === playerSide) {
      selectPiece(file, rank);
    }
  }, [
    deselectPiece,
    displayBoard,
    isPlayerTurn,
    onMove,
    playerSide,
    playWhoosh,
    selectPiece,
    selectedPosition,
  ]);

  const BASE_CELL = 56;
  const margin = BASE_CELL / 2;
  const svgW = 8 * BASE_CELL;
  const svgH = 9 * BASE_CELL;
  const totalW = svgW + BASE_CELL;
  const totalH = svgH + BASE_CELL;
  const boardPad = 16;
  const fullW = totalW + boardPad * 2;
  const fullH = totalH + boardPad * 2;

  return (
    <div className="flex w-full flex-col items-center">
      <div className="mb-3 relative" key={sideToMove}>
        {sideToMove === BLACK ? (
          <div className="relative flex items-center justify-center overflow-hidden px-6 py-2 sm:px-8">
            <img
              src={brushStroke.src}
              alt=""
              className="absolute inset-0 h-full w-full object-cover opacity-80 pointer-events-none"
              style={{ animation: 'brush-swipe 0.6s cubic-bezier(0.22,1,0.36,1) forwards' }}
            />
            <span
              className="font-calligraphy relative z-10 text-base tracking-wider text-[hsl(40,15%,95%)] sm:text-lg"
              style={{ animation: 'turn-text-in 0.5s 0.2s ease-out both' }}
            >
              {turnLabel(sideToMove)}
            </span>
          </div>
        ) : (
          <div className="flex items-center justify-center px-6 py-2 sm:px-8">
            <span
              className="font-calligraphy text-base tracking-wider text-stone-900 sm:text-lg"
              style={{ animation: 'turn-text-in 0.4s ease-out both' }}
            >
              {turnLabel(sideToMove)}
            </span>
          </div>
        )}
      </div>

      <div className="inkstone-board-scale-wrapper" style={{ width: fullW, height: fullH }}>
        <div className="relative h-full w-full">
          <div className="absolute inset-0 rounded-sm bg-[rgba(247,242,231,0.18)] backdrop-blur-lg" />
          <div className="absolute inset-0 bg-gradient-to-br from-[rgba(247,242,231,0.12)] via-transparent to-[rgba(247,242,231,0.06)]" />

          <svg
            className="absolute"
            style={{ left: boardPad, top: boardPad, width: totalW, height: totalH }}
            viewBox={`0 0 ${totalW} ${totalH}`}
          >
            <defs>
              <filter id="inkTexture">
                <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="4" result="noise" />
                <feDisplacementMap in="SourceGraphic" in2="noise" scale="2" />
              </filter>
            </defs>

            {Array.from({ length: 10 }, (_, i) => (
              <path
                key={`h${i}`}
                d={brushLine(margin, margin + i * BASE_CELL, margin + svgW, margin + i * BASE_CELL, i * 7.3)}
                stroke="hsl(0 0% 8% / 0.35)"
                strokeWidth={1.5}
                fill="none"
                filter="url(#inkTexture)"
              />
            ))}

            {Array.from({ length: 9 }, (_, i) => (
              <g key={`v${i}`}>
                <path
                  d={brushLine(margin + i * BASE_CELL, margin, margin + i * BASE_CELL, margin + 4 * BASE_CELL, i * 5.1)}
                  stroke="hsl(0 0% 8% / 0.35)"
                  strokeWidth={1.5}
                  fill="none"
                  filter="url(#inkTexture)"
                />
                <path
                  d={brushLine(margin + i * BASE_CELL, margin + 5 * BASE_CELL, margin + i * BASE_CELL, margin + 9 * BASE_CELL, i * 5.1 + 100)}
                  stroke="hsl(0 0% 8% / 0.35)"
                  strokeWidth={1.5}
                  fill="none"
                  filter="url(#inkTexture)"
                />
              </g>
            ))}

            <path d={brushLine(margin, margin, margin, margin + 9 * BASE_CELL, 99)} stroke="hsl(0 0% 8% / 0.45)" strokeWidth={2} fill="none" filter="url(#inkTexture)" />
            <path d={brushLine(margin + 8 * BASE_CELL, margin, margin + 8 * BASE_CELL, margin + 9 * BASE_CELL, 101)} stroke="hsl(0 0% 8% / 0.45)" strokeWidth={2} fill="none" filter="url(#inkTexture)" />

            <path d={brushLine(margin + 3 * BASE_CELL, margin, margin + 5 * BASE_CELL, margin + 2 * BASE_CELL, 200)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />
            <path d={brushLine(margin + 5 * BASE_CELL, margin, margin + 3 * BASE_CELL, margin + 2 * BASE_CELL, 201)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />
            <path d={brushLine(margin + 3 * BASE_CELL, margin + 7 * BASE_CELL, margin + 5 * BASE_CELL, margin + 9 * BASE_CELL, 202)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />
            <path d={brushLine(margin + 5 * BASE_CELL, margin + 7 * BASE_CELL, margin + 3 * BASE_CELL, margin + 9 * BASE_CELL, 203)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />

            <text
              x={totalW / 2}
              y={margin + 4.5 * BASE_CELL + 6}
              textAnchor="middle"
              fill="hsl(0 0% 8% / 0.18)"
              fontSize="20"
              fontFamily="'Ma Shan Zheng', cursive"
              letterSpacing="24"
            >
              楚河　　漢界
            </text>
          </svg>

          {selectedPosition && legalTargets.map((target) => {
            const pos = notationToPosition(target);
            if (!pos) return null;
            const x = boardPad + margin + pos.file * BASE_CELL;
            const y = boardPad + margin + (9 - pos.rank) * BASE_CELL;
            const targetPiece = displayBoard[pos.file][pos.rank];
            const hasEnemy = targetPiece !== EMPTY && getPieceColor(targetPiece) !== playerSide;
            return (
              <div
                key={`legal-${target}`}
                className="absolute pointer-events-none"
                style={{
                  left: x - (hasEnemy ? 22 : 10),
                  top: y - (hasEnemy ? 22 : 10),
                  width: hasEnemy ? 44 : 20,
                  height: hasEnemy ? 44 : 20,
                }}
              >
                <div className={hasEnemy ? 'ink-capture-ring' : 'ink-legal-dot'} />
              </div>
            );
          })}

          {suggestedMove ? (
            <>
              {[suggestedMove.from, suggestedMove.to].map((square, idx) => {
                const pos = notationToPosition(square);
                if (!pos) return null;
                const x = boardPad + margin + pos.file * BASE_CELL;
                const y = boardPad + margin + (9 - pos.rank) * BASE_CELL;
                return (
                  <div
                    key={`hint-${square}-${hintPulseKey}`}
                    className="absolute pointer-events-none hint-ink-spread"
                    style={{
                      left: x - 26,
                      top: y - 26,
                      width: 52,
                      height: 52,
                      animationDelay: idx === 1 ? '0.15s' : '0s',
                    }}
                  />
                );
              })}
            </>
          ) : null}

          {Array.from({ length: 10 }, (_, displayRow) => {
            const rank = 9 - displayRow;
            return Array.from({ length: 9 }, (_, file) => {
              const piece = displayBoard[file][rank];
              if (piece === EMPTY) {
                const pieceSize = BASE_CELL - 8;
                const x = boardPad + margin + file * BASE_CELL - pieceSize / 2;
                const y = boardPad + margin + displayRow * BASE_CELL - pieceSize / 2;
                const legal = selectedPosition !== null && isLegalTarget(file, rank);
                return (
                  <button
                    key={`empty-${file}-${rank}`}
                    onClick={() => handleCellClick(file, rank)}
                    className={`absolute transition-opacity ${legal ? 'cursor-pointer opacity-100' : 'opacity-0'}`}
                    style={{ width: pieceSize, height: pieceSize, left: x, top: y }}
                    aria-label={`Move target ${fileToLetter(file)}${rank}`}
                  />
                );
              }

              const info = PIECE_INFO[piece];
              if (!info) return null;

              const pieceSize = BASE_CELL - 8;
              const x = boardPad + margin + file * BASE_CELL - pieceSize / 2;
              const y = boardPad + margin + displayRow * BASE_CELL - pieceSize / 2;
              const isSelected = selectedPosition?.file === file && selectedPosition?.rank === rank;
              const isBlack = info.color === 'black';
              const blobClip = isBlack ? generateBlobPath(rank * 9 + file) : undefined;
              const isOpponentFrom = opponentMove?.from.file === file && opponentMove?.from.rank === rank;
              const isOpponentTo = opponentMove?.to.file === file && opponentMove?.to.rank === rank;
              const isPendingFrom = pendingFromPos?.file === file && pendingFromPos.rank === rank;
              const isPendingTo = pendingToPos?.file === file && pendingToPos.rank === rank;

              return (
                <button
                  key={`${file}-${rank}`}
                  onClick={() => handleCellClick(file, rank)}
                  className={`absolute flex items-center justify-center transition-all duration-300 cursor-pointer group ${
                    isBlack
                      ? 'piece-black text-[hsl(40,15%,95%)]'
                      : 'piece-red border border-black/20 bg-[rgba(247,242,231,0.88)] text-stone-900'
                  } ${isSelected ? 'piece-selected scale-110' : 'hover:scale-105'}`}
                  style={{
                    width: pieceSize,
                    height: pieceSize,
                    left: x,
                    top: y,
                    clipPath: isBlack ? blobClip : undefined,
                    borderRadius: isBlack ? undefined : '50%',
                    outline: isOpponentFrom
                      ? '2px solid rgba(54, 115, 255, 0.8)'
                      : isOpponentTo
                      ? '2px solid rgba(165, 86, 255, 0.85)'
                      : isPendingFrom || isPendingTo
                      ? '2px solid rgba(217, 119, 6, 0.75)'
                      : undefined,
                  }}
                  aria-label={`${info.name} ${fileToLetter(file)}${rank}`}
                >
                  <div
                    className={`absolute inset-[-6px] rounded-full opacity-0 pointer-events-none transition-opacity duration-500 group-hover:opacity-100 ${
                      isBlack ? 'bg-black/20 blur-md' : 'bg-white/60 blur-md'
                    }`}
                  />
                  {isSelected ? (
                    <div className={`absolute inset-[-8px] rounded-full pointer-events-none ${isBlack ? 'ink-select-glow-black' : 'ink-select-glow-red'}`} />
                  ) : null}
                  <span className="font-calligraphy relative z-10 select-none text-xl leading-none">
                    {info.char}
                  </span>
                </button>
              );
            });
          })}
        </div>
      </div>

      <style>{`
        .inkstone-board-scale-wrapper {
          transform-origin: top center;
        }
        @media (max-width: 560px) {
          .inkstone-board-scale-wrapper {
            transform: scale(0.7);
            margin-bottom: -${Math.round(fullH * 0.3)}px;
          }
        }
        @media (min-width: 561px) and (max-width: 680px) {
          .inkstone-board-scale-wrapper {
            transform: scale(0.82);
            margin-bottom: -${Math.round(fullH * 0.18)}px;
          }
        }
        @media (min-width: 681px) and (max-width: 800px) {
          .inkstone-board-scale-wrapper {
            transform: scale(0.92);
            margin-bottom: -${Math.round(fullH * 0.08)}px;
          }
        }

        @keyframes brush-swipe {
          0% { clip-path: inset(0 100% 0 0); opacity: 0.4; }
          60% { opacity: 0.9; }
          100% { clip-path: inset(0 0 0 0); opacity: 0.8; }
        }

        @keyframes turn-text-in {
          0% { opacity: 0; transform: translateY(6px); filter: blur(4px); }
          100% { opacity: 1; transform: translateY(0); filter: blur(0); }
        }

        .piece-black {
          background: hsl(0 0% 8% / 0.85);
          box-shadow: 0 0 6px 2px hsl(0 0% 8% / 0.15);
          animation: ink-spread-settle 1.5s ease-out forwards;
        }
        .piece-black:hover {
          box-shadow: 0 0 14px 5px hsl(0 0% 8% / 0.25), 0 0 30px 8px hsl(0 0% 8% / 0.08);
          backdrop-filter: blur(4px);
        }

        @keyframes ink-spread-settle {
          0% { box-shadow: 0 0 0px 0px hsl(0 0% 8% / 0); filter: blur(2px); }
          40% { box-shadow: 0 0 10px 4px hsl(0 0% 8% / 0.25); filter: blur(0.5px); }
          70% { box-shadow: 0 0 8px 3px hsl(0 0% 8% / 0.2); filter: blur(0); }
          100% { box-shadow: 0 0 6px 2px hsl(0 0% 8% / 0.15); filter: blur(0); }
        }

        .piece-red:hover {
          box-shadow: 0 0 12px 4px hsl(40 15% 95% / 0.5), 0 0 24px 6px hsl(0 0% 8% / 0.06);
          backdrop-filter: blur(3px);
        }

        .piece-selected.piece-black {
          box-shadow: 0 0 18px 6px hsl(0 0% 8% / 0.35), 0 0 40px 12px hsl(0 0% 8% / 0.12);
        }
        .piece-selected.piece-red {
          box-shadow: 0 0 16px 5px hsl(40 15% 80% / 0.6), 0 0 32px 10px hsl(0 0% 8% / 0.08);
        }

        .ink-select-glow-black {
          background: radial-gradient(circle, hsl(0 0% 8% / 0.2) 0%, transparent 70%);
          animation: ink-pulse 1.5s ease-in-out infinite;
        }
        .ink-select-glow-red {
          background: radial-gradient(circle, hsl(0 0% 50% / 0.15) 0%, transparent 70%);
          animation: ink-pulse 1.5s ease-in-out infinite;
        }

        @keyframes ink-pulse {
          0%, 100% { transform: scale(1); opacity: 0.6; }
          50% { transform: scale(1.2); opacity: 0.9; }
        }

        .ink-legal-dot {
          width: 100%;
          height: 100%;
          border-radius: 50%;
          background: radial-gradient(circle, hsl(0 0% 8% / 0.35) 0%, hsl(0 0% 8% / 0.1) 50%, transparent 70%);
          animation: ink-dot-appear 0.4s ease-out forwards;
        }

        .ink-capture-ring {
          width: 100%;
          height: 100%;
          border-radius: 50%;
          background: radial-gradient(circle, transparent 40%, hsl(0 0% 8% / 0.2) 55%, hsl(0 0% 8% / 0.1) 65%, transparent 75%);
          animation: ink-dot-appear 0.4s ease-out forwards;
        }

        @keyframes ink-dot-appear {
          0% { transform: scale(0); opacity: 0; filter: blur(4px); }
          60% { filter: blur(1px); }
          100% { transform: scale(1); opacity: 1; filter: blur(0.5px); }
        }

        .hint-ink-spread {
          border-radius: 50%;
          background: radial-gradient(circle, hsl(0 0% 8% / 0.3) 0%, hsl(0 0% 8% / 0.15) 40%, transparent 70%);
          animation: hint-spread 2.8s ease-out forwards;
        }

        @keyframes hint-spread {
          0% { transform: scale(0); opacity: 0; filter: blur(6px); }
          15% { transform: scale(0.6); opacity: 0.8; filter: blur(2px); }
          30% { transform: scale(1); opacity: 0.6; filter: blur(1px); }
          60% { transform: scale(1.15); opacity: 0.4; filter: blur(2px); }
          100% { transform: scale(1.3); opacity: 0; filter: blur(6px); }
        }
      `}</style>
    </div>
  );
}
