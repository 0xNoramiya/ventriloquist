import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { OverrideAction, Snapshot } from '../../api/types';
import { useT, type Key } from '../../i18n';
import { cx } from '../../lib/format';
import { groupRanges } from '../../lib/spelling';
import { sendMessage } from '../../store/session';
import { Button } from '../Button';

const STATE_KEYS: Record<string, Key> = {
  IDLE: 'state.IDLE',
  CONTEXT_REFRESH: 'state.CONTEXT_REFRESH',
  ASKING: 'state.ASKING',
  LISTENING: 'state.LISTENING',
  PROCESSING: 'state.PROCESSING',
  CONFIRMING: 'state.CONFIRMING',
  SPEAKING: 'state.SPEAKING',
  POST_CHECK: 'state.POST_CHECK',
  DONE: 'state.DONE',
  EMERGENCY: 'state.EMERGENCY',
  PAUSED: 'state.PAUSED',
  SPELLING: 'state.SPELLING',
  CAREGIVER_NEEDED: 'state.CAREGIVER_NEEDED',
};

const ANSWERABLE = new Set([
  'ASKING',
  'CONFIRMING',
  'SPELLING',
  'POST_CHECK',
  'LISTENING',
  'CAREGIVER_NEEDED',
]);
const ACTIVE = new Set([
  'ASKING',
  'CONFIRMING',
  'SPELLING',
  'POST_CHECK',
  'LISTENING',
  'PROCESSING',
  'SPEAKING',
  'CONTEXT_REFRESH',
]);

export function StateChip({ state, className }: { state: string; className?: string }) {
  const t = useT();
  const listening = state === 'LISTENING';
  return (
    <span
      className={cx(
        'inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-bold',
        state === 'EMERGENCY'
          ? 'bg-alarm text-paper'
          : listening
            ? 'bg-voice text-ink'
            : 'bg-night-3 text-paper',
        className,
      )}
    >
      {listening ? <span className="size-2 rounded-full bg-ink" aria-hidden="true" /> : null}
      {t(STATE_KEYS[state] ?? 'state.IDLE')}
    </span>
  );
}

/** The live prompt, mirrored from the patient screen, with every caregiver control. */
export function NowPanel({ snap }: { snap: Snapshot }) {
  const t = useT();
  const { state, prompt } = snap;
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!confirmEnd) return;
    const id = window.setTimeout(() => setConfirmEnd(false), 4000);
    return () => window.clearTimeout(id);
  }, [confirmEnd]);

  const override = (action: OverrideAction) => {
    setError(null);
    if (!sendMessage({ type: 'override', action })) {
      api
        .override(snap.session_id, action)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }
  };

  const notStarted = snap.message_index === 0 && state === 'IDLE';
  const canAnswer = Boolean(prompt) && ANSWERABLE.has(state) && prompt?.kind !== 'message';
  const active = ACTIVE.has(state);
  const canResume = state === 'PAUSED' || state === 'CAREGIVER_NEEDED';
  const showEnglish =
    snap.patient.language !== 'en' && prompt && prompt.text_en && prompt.text_en !== prompt.text;

  async function startHere() {
    setStarting(true);
    try {
      await api.start(snap.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section
      aria-labelledby="now-title"
      className="night flex flex-col gap-5 rounded-[var(--radius-panel)] bg-night p-5 text-mist sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="now-title" className="text-lg font-bold text-paper">
          {t('now.title')}
        </h2>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {snap.message_index > 0 ? (
            <span className="tabular text-mist-soft">
              {t('now.message_n', { n: snap.message_index })} ·{' '}
              {snap.stage === 'spelling' || snap.questions > snap.max_questions
                ? t('now.questions_plain', { n: snap.questions })
                : t('now.questions', { n: snap.questions, max: snap.max_questions })}
            </span>
          ) : null}
          <StateChip state={state} />
        </div>
      </div>

      <div className="min-h-[96px]" aria-live="polite">
        {notStarted ? (
          <div className="flex flex-col gap-3">
            <p className="text-xl text-paper">{t('now.not_started')}</p>
            <div>
              <Button variant="voice" size="lg" busy={starting} onClick={() => void startHere()}>
                {t('now.start_here')}
              </Button>
            </div>
          </div>
        ) : prompt ? (
          <div className="flex flex-col gap-2">
            {prompt.kind === 'message' ? (
              <p className="text-sm font-semibold text-voice">{t('message.confirmed_label')}</p>
            ) : prompt.kind !== 'ask' ? (
              <p className="text-sm font-semibold text-mist-soft">
                {t(`prompt.kind.${prompt.kind}` as Key)}
              </p>
            ) : null}
            <p
              lang={snap.patient.language}
              className={cx(
                'text-[26px] font-bold leading-tight sm:text-[30px]',
                prompt.kind === 'message' ? 'text-voice' : 'text-paper',
              )}
            >
              {prompt.text}
            </p>
            {showEnglish ? (
              <p lang="en" className="text-lg text-mist-soft">
                {prompt.text_en}
              </p>
            ) : null}
            {prompt.kind === 'spelling' ? (
              <p className="text-[15px] text-mist">
                {t('now.spelled', { text: snap.spelling?.text.trim() || '–' })}
                {prompt.group.length
                  ? ` · ${t('trail.group', { g: groupRanges(prompt.group).join(', ') })}`
                  : ''}
                {prompt.word ? ` · ${t('now.word', { w: prompt.word })}` : ''}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-xl text-mist">
            {state === 'DONE'
              ? t('now.done')
              : state === 'PAUSED'
                ? t('now.paused')
                : t(STATE_KEYS[state] ?? 'state.IDLE')}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <p id="answer-for" className="text-sm text-mist-soft">
          {t('now.answer_for')}
        </p>
        <div className="grid grid-cols-3 gap-2" role="group" aria-labelledby="answer-for">
          {(['yes', 'no', 'unclear'] as const).map((a) => (
            <Button
              key={a}
              size="answer"
              variant={canAnswer && a !== 'unclear' ? 'secondary' : 'night'}
              disabled={!canAnswer}
              onClick={() => override(a)}
            >
              {t(a === 'yes' ? 'answer.YES' : a === 'no' ? 'answer.NO' : 'answer.UNCLEAR')}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
        <Button
          variant="night"
          disabled={!active || state === 'SPEAKING'}
          onClick={() => override('skip')}
        >
          {t('now.skip')}
        </Button>
        <Button
          variant="night"
          disabled={snap.ended || snap.stage === 'spelling' || notStarted}
          onClick={() => override('spell')}
        >
          {t('now.spell')}
        </Button>
        {canResume ? (
          <Button variant="night" onClick={() => override('resume')}>
            {t('now.resume')}
          </Button>
        ) : (
          <Button variant="night" disabled={!active} onClick={() => override('pause')}>
            {t('now.pause')}
          </Button>
        )}
        <Button
          variant="night"
          disabled={snap.ended || notStarted || active}
          onClick={() => override('new_message')}
        >
          {t('now.new_message')}
        </Button>
        <Button
          variant={confirmEnd ? 'secondary' : 'night'}
          disabled={snap.ended}
          aria-live="polite"
          onClick={() => {
            if (confirmEnd) {
              override('end');
              setConfirmEnd(false);
            } else setConfirmEnd(true);
          }}
        >
          {confirmEnd ? t('now.end_confirm') : t('now.end')}
        </Button>
        <div className="ml-auto pl-4">
          <Button variant="danger" disabled={snap.emergency} onClick={() => override('emergency')}>
            <svg viewBox="0 0 20 20" className="size-5" aria-hidden="true" fill="currentColor">
              <path d="M10 1.8 1 17.6h18L10 1.8Zm0 5.4c.6 0 1 .4 1 1l-.3 4.3a.7.7 0 0 1-1.4 0L9 8.2c0-.6.4-1 1-1Zm0 6.9a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z" />
            </svg>
            {t('now.emergency')}
          </Button>
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-voice">
          {error}
        </p>
      ) : null}
    </section>
  );
}
