// Letter grid helpers for the spelling board.

export const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
export const SPECIALS = ['SPACE', 'END', 'UNDO'] as const;
export const GRID_SYMBOLS: string[] = [...LETTERS, ...SPECIALS];

export function isHighlighted(symbol: string, group: readonly string[]): boolean {
  return group.includes(symbol);
}

/** Split the 26 letters into rows of `cols`; the special keys always form their own row. */
export function gridRows(cols: number): string[][] {
  if (cols < 1) throw new Error('cols must be >= 1');
  const rows: string[][] = [];
  for (let i = 0; i < LETTERS.length; i += cols) rows.push(LETTERS.slice(i, i + cols));
  rows.push([...SPECIALS]);
  return rows;
}

/** Short spoken-style label for a group: "L to X" for a run, otherwise a list. */
export function groupRanges(group: readonly string[]): string[] {
  const letters = LETTERS.filter((l) => group.includes(l));
  const out: string[] = [];
  let start = -1;
  let prev = -1;
  for (const l of letters) {
    const i = LETTERS.indexOf(l);
    if (start < 0) {
      start = prev = i;
    } else if (i === prev + 1) {
      prev = i;
    } else {
      out.push(rangeText(start, prev));
      start = prev = i;
    }
  }
  if (start >= 0) out.push(rangeText(start, prev));
  for (const s of SPECIALS) if (group.includes(s)) out.push(s);
  return out;
}

function rangeText(a: number, b: number): string {
  const first = LETTERS[a] ?? '';
  const last = LETTERS[b] ?? '';
  if (a === b) return first;
  if (b === a + 1) return `${first}, ${last}`;
  return `${first}–${last}`;
}

/** The word currently being spelled (after the last space). */
export function currentWord(text: string): string {
  const parts = text.split(' ');
  return parts[parts.length - 1] ?? '';
}
