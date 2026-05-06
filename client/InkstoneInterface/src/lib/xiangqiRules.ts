// Xiangqi legal-move validation

type PieceType = 'king' | 'advisor' | 'elephant' | 'horse' | 'rook' | 'cannon' | 'pawn';
type PieceColor = 'red' | 'black';

export interface Piece {
  type: PieceType;
  color: PieceColor;
}

export type Board = (Piece | null)[][];

const inBounds = (r: number, c: number) => r >= 0 && r <= 9 && c >= 0 && c <= 8;

const inPalace = (r: number, c: number, color: PieceColor) => {
  if (c < 3 || c > 5) return false;
  return color === 'red' ? r >= 7 && r <= 9 : r >= 0 && r <= 2;
};

const ownHalf = (r: number, color: PieceColor) =>
  color === 'red' ? r >= 5 : r <= 4;

export const getLegalMoves = (
  board: Board,
  row: number,
  col: number,
): [number, number][] => {
  const piece = board[row][col];
  if (!piece) return [];
  const moves: [number, number][] = [];
  const { type, color } = piece;
  const enemy = color === 'red' ? 'black' : 'red';

  const canMove = (r: number, c: number) => {
    if (!inBounds(r, c)) return false;
    const target = board[r][c];
    return !target || target.color === enemy;
  };

  switch (type) {
    case 'king': {
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nr = row + dr;
        const nc = col + dc;
        if (inPalace(nr, nc, color) && canMove(nr, nc)) moves.push([nr, nc]);
      }
      const dir = color === 'red' ? -1 : 1;
      let r = row + dir;
      while (inBounds(r, col)) {
        if (board[r][col]) {
          if (board[r][col]!.type === 'king') moves.push([r, col]);
          break;
        }
        r += dir;
      }
      break;
    }
    case 'advisor': {
      for (const [dr, dc] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        const nr = row + dr;
        const nc = col + dc;
        if (inPalace(nr, nc, color) && canMove(nr, nc)) moves.push([nr, nc]);
      }
      break;
    }
    case 'elephant': {
      for (const [dr, dc] of [[2, 2], [2, -2], [-2, 2], [-2, -2]]) {
        const nr = row + dr;
        const nc = col + dc;
        const br = row + dr / 2;
        const bc = col + dc / 2;
        if (inBounds(nr, nc) && ownHalf(nr, color) && !board[br][bc] && canMove(nr, nc)) {
          moves.push([nr, nc]);
        }
      }
      break;
    }
    case 'horse': {
      const legs: [number, number, number, number][] = [
        [-2, -1, -1, 0], [-2, 1, -1, 0],
        [2, -1, 1, 0], [2, 1, 1, 0],
        [-1, -2, 0, -1], [-1, 2, 0, 1],
        [1, -2, 0, -1], [1, 2, 0, 1],
      ];
      for (const [dr, dc, br, bc] of legs) {
        const nr = row + dr;
        const nc = col + dc;
        if (inBounds(nr, nc) && !board[row + br][col + bc] && canMove(nr, nc)) {
          moves.push([nr, nc]);
        }
      }
      break;
    }
    case 'rook': {
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        let r = row + dr;
        let c = col + dc;
        while (inBounds(r, c)) {
          if (board[r][c]) {
            if (board[r][c]!.color === enemy) moves.push([r, c]);
            break;
          }
          moves.push([r, c]);
          r += dr;
          c += dc;
        }
      }
      break;
    }
    case 'cannon': {
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        let r = row + dr;
        let c = col + dc;
        let jumped = false;
        while (inBounds(r, c)) {
          if (board[r][c]) {
            if (jumped) {
              if (board[r][c]!.color === enemy) moves.push([r, c]);
              break;
            }
            jumped = true;
          } else if (!jumped) {
            moves.push([r, c]);
          }
          r += dr;
          c += dc;
        }
      }
      break;
    }
    case 'pawn': {
      const forward = color === 'red' ? -1 : 1;
      const nr = row + forward;
      if (inBounds(nr, col) && canMove(nr, col)) moves.push([nr, col]);
      if (!ownHalf(row, color)) {
        for (const dc of [-1, 1]) {
          if (inBounds(row, col + dc) && canMove(row, col + dc)) {
            moves.push([row, col + dc]);
          }
        }
      }
      break;
    }
  }

  return moves;
};

export const getHintMove = (
  board: Board,
  turn: PieceColor,
): { from: [number, number]; to: [number, number] } | null => {
  const pieceValue: Record<PieceType, number> = {
    king: 1000, rook: 9, cannon: 5, horse: 4, elephant: 2, advisor: 2, pawn: 1,
  };

  let bestFrom: [number, number] | null = null;
  let bestTo: [number, number] | null = null;
  let bestScore = -1;

  for (let r = 0; r < 10; r += 1) {
    for (let c = 0; c < 9; c += 1) {
      const p = board[r][c];
      if (!p || p.color !== turn) continue;
      const moves = getLegalMoves(board, r, c);
      for (const [tr, tc] of moves) {
        const target = board[tr][tc];
        const score = target ? pieceValue[target.type] : 0;
        if (score > bestScore) {
          bestScore = score;
          bestFrom = [r, c];
          bestTo = [tr, tc];
        }
      }
    }
  }

  if (bestScore === 0) {
    const allMoves: { from: [number, number]; to: [number, number] }[] = [];
    for (let r = 0; r < 10; r += 1) {
      for (let c = 0; c < 9; c += 1) {
        const p = board[r][c];
        if (!p || p.color !== turn) continue;
        const moves = getLegalMoves(board, r, c);
        for (const m of moves) allMoves.push({ from: [r, c], to: m });
      }
    }
    if (allMoves.length === 0) return null;
    return allMoves[Math.floor(Math.random() * allMoves.length)];
  }

  if (!bestFrom || !bestTo) return null;
  return { from: bestFrom, to: bestTo };
};
