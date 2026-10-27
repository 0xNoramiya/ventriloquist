import { describe, expect, it } from 'vitest';
import en from './en.json';
import enRaw from './en.json?raw';
import id from './id.json';
import idRaw from './id.json?raw';
import { translate } from './index';

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('i18n', () => {
  it('has every key in both languages', () => {
    expect(Object.keys(id).sort()).toEqual(Object.keys(en).sort());
  });

  it('defines each key once', () => {
    // JSON.parse keeps the last of two equal keys, so a clash only shows up in the source text.
    for (const [lang, raw] of Object.entries({ en: enRaw, id: idRaw })) {
      const keys = [...raw.matchAll(/^\s*"([^"]+)":/gm)].map((m) => m[1]);
      const twice = keys.filter((k, i) => keys.indexOf(k) !== i);
      expect(twice, lang).toEqual([]);
    }
  });

  it('has no empty strings', () => {
    for (const [lang, dict] of Object.entries({ en, id })) {
      for (const [k, v] of Object.entries(dict)) {
        expect(v.trim(), `${lang}:${k}`).not.toBe('');
      }
    }
  });

  it('uses the same placeholders in both languages', () => {
    const idDict = id as Record<string, string>;
    for (const [k, v] of Object.entries(en)) {
      expect(placeholders(idDict[k] ?? ''), k).toEqual(placeholders(v));
    }
  });

  it('fills placeholders and keeps unknown ones', () => {
    expect(translate('en', 'now.questions', { n: 3, max: 10 })).toBe('3 of 10 questions');
    expect(translate('id', 'now.questions', { n: 3, max: 10 })).toBe('3 dari 10 pertanyaan');
    expect(translate('en', 'now.questions', { n: 3 })).toBe('3 of {max} questions');
  });

  it('uses the singular form for one', () => {
    expect(translate('en', 'messages.questions', { n: 1 })).toBe('1 question');
    expect(translate('en', 'messages.questions', { n: 4 })).toBe('4 questions');
    expect(translate('id', 'messages.questions', { n: 1 })).toBe('1 pertanyaan');
  });

  it('never shortens the product name', () => {
    for (const dict of [en, id]) {
      for (const v of Object.values(dict)) expect(v).not.toMatch(/\bVentrilo\b/);
    }
  });

  it('labels confirmed messages the same way everywhere', () => {
    expect(en['message.confirmed_label']).toBe('Message from patient (confirmed)');
  });
});
