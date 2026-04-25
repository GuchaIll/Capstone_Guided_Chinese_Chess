import { describe, expect, it } from "vitest";

import { deriveMoveFromFenDiff, fenPlacementsEqual } from "./fenMoveDiff";

describe("fenMoveDiff", () => {
  it("derives a red quiet move", () => {
    const before = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1";
    const after = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/P8/2P1P1P1P/1C5C1/9/RNBAKABNR b - - 0 1";

    expect(deriveMoveFromFenDiff(before, after)).toEqual({
      from: "a3",
      to: "a4",
      move: "a3a4",
      piece: "P",
      captured: null,
    });
  });

  it("derives a black capture", () => {
    const before = "4k4/9/9/9/4p4/4P4/9/9/9/4K4 b - - 0 1";
    const after = "4k4/9/9/9/9/4p4/9/9/9/4K4 w - - 0 2";

    expect(deriveMoveFromFenDiff(before, after)).toEqual({
      from: "e5",
      to: "e4",
      move: "e5e4",
      piece: "p",
      captured: "P",
    });
  });

  it("ignores side-token differences when comparing placements", () => {
    const left = "4k4/9/9/9/4p4/9/9/9/9/4K4 w - - 0 1";
    const right = "4k4/9/9/9/4p4/9/9/9/9/4K4 b - - 0 99";

    expect(fenPlacementsEqual(left, right)).toBe(true);
  });

  it("rejects unchanged boards", () => {
    const fen = "4k4/9/9/9/4p4/9/9/9/9/4K4 w - - 0 1";
    expect(() => deriveMoveFromFenDiff(fen, fen)).toThrow("No physical-board change detected.");
  });

  it("rejects multi-square edits that are not a single move", () => {
    const before = "4k4/9/9/9/4p4/9/9/9/9/4K4 w - - 0 1";
    const after = "4k4/9/9/9/4p4/4P4/9/9/9/4K4 b - - 0 2";

    expect(() => deriveMoveFromFenDiff(before, after)).toThrow(
      "Expected exactly 2 changed squares, found 1.",
    );
  });
});
