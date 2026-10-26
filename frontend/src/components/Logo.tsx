import { cx } from '../lib/format';

/** Mark: a phone holding a closing quotation mark — the patient's words, not the machine's. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cx('size-8 shrink-0', className)} aria-hidden="true">
      <rect x="6" y="2" width="20" height="28" rx="5" fill="var(--color-ink)" />
      <g fill="var(--color-voice)" stroke="var(--color-voice)" strokeLinecap="round">
        <circle cx="13" cy="12.6" r="2.4" stroke="none" />
        <circle cx="19.6" cy="12.6" r="2.4" stroke="none" />
        <path d="M15.2 13.2c-.1 2.7-1.4 4.6-3.6 5.6" strokeWidth="1.7" fill="none" />
        <path d="M21.8 13.2c-.1 2.7-1.4 4.6-3.6 5.6" strokeWidth="1.7" fill="none" />
      </g>
      <rect x="13" y="25" width="6" height="1.6" rx="0.8" fill="var(--color-mist-soft)" />
    </svg>
  );
}
