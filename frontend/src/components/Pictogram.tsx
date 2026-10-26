import { useState } from 'react';
import { cx } from '../lib/format';
import { pictogramSrc } from '../lib/pictogram';

/**
 * AAC picture symbol for a message. Decorative (empty alt) because the text always sits next to
 * it. Renders nothing for spelled messages or ids without a picture, or if the image fails.
 */
export function Pictogram({
  id,
  size,
  className,
  fluid = false,
}: {
  id: string | null | undefined;
  /** Intrinsic size; with `fluid` the box is sized by className instead. */
  size: number;
  className?: string;
  fluid?: boolean;
}) {
  const src = pictogramSrc(id);
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) return null;
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center justify-center overflow-hidden bg-white',
        className,
      )}
      style={fluid ? undefined : { width: size, height: size }}
    >
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        decoding="async"
        className="size-full object-contain"
        onError={() => setFailed(src)}
      />
    </span>
  );
}
