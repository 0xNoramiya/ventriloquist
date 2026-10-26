import type { Lang } from '../api/types';

export type SpeakOutcome = 'spoken' | 'text-only' | 'error' | 'timeout' | 'cancelled';

export interface SpeakHandle {
  done: Promise<SpeakOutcome>;
  cancel: () => void;
}

const BCP47: Record<Lang, string> = { en: 'en-US', id: 'id-ID' };

/** Time to read a line on screen when no voice can say it. */
export function readingDelayMs(text: string): number {
  return Math.min(4000, Math.max(1500, 900 + text.length * 45));
}

function synth(): SpeechSynthesis | null {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
    ? window.speechSynthesis
    : null;
}

async function loadVoices(s: SpeechSynthesis, waitMs = 700): Promise<SpeechSynthesisVoice[]> {
  const now = s.getVoices();
  if (now.length) return now;
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(s.getVoices()), waitMs);
    s.addEventListener(
      'voiceschanged',
      () => {
        window.clearTimeout(timer);
        resolve(s.getVoices());
      },
      { once: true },
    );
  });
}

export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: Lang,
): SpeechSynthesisVoice | undefined {
  const tag = BCP47[lang].toLowerCase();
  const prefix = lang.toLowerCase();
  const norm = (v: SpeechSynthesisVoice) => v.lang.replace('_', '-').toLowerCase();
  return (
    voices.find((v) => norm(v) === tag && v.localService) ??
    voices.find((v) => norm(v) === tag) ??
    voices.find((v) => norm(v).startsWith(prefix))
  );
}

/** Unlock speech on the first user gesture (iOS and Android need one before speaking). */
export function unlockSpeech(): void {
  const s = synth();
  if (!s) return;
  try {
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0;
    s.speak(u);
  } catch {
    // speech is optional: the screen shows the text either way
  }
}

/**
 * Speak a line with the Web Speech API. Always settles: if there is no voice for the language,
 * or speech fails or hangs, it waits a reading delay so the patient can read the text instead.
 */
export function speak(text: string, lang: Lang, rate = 0.9): SpeakHandle {
  let cancelled = false;
  let timer: number | undefined;
  let finish: (o: SpeakOutcome) => void = () => {};
  const s = synth();

  const done = new Promise<SpeakOutcome>((resolve) => {
    let settled = false;
    finish = (o) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      resolve(o);
    };
    const textOnly = (o: SpeakOutcome) => {
      timer = window.setTimeout(() => finish(o), readingDelayMs(text));
    };
    if (!s || !text.trim()) {
      textOnly('text-only');
      return;
    }
    void loadVoices(s).then((voices) => {
      if (cancelled) return;
      const voice = pickVoice(voices, lang);
      if (!voice) {
        textOnly('text-only');
        return;
      }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = BCP47[lang];
      u.voice = voice;
      u.rate = rate;
      u.onend = () => finish('spoken');
      u.onerror = (e) => {
        if (e.error === 'interrupted' || e.error === 'canceled') finish('cancelled');
        else textOnly('error');
      };
      // Some engines never fire onend; never let the conversation hang on speech.
      const budget = (1500 + text.length * 110) / rate + 2500;
      timer = window.setTimeout(() => {
        s.cancel();
        finish('timeout');
      }, budget);
      s.cancel();
      s.speak(u);
    });
  });

  return {
    done,
    cancel: () => {
      cancelled = true;
      s?.cancel();
      finish('cancelled');
    },
  };
}
