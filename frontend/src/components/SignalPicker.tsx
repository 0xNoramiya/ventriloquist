import type { CSSProperties } from 'react';
import { useT } from '../i18n';
import { cx } from '../lib/format';
import { SIGNAL_PAIRS, type SignalHalf } from '../lib/signalPairs';

function Flip({ half, answer }: { half: SignalHalf; answer: 'YES' | 'NO' }) {
  const t = useT();
  const base = `${import.meta.env.BASE_URL}img/signals/${half.img}`;
  return (
    <span className="flex min-w-0 flex-col gap-1.5">
      <span
        className="relative block aspect-[4/3] overflow-hidden rounded-[10px] bg-wash"
        style={half.rhythm ? ({ '--signal-rhythm': half.rhythm } as CSSProperties) : undefined}
      >
        <img
          src={`${base}-rest.webp`}
          alt=""
          width={480}
          height={360}
          loading="lazy"
          draggable={false}
          className="absolute inset-0 size-full select-none object-cover"
        />
        <img
          src={`${base}-on.webp`}
          alt=""
          width={480}
          height={360}
          loading="lazy"
          draggable={false}
          className="signal-on absolute inset-0 size-full select-none object-cover"
        />
      </span>
      <span className="text-sm leading-snug">
        <strong className="font-bold">{t(answer === 'YES' ? 'answer.YES' : 'answer.NO')}</strong>{' '}
        <span className="text-ink-soft">{t(half.label)}</span>
      </span>
    </span>
  );
}

/**
 * Which movements the patient will use, shown rather than named: each card plays its YES and NO on
 * the fictional demo patient. Native radios, so arrow keys move between cards.
 */
export function SignalPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const t = useT();
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-lg font-bold">{t('cal.pick.title')}</legend>
      <p className="text-[15px] text-muted">{t('cal.pick.hint')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {SIGNAL_PAIRS.map((pair) => {
          const selected = value === pair.id;
          return (
            <label
              key={pair.id}
              data-selected={selected || undefined}
              className={cx(
                'signal-card flex cursor-pointer flex-col gap-3 rounded-[var(--radius-panel)] bg-paper p-3 transition-shadow duration-150 ease-out has-[input:focus-visible]:[outline:3px_solid_var(--focus)] has-[input:focus-visible]:[outline-offset:2px]',
                selected
                  ? 'shadow-[inset_0_0_0_2px_var(--color-ink)]'
                  : 'shadow-[inset_0_0_0_1px_var(--color-line)] hover:shadow-[inset_0_0_0_1px_var(--color-line-strong)]',
              )}
            >
              <input
                type="radio"
                name="signal"
                value={pair.id}
                checked={selected}
                onChange={() => onChange(pair.id)}
                className="sr-only"
              />
              <span className="grid grid-cols-2 gap-2">
                <Flip half={pair.yes} answer="YES" />
                <Flip half={pair.no} answer="NO" />
              </span>
            </label>
          );
        })}
      </div>
      <label
        data-selected={value === '' || undefined}
        className={cx(
          'flex cursor-pointer items-center gap-3 rounded-[var(--radius-control)] bg-paper px-4 py-3 transition-shadow duration-150 ease-out has-[input:focus-visible]:[outline:3px_solid_var(--focus)] has-[input:focus-visible]:[outline-offset:2px]',
          value === ''
            ? 'shadow-[inset_0_0_0_2px_var(--color-ink)]'
            : 'shadow-[inset_0_0_0_1px_var(--color-line)]',
        )}
      >
        <input
          type="radio"
          name="signal"
          value=""
          checked={value === ''}
          onChange={() => onChange('')}
          className="size-5 shrink-0 accent-[var(--color-ink)]"
        />
        <span>
          <span className="block font-semibold">{t('pick.unsure')}</span>
          <span className="block text-sm text-muted">{t('pick.unsure_hint')}</span>
        </span>
      </label>
    </fieldset>
  );
}
