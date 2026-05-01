'use client';

import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import Link from 'next/link';
import ChessBoard from './components/ChessBoard';
import ChatPanel from './components/ChatPanel';
import type { ChatPanelHandle } from './components/ChatPanel';
import AgentStateGraph from './components/AgentStateGraph';
import GameOverModal from './components/GameOverModal';
import EndTurnButton from './components/EndTurnButton';
import { VoiceButton, VoiceFeedback, VoiceSettings } from './components/VoiceControl';
import { useGameState } from './hooks/useGameState';
import { useWebSocket } from './hooks/useWebSocket';
import { useChessVoiceCommands } from './hooks/useChessVoiceCommands';
import { useBoardSync } from './hooks/useBoardSync';
import { useBridgeEventStream } from './hooks/useBridgeEventStream';
import {
  asBestMoveData,
  asFenUpdateData,
  asMoveMadeData,
  parseEngineMessage,
} from './types/bridgeProtocol';
import type {
  BridgeBusEvent,
  EngineAiMoveMessage,
  EngineMoveResultMessage,
  EngineStateMessage,
} from './types/bridgeProtocol';
import { SpeechService } from './services/speech/SpeechService';
import { SuggestedMove, RED, BLACK } from './types';
import type { GameResult } from './types';
import type { Position, Side } from './types';
import type { AgentGraphState } from './types/agentState';
import type { TurnPhase } from './types/turnPhase';
import { bridgeWsUrl } from './services/bridgeClient';
import {
  classifyMove,
  fireKiboTrigger,
  pickMoveQualityTrigger,
  pickOutcomeTrigger,
} from './services/kiboClient';
import './App.css';

const sideToString = (s: Side): 'red' | 'black' => (s === RED ? 'red' : 'black');
const otherSide = (s: Side): Side => (s === RED ? BLACK : RED);
const useBridgeCommands =
  (process.env.NEXT_PUBLIC_USE_BRIDGE_COMMANDS ?? 'true') !== 'false';

interface PendingCoachingEvent {
  move: string;
  fen: string;
  side: 'red' | 'black';
  result: string;
  isCheck: boolean;
  score: number;
}

function App() {
  const { gameState, resetGame, setGameStateFromFen, pushMoveRecord, setResult } = useGameState();
  const [legalTargets, setLegalTargets] = useState<string[]>([]);
  const [suggestedMove, setSuggestedMove] = useState<SuggestedMove | null>(null);
  const [aiThinking, setAiThinking] = useState(false);
  const [showAgentGraph] = useState(false);
  const [agentGraphData] = useState<AgentGraphState | null>(null);
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);
  const [playMode, setPlayMode] = useState<'guided' | 'free'>('guided');
  const [turnNotice, setTurnNotice] = useState<string | null>(null);
  const [turnActionPending, setTurnActionPending] = useState(false);
  const [opponentMove, setOpponentMove] = useState<{ from: Position; to: Position } | null>(null);
  const [boardSyncAlert, setBoardSyncAlert] = useState<string | null>(null);
  // CV health probe + capture/verify helpers live in a hook so they can be
  // tested in isolation and don't pollute the App component with timers.
  const {
    cvServiceHealthy,
    liveBoardCheckEnabled,
    setLiveBoardCheckEnabled,
    requestBoardCapture,
    validatePendingMoveWithLiveBoardCheck,
    detectPhysicalMove,
    verifyPhysicalBoardSync,
  } = useBoardSync(gameState.fen);
  // Which side the human plays. Defaults to RED (Xiangqi opening side).
  // Switching to BLACK triggers an auto-reset so the engine plays the opener.
  const [playerSide, setPlayerSide] = useState<Side>(RED);
  // Pending move + turn phase: a move stays local until the player clicks End Turn,
  // which triggers the WS commit. AI moves arrive automatically but require an
  // End Turn click to acknowledge before the player can interact again.
  const [pendingMove, setPendingMove] = useState<{ from: string; to: string } | null>(null);
  const [turnPhase, setTurnPhase] = useState<TurnPhase>('player_idle');
  const suggestionRequestedRef = useRef(false);
  const aiTurnTimeoutRef = useRef<number | null>(null);
  const aiThinkingRef = useRef(false);
  const endTurnInFlightRef = useRef(false);
  const lastAppliedMoveSignatureRef = useRef<string | null>(null);
  const pendingAcknowledgementCommentaryRef = useRef<PendingCoachingEvent | null>(null);

  // Speech service (singleton for component lifetime)
  const speechService = useMemo(() => new SpeechService(), []);

  // Stable refs for use inside handleMessage (avoids circular deps)
  const isConnectedRef = useRef(false);
  const sendMessageRef = useRef<(msg: string) => void>(() => {});
  // playerSide / turnPhase refs let handleMessage read the latest values
  // without being recreated (and re-subscribing the WS) on every change.
  const playerSideRef = useRef<Side>(playerSide);
  playerSideRef.current = playerSide;
  const turnPhaseRef = useRef<TurnPhase>(turnPhase);
  turnPhaseRef.current = turnPhase;
  const pendingMoveRef = useRef<{ from: string; to: string } | null>(pendingMove);
  pendingMoveRef.current = pendingMove;
  // FEN snapshot taken at the moment the player stages a move. We need
  // this to call /coach/classify-move once the engine confirms the move,
  // because move_result returns the FEN *after* the move and the
  // classifier needs the position before.
  const fenBeforeStagedRef = useRef<string | null>(null);

  // Helper: trigger AI turn after server confirms player's move (or at game
  // start when the engine is the side-to-move).
  const triggerAiTurn = useCallback(() => {
    if (aiThinkingRef.current) return; // Already thinking

    // Cancel any orphaned timer from a previous (interrupted) AI turn
    if (aiTurnTimeoutRef.current !== null) {
      clearTimeout(aiTurnTimeoutRef.current);
      aiTurnTimeoutRef.current = null;
    }

    setLegalTargets([]);
    setSuggestedMove(null);
    suggestionRequestedRef.current = false;

    aiThinkingRef.current = true;
    setAiThinking(true);

    console.log('[App] AI turn: scheduling ai_move in 500ms');
    aiTurnTimeoutRef.current = window.setTimeout(() => {
      console.log('[App] Sending ai_move request');
      sendMessageRef.current(JSON.stringify({ type: 'ai_move', difficulty: 4 }));
      aiTurnTimeoutRef.current = null;
    }, 500);
  }, []);

  // Kibo trigger dispatcher. Called once per End Turn outcome — see
  // docs/Kibo_flow.md for the trigger catalogue and priority order.
  // No-ops (returns null) keep Kibo in its idle loop.
  const dispatchKiboTriggerForPlayerMove = useCallback((
    fenBefore: string | null,
    move: string,
    result: string,
  ) => {
    // Priority 1: game outcome wins over everything else.
    const outcome = pickOutcomeTrigger(
      result,
      sideToString(playerSideRef.current),
    );
    if (outcome) {
      void fireKiboTrigger(outcome);
      return;
    }
    if (result !== 'in_progress') {
      // Game over but not a win/loss for the player (draw etc.) — no trigger.
      return;
    }
    if (!fenBefore || !move) return;
    // Priority 2-4: classify the move and let the kibo client decide.
    void classifyMove(fenBefore, move).then((classification) => {
      if (!classification) return;
      const trigger = pickMoveQualityTrigger(classification);
      if (trigger) void fireKiboTrigger(trigger);
    });
  }, []);

  const flushAcknowledgementCommentary = useCallback(() => {
    const pending = pendingAcknowledgementCommentaryRef.current;
    if (!pending) return;
    pendingAcknowledgementCommentaryRef.current = null;
    chatPanelRef.current?.sendMoveEvent(
      pending.move,
      pending.fen,
      pending.side,
      pending.result,
      pending.isCheck,
      pending.score,
    );
  }, []);

  const applyStateMessage = useCallback((data: EngineStateMessage) => {
    endTurnInFlightRef.current = false;
    setGameStateFromFen(data.fen);
    setOpponentMove(null);
    setTurnActionPending(false);
    // If the engine's side is to move (game start when player is BLACK,
    // or right after a side-switch reset), kick off the AI automatically.
    const fenSide = (data.fen.split(' ')[1] ?? 'w').toLowerCase();
    const sideOnMove: Side = fenSide === 'b' ? BLACK : RED;
    const result = data.result ?? 'in_progress';
    if (result !== 'in_progress') {
      setResult(result as GameResult);
    }
    if (
      isConnectedRef.current &&
      sideOnMove !== playerSideRef.current &&
      result === 'in_progress' &&
      turnPhaseRef.current === 'player_idle' &&
      !aiThinkingRef.current
    ) {
      triggerAiTurn();
    }
  }, [setGameStateFromFen, triggerAiTurn]);

  const applyMoveResultMessage = useCallback((data: EngineMoveResultMessage) => {
    endTurnInFlightRef.current = false;
    if (!data.valid) {
      // Engine rejected the move — fire the rule-violation Kibo reaction
      // (priority 4 in docs/Kibo_flow.md). Reset the staged-fen ref so
      // the next click captures fresh.
      void fireKiboTrigger('illegal_move');
      fenBeforeStagedRef.current = null;
      setPendingMove(null);
      setTurnPhase('player_idle');
      setTurnNotice(data.reason ?? 'Move was rejected by the engine.');
      setTurnActionPending(false);
      if (isConnectedRef.current) {
        sendMessageRef.current(JSON.stringify({ type: 'get_state' }));
      }
      return;
    }

    if (data.fen) setGameStateFromFen(data.fen);
    setOpponentMove(null);
    setPendingMove(null);
    setTurnNotice(null);
    setTurnActionPending(false);
    if (data.move) {
      pushMoveRecord(data.move.substring(0, 2), data.move.substring(2, 4));
    }

    chatPanelRef.current?.sendMoveEvent(
      data.move ?? '',
      data.fen ?? '',
      sideToString(playerSideRef.current),
      data.result ?? 'in_progress',
      data.is_check ?? false,
      data.score ?? 0,
    );

    // Fire a Kibo trigger using the FEN snapshot taken when the move was
    // staged. classify-move runs async; the result might not be a notable
    // classification, in which case nothing posts and Kibo stays idle.
    const fenBefore = fenBeforeStagedRef.current;
    fenBeforeStagedRef.current = null;
    if (data.move) {
      dispatchKiboTriggerForPlayerMove(
        fenBefore,
        data.move,
        data.result ?? 'in_progress',
      );
    }

    if (data.result && data.result !== 'in_progress') {
      setResult(data.result as GameResult);
    } else if (isConnectedRef.current && data.result === 'in_progress') {
      triggerAiTurn();
    }
  }, [setGameStateFromFen, pushMoveRecord, triggerAiTurn, setResult, dispatchKiboTriggerForPlayerMove]);

  const applyAiMoveMessage = useCallback((data: EngineAiMoveMessage) => {
    endTurnInFlightRef.current = false;
    if (data.fen) setGameStateFromFen(data.fen);
    if (data.move) {
      const from = data.move.substring(0, 2);
      const to = data.move.substring(2, 4);
      pushMoveRecord(from, to);
      const fromPos = { file: from.charCodeAt(0) - 'a'.charCodeAt(0), rank: Number(from[1]) };
      const toPos = { file: to.charCodeAt(0) - 'a'.charCodeAt(0), rank: Number(to[1]) };
      if (Number.isInteger(fromPos.rank) && Number.isInteger(toPos.rank)) {
        setOpponentMove({ from: fromPos, to: toPos });
      }
    }
    aiThinkingRef.current = false;
    setAiThinking(false);
    setTurnNotice("Mirror the engine move on the physical board, then press End Engine's Turn.");
    setTurnActionPending(false);
    setTurnPhase('engine_done');
    pendingAcknowledgementCommentaryRef.current = {
      move: data.move ?? '',
      fen: data.fen ?? '',
      side: sideToString(otherSide(playerSideRef.current)),
      result: data.result ?? 'in_progress',
      isCheck: data.is_check ?? false,
      score: data.score ?? 0,
    };

    if (data.result && data.result !== 'in_progress') {
      setResult(data.result as GameResult);
      // Engine's reply ended the game — fire the win/lose Kibo trigger
      // from the player's perspective. Move-quality reactions don't
      // apply to the engine's own moves, only to outcomes.
      const outcome = pickOutcomeTrigger(
        data.result,
        sideToString(playerSideRef.current),
      );
      if (outcome) void fireKiboTrigger(outcome);
    }
  }, [setGameStateFromFen, pushMoveRecord, setResult]);

  const handleEngineMessage = useCallback((message: string) => {
    const data = parseEngineMessage(message);
    if (data === null) return;
    console.log('[App] Received:', data.type);

    switch (data.type) {
      case 'state':
        applyStateMessage(data);
        return;
      case 'move_result':
        applyMoveResultMessage(data);
        return;
      case 'legal_moves':
        setTurnNotice(null);
        setLegalTargets(data.targets);
        return;
      case 'suggestion':
        setSuggestedMove({ from: data.from, to: data.to, score: data.score ?? 0 });
        return;
      case 'ai_move':
        applyAiMoveMessage(data);
        return;
      case 'error':
        console.error('[App] Server error:', data.message ?? data.reason);
        endTurnInFlightRef.current = false;
        if (aiTurnTimeoutRef.current !== null) {
          clearTimeout(aiTurnTimeoutRef.current);
          aiTurnTimeoutRef.current = null;
        }
        aiThinkingRef.current = false;
        setAiThinking(false);
        setTurnNotice(data.message ?? data.reason ?? 'Engine error.');
        setTurnActionPending(false);
        return;
    }
  }, [applyStateMessage, applyMoveResultMessage, applyAiMoveMessage]);

  const shouldApplyBridgeMove = useCallback((source: string, moveStr: string, fen: string) => {
    const signature = `${source}:${moveStr}:${fen}`;
    if (lastAppliedMoveSignatureRef.current === signature) {
      return false;
    }
    lastAppliedMoveSignatureRef.current = signature;
    return true;
  }, []);

  const handleBridgeCommandMessage = useCallback((message: string) => {
    const data = parseEngineMessage(message);
    if (data === null) return;
    console.log('[App] Bridge command response:', data.type);

    switch (data.type) {
      case 'state':
        applyStateMessage(data);
        return;
      case 'legal_moves':
        setTurnNotice(null);
        setLegalTargets(data.targets);
        return;
      case 'suggestion':
        setSuggestedMove({ from: data.from, to: data.to, score: data.score ?? 0 });
        return;
      case 'move_result': {
        if (!data.valid) {
          // Engine rejected the move — fire the illegal_move Kibo trigger
          // (priority 4 per docs/Kibo_flow.md) and reset the staged-fen
          // ref so the next stage captures fresh.
          void fireKiboTrigger('illegal_move');
          fenBeforeStagedRef.current = null;
          endTurnInFlightRef.current = false;
          setPendingMove(null);
          setTurnPhase('player_idle');
          setTurnNotice(data.reason ?? 'Move was rejected by the engine.');
          setTurnActionPending(false);
          return;
        }
        const moveStr = data.move ?? '';
        const fen = data.fen ?? '';
        if (!shouldApplyBridgeMove('player', moveStr, fen)) {
          endTurnInFlightRef.current = false;
          setTurnActionPending(false);
          return;
        }
        applyMoveResultMessage(data);
        return;
      }
      case 'ai_move': {
        const moveStr = data.move ?? '';
        const fen = data.fen ?? '';
        if (!shouldApplyBridgeMove('ai', moveStr, fen)) {
          aiThinkingRef.current = false;
          setAiThinking(false);
          endTurnInFlightRef.current = false;
          setTurnActionPending(false);
          return;
        }
        applyAiMoveMessage(data);
        return;
      }
      case 'error':
        console.error('[App] Bridge command error:', data.message ?? data.reason);
        endTurnInFlightRef.current = false;
        if (aiTurnTimeoutRef.current !== null) {
          clearTimeout(aiTurnTimeoutRef.current);
          aiTurnTimeoutRef.current = null;
        }
        aiThinkingRef.current = false;
        setAiThinking(false);
        setTurnNotice(data.message ?? data.reason ?? 'Bridge error.');
        setTurnActionPending(false);
        return;
    }
  }, [
    setGameStateFromFen,
    setResult,
    shouldApplyBridgeMove,
    applyMoveResultMessage,
    applyAiMoveMessage,
  ]);

  const handleBridgeEvent = useCallback((event: BridgeBusEvent) => {
    console.log('[App] Bridge event:', event.type);

    if (event.type === 'state_sync' || event.type === 'fen_update') {
      const data = asFenUpdateData(event);
      if (data === null) return;
      endTurnInFlightRef.current = false;
      setGameStateFromFen(data.fen);
      setTurnActionPending(false);
      setOpponentMove(null);

      const result = data.result ?? data.game_result ?? 'in_progress';
      if (result !== 'in_progress') {
        setResult(result as GameResult);
      }

      const sideToken = data.fen.split(' ')[1]?.toLowerCase() || 'w';
      const sideOnMove: Side = sideToken === 'b' ? BLACK : RED;
      if (
        isConnectedRef.current &&
        sideOnMove !== playerSideRef.current &&
        result === 'in_progress' &&
        turnPhaseRef.current === 'player_idle' &&
        !aiThinkingRef.current
      ) {
        triggerAiTurn();
      }
      return;
    }

    if (event.type === 'best_move') {
      const data = asBestMoveData(event);
      if (data === null) return;
      setSuggestedMove({ from: data.from, to: data.to, score: 0 });
      return;
    }

    if (event.type === 'move_made') {
      const data = asMoveMadeData(event);
      if (data === null) return;
      const fen = data.fen ?? '';
      const moveFrom = data.from ?? '';
      const moveTo = data.to ?? '';
      const source = data.source ?? '';
      const moveStr = `${moveFrom}${moveTo}`;
      const result = data.result ?? 'in_progress';
      const isCheck = data.is_check ?? false;
      const score = data.score ?? 0;
      if (!shouldApplyBridgeMove(source, moveStr, fen)) {
        return;
      }

      if (fen) setGameStateFromFen(fen);
      if (moveFrom && moveTo) pushMoveRecord(moveFrom, moveTo);
      endTurnInFlightRef.current = false;

      if (source === 'player') {
        setOpponentMove(null);
        setPendingMove(null);
        setTurnNotice(null);
        setTurnActionPending(false);

        chatPanelRef.current?.sendMoveEvent(
          moveStr, fen, sideToString(playerSideRef.current), result, isCheck, score,
        );

        if (result !== 'in_progress') {
          setResult(result as GameResult);
        } else if (isConnectedRef.current) {
          triggerAiTurn();
        }
        return;
      }

      if (source === 'ai' || source === 'opponent') {
        if (moveFrom && moveTo) {
          const fromPos = { file: moveFrom.charCodeAt(0) - 'a'.charCodeAt(0), rank: Number(moveFrom[1]) };
          const toPos = { file: moveTo.charCodeAt(0) - 'a'.charCodeAt(0), rank: Number(moveTo[1]) };
          if (Number.isInteger(fromPos.rank) && Number.isInteger(toPos.rank)) {
            setOpponentMove({ from: fromPos, to: toPos });
          }
        }

        aiThinkingRef.current = false;
        setAiThinking(false);
        setTurnNotice("Mirror the engine move on the physical board, then press End Engine's Turn.");
        setTurnActionPending(false);
        setTurnPhase('engine_done');
        pendingAcknowledgementCommentaryRef.current = {
          move: moveStr,
          fen,
          side: sideToString(otherSide(playerSideRef.current)),
          result,
          isCheck,
          score,
        };

        if (result !== 'in_progress') {
          setResult(result as GameResult);
        }
        return;
      }
    }

    if (event.type === 'game_reset') {
      resetGame();
      setLegalTargets([]);
      setSuggestedMove(null);
      setOpponentMove(null);
      setPendingMove(null);
      setTurnPhase('player_idle');
      setTurnNotice(null);
      setTurnActionPending(false);
      aiThinkingRef.current = false;
      setAiThinking(false);
      lastAppliedMoveSignatureRef.current = null;
      pendingAcknowledgementCommentaryRef.current = null;
      return;
    }
  }, [pushMoveRecord, resetGame, setGameStateFromFen, setResult, triggerAiTurn, shouldApplyBridgeMove]);

  const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const defaultEngineWsUrl = `${wsProtocol}://${window.location.host}/ws`;
  const engineWsUrl = process.env.NEXT_PUBLIC_ENGINE_WS_URL || defaultEngineWsUrl;

  const { sendMessage, isConnected } = useWebSocket({
    url: useBridgeCommands ? bridgeWsUrl('/ws') : engineWsUrl,
    onMessage: useBridgeCommands ? handleBridgeCommandMessage : handleEngineMessage,
  });

  isConnectedRef.current = isConnected;
  sendMessageRef.current = sendMessage;

  useBridgeEventStream(handleBridgeEvent, useBridgeCommands);

  // When a piece is selected, request legal moves and (once per turn) a suggestion.
  // Suppress during engine turn phases to avoid flooding WS.
  const handlePieceSelected = useCallback((square: string) => {
    if (turnPhase !== 'player_idle') return;
    if (!isConnected) return;
    sendMessage(JSON.stringify({ type: 'select', square }));
    if (!suggestionRequestedRef.current) {
      suggestionRequestedRef.current = true;
      sendMessage(JSON.stringify({ type: 'suggest', difficulty: 4 }));
    }
  }, [sendMessage, isConnected, turnPhase]);

  const handlePieceDeselected = useCallback((reason: 'manual' | 'move' | 'system' = 'manual') => {
    setLegalTargets([]);
    if (!useBridgeCommands) return;
    if (reason !== 'manual') return;
    if (turnPhase !== 'player_idle') return;
    if (gameState.sideToMove !== playerSide) return;
    if (!isConnected) return;
    sendMessage(JSON.stringify({ type: 'deselect' }));
  }, [gameState.sideToMove, isConnected, playerSide, sendMessage, turnPhase]);

  // Stage a move locally — do NOT send WS yet. Committed when player clicks End Turn.
  //
  // Rules:
  //  - Only player_idle accepts a move.
  //  - Exactly one move may be staged at a time.
  //  - A second move is rejected until the player clicks Take Back.
  const handleMove = useCallback((from: string, to: string): boolean => {
    if (turnPhase !== 'player_idle') {
      console.log('[App] Move ignored — not in player phase (turnPhase:', turnPhase, ')');
      return false;
    }
    if (pendingMove) {
      console.log('[App] Second move rejected — use Take Back to change the move');
      setTurnNotice('Second move rejected. Use Take Back before making a different move.');
      return false;
    }

    console.log('[App] Pending move set:', from, '→', to);
    setBoardSyncAlert(null);
    setPendingMove({ from, to });
    setTurnPhase('player_pending');
    setTurnNotice('Move staged locally. Press End My Turn to submit it.');
    // Capture the engine's view of the position before this move so the
    // Kibo trigger pipeline can call /coach/classify-move once the
    // engine confirms the move.
    fenBeforeStagedRef.current = gameState.fen;

    setLegalTargets([]);
    setSuggestedMove(null);
    suggestionRequestedRef.current = false;
    return true;
  }, [pendingMove, turnPhase, gameState.fen]);

  // Commit the pending move (player) or acknowledge the engine's move.
  const handleEndTurn = useCallback(() => {
    if (endTurnInFlightRef.current) return;

    const stagedMove = pendingMoveRef.current;

    if (stagedMove) {
      if (!isConnectedRef.current) {
        console.warn('[App] Cannot end turn — not connected');
        setTurnNotice('Cannot end turn while disconnected from the engine.');
        return;
      }
      endTurnInFlightRef.current = true;
      setTurnActionPending(true);
      const moveStr = `${stagedMove.from}${stagedMove.to}`;
      console.log('[App] End Turn: committing player move', moveStr);
      setTurnNotice(liveBoardCheckEnabled && cvServiceHealthy
        ? 'Verifying the physical board before submitting the move...'
        : `Submitting move ${moveStr}...`);

      void (async () => {
        try {
          let cvUnavailableNotice: string | null = null;
          if (liveBoardCheckEnabled && cvServiceHealthy) {
            const capture = await requestBoardCapture();
            if (capture.fen) {
              // Real validation: camera saw a board, must agree with the
              // engine's view of the staged move.
              await validatePendingMoveWithLiveBoardCheck(moveStr, capture);
            } else {
              // CV went unavailable between the last 5-sec health probe
              // and this click. Don't reject the move — submit with a
              // notice so the user knows verification was skipped.
              cvUnavailableNotice =
                'CV service unavailable; submitting move without physical-board verification.';
            }
          }

          setBoardSyncAlert(null);
          setTurnNotice(cvUnavailableNotice ?? `Submitting move ${moveStr}...`);
          sendMessageRef.current(JSON.stringify({ type: 'move', move: moveStr }));
          setTurnPhase('awaiting_engine');
        } catch (error: unknown) {
          const message = error instanceof Error
            ? error.message
            : 'Board out of sync. This can be caused by a misplaced move or low CV confidence.';
          // Match docs/error_handling.md: the alternative flow rejects the
          // submission but the client *stays the same* — the staged move
          // is preserved so the user can dismiss the warning and either
          // press End Turn again to retry the validation, or Take Back
          // to discard. Don't clear pendingMove or flip turnPhase.
          setTurnNotice(message);
          setBoardSyncAlert(message);
          endTurnInFlightRef.current = false;
          setTurnActionPending(false);
        }
      })();
    } else if (turnPhase === 'player_idle') {
      if (!isConnectedRef.current) {
        setTurnNotice('Cannot end turn while disconnected from the engine.');
        return;
      }

      // Without a staged digital move, the only legitimate End Turn flow is
      // "I made the move on the physical board — derive it from CV." If
      // CV isn't available (or the user disabled live board check), there's
      // nothing to commit, so prompt them to stage a move first instead of
      // surfacing the raw bridge 503 to the UI.
      if (!liveBoardCheckEnabled || !cvServiceHealthy) {
        setTurnNotice('You need to pick a move before ending your turn.');
        return;
      }

      endTurnInFlightRef.current = true;
      setTurnActionPending(true);
      setTurnNotice('Checking physical board for a completed move...');

      void detectPhysicalMove()
        .then((derivedMove) => {
          setTurnNotice(`Submitting physical move ${derivedMove.move}...`);
          sendMessageRef.current(JSON.stringify({ type: 'move', move: derivedMove.move }));
          setTurnPhase('awaiting_engine');
        })
        .catch((error: unknown) => {
          // CV-derived move failed validation — this is a real error path
          // (board out of sync, illegal move, etc.), not the no-move case
          // that's now caught by the guard above.
          const message = error instanceof Error
            ? error.message
            : 'Unable to validate the physical-board move.';
          setTurnNotice(message);
        })
        .finally(() => {
          endTurnInFlightRef.current = false;
          setTurnActionPending(false);
        });
    } else if (turnPhase === 'engine_done') {
      console.log('[App] End Turn: acknowledging engine move');
      endTurnInFlightRef.current = true;
      setTurnActionPending(true);
      setTurnNotice('Verifying the physical board matches the engine move...');

      void verifyPhysicalBoardSync()
        .then(({ ok, message }) => {
          if (!ok) {
            setTurnNotice(message);
            return;
          }
          // Only flush coaching commentary after a clean verification.
          // When CV is unavailable (message is non-null on the success path)
          // we still advance the turn but skip commentary so the user isn't
          // told a board state was confirmed when it wasn't.
          if (message === null) {
            flushAcknowledgementCommentary();
          } else {
            pendingAcknowledgementCommentaryRef.current = null;
          }
          setTurnPhase('player_idle');
          setTurnNotice(message);
        })
        .finally(() => {
          endTurnInFlightRef.current = false;
          setTurnActionPending(false);
        });
    }
  }, [
    turnPhase,
    detectPhysicalMove,
    verifyPhysicalBoardSync,
    flushAcknowledgementCommentary,
    requestBoardCapture,
    liveBoardCheckEnabled,
    cvServiceHealthy,
    validatePendingMoveWithLiveBoardCheck,
  ]);

  // Discard the staged move and return to player_idle so a fresh piece can be chosen.
  const handleTakeBack = useCallback(() => {
    if (turnPhase !== 'player_pending') return;
    console.log('[App] Take Back: discarding pending move');
    setPendingMove(null);
    setTurnPhase('player_idle');
    setTurnNotice('Pending move cleared. You can make a different move now.');
    setLegalTargets([]);
    setSuggestedMove(null);
    suggestionRequestedRef.current = false;
  }, [turnPhase]);

  const handleReset = useCallback(() => {
    resetGame();
    setLegalTargets([]);
    setSuggestedMove(null);
    setOpponentMove(null);
    setPendingMove(null);
    setTurnPhase('player_idle');
    setTurnNotice(null);
    setBoardSyncAlert(null);
    setTurnActionPending(false);
    setAiThinking(false);
    endTurnInFlightRef.current = false;
    aiThinkingRef.current = false;
    suggestionRequestedRef.current = false;
    lastAppliedMoveSignatureRef.current = null;
    pendingAcknowledgementCommentaryRef.current = null;
    if (aiTurnTimeoutRef.current) {
      clearTimeout(aiTurnTimeoutRef.current);
      aiTurnTimeoutRef.current = null;
    }
    if (isConnected) {
      sendMessage(JSON.stringify({ type: 'reset' }));
    }
  }, [resetGame, sendMessage, isConnected]);

  const handleLiveBoardCheckToggle = useCallback(() => {
    setLiveBoardCheckEnabled(!liveBoardCheckEnabled);
  }, [liveBoardCheckEnabled, setLiveBoardCheckEnabled]);

  // Switch which side the player controls. Forces a reset so the engine
  // is in a clean state for the new orientation; if the new side is BLACK,
  // the engine plays the opening move automatically (handled in the `state`
  // response by triggerAiTurn).
  const handleSwitchSide = useCallback(() => {
    const next = otherSide(playerSideRef.current);
    console.log('[App] Switching player side to', sideToString(next));
    // Update the ref synchronously so the upcoming `state` response, which
    // arrives before the next render, reads the new value.
    playerSideRef.current = next;
    setPlayerSide(next);
    handleReset();
  }, [handleReset]);

  // Voice commands: chess moves go to engine, chat goes to ChatPanel
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);

  const handleVoiceChatMessage = useCallback((message: string) => {
    chatPanelRef.current?.sendVoiceMessage(message);
  }, []);

  const voiceCommands = useChessVoiceCommands(
    speechService,
    undefined, // chess move handling (could be wired later)
    handleVoiceChatMessage
  );

  // Auto-start wake word detection
  useEffect(() => {
    voiceCommands.startWakeWordDetection();
    return () => {
      voiceCommands.stopWakeWordDetection();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleVoiceToggle = useCallback(() => {
    if (voiceCommands.wakeWordState === 'idle') {
      voiceCommands.startWakeWordDetection();
    } else if (voiceCommands.wakeWordState === 'listening') {
      voiceCommands.forceAwake();
    } else {
      voiceCommands.stopWakeWordDetection();
    }
  }, [voiceCommands]);

  // Cleanup speech service on unmount
  useEffect(() => {
    return () => {
      speechService.destroy();
    };
  }, [speechService]);

  return (
    <div className="bg-background-dark text-slate-100 flex flex-col font-display h-screen w-screen overflow-hidden">
      <main className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Left Panel: Board + Turn controls */}
        <div className={`w-full ${showAgentGraph ? 'md:w-1/2' : 'md:w-2/3'} flex flex-col border-r border-white/10 bg-black/20 overflow-hidden`}>
          <div className="h-full relative p-3 flex flex-col items-center justify-center border-b border-white/5">
            <div className="flex w-full max-w-[760px] flex-col items-center gap-4 md:flex-row md:items-start md:justify-center">
              <ChessBoard
                board={gameState.board}
                sideToMove={gameState.sideToMove}
                onMove={handleMove}
                legalTargets={legalTargets}
                suggestedMove={suggestedMove}
                onPieceSelected={handlePieceSelected}
                onPieceDeselected={handlePieceDeselected}
                aiThinking={aiThinking}
                opponentMove={opponentMove ?? undefined}
                pendingMove={pendingMove}
                canInteract={turnPhase === 'player_idle' && !turnActionPending}
                playerSide={playerSide}
              />
              <aside className="flex w-full max-w-[220px] flex-col gap-3 md:self-stretch">
                <EndTurnButton
                  turnPhase={turnPhase}
                  hasPendingMove={pendingMove !== null}
                  busy={turnActionPending}
                  onEndTurn={handleEndTurn}
                  onTakeBack={handleTakeBack}
                />
                {turnNotice ? (
                  <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs font-medium text-amber-100">
                    {turnNotice}
                  </div>
                ) : null}
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
                        Live Board Check
                      </div>
                      <div className="mt-1 text-[11px] text-slate-300">
                        {cvServiceHealthy ? 'Use CV to verify the board before ending your turn.' : 'CV offline — verification is disabled.'}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={handleLiveBoardCheckToggle}
                      className={`rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] transition-all ${
                        liveBoardCheckEnabled
                          ? 'border-emerald-400/50 bg-emerald-500/15 text-emerald-200'
                          : 'border-white/10 bg-white/5 text-slate-400'
                      }`}
                    >
                      {liveBoardCheckEnabled ? 'On' : 'Off'}
                    </button>
                  </div>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
                    Board Markers
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-2 text-[11px] text-slate-200">
                    {[
                      ['bg-[#ff5459]', 'Selected piece'],
                      ['bg-white border border-white/70', 'Legal empty square'],
                      ['bg-[#ff7b30]', 'Capture square'],
                      ['bg-[#3673ff]', 'Engine move from'],
                      ['bg-[#a556ff]', 'Engine move to'],
                      ['bg-[#31d566]', 'Best move'],
                    ].map(([swatchClass, label]) => (
                      <div key={label} className="flex items-center gap-3">
                        <span className={`h-3.5 w-3.5 rounded-full shadow-[0_0_10px_rgba(255,255,255,0.12)] ${swatchClass}`} />
                        <span>{label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </div>

        {/* Middle Panel: Agent State Graph (toggle) */}
        {showAgentGraph && (
          <div className="w-full md:w-1/4 flex flex-col border-r border-white/10 overflow-hidden">
            <AgentStateGraph graphData={agentGraphData} />
          </div>
        )}

        {/* Right Panel: Chat and Info */}
        <div className={`w-full ${showAgentGraph ? 'md:w-1/4' : 'md:w-1/3'} flex flex-col bg-background-dark overflow-hidden`}>
          <ChatPanel
            ref={chatPanelRef}
            moveHistory={gameState.moveHistory}
            aiThinking={aiThinking}
            suggestedMove={suggestedMove}
            gameStateFen={gameState.fen}
            speechService={speechService}
          />
        </div>
      </main>

      <footer className="h-14 bg-background-dark border-t border-white/10 flex items-center px-4 md:px-6 justify-between shrink-0">
        <div className="flex bg-white/5 p-1 rounded-lg">
          <button
            className={`px-3 md:px-5 py-1.5 text-[10px] font-bold rounded-md transition-all uppercase ${
              playMode === 'guided'
                ? 'bg-primary text-white shadow-lg'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setPlayMode('guided')}
            aria-pressed={playMode === 'guided'}
          >
            Guided Analysis
          </button>
          <button
            className={`px-3 md:px-5 py-1.5 text-[10px] font-bold rounded-md transition-all uppercase ${
              playMode === 'free'
                ? 'bg-primary text-white shadow-lg'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setPlayMode('free')}
            aria-pressed={playMode === 'free'}
          >
            Free Play
          </button>
        </div>
        <div className="hidden md:flex items-center gap-8">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.4)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.4)]'}`}></span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              {isConnected ? 'Board Synced' : 'Disconnected'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Voice Control */}
          <div className="relative">
            <VoiceFeedback
              isListening={voiceCommands.isListening}
              isSpeaking={voiceCommands.isSpeaking}
              isAwake={voiceCommands.isAwake}
              wakeWordState={voiceCommands.wakeWordState}
              transcript={voiceCommands.transcript}
              interimTranscript={voiceCommands.interimTranscript}
              error={voiceCommands.error}
            />
            <VoiceButton
              isListening={voiceCommands.isListening}
              isSpeaking={voiceCommands.isSpeaking}
              wakeWordState={voiceCommands.wakeWordState}
              onToggle={handleVoiceToggle}
            />
          </div>
          <Link
            href="/hardware"
            className="flex items-center gap-2 px-4 h-9 bg-slate-800 hover:bg-amber-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 hover:border-amber-500 transition-all active:scale-95"
            title="Open Hardware & Bus Dashboard"
          >
            <span className="material-symbols-outlined text-sm">developer_board</span>
            <span className="text-[10px] font-bold uppercase hidden md:inline">Hardware</span>
          </Link>
          <Link
            href="/agents"
            className="flex items-center gap-2 px-4 h-9 bg-slate-800 hover:bg-purple-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 hover:border-purple-500 transition-all active:scale-95"
            title="Open Agent Pipeline Inspector"
          >
            <span className="material-symbols-outlined text-sm">open_in_new</span>
            <span className="text-[10px] font-bold uppercase hidden md:inline">Inspect</span>
          </Link>
          <button
            onClick={handleSwitchSide}
            className="flex items-center gap-2 px-4 h-9 bg-slate-800 hover:bg-slate-700 text-white rounded-lg border border-slate-700 transition-all active:scale-95"
            title={`Currently playing ${sideToString(playerSide).toUpperCase()} — click to switch sides (resets game)`}
          >
            <span
              className={`w-3 h-3 rounded-full border ${
                playerSide === RED
                  ? 'bg-red-500 border-red-400 shadow-[0_0_8px_rgba(239,68,68,0.5)]'
                  : 'bg-slate-200 border-slate-300 shadow-[0_0_8px_rgba(226,232,240,0.5)]'
              }`}
            />
            <span className="text-[10px] font-bold uppercase">
              Play {sideToString(playerSide) === 'red' ? 'Red' : 'Black'}
            </span>
          </button>
          <button onClick={handleReset} className="flex items-center gap-2 px-4 h-9 bg-slate-800 hover:bg-slate-700 text-white rounded-lg border border-slate-700 transition-all active:scale-95">
            <span className="material-icons text-sm">restart_alt</span>
            <span className="text-[10px] font-bold uppercase">Reset</span>
          </button>
          <button onClick={() => setShowVoiceSettings(true)} className="w-9 h-9 bg-primary/20 text-primary rounded-lg flex items-center justify-center border border-primary/30 hover:bg-primary hover:text-white transition-all active:scale-95">
            <span className="material-icons text-sm">settings</span>
          </button>
        </div>
      </footer>

      {/* Voice Settings Modal */}
      <VoiceSettings
        speechService={speechService}
        isOpen={showVoiceSettings}
        onClose={() => setShowVoiceSettings(false)}
      />

      {boardSyncAlert ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/55 px-4">
          <div className="w-full max-w-md rounded-3xl border border-red-500/30 bg-slate-950 p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-red-300">
                  Board Out Of Sync
                </div>
                <p className="mt-3 text-sm text-slate-100">
                  {boardSyncAlert}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setBoardSyncAlert(null)}
                aria-label="Dismiss board sync warning"
                className="rounded-full border border-white/10 px-3 py-1 text-xs font-bold text-slate-300 hover:bg-white/10"
              >
                X
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Game Over Modal */}
      <GameOverModal
        result={gameState.result}
        playerSide={sideToString(playerSide)}
        onNewGame={handleReset}
        onAnalyze={() => {
          setResult('in_progress');
        }}
      />
    </div>
  );
}

export default App;
