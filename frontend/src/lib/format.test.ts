import { describe, expect, it } from 'vitest';
import type { Evidence } from '../api/types';
import { translate, type Key } from '../i18n';
import { evidenceLabel } from './format';

const t = (key: Key, vars?: Record<string, string | number>) => translate('en', key, vars);
const scene: Evidence = { id: 'S1', kind: 'scene', text: 'A family photo', at: '', minutes_ago: 0 };

describe('evidenceLabel', () => {
  it('names the source and how long ago', () => {
    expect(evidenceLabel(t, { ...scene, minutes_ago: 3 })).toBe('Camera scene · 3 min ago');
  });

  it('says when a demo scenario wrote the fact (issue #18)', () => {
    expect(evidenceLabel(t, { ...scene, scripted: true })).toBe('Scenario · Camera scene');
  });
});
