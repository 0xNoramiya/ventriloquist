import type { Evidence } from '../api/types';
import type { Key, TFn } from '../i18n';

export function ago(t: TFn, minutes: number | null): string {
  if (minutes === null) return '';
  if (minutes < 1) return t('time.just_now');
  if (minutes < 90) return t('time.ago', { m: Math.round(minutes) });
  return t('time.ago_h', { h: (minutes / 60).toFixed(1) });
}

/** "Camera scene · 3 min ago", or "Scenario · Camera scene" for a fact a demo scenario wrote in
 * advance: its time is part of the story, not of the room (issue #18). */
export function evidenceLabel(t: TFn, e: Evidence): string {
  const kind = t(`evidence.kind.${e.kind}` as Key);
  if (e.scripted) return `${t('evidence.scripted')} · ${kind}`;
  return e.minutes_ago !== null ? `${kind} · ${ago(t, e.minutes_ago)}` : kind;
}

export function pct(p: number | null | undefined, digits = 0): string {
  if (p === null || p === undefined || Number.isNaN(p)) return '–';
  return `${(p * 100).toFixed(digits)}%`;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined) return '–';
  return v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
}

export function factorText(f: number): string {
  if (f >= 1) return `×${Number.isInteger(f) ? f : f.toFixed(1)}`;
  return `×${f.toFixed(2).replace(/0$/, '')}`;
}

export function clockTime(iso: string | undefined | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}
