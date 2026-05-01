/**
 * SpeechService wraps browser SpeechSynthesis (TTS) and
 * SpeechRecognition (STT) for the chess coaching interface.
 */
export class SpeechService {
  private synth: SpeechSynthesis | null;
  private recognition: SpeechRecognition | null = null;
  private audio: HTMLAudioElement | null = null;
  private _isSpeaking = false;
  private _voices: SpeechSynthesisVoice[] = [];
  private _selectedVoiceURI: string | null = null;
  private _rate = 1.0;
  private _pitch = 1.0;
  private readonly ttsProvider: string;
  private readonly fallbackProvider: string;

  constructor() {
    this.ttsProvider = process.env.NEXT_PUBLIC_TTS_PROVIDER ?? 'browser';
    this.fallbackProvider = process.env.NEXT_PUBLIC_TTS_FALLBACK_PROVIDER ?? 'browser';
    this.synth = 'speechSynthesis' in window ? window.speechSynthesis : null;
    if (this.synth) {
      this._loadVoices();
      // Voices load asynchronously in some browsers
      this.synth.addEventListener('voiceschanged', () => this._loadVoices());
    }

    const SpeechRecognitionCtor =
      (window as unknown as Record<string, unknown>).SpeechRecognition ??
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition;

    if (SpeechRecognitionCtor) {
      this.recognition = new (SpeechRecognitionCtor as new () => SpeechRecognition)();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-US';
    }
  }

  private _loadVoices(): void {
    this._voices = this.synth?.getVoices() ?? [];
  }

  private async speakWithProvider(text: string, provider: string): Promise<void> {
    if (provider === 'fish_modal') {
      await this.speakWithFishModal(text);
      return;
    }
    await this.speakWithBrowser(text);
  }

  private speakWithBrowser(text: string): Promise<void> {
    return new Promise((resolve) => {
      if (!text.trim() || !this.synth) { resolve(); return; }
      this.synth.cancel();

      const utter = new SpeechSynthesisUtterance(text);
      utter.rate = this._rate;
      utter.pitch = this._pitch;

      if (this._selectedVoiceURI) {
        const voice = this._voices.find((v) => v.voiceURI === this._selectedVoiceURI);
        if (voice) utter.voice = voice;
      }

      this._isSpeaking = true;
      utter.onend = () => { this._isSpeaking = false; resolve(); };
      utter.onerror = () => { this._isSpeaking = false; resolve(); };

      this.synth.speak(utter);
    });
  }

  private async speakWithFishModal(text: string): Promise<void> {
    const response = await fetch('/dashboard/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      throw new Error(`fish tts failed: ${response.status}`);
    }

    const audioBlob = await response.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    this.audio?.pause();
    this.audio = new Audio(audioUrl);

    this._isSpeaking = true;
    await new Promise<void>((resolve) => {
      const audio = this.audio!;
      const cleanup = () => {
        audio.onended = null;
        audio.onerror = null;
        this._isSpeaking = false;
        URL.revokeObjectURL(audioUrl);
        resolve();
      };
      audio.onended = cleanup;
      audio.onerror = cleanup;
      void audio.play().catch(cleanup);
    });
  }

  get voices(): SpeechSynthesisVoice[] {
    return this._voices;
  }

  get isSpeaking(): boolean {
    return this._isSpeaking;
  }

  set selectedVoiceURI(uri: string | null) {
    this._selectedVoiceURI = uri;
  }

  set rate(r: number) {
    this._rate = Math.max(0.1, Math.min(10, r));
  }

  set pitch(p: number) {
    this._pitch = Math.max(0, Math.min(2, p));
  }

  /** Speak text aloud using Web Speech API. */
  async speak(text: string): Promise<void> {
    if (!text.trim()) return;
    try {
      await this.speakWithProvider(text, this.ttsProvider);
    } catch (_error) {
      if (this.fallbackProvider !== this.ttsProvider) {
        await this.speakWithProvider(text, this.fallbackProvider);
      }
    }
  }

  /** Stop any current speech. */
  stop(): void {
    this.synth?.cancel();
    this.audio?.pause();
    this._isSpeaking = false;
  }

  /** Start listening for speech, returns transcript. */
  listen(): Promise<string> {
    return new Promise((resolve, reject) => {
      if (!this.recognition) {
        reject(new Error('SpeechRecognition not supported'));
        return;
      }
      let finalTranscript = '';

      this.recognition.onresult = (event: SpeechRecognitionEvent) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          }
        }
      };

      this.recognition.onend = () => resolve(finalTranscript.trim());
      this.recognition.onerror = (e: SpeechRecognitionErrorEvent) => reject(e);
      this.recognition.start();
    });
  }

  /** Stop listening. */
  stopListening(): void {
    this.recognition?.stop();
  }

  /** Cleanup. */
  destroy(): void {
    this.stop();
    this.stopListening();
  }
}
