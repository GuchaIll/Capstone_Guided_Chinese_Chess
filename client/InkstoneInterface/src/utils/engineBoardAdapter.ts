import type { GameResult } from '../types';
import type { Board, Piece } from '../lib/xiangqiRules';

type PieceColor = Piece['color'];
type PieceType = Piece['type'];

const INITIAL_PIECE_COUNTS: Record<PieceColor, Record<PieceType, number>> = {
  red: {
    king: 1,
    advisor: 2,
    elephant: 2,
    horse: 2,
    rook: 2,
    cannon: 2,
    pawn: 5,
  },
  black: {
    king: 1,
    advisor: 2,
    elephant: 2,
    horse: 2,
    rook: 2,
    cannon: 2,
    pawn: 5,
  },
};

function pieceFromFenChar(char: string): Piece | null {
  const color: PieceColor = char === char.toUpperCase() ? 'red' : 'black';
  switch (char.toLowerCase()) {
    case 'k':
      return { type: 'king', color };
    case 'a':
      return { type: 'advisor', color };
    case 'b':
    case 'e':
      return { type: 'elephant', color };
    case 'n':
    case 'h':
      return { type: 'horse', color };
    case 'r':
      return { type: 'rook', color };
    case 'c':
      return { type: 'cannon', color };
    case 'p':
      return { type: 'pawn', color };
    default:
      return null;
  }
}

export function fenToInkstoneBoard(fen: string): Board {
  const board: Board = Array.from({ length: 10 }, () => Array(9).fill(null));
  const placement = fen.trim().split(/\s+/)[0] ?? '';
  let row = 0;
  let col = 0;

  for (const char of placement) {
    if (char === '/') {
      row += 1;
      col = 0;
      continue;
    }

    if (char >= '1' && char <= '9') {
      col += Number.parseInt(char, 10);
      continue;
    }

    const piece = pieceFromFenChar(char);
    if (piece && row >= 0 && row < 10 && col >= 0 && col < 9) {
      board[row][col] = piece;
      col += 1;
    }
  }

  return board;
}

export function fenToInkstoneTurn(fen: string): PieceColor {
  const sideToken = fen.trim().split(/\s+/)[1]?.toLowerCase();
  return sideToken === 'b' || sideToken === 'black' ? 'black' : 'red';
}

export function normalizeEngineResult(result: unknown): GameResult {
  if (
    result === 'in_progress' ||
    result === 'red_wins' ||
    result === 'black_wins' ||
    result === 'draw'
  ) {
    return result;
  }
  return 'in_progress';
}

export function deriveGamePhaseFromFen(fen: string): 'opening' | 'middlegame' | 'endgame' {
  const placement = fen.trim().split(/\s+/)[0] ?? '';
  let pieceCount = 0;

  for (const char of placement) {
    if (char === '/' || (char >= '1' && char <= '9')) continue;
    if (pieceFromFenChar(char)) pieceCount += 1;
  }

  const moveNumberToken = Number.parseInt(fen.trim().split(/\s+/)[5] ?? '0', 10);
  const moveNumber = Number.isFinite(moveNumberToken) ? moveNumberToken : 0;

  if (pieceCount <= 12) return 'endgame';
  if (moveNumber <= 10 || pieceCount >= 28) return 'opening';
  return 'middlegame';
}

export function coordsToSquare(row: number, col: number): string {
  return `${String.fromCharCode('a'.charCodeAt(0) + col)}${9 - row}`;
}

export function squareToCoords(square: string): [number, number] | null {
  if (!/^[a-i][0-9]$/.test(square)) return null;
  const col = square.charCodeAt(0) - 'a'.charCodeAt(0);
  const rank = Number.parseInt(square[1], 10);
  return [9 - rank, col];
}

export function moveStringToSquares(
  move: string,
): { from: [number, number]; to: [number, number] } | null {
  if (move.length !== 4) return null;
  const from = squareToCoords(move.slice(0, 2));
  const to = squareToCoords(move.slice(2, 4));
  if (!from || !to) return null;
  return { from, to };
}

export function legalTargetsToCoords(targets: string[]): [number, number][] {
  return targets
    .map((target) => squareToCoords(target))
    .filter((coords): coords is [number, number] => coords !== null);
}

function emptyPieceCounts(): Record<PieceColor, Record<PieceType, number>> {
  return {
    red: {
      king: 0,
      advisor: 0,
      elephant: 0,
      horse: 0,
      rook: 0,
      cannon: 0,
      pawn: 0,
    },
    black: {
      king: 0,
      advisor: 0,
      elephant: 0,
      horse: 0,
      rook: 0,
      cannon: 0,
      pawn: 0,
    },
  };
}

export function inferCapturedPieces(board: Board): { red: Piece[]; black: Piece[] } {
  const remaining = emptyPieceCounts();

  for (const row of board) {
    for (const piece of row) {
      if (!piece) continue;
      remaining[piece.color][piece.type] += 1;
    }
  }

  const captured = { red: [] as Piece[], black: [] as Piece[] };
  (['red', 'black'] as const).forEach((color) => {
    (Object.keys(INITIAL_PIECE_COUNTS[color]) as PieceType[]).forEach((type) => {
      const missing = INITIAL_PIECE_COUNTS[color][type] - remaining[color][type];
      if (missing <= 0) return;
      const capturedBy = color === 'black' ? 'red' : 'black';
      for (let i = 0; i < missing; i += 1) {
        captured[capturedBy].push({ color, type });
      }
    });
  });

  return captured;
}
