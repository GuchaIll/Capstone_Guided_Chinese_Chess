/**
 * VoiceControl – UI components for voice interaction.
 *
 * - VoiceButton: toggle wake-word listening
 * - VoiceFeedback: shows transcript / state indicator
 * - VoiceSettings: configure speech voice, rate, pitch
 */
import { useCallback } from 'react';
import type { SpeechService } from '../services/speech/SpeechService';

// ──────────────────────────────────────────────
// VoiceButton
// ──────────────────────────────────────────────

interface VoiceButtonProps {
  isListening: boolean;
  isSpeaking: boolean;
  wakeWordState: 'idle' | 'listening' | 'awake' | 'processing';
  onToggle: () => void;
}

export function VoiceButton({ isListening, isSpeaking, wakeWordState, onToggle }: VoiceButtonProps) {
  const stateColor =
    wakeWordState === 'awake'
      ? 'bg-green-500 border-green-400'
      : isListening
        ? 'bg-primary border-primary/60 animate-pulse'
        : isSpeaking
          ? 'bg-amber-500 border-amber-400'
          : 'bg-slate-700 border-slate-600';

  const title =
    wakeWordState === 'idle'
      ? 'Start voice (say "Kibo")'
      : wakeWordState === 'listening'
        ? 'Listening… click to force-activate'
        : 'Kibo is active — click to stop';

  return (
    <button
      onClick={onToggle}
      className={`w-9 h-9 rounded-lg flex items-center justify-center border transition-all active:scale-95 ${stateColor}`}
      title={title}
    >
      <span className="material-icons text-sm text-white">
        {isListening ? 'mic' : 'mic_off'}
      </span>
    </button>
  );
}

// ──────────────────────────────────────────────
// VoiceFeedback  (full-screen overlay popup)
// ──────────────────────────────────────────────

interface VoiceFeedbackProps {
  isListening: boolean;
  isSpeaking: boolean;
  isAwake: boolean;
  wakeWordState: 'idle' | 'listening' | 'awake' | 'processing';
  transcript: string;
  interimTranscript: string;
  error: string | null;
}

export function VoiceFeedback({
  isAwake,
  wakeWordState,
  transcript,
  interimTranscript,
  error,
}: VoiceFeedbackProps) {
  // Show the overlay when awake or processing (i.e. after wakeword detected)
  const visible = isAwake || wakeWordState === 'processing';

  if (!visible && !error) return null;

  if (error) {
    return (
      <div
        className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50
                   bg-red-950/95 border border-red-500/50 rounded-2xl
                   px-6 py-4 shadow-2xl flex items-center gap-3
                   animate-in fade-in slide-in-from-bottom-4 duration-200"
      >
        <span className="material-icons text-red-400 text-lg">mic_off</span>
        <span className="text-red-200 text-xs font-medium">{error}</span>
      </div>
    );
  }

  const displayText = interimTranscript || transcript;
  const isProcessing = wakeWordState === 'processing';

  return (
    <div
      className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50
                 bg-slate-900/95 backdrop-blur-md border border-white/10
                 rounded-2xl px-6 py-4 shadow-2xl min-w-[280px] max-w-[480px]
                 flex flex-col items-center gap-3
                 animate-in fade-in slide-in-from-bottom-4 duration-200"
    >
      {/* Header row: animated mic + label */}
      <div className="flex items-center gap-3">
        <span
          className={`w-8 h-8 rounded-full flex items-center justify-center
                      ${isProcessing
                        ? 'bg-amber-500/20'
                        : 'bg-green-500/20 animate-pulse'}`}
        >
          <span
            className={`material-icons text-base
                        ${isProcessing ? 'text-amber-400' : 'text-green-400'}`}
          >
            {isProcessing ? 'send' : 'mic'}
          </span>
        </span>
        <span
          className={`text-sm font-bold tracking-wide
                      ${isProcessing ? 'text-amber-300' : 'text-green-300'}`}
        >
          {isProcessing ? 'Sending to Kibo…' : 'Kibo is listening'}
        </span>
      </div>

      {/* Live transcript */}
      {displayText ? (
        <p className="text-slate-300 text-sm text-center leading-relaxed">
          {displayText}
        </p>
      ) : (
        !isProcessing && (
          <p className="text-slate-500 text-xs text-center italic">
            Speak now…
          </p>
        )
      )}

      {/* Sound-wave animation bars (purely decorative) */}
      {!isProcessing && (
        <div className="flex items-end gap-[3px] h-4">
          {[0.6, 1, 0.8, 1, 0.6, 0.9, 0.7].map((h, i) => (
            <span
              key={i}
              className="w-[3px] rounded-full bg-green-400 opacity-70"
              style={{
                height: `${h * 100}%`,
                animationName: 'voiceBar',
                animationDuration: `${0.4 + i * 0.07}s`,
                animationTimingFunction: 'ease-in-out',
                animationIterationCount: 'infinite',
                animationDirection: 'alternate',
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────
// VoiceSettings
// ──────────────────────────────────────────────

interface VoiceSettingsProps {
  speechService: SpeechService;
  isOpen: boolean;
  onClose: () => void;
}

export function VoiceSettings({ speechService, isOpen, onClose }: VoiceSettingsProps) {
  const handleVoiceChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      speechService.selectedVoiceURI = e.target.value || null;
    },
    [speechService],
  );

  const handleRateChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      speechService.rate = parseFloat(e.target.value);
    },
    [speechService],
  );

  const handlePitchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      speechService.pitch = parseFloat(e.target.value);
    },
    [speechService],
  );

  if (!isOpen) return null;

  const voices = speechService.voices;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-slate-900 border border-white/10 rounded-xl p-6 w-80 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-bold text-white mb-4 uppercase tracking-wider">Voice Settings</h3>

        <label className="block text-[10px] text-slate-400 uppercase mb-1">Voice</label>
        <select
          className="w-full bg-slate-800 text-white text-xs p-2 rounded mb-3 border border-white/10"
          onChange={handleVoiceChange}
          defaultValue=""
        >
          <option value="">System default</option>
          {voices.map((v) => (
            <option key={v.voiceURI} value={v.voiceURI}>
              {v.name} ({v.lang})
            </option>
          ))}
        </select>

        <label className="block text-[10px] text-slate-400 uppercase mb-1">Rate</label>
        <input
          type="range"
          min="0.5"
          max="2"
          step="0.1"
          defaultValue="1"
          onChange={handleRateChange}
          className="w-full mb-3"
        />

        <label className="block text-[10px] text-slate-400 uppercase mb-1">Pitch</label>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          defaultValue="1"
          onChange={handlePitchChange}
          className="w-full mb-4"
        />

        <button
          onClick={() => speechService.speak('Hello! I am Kibo, your chess coach.')}
          className="w-full py-2 bg-primary text-white text-xs rounded-lg hover:bg-primary/80 transition-all mb-2"
        >
          Test Voice
        </button>
        <button
          onClick={onClose}
          className="w-full py-2 bg-slate-800 text-slate-300 text-xs rounded-lg hover:bg-slate-700 transition-all"
        >
          Close
        </button>
      </div>
    </div>
  );
}
