// The app's own chime and alarm as WAV files for the edit: the oscillator calls from
// frontend/src/lib/alarm.ts (same waveforms, frequencies, envelopes and timing), rendered offline in
// Chromium. Keep the numbers in step with alarm.ts.
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const out = fileURLToPath(new URL('media/audio/', import.meta.url));
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();
const sounds = await page.evaluate(async () => {
  const rate = 48000;
  function beep(c, at, freq, dur) {
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
  function tone(c, at, freq, dur, level) {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, at);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(level, at + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    osc.connect(gain).connect(c.destination);
    osc.start(at);
    osc.stop(at + dur + 0.02);
  }
  const recipes = {
    app_chime: [1.2, (c) => {
      tone(c, 0.02, 660, 0.4, 0.16);
      tone(c, 0.27, 880, 0.55, 0.16);
    }],
    app_chime_urgent: [1.3, (c) => {
      tone(c, 0.02, 784, 0.32, 0.3);
      tone(c, 0.24, 988, 0.32, 0.3);
      tone(c, 0.46, 1175, 0.45, 0.3);
    }],
    // startAlarm: a high-low-high cycle every 1.4 s; three cycles
    app_alarm: [4.3, (c) => {
      for (const t of [0.02, 1.42, 2.82]) {
        beep(c, t, 960, 0.22);
        beep(c, t + 0.28, 720, 0.22);
        beep(c, t + 0.56, 960, 0.22);
      }
    }],
  };
  const wav = (buffer) => {
    const data = buffer.getChannelData(0);
    const bytes = new DataView(new ArrayBuffer(44 + data.length * 2));
    const text = (o, s) => [...s].forEach((ch, i) => bytes.setUint8(o + i, ch.charCodeAt(0)));
    text(0, 'RIFF');
    bytes.setUint32(4, 36 + data.length * 2, true);
    text(8, 'WAVEfmt ');
    bytes.setUint32(16, 16, true);
    bytes.setUint16(20, 1, true);
    bytes.setUint16(22, 1, true);
    bytes.setUint32(24, rate, true);
    bytes.setUint32(28, rate * 2, true);
    bytes.setUint16(32, 2, true);
    bytes.setUint16(34, 16, true);
    text(36, 'data');
    bytes.setUint32(40, data.length * 2, true);
    data.forEach((v, i) => bytes.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
    let s = '';
    new Uint8Array(bytes.buffer).forEach((b) => (s += String.fromCharCode(b)));
    return btoa(s);
  };
  const result = {};
  for (const [name, [seconds, draw]] of Object.entries(recipes)) {
    const c = new OfflineAudioContext(1, Math.ceil(seconds * rate), rate);
    draw(c);
    result[name] = wav(await c.startRendering());
  }
  return result;
});
await browser.close();
for (const [name, b64] of Object.entries(sounds)) {
  writeFileSync(`${out}${name}.wav`, Buffer.from(b64, 'base64'));
  console.log(`${name}.wav`);
}
