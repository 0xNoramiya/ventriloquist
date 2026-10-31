import { describe, expect, it } from 'vitest';
import { snapshot } from '../test/fixtures';
import { speechText } from './promptSpeech';

const prompt = snapshot().prompt;
if (!prompt) throw new Error('the fixture snapshot has a prompt');

describe('speechText', () => {
  it('says the question alone by default', () => {
    expect(speechText(prompt, 'en')).toBe('Is it about a person?');
  });

  it('adds when to answer on the first question and on a re-ask', () => {
    expect(speechText(prompt, 'en', 'first')).toBe('Is it about a person? Answer after the tone.');
    expect(speechText(prompt, 'en', 'again')).toBe(
      'Is it about a person? Answer after the tone, starting with your eyes open.',
    );
    expect(speechText(prompt, 'id', 'first')).toBe(
      'Is it about a person? Jawab setelah bunyi nada.',
    );
  });
});
