import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
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
import { SpeechService } from './services/speech/SpeechService';
import { SuggestedMove, RED, BLACK } from './types';
import type { GameResult } from './types';
import type { Position, Side } from './types';
import type { AgentGraphState } from './types/agentState';
import type { TurnPhase } from './types/turnPhase';
import { deriveMoveFromFenDiff, fenPlacementsEqual } from './utils/fenMoveDiff';
import './App.css';

const sideToString = (s: Side): 'red' | 'black' => (s === RED ? 'red' : 'black');
const otherSide = (s: Side): Side => (s === RED ? BLACK : RED);
const stateBridgeBase = import.meta.env.VITE_STATE_BRIDGE_BASE || `${window.location.origin}/bridge`;
const useBridgeCommands = (import.meta.env.VITE_USE_BRIDGE_COMMANDS ?? 'true') !== 'false';
const stateBridgeWs = stateBridgeBase.replace(/^http/, 'ws');

interface BridgeStateSnapshot {
  fen: string;
  cv_fen: string | null;
  side_to_move?: 'red' | 'black';
  game_result?: string;
  is_check?: boolean;
  event_seq?: number;
}

interface BridgeBusEvent {
  type: string;
  data: Record<string, unknown>;
  ts: number;
  seq: number | null;
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

  const handleEngineMessage = useCallback((message: string) => {
    try {
      const data = JSON.parse(message);
      console.log('[App] Received:', data.type, data);

      if (data.type === 'state') {
        endTurnInFlightRef.current = false;
        setGameStateFromFen(data.fen);
        setOpponentMove(null);
        setTurnActionPending(false);
        // If the engine's side is to move (game start when player is BLACK,
        // or right after a side-switch reset), kick off the AI automatically.
        const fenSide = (data.fen?.split(' ')[1] || 'w').toLowerCase();
        const sideOnMove: Side = fenSide === 'b' ? BLACK : RED;
        const result = data.result || 'in_progress';
        if (
          isConnectedRef.current &&
          sideOnMove !== playerSideRef.current &&
          result === 'in_progress' &&
          turnPhaseRef.current === 'player_idle' &&
          !aiThinkingRef.current
        ) {
          console.log('[App] State indicates engine to move — triggering AI');
          triggerAiTurn();
        }
      } else if (data.type === 'move_result') {
        endTurnInFlightRef.current = false;
        if (data.valid) {
          console.log('[App] Player move accepted, updating FEN');
          setGameStateFromFen(data.fen);
          setOpponentMove(null);
          setPendingMove(null);
          setTurnNotice(null);
          setTurnActionPending(false);
          if (data.move) {
            const from = data.move.substring(0, 2);
            const to = data.move.substring(2, 4);
            pushMoveRecord(from, to);
          }

          // Notify coaching pipeline about the player's move
          chatPanelRef.current?.sendMoveEvent(
            data.move || '',
            data.fen || '',
            sideToString(playerSideRef.current),
            data.result || 'in_progress',
            data.is_check || false,
            data.score || 0,
          );

          if (data.result && data.result !== 'in_progress') {
            setResult(data.result);
          }

          if (isConnectedRef.current && data.result === 'in_progress') {
            console.log('[App] Player move confirmed, scheduling AI turn');
            triggerAiTurn();
          }
        } else {
          console.log('[App] Player move rejected:', data.reason);
          setPendingMove(null);
          setTurnPhase('player_idle');
          setTurnNotice(data.reason || 'Move was rejected by the engine.');
          setTurnActionPending(false);
          if (isConnectedRef.current) {
            sendMessageRef.current(JSON.stringify({ type: 'get_state' }));
          }
        }
      } else if (data.type === 'legal_moves') {
        setTurnNotice(null);
        setLegalTargets(data.targets || []);
      } else if (data.type === 'suggestion') {
        setSuggestedMove({
          from: data.from,
          to: data.to,
          score: data.score,
        });
      } else if (data.type === 'ai_move') {
        console.log('[App] AI move received:', data.move, 'score:', data.score);
        endTurnInFlightRef.current = false;
        setGameStateFromFen(data.fen);
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
        // Engine's move is on the board; player must click End Turn to
        // acknowledge — this gives time to mirror the move on the physical board.
        setTurnPhase('engine_done');

        chatPanelRef.current?.sendMoveEvent(
          data.move || '',
          data.fen || '',
          sideToString(otherSide(playerSideRef.current)),
          data.result || 'in_progress',
          data.is_check || false,
          data.score || 0,
        );

        if (data.result && data.result !== 'in_progress') {
          setResult(data.result);
        }
      } else if (data.type === 'error') {
        console.error('[App] Server error:', data.message);
        endTurnInFlightRef.current = false;
        if (aiTurnTimeoutRef.current !== null) {
          clearTimeout(aiTurnTimeoutRef.current);
          aiTurnTimeoutRef.current = null;
        }
        aiThinkingRef.current = false;
        setAiThinking(false);
        setTurnNotice(data.message || 'Engine error.');
        setTurnActionPending(false);
      }
    } catch {
      console.log('[App] Received non-JSON message:', message);
    }
  }, [setGameStateFromFen, pushMoveRecord, triggerAiTurn, setResult]);

  const handleBridgeCommandMessage = useCallback((message: string) => {
    try {
      const data = JSON.parse(message);
      console.log('[App] Bridge command response:', data.type, data);

      if (data.type === 'state') {
        endTurnInFlightRef.current = false;
        setGameStateFromFen(data.fen);
        setTurnActionPending(false);
        if (data.result && data.result !== 'in_progress') {
          setResult(data.result);
        }
      } else if (data.type === 'legal_moves') {
        setTurnNotice(null);
        setLegalTargets(data.targets || []);
      } else if (data.type === 'suggestion') {
        setSuggestedMove({
          from: data.from,
          to: data.to,
          score: data.score,
        });
      } else if (data.type === 'move_result') {
        if (!data.valid) {
          endTurnInFlightRef.current = false;
          setPendingMove(null);
          setTurnPhase('player_idle');
          setTurnNotice(data.reason || 'Move was rejected by the engine.');
          setTurnActionPending(false);
        }
      } else if (data.type === 'error') {
        console.error('[App] Bridge command error:', data.message);
        endTurnInFlightRef.current = false;
        if (aiTurnTimeoutRef.current !== null) {
          clearTimeout(aiTurnTimeoutRef.current);
          aiTurnTimeoutRef.current = null;
        }
        aiThinkingRef.current = false;
        setAiThinking(false);
        setTurnNotice(data.message || 'Bridge error.');
        setTurnActionPending(false);
      }
    } catch {
      console.log('[App] Received non-JSON bridge message:', message);
    }
  }, [setGameStateFromFen, setResult]);

  const handleBridgeEvent = useCallback((event: BridgeBusEvent) => {
    const data = event.data ?? {};
    console.log('[App] Bridge event:', event.type, event);

    if (event.type === 'state_sync' || event.type === 'fen_update') {
      const fen = typeof data.fen === 'string' ? data.fen : null;
      if (!fen) return;
      endTurnInFlightRef.current = false;
      setGameStateFromFen(fen);
      setTurnActionPending(false);
      setOpponentMove(null);

      const result = typeof data.result === 'string'
        ? data.result
        : typeof data.game_result === 'string'
          ? data.game_result
          : 'in_progress';
      if (result !== 'in_progress') {
        setResult(result as GameResult);
      }

      const sideToken = fen.split(' ')[1]?.toLowerCase() || 'w';
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
      if (typeof data.from === 'string' && typeof data.to === 'string') {
        setSuggestedMove({
          from: data.from,
          to: data.to,
          score: 0,
        });
      }
      return;
    }

    if (event.type === 'move_made') {
      const fen = typeof data.fen === 'string' ? data.fen : '';
      const moveFrom = typeof data.from === 'string' ? data.from : '';
      const moveTo = typeof data.to === 'string' ? data.to : '';
      const source = typeof data.source === 'string' ? data.source : '';
      const result = typeof data.result === 'string' ? data.result : 'in_progress';
      const isCheck = Boolean(data.is_check);
      const score = typeof data.score === 'number' ? data.score : 0;

      if (fen) {
        setGameStateFromFen(fen);
      }
      if (moveFrom && moveTo) {
        pushMoveRecord(moveFrom, moveTo);
      }
      endTurnInFlightRef.current = false;

      if (source === 'player') {
        setOpponentMove(null);
        setPendingMove(null);
        setTurnNotice(null);
        setTurnActionPending(false);

        chatPanelRef.current?.sendMoveEvent(
          `${moveFrom}${moveTo}`,
          fen,
          sideToString(playerSideRef.current),
          result,
          isCheck,
          score,
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

        chatPanelRef.current?.sendMoveEvent(
          `${moveFrom}${moveTo}`,
          fen,
          sideToString(otherSide(playerSideRef.current)),
          result,
          isCheck,
          score,
        );

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
      return;
    }
  }, [pushMoveRecord, resetGame, setGameStateFromFen, setResult, triggerAiTurn]);

  const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const defaultEngineWsUrl = `${wsProtocol}://${window.location.host}/ws`;
  const engineWsUrl = import.meta.env.VITE_ENGINE_WS_URL || defaultEngineWsUrl;
  const bridgeWsUrl = `${stateBridgeWs}/ws`;

  const { sendMessage, isConnected } = useWebSocket({
    url: useBridgeCommands ? bridgeWsUrl : engineWsUrl,
    onMessage: useBridgeCommands ? handleBridgeCommandMessage : handleEngineMessage,
  });

  isConnectedRef.current = isConnected;
  sendMessageRef.current = sendMessage;

  useEffect(() => {
    if (!useBridgeCommands) return;

    const events = new EventSource(`${stateBridgeBase}/state/events`);
    events.onmessage = (raw) => {
      try {
        handleBridgeEvent(JSON.parse(raw.data) as BridgeBusEvent);
      } catch (error) {
        console.warn('[App] Failed to parse bridge event:', error);
      }
    };
    events.onerror = (error) => {
      console.warn('[App] Bridge SSE error:', error);
    };

    return () => {
      events.close();
    };
  }, [handleBridgeEvent]);

  // When a piece is selected, request legal moves and (once per turn) a suggestion.
  // Suppress during engine turn phases to avoid flooding WS.
  const handlePieceSelected = useCallback((square: string) => {
    if (turnPhase !== 'player_idle') return;
    if (!isConnected) return;
    sendMessage(JSON.stringify({ type: 'legal_moves', square }));
    if (!suggestionRequestedRef.current) {
      suggestionRequestedRef.current = true;
      sendMessage(JSON.stringify({ type: 'suggest', difficulty: 4 }));
    }
  }, [sendMessage, isConnected, turnPhase]);

  const handlePieceDeselected = useCallback(() => {
    setLegalTargets([]);
  }, []);

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
    setPendingMove({ from, to });
    setTurnPhase('player_pending');
    setTurnNotice('Move staged locally. Press End My Turn to submit it.');

    setLegalTargets([]);
    setSuggestedMove(null);
    suggestionRequestedRef.current = false;
    return true;
  }, [pendingMove, turnPhase]);

  const fetchBridgeJson = useCallback(async (
    path: string,
    init?: RequestInit,
  ): Promise<unknown> => {
    const response = await fetch(`${stateBridgeBase}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
      },
      ...init,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Bridge request failed with ${response.status}`);
    }

    return response.json();
  }, []);

  const detectPhysicalMove = useCallback(async () => {
    const bridgeState = await fetchBridgeJson('/state') as BridgeStateSnapshot;
    if (!bridgeState.cv_fen) {
      throw new Error('No camera board position is available yet.');
    }

    const derivedMove = deriveMoveFromFenDiff(gameState.fen, bridgeState.cv_fen);
    const legality = await fetchBridgeJson('/engine/is-move-legal', {
      method: 'POST',
      body: JSON.stringify({ fen: gameState.fen, move: derivedMove.move }),
    }) as { legal: boolean };

    if (!legality.legal) {
      throw new Error(`Detected physical move ${derivedMove.move} is not legal from the current position.`);
    }

    return derivedMove;
  }, [fetchBridgeJson, gameState.fen]);

  const verifyPhysicalBoardSync = useCallback(async () => {
    try {
      const bridgeState = await fetchBridgeJson('/state') as BridgeStateSnapshot;
      if (!bridgeState.cv_fen) {
        return {
          ok: true,
          message: 'Bridge camera state unavailable; skipping physical-board verification.',
        };
      }

      if (!fenPlacementsEqual(gameState.fen, bridgeState.cv_fen)) {
        return {
          ok: false,
          message: 'Physical board does not match the engine move yet. Mirror the engine move first.',
        };
      }

      return { ok: true, message: null };
    } catch (error) {
      console.warn('[App] Bridge sync check failed:', error);
      return {
        ok: true,
        message: 'Bridge unavailable; continuing without physical-board verification.',
      };
    }
  }, [fetchBridgeJson, gameState.fen]);

  // Commit the pending move (player) or acknowledge the engine's move.
  const handleEndTurn = useCallback(() => {
    if (endTurnInFlightRef.current) return;

    if (turnPhase === 'player_pending' && pendingMove) {
      if (!isConnectedRef.current) {
        console.warn('[App] Cannot end turn — not connected');
        setTurnNotice('Cannot end turn while disconnected from the engine.');
        return;
      }
      endTurnInFlightRef.current = true;
      setTurnActionPending(true);
      const moveStr = `${pendingMove.from}${pendingMove.to}`;
      console.log('[App] End Turn: committing player move', moveStr);
      setTurnNotice(`Submitting move ${moveStr}...`);
      sendMessageRef.current(JSON.stringify({ type: 'move', move: moveStr }));
      setTurnPhase('awaiting_engine');
    } else if (turnPhase === 'player_idle') {
      if (!isConnectedRef.current) {
        setTurnNotice('Cannot end turn while disconnected from the engine.');
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
          setTurnPhase('player_idle');
          setTurnNotice(message);
        })
        .finally(() => {
          endTurnInFlightRef.current = false;
          setTurnActionPending(false);
        });
    }
  }, [pendingMove, turnPhase, detectPhysicalMove, verifyPhysicalBoardSync]);

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
    setTurnActionPending(false);
    setAiThinking(false);
    endTurnInFlightRef.current = false;
    aiThinkingRef.current = false;
    suggestionRequestedRef.current = false;
    if (aiTurnTimeoutRef.current) {
      clearTimeout(aiTurnTimeoutRef.current);
      aiTurnTimeoutRef.current = null;
    }
    if (isConnected) {
      sendMessage(JSON.stringify({ type: 'reset' }));
    }
  }, [resetGame, sendMessage, isConnected]);

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
            to="/hardware"
            className="flex items-center gap-2 px-4 h-9 bg-slate-800 hover:bg-amber-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 hover:border-amber-500 transition-all active:scale-95"
            title="Open Hardware & Bus Dashboard"
          >
            <span className="material-symbols-outlined text-sm">developer_board</span>
            <span className="text-[10px] font-bold uppercase hidden md:inline">Hardware</span>
          </Link>
          <Link
            to="/agents"
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
