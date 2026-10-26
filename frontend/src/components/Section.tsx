import type { ReactNode } from 'react';
import { cx } from '../lib/format';

export function Section({
  id,
  title,
  meta,
  children,
  className,
}: {
  id: string;
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section aria-labelledby={id} className={cx('flex min-w-0 flex-col gap-3', className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={id} className="text-lg font-bold">
          {title}
        </h2>
        {meta ? <div className="text-sm text-muted">{meta}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Badge({
  children,
  tone = 'neutral',
  title,
  className,
}: {
  children: ReactNode;
  tone?: 'neutral' | 'ink' | 'caution' | 'alarm' | 'good' | 'voice' | 'outline';
  title?: string;
  className?: string;
}) {
  const tones = {
    neutral: 'bg-wash text-ink',
    ink: 'bg-ink text-paper',
    caution: 'bg-caution-soft text-caution',
    alarm: 'bg-alarm text-paper',
    good: 'bg-good-soft text-good',
    voice: 'bg-voice text-ink',
    outline: 'text-ink shadow-[inset_0_0_0_1px_var(--color-line-strong)]',
  };
  return (
    <span
      title={title}
      className={cx(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-[var(--radius-chip)] px-2 py-0.5 text-[13px] font-semibold leading-5',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
