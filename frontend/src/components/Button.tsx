import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import { cx } from '../lib/format';

export type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'voice' | 'night' | 'onAlarm';
export type Size = 'md' | 'lg' | 'xl' | 'sm' | 'answer';

const base =
  'inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] font-semibold ' +
  'select-none text-center leading-tight transition-[background-color,box-shadow,transform,color] duration-150 ' +
  'active:translate-y-px disabled:active:translate-y-0';

const variants: Record<Variant, string> = {
  primary:
    'bg-ink text-paper hover:bg-[color-mix(in_oklch,var(--color-ink)_86%,white)] disabled:bg-[#9aa9ac] disabled:text-paper',
  secondary:
    'bg-paper text-ink shadow-[inset_0_0_0_1px_var(--color-line-strong)] hover:bg-wash disabled:text-muted disabled:bg-linen',
  ghost: 'bg-transparent text-ink hover:bg-wash disabled:text-muted',
  danger: 'bg-alarm text-paper hover:bg-alarm-deep disabled:bg-[#c99a96]',
  onAlarm: 'bg-paper text-alarm-deep hover:bg-alarm-soft',
  voice: 'bg-voice text-ink hover:bg-[color-mix(in_oklch,var(--color-voice)_88%,black)]',
  night:
    'bg-night-2 text-mist shadow-[inset_0_0_0_1px_rgb(255_255_255/0.14)] hover:bg-night-3 disabled:bg-night disabled:text-[#6f8c90] disabled:shadow-[inset_0_0_0_1px_rgb(255_255_255/0.08)]',
};

const sizes: Record<Size, string> = {
  sm: 'min-h-10 px-3 text-sm',
  md: 'min-h-12 px-4 text-base',
  lg: 'min-h-14 px-5 text-lg',
  xl: 'min-h-16 px-6 text-xl',
  answer: 'min-h-16 px-2 text-lg sm:text-xl',
};

function buttonClass(variant: Variant = 'secondary', size: Size = 'md', extra?: string) {
  return cx(base, variants[variant], sizes[size], extra);
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  busy?: boolean;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    busy = false,
    className,
    children,
    disabled,
    type,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={buttonClass(variant, size, className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
});

export function LinkButton({
  variant = 'secondary',
  size = 'md',
  className,
  ...rest
}: LinkProps & { variant?: Variant; size?: Size }) {
  return <Link className={buttonClass(variant, size, className)} {...rest} />;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cx('size-4 animate-spin motion-reduce:animate-none', className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
