import { useState, useCallback } from 'react';
import {
  GameState,
  PieceType,
  Side,
  Position,
  MoveRecord,
  RED,
  BLACK,
  EMPTY,
  RED_PAWN,
  RED_ADVISOR,
  RED_ELEPHANT,
  RED_KNIGHT,
  RED_CANNON,
  RED_ROOK,
  RED_KING,
  BLACK_PAWN,
  BLACK_ADVISOR,
  BLACK_ELEPHANT,
  BLACK_KNIGHT,
  BLACK_CANNON,
  BLACK_ROOK,
  BLACK_KING,
  START_FEN,
  getPieceColor,
  notationToPosition,
} from '../types';

// Create empty 9x10 board
function createEmptyBoard(): PieceType[][] {
  return Array(9).fill(null).map(() => Array(10).fill(EMPTY));
}

// Parse FEN character to piece type
function charToPiece(c: string): PieceType {
  switch (c) {
    case 'P': return RED_PAWN;
    case 'A': return RED_ADVISOR;
    case 'B': case 'E': return RED_ELEPHANT;
    case 'N': case 'H': return RED_KNIGHT;
    case 'C': return RED_CANNON;
    case 'R': return RED_ROOK;
    case 'K': return RED_KING;
    case 'p': return BLACK_PAWN;
    case 'a': return BLACK_ADVISOR;
    case 'b': case 'e': return BLACK_ELEPHANT;
    case 'n': case 'h': return BLACK_KNIGHT;
    case 'c': return BLACK_CANNON;
    case 'r': return BLACK_ROOK;
    case 'k': return BLACK_KING;
    default: return EMPTY;
  }
}

// Parse FEN string to board state
function parseFen(fen: string): { board: PieceType[][], side: Side } {
  const board = createEmptyBoard();
  const parts = fen.split(' ');
  const position = parts[0];
  const side = parts[1] === 'b' ? BLACK : RED;

  let file = 0;
  let rank = 9; // Start from rank 9 (top)

  for (const c of position) {
    if (c === '/') {
      file = 0;
      rank--;
    } else if (c >= '1' && c <= '9') {
      file += parseInt(c, 10);
    } else {
      const piece = charToPiece(c);
      if (piece !== EMPTY && file < 9 && rank >= 0) {
        board[file][rank] = piece;
        file++;
      }
    }
  }

  return { board, side };
}

// Initial game state
function createInitialState(): GameState {
  const { board, side } = parseFen(START_FEN);
  return {
    board,
    sideToMove: side,
    moveHistory: [],
    result: 'in_progress',
    fen: START_FEN,
  };
}

// Simple move validation (basic rules, server is authoritative)
function isValidMove(
  board: PieceType[][],
  from: Position,
  to: Position,
  sideToMove: Side
): boolean {
  const piece = board[from.file][from.rank];

  // Must have a piece
  if (piece === EMPTY) return false;

  // Must be the correct side's piece
  const pieceColor = getPieceColor(piece);
  if (pieceColor !== sideToMove) return false;

  // Can't capture own piece
  const targetPiece = board[to.file][to.rank];
  if (targetPiece !== EMPTY && getPieceColor(targetPiece) === sideToMove) {
    return false;
  }

  // Bounds check
  if (to.file < 0 || to.file > 8 || to.rank < 0 || to.rank > 9) {
    return false;
  }

  return true;
}

export function useGameState() {
  const [gameState, setGameState] = useState<GameState>(createInitialState);

  const applyMove = useCallback((fromStr: string, toStr: string): boolean => {
    const from = notationToPosition(fromStr);
    const to = notationToPosition(toStr);

    if (!from || !to) return false;

    let success = false;

    setGameState(prev => {
      // Basic validation
      if (!isValidMove(prev.board, from, to, prev.sideToMove)) {
        return prev;
      }

      const piece = prev.board[from.file][from.rank];
      const captured = prev.board[to.file][to.rank];

      // Create new board
      const newBoard = prev.board.map(file => [...file]);
      newBoard[to.file][to.rank] = piece;
      newBoard[from.file][from.rank] = EMPTY;

      // Record move
      const moveRecord: MoveRecord = {
        from: fromStr,
        to: toStr,
        piece,
        captured: captured !== EMPTY ? captured : undefined,
      };

      success = true;

      return {
        ...prev,
        board: newBoard,
        sideToMove: prev.sideToMove === RED ? BLACK : RED,
        moveHistory: [...prev.moveHistory, moveRecord],
        lastMove: { from, to },
        fen: prev.fen, // Could probably update FEN generator, but just keeping old fen for now unless from server
      };
    });

    return success;
  }, []);

  const resetGame = useCallback(() => {
    setGameState(createInitialState());
  }, []);

  const setGameStateFromFen = useCallback((fen: string) => {
    const { board, side } = parseFen(fen);
    setGameState(prev => ({
      ...prev,
      board,
      sideToMove: side,
      fen,
    }));
  }, []);

  const setResult = useCallback((result: GameState['result']) => {
    setGameState(prev => ({ ...prev, result }));
  }, []);

  const undoMove = useCallback(() => {
    setGameState(prev => {
      if (prev.moveHistory.length === 0) return prev;

      // This is a simplified undo - in production, would need full state restoration
      // For now, just reset to start position if history exists
      return createInitialState();
    });
  }, []);

  // Push a move record from an externally applied move (e.g., AI move via FEN update)
  const pushMoveRecord = useCallback((fromStr: string, toStr: string) => {
    const from = notationToPosition(fromStr);
    const to = notationToPosition(toStr);
    if (!from || !to) return;

    setGameState(prev => {
      // The board has already been updated via setGameStateFromFen,
      // so the piece that moved is now at the target square.
      const piece = prev.board[to.file][to.rank];
      if (piece === EMPTY) return prev;

      const moveRecord: MoveRecord = {
        from: fromStr,
        to: toStr,
        piece,
        captured: undefined, // Capture info not easily available after FEN update
      };

      return {
        ...prev,
        moveHistory: [...prev.moveHistory, moveRecord],
        lastMove: { from, to },
      };
    });
  }, []);

  return {
    gameState,
    applyMove,
    resetGame,
    setGameStateFromFen,
    undoMove,
    pushMoveRecord,
    setResult,
  };
}
