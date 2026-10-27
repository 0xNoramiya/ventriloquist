import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { AnswerValue, Lang, Prompt, Snapshot } from '../api/types';
import { Footer } from '../components/Shell';
import { Pictogram } from '../components/Pictogram';
import { translate, useT, type TFn } from '../i18n';
import { unlockAudio } from '../lib/alarm';
import { cx } from '../lib/format';
import { grabFrame, keepAwake, recordClip, startCamera, stopStream } from '../lib/media';
import { signalPair } from '../lib/signals';
import { speak, unlockSpeech, type SpeakHandle } from '../lib/speech';
import { speechText } from '../lib/promptSpeech';
import { isHighlighted, LETTERS, SPECIALS } from '../lib/spelling';
import { loadConfig } from '../lib/useConfig';
import { useSessionSocket } from '../lib/useSessionSocket';
import { sendMessage, useSession } from '../store/session';

const PROMPTING = new Set(['ASKING', 'CONFIRMING', 'SPELLING', 'POST_CHECK']);
const KEYS: Record<string, AnswerValue> = { y: 'yes', n: 'no', u: 'unclear', e: 'emergency' };

function isLive(s: Snapshot | null): boolean {
  return Boolean(s && s.mode.effective !== 'mock');
}

/** Read answers from the camera in live mode, and also in mock mode once the patient has a real
 * calibration: the on-device motion tracker needs no keys and sends nothing off the machine. */
function usesCamera(s: Snapshot | null): boolean {
  return isLive(s) || Boolean(s && !s.calibration.skipped);
}

export default function Patient() {
  const { sid } = useParams<{ sid: string }>();
  useSessionSocket(sid);
  const snap = useSession((s) => s.snapshot);
  const connection = useSession((s) => s.connection);
  const lang: Lang = snap?.patient.language ?? 'en';
  const t = useT(snap ? lang : undefined);
  const live = isLive(snap);
  const camera = usesCamera(snap);

  const [started, setStarted] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [recording, setRecording] = useState<{ promptId: string; ms: number } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const speechRef = useRef<{ promptId: string; handle: SpeakHandle } | null>(null);
  const spokenRef = useRef<string | null>(null);
  const recordedRef = useRef<string | null>(null);
  const emergencySpokenRef = useRef(false);
  const settingsRef = useRef({ rate: 0.9, windowMs: 4000, delayMs: 300 });
  const [idleMs, setIdleMs] = useState(0);

  useEffect(() => {
    loadConfig()
      .then((c) => {
        settingsRef.current = {
          rate: c.speech.rate ?? 0.9,
          windowMs: (c.perception.window_s ?? 4) * 1000,
          delayMs: c.perception.window_delay_ms ?? 300,
        };
        setIdleMs(c.flags.idle_watch ? (c.perception.idle_watch_interval_s ?? 20) * 1000 : 0);
      })
      .catch(() => {
        // defaults are fine
      });
  }, []);

  // Release camera and speech when leaving the page.
  useEffect(
    () => () => {
      stopStream(streamRef.current);
      speechRef.current?.handle.cancel();
    },
    [],
  );

  useEffect(() => {
    if (!started) return;
    return keepAwake();
  }, [started]);

  const start = useCallback(async () => {
    unlockSpeech();
    unlockAudio();
    setStarted(true);
    const current = useSession.getState().snapshot;
    if (usesCamera(current) && sid) {
      try {
        const stream = await startCamera();
        streamRef.current = stream;
        setCameraOn(true);
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => undefined);
          await new Promise((r) => window.setTimeout(r, 600));
          if (isLive(current)) {
            const frame = await grabFrame(video);
            await api.sessionSnapshotImage(sid, frame);
          }
        }
      } catch (e) {
        setStartError(e instanceof Error ? e.message : String(e));
      }
    }
    const latest = useSession.getState().snapshot;
    if (!latest || latest.message_index === 0) sendMessage({ type: 'start' });
  }, [sid]);

  // One answer clip per prompt, uploaded when the window closes.
  const recordAnswer = useCallback(
    (forPrompt: string) => {
      const stream = streamRef.current;
      if (!sid || !stream || recordedRef.current === forPrompt) return;
      recordedRef.current = forPrompt;
      const { windowMs, delayMs } = settingsRef.current;
      window.setTimeout(() => {
        if (useSession.getState().snapshot?.prompt?.id !== forPrompt) return;
        setRecording({ promptId: forPrompt, ms: windowMs });
        setUploadError(null);
        recordClip(stream, windowMs)
          .then((clip) => {
            setRecording(null);
            return api.sessionClip(sid, forPrompt, clip);
          })
          .catch((e: unknown) => {
            setRecording(null);
            setUploadError(e instanceof Error ? e.message : String(e));
          });
      }, delayMs);
    },
    [sid],
  );

  // Speak each new prompt once, then tell the backend it was spoken.
  const promptId = snap?.prompt?.id ?? null;
  const state = snap?.state ?? null;
  useEffect(() => {
    const active = speechRef.current;
    if (active && active.promptId !== promptId) {
      active.handle.cancel();
      speechRef.current = null;
    }
    // Read the prompt from the store: the effect re-runs only when its id or the state changes.
    const p = useSession.getState().snapshot?.prompt;
    if (!started || !p || p.id !== promptId || !state) return;
    const speakable = PROMPTING.has(state) || (state === 'SPEAKING' && p.kind === 'message');
    if (!speakable || spokenRef.current === p.id) return;
    spokenRef.current = p.id;
    const asksQuestion = PROMPTING.has(state);
    const handle = speak(speechText(p, lang), lang, settingsRef.current.rate);
    speechRef.current = { promptId: p.id, handle };
    void handle.done.then((outcome) => {
      if (speechRef.current?.handle === handle) speechRef.current = null;
      if (outcome === 'cancelled') return;
      sendMessage({ type: 'spoken', prompt_id: p.id });
      // Start the answer window here rather than after the server's reply, so a quick answer
      // is not lost to the round trip.
      if (asksQuestion && usesCamera(useSession.getState().snapshot)) recordAnswer(p.id);
    });
  }, [started, promptId, state, lang, recordAnswer]);

  // Nobody acknowledged the message yet: the server asks the idle phone to say it again. When a
  // caregiver taps "I'm coming", tell the patient (their eyes may be closed).
  const lastEvent = useSession((s) => s.lastEvent);
  useEffect(() => {
    if (!started || !lastEvent) return;
    const { event } = lastEvent;
    if ((event.type === 'reminder' || event.type === 'relay_reply') && event.text)
      speak(event.text, lang, settingsRef.current.rate);
    if (event.type === 'acknowledged') speak(t('patient.ack.seen'), lang, settingsRef.current.rate);
  }, [started, lastEvent, lang, t]);

  // Emergency: say once, calmly, that help is coming.
  useEffect(() => {
    if (!started) return;
    if (state === 'EMERGENCY' && !emergencySpokenRef.current) {
      emergencySpokenRef.current = true;
      speechRef.current?.handle.cancel();
      speak(translate(lang, 'patient.emergency.title'), lang, settingsRef.current.rate);
    } else if (state !== 'EMERGENCY') {
      emergencySpokenRef.current = false;
    }
  }, [started, state, lang]);

  // Fallback: listening without a clip yet (speech unavailable, or the page reconnected).
  useEffect(() => {
    if (!started || !camera || state !== 'LISTENING' || !promptId) return;
    recordAnswer(promptId);
  }, [started, camera, state, promptId, recordAnswer]);

  // Idle watch (brief 9.6): between messages, look for the patient's signal every few seconds.
  // Triple YES raises the alarm; a single YES starts a new message. Off unless the flag is on.
  useEffect(() => {
    if (!started || !camera || !sid || snap?.ended || !(state === 'DONE' || state === 'IDLE'))
      return;
    const { windowMs } = settingsRef.current;
    const stream = streamRef.current;
    if (!idleMs || !cameraOn || !stream) return;
    let busy = false;
    const timer = window.setInterval(() => {
      if (busy) return;
      busy = true;
      recordClip(stream, windowMs)
        .then((clip) => api.idleClip(sid, clip))
        .catch(() => undefined)
        .finally(() => {
          busy = false;
        });
    }, idleMs);
    return () => window.clearInterval(timer);
  }, [started, camera, cameraOn, idleMs, state, sid, snap?.ended]);

  // Mock mode: keyboard answers.
  useEffect(() => {
    if (!started || live) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      const answer = KEYS[e.key.toLowerCase()];
      if (!answer) return;
      const current = useSession.getState().snapshot;
      const pid = current?.prompt?.id;
      if (answer !== 'emergency' && !pid) return;
      e.preventDefault();
      sendMessage({ type: 'answer', prompt_id: pid ?? '', answer });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [started, live]);

  if (connection === 'missing') {
    return (
      <NightFrame lang={snap?.patient.language}>
        <CalmScreen title={t('patient.missing.title')} body={t('patient.missing.body')} />
      </NightFrame>
    );
  }

  return (
    <NightFrame
      lang={snap?.patient.language}
      top={snap ? <SignalsBar snap={snap} t={t} clearPreview={cameraOn} /> : null}
      bottom={
        snap && started && !live ? (
          <p className="text-[15px] text-mist-soft">{t('patient.mock_hint')}</p>
        ) : null
      }
    >
      <video
        ref={videoRef}
        muted
        playsInline
        aria-hidden="true"
        className={cx(
          'pointer-events-none fixed right-4 top-4 z-20 w-24 -scale-x-100 rounded-[10px] bg-night-2 sm:w-32',
          cameraOn ? 'block' : 'hidden',
        )}
      />
      {connection === 'reconnecting' ? (
        <p role="status" className="mx-auto mb-4 rounded-full bg-night-2 px-4 py-2 text-mist">
          {t('patient.reconnecting')}
        </p>
      ) : null}
      {startError ? (
        <p
          role="alert"
          className="mx-auto mb-4 max-w-[60ch] rounded-[10px] bg-night-2 px-4 py-2 text-center text-mist"
        >
          {t('patient.camera_error')} ({startError})
        </p>
      ) : null}
      {!snap ? (
        <CalmScreen title={t('patient.connecting')} />
      ) : !started ? (
        <StartGate t={t} live={camera} onStart={() => void start()} />
      ) : (
        <Stage snap={snap} t={t} recording={recording} uploadError={uploadError} />
      )}
    </NightFrame>
  );
}

function NightFrame({
  children,
  top,
  bottom,
  lang,
}: {
  children: ReactNode;
  top?: ReactNode;
  bottom?: ReactNode;
  lang?: Lang;
}) {
  return (
    <div className="night flex min-h-dvh flex-col bg-night text-mist">
      {top}
      <main className="flex flex-1 flex-col items-stretch justify-center px-5 py-[clamp(12px,4vh,32px)] sm:px-10">
        {children}
      </main>
      {bottom ? <aside className="px-5 pb-2 sm:px-10">{bottom}</aside> : null}
      <Footer night lang={lang} />
    </div>
  );
}

/** The patient's own YES and NO signals. Leaves room for the camera preview in the top corner. */
function SignalsBar({ snap, t, clearPreview }: { snap: Snapshot; t: TFn; clearPreview: boolean }) {
  const pair = signalPair(snap.signals.yes, snap.signals.no);
  if (!pair) return null;
  const { yes, no } = pair;
  const text = (x: typeof yes) => ('key' in x ? t(x.key) : x.text);
  return (
    <header
      className={cx(
        'border-b border-white/10 px-5 py-3 sm:px-10',
        clearPreview && 'pr-32 sm:pr-40',
      )}
    >
      <p
        className={cx(
          'flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[clamp(20px,2.6vw,30px)] leading-tight text-mist',
          clearPreview ? 'justify-start text-left' : 'justify-center text-center',
        )}
      >
        <span className="sr-only">{t('patient.signals_label')}</span>
        <span>
          {text(yes)} = <strong className="font-bold text-paper">{t('answer.YES')}</strong>
        </span>
        <span aria-hidden="true" className="hidden text-mist-soft sm:inline">
          ·
        </span>
        <span>
          {text(no)} = <strong className="font-bold text-paper">{t('answer.NO')}</strong>
        </span>
      </p>
    </header>
  );
}

function StartGate({ t, live, onStart }: { t: TFn; live: boolean; onStart: () => void }) {
  return (
    <div className="flex flex-col items-center gap-6 text-center">
      <h1 className="sr-only">{t('patient.title')}</h1>
      <button
        type="button"
        onClick={onStart}
        className="flex min-h-[40vh] w-full max-w-[720px] flex-col items-center justify-center gap-4 rounded-[24px] bg-voice px-8 py-10 text-ink transition-transform duration-150 active:scale-[0.99]"
      >
        <span className="text-[clamp(44px,8vw,96px)] font-bold leading-none">
          {t('patient.start')}
        </span>
        <span className="max-w-[32ch] text-[clamp(18px,2.4vw,26px)] leading-snug">
          {live ? t('patient.start_hint_live') : t('patient.start_hint')}
        </span>
      </button>
    </div>
  );
}

function Stage({
  snap,
  t,
  recording,
  uploadError,
}: {
  snap: Snapshot;
  t: TFn;
  recording: { promptId: string; ms: number } | null;
  uploadError: string | null;
}) {
  const { state, prompt } = snap;

  if (state === 'EMERGENCY') return <EmergencyScreen t={t} />;
  if (snap.ended)
    return <CalmScreen title={t('patient.ended.title')} body={t('patient.ended.body')} />;
  if (state === 'PAUSED')
    return <CalmScreen title={t('patient.paused.title')} body={t('patient.paused.body')} />;
  if (state === 'CAREGIVER_NEEDED')
    return <CalmScreen title={t('patient.caregiver.title')} body={t('patient.caregiver.body')} />;
  if (state === 'DONE') {
    const last = [...snap.messages].reverse().find((m) => m.status === 'confirmed' && !m.sensitive);
    const reply = [...(snap.relays ?? [])].reverse().find((r) => r.reply?.read_at)?.reply;
    return (
      <CalmScreen title={t('patient.done.title')} body={t('patient.done.body')}>
        {last ? (
          <>
            <p className="mt-8 text-[clamp(20px,2.6vw,28px)] text-mist-soft">
              {t('patient.done.last')}{' '}
              <span className="text-mist">
                “{snap.patient.language === 'id' ? last.text_id : last.text_en}”
              </span>
            </p>
            <p
              key={last.acknowledged_at ? 'seen' : 'waiting'}
              role="status"
              className={cx(
                'enter-line mt-4 text-[clamp(20px,2.6vw,28px)] font-semibold',
                last.acknowledged_at ? 'text-voice' : 'text-mist-soft',
              )}
            >
              {last.acknowledged_at ? `✓ ${t('patient.ack.seen')}` : t('patient.ack.waiting')}
            </p>
          </>
        ) : null}
        {reply ? (
          <p className="mx-auto mt-8 max-w-[34ch] rounded-[16px] bg-night-2 px-5 py-4 text-[clamp(20px,2.6vw,28px)] text-paper">
            {reply.spoken}
          </p>
        ) : null}
      </CalmScreen>
    );
  }
  if (state === 'SPEAKING' && prompt?.kind === 'message') {
    return <MessageView text={prompt.text} hypothesisId={snap.message?.hypothesis_id} t={t} />;
  }
  if (!prompt || state === 'IDLE' || state === 'CONTEXT_REFRESH') {
    return <CalmScreen title={t('patient.preparing')} quiet />;
  }

  const status = (
    <StatusLine
      state={state}
      t={t}
      recordingMs={recording?.promptId === prompt.id ? recording.ms : null}
      uploadError={uploadError}
    />
  );

  if (prompt.kind === 'spelling') {
    return <SpellingBoard snap={snap} prompt={prompt} t={t} status={status} />;
  }

  const picture = prompt.kind === 'confirm' ? prompt.question?.target_id : null;
  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col items-center gap-[clamp(16px,5vh,40px)]">
      <div
        className={cx(
          'flex w-full flex-col items-center gap-[clamp(16px,4vh,40px)]',
          picture && 'md:flex-row md:justify-center md:text-left',
        )}
      >
        {picture ? (
          <Pictogram
            id={picture}
            size={220}
            fluid
            className="size-[clamp(96px,26vh,220px)] rounded-[20px] p-2"
          />
        ) : null}
        <h1
          key={prompt.id}
          aria-live="polite"
          className={cx(
            'enter-line max-w-[22ch] text-center text-[clamp(40px,min(6.6vw,10.5vh),104px)] font-bold leading-[1.08] tracking-[-0.01em] text-paper',
            picture && 'md:text-left',
            state === 'PROCESSING' && 'opacity-70',
          )}
        >
          <QuotedPrompt text={prompt.text} />
        </h1>
      </div>
      {status}
    </div>
  );
}

/**
 * Confirmations read "Is this your message: “…”?". The quote starts on its own line at full size,
 * so the patient reads the message as one piece instead of a fragment wrapped after the colon.
 */
function QuotedPrompt({ text }: { text: string }) {
  const at = text.indexOf(': “');
  if (at < 0) return <>{text}</>;
  return (
    <>
      <span className="mb-[0.35em] block text-[0.55em] font-semibold leading-tight text-paper/80">
        {text.slice(0, at + 1)}
      </span>
      <span className="block">{text.slice(at + 2)}</span>
    </>
  );
}

function StatusLine({
  state,
  t,
  recordingMs,
  uploadError,
}: {
  state: string;
  t: TFn;
  recordingMs: number | null;
  uploadError: string | null;
}) {
  if (state === 'LISTENING') {
    return (
      <div role="status" className="flex w-full max-w-[520px] flex-col items-center gap-4">
        <p className="flex items-center gap-4 text-[clamp(24px,min(3.2vw,6vh),40px)] font-bold text-voice">
          <span
            className="breathe relative inline-block size-5 rounded-full bg-voice text-voice sm:size-6"
            aria-hidden="true"
          />
          {t('patient.listening')}
        </p>
        {recordingMs ? (
          <div className="h-2 w-full overflow-hidden rounded-full bg-night-3" aria-hidden="true">
            <div
              className="fill-bar h-full rounded-full bg-voice"
              style={{ ['--fill-ms' as string]: `${recordingMs}ms` }}
            />
          </div>
        ) : null}
        {uploadError ? <p className="text-lg text-mist">{t('patient.upload_error')}</p> : null}
      </div>
    );
  }
  if (state === 'PROCESSING') {
    return (
      <p role="status" className="text-[clamp(20px,2.6vw,30px)] text-mist-soft">
        {t('patient.processing')}
      </p>
    );
  }
  return (
    <p
      role="status"
      className="flex items-center gap-3 text-[clamp(20px,2.6vw,30px)] text-mist-soft"
    >
      <SpeakerIcon />
      {t('patient.asking')}
    </p>
  );
}

function SpeakerIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-7"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5H4Z" fill="currentColor" stroke="none" />
      <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
    </svg>
  );
}

function SpellingBoard({
  snap,
  prompt,
  t,
  status,
}: {
  snap: Snapshot;
  prompt: Prompt;
  t: TFn;
  status: ReactNode;
}) {
  const text = snap.spelling?.text ?? '';
  const sub = prompt.sub;
  const label = (s: string) =>
    s === 'SPACE'
      ? t('spell.key.space')
      : s === 'END'
        ? t('spell.key.end')
        : s === 'UNDO'
          ? t('spell.key.undo')
          : s;
  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col items-center gap-[clamp(8px,2.5vh,32px)]">
      <div className="flex w-full flex-col items-center gap-2">
        <p className="text-[clamp(18px,2.2vw,24px)] text-mist-soft [@media(max-height:520px)]:sr-only">
          {t('patient.spelled_so_far')}
        </p>
        <p className="tabular flex min-h-[1.2em] flex-wrap justify-center text-center text-[clamp(40px,min(7vw,11vh),96px)] font-bold leading-none tracking-[0.08em] text-paper">
          <span className="sr-only">{text.trim() ? text : t('patient.spelled_empty')}</span>
          {text.split('').map((c, i) => (
            <span key={i} aria-hidden="true" className={c === ' ' ? 'w-[0.6em]' : undefined}>
              {c}
            </span>
          ))}
          {sub === 'letter' ? (
            <span
              aria-hidden="true"
              className="ml-1 inline-block w-[0.6em] border-b-[6px] border-voice"
            />
          ) : null}
        </p>
      </div>

      {sub === 'word' && prompt.word ? (
        <p className="rounded-[18px] bg-voice px-8 py-3 text-[clamp(40px,min(7vw,11vh),96px)] font-bold leading-none tracking-[0.06em] text-ink">
          {prompt.word}?
        </p>
      ) : null}

      <h1
        key={prompt.id}
        aria-live="polite"
        className="enter-line max-w-[26ch] text-center text-[clamp(28px,min(4.6vw,8vh),64px)] [@media(orientation:landscape)]:max-w-[40ch] font-bold leading-[1.1] text-paper"
      >
        {prompt.text}
      </h1>

      {sub === 'letter' ? (
        <div className="w-full" aria-label={t('patient.letter_grid')} role="group">
          <ul className="grid grid-cols-7 gap-1.5 sm:grid-cols-9 sm:gap-2 lg:grid-cols-13 [@media(orientation:landscape)]:grid-cols-13">
            {LETTERS.map((l) => {
              const on = isHighlighted(l, prompt.group);
              return (
                <li
                  key={l}
                  aria-current={on || undefined}
                  className={cx(
                    'flex h-[clamp(34px,min(12vw,10vh),88px)] items-center justify-center rounded-[10px] text-[clamp(22px,min(3.6vw,6vh),48px)] font-bold',
                    on ? 'bg-voice text-ink' : 'bg-night-2 font-normal text-mist-soft',
                  )}
                >
                  {l}
                </li>
              );
            })}
          </ul>
          <ul className="mt-1.5 grid grid-cols-3 gap-1.5 sm:mt-2 sm:gap-2">
            {SPECIALS.map((s) => {
              const on = isHighlighted(s, prompt.group);
              return (
                <li
                  key={s}
                  aria-current={on || undefined}
                  className={cx(
                    'flex h-[clamp(34px,8vh,64px)] items-center justify-center rounded-[10px] px-2 text-[clamp(18px,min(2.4vw,5vh),30px)] font-bold',
                    on ? 'bg-voice text-ink' : 'bg-night-2 font-normal text-mist-soft',
                  )}
                >
                  {label(s)}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {status}
    </div>
  );
}

function MessageView({
  text,
  hypothesisId,
  t,
}: {
  text: string;
  hypothesisId: string | null | undefined;
  t: TFn;
}) {
  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col items-center gap-6 text-center">
      <h1 className="flex items-center gap-3 text-[clamp(20px,2.6vw,30px)] font-semibold text-voice">
        <SpeakerIcon />
        {t('message.confirmed_label')}
      </h1>
      <div className="flex w-full flex-col items-center gap-[clamp(12px,3vh,24px)] rounded-[28px] bg-voice px-6 py-[clamp(16px,5vh,48px)] text-ink sm:px-12 md:flex-row md:text-left">
        <Pictogram
          id={hypothesisId}
          size={200}
          fluid
          className="size-[clamp(88px,22vh,200px)] rounded-[18px] p-1.5"
        />
        <blockquote
          aria-live="assertive"
          className="enter-line text-[clamp(40px,min(7.4vw,12vh),116px)] font-bold leading-[1.05] tracking-[-0.01em]"
        >
          {text}
        </blockquote>
      </div>
    </div>
  );
}

function CalmScreen({
  title,
  body,
  quiet = false,
  children,
}: {
  title: string;
  body?: string;
  quiet?: boolean;
  children?: ReactNode;
}) {
  return (
    <div role="status" className="mx-auto flex max-w-[900px] flex-col items-center text-center">
      <h1
        className={cx(
          'font-bold leading-[1.1]',
          quiet
            ? 'text-[clamp(28px,4vw,48px)] text-mist-soft'
            : 'text-[clamp(40px,6vw,88px)] text-paper',
        )}
      >
        {title}
      </h1>
      {body ? (
        <p className="mt-6 max-w-[30ch] text-[clamp(22px,3vw,36px)] leading-snug text-mist">
          {body}
        </p>
      ) : null}
      {children}
    </div>
  );
}

function EmergencyScreen({ t }: { t: TFn }) {
  return (
    <div
      role="alert"
      className="alarm-flash fixed inset-0 z-30 flex flex-col items-center justify-center gap-6 bg-alarm px-6 text-center text-paper"
    >
      <svg
        viewBox="0 0 24 24"
        className="size-24 sm:size-32"
        aria-hidden="true"
        fill="currentColor"
      >
        <path d="M12 2.5 1.8 20.5h20.4L12 2.5Zm0 6.2c.7 0 1.2.5 1.1 1.2l-.3 5a.8.8 0 0 1-1.6 0l-.3-5c0-.7.4-1.2 1.1-1.2Zm0 8a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4Z" />
      </svg>
      <h1 className="text-[clamp(44px,8vw,112px)] font-bold leading-none">
        {t('patient.emergency.title')}
      </h1>
      <p className="max-w-[24ch] text-[clamp(24px,3.4vw,44px)] leading-snug">
        {t('patient.emergency.body')}
      </p>
      <p className="absolute inset-x-0 bottom-3 px-4 text-sm">{t('footer.not_device')}</p>
    </div>
  );
}
