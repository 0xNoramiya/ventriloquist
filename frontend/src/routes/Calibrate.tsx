import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { CalibrationSummary, FramingResult, Lang, Patient, SignalSpec } from '../api/types';
import { Button } from '../components/Button';
import { Field, Notice, Select, TextInput } from '../components/Form';
import { Shell } from '../components/Shell';
import { useT, type Key } from '../i18n';
import { cx, pct } from '../lib/format';
import {
  cameraSupported,
  grabFrame,
  recordClip,
  recorderMime,
  startCamera,
  stopStream,
} from '../lib/media';
import { speak } from '../lib/speech';
import { Photo } from '../components/Photo';
import { SignalPicker } from '../components/SignalPicker';
import { useConfig } from '../lib/useConfig';

type Label = 'rest' | 'yes' | 'no' | 'emergency';

const TASKS: { label: Label; count: number; ms: number; say: Key; title: Key; body: Key }[] = [
  {
    label: 'rest',
    count: 1,
    ms: 15000,
    say: 'cal.say.rest',
    title: 'cal.task.rest',
    body: 'cal.task.rest_body',
  },
  {
    label: 'yes',
    count: 3,
    ms: 4000,
    say: 'cal.say.yes',
    title: 'cal.task.yes',
    body: 'cal.task.yes_body',
  },
  {
    label: 'no',
    count: 3,
    ms: 4000,
    say: 'cal.say.no',
    title: 'cal.task.no',
    body: 'cal.task.no_body',
  },
  {
    label: 'emergency',
    count: 1,
    ms: 4000,
    say: 'cal.say.emergency',
    title: 'cal.task.emergency',
    body: 'cal.task.emergency_body',
  },
];

const HINTS = ['', 'eyebrows', 'blink', 'finger', 'nod'] as const;

type Step = 'intro' | 'framing' | 'record' | 'finalize' | 'results';
const STEPS: Step[] = ['intro', 'framing', 'record', 'finalize', 'results'];

export default function Calibrate() {
  const { pid } = useParams<{ pid: string }>();
  const t = useT();
  const navigate = useNavigate();
  // In live mode the camera still reads answers without calibration (blind judge only).
  const liveMode = useConfig().config?.mode === 'live';
  const [patient, setPatient] = useState<Patient | null>(null);
  const [step, setStep] = useState<Step>('intro');
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [framing, setFraming] = useState<FramingResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<Label, number>>({
    rest: 0,
    yes: 0,
    no: 0,
    emergency: 0,
  });
  const [phase, setPhase] = useState<
    | { kind: 'countdown'; n: number }
    | { kind: 'recording'; ms: number }
    | { kind: 'uploading' }
    | null
  >(null);
  const [hint, setHint] = useState<string>('');
  const [result, setResult] = useState<CalibrationSummary | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const lang: Lang = patient?.language ?? 'en';

  useEffect(() => {
    if (!pid) return;
    api
      .patient(pid)
      .then(setPatient)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [pid]);

  useEffect(() => {
    const video = videoRef.current;
    if (video && stream) {
      video.srcObject = stream;
      void video.play().catch(() => undefined);
    }
  }, [stream, step]);

  useEffect(() => () => stopStream(stream), [stream]);

  const enableCamera = useCallback(async () => {
    setError(null);
    try {
      const s = await startCamera();
      setStream(s);
      setStep('framing');
    } catch (e) {
      setError(t('cal.camera_denied', { reason: e instanceof Error ? e.message : String(e) }));
    }
  }, [t]);

  async function checkFraming() {
    if (!pid || !videoRef.current) return;
    setBusy('framing');
    setError(null);
    try {
      const frame = await grabFrame(videoRef.current);
      setFraming(await api.framing(pid, frame));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const nextTask = TASKS.find((task) => counts[task.label] < task.count) ?? null;

  async function recordNext() {
    if (!pid || !stream || !nextTask) return;
    setError(null);
    speak(t(nextTask.say), lang);
    for (let n = 3; n >= 1; n -= 1) {
      setPhase({ kind: 'countdown', n });
      await new Promise((r) => window.setTimeout(r, 1000));
    }
    setPhase({ kind: 'recording', ms: nextTask.ms });
    try {
      const clip = await recordClip(stream, nextTask.ms);
      setPhase({ kind: 'uploading' });
      const res = await api.calibrationClip(pid, nextTask.label, clip);
      setCounts((c) => ({ ...c, ...(res.counts as Partial<Record<Label, number>>) }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPhase(null);
    }
  }

  async function restart() {
    if (!pid) return;
    setBusy('restart');
    try {
      await api.resetCalibrationClips(pid);
      setCounts({ rest: 0, yes: 0, no: 0, emergency: 0 });
      setResult(null);
      setStep(stream ? 'record' : 'intro');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function finalize(skip: boolean) {
    if (!pid) return;
    setBusy(skip ? 'skip' : 'finalize');
    setError(null);
    try {
      const res = await api.finalizeCalibration(
        pid,
        skip ? { skip: true, hint: hint || undefined } : { hint: hint || undefined },
      );
      setResult(res);
      setStep('results');
      stopStream(stream);
      setStream(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function startSession() {
    if (!pid) return;
    setBusy('session');
    try {
      const snap = await api.createSession({ patient_id: pid });
      navigate(`/caregiver/${snap.session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  const stepIndex = STEPS.indexOf(step);

  return (
    <Shell>
      <div className="mx-auto flex max-w-[960px] flex-col gap-6">
        <div>
          <p className="text-sm text-muted">{patient ? patient.display_name : ' '}</p>
          <h1 className="text-[34px] font-bold">{t('cal.title')}</h1>
          <p className="mt-1 max-w-[62ch] text-lg text-ink-soft">{t('cal.lead')}</p>
        </div>

        <ol className="flex flex-wrap gap-x-6 gap-y-2" aria-label={t('cal.progress')}>
          {(
            [
              'cal.step.intro',
              'cal.step.framing',
              'cal.step.record',
              'cal.step.finalize',
              'cal.step.results',
            ] as const
          ).map((k, i) => (
            <li
              key={k}
              aria-current={i === stepIndex ? 'step' : undefined}
              className={cx(
                'flex items-center gap-2 text-[15px]',
                i === stepIndex
                  ? 'font-bold text-ink'
                  : i < stepIndex
                    ? 'text-ink-soft'
                    : 'text-muted',
              )}
            >
              <span
                className={cx(
                  'tabular inline-flex size-7 items-center justify-center rounded-full text-sm font-bold',
                  i === stepIndex
                    ? 'bg-ink text-paper'
                    : i < stepIndex
                      ? 'bg-wash text-ink'
                      : 'text-muted shadow-[inset_0_0_0_1px_var(--color-line-strong)]',
                )}
              >
                {i + 1}
              </span>
              {t(k)}
            </li>
          ))}
        </ol>

        {error ? <Notice tone="error">{error}</Notice> : null}

        {step === 'intro' ? (
          <div className="flex flex-col gap-8">
            <div className="grid items-start gap-6 md:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] md:gap-8">
              <div className="flex flex-col gap-6">
                <ul className="flex max-w-[62ch] list-disc flex-col gap-2 pl-5 text-ink-soft">
                  <li>{t('cal.intro.1')}</li>
                  <li>{t('cal.intro.2')}</li>
                  <li>{t('cal.intro.3')}</li>
                </ul>
                <div className="flex max-w-[62ch] flex-col gap-1">
                  <h2 className="text-lg font-bold">{t('cal.mount.title')}</h2>
                  <p className="text-ink-soft">{t('cal.mount.body')}</p>
                </div>
              </div>
              <figure className="flex flex-col gap-2">
                <Photo
                  name="phone-mount"
                  widths={[600, 1200]}
                  ratio={2336 / 1744}
                  sizes="(min-width: 768px) 40vw, 100vw"
                  alt={t('cal.mount.alt')}
                  className="rounded-[var(--radius-panel)] bg-wash"
                />
                <figcaption className="text-sm text-muted">{t('cal.mount.caption')}</figcaption>
              </figure>
            </div>
            <SignalPicker value={hint} onChange={setHint} />
            {!cameraSupported() ? <Notice tone="caution">{t('cal.no_camera')}</Notice> : null}
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button
                variant="primary"
                size="lg"
                disabled={!cameraSupported()}
                onClick={() => void enableCamera()}
              >
                {t('cal.enable_camera')}
              </Button>
              <Button size="lg" busy={busy === 'skip'} onClick={() => void finalize(true)}>
                {t(liveMode ? 'cal.skip_live' : 'cal.skip')}
              </Button>
            </div>
            <p className="text-[15px] text-muted">
              {t(liveMode ? 'cal.skip_live_hint' : 'cal.skip_hint')}
            </p>
          </div>
        ) : null}

        {step === 'framing' || step === 'record' ? (
          <div className="grid items-start gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="relative overflow-hidden rounded-[var(--radius-panel)] bg-night">
              <video
                ref={videoRef}
                muted
                playsInline
                className="aspect-[4/3] w-full -scale-x-100 object-cover"
                aria-label={t('cal.preview')}
              />
              {phase ? (
                <div
                  className="absolute inset-0 flex flex-col items-center justify-center bg-night/55 text-paper"
                  aria-live="assertive"
                >
                  {phase.kind === 'countdown' ? (
                    <span className="tabular text-[120px] font-bold leading-none">{phase.n}</span>
                  ) : phase.kind === 'recording' ? (
                    <>
                      <span className="flex items-center gap-3 text-2xl font-bold">
                        <span className="size-4 rounded-full bg-alarm" aria-hidden="true" />
                        {t('cal.recording')}
                      </span>
                      <div className="absolute inset-x-0 bottom-0 h-2 bg-night-3">
                        <div
                          className="fill-bar h-full bg-voice"
                          style={{ ['--fill-ms' as string]: `${phase.ms}ms` }}
                        />
                      </div>
                    </>
                  ) : (
                    <span className="text-xl font-semibold">{t('cal.uploading')}</span>
                  )}
                </div>
              ) : null}
            </div>

            {step === 'framing' ? (
              <div className="flex flex-col gap-4">
                <h2 className="text-2xl font-bold">{t('cal.framing.title')}</h2>
                <p className="text-ink-soft">{t('cal.framing.body')}</p>
                <div>
                  <Button
                    variant="primary"
                    busy={busy === 'framing'}
                    onClick={() => void checkFraming()}
                  >
                    {t('cal.framing.check')}
                  </Button>
                </div>
                {framing ? (
                  <div className="flex flex-col gap-2 rounded-[var(--radius-control)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]">
                    <Check ok={framing.face_visible} label={t('cal.framing.face')} />
                    <Check ok={framing.upper_body_visible} label={t('cal.framing.body_visible')} />
                    <Check ok={framing.lighting_ok} label={t('cal.framing.light')} />
                    {framing.advice ? (
                      <p className="mt-1 text-[15px] text-ink-soft">{framing.advice}</p>
                    ) : null}
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-3">
                  <Button
                    variant={framing ? 'primary' : 'secondary'}
                    onClick={() => setStep('record')}
                  >
                    {framing ? t('cal.next') : t('cal.framing.skip')}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {nextTask ? (
                  <>
                    <h2 className="text-2xl font-bold">
                      {t(nextTask.title)}{' '}
                      <span className="tabular font-normal text-muted">
                        {t('cal.count', { n: counts[nextTask.label] + 1, of: nextTask.count })}
                      </span>
                    </h2>
                    <p className="text-ink-soft">{t(nextTask.body)}</p>
                    <div>
                      <Button
                        variant="primary"
                        size="lg"
                        disabled={phase !== null}
                        onClick={() => void recordNext()}
                      >
                        {phase ? t('cal.recording') : t('cal.record', { s: nextTask.ms / 1000 })}
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <h2 className="text-2xl font-bold">{t('cal.all_recorded')}</h2>
                    <div>
                      <Button variant="primary" size="lg" onClick={() => setStep('finalize')}>
                        {t('cal.next')}
                      </Button>
                    </div>
                  </>
                )}
                <ul className="flex flex-col gap-1.5 text-[15px]">
                  {TASKS.map((task) => (
                    <li
                      key={task.label}
                      className="flex items-center justify-between gap-3 border-t border-line pt-1.5"
                    >
                      <span>{t(task.title)}</span>
                      <span className="tabular font-semibold">
                        {Math.min(counts[task.label], task.count)} / {task.count}
                      </span>
                    </li>
                  ))}
                </ul>
                {!recorderMime() ? <Notice tone="caution">{t('cal.no_recorder')}</Notice> : null}
                <p className="text-sm text-muted">{t('cal.mirror_note')}</p>
              </div>
            )}
          </div>
        ) : null}

        {step === 'finalize' ? (
          <div className="flex max-w-[640px] flex-col gap-5">
            <h2 className="text-2xl font-bold">{t('cal.finalize.title')}</h2>
            <p className="text-ink-soft">{t('cal.finalize.body')}</p>
            <Field label={t('cal.hint')} hint={t('cal.hint_hint')}>
              {(p) => (
                <Select {...p} value={hint} onChange={(e) => setHint(e.target.value)}>
                  {HINTS.map((h) => (
                    <option key={h} value={h}>
                      {t(`cal.hint.${h || 'none'}` as Key)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div>
              <Button
                variant="primary"
                size="lg"
                busy={busy === 'finalize'}
                onClick={() => void finalize(false)}
              >
                {t('cal.finalize.go')}
              </Button>
            </div>
          </div>
        ) : null}

        {step === 'results' && result && pid ? (
          <Results
            pid={pid}
            result={result}
            onChange={setResult}
            onRestart={() => void restart()}
            onStart={() => void startSession()}
            busy={busy}
          />
        ) : null}
      </div>
    </Shell>
  );
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  const t = useT();
  return (
    <p className="flex items-center gap-2">
      <span
        className={cx(
          'inline-flex size-6 items-center justify-center rounded-full text-sm font-bold',
          ok ? 'bg-good-soft text-good' : 'bg-alarm-soft text-alarm-deep',
        )}
        aria-hidden="true"
      >
        {ok ? '✓' : '✕'}
      </span>
      <span>
        {label}: <strong>{ok ? t('cal.ok') : t('cal.not_ok')}</strong>
      </span>
    </p>
  );
}

function Results({
  pid,
  result,
  onChange,
  onRestart,
  onStart,
  busy,
}: {
  pid: string;
  result: CalibrationSummary;
  onChange: (r: CalibrationSummary) => void;
  onRestart: () => void;
  onStart: () => void;
  busy: string | null;
}) {
  const t = useT();
  const [draft, setDraft] = useState({
    yes: { ...result.description.yes },
    no: { ...result.description.no },
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onChange(await api.editDescription(pid, draft));
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const edit = (which: 'yes' | 'no', key: keyof SignalSpec, value: string) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [which]: { ...d[which], [key]: value } }));
  };

  const sources = Object.entries(result.accuracy);
  return (
    <div className="flex flex-col gap-6">
      {result.skipped ? (
        <Notice tone="info">{t('cal.results.skipped')}</Notice>
      ) : result.ok ? (
        <Notice tone="good">{t('cal.results.ok')}</Notice>
      ) : (
        <Notice tone="caution">
          <p className="font-semibold">{t('cal.results.not_ok')}</p>
          {result.suggestion ? <p className="mt-1">{result.suggestion}</p> : null}
        </Notice>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {(['yes', 'no'] as const).map((which) => (
          <fieldset
            key={which}
            className="flex flex-col gap-3 rounded-[var(--radius-panel)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]"
          >
            <legend className="sr-only">
              {which === 'yes' ? t('answer.YES') : t('answer.NO')}
            </legend>
            <p className="text-xl font-bold" aria-hidden="true">
              {which === 'yes' ? t('answer.YES') : t('answer.NO')}
            </p>
            <Field label={t('cal.desc.body_part')}>
              {(p) => (
                <TextInput
                  {...p}
                  value={draft[which].body_part}
                  maxLength={60}
                  onChange={(e) => edit(which, 'body_part', e.target.value)}
                />
              )}
            </Field>
            <Field label={t('cal.desc.motion')}>
              {(p) => (
                <TextInput
                  {...p}
                  value={draft[which].motion}
                  maxLength={120}
                  onChange={(e) => edit(which, 'motion', e.target.value)}
                />
              )}
            </Field>
            <Field label={t('cal.desc.description')}>
              {(p) => (
                <TextInput
                  {...p}
                  value={draft[which].description}
                  maxLength={240}
                  onChange={(e) => edit(which, 'description', e.target.value)}
                />
              )}
            </Field>
          </fieldset>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button busy={saving} onClick={() => void save()}>
          {t('cal.desc.save')}
        </Button>
        {saved ? (
          <span role="status" className="text-[15px] text-good">
            {t('cal.desc.saved')}
          </span>
        ) : null}
        {error ? (
          <span role="alert" className="text-[15px] text-alarm">
            {error}
          </span>
        ) : null}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-lg font-bold">{t('cal.results.accuracy')}</h3>
          {sources.length ? (
            <table className="w-full text-[15px]">
              <tbody>
                {sources.map(([k, v]) => (
                  <tr key={k} className="border-t border-line">
                    <th scope="row" className="py-1.5 text-left font-semibold">
                      {t(
                        k === 'spark' && result.mode === 'privacy'
                          ? 'source.spark_open'
                          : (`source.${k}` as Key),
                      )}
                    </th>
                    <td className="tabular py-1.5 text-right">{pct(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-muted">{t('cal.results.no_accuracy')}</p>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-lg font-bold">{t('cal.results.errors')}</h3>
          <table className="w-full text-[15px]">
            <tbody>
              <tr className="border-t border-line">
                <th scope="row" className="py-1.5 text-left font-semibold">
                  {t('cal.results.a')}
                </th>
                <td className="tabular py-1.5 text-right">{pct(result.error_rates.a)}</td>
              </tr>
              <tr className="border-t border-line">
                <th scope="row" className="py-1.5 text-left font-semibold">
                  {t('cal.results.b')}
                </th>
                <td className="tabular py-1.5 text-right">{pct(result.error_rates.b)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button variant="primary" size="lg" busy={busy === 'session'} onClick={onStart}>
          {t('cal.start_session')}
        </Button>
        <Button size="lg" busy={busy === 'restart'} onClick={onRestart}>
          {t('cal.again')}
        </Button>
      </div>
    </div>
  );
}
