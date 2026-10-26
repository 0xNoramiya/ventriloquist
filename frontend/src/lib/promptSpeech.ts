import type { Lang, Prompt } from '../api/types';
import { translate } from '../i18n';
import { groupRanges } from './spelling';

/** What to say aloud for a prompt. Letter groups are read out so the screen is not required. */
export function speechText(p: Prompt, lang: Lang): string {
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
