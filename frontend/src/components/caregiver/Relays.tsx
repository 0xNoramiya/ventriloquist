import { useState } from 'react';
import { api } from '../../api/client';
import type { Relay, RelayStatus, Snapshot } from '../../api/types';
import { useT, type Key } from '../../i18n';
import { clockTime, cx } from '../../lib/format';
import { Button } from '../Button';
import { Badge } from '../Section';

const NONE: Relay[] = [];

const STATUS_TONE: Record<RelayStatus, 'neutral' | 'ink' | 'caution' | 'alarm' | 'good' | 'voice'> =
  {
    awaiting_approval: 'voice',
    sending: 'neutral',
    sent: 'neutral',
    delivered: 'neutral',
    read: 'ink',
    review: 'caution',
    replied: 'good',
    read_to_patient: 'good',
    no_reply: 'caution',
    cancelled: 'neutral',
    failed: 'alarm',
  };

function useRelayAction(sid: string) {
  const [busy, setBusy] = useState<string | null>(null);
  async function run(relay: Relay, action: 'approve' | 'cancel' | 'read') {
    setBusy(`${relay.id}:${action}`);
    try {
      await api.relayAction(sid, relay.id, action);
    } finally {
      setBusy(null);
    }
  }
  return { busy, run };
}

/** Steps that need a caregiver: approving what goes to a relative, and reading a flagged reply
 * before the patient hears it. Shown at the top of the console. */
export function RelayActions({ snap }: { snap: Snapshot }) {
  const t = useT();
  const relays = snap.relays ?? NONE;
  const { busy, run } = useRelayAction(snap.session_id);
  const open = relays.filter((r) => r.status === 'awaiting_approval' || r.status === 'review');
  if (!open.length) return null;
  return (
    <section aria-label={t('relay.title')} className="flex flex-col gap-3">
      {open.map((r) =>
        r.status === 'awaiting_approval' ? (
          <div
            key={r.id}
            role="status"
            className="flex flex-col gap-4 rounded-[var(--radius-panel)] bg-paper px-5 py-4 shadow-[inset_0_0_0_2px_var(--color-ink)] sm:flex-row sm:items-center"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink-soft">
                {t('relay.approve_title', { name: r.to, relation: r.relation })}
              </p>
              <p className="mt-1 text-xl font-bold leading-snug">“{r.patient_text}”</p>
              <p className="mt-1 text-sm text-muted">
                {r.simulated ? t('relay.simulated') : t('relay.whatsapp', { phone: r.phone })}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                size="lg"
                variant="primary"
                busy={busy === `${r.id}:approve`}
                onClick={() => void run(r, 'approve')}
              >
                {t('relay.send')}
              </Button>
              <Button
                size="lg"
                busy={busy === `${r.id}:cancel`}
                onClick={() => void run(r, 'cancel')}
              >
                {t('relay.dont_send')}
              </Button>
            </div>
          </div>
        ) : (
          <div
            key={r.id}
            role="alert"
            className="flex flex-col gap-4 rounded-[var(--radius-panel)] bg-caution-soft px-5 py-4 shadow-[inset_0_0_0_2px_var(--color-caution)] sm:flex-row sm:items-center"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-caution">
                {t('relay.review_title', { name: r.to })}
              </p>
              <p className="mt-1 text-xl font-bold leading-snug">“{r.reply?.text}”</p>
              {r.reply?.reason ? (
                <p className="mt-1 text-sm text-ink-soft">
                  {t('relay.review_reason', { reason: r.reply.reason })}
                </p>
              ) : null}
            </div>
            <Button
              size="lg"
              variant="primary"
              busy={busy === `${r.id}:read`}
              onClick={() => void run(r, 'read')}
              className="shrink-0"
            >
              {t('relay.read_aloud')}
            </Button>
          </div>
        ),
      )}
    </section>
  );
}

/** Every relay of this session: who, what, how far it got, and the reply. */
export function Relays({ snap }: { snap: Snapshot }) {
  const t = useT();
  const relays = snap.relays ?? NONE;
  const { busy, run } = useRelayAction(snap.session_id);
  if (!relays.length) return <p className="text-muted">{t('relay.empty')}</p>;
  return (
    <ol className="flex flex-col gap-3">
      {[...relays].reverse().map((r) => (
        <li
          key={r.id}
          className="rounded-[var(--radius-control)] bg-paper px-4 py-3 shadow-[inset_0_0_0_1px_var(--color-line)]"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold">
              {t('relay.to', { name: r.to, relation: r.relation })}{' '}
              <span className="font-normal text-muted">
                · {r.simulated ? t('relay.simulated_short') : 'WhatsApp'}
              </span>
            </p>
            <Badge tone={STATUS_TONE[r.status]}>{t(`relay.status.${r.status}` as Key)}</Badge>
          </div>
          <p className="mt-1 text-ink-soft">“{r.patient_text}”</p>
          <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
            {r.events.map((e, i) => (
              <span key={i} className="tabular">
                {t(`relay.event.${e.kind}` as Key)} {clockTime(e.at)}
              </span>
            ))}
          </p>
          {r.reply ? (
            <div
              className={cx(
                'mt-2 rounded-[var(--radius-control)] px-3 py-2',
                r.reply.needs_review ? 'bg-caution-soft' : 'bg-good-soft',
              )}
            >
              <p className="text-sm font-semibold">{t('relay.reply_from', { name: r.to })}</p>
              <p className="text-lg">“{r.reply.text}”</p>
              {r.reply.read_at ? (
                <p className="text-sm text-muted">
                  {t('relay.read_at', { time: clockTime(r.reply.read_at) })}
                </p>
              ) : null}
            </div>
          ) : null}
          {['sent', 'delivered', 'read'].includes(r.status) ? (
            <Button
              size="sm"
              variant="ghost"
              className="-ml-2 mt-1"
              busy={busy === `${r.id}:cancel`}
              onClick={() => void run(r, 'cancel')}
            >
              {t('relay.stop')}
            </Button>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
