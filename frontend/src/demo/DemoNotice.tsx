import { useEffect, useState } from 'react';
import { useT } from '../i18n';
import { demoBridge, isBrowserDemo, type DemoStage } from './bridge';

/** Explains the hosted demo and shows the engine loading progress. */
export function DemoNotice() {
  const t = useT();
  const [stage, setStage] = useState<DemoStage>(demoBridge.stage);

  useEffect(() => {
    if (!isBrowserDemo) return;
    const off = demoBridge.onStage(setStage);
    void demoBridge.init().catch(() => undefined);
    return off;
  }, []);

  if (!isBrowserDemo) return null;
  return (
    <div className="rounded-[var(--radius-card)] bg-wash p-5 shadow-[inset_0_0_0_1px_var(--color-line)]">
      <p className="font-semibold text-ink">{t('demo.notice.title')}</p>
      <p className="mt-1 max-w-[70ch] text-[15px] text-ink-soft">{t('demo.notice.body')}</p>
      <p role="status" className="mt-2 text-[15px] font-semibold text-ink">
        {t(`demo.stage.${stage}`)}
      </p>
    </div>
  );
}
