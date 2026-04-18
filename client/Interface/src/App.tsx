import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import ChessBoard from './components/ChessBoard';
import ChatPanel from './components/ChatPanel';
import type { ChatPanelHandle } from './components/ChatPanel';
import AgentStateGraph from './components/AgentStateGraph';
import { VoiceButton, VoiceFeedback, VoiceSettings } from './components/VoiceControl';
import { useGameState } from './hooks/useGameState';
import { useWebSocket } from './hooks/useWebSocket';
import { useChessVoiceCommands } from './hooks/useChessVoiceCommands';
import { SpeechService } from './services/speech/SpeechService';
import { SuggestedMove } from './types';
import type { AgentGraphState } from './types/agentState';
import './App.css';

function App() {
  const { gameState, resetGame, setGameStateFromFen, pushMoveRecord } = useGameState();
  const [legalTargets, setLegalTargets] = useState<string[]>([]);
  const [suggestedMove, setSuggestedMove] = useState<SuggestedMove | null>(null);
  const [aiThinking, setAiThinking] = useState(false);
  const [showAgentGraph] = useState(false);
  const [agentGraphData, setAgentGraphData] = useState<AgentGraphState | null>(null);
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);
  const [playMode, setPlayMode] = useState<'guided' | 'free'>('guided');
  const suggestionRequestedRef = useRef(false);
  const aiTurnTimeoutRef = useRef<number | null>(null);
  const aiThinkingRef = useRef(false);

  // Speech service (singleton for component lifetime)
  const speechService = useMemo(() => new SpeechService(), []);

  // Stable refs for use inside handleMessage (avoids circular deps)
  const isConnectedRef = useRef(false);
  const sendMessageRef = useRef<(msg: string) => void>(() => {});

  // Helper: trigger AI turn after server confirms player's move
  const triggerAiTurn = useCallback(() => {
    if (aiThinkingRef.current) return; // Already thinking

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

  const handleMessage = useCallback((message: string) => {
    try {
      const data = JSON.parse(message);
      console.log('[App] Received:', data.type, data);

      if (data.type === 'state') {
        setGameStateFromFen(data.fen);
      } else if (data.type === 'move_result') {
        if (data.valid) {
          console.log('[App] Player move accepted, updating FEN');
          setGameStateFromFen(data.fen);
          // Record the move in history
          if (data.move) {
            const from = data.move.substring(0, 2);
            const to = data.move.substring(2, 4);
            pushMoveRecord(from, to);
          }

          // Notify coaching pipeline about the player's move
          chatPanelRef.current?.sendMoveEvent(
            data.move || '',
            data.fen || '',
            'red',  // Player is red
            data.result || 'in_progress',
            data.is_check || false,
            data.score || 0,
          );

          // Now trigger AI turn since server confirmed side switched to BLACK
          if (isConnectedRef.current && data.result === 'in_progress') {
            console.log('[App] Player move confirmed, scheduling AI turn');
            triggerAiTurn();
          }
        } else {
          console.log('[App] Player move rejected:', data.reason);
          // Revert local board to server state — request fresh state
          if (isConnectedRef.current) {
            sendMessageRef.current(JSON.stringify({ type: 'get_state' }));
          }
        }
      } else if (data.type === 'legal_moves') {
        setLegalTargets(data.targets || []);
      } else if (data.type === 'suggestion') {
        setSuggestedMove({
          from: data.from,
          to: data.to,
          score: data.score,
        });
      } else if (data.type === 'ai_move') {
        console.log('[App] AI move received:', data.move, 'score:', data.score);
        setGameStateFromFen(data.fen);
        if (data.move) {
          const from = data.move.substring(0, 2);
          const to = data.move.substring(2, 4);
          pushMoveRecord(from, to);
        }
        setAiThinking(false);

        // Notify coaching pipeline about the AI's move
        chatPanelRef.current?.sendMoveEvent(
          data.move || '',
          data.fen || '',
          'black',  // AI is black
          data.result || 'in_progress',
          data.is_check || false,
          data.score || 0,
        );
      } else if (data.type === 'error') {
        console.error('[App] Server error:', data.message);
        setAiThinking(false);
      }
    } catch {
      console.log('[App] Received non-JSON message:', message);
    }
  }, [setGameStateFromFen, pushMoveRecord, triggerAiTurn]);

  const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const defaultEngineWsUrl = `${wsProtocol}://${window.location.host}/ws`;
  const engineWsUrl = import.meta.env.VITE_ENGINE_WS_URL || defaultEngineWsUrl;

  const { sendMessage, isConnected } = useWebSocket({
    url: engineWsUrl,
    onMessage: handleMessage,
  });

  // Keep refs in sync with latest values
  isConnectedRef.current = isConnected;
  sendMessageRef.current = sendMessage;

  // When a piece is selected, request legal moves and (once per turn) a suggestion
  const handlePieceSelected = useCallback((square: string) => {
    if (isConnected) {
      sendMessage(JSON.stringify({ type: 'legal_moves', square }));

      // Request suggestion once per turn (not on every piece re-select)
      if (!suggestionRequestedRef.current) {
        suggestionRequestedRef.current = true;
        sendMessage(JSON.stringify({ type: 'suggest', difficulty: 4 }));
      }
    }
  }, [sendMessage, isConnected]);

  // Clear piece deselected
  const handlePieceDeselected = useCallback(() => {
    setLegalTargets([]);
  }, []);

  const handleMove = useCallback((from: string, to: string): boolean => {
    if (!isConnected) return false;

    const moveStr = `${from}${to}`;
    console.log('[App] Sending player move:', moveStr);

    // Send move to server — server is the source of truth
    // Board will update when move_result response arrives
    sendMessage(JSON.stringify({ type: 'move', move: moveStr }));

    // Clear highlights after a move attempt
    setLegalTargets([]);
    setSuggestedMove(null);
    suggestionRequestedRef.current = false;

    return true; // We sent it — actual validity comes from server response
  }, [sendMessage, isConnected]);

  const handleReset = useCallback(() => {
    resetGame();
    setLegalTargets([]);
    setSuggestedMove(null);
    setAiThinking(false);
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


  // Reset aiThinkingRef when aiThinking state is cleared (on AI response or reset)
  useEffect(() => {
    if (!aiThinking) {
      aiThinkingRef.current = false;
    }
  }, [aiThinking]);

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
      // Not yet started → start listening
      voiceCommands.startWakeWordDetection();
    } else if (voiceCommands.wakeWordState === 'listening') {
      // Already listening but wakeword not heard → force awake (push-to-talk)
      voiceCommands.forceAwake();
    } else {
      // Awake or processing → stop entirely
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
        {/* Left Panel: Board + optional Agent Graph */}
        <div className={`w-full ${showAgentGraph ? 'md:w-1/2' : 'md:w-2/3'} flex flex-col border-r border-white/10 bg-black/20 overflow-hidden`}>
          <div className="h-full relative p-3 flex flex-col items-center justify-center border-b border-white/5">
              <ChessBoard
                board={gameState.board}
                sideToMove={gameState.sideToMove}
                onMove={handleMove}
                lastMove={gameState.lastMove}
                legalTargets={legalTargets}
                suggestedMove={suggestedMove}
                onPieceSelected={handlePieceSelected}
                onPieceDeselected={handlePieceDeselected}
                aiThinking={aiThinking}
              />
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
             onAgentGraphUpdate={setAgentGraphData}
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
            to="/agents"
            className="flex items-center gap-2 px-4 h-9 bg-slate-800 hover:bg-purple-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 hover:border-purple-500 transition-all active:scale-95"
            title="Open Agent Pipeline Inspector"
          >
            <span className="material-symbols-outlined text-sm">open_in_new</span>
            <span className="text-[10px] font-bold uppercase hidden md:inline">Inspect</span>
          </Link>
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
    </div>
  );
}

export default App;
