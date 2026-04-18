/**
 * useChessVoiceCommands – Wake-word detection for "Kibo".
 *
 * Wakeword: "Kibo" and common STT mis-transcriptions.
 *
 * Flow:
 *   1. SpeechRecognition runs continuously, always scanning for the wakeword.
 *   2. On ANY result (interim or final) that contains the wakeword, immediately
 *      transition to 'awake' and surface the live transcript.
 *   3. The text AFTER the wakeword on the same utterance is sent as a chat
 *      message once the result is final.
 *   4. If the wakeword appeared alone (no follow-up text), wait AWAKE_TIMEOUT
 *      for the next final result and send that as the message.
 *   5. Returns to 'listening' automatically after a message is sent or timeout.
 *   6. Clicking the mic button while listening forces 'awake' mode (push-to-talk).
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import type { SpeechService } from '../services/speech/SpeechService';

// Wakeword regex — "kibo" and broad phonetic mis-transcriptions from Chrome STT
// Common mishearings: "key bo", "cabo", "gibo", "kebo", "kibou", "keebo", "Kylo", "Kyber"
const WAKEWORD_PATTERN =
  /\b(kibo|kibble|kimbo|kiko|kido|kebo|kibou|keebo|cabo|gibo|gibow|kybo|keybo|kiboo)\b/i;

/** Strip the wakeword and anything before it from a transcript. */
function stripWakeword(text: string): string {
  return text.replace(WAKEWORD_PATTERN, '').trim();
}

/** Check if text contains the wakeword. */
function hasWakeword(text: string): boolean {
  return WAKEWORD_PATTERN.test(text);
}

type WakeWordState = 'idle' | 'listening' | 'awake' | 'processing';

interface VoiceCommandsReturn {
  isListening: boolean;
  isSpeaking: boolean;
  isAwake: boolean;
  wakeWordState: WakeWordState;
  transcript: string;
  interimTranscript: string;
  error: string | null;
  startWakeWordDetection: () => void;
  stopWakeWordDetection: () => void;
  /** Force 'awake' state immediately (push-to-talk fallback). */
  forceAwake: () => void;
}

export function useChessVoiceCommands(
  speechService: SpeechService,
  _onChessMove?: (move: string) => void,
  onChatMessage?: (message: string) => void,
): VoiceCommandsReturn {
  const [wakeWordState, setWakeWordState] = useState<WakeWordState>('idle');
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const awakeTimerRef = useRef<number | null>(null);
  const activeRef = useRef(false);
  // Use a ref so onresult closure always reads the current state without stale capture
  const wakeWordStateRef = useRef<WakeWordState>('idle');

  const setWakeState = useCallback((s: WakeWordState) => {
    wakeWordStateRef.current = s;
    setWakeWordState(s);
  }, []);

  // Auto-return to listening after awake timeout (5s)
  const AWAKE_TIMEOUT = 5000;

  const clearTimers = useCallback(() => {
    if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
    if (awakeTimerRef.current) clearTimeout(awakeTimerRef.current);
    restartTimerRef.current = null;
    awakeTimerRef.current = null;
  }, []);

  const createRecognition = useCallback((): SpeechRecognition | null => {
    const SpeechRecognitionCtor =
      (window as unknown as Record<string, unknown>).SpeechRecognition ??
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition;

    if (!SpeechRecognitionCtor) return null;

    const rec = new (SpeechRecognitionCtor as new () => SpeechRecognition)();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';
    return rec;
  }, []);

  const startWakeWordDetection = useCallback(() => {
    if (activeRef.current) return;

    const rec = createRecognition();
    if (!rec) {
      setError('Speech recognition not supported in this browser');
      return;
    }

    activeRef.current = true;
    recognitionRef.current = rec;
    setWakeState('listening');
    setError(null);

    rec.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      let finalText = '';

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += t;
        } else {
          interim += t;
        }
      }

      // Always show what's being heard while awake
      if (wakeWordStateRef.current === 'awake' || wakeWordStateRef.current === 'processing') {
        setInterimTranscript(interim);
      }

      const currentState = wakeWordStateRef.current;

      // ── PRIORITY 1: Check for wakeword in interim (fastest response) ──
      if (hasWakeword(interim)) {
        clearTimers();
        setWakeState('awake');
        // Show the live transcript (strip wakeword for display)
        setInterimTranscript(stripWakeword(interim) || interim);
        // Set awake timeout — will be cancelled if final arrives first
        awakeTimerRef.current = window.setTimeout(() => {
          setWakeState('listening');
          setInterimTranscript('');
          setTranscript('');
        }, AWAKE_TIMEOUT);
        return;
      }

      // ── PRIORITY 2: Check for wakeword in final result ──
      if (hasWakeword(finalText)) {
        clearTimers();
        const message = stripWakeword(finalText);
        if (message) {
          // Wakeword + message in the same utterance → send immediately
          setTranscript(message);
          setInterimTranscript('');
          setWakeState('processing');
          onChatMessage?.(message);
          awakeTimerRef.current = window.setTimeout(() => {
            setWakeState('listening');
            setTranscript('');
          }, 2000);
        } else {
          // Wakeword only → stay awake, wait for follow-up utterance
          setWakeState('awake');
          setInterimTranscript('');
          awakeTimerRef.current = window.setTimeout(() => {
            setWakeState('listening');
            setInterimTranscript('');
            setTranscript('');
          }, AWAKE_TIMEOUT);
        }
        return;
      }

      // ── PRIORITY 3: Already awake — treat next final result as the message ──
      if (currentState === 'awake' && finalText.trim()) {
        clearTimers();
        const message = finalText.trim();
        setTranscript(message);
        setInterimTranscript('');
        setWakeState('processing');
        onChatMessage?.(message);
        awakeTimerRef.current = window.setTimeout(() => {
          setWakeState('listening');
          setTranscript('');
        }, 2000);
      }
    };

    rec.onend = () => {
      // Auto-restart if still active.
      // IMPORTANT: use recognitionRef.current (not the captured `rec`) so the
      // restart always targets the live instance, even after fresh replacements.
      if (!activeRef.current) return;
      // Deduplicate: clear any existing restart timer before scheduling a new one
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
      restartTimerRef.current = window.setTimeout(() => {
        restartTimerRef.current = null;
        if (!activeRef.current) return;
        const target = recognitionRef.current;
        if (!target) return;
        try {
          target.start();
        } catch {
          // Instance is permanently dead — create a fresh replacement
          const fresh = createRecognition();
          if (fresh) {
            // Assign the same handlers; onend/onresult/onerror close over
            // recognitionRef, so future restarts will correctly use `fresh`.
            fresh.onresult = target.onresult;
            fresh.onend = target.onend;
            fresh.onerror = target.onerror;
            recognitionRef.current = fresh;
            try { fresh.start(); } catch {
              console.error('[VoiceCommands] Failed to restart fresh recognition');
              setWakeState('idle');
              activeRef.current = false;
            }
          }
        }
      }, 100);
    };

    rec.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      console.error('[VoiceCommands] Recognition error:', e.error, e.message ?? '');
      setError(e.error);
    };

    try {
      rec.start();
      console.info('[VoiceCommands] Recognition started — say "Kibo" to activate');
    } catch (e) {
      console.error('[VoiceCommands] Failed to start recognition:', e);
      setError('Failed to start speech recognition');
      activeRef.current = false;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createRecognition, clearTimers, onChatMessage, setWakeState]);

  const stopWakeWordDetection = useCallback(() => {
    activeRef.current = false;
    clearTimers();
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setWakeState('idle');
    setTranscript('');
    setInterimTranscript('');
    setError(null);
  }, [clearTimers, setWakeState]);

  /**
   * Immediately activate 'awake' mode without requiring the wakeword.
   * Useful as a push-to-talk fallback when STT doesn't catch "Kibo".
   */
  const forceAwake = useCallback(() => {
    if (!activeRef.current) {
      startWakeWordDetection();
    }
    clearTimers();
    setWakeState('awake');
    setInterimTranscript('');
    setTranscript('');
    awakeTimerRef.current = window.setTimeout(() => {
      setWakeState('listening');
      setInterimTranscript('');
      setTranscript('');
    }, 10_000); // 10s push-to-talk window
  }, [clearTimers, setWakeState, startWakeWordDetection]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      activeRef.current = false;
      clearTimers();
      recognitionRef.current?.stop();
    };
  }, [clearTimers]);

  return {
    isListening: wakeWordState === 'listening' || wakeWordState === 'awake',
    isSpeaking: speechService.isSpeaking,
    isAwake: wakeWordState === 'awake',
    wakeWordState,
    transcript,
    interimTranscript,
    error,
    startWakeWordDetection,
    stopWakeWordDetection,
    forceAwake,
  };
}
