import { useEffect, useRef } from 'react';
import type { Overlay } from '../../api/types';
import { useT } from '../../i18n';

function providerLabel(provider: string): string {
  if (provider === 'meta' || provider === 'modal' || provider.startsWith('sam')) return 'SAM 3.1';
  if (provider === 'local') return 'Local motion';
  return provider;
}

const W = 320;
const H = 240;

function draw(ctx: CanvasRenderingContext2D, overlay: Overlay, frameIndex: number) {
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#e5ecea';
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = 'rgba(15,46,53,0.08)';
  ctx.lineWidth = 1;
  for (let x = 0; x <= W; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, H);
    ctx.stroke();
  }
  for (let y = 0; y <= H; y += 32) {
    ctx.beginPath();
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(W, y + 0.5);
    ctx.stroke();
  }
  const frame = overlay.frames[frameIndex];
  if (!frame) return;
  ctx.font = '600 12px "Atkinson Hyperlegible Next Variable", system-ui, sans-serif';
  for (const obj of frame.objects) {
    const [x0, y0, x1, y1] = obj.box;
    const x = x0 * W;
    const y = y0 * H;
    const w = (x1 - x0) * W;
    const h = (y1 - y0) * H;
    ctx.strokeStyle = '#0f2e35';
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    const label = `${overlay.prompt} #${obj.id}`;
    const tw = ctx.measureText(label).width + 8;
    ctx.fillStyle = '#0f2e35';
    ctx.fillRect(x, Math.max(0, y - 18), tw, 18);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, x + 4, Math.max(13, y - 5));
  }
  ctx.fillStyle = 'rgba(15,46,53,0.75)';
  ctx.fillText(`t = ${frame.t.toFixed(2)} s`, 8, H - 8);
}

/** Tracking boxes from the latest clip, drawn on a neutral canvas (no video is kept). */
export function OverlayCanvas({ overlay, mock }: { overlay: Overlay | null; mock: boolean }) {
  const t = useT();
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !overlay || !overlay.frames.length) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced || overlay.frames.length === 1) {
      draw(ctx, overlay, overlay.frames.length - 1);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const last = overlay.frames[overlay.frames.length - 1];
    const duration = Math.max(1, last ? last.t : 4) * 1000;
    const tick = (now: number) => {
      const elapsed = ((now - start) % (duration + 600)) / 1000;
      const next = overlay.frames.findIndex((f) => f.t > elapsed);
      const i = next === -1 ? overlay.frames.length - 1 : Math.max(0, next - 1);
      draw(ctx, overlay, i);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [overlay]);

  if (!overlay || !overlay.frames.length) {
    return (
      <p className="rounded-[var(--radius-control)] bg-wash px-4 py-3 text-[15px] text-ink-soft">
        {t(mock ? 'overlay.empty' : 'overlay.empty_live')}
      </p>
    );
  }
  return (
    <figure className="flex w-full max-w-[420px] flex-col gap-2">
      <canvas
        ref={ref}
        className="aspect-[4/3] w-full rounded-[var(--radius-control)]"
        role="img"
        aria-label={t('overlay.aria', {
          provider: providerLabel(overlay.provider),
          prompt: overlay.prompt,
        })}
      />
      <figcaption className="text-sm text-muted">
        {t('overlay.caption', {
          provider: providerLabel(overlay.provider),
          prompt: overlay.prompt,
          n: overlay.frames.length,
        })}
      </figcaption>
    </figure>
  );
}
