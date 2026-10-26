import { describe, expect, it } from 'vitest';
import { pictogramSrc } from './pictogram';
import { signalPhrase } from './signals';

describe('signalPhrase', () => {
  it('maps calibrated movements to short patient-facing phrases', () => {
    expect(
      signalPhrase({ body_part: 'eyebrows', motion: 'raises both eyebrows', description: '' }),
    ).toEqual({
      key: 'signal.eyebrows_up',
    });
    expect(
      signalPhrase({ body_part: 'eyes', motion: 'closes both eyes tightly', description: '' }),
    ).toEqual({
      key: 'signal.eyes_shut',
    });
    expect(
      signalPhrase({ body_part: 'eyes', motion: 'two quick blinks', description: '' }),
    ).toEqual({
      key: 'signal.two_blinks',
    });
  });

  it('falls back to the described motion', () => {
    expect(signalPhrase({ body_part: 'foot', motion: 'taps the toes', description: '' })).toEqual({
      text: 'Taps the toes',
    });
    expect(signalPhrase(undefined)).toBeNull();
  });
});

describe('pictogramSrc', () => {
  it('uses the part before the colon', () => {
    expect(pictogramSrc('see_person:aisyah')).toBe('/pictograms/see_person.webp');
    expect(pictogramSrc('thirst')).toBe('/pictograms/thirst.webp');
  });

  it('returns null for spelled messages and unknown ids', () => {
    expect(pictogramSrc(null)).toBeNull();
    expect(pictogramSrc('pain_loc:chest')).toBeNull();
    expect(pictogramSrc('spelled:KUCING')).toBeNull();
  });
});
