import type { Lang, Prompt } from '../api/types';
import { translate } from '../i18n';
import { groupRanges } from './spelling';

/** When to tell the patient to wait for the tone: once at the start of a session, and when a
 * question is asked again because no clear answer was seen (often the eyes were already shut when
 * the window opened, issue #2). */
export type AnswerCue = 'first' | 'again' | null;

/** What to say aloud for a prompt. Letter groups are read out so the screen is not required. */
export function speechText(p: Prompt, lang: Lang, cue: AnswerCue = null): string {
  const text = questionText(p, lang);
  return cue
    ? `${text} ${translate(lang, cue === 'first' ? 'patient.cue.first' : 'patient.cue.again')}`
    : text;
}

function questionText(p: Prompt, lang: Lang): string {
  if (p.kind === 'spelling' && p.sub === 'letter' && p.group.length) {
    const ranges = groupRanges(p.group).map((r) =>
      r
        .replace('–', ` ${translate(lang, 'spell.to')} `)
        .replace('SPACE', translate(lang, 'spell.space'))
        .replace('END', translate(lang, 'spell.end'))
        .replace('UNDO', translate(lang, 'spell.undo')),
    );
    return `${p.text} ${ranges.join(', ')}.`;
  }
  return p.text;
}
