import { useMemo } from 'react';
import { encode } from 'uqr';

/** QR code drawn as one SVG path (no canvas, crisp at any size). */
export function QRCode({
  value,
  size = 168,
  label,
}: {
  value: string;
  size?: number;
  label: string;
}) {
  const { path, n } = useMemo(() => {
    const qr = encode(value, { ecc: 'M', border: 2 });
    let d = '';
    qr.data.forEach((row, y) =>
      row.forEach((on, x) => {
        if (on) d += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return { path: d, n: qr.size };
  }, [value]);
  return (
    <svg
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${n} ${n}`}
      shapeRendering="crispEdges"
      className="rounded-[var(--radius-control)] bg-white"
    >
      <rect width={n} height={n} fill="#fff" />
      <path d={path} fill="#0f2e35" />
    </svg>
  );
}
