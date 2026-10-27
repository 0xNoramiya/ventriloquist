import { lazy, Suspense } from 'react';
import { useParams } from 'react-router-dom';
import { useT } from '../i18n';

const Caregiver = lazy(() => import('./Caregiver'));

/**
 * Hosted demo: the caregiver console and the patient phone side by side in one tab, because the
 * whole session runs in this tab (Pyodide worker). The phone is a same-origin iframe so the patient
 * view gets a phone-sized viewport; it shares this page's engine (see demo/bridge.ts).
 */
export default function Demo() {
  const t = useT();
  const { sid } = useParams<{ sid: string }>();
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_430px]">
      <div className="min-w-0">
        <Suspense fallback={<div className="min-h-dvh" aria-busy="true" />}>
          <Caregiver />
        </Suspense>
      </div>
      <aside
        aria-label={t('demo.phone_label')}
        className="border-t border-line bg-wash p-4 lg:sticky lg:top-0 lg:h-dvh lg:border-l lg:border-t-0"
      >
        <p className="mb-1 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">
          {t('demo.phone_label')}
        </p>
        <p className="mb-3 text-[14px] text-ink-soft">{t('demo.phone_hint')}</p>
        <iframe
          title={t('demo.phone_label')}
          src={`${import.meta.env.BASE_URL}?r=${encodeURIComponent(`patient/${sid ?? ''}`)}`}
          allow="autoplay"
          className="mx-auto block h-[min(800px,calc(100dvh-7rem))] w-full max-w-[390px] rounded-[28px] border-0 bg-night shadow-[0_0_0_10px_#0b0b0b]"
        />
      </aside>
    </div>
  );
}
