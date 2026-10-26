import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { MemoryEntry, MemoryView, Patient } from '../api/types';
import { Button } from '../components/Button';
import { Field, Notice, Select, TextInput } from '../components/Form';
import { LineChart } from '../components/LineChart';
import { Badge, Section } from '../components/Section';
import { Shell } from '../components/Shell';
import { useT, type Key } from '../i18n';
import { clockTime, cx } from '../lib/format';

const SOURCE_KEYS: Record<string, Key> = {
  caregiver: 'memory.source.caregiver',
  transcript: 'memory.source.transcript',
  patient_confirmed: 'memory.source.patient_confirmed',
};

const CATEGORIES = ['fact', 'preference', 'habit', 'routine', 'person'] as const;

function EntryRow({
  entry,
  onDelete,
}: {
  entry: MemoryEntry;
  onDelete: (id: string) => Promise<void>;
}) {
  const t = useT();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!confirm) return;
    const id = window.setTimeout(() => setConfirm(false), 4000);
    return () => window.clearTimeout(id);
  }, [confirm]);
  const retired = entry.status !== 'approved';
  return (
    <li className="flex flex-col gap-2 py-4 sm:flex-row sm:items-start sm:gap-6">
      <div className="min-w-0 flex-1">
        <p
          className={cx('text-lg font-semibold leading-snug', retired && 'text-muted line-through')}
        >
          {entry.text}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-muted">
          <Badge
            tone={
              entry.source_type === 'caregiver'
                ? 'ink'
                : entry.source_type === 'patient_confirmed'
                  ? 'voice'
                  : 'neutral'
            }
          >
            {t(SOURCE_KEYS[entry.source_type] ?? 'memory.source.other')}
          </Badge>
          {entry.category ? <Badge tone="outline">{entry.category}</Badge> : null}
          <Badge tone={retired ? 'caution' : 'good'}>
            {retired ? t('memory.status.retired') : t('memory.status.approved')}
          </Badge>
          {entry.source_ref ? (
            <span className="break-all">
              {t('memory.ref')}: {entry.source_ref}
            </span>
          ) : null}
          <span className="tabular">
            {t('memory.added', {
              at:
                new Date(entry.created_at).toLocaleDateString() + ' ' + clockTime(entry.created_at),
            })}
          </span>
          {entry.last_used_at ? (
            <span className="tabular">
              {t('memory.used', { at: clockTime(entry.last_used_at) })}
            </span>
          ) : null}
        </div>
      </div>
      <Button
        variant={confirm ? 'danger' : 'ghost'}
        busy={busy}
        className="self-start"
        aria-label={confirm ? t('memory.delete_confirm') : `${t('memory.delete')}: ${entry.text}`}
        onClick={async () => {
          if (!confirm) {
            setConfirm(true);
            return;
          }
          setBusy(true);
          await onDelete(entry.id);
          setBusy(false);
        }}
      >
        {confirm ? t('memory.delete_confirm') : t('memory.delete')}
      </Button>
    </li>
  );
}

export default function Memory() {
  const { pid } = useParams<{ pid: string }>();
  const t = useT();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [data, setData] = useState<MemoryView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [category, setCategory] = useState<string>('fact');
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!pid) return;
    try {
      const [p, m] = await Promise.all([api.patient(pid), api.memory(pid)]);
      setPatient(p);
      setData(m);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [pid]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run<T>(key: string, fn: () => Promise<T>, done?: (r: T) => string | null) {
    setBusy(key);
    setStatus(null);
    try {
      const r = await fn();
      setStatus(done ? done(r) : null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function addFact(e: FormEvent) {
    e.preventDefault();
    if (!pid) return;
    if (!text.trim()) {
      setFormError(t('memory.form.empty'));
      return;
    }
    setFormError(null);
    setBusy('add');
    try {
      await api.addMemory(pid, text.trim(), category);
      setText('');
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const curve = data?.learning_curve ?? [];
  const maxY = Math.max(10, ...curve.map((c) => Math.ceil(c.mean_questions)));

  return (
    <Shell>
      <div className="flex flex-col gap-10">
        <div>
          <p className="text-sm text-muted">{patient?.display_name ?? ' '}</p>
          <h1 className="text-[34px] font-bold">{t('memory.title')}</h1>
          <p className="mt-1 max-w-[64ch] text-lg text-ink-soft">{t('memory.lead')}</p>
        </div>
        {error ? <Notice tone="error">{error}</Notice> : null}
        {status ? <Notice tone="good">{status}</Notice> : null}

        <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div className="flex min-w-0 flex-col gap-10">
            <Section
              id="ops-title"
              title={t('memory.ops.title')}
              meta={
                <Button
                  size="sm"
                  busy={busy === 'curate'}
                  onClick={() =>
                    pid &&
                    void run(
                      'curate',
                      () => api.curate(pid),
                      (r) => t('memory.curated', { n: r.proposed }),
                    )
                  }
                >
                  {t('memory.curate')}
                </Button>
              }
            >
              <p className="text-[15px] text-muted">{t('memory.ops.hint')}</p>
              {data && data.ops.length ? (
                <ul className="flex flex-col gap-3">
                  {data.ops.map((op) => (
                    <li
                      key={op.id}
                      className="flex flex-col gap-2 rounded-[var(--radius-panel)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={op.op === 'retire' ? 'caution' : 'ink'}>
                          {t(`memory.op.${op.op}` as Key)}
                        </Badge>
                        {op.category ? <Badge tone="outline">{op.category}</Badge> : null}
                      </div>
                      <p className="text-lg font-semibold">{op.text}</p>
                      {op.reason ? (
                        <p className="text-[15px] text-ink-soft">
                          {t('memory.op.reason', { r: op.reason })}
                        </p>
                      ) : null}
                      {op.source_refs.length ? (
                        <p className="text-sm text-muted">
                          {t('memory.op.cites')}{' '}
                          {op.source_refs.map((r) => (
                            <span key={r.id} className="mr-2 inline-block">
                              <strong className="tabular text-ink">{r.id}</strong>{' '}
                              <span className="break-all">{r.ref}</span>
                            </span>
                          ))}
                        </p>
                      ) : null}
                      <div className="flex gap-2">
                        <Button
                          variant="primary"
                          size="sm"
                          busy={busy === `a-${op.id}`}
                          onClick={() =>
                            pid && void run(`a-${op.id}`, () => api.approveOp(pid, op.id))
                          }
                        >
                          {t('memory.approve')}
                        </Button>
                        <Button
                          size="sm"
                          busy={busy === `r-${op.id}`}
                          onClick={() =>
                            pid && void run(`r-${op.id}`, () => api.rejectOp(pid, op.id))
                          }
                        >
                          {t('memory.reject')}
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="rounded-[var(--radius-control)] bg-wash px-4 py-3 text-ink-soft">
                  {t('memory.ops.empty')}
                </p>
              )}
            </Section>

            <Section
              id="entries-title"
              title={t('memory.entries.title')}
              meta={data ? t('memory.entries.count', { n: data.entries.length }) : undefined}
            >
              {data && data.entries.length ? (
                <ul className="flex flex-col divide-y divide-line">
                  {data.entries.map((e) => (
                    <EntryRow
                      key={e.id}
                      entry={e}
                      onDelete={async (id) => {
                        if (!pid) return;
                        await run(`d-${id}`, () => api.deleteMemory(pid, id));
                      }}
                    />
                  ))}
                </ul>
              ) : (
                <p className="text-ink-soft">{t('memory.entries.empty')}</p>
              )}
            </Section>
          </div>

          <div className="flex min-w-0 flex-col gap-10">
            <Section id="add-title" title={t('memory.form.title')}>
              <form onSubmit={(e) => void addFact(e)} className="flex flex-col gap-4" noValidate>
                <Field label={t('memory.form.text')} hint={t('memory.form.hint')} error={formError}>
                  {(p) => (
                    <TextInput
                      {...p}
                      value={text}
                      maxLength={200}
                      onChange={(e) => setText(e.target.value)}
                    />
                  )}
                </Field>
                <Field label={t('memory.form.category')}>
                  {(p) => (
                    <Select {...p} value={category} onChange={(e) => setCategory(e.target.value)}>
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                          {t(`memory.category.${c}` as Key)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <div>
                  <Button type="submit" variant="primary" busy={busy === 'add'}>
                    {t('memory.form.save')}
                  </Button>
                </div>
              </form>
            </Section>

            <Section id="curve-title" title={t('memory.curve.title')}>
              <p className="text-[15px] text-muted">{t('memory.curve.hint')}</p>
              {curve.length ? (
                <>
                  <div className="rounded-[var(--radius-panel)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]">
                    <LineChart
                      title={t('memory.curve.title')}
                      series={[
                        {
                          id: 'q',
                          label: t('memory.curve.series'),
                          color: '#2a78d6',
                          points: curve.map((c, i) => ({ x: i + 1, y: c.mean_questions })),
                        },
                      ]}
                      xDomain={[1, Math.max(2, curve.length)]}
                      yDomain={[0, maxY]}
                      xTicks={curve.map((_, i) => i + 1)}
                      yTicks={[0, Math.round(maxY / 2), maxY]}
                      formatX={(v) => t('memory.curve.session', { n: v })}
                      formatY={(v) => (Number.isInteger(v) ? String(v) : v.toFixed(1))}
                      xLabel={t('memory.curve.x')}
                    />
                  </div>
                  <details className="text-[15px]">
                    <summary className="min-h-11 cursor-pointer py-2 font-semibold">
                      {t('chart.table')}
                    </summary>
                    <table className="w-full">
                      <thead>
                        <tr className="text-left text-sm text-muted">
                          <th scope="col" className="py-1 font-semibold">
                            {t('memory.curve.x')}
                          </th>
                          <th scope="col" className="py-1 text-right font-semibold">
                            {t('memory.curve.messages')}
                          </th>
                          <th scope="col" className="py-1 text-right font-semibold">
                            {t('memory.curve.series')}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {curve.map((c, i) => (
                          <tr key={c.session_id} className="border-t border-line">
                            <td className="py-1">{t('memory.curve.session', { n: i + 1 })}</td>
                            <td className="tabular py-1 text-right">{c.messages}</td>
                            <td className="tabular py-1 text-right">
                              {c.mean_questions.toFixed(1)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                </>
              ) : (
                <p className="rounded-[var(--radius-control)] bg-wash px-4 py-3 text-ink-soft">
                  {t('memory.curve.empty')}
                </p>
              )}
            </Section>
          </div>
        </div>
      </div>
    </Shell>
  );
}
