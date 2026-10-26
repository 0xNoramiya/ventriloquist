// Emergency tone with WebAudio: no audio files, works offline.

let ctx: AudioContext | null = null;

function context(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const Ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  ctx ??= new Ctor();
  return ctx;
}

/** Call from a user gesture so the alarm can sound later without one. */
export function unlockAudio(): void {
  const c = context();
  if (c && c.state === 'suspended') void c.resume();
}

export function audioReady(): boolean {
  return ctx?.state === 'running';
}

function beep(c: AudioContext, at: number, freq: number, dur: number): void {
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = 'square';
  osc.frequency.setValueAtTime(freq, at);
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(0.22, at + 0.02);
  gain.gain.setValueAtTime(0.22, at + dur - 0.04);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  osc.connect(gain).connect(c.destination);
  osc.start(at);
  osc.stop(at + dur + 0.02);
}

/** Repeating high-low alarm until the returned stop function is called. */
export function startAlarm(): () => void {
  const c = context();
  if (!c) return () => {};
  void c.resume();
  const cycle = () => {
    const t = c.currentTime + 0.02;
    beep(c, t, 960, 0.22);
    beep(c, t + 0.28, 720, 0.22);
    beep(c, t + 0.56, 960, 0.22);
  };
  cycle();
  const id = window.setInterval(cycle, 1400);
  return () => window.clearInterval(id);
}
