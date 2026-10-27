import type { Key } from '../i18n';
import type { SignalSpec } from '../api/types';

/**
 * Short, patient-facing name of a calibrated movement ("Eyebrows up"), from the calibration
 * description. Returns an i18n key when the movement is a known one, otherwise the raw motion.
 */
export function signalPhrase(spec: SignalSpec | undefined): { key: Key } | { text: string } | null {
  if (!spec) return null;
  const part = spec.body_part.toLowerCase();
  const motion = spec.motion.toLowerCase();
  if (motion.includes('long blink')) return { key: 'signal.long_blink' };
  if (motion.includes('two') && motion.includes('blink')) return { key: 'signal.two_blinks' };
  // before the eyebrow rule: a NO of "draws brows together while squeezing eyes shut" is an eye
  // movement, not eyebrows up ("eyebrows" also contains "eye")
  if (part.includes('eye') && /(clos|shut|squeez)/.test(motion)) return { key: 'signal.eyes_shut' };
  if (part.includes('eyebrow') && /(rais|lift|\bup)/.test(motion)) return { key: 'signal.eyebrows_up' };
  if (part.includes('finger') && /(lift|raise)/.test(motion)) return { key: 'signal.finger_lift' };
  if (part.includes('hand') && /(clos|fist)/.test(motion)) return { key: 'signal.hand_close' };
  if (part.includes('head') && motion.includes('nod')) return { key: 'signal.nod' };
  if (part.includes('head') && /(turn|shake|side)/.test(motion))
    return { key: 'signal.head_shake' };
  if (part.includes('mouth') || motion.includes('mouth')) return { key: 'signal.mouth' };
  const text = spec.motion.trim();
  return text ? { text: text.charAt(0).toUpperCase() + text.slice(1) } : null;
}

type Phrase = NonNullable<ReturnType<typeof signalPhrase>>;

const same = (a: Phrase, b: Phrase) =>
  'key' in a && 'key' in b ? a.key === b.key : 'text' in a && 'text' in b && a.text === b.text;

/**
 * The YES and NO phrases for the patient's legend. A legend that gives both answers the same name
 * would tell the patient one movement means yes and no, so when the short names collide it shows
 * the described movements instead, and nothing at all if those match too.
 */
export function signalPair(
  yes: SignalSpec | undefined,
  no: SignalSpec | undefined,
): { yes: Phrase; no: Phrase } | null {
  const y = signalPhrase(yes);
  const n = signalPhrase(no);
  if (!y || !n || !yes || !no) return null;
  if (!same(y, n)) return { yes: y, no: n };
  const raw = (spec: SignalSpec): Phrase => {
    const text = spec.motion.trim();
    return { text: text.charAt(0).toUpperCase() + text.slice(1) };
  };
  const ry = raw(yes);
  const rn = raw(no);
  return same(ry, rn) ? null : { yes: ry, no: rn };
}
