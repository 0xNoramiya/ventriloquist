import { useState } from 'react';
import type { Chip, Evidence, Hypothesis, Lang } from '../../api/types';
import { useT, type Key } from '../../i18n';
import { cx, factorText, pct } from '../../lib/format';
import { Pictogram } from '../Pictogram';
import { Badge } from '../Section';

const BOUNDED: Record<string, Key> = {
  cap: 'bars.bounded.cap',
  floor: 'bars.bounded.floor',
  other_min: 'bars.bounded.other_min',
};

const BOUNDED_SHORT: Record<string, Key> = {
  cap: 'bars.bounded_short.cap',
  floor: 'bars.bounded_short.floor',
  other_min: 'bars.bounded_short.other_min',
};

function boundedLabel(t: (k: Key) => string, bounded: string): string {
  const key = BOUNDED_SHORT[bounded];
  return key ? t(key) : bounded.replace('_', ' ');
}

interface Row {
  id: string;
  text: string;
  p: number;
  prior: number | null;
  chips: Chip[];
  bounded: string | null;
  personal: number | null;
  urgent: boolean;
  other: boolean;
}

function toRows(
  posterior: Hypothesis[],
  otherP: number | null,
  lang: Lang,
  otherText: string,
): Row[] {
  const rows: Row[] = posterior.map((h) => ({
    id: h.id,
    text: h.id === 'other' ? otherText : lang === 'id' ? h.text_id : h.text_en,
    p: h.p,
    prior: h.prior,
    chips: h.chips,
    bounded: h.bounded,
    personal: h.personal,
    urgent: h.urgent,
    other: h.id === 'other',
  }));
  if (otherP !== null && !rows.some((r) => r.other)) {
    rows.push({
      id: 'other',
      text: otherText,
      p: otherP,
      prior: null,
      chips: [],
      bounded: null,
      personal: null,
      urgent: false,
      other: true,
    });
  }
  return rows;
}

export function PosteriorBars({
  posterior,
  otherP,
  evidence,
  tau,
  lang,
}: {
  posterior: Hypothesis[];
  otherP: number | null;
  evidence: Evidence[];
  tau: number;
  lang: Lang;
}) {
  const t = useT();
  const [open, setOpen] = useState<string | null>(null);
  const rows = toRows(posterior, otherP, lang, t('bars.other'));
  const byId = new Map(evidence.map((e) => [e.id, e]));

  if (!rows.length) {
    return <p className="text-muted">{t('bars.empty')}</p>;
  }

  return (
    <div className="flex flex-col">
      <ol className="flex flex-col">
        {rows.map((r, i) => {
          const width = Math.max(0.4, Math.min(100, r.p * 100));
          return (
            <li
              key={r.id}
              className={cx('flex flex-col gap-1.5 py-3', i > 0 && 'border-t border-line')}
            >
              <div className="flex items-start gap-3">
                {r.other ? (
                  <span className="size-8 shrink-0" aria-hidden="true" />
                ) : (
                  <Pictogram
                    id={r.id}
                    size={32}
                    className="rounded-[6px] shadow-[inset_0_0_0_1px_var(--color-line)]"
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p
                    className={cx(
                      'leading-snug',
                      i === 0 ? 'font-bold' : 'font-semibold',
                      r.other && 'italic text-ink-soft',
                    )}
                  >
                    {r.text}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {r.urgent ? <Badge tone="alarm">{t('bars.urgent')}</Badge> : null}
                    {r.bounded ? (
                      <Badge tone="caution" title={t(BOUNDED[r.bounded] ?? 'bars.bounded.generic')}>
                        {t('bars.bounded')}: {boundedLabel(t, r.bounded)}
                      </Badge>
                    ) : null}
                    {r.personal && Math.abs(r.personal - 1) > 0.15 ? (
                      <Badge tone="neutral" title={t('bars.personal_hint')}>
                        {t('bars.personal')} {factorText(r.personal)}
                      </Badge>
                    ) : null}
                    {r.chips.map((c, ci) => {
                      const key = `${r.id}|${c.evidence_id}|${ci}`;
                      const expanded = open === key;
                      return (
                        <button
                          key={key}
                          type="button"
                          aria-expanded={expanded}
                          aria-controls={`chip-${key}`}
                          onClick={() => setOpen(expanded ? null : key)}
                          className={cx(
                            'relative inline-flex min-h-7 items-center gap-1 rounded-[var(--radius-chip)] px-2 text-[13px] font-bold leading-5 transition-colors duration-150',
                            'before:absolute before:inset-x-0 before:-inset-y-2.5 before:content-[""]',
                            expanded
                              ? 'bg-ink text-paper'
                              : 'bg-paper text-ink shadow-[inset_0_0_0_1px_var(--color-line-strong)] hover:bg-wash',
                          )}
                        >
                          <span className="tabular">{c.evidence_id}</span>
                          <span className="font-semibold opacity-80">{factorText(c.factor)}</span>
                          <span className="sr-only">{t('bars.chip_sr')}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
                <span className="tabular w-14 shrink-0 text-right text-lg font-bold">
                  {pct(r.p)}
                </span>
              </div>
              <div className="relative ml-11 h-3" aria-hidden="true">
                <div className="absolute inset-0 rounded-full bg-wash" />
                <div
                  className={cx(
                    // Grows from the left after each answer. clip-path rather than width: no layout
                    // work per frame, and the rounded end keeps its shape (scaleX would squash it).
                    'absolute inset-0 transition-[clip-path] duration-300 ease-[var(--ease-move)]',
                    r.other
                      ? 'bg-[repeating-linear-gradient(135deg,var(--color-ink-soft)_0_4px,transparent_4px_8px)] shadow-[inset_0_0_0_1px_var(--color-ink-soft)]'
                      : i === 0
                        ? 'bg-ink'
                        : 'bg-ink-soft',
                  )}
                  style={{ clipPath: `inset(0 ${100 - width}% 0 0 round 9999px)` }}
                />
                {r.prior !== null ? (
                  <div
                    className="absolute -top-1 h-5 w-[3px] -translate-x-1/2 rounded-full bg-voice-deep"
                    style={{ left: `${Math.min(100, r.prior * 100)}%` }}
                    title={`${t('bars.prior')} ${pct(r.prior)}`}
                  />
                ) : null}
                <div
                  className="absolute -inset-y-1.5 w-0 border-l-2 border-dashed border-alarm/60"
                  style={{ left: `${tau * 100}%` }}
                />
              </div>
              <p className="sr-only">
                {t('bars.sr', { p: pct(r.p), prior: r.prior === null ? '–' : pct(r.prior) })}
              </p>
              {r.chips.map((c, ci) => {
                const key = `${r.id}|${c.evidence_id}|${ci}`;
                if (open !== key) return null;
                const ev = byId.get(c.evidence_id);
                return (
                  <div
                    key={key}
                    id={`chip-${key}`}
                    className="ml-11 rounded-[var(--radius-control)] bg-paper px-3 py-2 text-[15px] shadow-[inset_0_0_0_1px_var(--color-line-strong)]"
                  >
                    <p className="font-semibold">
                      {c.evidence_id} · {t(`evidence.kind.${ev?.kind ?? 'unknown'}` as Key)}
                      {ev ? (
                        <span className="font-normal text-muted">
                          {' '}
                          · {t('time.ago', { m: Math.round(ev.minutes_ago) })}
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-0.5">{ev?.text ?? t('bars.chip_missing')}</p>
                    <p className="mt-1 text-sm text-muted">
                      {t('bars.chip_reason', { reason: c.reason, factor: factorText(c.factor) })}
                    </p>
                  </div>
                );
              })}
            </li>
          );
        })}
      </ol>
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-muted">
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-3.5 w-[3px] rounded-full bg-voice-deep"
            aria-hidden="true"
          />
          {t('bars.legend.prior')}
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-3.5 w-0 border-l-2 border-dashed border-alarm/60"
            aria-hidden="true"
          />
          {t('bars.legend.tau', { tau: pct(tau) })}
        </span>
        <span>{t('bars.legend.chips')}</span>
      </div>
    </div>
  );
}
