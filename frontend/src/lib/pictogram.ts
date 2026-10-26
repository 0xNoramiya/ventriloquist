// AAC pictograms in /public/pictograms/{id}.webp, one per taxonomy message id.

export const PICTOGRAM_IDS = new Set([
  'pain',
  'breathing',
  'suction',
  'tube_discomfort',
  'thirst',
  'nausea',
  'itch',
  'position',
  'hands_uncomfortable',
  'toilet',
  'tired',
  'hot',
  'cold',
  'light',
  'noise',
  'what_happened',
  'where',
  'time',
  'tube_when',
  'talk_staff',
  'scared',
  'company',
  'thanks',
  'see_person',
  'where_person',
  'call_person',
  'want_item',
  'tell_family_ok',
  'pray',
  'glasses_hearing',
  'phone_music',
  'spell',
  'stop',
  'other',
]);

/** Pictogram URL for a hypothesis id ("see_person:aisyah" uses see_person), or null. */
export function pictogramSrc(hypothesisId: string | null | undefined): string | null {
  if (!hypothesisId) return null;
  const base = hypothesisId.split(':')[0] ?? '';
  return PICTOGRAM_IDS.has(base) ? `/pictograms/${base}.webp` : null;
}
