import { useCallback, useRef } from "react";

// Synthesise short ink-brush and whoosh sounds via Web Audio API
// so we don't need any external service or audio files.

export const useInkSounds = () => {
  const ctxRef = useRef<AudioContext | null>(null);

  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      ctxRef.current = new AudioContext();
    }
    return ctxRef.current;
  }, []);

  /** Soft brush-on-paper sound (~200 ms) */
  const playBrush = useCallback(() => {
    const ctx = getCtx();
    const duration = 0.22;
    const now = ctx.currentTime;

    // Filtered noise burst to emulate bristle friction
    const bufferSize = Math.floor(ctx.sampleRate * duration);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      // Envelope: quick attack, smooth decay
      const t = i / bufferSize;
      const env = t < 0.08 ? t / 0.08 : Math.pow(1 - (t - 0.08) / 0.92, 2);
      data[i] = (Math.random() * 2 - 1) * env;
    }

    const src = ctx.createBufferSource();
    src.buffer = buffer;

    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 2800;
    bp.Q.value = 0.6;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.09, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

    src.connect(bp).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + duration);
  }, [getCtx]);

  /** Airy whoosh (~300 ms) for turn change */
  const playWhoosh = useCallback(() => {
    const ctx = getCtx();
    const duration = 0.32;
    const now = ctx.currentTime;

    const bufferSize = Math.floor(ctx.sampleRate * duration);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      const t = i / bufferSize;
      // Smooth bell-shaped envelope
      const env = Math.sin(t * Math.PI) * 0.7;
      data[i] = (Math.random() * 2 - 1) * env;
    }

    const src = ctx.createBufferSource();
    src.buffer = buffer;

    // Sweeping bandpass gives the "air" character
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.setValueAtTime(600, now);
    bp.frequency.exponentialRampToValueAtTime(3500, now + duration * 0.6);
    bp.frequency.exponentialRampToValueAtTime(1200, now + duration);
    bp.Q.value = 0.4;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.07, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

    src.connect(bp).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + duration);
  }, [getCtx]);

  /** Crisp tick of bamboo brush tapping ink stone (~80 ms) */
  const playInkTick = useCallback(() => {
    const ctx = getCtx();
    const now = ctx.currentTime;

    // Short percussive click — two high-freq sine pings
    const osc1 = ctx.createOscillator();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(3200, now);
    osc1.frequency.exponentialRampToValueAtTime(1800, now + 0.06);

    const osc2 = ctx.createOscillator();
    osc2.type = "triangle";
    osc2.frequency.setValueAtTime(5500, now);
    osc2.frequency.exponentialRampToValueAtTime(2000, now + 0.04);

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.12, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);
    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.08);
    osc2.stop(now + 0.08);
  }, [getCtx]);

  /** Low sustained hum of wet ink spreading (~600 ms) */
  const playInkHum = useCallback(() => {
    const ctx = getCtx();
    const duration = 0.6;
    const now = ctx.currentTime;

    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.setValueAtTime(110, now);
    osc.frequency.linearRampToValueAtTime(85, now + duration);

    // Add slight noise layer for texture
    const bufferSize = Math.floor(ctx.sampleRate * duration);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      const t = i / bufferSize;
      const env = Math.sin(t * Math.PI) * 0.3;
      data[i] = (Math.random() * 2 - 1) * env;
    }
    const noiseSrc = ctx.createBufferSource();
    noiseSrc.buffer = buffer;
    const noiseBp = ctx.createBiquadFilter();
    noiseBp.type = "lowpass";
    noiseBp.frequency.value = 300;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.04, now);
    gain.gain.linearRampToValueAtTime(0.06, now + duration * 0.3);
    gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

    osc.connect(gain);
    noiseSrc.connect(noiseBp).connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    noiseSrc.start(now);
    osc.stop(now + duration);
    noiseSrc.stop(now + duration);
  }, [getCtx]);

  /** Continuous dry brush scratching across rough paper (~400 ms) */
  const playDryBrush = useCallback(() => {
    const ctx = getCtx();
    const duration = 0.4;
    const now = ctx.currentTime;

    // Filtered noise with rising pitch to simulate speed
    const bufferSize = Math.floor(ctx.sampleRate * duration);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      const t = i / bufferSize;
      // Irregular envelope — scratchy, not smooth
      const env = Math.sin(t * Math.PI) * 0.6 * (1 + Math.sin(t * 47) * 0.3);
      data[i] = (Math.random() * 2 - 1) * env;
    }

    const src = ctx.createBufferSource();
    src.buffer = buffer;

    // Bandpass that rises in frequency (simulating speed)
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.setValueAtTime(1800, now);
    bp.frequency.exponentialRampToValueAtTime(3500, now + duration * 0.7);
    bp.frequency.exponentialRampToValueAtTime(2200, now + duration);
    bp.Q.value = 0.8;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.06, now);
    gain.gain.linearRampToValueAtTime(0.09, now + duration * 0.4);
    gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

    src.connect(bp).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + duration);
  }, [getCtx]);

  return { playBrush, playWhoosh, playInkTick, playInkHum, playDryBrush };
};
