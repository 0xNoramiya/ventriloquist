import { useEffect, useState, type FormEvent } from 'react';
import { api, setLivePasscode, type SettingsUpdate } from '../api/client';
import type { Lang, PublicConfig } from '../api/types';
import { Button } from '../components/Button';
import { Field, Notice, Select, Switch, TextInput } from '../components/Form';
import { Section } from '../components/Section';
import { Shell } from '../components/Shell';
import { useT, type Key } from '../i18n';
import { cx, pct, usd } from '../lib/format';
import { loadConfig, setCachedConfig } from '../lib/useConfig';

const FLAGS: { id: string; label: Key; hint: Key }[] = [
  { id: 'use_sam', label: 'settings.flag.use_sam', hint: 'settings.flag.use_sam_hint' },
  {
    id: 'use_spark_judge',
    label: 'settings.flag.use_spark_judge',
    hint: 'settings.flag.use_spark_judge_hint',
  },
  {
    id: 'use_transcribe',
    label: 'settings.flag.use_transcribe',
    hint: 'settings.flag.use_transcribe_hint',
  },
  { id: 'use_wonder', label: 'settings.flag.use_wonder', hint: 'settings.flag.use_wonder_hint' },
  { id: 'idle_watch', label: 'settings.flag.idle_watch', hint: 'settings.flag.idle_watch_hint' },
];

export default function Settings() {
  const t = useT();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState<'general' | 'mode' | null>(null);

  const [tau, setTau] = useState(0.7);
  const [windowS, setWindowS] = useState(4);
  const [language, setLanguage] = useState<Lang>('en');
  const [budgetMax, setBudgetMax] = useState('120');
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [keepClips, setKeepClips] = useState(false);

  const [mode, setMode] = useState<'mock' | 'live'>('mock');
  const [privacy, setPrivacy] = useState(false);
  const [passcode, setPasscode] = useState('');

  function hydrate(c: PublicConfig) {
    setConfig(c);
    setCachedConfig(c);
    setTau(c.engine.tau_confirm);
    setWindowS(c.perception.window_s);
    setLanguage(c.language);
    setBudgetMax(String(c.budget.max_usd));
    setFlags(c.flags);
    setKeepClips(c.keep_clips_for_evaluation);
    setMode(c.mode === 'live' ? 'live' : 'mock');
    setPrivacy(c.privacy_default);
  }

  useEffect(() => {
    loadConfig(true)
      .then(hydrate)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function save(body: SettingsUpdate, which: 'general' | 'mode') {
    setSaving(which);
    setError(null);
    setSaved(null);
    try {
      hydrate(await api.updateSettings(body));
      setSaved(which === 'mode' ? t('settings.mode_saved') : t('settings.saved'));
      setPasscode('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  }

  function submitGeneral(e: FormEvent) {
    e.preventDefault();
    const cap = Number(budgetMax);
    void save(
      {
        tau_confirm: tau,
        window_s: windowS,
        language,
        budget_max_usd: Number.isFinite(cap) ? cap : undefined,
        keep_clips_for_evaluation: keepClips,
        ...Object.fromEntries(FLAGS.map((f) => [f.id, Boolean(flags[f.id])])),
      },
      'general',
    );
  }

  function submitMode(e: FormEvent) {
    e.preventDefault();
    void save({ app_mode: mode, privacy_mode: privacy, passcode: passcode || undefined }, 'mode');
  }

  const modeChanged = config
    ? mode !== (config.mode === 'live' ? 'live' : 'mock') || privacy !== config.privacy_default
    : false;
  const needsPasscode = mode === 'live' || privacy;

  return (
    <Shell>
      <div className="mx-auto flex max-w-[880px] flex-col gap-10">
        <div>
          <h1 className="text-[34px] font-bold">{t('settings.title')}</h1>
          <p className="mt-1 max-w-[62ch] text-lg text-ink-soft">{t('settings.lead')}</p>
        </div>
        {error ? <Notice tone="error">{error}</Notice> : null}
        {saved ? <Notice tone="good">{saved}</Notice> : null}

        {config?.passcode_required ? (
          <UnlockPanel
            unlocked={Boolean(config.unlocked)}
            publicLive={Boolean(config.public_live)}
            onChange={() => void loadConfig(true).then(setConfig)}
          />
        ) : null}

        <Section id="mode-title" title={t('settings.mode.title')}>
          <form onSubmit={submitMode} className="flex flex-col gap-5">
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 font-semibold">{t('settings.mode.legend')}</legend>
              {(['mock', 'live'] as const).map((m) => (
                <label
                  key={m}
                  className={cx(
                    'flex cursor-pointer items-start gap-3 rounded-[var(--radius-control)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]',
                    mode === m && 'shadow-[inset_0_0_0_2px_var(--color-ink)]',
                  )}
                >
                  <input
                    type="radio"
                    name="mode"
                    value={m}
                    checked={mode === m}
                    onChange={() => setMode(m)}
                    className="mt-1 size-5 accent-[var(--color-ink)]"
                  />
                  <span>
                    <span className="block font-bold">
                      {t(m === 'mock' ? 'settings.mode.mock' : 'settings.mode.live')}
                    </span>
                    <span className="block text-[15px] text-muted">
                      {t(m === 'mock' ? 'settings.mode.mock_hint' : 'settings.mode.live_hint')}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
            {mode === 'live' && config?.mode !== 'live' ? (
              <Notice tone="caution">{t('settings.mode.live_warning')}</Notice>
            ) : null}
            <Switch
              checked={privacy}
              onChange={setPrivacy}
              label={t('settings.privacy')}
              description={t('settings.privacy_hint')}
            />
            {needsPasscode && modeChanged && !config?.unlocked ? (
              <Field label={t('settings.passcode')} hint={t('settings.passcode_hint')}>
                {(p) => (
                  <TextInput
                    {...p}
                    type="password"
                    autoComplete="off"
                    value={passcode}
                    onChange={(e) => setPasscode(e.target.value)}
                  />
                )}
              </Field>
            ) : null}
            <div>
              <Button
                type="submit"
                variant="primary"
                busy={saving === 'mode'}
                disabled={!modeChanged}
              >
                {t('settings.mode.apply')}
              </Button>
            </div>

            <div className="rounded-[var(--radius-panel)] bg-paper p-5 shadow-[inset_0_0_0_1px_var(--color-line)]">
              <h3 className="text-lg font-bold">{t('settings.leaves.title')}</h3>
              <dl className="mt-3 flex flex-col gap-3">
                {(['mock', 'live', 'privacy'] as const).map((m) => (
                  <div
                    key={m}
                    className="grid gap-1 border-t border-line pt-3 sm:grid-cols-[8rem_1fr] sm:gap-4"
                  >
                    <dt className="font-bold">{t(`mode.${m}` as Key)}</dt>
                    <dd className="text-ink-soft">{t(`settings.leaves.${m}` as Key)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </form>
        </Section>

        <form onSubmit={submitGeneral} className="flex flex-col gap-10">
          <Section id="conv-title" title={t('settings.conversation')}>
            <div className="flex flex-col gap-6">
              <Field
                label={
                  <span className="flex justify-between gap-4">
                    {t('settings.tau')} <span className="tabular">{pct(tau)}</span>
                  </span>
                }
                hint={t('settings.tau_hint')}
              >
                {(p) => (
                  <input
                    {...p}
                    type="range"
                    min={0.5}
                    max={0.9}
                    step={0.05}
                    value={tau}
                    onChange={(e) => setTau(Number(e.target.value))}
                    className="h-11 w-full accent-[var(--color-ink)]"
                  />
                )}
              </Field>
              <Field
                label={
                  <span className="flex justify-between gap-4">
                    {t('settings.window')}{' '}
                    <span className="tabular">
                      {t('settings.seconds', { s: windowS.toFixed(1) })}
                    </span>
                  </span>
                }
                hint={t('settings.window_hint')}
              >
                {(p) => (
                  <input
                    {...p}
                    type="range"
                    min={2}
                    max={8}
                    step={0.5}
                    value={windowS}
                    onChange={(e) => setWindowS(Number(e.target.value))}
                    className="h-11 w-full accent-[var(--color-ink)]"
                  />
                )}
              </Field>
              <Field label={t('settings.language')} hint={t('settings.language_hint')}>
                {(p) => (
                  <Select
                    {...p}
                    value={language}
                    onChange={(e) => setLanguage(e.target.value as Lang)}
                  >
                    <option value="en">English</option>
                    <option value="id">Bahasa Indonesia</option>
                  </Select>
                )}
              </Field>
            </div>
          </Section>

          <Section id="budget-title" title={t('settings.budget')}>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label={t('settings.budget_cap')} hint={t('settings.budget_cap_hint')}>
                {(p) => (
                  <TextInput
                    {...p}
                    type="number"
                    inputMode="decimal"
                    min={1}
                    max={1000}
                    step={1}
                    value={budgetMax}
                    onChange={(e) => setBudgetMax(e.target.value)}
                  />
                )}
              </Field>
              <div className="flex flex-col gap-1.5">
                <span className="text-[15px] font-semibold">{t('settings.budget_spent')}</span>
                <span className="tabular text-2xl font-bold">
                  {config ? usd(config.budget.spent_usd) : '–'}
                  <span className="ml-2 text-base font-normal text-muted">
                    {config
                      ? t('settings.budget_level', {
                          p: pct(config.budget.fraction),
                          level: config.budget.level,
                        })
                      : ''}
                  </span>
                </span>
              </div>
            </div>
          </Section>

          <Section id="flags-title" title={t('settings.flags')}>
            <div className="flex flex-col gap-5">
              {FLAGS.map((f) => (
                <Switch
                  key={f.id}
                  checked={Boolean(flags[f.id])}
                  onChange={(v) => setFlags((s) => ({ ...s, [f.id]: v }))}
                  label={t(f.label)}
                  description={t(f.hint)}
                />
              ))}
              <Switch
                checked={keepClips}
                onChange={setKeepClips}
                label={t('settings.keep_clips')}
                description={t('settings.keep_clips_hint')}
              />
            </div>
          </Section>

          <div className="sticky bottom-0 -mx-4 border-t border-line bg-linen/95 px-4 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0">
            <Button
              type="submit"
              variant="primary"
              size="lg"
              busy={saving === 'general'}
              disabled={!config}
            >
              {t('settings.save')}
            </Button>
          </div>
        </form>
      </div>
    </Shell>
  );
}

/** Public deployment: live mode (real models, real cost) only for browsers with the passcode. */
function UnlockPanel({
  unlocked,
  publicLive,
  onChange,
}: {
  unlocked: boolean;
  publicLive: boolean;
  onChange: () => void;
}) {
  const t = useT();
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function unlock(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const { ok } = await api.unlock(value);
      if (ok) {
        setLivePasscode(value);
        setValue('');
        onChange();
      } else {
        setFailed(true);
      }
    } finally {
      setBusy(false);
    }
  }

  if (unlocked) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-panel)] bg-good-soft px-5 py-4">
        <p className="font-semibold text-good">{t('unlock.done')}</p>
        <Button
          variant="ghost"
          onClick={() => {
            setLivePasscode(null);
            onChange();
          }}
        >
          {t('unlock.lock')}
        </Button>
      </div>
    );
  }
  return (
    <form
      onSubmit={(e) => void unlock(e)}
      className="flex flex-col gap-3 rounded-[var(--radius-panel)] bg-paper p-5 shadow-[inset_0_0_0_1px_var(--color-line)]"
    >
      <p className="font-semibold">{t(publicLive ? 'unlock.title_public' : 'unlock.title')}</p>
      <p className="text-[15px] text-muted">
        {t(publicLive ? 'unlock.hint_public' : 'unlock.hint')}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('settings.passcode')}>
          {(p) => (
            <TextInput
              {...p}
              type="password"
              autoComplete="off"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" busy={busy} disabled={!value}>
          {t('unlock.button')}
        </Button>
      </div>
      {failed ? <Notice tone="error">{t('unlock.wrong')}</Notice> : null}
    </form>
  );
}
