import { describe, expect, it } from 'vitest';
import { pictogramSrc } from './pictogram';
import { signalPair, signalPhrase } from './signals';

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

  it('names a squeeze an eye movement even when Muse Spark files it under eyebrows', () => {
    // from a live calibration: both movements came back with body_part "eyebrows"
    expect(
      signalPhrase({
        body_part: 'eyebrows',
        motion: 'raises both eyebrows upward for about one second',
        description: '',
      }),
    ).toEqual({ key: 'signal.eyebrows_up' });
    expect(
      signalPhrase({
        body_part: 'eyebrows',
        motion: 'lowers and draws brows together while squeezing eyes shut',
        description: '',
      }),
    ).toEqual({ key: 'signal.eyes_shut' });
  });

  it('falls back to the described motion', () => {
    expect(signalPhrase({ body_part: 'foot', motion: 'taps the toes', description: '' })).toEqual({
      text: 'Taps the toes',
    });
    expect(signalPhrase(undefined)).toBeNull();
  });
});

describe('signalPair', () => {
  it('never gives YES and NO the same name', () => {
    const pair = signalPair(
      { body_part: 'eyebrows', motion: 'raises both eyebrows quickly', description: '' },
      { body_part: 'eyebrows', motion: 'raises both eyebrows slowly twice', description: '' },
    );
    expect(pair).toEqual({
      yes: { text: 'Raises both eyebrows quickly' },
      no: { text: 'Raises both eyebrows slowly twice' },
    });
  });

  it('hides the legend when even the described movements match', () => {
    const spec = { body_part: 'eyebrows', motion: 'raises both eyebrows', description: '' };
    expect(signalPair(spec, spec)).toBeNull();
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
