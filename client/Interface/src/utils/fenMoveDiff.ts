export interface DerivedFenMove {
  from: string;
  to: string;
  move: string;
  piece: string;
  captured: string | null;
}

type FenBoard = (string | null)[][];

interface SquareDelta {
  square: string;
  before: string | null;
  after: string | null;
}

function fileToLetter(file: number): string {
  return String.fromCharCode("a".charCodeAt(0) + file);
}

function parseFenBoard(fen: string): FenBoard | null {
  const [placement] = fen.trim().split(/\s+/);
  const ranks = placement?.split("/") ?? [];
  if (ranks.length !== 10) return null;

  const board: FenBoard = Array.from({ length: 9 }, () => Array(10).fill(null));

  for (let rankIndex = 0; rankIndex < ranks.length; rankIndex += 1) {
    const rankText = ranks[rankIndex];
    const rank = 9 - rankIndex;
    let file = 0;

    for (const char of rankText) {
      if (/[1-9]/.test(char)) {
        file += Number(char);
        continue;
      }

      if (file > 8) return null;
      board[file][rank] = char;
      file += 1;
    }

    if (file !== 9) return null;
  }

  return board;
}

function piecePlacement(fen: string): string {
  return fen.trim().split(/\s+/)[0] ?? "";
}

function isMovingSidePiece(piece: string, sideToken: string): boolean {
  if (!piece) return false;
  return sideToken === "w" ? piece === piece.toUpperCase() : piece === piece.toLowerCase();
}

export function fenPlacementsEqual(leftFen: string, rightFen: string): boolean {
  return piecePlacement(leftFen) === piecePlacement(rightFen);
}

export function deriveMoveFromFenDiff(beforeFen: string, afterFen: string): DerivedFenMove {
  const beforeBoard = parseFenBoard(beforeFen);
  const afterBoard = parseFenBoard(afterFen);
  if (!beforeBoard || !afterBoard) {
    throw new Error("Invalid FEN supplied for board-diff validation.");
  }

  const sideToken = beforeFen.trim().split(/\s+/)[1]?.toLowerCase();
  if (sideToken !== "w" && sideToken !== "b") {
    throw new Error("Unable to determine side to move from FEN.");
  }

  const deltas: SquareDelta[] = [];
  for (let file = 0; file < 9; file += 1) {
    for (let rank = 0; rank < 10; rank += 1) {
      const before = beforeBoard[file][rank];
      const after = afterBoard[file][rank];
      if (before === after) continue;
      deltas.push({
        square: `${fileToLetter(file)}${rank}`,
        before,
        after,
      });
    }
  }

  if (deltas.length === 0) {
    throw new Error("No physical-board change detected.");
  }

  if (deltas.length !== 2) {
    throw new Error(`Expected exactly 2 changed squares, found ${deltas.length}.`);
  }

  const fromDelta = deltas.find(
    (delta) =>
      delta.before !== null &&
      isMovingSidePiece(delta.before, sideToken) &&
      delta.after === null,
  );
  const toDelta = deltas.find(
    (delta) =>
      delta.after !== null &&
      isMovingSidePiece(delta.after, sideToken) &&
      delta.after !== delta.before,
  );

  if (!fromDelta || !toDelta) {
    throw new Error("Could not isolate a single move by the side to move.");
  }

  if (toDelta.after !== fromDelta.before) {
    throw new Error("Detected board change does not preserve the moving piece.");
  }

  if (toDelta.before && isMovingSidePiece(toDelta.before, sideToken)) {
    throw new Error("Detected move appears to capture a piece of the moving side.");
  }

  return {
    from: fromDelta.square,
    to: toDelta.square,
    move: `${fromDelta.square}${toDelta.square}`,
    piece: fromDelta.before!,
    captured: toDelta.before,
  };
}
