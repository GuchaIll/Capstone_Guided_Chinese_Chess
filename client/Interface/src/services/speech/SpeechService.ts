/**
 * SpeechService wraps browser SpeechSynthesis (TTS) and
 * SpeechRecognition (STT) for the chess coaching interface.
 */
export class SpeechService {
  private synth: SpeechSynthesis;
  private recognition: SpeechRecognition | null = null;
  private _isSpeaking = false;
  private _voices: SpeechSynthesisVoice[] = [];
  private _selectedVoiceURI: string | null = null;
  private _rate = 1.0;
  private _pitch = 1.0;

  constructor() {
    this.synth = window.speechSynthesis;
    this._loadVoices();
    // Voices load asynchronously in some browsers
    this.synth.addEventListener('voiceschanged', () => this._loadVoices());

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
    this._voices = this.synth.getVoices();
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
  speak(text: string): Promise<void> {
    return new Promise((resolve) => {
      if (!text.trim()) { resolve(); return; }
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

  /** Stop any current speech. */
  stop(): void {
    this.synth.cancel();
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
