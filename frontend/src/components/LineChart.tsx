import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

export interface ChartSeries {
  id: string;
  label: string;
  color: string;
  dash?: string;
  points: { x: number; y: number }[];
}

interface Props {
  title: string;
  series: ChartSeries[];
  xDomain: [number, number];
  yDomain: [number, number];
  xTicks: number[];
  yTicks: number[];
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  xLabel?: string;
  height?: number;
}

const W = 360;
const PAD = { top: 12, right: 14, bottom: 34, left: 40 };

/** Small hand-made SVG line chart with a crosshair readout (pointer and keyboard). */
export function LineChart({
  title,
  series,
  xDomain,
  yDomain,
  xTicks,
  yTicks,
  formatX,
  formatY,
  xLabel,
  height = 220,
}: Props) {
  const id = useId();
  const wrap = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const H = height;
  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const sx = (v: number) => PAD.left + ((v - xDomain[0]) / (xDomain[1] - xDomain[0] || 1)) * iw;
  const sy = (v: number) => PAD.top + ih - ((v - yDomain[0]) / (yDomain[1] - yDomain[0] || 1)) * ih;

  const xs = useMemo(
    () => [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b),
    [series],
  );

  function nearest(clientX: number) {
    const el = wrap.current;
    if (!el || !xs.length) return;
    const rect = el.getBoundingClientRect();
    const vx = ((clientX - rect.left) / rect.width) * W;
    let best = 0;
    xs.forEach((x, i) => {
      if (Math.abs(sx(x) - vx) < Math.abs(sx(xs[best] ?? 0) - vx)) best = i;
    });
    setActive(best);
  }

  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    if (!xs.length) return;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      setActive((a) => Math.min(xs.length - 1, (a ?? -1) + 1));
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setActive((a) => Math.max(0, (a ?? 1) - 1));
    } else if (e.key === 'Escape') {
      setActive(null);
    }
  }

  const ax = active !== null ? xs[active] : undefined;
  const readout =
    ax === undefined
      ? []
      : series
          .map((s) => ({ s, p: s.points.find((p) => p.x === ax) }))
          .filter((r): r is { s: ChartSeries; p: { x: number; y: number } } => Boolean(r.p))
          .sort((a, b) => b.p.y - a.p.y);
  const leftPct = ax === undefined ? 0 : (sx(ax) / W) * 100;

  return (
    <div ref={wrap} className="relative w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full touch-pan-y overflow-visible"
        role="img"
        aria-labelledby={`${id}-t`}
        tabIndex={0}
        onPointerMove={(e: PointerEvent<SVGSVGElement>) => nearest(e.clientX)}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive((a) => a ?? 0)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        <title id={`${id}-t`}>{title}</title>
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={sy(v)}
              y2={sy(v)}
              stroke="rgb(15 46 53 / 0.1)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 6}
              y={sy(v)}
              dy="0.32em"
              textAnchor="end"
              fontSize={12}
              fill="#4e666c"
              className="tabular"
            >
              {formatY(v)}
            </text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text
            key={`x${v}`}
            x={sx(v)}
            y={H - PAD.bottom + 16}
            textAnchor="middle"
            fontSize={12}
            fill="#4e666c"
            className="tabular"
          >
            {formatX(v)}
          </text>
        ))}
        {xLabel ? (
          <text x={PAD.left + iw / 2} y={H - 4} textAnchor="middle" fontSize={12} fill="#4e666c">
            {xLabel}
          </text>
        ) : null}
        {ax !== undefined ? (
          <line
            x1={sx(ax)}
            x2={sx(ax)}
            y1={PAD.top}
            y2={PAD.top + ih}
            stroke="#0f2e35"
            strokeOpacity={0.35}
            strokeWidth={1}
          />
        ) : null}
        {series.map((s) => (
          <g key={s.id}>
            <polyline
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={s.dash}
              points={s.points.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ')}
            />
            {s.points.map((p) =>
              p.x === ax || s.points.length === 1 ? (
                <circle
                  key={p.x}
                  cx={sx(p.x)}
                  cy={sy(p.y)}
                  r={4}
                  fill={s.color}
                  stroke="#ffffff"
                  strokeWidth={2}
                />
              ) : null,
            )}
          </g>
        ))}
      </svg>
      {ax !== undefined && readout.length ? (
        <div
          className="pointer-events-none absolute top-1 z-10 min-w-[10rem] rounded-[8px] bg-paper px-3 py-2 text-[13px] shadow-[0_0_0_1px_var(--color-line-strong),0_6px_16px_-6px_rgb(15_46_53/0.25)]"
          style={{
            left: `${leftPct}%`,
            transform: leftPct > 55 ? 'translateX(calc(-100% - 10px))' : 'translateX(10px)',
          }}
        >
          <p className="mb-1 text-muted">{formatX(ax)}</p>
          <ul className="flex flex-col gap-0.5">
            {readout.map(({ s, p }) => (
              <li key={s.id} className="flex items-center gap-2">
                <svg width="16" height="4" aria-hidden="true">
                  <line
                    x1="0"
                    x2="16"
                    y1="2"
                    y2="2"
                    stroke={s.color}
                    strokeWidth="2"
                    strokeDasharray={s.dash}
                  />
                </svg>
                <strong className="tabular">{formatY(p.y)}</strong>
                <span className="text-ink-soft">{s.label}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function LegendKey({ color, dash }: { color: string; dash?: string }) {
  return (
    <svg width="22" height="6" aria-hidden="true" className="shrink-0">
      <line
        x1="1"
        x2="21"
        y1="3"
        y2="3"
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={dash}
      />
    </svg>
  );
}
