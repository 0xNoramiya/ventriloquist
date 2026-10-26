import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react';
import { cx } from '../lib/format';

export const inputClass =
  'min-h-12 w-full rounded-[var(--radius-control)] bg-paper px-3 text-ink shadow-[inset_0_0_0_1px_var(--color-line-strong)] ' +
  'placeholder:text-muted hover:shadow-[inset_0_0_0_1px_var(--color-ink-soft)] focus-visible:outline-offset-0';

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  children: (props: {
    id: string;
    'aria-describedby'?: string;
    'aria-invalid'?: boolean;
  }) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={cx('flex flex-col gap-1.5', className)}>
      <label htmlFor={id} className="text-[15px] font-semibold">
        {label}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {hint ? (
        <p id={hintId} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errId} className="flex items-start gap-1.5 text-sm font-semibold text-alarm">
          <ErrorIcon />
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputClass, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputClass, 'pr-8', props.className)} />;
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <span className="relative mt-0.5 inline-flex h-7 w-12 shrink-0">
        <input
          id={id}
          type="checkbox"
          role="switch"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          aria-describedby={description ? `${id}-d` : undefined}
          className="peer absolute inset-[-10px] z-10 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        />
        <span
          aria-hidden="true"
          className="h-7 w-12 rounded-full bg-[#b9c7c8] transition-colors duration-150 peer-checked:bg-ink peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--focus)] peer-disabled:opacity-60"
        />
        <span
          aria-hidden="true"
          className="absolute left-1 top-1 size-5 rounded-full bg-paper shadow-sm transition-transform duration-150 peer-checked:translate-x-5"
        />
      </span>
      <span className="flex flex-col">
        <label htmlFor={id} className="cursor-pointer font-semibold">
          {label}
        </label>
        {description ? (
          <span id={`${id}-d`} className="text-sm text-muted">
            {description}
          </span>
        ) : null}
      </span>
    </div>
  );
}

export function ErrorIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      className="mt-0.5 size-4 shrink-0"
      aria-hidden="true"
      fill="currentColor"
    >
      <path d="M10 1.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17Zm0 11.6a1.1 1.1 0 1 0 0 2.2 1.1 1.1 0 0 0 0-2.2Zm0-8.3c-.7 0-1.1.5-1.1 1.1l.3 5.6a.8.8 0 0 0 1.6 0l.3-5.6c0-.6-.4-1.1-1.1-1.1Z" />
    </svg>
  );
}

export function Notice({
  tone = 'info',
  children,
  role,
}: {
  tone?: 'info' | 'error' | 'good' | 'caution';
  children: ReactNode;
  role?: 'status' | 'alert';
}) {
  const tones = {
    info: 'bg-wash text-ink',
    error: 'bg-alarm-soft text-alarm-deep',
    good: 'bg-good-soft text-good',
    caution: 'bg-caution-soft text-caution',
  };
  return (
    <div
      role={role ?? (tone === 'error' ? 'alert' : 'status')}
      className={cx(
        'flex items-start gap-2 rounded-[var(--radius-control)] px-4 py-3 text-[15px]',
        tones[tone],
      )}
    >
      {tone === 'error' ? <ErrorIcon /> : null}
      <div className="min-w-0">{children}</div>
    </div>
  );
}
