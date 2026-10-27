import type { Key } from '../i18n';

export type SignalRhythm = 'signal-once' | 'signal-twice' | 'signal-sway';

export interface SignalHalf {
  img: string;
  label: Key;
  rhythm?: SignalRhythm;
}

/** The YES/NO pairs the calibration describer knows (backend mock presets use the same ids). */
export const SIGNAL_PAIRS: { id: string; yes: SignalHalf; no: SignalHalf }[] = [
  {
    id: 'eyebrows',
    yes: { img: 'brows', label: 'pick.brows' },
    no: { img: 'squeeze', label: 'pick.squeeze' },
  },
  {
    id: 'blink',
    yes: { img: 'blink', label: 'pick.long_blink' },
    no: { img: 'blink', label: 'pick.two_blinks', rhythm: 'signal-twice' },
  },
  {
    id: 'finger',
    yes: { img: 'finger', label: 'pick.finger' },
    no: { img: 'fist', label: 'pick.fist' },
  },
  {
    id: 'nod',
    yes: { img: 'nod', label: 'pick.nod' },
    no: { img: 'shake', label: 'pick.shake', rhythm: 'signal-sway' },
  },
];
