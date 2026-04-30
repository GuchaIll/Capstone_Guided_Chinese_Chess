'use client';

import { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import axios from 'axios';
import { MoveRecord, SuggestedMove, PIECE_INFO } from '../types';
import type { SpeechService } from '../services/speech/SpeechService';

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
}, ref) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [onboardingComplete] = useState(false);
  const [activeButtons, setActiveButtons] = useState<OnboardingButton[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef(`session-${Date.now()}`);

  const httpProtocol = globalThis.location.protocol === 'https:' ? 'https' : 'http';
  const defaultCoachUrl = `${httpProtocol}://${globalThis.location.host}`;
  const coachUrl = process.env.NEXT_PUBLIC_COACH_URL || defaultCoachUrl;

  // Expose sendVoiceMessage and sendMoveEvent to parent via ref
  useImperativeHandle(ref, () => ({
    sendVoiceMessage: (msg: string) => {
      if (!msg.trim()) return;
      setMessages(prev => [...prev, { role: 'user', content: msg }]);
      setIsTyping(true);

      axios.post(`${coachUrl}/dashboard/chat`, {
        message: msg,
        session_id: sessionIdRef.current,
        fen: gameStateFen,
      }).then(res => {
        const response = res.data.response || 'Sorry, I could not understand that.';
        setMessages(prev => [...prev, { role: 'assistant', content: response }]);
        speechService?.speak(response).catch(() => {});
      }).catch(() => {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Failed to communicate with the coaching agent.' }]);
      }).finally(() => setIsTyping(false));
    },
    sendMoveEvent: (move: string, fen: string, side: string, _result: string, isCheck: boolean, score: number) => {
      setIsTyping(true);
      axios.post(`${coachUrl}/dashboard/chat`, {
        message: `${side} played ${move}. Check: ${isCheck}, score: ${score}. Comment on this move.`,
        fen,
        move,
        session_id: sessionIdRef.current,
      }).then(res => {
        const response = res.data.response;
        if (response) {
          setMessages(prev => [...prev, { role: 'assistant', content: response }]);
          speechService?.speak(response).catch(() => {});
        }
      }).catch(() => {
        // Silently ignore move event failures
      }).finally(() => setIsTyping(false));
    },
  }), [coachUrl, speechService, gameStateFen]);

  // ---- Scroll ----
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping, activeButtons]);

  // ---- Send onboarding answer ----
  const sendOnboardingAnswer = useCallback((value: string, label: string) => {
    setMessages(prev => [...prev, { role: 'user', content: label }]);
    setActiveButtons([]);
    setIsTyping(true);

    axios.post(`${coachUrl}/dashboard/chat`, {
      message: value,
      session_id: sessionIdRef.current,
      fen: gameStateFen,
    })
      .then(res => {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: res.data.response || 'Received.',
        }]);
        setIsTyping(false);
      })
      .catch(() => {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: 'Failed to reach coaching server.',
        }]);
        setIsTyping(false);
      });
  }, [coachUrl, gameStateFen]);

  // ---- Send chat message ----
  const handleSendChat = async () => {
    if (!chatInput.trim()) return;

    const text = chatInput.trim();
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setChatInput('');
    setIsTyping(true);

    try {
      const response = await axios.post(`${coachUrl}/dashboard/chat`, {
        message: text,
        session_id: sessionIdRef.current,
        fen: gameStateFen,
      });
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: response.data.response || 'Sorry, I could not understand that.',
      }]);
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Failed to communicate with the coaching agent.',
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  // ---- Render ----
  return (
    <div className="w-full h-full flex flex-col bg-background-dark overflow-hidden text-slate-100 font-display">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/5 bg-white/5">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <span className="material-symbols-outlined text-primary text-xl">psychology</span>
          </div>
          <div>
            <h2 className="text-sm font-bold tracking-tight">Strategy Insight</h2>
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-slate-500 uppercase font-medium tracking-wider">LLM EVALUATION</span>
              {suggestedMove && (
                <span className={`text-[9px] font-bold ${suggestedMove.score >= 0 ? 'text-primary' : 'text-red-500'}`}>
                  {suggestedMove.score > 0 ? '+' : ''}{suggestedMove.score}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Chat body */}
      <div className="flex-1 p-5 overflow-y-auto no-scrollbar border-b border-white/5 flex flex-col">
        <div className="flex-1 space-y-4 mb-4">
          {messages.length === 0 && !suggestedMove && (
            <div className="text-slate-500 text-xs text-center mt-10">
              Ask the coaching agent a question about your game...
            </div>
          )}

          {suggestedMove && onboardingComplete && (
            <div className="bg-primary/5 border border-primary/20 rounded-xl p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[9px] font-bold bg-primary text-white px-2 py-0.5 rounded-sm uppercase tracking-wide">AI Recommendation</span>
                <span className="text-xs font-bold text-slate-200">{suggestedMove.from}-{suggestedMove.to}</span>
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Consider this tactical move to strengthen your position.
              </p>
            </div>
          )}

          {messages.map((msg, idx) => {
            if (msg.role === 'onboarding') {
              return (
                <div key={idx} className="flex flex-col items-start space-y-3">
                  {/* Onboarding message bubble */}
                  <div className="p-4 rounded-lg bg-white/5 border border-white/10 rounded-tl-none max-w-[95%]">
                    {/* Progress indicator */}
                    {msg.progress && msg.progress.total > 0 && (
                      <div className="mb-3">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">Setup</span>
                          <span className="text-[9px] text-slate-600">
                            {msg.progress.current} / {msg.progress.total}
                          </span>
                        </div>
                        <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary rounded-full transition-all duration-500"
                            style={{ width: `${(msg.progress.current / msg.progress.total) * 100}%` }}
                          />
                        </div>
                      </div>
                    )}
                    {/* Message text */}
                    <div className="text-[11px] text-slate-200 leading-relaxed whitespace-pre-line">
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
                          className="w-full text-left px-4 py-3 rounded-lg border border-white/10 bg-white/5
                                     hover:bg-primary/10 hover:border-primary/30
                                     active:scale-[0.98] transition-all group"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-slate-200 group-hover:text-primary transition-colors">
                              {btn.label}
                            </span>
                            <span className="material-icons text-sm text-slate-600 group-hover:text-primary/60 transition-colors">
                              arrow_forward
                            </span>
                          </div>
                          {btn.description && (
                            <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">
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
                    ? 'bg-primary text-white rounded-tr-none'
                    : 'bg-white/10 text-slate-200 rounded-tl-none'
                }`}>
                  <span className="whitespace-pre-line">{msg.content}</span>
                </div>
              </div>
            );
          })}

          {isTyping && (
            <div className="flex items-start">
              <div className="p-3 rounded-lg bg-white/10 text-slate-400 rounded-tl-none text-[11px] flex gap-1">
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
          <div className="flex items-center bg-black/40 border rounded-lg p-1 transition-colors border-white/10 focus-within:border-primary/50">
            <input
              type="text"
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSendChat()}
              placeholder="Type a message..."
              className="flex-1 bg-transparent border-none text-xs text-slate-200 px-3 py-2 focus:ring-0 placeholder:text-slate-600"
            />
            <button
              onClick={handleSendChat}
              disabled={isTyping || !chatInput.trim()}
              className="p-1.5 text-primary hover:bg-primary/20 rounded-md transition-colors disabled:opacity-50"
            >
              <span className="material-icons text-sm">send</span>
            </button>
          </div>
        </div>
      </div>

      {/* Move History */}
      <div className="h-1/3 flex flex-col overflow-hidden bg-black/10 shrink-0">
        <div className="px-5 py-3 border-b border-white/5 flex items-center justify-between">
          <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Move History</h4>
          <span className="text-[9px] text-slate-600">{moveHistory.length} Total</span>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-2 move-history-scroll">
          <div className="text-[11px] font-mono">
            {moveHistory.length === 0 ? (
              <div className="text-slate-500 py-2 text-center text-xs">No moves yet</div>
            ) : (
              moveHistory.map((move, index) => {
                const pieceInfo = PIECE_INFO[move.piece];
                const moveNum = Math.floor(index / 2) + 1;
                const isRed = index % 2 === 0;
                return (
                  <div key={index} className="grid grid-cols-12 gap-1 py-1.5 border-b border-white/5">
                    <div className={`col-span-2 ${isRed ? 'text-primary font-bold' : 'text-slate-600'}`}>{moveNum}.</div>
                    <div className="col-span-5 text-slate-400">
                      {move.from}-{move.to} <span className="text-[8px] opacity-40 ml-1">({pieceInfo?.char || '?'})</span>
                    </div>
                    <div className="col-span-5"></div>
                  </div>
                );
              })
            )}
            {aiThinking && (
              <div className="grid grid-cols-12 gap-1 py-1.5 border-b border-white/5 bg-primary/5 -mx-5 px-5">
                <div className="col-span-2 text-primary font-bold">...</div>
                <div className="col-span-10 text-slate-500 italic">Thinking...</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});

export default ChatPanel;
