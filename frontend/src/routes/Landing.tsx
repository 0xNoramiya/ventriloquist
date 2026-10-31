import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Button, LinkButton } from '../components/Button';
import { Notice, Switch } from '../components/Form';
import { Photo } from '../components/Photo';
import { SIGNAL_PAIRS } from '../lib/signalPairs';
import { Shell } from '../components/Shell';
import { unlockAudio } from '../lib/alarm';
import { cx } from '../lib/format';
import { useConfig } from '../lib/useConfig';
import { useT, type Key } from '../i18n';

const SCENARIOS: { id: string; title: Key; body: Key }[] = [
  // English patients first; the Indonesian ones show the second language.
  { id: 'daughter', title: 'scenario.daughter.title', body: 'scenario.daughter.body' },
  { id: 'cold', title: 'scenario.cold.title', body: 'scenario.cold.body' },
  { id: 'suction', title: 'scenario.suction.title', body: 'scenario.suction.body' },
  { id: 'spelling', title: 'scenario.spelling.title', body: 'scenario.spelling.body' },
];

type Line = { kind: 'q'; text: Key; answer: 'yes' | 'no' } | { kind: 'say'; text: Key };

const TRAIL: Line[] = [
  { kind: 'q', text: 'landing.trail.q1', answer: 'no' },
  { kind: 'q', text: 'landing.trail.q2', answer: 'yes' },
  { kind: 'q', text: 'landing.trail.q3', answer: 'yes' },
  { kind: 'q', text: 'landing.trail.q4', answer: 'yes' },
  { kind: 'say', text: 'landing.trail.say' },
  { kind: 'q', text: 'landing.trail.q5', answer: 'yes' },
];

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/** The page's only animated sequence: a question trail plays itself and ends in the patient's
 * words. It starts when it scrolls into view, so nobody misses it. */
function TrailDemo() {
  const t = useT();
  const ref = useRef<HTMLElement | null>(null);
  const [seen, setSeen] = useState(false);
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? TRAIL.length : 0));
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  useEffect(() => {
    if (!seen || shown >= TRAIL.length) return;
    const id = window.setTimeout(
      () => setShown((n) => n + 1),
      shown === 0 ? 200 : shown === 4 ? 1100 : 750,
    );
    return () => window.clearTimeout(id);
  }, [seen, shown]);

  return (
    <figure
      ref={ref}
      className="night relative flex flex-col overflow-hidden rounded-[var(--radius-panel)] bg-night text-mist"
    >
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-5 py-3 text-sm text-mist-soft">
        <span>{t('landing.trail.label')}</span>
        <span className="tabular">{t('landing.trail.count')}</span>
      </div>
      <ol
        className="flex min-h-[420px] flex-col gap-3 px-5 py-5 sm:px-6"
        aria-label={t('landing.trail.aria')}
      >
        {TRAIL.map((line, i) => {
          const visible = i < shown;
          if (line.kind === 'say') {
            return (
              <li
                key={line.text}
                className={cx('my-2', visible ? 'enter-line' : 'invisible')}
                aria-hidden={!visible || undefined}
              >
                <p className="mb-1 text-sm text-mist-soft">{t('landing.trail.spoken')}</p>
                <blockquote className="rounded-[12px] bg-voice px-4 py-4 text-[26px] font-bold leading-tight text-ink sm:text-[30px]">
                  {t(line.text)}
                </blockquote>
              </li>
            );
          }
          return (
            <li
              key={line.text}
              className={cx(
                'flex items-baseline justify-between gap-4 border-b border-white/[0.08] pb-3',
                visible ? 'enter-line' : 'invisible',
              )}
              aria-hidden={!visible || undefined}
            >
              <span className="text-[17px] leading-snug text-paper sm:text-lg">{t(line.text)}</span>
              <AnswerTag answer={line.answer} />
            </li>
          );
        })}
      </ol>
      <figcaption className="border-t border-white/10 px-5 py-3 text-sm text-mist-soft">
        {t('landing.trail.caption')}
      </figcaption>
    </figure>
  );
}

function AnswerTag({ answer }: { answer: 'yes' | 'no' }) {
  const t = useT();
  return (
    <span
      className={cx(
        'inline-flex min-w-14 shrink-0 justify-center rounded-full px-3 py-0.5 text-sm font-bold',
        answer === 'yes'
          ? 'bg-mist text-night'
          : 'text-mist shadow-[inset_0_0_0_1.5px_var(--color-mist-soft)]',
      )}
    >
      {answer === 'yes' ? t('answer.yes') : t('answer.no')}
    </span>
  );
}

export function Landing() {
  const t = useT();
  const navigate = useNavigate();
  const { config, error: configError } = useConfig();
  const [simulated, setSimulated] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [heroError, setHeroError] = useState<string | null>(null);

  const available = new Set(config?.scenarios.map((s) => s.id) ?? SCENARIOS.map((s) => s.id));

  // On your own face: the scenario's patient, calibrated first, so answers fuse SAM 3.1 with the
  // judge instead of the judge alone on default signals (weaker readings, more questions).
  async function tryOnFace() {
    unlockAudio();
    setBusy('face');
    setHeroError(null);
    try {
      const patient = await api.scenarioPatient('daughter');
      navigate(`/calibrate/${patient.id}?scenario=daughter`);
    } catch (e) {
      setHeroError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  async function start(id: string) {
    unlockAudio();
    setBusy(id);
    setError(null);
    try {
      const snap = await api.startScenario(id, { simulated, noise: 0.05, mock: true });
      navigate(`/caregiver/${snap.session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  return (
    <Shell>
      <section className="grid items-start gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
        <div className="flex flex-col gap-6 pt-2 lg:pt-8">
          <h1 className="max-w-[16ch] text-[44px] font-bold leading-[1.02] tracking-[-0.02em] sm:text-[64px] lg:text-[76px]">
            {t('landing.tagline')}
          </h1>
          <p className="max-w-[60ch] text-lg text-ink-soft sm:text-xl">{t('landing.lead')}</p>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="primary"
              size="lg"
              busy={busy === 'face'}
              onClick={() => void tryOnFace()}
            >
              {t('landing.cta_face')}
            </Button>
            <LinkButton to="/setup" variant="secondary" size="lg">
              {t('landing.setup')}
            </LinkButton>
          </div>
          <p className="max-w-[60ch] text-[15px] text-ink-soft">{t('landing.cta_face_hint')}</p>
          {heroError ? <Notice tone="error">{heroError}</Notice> : null}
          <p className="max-w-[60ch] text-[15px] text-muted">
            <strong className="text-ink">{t('footer.not_device')}</strong>{' '}
            {t('landing.not_device_body')}
          </p>
        </div>
        <figure className="flex flex-col gap-2 lg:pt-8">
          <Photo
            name="hero-bedside"
            widths={[800, 1600]}
            ratio={3 / 2}
            sizes="(min-width: 1024px) 40vw, 100vw"
            alt={t('landing.hero_alt')}
            eager
            className="rounded-[20px] bg-wash"
          />
          <figcaption className="text-sm text-muted">{t('landing.photo_note')}</figcaption>
        </figure>
      </section>

      <section className="mt-20 grid gap-6 border-t border-line pt-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-14">
        <h2 className="text-[30px] font-bold leading-tight sm:text-[36px]">
          {t('landing.flip.title')}
        </h2>
        <div className="flex max-w-[62ch] flex-col gap-4 text-lg text-ink-soft">
          <p>{t('landing.flip.p1')}</p>
          <p>
            <strong className="text-ink">{t('landing.flip.p2')}</strong>
          </p>
          <p>{t('landing.flip.p3')}</p>
        </div>
        <div className="lg:col-span-2 lg:mx-auto lg:w-full lg:max-w-[760px]">
          <TrailDemo />
        </div>
      </section>

      <section
        className="mt-16 grid items-center gap-8 border-t border-line pt-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,6fr)] lg:gap-14"
        aria-labelledby="alone-title"
      >
        <figure className="flex flex-col gap-2">
          <Photo
            name="night-check"
            widths={[800, 1600]}
            ratio={1600 / 1062}
            sizes="(min-width: 1024px) 45vw, 100vw"
            alt={t('landing.alone.photo_alt')}
            className="rounded-[20px] bg-night"
          />
          <figcaption className="text-sm text-muted">{t('landing.photo_note')}</figcaption>
        </figure>
        <div className="flex flex-col gap-5">
          <h2 id="alone-title" className="text-[30px] font-bold leading-tight sm:text-[36px]">
            {t('landing.alone.title')}
          </h2>
          <p className="max-w-[56ch] text-lg text-ink-soft">{t('landing.alone.lead')}</p>
          <ul className="flex flex-col gap-4">
            {(['1', '2', '3'] as const).map((n) => (
              <li key={n} className="border-l-[3px] border-voice pl-4">
                <h3 className="text-lg font-bold">{t(`landing.alone.${n}.title` as Key)}</h3>
                <p className="text-ink-soft">{t(`landing.alone.${n}.body` as Key)}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section id="demo" className="mt-16 border-t border-line pt-10" aria-labelledby="demo-title">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-14">
          <div className="flex flex-col gap-4">
            <h2 id="demo-title" className="text-[30px] font-bold leading-tight sm:text-[36px]">
              {t('landing.demo.title')}
            </h2>
            <p className="max-w-[52ch] text-ink-soft">{t('landing.demo.body')}</p>
            <div className="rounded-[var(--radius-panel)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]">
              <Switch
                checked={simulated}
                onChange={setSimulated}
                label={t('landing.demo.simulated')}
                description={t('landing.demo.simulated_hint')}
              />
            </div>
          </div>
          <div className="flex flex-col gap-3">
            {configError ? (
              <Notice tone="error">
                {t('error.backend')} <span className="text-sm">({configError})</span>
              </Notice>
            ) : null}
            {error ? <Notice tone="error">{error}</Notice> : null}
            <ul className="flex flex-col divide-y divide-line rounded-[var(--radius-panel)] bg-paper shadow-[inset_0_0_0_1px_var(--color-line)]">
              {SCENARIOS.filter((s) => available.has(s.id)).map((s) => (
                <li
                  key={s.id}
                  className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-6 sm:p-5"
                >
                  <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-bold">{t(s.title)}</h3>
                    <p className="text-[15px] text-muted">{t(s.body)}</p>
                  </div>
                  <Button
                    variant="secondary"
                    busy={busy === s.id}
                    disabled={busy !== null && busy !== s.id}
                    onClick={() => void start(s.id)}
                    aria-label={`${t('landing.demo.start')}: ${t(s.title)}`}
                  >
                    {t('landing.demo.start')}
                  </Button>
                </li>
              ))}
            </ul>
            <p className="text-[15px] text-muted">{t('landing.demo.after')}</p>
          </div>
        </div>
      </section>

      <section className="mt-16 border-t border-line pt-10" aria-labelledby="how-title">
        <h2 id="how-title" className="text-[30px] font-bold leading-tight sm:text-[36px]">
          {t('landing.how.title')}
        </h2>
        <ol className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {(['1', '2', '3', '4'] as const).map((n) => (
            <li key={n} className="flex flex-col gap-2">
              <span className="tabular text-sm font-bold text-muted">
                {t('landing.how.step', { n })}
              </span>
              <h3 className="text-xl font-bold">{t(`landing.how.${n}.title` as Key)}</h3>
              <p className="text-ink-soft">{t(`landing.how.${n}.body` as Key)}</p>
              {n === '1' ? (
                <ul
                  className="mt-2 grid grid-cols-4 gap-1.5"
                  aria-label={t('landing.how.1.examples')}
                >
                  {SIGNAL_PAIRS.map((p) => (
                    <li key={p.id}>
                      <img
                        src={`${import.meta.env.BASE_URL}img/signals/${p.yes.img}-on.webp`}
                        alt={t(p.yes.label)}
                        title={t(p.yes.label)}
                        width={480}
                        height={360}
                        loading="lazy"
                        draggable={false}
                        className="aspect-[4/3] w-full select-none rounded-[6px] bg-wash object-cover"
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
    </Shell>
  );
}
