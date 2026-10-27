import type { LlmCall } from '../../api/types';
import { useT } from '../../i18n';
import { Badge } from '../Section';

export function ModelCalls({ calls }: { calls: LlmCall[] }) {
  const t = useT();
  if (!calls.length) return <p className="text-muted">{t('calls.empty')}</p>;
  const rows = [...calls].reverse();
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm sm:text-[15px]">
        <thead>
          <tr className="text-sm text-muted">
            <th scope="col" className="px-1 py-1.5 font-semibold">
              {t('calls.role')}
            </th>
            <th scope="col" className="px-1 py-1.5 font-semibold">
              {t('calls.model')}
            </th>
            <th scope="col" className="px-1 py-1.5 text-right font-semibold">
              {t('calls.latency')}
            </th>
            <th scope="col" className="px-1 py-1.5 text-right font-semibold">
              {t('calls.cost')}
            </th>
            <th scope="col" className="px-1 py-1.5 font-semibold">
              <span className="sr-only">{t('calls.flags')}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c, i) => (
            <tr key={i} className="border-t border-line align-top">
              <td className="px-1 py-1.5 font-semibold">{c.role.replace(/_/g, ' ')}</td>
              <td className="px-1 py-1.5">
                <span className="text-ink-soft">{c.provider}</span> · {c.model}
              </td>
              <td className="tabular px-1 py-1.5 text-right">{Math.round(c.latency_ms)} ms</td>
              <td className="tabular px-1 py-1.5 text-right">${(c.usd ?? 0).toFixed(4)}</td>
              <td className="px-1 py-1.5">
                {c.fallback ? (
                  <Badge tone="caution" title={c.error ?? undefined}>
                    {t('calls.fallback')}
                  </Badge>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
