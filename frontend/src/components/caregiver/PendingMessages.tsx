import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import type { PatientMessage, Snapshot } from '../../api/types';
import { useCurrentLang, useT } from '../../i18n';
import { playChime, unlockAudio } from '../../lib/alarm';
import { clockTime, cx } from '../../lib/format';
import { Button } from '../Button';
import { Pictogram } from '../Pictogram';
import { Badge } from '../Section';

const NONE: PatientMessage[] = [];
const URGENT_REPEAT_MS = 20_000;

/**
 * Messages the patient has said that no caregiver has acknowledged yet. The room may be empty and
 * the patient cannot press the call bell, so each one chimes (again on every repeat) and stays until
 * someone taps "I'm coming". Urgent and escalated ones chime every 20 seconds until then.
 */
export function PendingMessages({ snap }: { snap: Snapshot }) {
  const t = useT();
  const lang = useCurrentLang();
  const pending = snap.pending_ack ?? NONE;
  const heard = useRef(new Map<string, number>());
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let chime: 'urgent' | 'normal' | null = null;
    for (const m of pending) {
      const n = m.announced ?? 1;
      if ((heard.current.get(m.id) ?? 0) >= n) continue;
      heard.current.set(m.id, n);
      chime = m.urgent || m.escalated || chime === 'urgent' ? 'urgent' : 'normal';
    }
    if (chime) playChime(chime === 'urgent');
  }, [pending]);

  const insistent = pending.some((m) => m.urgent || m.escalated);
  useEffect(() => {
    if (!insistent) return;
    const id = window.setInterval(() => playChime(true), URGENT_REPEAT_MS);
    return () => window.clearInterval(id);
  }, [insistent]);

  if (!pending.length) return null;

  async function acknowledge(m: PatientMessage) {
    unlockAudio();
    setBusy(m.id);
    try {
      await api.ackMessage(snap.session_id, m.id);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-label={t('pending.title')} className="flex flex-col gap-3">
      {pending.map((m) => {
        const loud = m.urgent || m.escalated;
        return (
          <div
            key={m.id}
            role={loud ? 'alert' : 'status'}
            className={cx(
              'flex flex-col gap-4 rounded-[var(--radius-panel)] px-5 py-4 sm:flex-row sm:items-center',
              loud
                ? 'bg-alarm-soft shadow-[inset_0_0_0_2px_var(--color-alarm)]'
                : 'bg-voice-soft shadow-[inset_0_0_0_2px_var(--color-voice)]',
            )}
          >
            <Pictogram id={m.hypothesis_id} size={56} className="shrink-0 rounded-[10px]" />
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-semibold text-ink-soft">
                <span>{t('pending.says')}</span>
                {m.at ? <span className="tabular font-normal">{clockTime(m.at)}</span> : null}
                {(m.announced ?? 1) > 1 ? (
                  <span className="tabular font-normal">
                    {t('pending.said_times', { n: m.announced ?? 1 })}
                  </span>
                ) : null}
                {m.urgent ? <Badge tone="alarm">{t('bars.urgent')}</Badge> : null}
              </p>
              <p className="mt-1 text-[24px] font-bold leading-snug sm:text-[26px]">
                “{lang === 'id' ? m.text_id : m.text_en}”
              </p>
              {m.escalated ? (
                <p className="mt-1 font-semibold text-alarm-deep">{t('pending.escalated')}</p>
              ) : null}
            </div>
            <Button
              size="xl"
              variant={loud ? 'danger' : 'primary'}
              busy={busy === m.id}
              onClick={() => void acknowledge(m)}
              className="shrink-0"
            >
              {t('pending.ack')}
            </Button>
          </div>
        );
      })}
    </section>
  );
}
