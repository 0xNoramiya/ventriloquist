import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import type { Budget, ModeInfo, OverrideAction, Snapshot } from '../../api/types';
import { useCurrentLang, useT, type Key } from '../../i18n';
import { audioReady, startAlarm, unlockAudio } from '../../lib/alarm';
import { cx, pct, usd } from '../../lib/format';
import { speak } from '../../lib/speech';
import { sendMessage, useSession } from '../../store/session';
import { Button } from '../Button';

function override(sid: string, action: OverrideAction) {
  if (!sendMessage({ type: 'override', action })) void api.override(sid, action);
}

/** Loud, unmissable, and only goes away when a person acknowledges it. */
export function AlarmBanner({ snap }: { snap: Snapshot }) {
  const t = useT();
  const lang = useCurrentLang();
  const alarm = useSession((s) => s.alarm);
  const seq = useSession((s) => s.alarmSeq);
  const ackRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!alarm.active) return;
    unlockAudio();
    const stop = startAlarm();
    const line = lang === 'id' ? t('alarm.title') : (alarm.textEn ?? t('alarm.title'));
    const handle = speak(line, lang, 1);
    ackRef.current?.focus();
    return () => {
      stop();
      handle.cancel();
    };
  }, [alarm.active, alarm.textEn, seq, lang, t]);

  if (!alarm.active && !snap.emergency) return null;
  return (
    <div role="alert" className="alarm-flash sticky top-0 z-40 bg-alarm text-paper">
      <div className="mx-auto flex max-w-[1480px] flex-col gap-4 px-4 py-5 sm:flex-row sm:items-center sm:px-8">
        <svg
          viewBox="0 0 24 24"
          className="size-12 shrink-0"
          aria-hidden="true"
          fill="currentColor"
        >
          <path d="M12 2.5 1.8 20.5h20.4L12 2.5Zm0 6.2c.7 0 1.2.5 1.1 1.2l-.3 5a.8.8 0 0 1-1.6 0l-.3-5c0-.7.4-1.2 1.1-1.2Zm0 8a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4Z" />
        </svg>
        <div className="flex-1">
          <p className="text-[28px] font-bold leading-tight sm:text-[34px]">{t('alarm.title')}</p>
          <p className="text-lg">{t('alarm.body', { name: snap.patient.display_name })}</p>
        </div>
        <Button
          ref={ackRef}
          size="xl"
          variant="onAlarm"
          onClick={() => override(snap.session_id, 'ack_emergency')}
        >
          {t('alarm.ack')}
        </Button>
      </div>
    </div>
  );
}

const REASONS: Record<string, Key> = {
  question_cap: 'reason.question_cap',
  unclear: 'reason.unclear',
  inconsistent: 'reason.inconsistent',
  tap_answer: 'reason.tap_answer',
  no_match: 'reason.no_match',
  no_questions_left: 'reason.no_questions_left',
  spelling_stuck: 'reason.spelling_stuck',
  internal_error: 'reason.internal_error',
};

const KNOWN_ALERTS = new Set(['emergency', 'urgent', 'sensitive']);

export function CaregiverBanners({ snap }: { snap: Snapshot }) {
  const t = useT();
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  // Alerts of other kinds (for example a late judge disagreeing with an early decision).
  const otherAlerts = snap.alerts.filter(
    (a) => !KNOWN_ALERTS.has(a.kind) && a.text && !hidden.has(`${a.at}|${a.text}`),
  );
  const lang = useCurrentLang();
  const banners = useSession((s) => s.banners);
  const dismiss = useSession((s) => s.dismiss);
  // The held message decides; caregiver_reason can linger after the acknowledgement.
  const sensitive =
    snap.caregiver_reason === 'sensitive_verify' && snap.message?.status === 'needs_verification';
  const reason =
    snap.caregiver_reason && !sensitive && snap.state === 'CAREGIVER_NEEDED'
      ? snap.caregiver_reason
      : null;
  const msg = snap.message;

  return (
    <div className="flex flex-col gap-3 empty:hidden">
      {snap.budget.level === 'mock' ? (
        <div
          role="alert"
          className="rounded-[var(--radius-control)] bg-alarm px-4 py-3 font-semibold text-paper"
        >
          {t('budget.mock_notice', {
            spent: usd(snap.budget.spent_usd),
            max: usd(snap.budget.max_usd),
          })}
        </div>
      ) : null}
      {sensitive ? (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-[var(--radius-panel)] bg-caution-soft px-5 py-4 text-ink shadow-[inset_0_0_0_2px_var(--color-caution)]"
        >
          <p className="text-xl font-bold text-caution">{t('sensitive.title')}</p>
          <p className="max-w-[70ch]">{t('sensitive.body')}</p>
          {msg ? (
            <p className="text-xl font-bold">“{lang === 'id' ? msg.text_id : msg.text_en}”</p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => override(snap.session_id, 'ack_sensitive')}>
              {t('sensitive.speak')}
            </Button>
            <Button onClick={() => override(snap.session_id, 'ack_sensitive_silent')}>
              {t('sensitive.silent')}
            </Button>
          </div>
        </div>
      ) : null}
      {reason ? (
        <div
          role="status"
          className="flex flex-col gap-1 rounded-[var(--radius-panel)] bg-paper px-5 py-4 shadow-[inset_0_0_0_2px_var(--color-ink)]"
        >
          <p className="text-lg font-bold">{t('reason.title')}</p>
          <p>{REASONS[reason] ? t(REASONS[reason]) : snap.caregiver_text}</p>
        </div>
      ) : null}
      {otherAlerts.map((a) => (
        <div
          key={`${a.at}|${a.text}`}
          role="status"
          className="flex items-start gap-3 rounded-[var(--radius-control)] bg-caution-soft px-4 py-3 text-ink"
        >
          <p className="flex-1">
            <strong className="text-caution">{t('banner.check')}</strong> {a.text}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setHidden((h) => new Set(h).add(`${a.at}|${a.text}`))}
            aria-label={t('banner.dismiss')}
          >
            <svg viewBox="0 0 20 20" className="size-4" aria-hidden="true">
              <path
                d="M5 5l10 10M15 5L5 15"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </Button>
        </div>
      ))}
      {banners.map((b) => (
        <div
          key={b.id}
          role={b.kind === 'error' ? 'alert' : 'status'}
          className={cx(
            'flex items-start gap-3 rounded-[var(--radius-control)] px-4 py-3',
            b.kind === 'error' ? 'bg-alarm-soft text-alarm-deep' : 'bg-caution-soft text-ink',
          )}
        >
          <p className="flex-1">
            <strong>{b.kind === 'error' ? t('banner.error') : t('banner.urgent')}</strong> {b.text}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => dismiss(b.id)}
            aria-label={t('banner.dismiss')}
          >
            <svg viewBox="0 0 20 20" className="size-4" aria-hidden="true">
              <path
                d="M5 5l10 10M15 5L5 15"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </Button>
        </div>
      ))}
    </div>
  );
}

const MODE_KEYS: Record<string, Key> = {
  mock: 'mode.mock',
  live: 'mode.live',
  privacy: 'mode.privacy',
};

export function ModeBadge({ mode }: { mode: ModeInfo }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const eff = mode.effective;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button
        type="button"
        title={mode.reason}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cx(
          'relative inline-flex min-h-8 items-center gap-1.5 rounded-full px-3 text-sm font-bold',
          'before:absolute before:-inset-y-2 before:inset-x-0 before:content-[""]',
          eff === 'live'
            ? 'bg-ink text-paper'
            : eff === 'privacy'
              ? 'bg-good-soft text-good'
              : 'bg-wash text-ink',
        )}
      >
        <span
          className={cx(
            'size-2 rounded-full',
            eff === 'live' ? 'bg-voice' : eff === 'privacy' ? 'bg-good' : 'bg-ink-soft',
          )}
          aria-hidden="true"
        />
        {t(MODE_KEYS[eff] ?? 'mode.mock')}
        <span className="sr-only">{t('mode.why')}</span>
      </button>
      {open ? <span className="text-sm text-ink-soft">{mode.reason}</span> : null}
    </span>
  );
}

export function BudgetMeter({ budget }: { budget: Budget }) {
  const t = useT();
  const level = budget.level;
  return (
    <div
      className="flex min-w-[9rem] flex-col gap-1"
      title={t('budget.title')}
      aria-label={t('budget.aria', {
        spent: usd(budget.spent_usd),
        max: usd(budget.max_usd),
        p: pct(budget.fraction),
      })}
      role="group"
    >
      <span
        className={cx(
          'tabular text-sm font-semibold',
          level === 'mock' ? 'text-alarm' : level === 'warn' ? 'text-caution' : 'text-ink',
        )}
      >
        {usd(budget.spent_usd)}{' '}
        <span className="font-normal text-muted">/ {usd(budget.max_usd)}</span>
        {level === 'warn' ? <span className="ml-1">{t('budget.warn')}</span> : null}
      </span>
      <span className="h-1.5 w-full overflow-hidden rounded-full bg-wash" aria-hidden="true">
        <span
          className={cx(
            'block h-full rounded-full',
            level === 'mock' ? 'bg-alarm' : level === 'warn' ? 'bg-caution' : 'bg-ink',
          )}
          style={{ width: `${Math.max(1, Math.min(100, budget.fraction * 100))}%` }}
        />
      </span>
    </div>
  );
}

export function SoundButton() {
  const t = useT();
  const [ready, setReady] = useState(audioReady);
  useEffect(() => {
    const id = window.setInterval(() => setReady(audioReady()), 2000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <Button
      variant={ready ? 'ghost' : 'secondary'}
      size="sm"
      aria-pressed={ready}
      onClick={() => {
        unlockAudio();
        window.setTimeout(() => setReady(audioReady()), 150);
      }}
    >
      <svg
        viewBox="0 0 24 24"
        className="size-5"
        aria-hidden="true"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5H4Z" fill="currentColor" stroke="none" />
        {ready ? (
          <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
        ) : (
          <path d="m16 9 5 6m0-6-5 6" />
        )}
      </svg>
      {ready ? t('sound.on') : t('sound.enable')}
    </Button>
  );
}
