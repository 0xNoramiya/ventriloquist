import { cx } from '../lib/format';

/**
 * A responsive WebP from public/img/<name>-<width>.webp. Width and height are set, so the page does
 * not shift while it loads; the photo above the fold loads eagerly, the rest lazily.
 */
export function Photo({
  name,
  widths,
  ratio,
  alt,
  sizes,
  eager = false,
  className,
}: {
  name: string;
  widths: number[];
  ratio: number;
  alt: string;
  sizes: string;
  eager?: boolean;
  className?: string;
}) {
  const base = `${import.meta.env.BASE_URL}img/${name}`;
  const largest = Math.max(...widths);
  return (
    <img
      src={`${base}-${Math.min(...widths)}.webp`}
      srcSet={widths.map((w) => `${base}-${w}.webp ${w}w`).join(', ')}
      sizes={sizes}
      width={largest}
      height={Math.round(largest / ratio)}
      alt={alt}
      loading={eager ? 'eager' : 'lazy'}
      // React 18 only passes the lowercase HTML attribute through
      {...{ fetchpriority: eager ? 'high' : 'auto' }}
      decoding="async"
      draggable={false}
      className={cx('block h-auto w-full select-none object-cover', className)}
      style={{ aspectRatio: String(ratio) }}
    />
  );
}
