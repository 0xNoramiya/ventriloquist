import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import type { Lang } from '../api/types';
import { useLang, useT } from '../i18n';
import { cx } from '../lib/format';
import { LogoMark } from './Logo';

export function LangToggle({ className }: { className?: string }) {
  const t = useT();
  const { lang, setLang } = useLang();
  return (
    <div
      role="group"
      aria-label={t('nav.language')}
      className={cx(
        'inline-flex rounded-[var(--radius-control)] bg-paper p-1 shadow-[inset_0_0_0_1px_var(--color-line)]',
        className,
      )}
    >
      {(['en', 'id'] as const).map((l) => (
        <button
          key={l}
          type="button"
          aria-pressed={lang === l}
          onClick={() => setLang(l)}
          className={cx(
            'min-h-10 min-w-11 rounded-[7px] px-2 text-sm font-semibold transition-colors duration-150',
            lang === l ? 'bg-ink text-paper' : 'text-ink-soft hover:bg-wash',
          )}
        >
          <span aria-hidden="true">{l.toUpperCase()}</span>
          <span className="sr-only">{l === 'en' ? 'English' : 'Bahasa Indonesia'}</span>
        </button>
      ))}
    </div>
  );
}

export function Footer({
  night = false,
  lang,
  wide = false,
}: {
  night?: boolean;
  lang?: Lang;
  wide?: boolean;
}) {
  const t = useT(lang);
  return (
    <footer
      className={cx(
        'mt-auto border-t text-sm',
        night ? 'border-white/10 py-3 text-mist-soft' : 'border-line py-6 text-muted',
      )}
    >
      <div
        className={cx(
          'mx-auto flex flex-col gap-1 px-4 sm:flex-row sm:items-baseline sm:justify-between sm:px-8',
          wide ? 'max-w-[1480px]' : 'max-w-[1240px]',
        )}
      >
        <p>
          <strong className={night ? 'text-mist' : 'text-ink'}>{t('footer.not_device')}</strong>{' '}
          {t('footer.prototype')}
        </p>
        {night ? null : <p>{t('footer.fictional')}</p>}
      </div>
    </footer>
  );
}

const NAV: { to: string; key: 'nav.home' | 'nav.setup' | 'nav.eval' | 'nav.settings' }[] = [
  { to: '/', key: 'nav.home' },
  { to: '/setup', key: 'nav.setup' },
  { to: '/eval', key: 'nav.eval' },
  { to: '/settings', key: 'nav.settings' },
];

export function Header({ children, wide = false }: { children?: ReactNode; wide?: boolean }) {
  const t = useT();
  return (
    <header className="border-b border-line bg-linen">
      <div
        className={cx(
          'mx-auto flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-8',
          wide ? 'max-w-[1480px]' : 'max-w-[1240px]',
        )}
      >
        <Link
          to="/"
          className="-ml-1 flex min-h-12 items-center gap-2 rounded-[var(--radius-control)] px-1 text-lg font-bold tracking-[-0.01em]"
        >
          <LogoMark />
          Ventriloquist
        </Link>
        <nav aria-label={t('nav.main')} className="order-3 w-full sm:order-none sm:w-auto">
          <ul className="-mx-2 flex flex-wrap gap-x-1">
            {NAV.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end
                  className={({ isActive }) =>
                    cx(
                      'inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-2.5 text-[15px] font-semibold',
                      isActive
                        ? 'text-ink underline decoration-voice decoration-[3px] underline-offset-[7px]'
                        : 'text-ink-soft hover:text-ink hover:bg-wash',
                    )
                  }
                >
                  {t(n.key)}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {children}
          <LangToggle />
        </div>
      </div>
    </header>
  );
}

export function Shell({
  children,
  headerExtra,
  wide = false,
}: {
  children: ReactNode;
  headerExtra?: ReactNode;
  wide?: boolean;
}) {
  const t = useT();
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only-focusable absolute left-3 top-3 z-50 rounded-[var(--radius-control)] bg-ink px-4 py-3 text-paper"
      >
        {t('nav.skip')}
      </a>
      <Header wide={wide}>{headerExtra}</Header>
      <main
        id="main"
        className={cx(
          'mx-auto w-full flex-1 px-4 pb-16 pt-8 sm:px-8',
          wide ? 'max-w-[1480px]' : 'max-w-[1240px]',
        )}
      >
        {children}
      </main>
      <Footer wide={wide} />
    </div>
  );
}
