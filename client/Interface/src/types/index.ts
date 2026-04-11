// Piece types matching the Rust engine
export const EMPTY = 0;
export const RED_PAWN = 1;
export const RED_ADVISOR = 2;
export const RED_ELEPHANT = 3;
export const RED_KNIGHT = 4;
export const RED_CANNON = 5;
export const RED_ROOK = 6;
export const RED_KING = 7;
export const BLACK_PAWN = 8;
export const BLACK_ADVISOR = 9;
export const BLACK_ELEPHANT = 10;
export const BLACK_KNIGHT = 11;
export const BLACK_CANNON = 12;
export const BLACK_ROOK = 13;
export const BLACK_KING = 14;
export const OFFBOARD = 15;

// Sides
export const RED = 0;
export const BLACK = 1;

export type PieceType = number;
export type Side = typeof RED | typeof BLACK;

export interface Position {
  file: number; // 0-8 (a-i)
  rank: number; // 0-9
}

export interface MoveRecord {
  from: string;
  to: string;
  piece: PieceType;
  captured?: PieceType;
}

export type GameResult = 'in_progress' | 'red_wins' | 'black_wins' | 'draw';

export interface SuggestedMove {
  from: string; // e.g., "e0"
  to: string;   // e.g., "e1"
  score: number;
}

export interface GameState {
  board: PieceType[][]; // 9 files x 10 ranks
  sideToMove: Side;
  moveHistory: MoveRecord[];
  lastMove?: { from: Position; to: Position };
  result: GameResult;
  fen: string;
}

// Piece display information
export interface PieceInfo {
  char: string;        // Chinese character
  name: string;        // English name
  color: 'red' | 'black';
}

// Map piece codes to display info
export const PIECE_INFO: Record<number, PieceInfo> = {
  [RED_PAWN]: { char: '兵', name: 'Soldier', color: 'red' },
  [RED_ADVISOR]: { char: '仕', name: 'Advisor', color: 'red' },
  [RED_ELEPHANT]: { char: '相', name: 'Elephant', color: 'red' },
  [RED_KNIGHT]: { char: '傌', name: 'Horse', color: 'red' },
  [RED_CANNON]: { char: '炮', name: 'Cannon', color: 'red' },
  [RED_ROOK]: { char: '俥', name: 'Chariot', color: 'red' },
  [RED_KING]: { char: '帥', name: 'General', color: 'red' },
  [BLACK_PAWN]: { char: '卒', name: 'Soldier', color: 'black' },
  [BLACK_ADVISOR]: { char: '士', name: 'Advisor', color: 'black' },
  [BLACK_ELEPHANT]: { char: '象', name: 'Elephant', color: 'black' },
  [BLACK_KNIGHT]: { char: '馬', name: 'Horse', color: 'black' },
  [BLACK_CANNON]: { char: '砲', name: 'Cannon', color: 'black' },
  [BLACK_ROOK]: { char: '車', name: 'Chariot', color: 'black' },
  [BLACK_KING]: { char: '將', name: 'General', color: 'black' },
};

// Convert file index (0-8) to letter (a-i)
export function fileToLetter(file: number): string {
  return String.fromCharCode('a'.charCodeAt(0) + file);
}

// Convert letter (a-i) to file index (0-8)
export function letterToFile(letter: string): number {
  return letter.charCodeAt(0) - 'a'.charCodeAt(0);
}

// Convert position to algebraic notation (e.g., "e4")
export function positionToNotation(pos: Position): string {
  return `${fileToLetter(pos.file)}${pos.rank}`;
}

// Convert algebraic notation to position
export function notationToPosition(notation: string): Position | null {
  if (notation.length !== 2) return null;
  const file = letterToFile(notation[0]);
  const rank = parseInt(notation[1], 10);
  if (file < 0 || file > 8 || rank < 0 || rank > 9) return null;
  return { file, rank };
}

// Get piece color from piece type
export function getPieceColor(piece: PieceType): Side | null {
  if (piece >= RED_PAWN && piece <= RED_KING) return RED;
  if (piece >= BLACK_PAWN && piece <= BLACK_KING) return BLACK;
  return null;
}

// Starting position FEN
export const START_FEN = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1';
