import { describe, expect, it } from 'vitest';
import type { Prompt } from '../api/types';
import { speechText } from './promptSpeech';
import { currentWord, GRID_SYMBOLS, groupRanges, isHighlighted, LETTERS } from './spelling';

describe('spelling grid helpers', () => {
  it('has the 26 letters plus SPACE, END and UNDO', () => {
    expect(LETTERS).toHaveLength(26);
    expect(GRID_SYMBOLS).toHaveLength(29);
    expect(GRID_SYMBOLS.slice(-3)).toEqual(['SPACE', 'END', 'UNDO']);
  });

  it('highlights only symbols in the group', () => {
    const group = ['K', 'L', 'UNDO'];
    expect(isHighlighted('K', group)).toBe(true);
    expect(isHighlighted('UNDO', group)).toBe(true);
    expect(isHighlighted('A', group)).toBe(false);
  });

  it('collapses runs into ranges and keeps specials last', () => {
    expect(groupRanges(['L', 'M', 'N', 'O', 'P'])).toEqual(['L–P']);
    expect(groupRanges(['K'])).toEqual(['K']);
    expect(groupRanges(['A', 'B'])).toEqual(['A, B']);
    expect(groupRanges(['UNDO', 'E', 'C', 'D', 'X', 'SPACE'])).toEqual([
      'C–E',
      'X',
      'SPACE',
      'UNDO',
    ]);
    expect(groupRanges([])).toEqual([]);
  });

  it('finds the word being spelled', () => {
    expect(currentWord('KUCING SA')).toBe('SA');
    expect(currentWord('KU')).toBe('KU');
    expect(currentWord('KUCING ')).toBe('');
  });

  it('reads the letter group aloud in the patient language', () => {
    const p: Prompt = {
      id: 'p9',
      kind: 'spelling',
      stage: 'spelling',
      sub: 'letter',
      text: 'Apakah huruf Ibu ada di kelompok ini?',
      text_en: 'Is your letter in this group?',
      question: null,
      group: ['L', 'M', 'N', 'O', 'SPACE'],
      word: null,
      rephrased: false,
    };
    expect(speechText(p, 'id')).toBe('Apakah huruf Ibu ada di kelompok ini? L sampai O, spasi.');
    expect(speechText({ ...p, text: 'Is your letter in this group?' }, 'en')).toBe(
      'Is your letter in this group? L to O, space.',
    );
    expect(speechText({ ...p, sub: 'word', text: 'Is your word KUCING?' }, 'en')).toBe(
      'Is your word KUCING?',
    );
  });
});
