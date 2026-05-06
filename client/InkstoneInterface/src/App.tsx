'use client';

import { useState, useCallback, useEffect, useRef, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import fishermanBg from "./assets/fisherman-bg.jpg";
import brushStroke from "./assets/brush-stroke.png";
import captureCircleImg from "./assets/capture-circle.png";
import sootBrushImg from "./assets/soot-brush.png";
import captureStrikeImg from "./assets/capture-strike.png";
import pieceKingImg from "./assets/piece-king.png";
import pieceAdvisorImg from "./assets/piece-advisor.png";
import pieceElephantImg from "./assets/piece-elephant.png";
import pieceHorseImg from "./assets/piece-horse.png";
import pieceRookImg from "./assets/piece-rook.png";
import pieceCannonImg from "./assets/piece-cannon.png";
import piecePawnImg from "./assets/piece-pawn.png";
import { useInkSounds } from "./hooks/useInkSounds";
import { useInkstoneEngineGame } from "./hooks/useInkstoneEngineGame";
import { useGuidance, useStructuredGuidance } from "./hooks/useGuidance";
import { GameOverModal } from "./components/inkstone/GameOverModal";
import { Typewriter } from "./components/inkstone/Typewriter";
import { type Piece } from "./lib/xiangqiRules";
import { START_FEN } from "./types";
import { deriveGamePhaseFromFen, squareToCoords } from "./utils/engineBoardAdapter";

const toRoman = (n: number): string => {
  if (n <= 0) return "";
  const vals = [10,9,5,4,1];
  const syms = ["X","IX","V","IV","I"];
  let result = "";
  for (let i = 0; i < vals.length; i++) {
    while (n >= vals[i]) { result += syms[i]; n -= vals[i]; }
  }
  return result;
};

type PieceType = "king" | "advisor" | "elephant" | "horse" | "rook" | "cannon" | "pawn";
type PieceColor = "red" | "black";

const PIECE_RULES: { type: PieceType; name: string; nameZh: string; image: string; description: string }[] = [
  { type: "king", name: "General", nameZh: "帥/將", image: pieceKingImg.src, description: "Moves one step orthogonally (up, down, left, right). Confined to the 3×3 palace. Cannot face the opposing General on the same column with no pieces in between (\"Flying General\" rule)." },
  { type: "advisor", name: "Advisor", nameZh: "仕/士", image: pieceAdvisorImg.src, description: "Moves one step diagonally. Confined to the 3×3 palace. Protects the General and controls the center of the palace." },
  { type: "elephant", name: "Elephant", nameZh: "相/象", image: pieceElephantImg.src, description: "Moves exactly two steps diagonally (forming a \"田\" shape). Cannot jump over a blocking piece at the midpoint. Cannot cross the river — stays on its own half of the board." },
  { type: "horse", name: "Horse", nameZh: "馬", image: pieceHorseImg.src, description: "Moves one step orthogonally then one step diagonally outward (an \"L\" shape like chess). Can be blocked by a piece adjacent in the orthogonal direction (\"hobbling the horse's leg\")." },
  { type: "rook", name: "Chariot", nameZh: "車", image: pieceRookImg.src, description: "Moves any number of steps orthogonally (like a chess Rook). The most powerful piece — it cannot jump over other pieces." },
  { type: "cannon", name: "Cannon", nameZh: "砲/炮", image: pieceCannonImg.src, description: "Moves any number of steps orthogonally like the Chariot, but captures by jumping over exactly one piece (the \"screen\") to land on an enemy beyond it." },
  { type: "pawn", name: "Soldier", nameZh: "兵/卒", image: piecePawnImg.src, description: "Moves one step forward only. After crossing the river, it may also move one step sideways (left or right) but never backward." },
];

// Preload & decode all rule images at module level
const imageDecodeCache = new Map<string, Promise<void>>();
function preloadAndDecodeImage(url: string) {
  if (!imageDecodeCache.has(url)) {
    const img = new Image();
    img.src = url;
    const p = img.decode().catch(() => {});
    imageDecodeCache.set(url, p);
  }
  return imageDecodeCache.get(url)!;
}
PIECE_RULES.forEach(r => preloadAndDecodeImage(r.image));

const PIECE_CHARS: Record<PieceColor, Record<PieceType, string>> = {
  red: { king: "帥", advisor: "仕", elephant: "相", horse: "馬", rook: "車", cannon: "砲", pawn: "兵" },
  black: { king: "將", advisor: "士", elephant: "象", horse: "馬", rook: "車", cannon: "炮", pawn: "卒" },
};

const generateBlobPath = (seed: number): string => {
  const points: string[] = [];
  const steps = 12;
  for (let i = 0; i < steps; i++) {
    const angle = (i / steps) * Math.PI * 2;
    const wobble = 3 + Math.sin(seed * 7.3 + i * 2.1) * 4 + Math.cos(seed * 3.7 + i * 1.3) * 3;
    const r = 50 - wobble;
    const x = 50 + r * Math.cos(angle);
    const y = 50 + r * Math.sin(angle);
    points.push(`${x}% ${y}%`);
  }
  return `polygon(${points.join(", ")})`;
};

const brushLine = (x1: number, y1: number, x2: number, y2: number, seed: number) => {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  const steps = Math.max(4, Math.floor(len / 30));
  const points: string[] = [`M ${x1} ${y1}`];
  for (let i = 1; i < steps; i++) {
    const t = i / steps;
    const wobbleX = Math.sin(seed + i * 2.7) * 1.2;
    const wobbleY = Math.cos(seed + i * 3.1) * 1.2;
    points.push(`L ${x1 + dx * t + wobbleX} ${y1 + dy * t + wobbleY}`);
  }
  points.push(`L ${x2} ${y2}`);
  return points.join(" ");
};

interface CaptureAnim {
  x: number;
  y: number;
  key: number;
}

const T = {
  zh: {
    back: "← 返回", title: "象棋", hint: "提示", rules: "棋规", guidance: "导引", newGame: "新局",
    blackTurn: "黑方执棋", redTurn: "红方执棋", river: "楚河　　漢界",
    redCaptures: "红方所获", blackCaptures: "黑方所获",
    selectPieceRule: "选择棋子查看规则", selectPieceRuleSub: "Select a piece to view its rules",
    guidanceTitle: "棋局导引", guidanceSub: "AI-generated guidance (placeholder)",
    redWins: "红方胜", blackWins: "黑方胜", draw: "和局",
    lang: "EN",
  },
  en: {
    back: "← Back", title: "Xiangqi", hint: "Hint", rules: "Rules", guidance: "Guide", newGame: "New",
    blackTurn: "Black's Turn", redTurn: "Red's Turn", river: "River",
    redCaptures: "Red Captures", blackCaptures: "Black Captures",
    selectPieceRule: "Select a piece to view its rules", selectPieceRuleSub: "",
    guidanceTitle: "Game Guidance", guidanceSub: "AI-generated guidance (placeholder)",
    redWins: "Red Wins", blackWins: "Black Wins", draw: "Draw",
    lang: "中",
  },
};

const PHASE_LABELS: Record<'zh' | 'en', Record<'opening' | 'middlegame' | 'endgame', string>> = {
  zh: {
    opening: '开局',
    middlegame: '中盘',
    endgame: '残局',
  },
  en: {
    opening: 'Opening',
    middlegame: 'Middlegame',
    endgame: 'Endgame',
  },
};

function formatPhaseLabel(phase: string | undefined, lang: 'zh' | 'en') {
  if (!phase) return '';
  const normalized = phase.trim().toLowerCase();
  if (normalized === 'opening' || normalized === 'middlegame' || normalized === 'endgame') {
    return PHASE_LABELS[lang][normalized];
  }
  return phase;
}

function formatBoardMove(move: string) {
  if (!/^[a-i][0-9][a-i][0-9]$/i.test(move)) return move;
  return `${move.slice(0, 2)}→${move.slice(2, 4)}`;
}

function pieceDisplayName(piece: Piece | null | undefined, lang: 'zh' | 'en') {
  if (!piece) return '';
  if (lang === 'zh') {
    return `${piece.color === 'red' ? '红' : '黑'}${PIECE_CHARS[piece.color][piece.type]}`;
  }
  const rule = PIECE_RULES.find((entry) => entry.type === piece.type);
  return `${piece.color === 'red' ? 'Red' : 'Black'} ${rule?.name ?? piece.type}`;
}

function describeMoveWithPiece(board: (Piece | null)[][], move: string, lang: 'zh' | 'en') {
  if (!/^[a-i][0-9][a-i][0-9]$/i.test(move)) return move;
  const fromSquare = move.slice(0, 2);
  const file = fromSquare.charCodeAt(0) - 'a'.charCodeAt(0);
  const rank = Number.parseInt(fromSquare[1], 10);
  const row = 9 - rank;
  const piece = board[row]?.[file] ?? null;
  const moveText = formatBoardMove(move);
  const pieceText = pieceDisplayName(piece, lang);
  return pieceText ? `${pieceText} ${moveText}` : moveText;
}

function rewriteCoachSummary(summary: string, board: (Piece | null)[][], lang: 'zh' | 'en') {
  return summary.replace(/\b[a-i][0-9][a-i][0-9]\b/gi, (match) => describeMoveWithPiece(board, match, lang));
}

// --- Move trail particle types ---
type MoveTrailParticle = {
  id: number;
  x: number;
  y: number;
  size: number;
  opacity: number;
  rotation: number;
  elongation: number; // 1 = round, >1 = pressed/elongated
  delay: number;
};

type MoveAnim = {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  piece: Piece;
  key: number;
  particles: MoveTrailParticle[];
  duration: number; // animation duration based on speed
};

// Drag trail point recorded while dragging
type DragTrailPoint = {
  x: number;
  y: number;
  time: number;
  id: number;
};

type DragState = {
  row: number;
  col: number;
  piece: Piece;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  trail: DragTrailPoint[];
  lastTrailTime: number;
  isDragging: boolean; // false = pending, true = committed to drag
};

function generateTrailParticles(
  fromX: number, fromY: number, toX: number, toY: number, speedFactor: number = 1
): MoveTrailParticle[] {
  const dx = toX - fromX;
  const dy = toY - fromY;
  const dist = Math.sqrt(dx * dx + dy * dy);
  // More particles for faster/longer moves
  const densityMult = Math.max(0.6, Math.min(2, speedFactor));
  const count = Math.max(6, Math.min(20, Math.floor(dist / (22 / densityMult))));
  const angle = Math.atan2(dy, dx);
  const particles: MoveTrailParticle[] = [];
  for (let i = 0; i < count; i++) {
    const t = (i + 0.5) / count;
    const jitterMag = 4 + Math.random() * 8;
    const jitterAngle = angle + Math.PI / 2;
    const jx = Math.cos(jitterAngle) * jitterMag * (Math.random() > 0.5 ? 1 : -1);
    const jy = Math.sin(jitterAngle) * jitterMag * (Math.random() > 0.5 ? 1 : -1);
    // Faster = more broken/smaller, slower = pooled/larger
    const isFast = speedFactor > 1;
    const baseSize = isFast ? 8 + Math.random() * 10 : 12 + Math.random() * 14;
    particles.push({
      id: i,
      x: fromX + dx * t + jx,
      y: fromY + dy * t + jy,
      size: baseSize,
      opacity: isFast ? 0.1 + Math.random() * 0.2 : 0.2 + Math.random() * 0.3,
      rotation: Math.random() * 360,
      elongation: isFast ? 1.5 + Math.random() * 1.5 : 1 + Math.random() * 0.5,
      delay: t * 0.15,
    });
  }
  return particles;
}

const XiangqiGame = () => {
  const router = useRouter();
  const { playBrush, playWhoosh, playInkTick, playInkHum, playDryBrush } = useInkSounds();
  const {
    board,
    fen,
    turn,
    result,
    selected,
    legalMoves,
    captured,
    lastMoveEvent,
    hintMove,
    error,
    selectSquare,
    deselectSquare,
    moveSelectedPiece,
    requestHint,
    dismissHint,
    resetGame,
  } = useInkstoneEngineGame();
  const [hoveredPiece, setHoveredPiece] = useState<string | null>(null);
  const [hoverKey, setHoverKey] = useState(0);
  const [transitioning, setTransitioning] = useState(false);
  const [captureAnim, setCaptureAnim] = useState<CaptureAnim | null>(null);
  const [showRules, setShowRules] = useState(false);
  const [ruleImageReady, setRuleImageReady] = useState(false);
  const [showGuidance, setShowGuidance] = useState(false);
  const [guidanceHighlights, setGuidanceHighlights] = useState<[number, number][]>([]);
  const { guidance: coachGuidance, loading: coachGuidanceLoading, error: coachGuidanceError } = useGuidance(fen, showGuidance);
  const { guidance: structuredGuidance, loading: structuredGuidanceLoading } = useStructuredGuidance(fen, showGuidance);
  const [capturedAnimKey, setCapturedAnimKey] = useState(0);
  const [lang, setLang] = useState<"zh" | "en">("zh");
  const [moveAnim, setMoveAnim] = useState<MoveAnim | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const dragIdCounter = useRef(0);
  const boardRef = useRef<HTMLDivElement>(null);
  const clickSuppressed = useRef(false);
  const t = T[lang];

  useEffect(() => {
    if (!hintMove) return;
    const t = setTimeout(() => dismissHint(), 3000);
    return () => clearTimeout(t);
  }, [hintMove, dismissHint]);

  useEffect(() => {
    if (!moveAnim) return;
    const t = setTimeout(() => setMoveAnim(null), moveAnim.duration + 100);
    return () => clearTimeout(t);
  }, [moveAnim]);

  useEffect(() => {
    if (!captureAnim) return;
    const t = setTimeout(() => setCaptureAnim(null), 1200);
    return () => clearTimeout(t);
  }, [captureAnim]);

  const isLegalTarget = useCallback(
    (r: number, c: number) => legalMoves.some(([mr, mc]) => mr === r && mc === c),
    [legalMoves]
  );

  const handleBack = () => {
    setTransitioning(true);
    setTimeout(() => router.push("/"), 500);
  };

  const handleReset = () => {
    resetGame();
    dismissHint();
    setCaptureAnim(null);
  };

  const handleHint = () => {
    if (requestHint()) playBrush();
  };

  const handleCellClick = useCallback((row: number, col: number) => {
    if (result !== "in_progress") return;
    const piece = board[row][col];
    if (selected) {
      const [sr, sc] = selected;
      const selectedPiece = board[sr][sc];
      if (sr === row && sc === col) { deselectSquare(); return; }
      if (piece && piece.color === turn) { selectSquare(row, col); return; }

      if (selectedPiece && isLegalTarget(row, col)) {
        if (moveSelectedPiece(row, col)) {
          dismissHint();
        }
      }
    } else {
      if (piece && piece.color === turn) {
        if (selectSquare(row, col)) {
          playInkTick();
          setTimeout(() => playInkHum(), 60);
        }
      }
    }
  }, [
    board,
    selected,
    turn,
    result,
    isLegalTarget,
    deselectSquare,
    selectSquare,
    moveSelectedPiece,
    playInkTick,
    playInkHum,
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

  // --- Drag handlers ---
  const getBoardLocalCoords = useCallback((clientX: number, clientY: number) => {
    const boardEl = boardRef.current;
    if (!boardEl) return null;
    const rect = boardEl.getBoundingClientRect();
    const scaleX = fullW / rect.width;
    const scaleY = fullH / rect.height;
    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY,
    };
  }, [fullW, fullH]);

  const handleDragStart = useCallback((row: number, col: number, clientX: number, clientY: number) => {
    const piece = board[row][col];
    if (!piece || piece.color !== turn || result !== "in_progress") return;
    // Select immediately — this shows the selection animation + legal moves
    clickSuppressed.current = true;
    if (selectSquare(row, col)) {
      playInkTick();
      setTimeout(() => playInkHum(), 60);
    }

    const coords = getBoardLocalCoords(clientX, clientY);
    if (!coords) return;

    setDragState({
      row, col, piece,
      startX: coords.x, startY: coords.y,
      currentX: coords.x, currentY: coords.y,
      trail: [],
      lastTrailTime: Date.now(),
      isDragging: false,
    });
  }, [board, turn, result, playInkTick, playInkHum, getBoardLocalCoords, selectSquare]);

  const DRAG_THRESHOLD = 12; // px before committing to drag mode

  const handleDragMove = useCallback((clientX: number, clientY: number) => {
    if (!dragState) return;
    const coords = getBoardLocalCoords(clientX, clientY);
    if (!coords) return;
    const now = Date.now();

    setDragState(prev => {
      if (!prev) return null;
      // Check if we've exceeded the drag threshold
      const distFromStart = Math.sqrt((coords.x - prev.startX) ** 2 + (coords.y - prev.startY) ** 2);
      const nowDragging = prev.isDragging || distFromStart > DRAG_THRESHOLD;

      if (!nowDragging) {
        // Still below threshold — just update position, don't generate trail
        return { ...prev, currentX: coords.x, currentY: coords.y };
      }

      const dx = coords.x - prev.currentX;
      const dy = coords.y - prev.currentY;
      const moveDist = Math.sqrt(dx * dx + dy * dy);
      const timeDelta = now - prev.lastTrailTime;
      const shouldAddPoint = moveDist > 8 && timeDelta > 16;
      const newTrail = shouldAddPoint
        ? [...prev.trail, { x: coords.x, y: coords.y, time: now, id: dragIdCounter.current++ }]
        : prev.trail;
      const trimmedTrail = newTrail.length > 40 ? newTrail.slice(-40) : newTrail;
      return {
        ...prev,
        currentX: coords.x,
        currentY: coords.y,
        trail: trimmedTrail,
        lastTrailTime: shouldAddPoint ? now : prev.lastTrailTime,
        isDragging: true,
      };
    });
  }, [dragState, getBoardLocalCoords]);

  const handleDragEnd = useCallback((clientX: number, clientY: number) => {
    if (!dragState) return;
    
    // If we never actually dragged, just clear drag state — selection is already set
    if (!dragState.isDragging) {
      setDragState(null);
      return;
    }

    const coords = getBoardLocalCoords(clientX, clientY);
    if (!coords) { setDragState(null); return; }

    const col = Math.round((coords.x - boardPad - margin) / BASE_CELL);
    const row = Math.round((coords.y - boardPad - margin) / BASE_CELL);

    if (row >= 0 && row <= 9 && col >= 0 && col <= 8 && !(row === dragState.row && col === dragState.col)) {
      handleCellClick(row, col);
    }
    setDragState(null);
  }, [dragState, handleCellClick, getBoardLocalCoords, boardPad, margin, BASE_CELL]);

  useEffect(() => {
    if (!dragState) return;
    const onMouseMove = (e: MouseEvent) => handleDragMove(e.clientX, e.clientY);
    const onMouseUp = (e: MouseEvent) => handleDragEnd(e.clientX, e.clientY);
    const onTouchMove = (e: TouchEvent) => { e.preventDefault(); handleDragMove(e.touches[0].clientX, e.touches[0].clientY); };
    const onTouchEnd = (e: TouchEvent) => { handleDragEnd(e.changedTouches[0].clientX, e.changedTouches[0].clientY); };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
    };
  }, [dragState, handleDragMove, handleDragEnd]);

  useEffect(() => {
    if (!lastMoveEvent) return;

    const [[fromRow, fromCol], [toRow, toCol]] = [lastMoveEvent.from, lastMoveEvent.to];
    const fromX = boardPad + margin + fromCol * BASE_CELL;
    const fromY = boardPad + margin + fromRow * BASE_CELL;
    const toX = boardPad + margin + toCol * BASE_CELL;
    const toY = boardPad + margin + toRow * BASE_CELL;
    const dist = Math.sqrt((toX - fromX) ** 2 + (toY - fromY) ** 2);
    const speedFactor = Math.max(0.5, Math.min(2.5, dist / 120));
    const animDuration = Math.max(400, Math.min(900, 300 + dist * 2));

    if (lastMoveEvent.movedPiece) {
      setMoveAnim({
        fromX,
        fromY,
        toX,
        toY,
        piece: lastMoveEvent.movedPiece,
        key: lastMoveEvent.key,
        particles: generateTrailParticles(fromX, fromY, toX, toY, speedFactor),
        duration: animDuration,
      });
    }

    dismissHint();
    playDryBrush();
    playBrush();

    if (lastMoveEvent.capturedPiece) {
      setCapturedAnimKey((key) => key + 1);
      setCaptureAnim({
        x: toX,
        y: toY,
        key: lastMoveEvent.key,
      });
    }

    const whooshTimeout = window.setTimeout(() => playWhoosh(), 150);
    return () => window.clearTimeout(whooshTimeout);
  }, [lastMoveEvent, boardPad, margin, BASE_CELL, playDryBrush, playBrush, playWhoosh]);

  const buildTally = (pieces: Piece[]) => {
    const tally: Record<string, { piece: Piece; count: number }> = {};
    for (const p of pieces) {
      const key = `${p.color}-${p.type}`;
      if (!tally[key]) tally[key] = { piece: p, count: 0 };
      tally[key].count++;
    }
    return Object.values(tally);
  };

  const selectedPiece = selected ? board[selected[0]][selected[1]] : null;
  const selectedRule = selectedPiece ? PIECE_RULES.find(r => r.type === selectedPiece.type) : null;
  const phaseLabel = formatPhaseLabel(deriveGamePhaseFromFen(fen), lang);
  const isAtStartFen = fen === START_FEN;
  const primaryGuidanceMove = structuredGuidance?.recommendedLine[0] ?? null;
  const primaryGuidanceSquares: [number, number][] = primaryGuidanceMove
    ? [primaryGuidanceMove.from, primaryGuidanceMove.to]
    : [];
  const primaryGuidanceActive =
    primaryGuidanceSquares.length > 0 &&
    JSON.stringify(guidanceHighlights) === JSON.stringify(primaryGuidanceSquares);
  const formattedCoachSummary = coachGuidance
    ? rewriteCoachSummary(coachGuidance.summary, board, lang)
    : '';

  // Pills for "Best move:" / "Best line:" become clickable. Click parses
  // the move that follows in the prose and toggles the board highlight,
  // matching the behaviour of the recommended-line chips below.
  const handleCoachPillClick = useCallback((label: string) => {
    if (!formattedCoachSummary) return;
    const normalized = label.trim();
    const lower = normalized.toLowerCase();
    if (!lower.startsWith('best move') && !lower.startsWith('best line')) return;

    const labelIdx = formattedCoachSummary.indexOf(normalized);
    if (labelIdx < 0) return;
    const after = formattedCoachSummary.slice(labelIdx + normalized.length);
    const moveMatch = after.match(/[a-i][0-9][a-i][0-9]/);
    if (!moveMatch) return;

    const move = moveMatch[0];
    const from = squareToCoords(move.slice(0, 2));
    const to = squareToCoords(move.slice(2, 4));
    if (!from || !to) return;

    const squares: [number, number][] = [from, to];
    setGuidanceHighlights((prev) =>
      JSON.stringify(prev) === JSON.stringify(squares) ? [] : squares,
    );
  }, [formattedCoachSummary]);
  const resultLabel = result === "red_wins"
    ? t.redWins
    : result === "black_wins"
      ? t.blackWins
      : result === "draw"
        ? t.draw
        : null;
  // Wait for rule image decode before showing
  useEffect(() => {
    if (!selectedRule) { setRuleImageReady(false); return; }
    let mounted = true;
    setRuleImageReady(false);
    preloadAndDecodeImage(selectedRule.image).then(() => {
      if (mounted) setRuleImageReady(true);
    });
    return () => { mounted = false; };
  }, [selectedRule]);

  return (
    <div className={`min-h-screen relative overflow-hidden transition-all duration-500 ${transitioning ? "animate-zoom-exit" : "animate-zoom-enter"}`} style={{ background: "#ffffff" }}>
      {/* Animated fisherman background */}
      <div className="absolute inset-0 z-0">
        <img
          src={fishermanBg.src}
          alt="Fisherman on misty lake"
          className="w-full h-full object-cover opacity-20"
          style={{ animation: "float-bg 40s ease-in-out infinite" }}
          width={1920}
          height={1080}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-white/80 via-white/60 to-white/90" />
      </div>

      {/* Header */}
      <header className="relative z-10 flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 backdrop-blur-sm bg-white/60 border-b border-ink/10">
        <button onClick={handleBack} className="text-ink-light hover:text-ink transition-colors font-calligraphy text-base sm:text-lg tracking-wider">
          {t.back}
        </button>
        <h1 className="font-calligraphy text-ink text-2xl sm:text-3xl">{t.title}</h1>
        <div className="flex gap-3 sm:gap-4">
          <button
            onClick={() => setLang(l => l === "zh" ? "en" : "zh")}
            className="text-ink-light hover:text-ink transition-colors font-calligraphy text-base sm:text-lg tracking-wider border border-ink/20 rounded px-2"
          >
            {t.lang}
          </button>
          <button onClick={handleHint} className="text-ink-light hover:text-ink transition-colors font-calligraphy text-base sm:text-lg tracking-wider">
            {t.hint}
          </button>
          <button
            onClick={() => { setShowRules(r => !r); if (showGuidance) setShowGuidance(false); }}
            className={`transition-colors font-calligraphy text-base sm:text-lg tracking-wider ${showRules ? "text-ink" : "text-ink-light hover:text-ink"}`}
          >
            {t.rules}
          </button>
          <button
            onClick={() => { setShowGuidance(g => !g); if (showRules) setShowRules(false); setGuidanceHighlights([]); }}
            className={`transition-colors font-calligraphy text-base sm:text-lg tracking-wider ${showGuidance ? "text-ink" : "text-ink-light hover:text-ink"}`}
          >
            {t.guidance}
          </button>
          <button onClick={handleReset} className="text-ink-light hover:text-ink transition-colors font-calligraphy text-base sm:text-lg tracking-wider">
            {t.newGame}
          </button>
        </div>
      </header>

      {/* Main layout: board always left, rules panel right */}
      <div className="relative z-10 flex flex-row py-4 sm:py-6 px-2 sm:px-4 gap-6">
        {/* Left: board + tally — always positioned to the left */}
        <div className="flex flex-col items-center flex-shrink-0" style={{ marginLeft: "2vw" }}>
          {/* Turn indicator */}
          <div className="mb-3 sm:mb-4 relative" key={turn}>
            {resultLabel ? (
              <div className="relative px-6 sm:px-8 py-2 flex items-center justify-center overflow-hidden" style={{ minHeight: 40 }}>
                <img
                  src={brushStroke.src}
                  alt=""
                  className="absolute left-0 w-full pointer-events-none opacity-75"
                  style={{
                    top: "50%",
                    transform: "translateY(-50%)",
                    height: "auto",
                    maxHeight: "100%",
                    objectFit: "contain",
                    animation: "brush-swipe 0.6s cubic-bezier(0.22,1,0.36,1) forwards",
                  }}
                />
                <span
                  className="font-calligraphy text-rice-paper text-base sm:text-lg tracking-wider relative z-10"
                  style={{ animation: "turn-text-in 0.5s 0.2s ease-out both" }}
                >
                  {resultLabel}
                </span>
              </div>
            ) : turn === "black" ? (
              <div className="relative px-6 sm:px-8 py-2 flex items-center justify-center overflow-hidden" style={{ minHeight: 40 }}>
                <img
                  src={brushStroke.src}
                  alt=""
                  className="absolute left-0 w-full pointer-events-none"
                  style={{
                    top: "50%",
                    transform: "translateY(-50%)",
                    height: "auto",
                    maxHeight: "100%",
                    objectFit: "contain",
                    animation: "brush-swipe 0.6s cubic-bezier(0.22,1,0.36,1) forwards",
                  }}
                />
                <span
                  className="font-calligraphy text-rice-paper text-base sm:text-lg tracking-wider relative z-10"
                  style={{ animation: "turn-text-in 0.5s 0.2s ease-out both" }}
                >
                  {t.blackTurn}
                </span>
              </div>
            ) : (
              <div className="px-6 sm:px-8 py-2 flex items-center justify-center">
                <span
                  className="font-calligraphy text-ink text-base sm:text-lg tracking-wider"
                  style={{ animation: "turn-text-in 0.4s ease-out both" }}
                >
                  {t.redTurn}
                </span>
              </div>
            )}
          </div>

          {/* Responsive board wrapper */}
          <div
            ref={boardRef}
            className="board-scale-wrapper"
            style={{ width: fullW, height: fullH }}
          >
            <div className="relative w-full h-full">
              <div className="absolute inset-0 backdrop-blur-lg bg-white/20 rounded-sm" />
              <div className="absolute inset-0 bg-gradient-to-br from-white/10 via-transparent to-white/5" />

              {/* SVG Grid */}
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
                  <path key={`h${i}`} d={brushLine(margin, margin + i * BASE_CELL, margin + svgW, margin + i * BASE_CELL, i * 7.3)} stroke="hsl(0 0% 8% / 0.35)" strokeWidth={1.5} fill="none" filter="url(#inkTexture)" />
                ))}

                {Array.from({ length: 9 }, (_, i) => (
                  <g key={`v${i}`}>
                    <path d={brushLine(margin + i * BASE_CELL, margin, margin + i * BASE_CELL, margin + 4 * BASE_CELL, i * 5.1)} stroke="hsl(0 0% 8% / 0.35)" strokeWidth={1.5} fill="none" filter="url(#inkTexture)" />
                    <path d={brushLine(margin + i * BASE_CELL, margin + 5 * BASE_CELL, margin + i * BASE_CELL, margin + 9 * BASE_CELL, i * 5.1 + 100)} stroke="hsl(0 0% 8% / 0.35)" strokeWidth={1.5} fill="none" filter="url(#inkTexture)" />
                  </g>
                ))}

                <path d={brushLine(margin, margin, margin, margin + 9 * BASE_CELL, 99)} stroke="hsl(0 0% 8% / 0.45)" strokeWidth={2} fill="none" filter="url(#inkTexture)" />
                <path d={brushLine(margin + 8 * BASE_CELL, margin, margin + 8 * BASE_CELL, margin + 9 * BASE_CELL, 101)} stroke="hsl(0 0% 8% / 0.45)" strokeWidth={2} fill="none" filter="url(#inkTexture)" />

                <path d={brushLine(margin + 3 * BASE_CELL, margin, margin + 5 * BASE_CELL, margin + 2 * BASE_CELL, 200)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />
                <path d={brushLine(margin + 5 * BASE_CELL, margin, margin + 3 * BASE_CELL, margin + 2 * BASE_CELL, 201)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />
                <path d={brushLine(margin + 3 * BASE_CELL, margin + 7 * BASE_CELL, margin + 5 * BASE_CELL, margin + 9 * BASE_CELL, 202)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />
                <path d={brushLine(margin + 5 * BASE_CELL, margin + 7 * BASE_CELL, margin + 3 * BASE_CELL, margin + 9 * BASE_CELL, 203)} stroke="hsl(0 0% 8% / 0.2)" strokeWidth={1} fill="none" filter="url(#inkTexture)" />

                <text x={totalW / 2} y={margin + 4.5 * BASE_CELL + 6} textAnchor="middle" fill="hsl(0 0% 8% / 0.18)" fontSize="20" fontFamily="'Ma Shan Zheng', cursive" letterSpacing="24">
                  {t.river}
                </text>
              </svg>

              {/* Legal move ink-wash indicators */}
              {selected && legalMoves.map(([mr, mc]) => {
                const x = boardPad + margin + mc * BASE_CELL;
                const y = boardPad + margin + mr * BASE_CELL;
                const hasEnemy = board[mr][mc] && board[mr][mc]!.color !== turn;
                return (
                  <div
                    key={`legal-${mr}-${mc}`}
                    className="absolute pointer-events-none"
                    style={{
                      left: x - (hasEnemy ? 22 : 10),
                      top: y - (hasEnemy ? 22 : 10),
                      width: hasEnemy ? 44 : 20,
                      height: hasEnemy ? 44 : 20,
                    }}
                  >
                    <div className={hasEnemy ? "ink-capture-ring" : "ink-legal-dot"} />
                  </div>
                );
              })}

              {/* Hint overlay */}
              {hintMove && (
                <>
                  {[hintMove.from, hintMove.to].map(([hr, hc], idx) => {
                    const x = boardPad + margin + hc * BASE_CELL;
                    const y = boardPad + margin + hr * BASE_CELL;
                    return (
                      <div
                        key={`hint-${idx}-${hintMove.key}`}
                        className="absolute pointer-events-none hint-ink-spread"
                        style={{
                          left: x - 26,
                          top: y - 26,
                          width: 52,
                          height: 52,
                          animationDelay: idx === 1 ? "0.15s" : "0s",
                        }}
                      />
                    );
                  })}
                </>
              )}

              {/* Guidance highlights */}
              {showGuidance && guidanceHighlights.length > 0 && guidanceHighlights.map(([gr, gc], idx) => {
                const x = boardPad + margin + gc * BASE_CELL;
                const y = boardPad + margin + gr * BASE_CELL;
                return (
                  <div
                    key={`guide-${gr}-${gc}`}
                    className="absolute pointer-events-none guidance-highlight"
                    style={{
                      left: x - 24,
                      top: y - 24,
                      width: 48,
                      height: 48,
                      animationDelay: `${idx * 0.1}s`,
                    }}
                  />
                );
              })}

              {/* Drag trail preview while dragging */}
              {dragState && dragState.isDragging && dragState.trail.length > 0 && (
                <div className="absolute inset-0 pointer-events-none z-25">
                  {/* Connecting stroke from start to current drag position */}
                  <svg className="absolute inset-0" style={{ width: fullW, height: fullH, overflow: "visible" }}>
                    <line
                      x1={boardPad + margin + dragState.col * BASE_CELL}
                      y1={boardPad + margin + dragState.row * BASE_CELL}
                      x2={dragState.currentX} y2={dragState.currentY}
                      stroke="hsl(0 0% 8% / 0.12)"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeDasharray="4 6"
                      style={{ filter: "url(#trailNoise)" }}
                    />
                    <defs>
                      <filter id="trailNoise" x="-20%" y="-20%" width="140%" height="140%">
                        <feTurbulence type="fractalNoise" baseFrequency="1.2" numOctaves="2" result="n" />
                        <feDisplacementMap in="SourceGraphic" in2="n" scale="3" />
                      </filter>
                    </defs>
                  </svg>
                  {/* Soot trail particles along drag path */}
                  {dragState.trail.map((pt) => {
                    const age = (Date.now() - pt.time) / 1000;
                    const decayOpacity = Math.max(0, 0.5 - age * 0.4);
                    const size = 16 + Math.sin(pt.id * 3.7) * 8;
                    return (
                      <img
                        key={pt.id}
                        src={sootBrushImg.src}
                        alt=""
                        className="absolute pointer-events-none"
                        style={{
                          left: pt.x - size / 2,
                          top: pt.y - size / 2,
                          width: size,
                          height: size * (1 + Math.sin(pt.id * 2.1) * 0.4),
                          opacity: decayOpacity,
                          transform: `rotate(${(pt.id * 47) % 360}deg)`,
                          filter: "blur(0.5px)",
                          objectFit: "contain",
                        }}
                      />
                    );
                  })}
                </div>
              )}

              {/* Move trail animation (after release) */}
              {moveAnim && (
                <div key={moveAnim.key} className="absolute inset-0 pointer-events-none z-30"
                  style={{ '--trail-duration': `${moveAnim.duration}ms` } as CSSProperties}
                >
                  {/* Connecting stroke from start to end */}
                  <svg className="absolute inset-0" style={{ width: fullW, height: fullH, overflow: "visible" }}>
                    <line
                      x1={moveAnim.fromX} y1={moveAnim.fromY}
                      x2={moveAnim.toX} y2={moveAnim.toY}
                      stroke="hsl(0 0% 8% / 0.18)"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeDasharray="6 4"
                      className="trail-connecting-stroke"
                      style={{ filter: "url(#trailNoise)", animationDuration: `${moveAnim.duration}ms` }}
                    />
                  </svg>
                  {/* Soot brush image particles */}
                  {moveAnim.particles.map(p => (
                    <img
                      key={p.id}
                      src={sootBrushImg.src}
                      alt=""
                      className="absolute trail-particle pointer-events-none"
                      style={{
                        left: p.x - p.size / 2,
                        top: p.y - p.size / 2,
                        width: p.size,
                        height: p.size * p.elongation,
                        opacity: 0,
                        transform: `rotate(${p.rotation}deg)`,
                        animationDelay: `${p.delay}s`,
                        animationDuration: `${moveAnim.duration * 0.8}ms`,
                        filter: "blur(0.3px)",
                        objectFit: "contain",
                      }}
                    />
                  ))}
                  {/* Ink halo at destination */}
                  <div
                    className="absolute trail-dest-halo"
                    style={{
                      left: moveAnim.toX - 24,
                      top: moveAnim.toY - 24,
                      width: 48,
                      height: 48,
                      borderRadius: "50%",
                      background: "radial-gradient(circle, hsl(0 0% 8% / 0.15) 0%, hsl(0 0% 8% / 0.06) 50%, transparent 75%)",
                    }}
                  />
                </div>
              )}

              {captureAnim && (
                <div
                  key={captureAnim.key}
                  className="absolute pointer-events-none"
                  style={{
                    left: captureAnim.x - 48,
                    top: captureAnim.y - 48,
                    width: 96,
                    height: 96,
                  }}
                >
                  <img
                    src={captureCircleImg.src}
                    alt=""
                    className="absolute inset-0 w-full h-full object-contain capture-circle-anim"
                  />
                  <img
                    src={captureStrikeImg.src}
                    alt=""
                    className="absolute capture-strike-anim object-contain"
                    style={{
                      left: -16,
                      top: 28,
                      width: 128,
                      height: 40,
                    }}
                  />
                </div>
              )}

              {/* Pieces */}
              {board.map((row, r) =>
                row.map((piece, c) => {
                  if (!piece) return null;
                  const isSelected = selected?.[0] === r && selected?.[1] === c;
                  const pieceSize = BASE_CELL - 8;
                  const x = boardPad + margin + c * BASE_CELL - pieceSize / 2;
                  const y = boardPad + margin + r * BASE_CELL - pieceSize / 2;
                  const isBlack = piece.color === "black";
                  const blobClip = isBlack ? generateBlobPath(r * 9 + c) : undefined;
                  const pieceId = `${r}-${c}`;
                  const isHovered = hoveredPiece === pieceId;
                  return (
                    <button
                      key={pieceId}
                      onClick={() => { if (clickSuppressed.current) { clickSuppressed.current = false; return; } handleCellClick(r, c); }}
                      onMouseDown={(e) => { e.preventDefault(); handleDragStart(r, c, e.clientX, e.clientY); }}
                      onTouchStart={(e) => { handleDragStart(r, c, e.touches[0].clientX, e.touches[0].clientY); }}
                      onMouseEnter={() => { setHoveredPiece(pieceId); setHoverKey(k => k + 1); }}
                      onMouseLeave={() => { if (hoveredPiece === pieceId) setHoveredPiece(null); }}
                      className={`absolute flex items-center justify-center transition-all duration-300 cursor-pointer group
                        ${isBlack
                          ? "text-rice-paper piece-black"
                          : "bg-rice-paper/80 rounded-full border border-ink/30 text-ink piece-red"
                        }
                        ${isSelected ? "scale-110 piece-selected" : "hover:scale-105"}
                      `}
                      style={{
                        width: pieceSize,
                        height: pieceSize,
                        left: x,
                        top: y,
                        clipPath: isBlack ? blobClip : undefined,
                        borderRadius: isBlack ? undefined : "50%",
                      }}
                    >
                      <div
                        className={`absolute inset-[-6px] rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none ${
                          isBlack ? "bg-ink/20 blur-md" : "bg-rice-paper/60 blur-md"
                        }`}
                        style={isBlack ? { clipPath: blobClip } : undefined}
                      />
                      {isHovered && (
                        <>
                          <div key={`hr1-${hoverKey}`} className="absolute inset-[-12px] rounded-full pointer-events-none hover-ripple-ring" />
                          <div key={`hr2-${hoverKey}`} className="absolute inset-[-12px] rounded-full pointer-events-none hover-ripple-ring" style={{ animationDelay: "0.15s" }} />
                          <div key={`hr3-${hoverKey}`} className="absolute inset-[-12px] rounded-full pointer-events-none hover-ripple-ring" style={{ animationDelay: "0.3s" }} />
                        </>
                      )}
                      {isSelected && (
                        <>
                          {/* Calligraphic brush stroke crescent */}
                          <svg className="absolute pointer-events-none z-20 brush-stroke-sweep" style={{ left: -14, top: -14, width: pieceSize + 28, height: pieceSize + 28 }} viewBox="0 0 100 100">
                            <ellipse cx="50" cy="50" rx="42" ry="42" fill="none" stroke="hsl(0 0% 8%)" strokeWidth="4" strokeLinecap="round"
                              strokeDasharray="200 80" strokeDashoffset="280"
                              className="brush-crescent-path"
                              style={{ filter: "url(#brushTexture)" }}
                            />
                            <defs>
                              <filter id="brushTexture" x="-10%" y="-10%" width="120%" height="120%">
                                <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="3" result="noise" />
                                <feDisplacementMap in="SourceGraphic" in2="noise" scale="2" />
                              </filter>
                            </defs>
                          </svg>
                          {/* Wet ink halo — single pulsation */}
                          <div className="absolute pointer-events-none z-10 wet-ink-halo" style={{ inset: -10, borderRadius: "50%" }} />
                          {/* Dry-brush texture flicker on piece surface */}
                          <div className="absolute inset-0 pointer-events-none z-30 dry-brush-texture" style={{ borderRadius: isBlack ? undefined : "50%", clipPath: isBlack ? blobClip : undefined }} />
                        </>
                      )}
                      <span style={{ fontFamily: "'Ma Shan Zheng', cursive", fontSize: "1.35rem" }} className="select-none leading-none relative z-10">
                        {PIECE_CHARS[piece.color][piece.type]}
                      </span>
                    </button>
                  );
                })
              )}

              {/* Empty cell click targets */}
              {board.map((row, r) =>
                row.map((piece, c) => {
                  if (piece) return null;
                  const pieceSize = BASE_CELL - 8;
                  const x = boardPad + margin + c * BASE_CELL - pieceSize / 2;
                  const y = boardPad + margin + r * BASE_CELL - pieceSize / 2;
                  const legal = selected && isLegalTarget(r, c);
                  return (
                    <button
                      key={`e-${r}-${c}`}
                      onClick={() => handleCellClick(r, c)}
                      className={`absolute transition-opacity ${legal ? "opacity-100 cursor-pointer" : "opacity-0"}`}
                      style={{ width: pieceSize, height: pieceSize, left: x, top: y }}
                    />
                  );
                })
              )}
            </div>
          </div>

          {/* Captured pieces tally */}
          <div className="mt-4 sm:mt-6 flex gap-6 sm:gap-12">
            {(["red", "black"] as const).map(color => {
              const tally = buildTally(captured[color]);
              return (
                <div key={color} className="text-center px-3 sm:px-4 py-2 rounded-lg backdrop-blur-sm bg-white/30">
                  <p className="font-calligraphy text-ink-wash text-xs sm:text-sm tracking-wider mb-2">
                    {color === "red" ? t.redCaptures : t.blackCaptures}
                  </p>
                  <div className="flex flex-wrap gap-2 max-w-48 sm:max-w-64 justify-center min-h-8">
                    {tally.length === 0 && (
                      <span className="text-ink/20 text-xs font-calligraphy">—</span>
                    )}
                    {tally.map(({ piece, count }, idx) => (
                      <div
                        key={`${piece.color}-${piece.type}-${capturedAnimKey}`}
                        className="flex items-center gap-0.5"
                        style={{ animation: `captured-fade-in 0.4s ${idx * 0.05}s ease-out both` }}
                      >
                        <span
                          style={{ fontFamily: "'Ma Shan Zheng', cursive" }}
                          className={`font-calligraphy text-base sm:text-lg leading-none ${
                            piece.color === "black" ? "text-ink/80" : "text-ink/60"
                          }`}
                        >
                          {PIECE_CHARS[piece.color][piece.type]}
                        </span>
                        {count > 1 && (
                          <span className="text-[10px] text-ink/40 font-calligraphy tracking-wide">
                            {toRoman(count)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {error && (
            <div className="mt-4 max-w-md rounded-lg bg-white/70 backdrop-blur-sm px-4 py-3 text-center text-sm text-ink/70 shadow-sm">
              {error}
            </div>
          )}
        </div>

        {/* Right: rules panel — always occupies space when showRules is on */}
        {showRules && (
          <div className="hidden lg:flex flex-1 items-start justify-center mt-12 min-w-[280px]">
            {selectedRule ? (
              <div
                key={selectedRule.type}
                className="w-80 xl:w-96 flex-shrink-0"
                style={{ animation: "rules-fade-in 0.5s ease-out both" }}
              >
                <div className="rounded-lg bg-white overflow-hidden shadow-sm">
                  <div className="py-4 text-center" style={ruleImageReady ? { animation: "rule-img-fade-in 0.6s ease-out both" } : { opacity: 0 }}>
                    <h3 className="font-calligraphy text-ink text-3xl xl:text-4xl">
                      <span style={{ fontFamily: "'Ma Shan Zheng', cursive" }}>{lang === "zh" ? selectedRule.nameZh : selectedRule.name}</span>
                    </h3>
                    <p className="text-ink/40 text-sm mt-1">{lang === "zh" ? selectedRule.name : selectedRule.nameZh}</p>
                  </div>
                  <div className="bg-white flex items-center justify-center" style={{ height: "33.33vh" }}>
                    {ruleImageReady ? (
                      <img
                        src={selectedRule.image}
                        alt={selectedRule.name}
                        className="w-full h-full object-contain"
                        style={{ animation: "rule-img-fade-in 0.6s ease-out both" }}
                      />
                    ) : (
                      <div className="w-full h-full" />
                    )}
                  </div>
                  <div className="p-5" style={ruleImageReady ? { animation: "rule-img-fade-in 0.6s 0.1s ease-out both" } : { opacity: 0 }}>
                    <p className="text-ink/60 text-sm leading-relaxed">{selectedRule.description}</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="w-80 xl:w-96 flex-shrink-0 text-center mt-20">
                <p className="font-calligraphy text-ink/30 text-lg">{t.selectPieceRule}</p>
                {t.selectPieceRuleSub && <p className="text-ink/20 text-sm mt-1">{t.selectPieceRuleSub}</p>}
              </div>
            )}
          </div>
        )}

        {/* Guidance panel */}
        {showGuidance && (
          <div className="hidden lg:flex flex-1 items-start justify-center mt-12 min-w-[560px]">
            <div
              className="w-[40rem] xl:w-[48rem] flex-shrink-0"
              style={{ animation: "rules-fade-in 0.5s ease-out both" }}
            >
              <div className="rounded-lg bg-white overflow-hidden shadow-sm p-5">
                <h3 className="font-calligraphy text-ink text-2xl xl:text-3xl text-center mb-4">
                  {t.guidanceTitle}
                </h3>
                <p className="text-ink/40 text-xs text-center mb-5 tracking-[0.2em] uppercase">
                  {phaseLabel || t.guidanceSub}
                </p>

                {/* Coach prose summary — animates word-by-word as the LLM
                    response arrives for the current FEN. The "Consulting
                    the coach…" placeholder is suppressed at the starting
                    position so the panel doesn't flash a wait state when
                    the player has not yet moved; reference openings show
                    instead. After the first move, the placeholder appears
                    until the LLM responds, then the typewriter takes over. */}
                {(coachGuidance || (coachGuidanceLoading && !isAtStartFen)) && (
                  <div className="mb-5 pb-5 border-b border-ink/10 min-h-[3rem]">
                    {coachGuidance ? (
                      <Typewriter
                        key={`${fen}-${structuredGuidance?.key ?? 'coach'}`}
                        text={formattedCoachSummary}
                        className="text-ink/70 text-sm leading-relaxed whitespace-pre-line"
                        onPillClick={handleCoachPillClick}
                      />
                    ) : (
                      <p className="text-ink/40 text-xs italic">{lang === 'zh' ? '正在请教棋师…' : 'Consulting the coach…'}</p>
                    )}
                  </div>
                )}

                {coachGuidanceError && !coachGuidance && (
                  <p className="text-ink/40 text-xs italic mb-4">
                    {coachGuidanceError}
                  </p>
                )}

                {primaryGuidanceMove && (
                  <div className="mb-5 pb-5 border-b border-ink/10">
                    <h4 className="font-calligraphy text-ink text-lg mb-2">
                      {lang === 'zh' ? '最佳着法' : 'Best Move'}
                    </h4>
                    <button
                      onClick={() =>
                        setGuidanceHighlights((prev) =>
                          JSON.stringify(prev) === JSON.stringify(primaryGuidanceSquares) ? [] : primaryGuidanceSquares,
                        )
                      }
                      className={`w-full text-left px-3 py-2 rounded-xl border transition-all ${
                        primaryGuidanceActive
                          ? 'bg-ink text-rice-paper border-ink'
                          : 'border-ink/20 text-ink/70 hover:border-ink/40 hover:text-ink'
                      }`}
                    >
                      <p className="font-calligraphy text-sm tracking-wide">
                        {describeMoveWithPiece(board, primaryGuidanceMove.move, lang)}
                      </p>
                      <p className={`text-[11px] mt-1 ${primaryGuidanceActive ? 'text-rice-paper/80' : 'text-ink/40'}`}>
                        {lang === 'zh' ? '点击在棋盘上高亮路线' : 'Tap to highlight the route on the board'}
                      </p>
                    </button>
                  </div>
                )}

                {structuredGuidanceLoading && !structuredGuidance && (
                  <p className="text-ink/30 text-xs italic mb-4">
                    {lang === 'zh' ? '解析中…' : 'Analysing position…'}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes rules-fade-in {
          0% { opacity: 0; transform: translateY(12px); filter: blur(4px); }
          100% { opacity: 1; transform: translateY(0); filter: blur(0); }
        }
        @keyframes rule-img-fade-in {
          0% { opacity: 0; }
          100% { opacity: 1; }
        }
        @keyframes captured-fade-in {
          0% { opacity: 0; transform: translateY(4px); }
          100% { opacity: 1; transform: translateY(0); }
        }

        .guidance-highlight {
          border-radius: 50%;
          background: radial-gradient(circle, hsl(200 70% 50% / 0.35) 0%, hsl(200 70% 50% / 0.15) 50%, transparent 70%);
          border: 2px solid hsl(200 70% 50% / 0.4);
          animation: guidance-pulse 1.5s ease-in-out infinite both;
        }
        @keyframes guidance-pulse {
          0%, 100% { transform: scale(0.85); opacity: 0.5; }
          50% { transform: scale(1.1); opacity: 1; }
        }

        .board-scale-wrapper {
          transform-origin: top center;
        }
        @media (max-width: 560px) {
          .board-scale-wrapper {
            transform: scale(0.7);
            margin-bottom: -${Math.round(fullH * 0.3)}px;
          }
        }
        @media (min-width: 561px) and (max-width: 680px) {
          .board-scale-wrapper {
            transform: scale(0.82);
            margin-bottom: -${Math.round(fullH * 0.18)}px;
          }
        }
        @media (min-width: 681px) and (max-width: 800px) {
          .board-scale-wrapper {
            transform: scale(0.92);
            margin-bottom: -${Math.round(fullH * 0.08)}px;
          }
        }

        @keyframes float-bg {
          0%, 100% { transform: scale(1.05) translateX(0); }
          25% { transform: scale(1.08) translateX(-15px); }
          50% { transform: scale(1.05) translateX(10px) translateY(-8px); }
          75% { transform: scale(1.07) translateX(-8px) translateY(5px); }
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

        /* Calligraphic brush stroke sweep */
        .brush-crescent-path {
          animation: brush-sweep-draw 0.35s cubic-bezier(0.4, 0, 0.2, 1) forwards;
        }
        @keyframes brush-sweep-draw {
          0% { stroke-dashoffset: 280; opacity: 0.6; stroke-width: 6; }
          40% { stroke-width: 5; opacity: 1; }
          80% { stroke-width: 2.5; }
          100% { stroke-dashoffset: 80; opacity: 0.85; stroke-width: 1.5; }
        }

        /* Wet ink halo — glossy rim that pulsates once */
        .wet-ink-halo {
          background: radial-gradient(circle, transparent 55%, hsl(0 0% 8% / 0.12) 65%, hsl(0 0% 8% / 0.06) 75%, transparent 85%);
          animation: wet-halo-pulse 0.8s ease-out forwards;
        }
        @keyframes wet-halo-pulse {
          0% { transform: scale(0.7); opacity: 0; }
          30% { transform: scale(1.05); opacity: 0.4; }
          60% { transform: scale(1.15); opacity: 0.35; }
          100% { transform: scale(1.1); opacity: 0.3; }
        }

        /* Dry-brush texture flicker */
        .dry-brush-texture {
          background: repeating-conic-gradient(
            from 0deg,
            hsl(0 0% 8% / 0.06) 0deg 12deg,
            transparent 12deg 24deg
          );
          animation: dry-brush-flicker 1.2s ease-in-out forwards;
          mix-blend-mode: multiply;
        }
        @keyframes dry-brush-flicker {
          0% { opacity: 0; }
          20% { opacity: 0.5; }
          40% { opacity: 0.2; }
          60% { opacity: 0.45; }
          80% { opacity: 0.15; }
          100% { opacity: 0.1; }
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
          width: 100%; height: 100%; border-radius: 50%;
          background: radial-gradient(circle, hsl(0 0% 8% / 0.35) 0%, hsl(0 0% 8% / 0.1) 50%, transparent 70%);
          animation: ink-dot-appear 0.4s ease-out forwards;
        }

        .ink-capture-ring {
          width: 100%; height: 100%; border-radius: 50%;
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

        .hover-ripple-ring {
          border: 1.5px solid hsl(0 0% 8% / 0.25);
          animation: hover-ripple-out 0.8s ease-out forwards;
        }

        @keyframes hover-ripple-out {
          0% { transform: scale(0.4); opacity: 0.6; filter: blur(0px); border-width: 2px; }
          50% { opacity: 0.35; filter: blur(2px); }
          100% { transform: scale(2.5); opacity: 0; filter: blur(5px); border-width: 0.5px; }
        }

        /* Trail connecting stroke — dissolves from middle outward */
        .trail-connecting-stroke {
          animation: trail-stroke-dissolve 0.6s ease-out forwards;
        }
        @keyframes trail-stroke-dissolve {
          0% { opacity: 0; stroke-dashoffset: 20; }
          20% { opacity: 0.25; stroke-dashoffset: 0; }
          60% { opacity: 0.18; }
          100% { opacity: 0; }
        }

        /* Trail ink splatter particles */
        .trail-particle {
          animation: trail-particle-life 0.55s ease-out forwards;
        }
        @keyframes trail-particle-life {
          0% { opacity: 0; transform: scale(0.3); }
          25% { opacity: 0.4; transform: scale(1.1); }
          70% { opacity: 0.2; transform: scale(0.7); }
          100% { opacity: 0; transform: scale(0.3); }
        }

        /* Destination ink halo ripple */
        .trail-dest-halo {
          animation: trail-halo-bloom 0.5s ease-out 0.15s forwards;
          opacity: 0;
        }
        @keyframes trail-halo-bloom {
          0% { opacity: 0; transform: scale(0.5); }
          40% { opacity: 0.5; transform: scale(1.1); }
          70% { opacity: 0.3; transform: scale(1.2); }
          100% { opacity: 0; transform: scale(1.4); }
        }

        /* Capture circle: show for 0.5s then fade */
        .capture-circle-anim {
          animation: capture-circle-seq 1.0s ease-out forwards;
        }

        @keyframes capture-circle-seq {
          0% { opacity: 0; transform: scale(0.3); }
          10% { opacity: 0.85; transform: scale(0.9); }
          20% { opacity: 0.85; transform: scale(1); }
          50% { opacity: 0.8; transform: scale(1); }
          60% { opacity: 0; transform: scale(1); }
          100% { opacity: 0; transform: scale(1); }
        }

        /* Capture strike: appears at 0.5s, plays for 0.5s */
        .capture-strike-anim {
          opacity: 0;
          animation: capture-strike-seq 1.0s ease-out forwards;
        }

        @keyframes capture-strike-seq {
          0% { clip-path: inset(0 100% 0 0); opacity: 0; }
          50% { clip-path: inset(0 100% 0 0); opacity: 0; }
          55% { opacity: 0.85; }
          80% { clip-path: inset(0 0 0 0); opacity: 0.75; }
          100% { clip-path: inset(0 0 0 0); opacity: 0; }
        }
      `}</style>

      <GameOverModal
        result={result}
        lang={lang}
        onRestart={handleReset}
        onQuit={handleBack}
      />
    </div>
  );
};

export default XiangqiGame;
