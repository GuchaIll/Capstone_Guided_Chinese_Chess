import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { START_FEN, type GameResult } from '../types';
import { getBridgeWsUrl } from '../services/bridgeClient';
import { useBridgeEventStream } from './useBridgeEventStream';
import { useWebSocket } from './useWebSocket';
import {
  asFenUpdateData,
  asMoveMadeData,
  parseEngineMessage,
  type BridgeBusEvent,
} from '../types/bridgeProtocol';
import { getHintMove } from '../lib/xiangqiRules';
import type { Board, Piece } from '../lib/xiangqiRules';
import {
  coordsToSquare,
  fenToInkstoneBoard,
  fenToInkstoneTurn,
  inferCapturedPieces,
  legalTargetsToCoords,
  moveStringToSquares,
  normalizeEngineResult,
  squareToCoords,
} from '../utils/engineBoardAdapter';

type PieceColor = Piece['color'];

const AI_DIFFICULTY = 4;

interface EngineGameSnapshot {
  fen: string;
  board: Board;
  turn: PieceColor;
  result: GameResult;
}

export interface EngineMoveEvent {
  from: [number, number];
  to: [number, number];
  movedPiece: Piece | null;
  capturedPiece: Piece | null;
  key: number;
}

export interface HintMove {
  from: [number, number];
  to: [number, number];
  key: number;
  source: 'engine' | 'fallback';
}

const INITIAL_SNAPSHOT: EngineGameSnapshot = {
  fen: START_FEN,
  board: fenToInkstoneBoard(START_FEN),
  turn: fenToInkstoneTurn(START_FEN),
  result: 'in_progress',
};

export function useInkstoneEngineGame() {
  const [game, setGame] = useState<EngineGameSnapshot>(INITIAL_SNAPSHOT);
  const [selected, setSelected] = useState<[number, number] | null>(null);
  const [legalMoves, setLegalMoves] = useState<[number, number][]>([]);
  const [lastMoveEvent, setLastMoveEvent] = useState<EngineMoveEvent | null>(null);
  const [hintMove, setHintMove] = useState<HintMove | null>(null);
  const [error, setError] = useState<string | null>(null);

  const gameRef = useRef(game);
  const selectedRef = useRef(selected);
  const legalMovesRef = useRef(legalMoves);
  const lastMoveSignatureRef = useRef<string | null>(null);
  const sendMessageRef = useRef<(message: string) => void>(() => {});
  const isConnectedRef = useRef(false);
  const aiMoveRequestedForFenRef = useRef<string | null>(null);

  useEffect(() => {
    gameRef.current = game;
  }, [game]);

  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  useEffect(() => {
    legalMovesRef.current = legalMoves;
  }, [legalMoves]);

  const applyAuthoritativeSnapshot = useCallback((
    fen: string,
    result: unknown,
    move?: string | null,
  ) => {
    const nextResult = normalizeEngineResult(result ?? gameRef.current.result);
    const nextSnapshot: EngineGameSnapshot = {
      fen,
      board: fenToInkstoneBoard(fen),
      turn: fenToInkstoneTurn(fen),
      result: nextResult,
    };

    if (move) {
      const signature = `${move}:${fen}`;
      if (lastMoveSignatureRef.current !== signature) {
        lastMoveSignatureRef.current = signature;
        const squares = moveStringToSquares(move);
        if (squares) {
          setLastMoveEvent({
            from: squares.from,
            to: squares.to,
            movedPiece: gameRef.current.board[squares.from[0]]?.[squares.from[1]] ?? null,
            capturedPiece: gameRef.current.board[squares.to[0]]?.[squares.to[1]] ?? null,
            key: Date.now(),
          });
        }
      }
    }

    gameRef.current = nextSnapshot;
    setGame(nextSnapshot);
    setSelected(null);
    selectedRef.current = null;
    setLegalMoves([]);
    legalMovesRef.current = [];
    setHintMove(null);
    setError(null);
  }, []);

  const handleBridgeEvent = useCallback((event: BridgeBusEvent) => {
    if (event.type === 'state_sync' || event.type === 'fen_update') {
      const data = asFenUpdateData(event);
      if (!data?.fen) return;
      applyAuthoritativeSnapshot(data.fen, data.result ?? data.game_result);
      return;
    }

    if (event.type === 'move_made') {
      const data = asMoveMadeData(event);
      if (!data?.fen) return;
      const move = data.from && data.to ? `${data.from}${data.to}` : null;
      applyAuthoritativeSnapshot(data.fen, data.result, move);
      return;
    }

    if (event.type === 'game_reset') {
      applyAuthoritativeSnapshot(START_FEN, 'in_progress');
    }
  }, [applyAuthoritativeSnapshot]);

  useBridgeEventStream(handleBridgeEvent, true);

  const handleEngineMessage = useCallback((message: string) => {
    const parsed = parseEngineMessage(message);
    if (!parsed) return;

    switch (parsed.type) {
      case 'state':
        applyAuthoritativeSnapshot(parsed.fen, parsed.result);
        return;
      case 'legal_moves': {
        const currentSelection = selectedRef.current;
        if (!currentSelection) return;
        const expectedSquare = coordsToSquare(currentSelection[0], currentSelection[1]);
        if (parsed.square && parsed.square !== expectedSquare) return;
        setLegalMoves(legalTargetsToCoords(parsed.targets));
        setError(null);
        return;
      }
      case 'move_result':
        if (!parsed.valid || !parsed.fen) {
          setError(parsed.reason ?? 'Move was rejected by the engine.');
          return;
        }
        applyAuthoritativeSnapshot(parsed.fen, parsed.result, parsed.move);
        return;
      case 'ai_move':
        if (!parsed.fen) return;
        applyAuthoritativeSnapshot(parsed.fen, parsed.result, parsed.move ?? null);
        return;
      case 'suggestion': {
        const fromCoords = squareToCoords(parsed.from);
        const toCoords = squareToCoords(parsed.to);
        if (!fromCoords || !toCoords) return;
        setHintMove({ from: fromCoords, to: toCoords, key: Date.now(), source: 'engine' });
        setError(null);
        return;
      }
      case 'error':
        setError(parsed.message ?? parsed.reason ?? 'Engine error.');
        return;
      default:
        return;
    }
  }, [applyAuthoritativeSnapshot]);

  const wsUrlResolver = useCallback(() => getBridgeWsUrl('/ws'), []);
  const handleWsOpen = useCallback(() => setError(null), []);

  const { sendMessage, isConnected } = useWebSocket({
    url: wsUrlResolver,
    onMessage: handleEngineMessage,
    onOpen: handleWsOpen,
  });

  useEffect(() => {
    sendMessageRef.current = sendMessage;
  }, [sendMessage]);

  useEffect(() => {
    isConnectedRef.current = isConnected;
    if (isConnected) {
      sendMessage(JSON.stringify({ type: 'get_state' }));
    }
  }, [isConnected, sendMessage]);

  // Auto-trigger AI when it's black's turn. The bridge does not auto-play
  // the engine after a player move over WS; the client must request it.
  // Guarded by FEN so we don't double-send on re-renders.
  useEffect(() => {
    if (!isConnected) return;
    if (game.result !== 'in_progress') return;
    if (game.turn !== 'black') return;
    if (aiMoveRequestedForFenRef.current === game.fen) return;
    aiMoveRequestedForFenRef.current = game.fen;
    sendMessage(JSON.stringify({ type: 'ai_move', difficulty: AI_DIFFICULTY }));
  }, [game.turn, game.result, game.fen, isConnected, sendMessage]);

  const selectSquare = useCallback((row: number, col: number): boolean => {
    const piece = gameRef.current.board[row]?.[col];
    if (!piece || piece.color !== gameRef.current.turn || gameRef.current.result !== 'in_progress') {
      return false;
    }

    const nextSelected: [number, number] = [row, col];
    setSelected(nextSelected);
    selectedRef.current = nextSelected;
    setLegalMoves([]);
    legalMovesRef.current = [];
    setError(null);

    if (isConnectedRef.current) {
      sendMessageRef.current(JSON.stringify({
        type: 'select',
        square: coordsToSquare(row, col),
      }));
    }

    return true;
  }, []);

  const deselectSquare = useCallback(() => {
    setSelected(null);
    selectedRef.current = null;
    setLegalMoves([]);
    legalMovesRef.current = [];
    if (isConnectedRef.current) {
      sendMessageRef.current(JSON.stringify({ type: 'deselect' }));
    }
  }, []);

  const moveSelectedPiece = useCallback((row: number, col: number): boolean => {
    const currentSelection = selectedRef.current;
    if (!currentSelection || gameRef.current.result !== 'in_progress') {
      return false;
    }

    const isLegalTarget = legalMovesRef.current.some(
      ([legalRow, legalCol]) => legalRow === row && legalCol === col,
    );
    if (!isLegalTarget || !isConnectedRef.current) {
      return false;
    }

    const move = `${coordsToSquare(currentSelection[0], currentSelection[1])}${coordsToSquare(row, col)}`;
    setSelected(null);
    selectedRef.current = null;
    setLegalMoves([]);
    legalMovesRef.current = [];
    setError(null);
    sendMessageRef.current(JSON.stringify({ type: 'move', move }));
    return true;
  }, []);

  const requestHint = useCallback((): boolean => {
    if (gameRef.current.result !== 'in_progress') return false;
    if (isConnectedRef.current) {
      sendMessageRef.current(JSON.stringify({ type: 'suggest', difficulty: AI_DIFFICULTY }));
      return true;
    }
    const fallback = getHintMove(gameRef.current.board, gameRef.current.turn);
    if (!fallback) return false;
    setHintMove({ from: fallback.from, to: fallback.to, key: Date.now(), source: 'fallback' });
    return true;
  }, []);

  const dismissHint = useCallback(() => setHintMove(null), []);

  const resetGame = useCallback((): boolean => {
    if (!isConnectedRef.current) {
      setError('Unable to reset while disconnected from the engine.');
      return false;
    }

    setSelected(null);
    selectedRef.current = null;
    setLegalMoves([]);
    legalMovesRef.current = [];
    setError(null);
    aiMoveRequestedForFenRef.current = null;
    sendMessageRef.current(JSON.stringify({ type: 'reset' }));
    return true;
  }, []);

  const captured = useMemo(() => inferCapturedPieces(game.board), [game.board]);

  return {
    board: game.board,
    fen: game.fen,
    turn: game.turn,
    result: game.result,
    selected,
    legalMoves,
    captured,
    lastMoveEvent,
    hintMove,
    error,
    isConnected,
    selectSquare,
    deselectSquare,
    moveSelectedPiece,
    requestHint,
    dismissHint,
    resetGame,
  };
}
