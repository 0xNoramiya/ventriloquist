import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { SimResult, SimResults } from '../api/types';
import { Button } from '../components/Button';
import { Notice } from '../components/Form';
import { LegendKey, LineChart, type ChartSeries } from '../components/LineChart';
import { Shell } from '../components/Shell';
import { useT, type Key } from '../i18n';
import { cx, pct } from '../lib/format';

// Fixed slot per strategy (validated categorical order). Baselines also get a dash pattern so
// identity never rests on color alone.
const STRATEGIES: { id: string; color: string; dash?: string; label: Key }[] = [
  { id: 'eig_context_personal', color: '#2a78d6', label: 'eval.s.eig_context_personal' },
  { id: 'eig_context', color: '#eb6834', label: 'eval.s.eig_context' },
  { id: 'eig', color: '#1baf7a', label: 'eval.s.eig' },
  { id: 'board', color: '#eda100', dash: '6 4', label: 'eval.s.board' },
  { id: 'random', color: '#e87ba4', dash: '1.5 4', label: 'eval.s.random' },
];

const CONTEXTS: { id: string; label: Key }[] = [
  { id: 'none', label: 'eval.ctx.none' },
  { id: 'weak', label: 'eval.ctx.weak' },
  { id: 'strong', label: 'eval.ctx.strong' },
];

type Metric = 'mean_q' | 'success_rate';

function value(r: SimResult, metric: Metric): number | null {
  const v = r[metric];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

export default function Eval() {
  const t = useT();
  const [data, setData] = useState<SimResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>('mean_q');
  const [running, setRunning] = useState(false);
  const [quick, setQuick] = useState(false);

  useEffect(() => {
    api
      .simResults()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function runQuick() {
    setRunning(true);
    setError(null);
    try {
      setData(await api.runSim(150));
      setQuick(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const results = data?.results ?? [];
  const noises = [...new Set(results.map((r) => r.noise))].sort((a, b) => a - b);
  const maxNoise = noises[noises.length - 1] ?? 0.2;
  const meanQs = results.map((r) => value(r, 'mean_q')).filter((v): v is number => v !== null);
  const yMin = metric === 'success_rate' ? 0 : Math.max(0, Math.floor(Math.min(...meanQs, 4)) - 1);
  const yMax = metric === 'success_rate' ? 1 : Math.ceil(Math.max(...meanQs, 8));
  const fmtY = (v: number) =>
    metric === 'success_rate' ? pct(v) : Number.isInteger(v) ? String(v) : v.toFixed(1);

  function seriesFor(ctx: string): ChartSeries[] {
    return STRATEGIES.map((s) => ({
      id: s.id,
      label: t(s.label),
      color: s.color,
      dash: s.dash,
      points: results
        .filter((r) => r.context === ctx && r.strategy === s.id)
        .map((r) => ({ x: r.noise, y: value(r, metric) }))
        .filter((p): p is { x: number; y: number } => p.y !== null)
        .sort((a, b) => a.x - b.x),
    }));
  }

  return (
    <Shell>
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-3">
          <h1 className="text-[34px] font-bold">{t('eval.title')}</h1>
          <p>
            <span className="inline-flex rounded-[var(--radius-chip)] bg-caution-soft px-2.5 py-1 font-bold text-caution">
              {t('eval.label')}
            </span>
          </p>
          <p className="max-w-[68ch] text-lg text-ink-soft">{t('eval.lead')}</p>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div
            role="group"
            aria-label={t('eval.metric')}
            className="inline-flex rounded-[var(--radius-control)] bg-paper p-1 shadow-[inset_0_0_0_1px_var(--color-line)]"
          >
            {(['mean_q', 'success_rate'] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={metric === m}
                onClick={() => setMetric(m)}
                className={cx(
                  'min-h-11 rounded-[7px] px-3 font-semibold transition-colors duration-150',
                  metric === m ? 'bg-ink text-paper' : 'text-ink-soft hover:bg-wash',
                )}
              >
                {t(m === 'mean_q' ? 'eval.metric.mean_q' : 'eval.metric.success')}
              </button>
            ))}
          </div>
          <Button busy={running} onClick={() => void runQuick()}>
            {running ? t('eval.running') : t('eval.run')}
          </Button>
          {data ? (
            <p className="text-[15px] text-muted">
              {quick
                ? t('eval.quick_source', { n: data.trials })
                : t('eval.saved_source', { n: data.trials, seed: data.seed })}
            </p>
          ) : null}
        </div>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <ul className="flex flex-wrap gap-x-5 gap-y-2" aria-label={t('eval.legend')}>
          {STRATEGIES.map((s) => (
            <li key={s.id} className="flex items-center gap-2 text-[15px]">
              <LegendKey color={s.color} dash={s.dash} />
              {t(s.label)}
            </li>
          ))}
        </ul>

        {results.length ? (
          <div className={cx('grid gap-6 md:grid-cols-3', running && 'opacity-50')}>
            {CONTEXTS.map((c) => (
              <figure
                key={c.id}
                className="flex flex-col gap-2 rounded-[var(--radius-panel)] bg-paper p-4 shadow-[inset_0_0_0_1px_var(--color-line)]"
              >
                <figcaption className="font-bold">{t(c.label)}</figcaption>
                <LineChart
                  title={`${t(c.label)}: ${t(metric === 'mean_q' ? 'eval.metric.mean_q' : 'eval.metric.success')}`}
                  series={seriesFor(c.id)}
                  xDomain={[0, maxNoise]}
                  yDomain={[yMin, yMax]}
                  xTicks={noises}
                  yTicks={
                    metric === 'success_rate'
                      ? [0, 0.25, 0.5, 0.75, 1]
                      : Array.from({ length: yMax - yMin + 1 }, (_, i) => yMin + i)
                  }
                  formatX={(v) => pct(v)}
                  formatY={fmtY}
                  xLabel={t('eval.x')}
                />
              </figure>
            ))}
          </div>
        ) : !error ? (
          <p className="text-muted">{t('eval.loading')}</p>
        ) : null}

        {results.length ? (
          <details className="text-[15px]">
            <summary className="min-h-11 cursor-pointer py-2 font-semibold">
              {t('chart.table')}
            </summary>
            <div className="overflow-x-auto">
              <table className="w-full text-sm sm:text-[15px]">
                <thead>
                  <tr className="text-left text-sm text-muted">
                    <th scope="col" className="py-1 font-semibold">
                      {t('eval.table.context')}
                    </th>
                    <th scope="col" className="py-1 font-semibold">
                      {t('eval.table.strategy')}
                    </th>
                    <th scope="col" className="py-1 text-right font-semibold">
                      {t('eval.x')}
                    </th>
                    <th scope="col" className="py-1 text-right font-semibold">
                      {t('eval.metric.mean_q')}
                    </th>
                    <th scope="col" className="py-1 text-right font-semibold">
                      {t('eval.metric.success')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {CONTEXTS.flatMap((c) =>
                    STRATEGIES.flatMap((s) =>
                      results
                        .filter((r) => r.context === c.id && r.strategy === s.id)
                        .sort((a, b) => a.noise - b.noise)
                        .map((r) => (
                          <tr key={`${c.id}-${s.id}-${r.noise}`} className="border-t border-line">
                            <td className="py-1">{t(c.label)}</td>
                            <td className="py-1">{t(s.label)}</td>
                            <td className="tabular py-1 text-right">{pct(r.noise)}</td>
                            <td className="tabular py-1 text-right">
                              {value(r, 'mean_q')?.toFixed(2) ?? '–'}
                            </td>
                            <td className="tabular py-1 text-right">{pct(r.success_rate)}</td>
                          </tr>
                        )),
                    ),
                  )}
                </tbody>
              </table>
            </div>
          </details>
        ) : null}

        <div className="grid gap-6 border-t border-line pt-8 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <h2 className="text-xl font-bold">{t('eval.how.title')}</h2>
            <p className="max-w-[62ch] text-ink-soft">{t('eval.how.body')}</p>
          </div>
          <div className="flex flex-col gap-2">
            <h2 className="text-xl font-bold">{t('eval.detector.title')}</h2>
            <p className="max-w-[62ch] text-ink-soft">{t('eval.detector.body')}</p>
            <p>
              <code className="rounded-[var(--radius-chip)] bg-wash px-2 py-1 text-[15px]">
                python scripts/eval_detector.py
              </code>
            </p>
          </div>
        </div>
      </div>
    </Shell>
  );
}
