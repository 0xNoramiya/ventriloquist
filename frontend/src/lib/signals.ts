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
  if (part.includes('eyebrow')) return { key: 'signal.eyebrows_up' };
  if (motion.includes('long blink')) return { key: 'signal.long_blink' };
  if (motion.includes('two') && motion.includes('blink')) return { key: 'signal.two_blinks' };
  if (part.includes('eye') && /(clos|shut|squeez)/.test(motion)) return { key: 'signal.eyes_shut' };
  if (part.includes('finger') && /(lift|raise)/.test(motion)) return { key: 'signal.finger_lift' };
  if (part.includes('hand') && /(clos|fist)/.test(motion)) return { key: 'signal.hand_close' };
  if (part.includes('head') && motion.includes('nod')) return { key: 'signal.nod' };
  if (part.includes('head') && /(turn|shake|side)/.test(motion))
    return { key: 'signal.head_shake' };
  if (part.includes('mouth') || motion.includes('mouth')) return { key: 'signal.mouth' };
  const text = spec.motion.trim();
  return text ? { text: text.charAt(0).toUpperCase() + text.slice(1) } : null;
}
