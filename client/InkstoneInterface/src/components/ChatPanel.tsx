'use client';

import { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import axios from 'axios';
import { MoveRecord, SuggestedMove, PIECE_INFO } from '../types';
import type { SpeechService } from '../services/speech/SpeechService';
import { dashboardUrl } from '../services/coachClient';

// ========================
//   TYPES
// ========================

interface OnboardingButton {
  label: string;
  value: string;
  description: string;
}

interface ChatMessage {
  role: 'user' | 'assistant' | 'onboarding';
  content: string;
  buttons?: OnboardingButton[];
  progress?: { current: number; total: number };
}

interface ChatPanelProps {
  moveHistory: MoveRecord[];
  aiThinking: boolean;
  suggestedMove: SuggestedMove | null;
  gameStateFen: string;
  speechService?: SpeechService | null;
  resetVersion?: number;
}

export interface ChatPanelHandle {
  sendVoiceMessage: (msg: string) => void;
  sendMoveEvent: (move: string, fen: string, side: string, result: string, isCheck: boolean, score: number) => void;
}

// ========================
//   COMPONENT
// ========================

const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel({
  moveHistory,
  aiThinking,
  suggestedMove,
  gameStateFen,
  speechService,
  resetVersion = 0,
}, ref) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [pendingRequests, setPendingRequests] = useState(0);
  const [onboardingComplete] = useState(false);
  const [activeButtons, setActiveButtons] = useState<OnboardingButton[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef(`session-${Date.now()}`);
  const warmupSessionIdRef = useRef(`${sessionIdRef.current}-warmup`);
  const sessionGenerationRef = useRef(0);

  const isTyping = pendingRequests > 0;

  const beginRequest = useCallback(() => {
    setPendingRequests((count) => count + 1);
  }, []);

  const endRequest = useCallback(() => {
    setPendingRequests((count) => Math.max(0, count - 1));
  }, []);

  // Routes through the BFF: /api/dashboard/chat → go-coach /dashboard/chat.
  // Same-origin POST so axios picks up the inkstone_session cookie
  // automatically; the BFF attaches the real STATE_BRIDGE_TOKEN.
  const postCoachMessage = useCallback(async (payload: {
    message: string;
    session_id: string;
    fen?: string;
    move?: string;
  }): Promise<string> => {
    const response = await axios.post(dashboardUrl('/chat'), payload);
    return response.data.response || '';
  }, []);

  const pushAssistantMessage = useCallback((content: string) => {
    setMessages((prev) => [...prev, { role: 'assistant', content }]);
    speechService?.speak(content).catch(() => {});
  }, [speechService]);

  useEffect(() => {
    sessionGenerationRef.current += 1;
    const requestGeneration = sessionGenerationRef.current;
    const sessionId = `session-${Date.now()}-${requestGeneration}`;
    sessionIdRef.current = sessionId;
    warmupSessionIdRef.current = `${sessionId}-warmup`;
    setMessages([]);
    setActiveButtons([]);
    setChatInput('');
    setPendingRequests(0);
    beginRequest();

    void postCoachMessage({
      message: 'Introduce yourself as a Chinese chess coach for a brand-new player. Briefly explain the goal of the game, a few core rules, and a short bit of history. Keep it welcoming and concise. Use the phrase "Chinese chess" and avoid the word "Xiangqi."',
      session_id: warmupSessionIdRef.current,
    }).then((response) => {
      if (sessionGenerationRef.current !== requestGeneration || !response) return;
      pushAssistantMessage(response);
    }).catch(() => {
      if (sessionGenerationRef.current !== requestGeneration) return;
      // Warm-up is best-effort; keep the chat quiet if it fails.
    }).finally(() => {
      if (sessionGenerationRef.current !== requestGeneration) return;
      endRequest();
    });
  }, [beginRequest, endRequest, postCoachMessage, pushAssistantMessage, resetVersion]);

  const deliverAssistantReply = useCallback((content: string, generation: number) => {
    if (sessionGenerationRef.current !== generation) return;
    pushAssistantMessage(content);
  }, [pushAssistantMessage]);

  const handleCoachFailure = useCallback((content: string, generation: number) => {
    if (sessionGenerationRef.current !== generation) return;
    setMessages((prev) => [...prev, { role: 'assistant', content }]);
  }, []);

  const endRequestIfCurrent = useCallback((generation: number) => {
    if (sessionGenerationRef.current !== generation) return;
    endRequest();
  }, [endRequest]);

  // Expose sendVoiceMessage and sendMoveEvent to parent via ref
  useImperativeHandle(ref, () => ({
    sendVoiceMessage: (msg: string) => {
      if (!msg.trim()) return;
      const generation = sessionGenerationRef.current;
      setMessages(prev => [...prev, { role: 'user', content: msg }]);
      beginRequest();

      postCoachMessage({
        message: msg,
        session_id: sessionIdRef.current,
        fen: gameStateFen,
      }).then(response => {
        const content = response || 'Sorry, I could not understand that.';
        deliverAssistantReply(content, generation);
      }).catch(() => {
        handleCoachFailure('Failed to communicate with the coaching agent.', generation);
      }).finally(() => endRequestIfCurrent(generation));
    },
    sendMoveEvent: (move: string, fen: string, side: string, _result: string, isCheck: boolean, score: number) => {
      const generation = sessionGenerationRef.current;
      beginRequest();
      postCoachMessage({
        message: `${side} played ${move}. Check: ${isCheck}, score: ${score}. Comment on this move.`,
        fen,
        move,
        session_id: sessionIdRef.current,
      }).then(response => {
        if (response) {
          deliverAssistantReply(response, generation);
        }
      }).catch(() => {
        // Silently ignore move event failures
      }).finally(() => endRequestIfCurrent(generation));
    },
  }), [beginRequest, deliverAssistantReply, endRequestIfCurrent, gameStateFen, handleCoachFailure, postCoachMessage]);

  // ---- Scroll ----
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping, activeButtons]);

  // ---- Send onboarding answer ----
  const sendOnboardingAnswer = useCallback((value: string, label: string) => {
    const generation = sessionGenerationRef.current;
    setMessages(prev => [...prev, { role: 'user', content: label }]);
    setActiveButtons([]);
    beginRequest();

    postCoachMessage({
      message: value,
      session_id: sessionIdRef.current,
      fen: gameStateFen,
    })
      .then((response) => {
        deliverAssistantReply(response || 'Received.', generation);
      })
      .catch(() => {
        handleCoachFailure('Failed to reach coaching server.', generation);
      })
      .finally(() => endRequestIfCurrent(generation));
  }, [beginRequest, deliverAssistantReply, endRequestIfCurrent, gameStateFen, handleCoachFailure, postCoachMessage]);

  // ---- Send chat message ----
  const handleSendChat = async () => {
    if (!chatInput.trim()) return;

    const generation = sessionGenerationRef.current;
    const text = chatInput.trim();
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setChatInput('');
    beginRequest();

    try {
      const response = await postCoachMessage({
        message: text,
        session_id: sessionIdRef.current,
        fen: gameStateFen,
      });
      deliverAssistantReply(response || 'Sorry, I could not understand that.', generation);
    } catch (error) {
      console.error('Chat error:', error);
      handleCoachFailure('Failed to communicate with the coaching agent.', generation);
    } finally {
      endRequestIfCurrent(generation);
    }
  };

  // ---- Render ----
  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[rgba(18,18,18,0.12)] text-[hsl(40,15%,95%)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-white/5 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-full border border-white/10 bg-white/5 p-2">
            <span className="material-symbols-outlined text-[hsl(40,15%,90%)] text-xl">psychology</span>
          </div>
          <div>
            <h2 className="font-calligraphy text-xl tracking-[0.08em] text-[hsl(40,15%,95%)]">Coach</h2>
            <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">
              Conversation and move guidance
            </div>
          </div>
        </div>
      </div>

      {/* Chat body */}
      <div className="no-scrollbar flex flex-1 flex-col overflow-y-auto border-b border-white/10 p-5">
        <div className="flex-1 space-y-4 mb-4">
          {messages.length === 0 && !suggestedMove && (
            <div className="mt-10 text-center text-xs text-white/45">
              Ask for strategy, tactics, or an explanation of the last move.
            </div>
          )}

          {suggestedMove && onboardingComplete && (
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-[9px] uppercase tracking-[0.2em] text-white/60">
                  Suggested line
                </span>
                <span className="text-xs font-semibold text-[hsl(40,15%,95%)]">{suggestedMove.from}-{suggestedMove.to}</span>
              </div>
              <p className="text-[11px] leading-relaxed text-white/55">
                Consider this tactical move to strengthen your position.
              </p>
            </div>
          )}

          {messages.map((msg, idx) => {
            if (msg.role === 'onboarding') {
              return (
                <div key={idx} className="flex flex-col items-start space-y-3">
                  {/* Onboarding message bubble */}
                  <div className="max-w-[95%] rounded-lg rounded-tl-none border border-white/10 bg-white/5 p-4">
                    {/* Progress indicator */}
                    {msg.progress && msg.progress.total > 0 && (
                      <div className="mb-3">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[9px] font-bold uppercase tracking-widest text-white/45">Setup</span>
                          <span className="text-[9px] text-white/35">
                            {msg.progress.current} / {msg.progress.total}
                          </span>
                        </div>
                        <div className="h-1 w-full overflow-hidden rounded-full bg-white/5">
                          <div
                            className="h-full rounded-full bg-[rgba(247,242,231,0.72)] transition-all duration-500"
                            style={{ width: `${(msg.progress.current / msg.progress.total) * 100}%` }}
                          />
                        </div>
                      </div>
                    )}
                    {/* Message text */}
                    <div className="text-[11px] leading-relaxed whitespace-pre-line text-white/85">
                      {msg.content}
                    </div>
                  </div>

                  {/* Buttons — only for the LAST onboarding message */}
                  {idx === messages.length - 1 && activeButtons.length > 0 && (
                    <div className="w-full flex flex-col gap-2 pl-1">
                      {activeButtons.map((btn) => (
                        <button
                          key={btn.value}
                          onClick={() => sendOnboardingAnswer(btn.value, btn.label)}
                          className="w-full rounded-lg border border-white/10 bg-white/5 px-4 py-3 text-left
                                     hover:border-white/20 hover:bg-white/10
                                     active:scale-[0.98] transition-all group"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-white/90 transition-colors group-hover:text-white">
                              {btn.label}
                            </span>
                            <span className="material-icons text-sm text-white/35 transition-colors group-hover:text-white/65">
                              arrow_forward
                            </span>
                          </div>
                          {btn.description && (
                            <p className="mt-0.5 text-[10px] leading-relaxed text-white/45">
                              {btn.description}
                            </p>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            }

            // Regular user / assistant messages
            return (
              <div key={idx} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className={`p-3 rounded-lg max-w-[85%] text-[11px] ${
                  msg.role === 'user'
                    ? 'rounded-tr-none bg-[rgba(247,242,231,0.88)] text-stone-900'
                    : 'rounded-tl-none bg-white/10 text-white/85'
                }`}>
                  <span className="whitespace-pre-line">{msg.content}</span>
                </div>
              </div>
            );
          })}

          {isTyping && (
            <div className="flex items-start">
              <div className="flex gap-1 rounded-lg rounded-tl-none bg-white/10 p-3 text-[11px] text-white/45">
                <span className="animate-bounce">.</span>
                <span className="animate-bounce" style={{ animationDelay: '75ms' }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: '150ms' }}>.</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input — disabled during onboarding */}
        <div className="mt-auto">
          <div className="flex items-center rounded-lg border border-white/10 bg-black/25 p-1 transition-colors focus-within:border-white/25">
            <input
              type="text"
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSendChat()}
              placeholder="Ask your coach about this position..."
              className="flex-1 border-none bg-transparent px-3 py-2 text-xs text-white/90 focus:ring-0 placeholder:text-white/35"
            />
            <button
              onClick={handleSendChat}
              disabled={isTyping || !chatInput.trim()}
              className="rounded-md p-1.5 text-white/80 transition-colors hover:bg-white/10 disabled:opacity-50"
            >
              <span className="material-icons text-sm">send</span>
            </button>
          </div>
        </div>
      </div>

      {/* Move History */}
      <div className="flex h-1/3 shrink-0 flex-col overflow-hidden bg-black/10">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h4 className="text-[10px] font-bold uppercase tracking-widest text-white/45">Moves</h4>
          <span className="text-[9px] text-white/30">{moveHistory.length}</span>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-2 move-history-scroll">
          <div className="text-[11px] font-mono">
            {moveHistory.length === 0 ? (
              <div className="py-2 text-center text-xs text-white/35">No moves yet</div>
            ) : (
              moveHistory.map((move, index) => {
                const pieceInfo = PIECE_INFO[move.piece];
                const moveNum = Math.floor(index / 2) + 1;
                const isRed = index % 2 === 0;
                return (
                  <div key={index} className="grid grid-cols-12 gap-1 border-b border-white/5 py-1.5">
                    <div className={`col-span-2 ${isRed ? 'font-bold text-[hsl(40,15%,92%)]' : 'text-white/35'}`}>{moveNum}.</div>
                    <div className="col-span-5 text-white/60">
                      {move.from}-{move.to} <span className="ml-1 text-[8px] opacity-40">({pieceInfo?.char || '?'})</span>
                    </div>
                    <div className="col-span-5"></div>
                  </div>
                );
              })
            )}
            {aiThinking && (
              <div className="-mx-5 grid grid-cols-12 gap-1 border-b border-white/5 bg-white/5 px-5 py-1.5">
                <div className="col-span-2 font-bold text-[hsl(40,15%,92%)]">...</div>
                <div className="col-span-10 italic text-white/40">Engine responding...</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});

export default ChatPanel;
