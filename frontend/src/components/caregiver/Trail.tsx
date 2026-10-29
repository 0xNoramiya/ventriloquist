import type { Lang, SourceOutput, TrailItem } from '../../api/types';
import { useCurrentLang, useT, type Key, type TFn } from '../../i18n';
import { cx, pct } from '../../lib/format';
import { groupRanges } from '../../lib/spelling';
import { Badge } from '../Section';

const SOURCE_NAMES: Record<string, Key> = {
  tracker: 'source.tracker',
  local: 'source.local',
  spark: 'source.spark',
  keyboard: 'source.keyboard',
  caregiver: 'source.caregiver',
  simulated: 'source.simulated',
  camera: 'source.camera',
};

export function AnswerPill({ answer, t }: { answer: string; t: TFn }) {
  const label =
    answer === 'yes'
      ? t('answer.YES')
      : answer === 'no'
        ? t('answer.NO')
        : answer === 'emergency'
          ? t('answer.EMERGENCY')
          : t('answer.UNCLEAR');
  return (
    <span
      className={cx(
        'inline-flex min-w-16 justify-center rounded-full border-2 px-2.5 py-px text-[13px] font-bold tracking-[0.04em]',
        answer === 'yes' && 'border-ink bg-ink text-paper',
        answer === 'no' && 'border-ink text-ink',
        answer !== 'yes' && answer !== 'no' && 'border-dashed border-ink-soft text-ink-soft',
      )}
    >
      {label}
    </span>
  );
}

// In privacy mode the judge is Muse Spark Open, served by one of these hosts.
const OPEN_WEIGHT_HOSTS = new Set(['baseten', 'modal']);

function sourceLine(name: string, s: SourceOutput, t: TFn): string {
  const key =
    name === 'spark' && OPEN_WEIGHT_HOSTS.has(String(s.provider))
      ? 'source.spark_open'
      : SOURCE_NAMES[name];
  const label = key ? t(key) : name;
  if (s.pending) return `${label}: ${t('trail.source_pending')}`;
  if (s.error) return `${label}: ${t('trail.source_error')} (${String(s.error)})`;
  if (s.ok === false) return `${label}: ${t('trail.source_failed')}`;
  const ans = s.answer ?? s.top ?? '–';
  const p = typeof s.p === 'number' ? ` ${pct(s.p)}` : '';
  return `${label}: ${ans}${p}`;
}

export function Trail({ trail, patientLang }: { trail: TrailItem[]; patientLang: Lang }) {
  const t = useT();
  const uiLang = useCurrentLang();
  if (!trail.length) return <p className="text-muted">{t('trail.empty')}</p>;
  return (
    <ol className="flex flex-col">
      {trail.map((item, i) => {
        const showEnglish = patientLang !== 'en' && item.text_en && item.text_en !== item.text;
        const leader = item.top_after?.[0];
        return (
          <li
            key={`${item.prompt_id}-${item.n}`}
            className={cx(
              'grid grid-cols-[2.25rem_1fr] gap-x-2 py-3',
              i > 0 && 'border-t border-line',
            )}
          >
            <span className="tabular pt-0.5 text-sm font-bold text-muted">Q{item.n}</span>
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                <p className="min-w-0 flex-1 font-semibold leading-snug" lang={patientLang}>
                  {item.text}
                  {showEnglish ? (
                    <span className="block font-normal text-muted" lang="en">
                      {item.text_en}
                    </span>
                  ) : null}
                </p>
                <div className="flex items-center gap-2">
                  {item.overridden ? (
                    <Badge tone="caution" title={t('trail.override_hint')}>
                      <svg
                        viewBox="0 0 16 16"
                        className="size-3.5"
                        aria-hidden="true"
                        fill="currentColor"
                      >
                        <path d="M6.5 1.5a1 1 0 0 1 1 1V7h.5V3a1 1 0 1 1 2 0v4h.5V4a1 1 0 1 1 2 0v6.5c0 2.5-1.9 4-4.2 4-1.6 0-2.7-.7-3.6-1.9L2.6 9.9a1 1 0 0 1 1.6-1.2l1.3 1.6V2.5a1 1 0 0 1 1-1Z" />
                      </svg>
                      {t('trail.override')}
                    </Badge>
                  ) : null}
                  <AnswerPill answer={item.answer} t={t} />
                </div>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-muted">
                {item.kind !== 'ask' ? <span>{t(`prompt.kind.${item.kind}` as Key)}</span> : null}
                {item.group.length ? (
                  <span>{t('trail.group', { g: groupRanges(item.group).join(', ') })}</span>
                ) : null}
                <span className="tabular">
                  {t('trail.confidence', { c: pct(item.confidence) })}
                </span>
                {Object.entries(item.sources).map(([name, s]) => (
                  <span key={name}>{sourceLine(name, s, t)}</span>
                ))}
              </div>
              {leader ? (
                <p className="text-sm text-ink-soft">
                  {t('trail.leader', {
                    text: uiLang === 'id' ? leader.text_id : leader.text_en,
                    p: pct(leader.p),
                  })}
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
