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
  const recognitionRunningRef = useRef(false);
  // Mutex preventing concurrent starts (e.g. StrictMode mount → cleanup → mount
  // firing two startWakeWordDetection() calls before either's getUserMedia
  // resolves, which would create two recognition instances fighting for the mic).
  const startInProgressRef = useRef(false);
  // One-shot mic permission probe — after the first grant we trust the browser
  // and let SpeechRecognition manage its own audio session. Re-probing on every
  // restart causes the browser's "in use" indicator to flash on/off.
  const permissionGrantedRef = useRef(false);
  // Restart backoff: cap consecutive auto-restart attempts so a stuck mic or
  // permanent error doesn't loop forever.
  const consecutiveRestartFailuresRef = useRef(0);
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

  const startWakeWordDetection = useCallback(async () => {
    // Already running? Done. Already starting? Bail — concurrent starts are
    // the StrictMode double-mount foot-gun we are protecting against here.
    if (activeRef.current && recognitionRunningRef.current) return;
    if (startInProgressRef.current) return;
    startInProgressRef.current = true;

    // Mark active SYNCHRONOUSLY so a cleanup that fires while we are awaiting
    // getUserMedia can flip activeRef back to false; we then abort below.
    activeRef.current = true;

    try {
      // Probe permission once per session. After it is granted, skip the probe
      // — SpeechRecognition.start() opens its own audio session and re-probing
      // here just makes the browser's mic indicator blink on every restart.
      if (!permissionGrantedRef.current && navigator.mediaDevices?.getUserMedia) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          stream.getTracks().forEach((track) => track.stop());
          permissionGrantedRef.current = true;
        } catch {
          setError('Microphone permission denied or unavailable');
          setWakeState('idle');
          activeRef.current = false;
          return;
        }
      }

      // Cleanup may have run while we were awaiting permission — abort.
      if (!activeRef.current) return;

      // Dispose any leftover instance before creating a new one. Avoids the
      // "two recognitions running at once" state that breaks transcription.
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch { /* already stopped */ }
        recognitionRef.current = null;
      }

      const rec = createRecognition();
      if (!rec) {
        setError('Speech recognition not supported in this browser');
        activeRef.current = false;
        return;
      }

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
      recognitionRunningRef.current = false;
      // Auto-restart if still active.
      // IMPORTANT: use recognitionRef.current (not the captured `rec`) so the
      // restart always targets the live instance, even after fresh replacements.
      if (!activeRef.current) return;
      // Bail out after repeated failures so a stuck mic doesn't loop forever.
      if (consecutiveRestartFailuresRef.current >= 5) {
        console.error('[VoiceCommands] Giving up after 5 consecutive restart failures');
        setError('Recognition kept failing — click the mic to retry');
        activeRef.current = false;
        setWakeState('idle');
        return;
      }
      // Deduplicate: clear any existing restart timer before scheduling a new one
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
      // 300ms backoff (vs the previous 100ms) — shorter intervals just open
      // the mic stream again and again, which is what was causing the
      // browser's mic indicator to flash on/off.
      restartTimerRef.current = window.setTimeout(() => {
        restartTimerRef.current = null;
        if (!activeRef.current) return;
        const target = recognitionRef.current;
        if (!target) return;
        try {
          target.start();
          recognitionRunningRef.current = true;
          consecutiveRestartFailuresRef.current = 0;
        } catch {
          consecutiveRestartFailuresRef.current += 1;
          // Instance is permanently dead — create a fresh replacement
          const fresh = createRecognition();
          if (fresh) {
            // Assign the same handlers; onend/onresult/onerror close over
            // recognitionRef, so future restarts will correctly use `fresh`.
            fresh.onresult = target.onresult;
            fresh.onend = target.onend;
            fresh.onerror = target.onerror;
            recognitionRef.current = fresh;
            try {
              fresh.start();
              recognitionRunningRef.current = true;
              consecutiveRestartFailuresRef.current = 0;
            } catch {
              console.error('[VoiceCommands] Failed to restart fresh recognition');
              setWakeState('idle');
              activeRef.current = false;
            }
          }
        }
      }, 300);
    };

    rec.onerror = (e: SpeechRecognitionErrorEvent) => {
      // `no-speech` is normal during silence; `aborted` happens when we call
      // .stop() ourselves. Log at debug level only — surfacing them as errors
      // would constantly flash the user-visible error overlay.
      if (e.error === 'no-speech' || e.error === 'aborted') {
        console.debug('[VoiceCommands] Benign recognition event:', e.error);
        return;
      }
      // Permission-class errors are terminal — stop trying.
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture') {
        activeRef.current = false;
        recognitionRunningRef.current = false;
        permissionGrantedRef.current = false; // re-probe on next start
        setWakeState('idle');
      }
      console.error('[VoiceCommands] Recognition error:', e.error, e.message ?? '');
      setError(e.message || e.error);
    };

      try {
        rec.start();
        recognitionRunningRef.current = true;
        consecutiveRestartFailuresRef.current = 0;
        console.info('[VoiceCommands] Recognition started — say "Kibo" to activate');
      } catch (e) {
        console.error('[VoiceCommands] Failed to start recognition:', e);
        setError('Failed to start speech recognition');
        activeRef.current = false;
      }
    } finally {
      startInProgressRef.current = false;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createRecognition, clearTimers, onChatMessage, setWakeState]);

  const stopWakeWordDetection = useCallback(() => {
    activeRef.current = false;
    recognitionRunningRef.current = false;
    // If a start() is mid-await (StrictMode cleanup case), the in-progress
    // start will see activeRef === false and abort cleanly. The mutex itself
    // is reset by the start's finally block — but in case we are stopping
    // before a start ever fired, clear it here too.
    startInProgressRef.current = false;
    consecutiveRestartFailuresRef.current = 0;
    clearTimers();
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
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
      recognitionRunningRef.current = false;
      clearTimers();
      recognitionRef.current?.stop();
    };
  }, [clearTimers]);

  return {
    isListening: wakeWordState === 'listening' || wakeWordState === 'awake' || wakeWordState === 'processing',
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
