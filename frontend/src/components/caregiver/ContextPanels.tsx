import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from '../../api/client';
import type { Evidence } from '../../api/types';
import { useT, type Key } from '../../i18n';
import { cx } from '../../lib/format';
import { Button } from '../Button';
import { Notice, Select, Switch, inputClass } from '../Form';

function ago(t: ReturnType<typeof useT>, minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '';
  if (minutes < 1) return t('time.just_now');
  if (minutes < 90) return t('time.ago', { m: Math.round(minutes) });
  return t('time.ago_h', { h: (minutes / 60).toFixed(1) });
}

function EvidenceRow({ e }: { e: Evidence }) {
  const t = useT();
  return (
    <li className="grid grid-cols-[3rem_1fr] gap-x-2 py-2">
      <span className="tabular inline-flex h-6 w-fit items-center rounded-[var(--radius-chip)] bg-paper px-1.5 text-[13px] font-bold shadow-[inset_0_0_0_1px_var(--color-line-strong)]">
        {e.id}
      </span>
      <div className="min-w-0">
        <p className="leading-snug">{e.text}</p>
        <p className="text-sm text-muted">
          {t(`evidence.kind.${e.kind}` as Key)}
          {e.minutes_ago !== null && e.minutes_ago !== undefined
            ? ` · ${ago(t, e.minutes_ago)}`
            : ''}
        </p>
      </div>
    </li>
  );
}

/** Scene facts, caregiver events, memory and history that shaped the guesses. */
export function RoomContext({ evidence }: { evidence: Evidence[] }) {
  const t = useT();
  const items = evidence.filter((e) => e.kind !== 'transcript');
  if (!items.length) return <p className="text-muted">{t('context.empty')}</p>;
  return (
    <ul className="flex flex-col divide-y divide-line">
      {items.map((e) => (
        <EvidenceRow key={e.id} e={e} />
      ))}
    </ul>
  );
}

const SPEAKERS = ['Nurse', 'Family', 'Doctor', 'Room'] as const;

export function Transcript({
  sid,
  evidence,
  mock,
}: {
  sid: string;
  evidence: Evidence[];
  mock: boolean;
}) {
  const t = useT();
  const lines = evidence.filter((e) => e.kind === 'transcript');
  const [speaker, setSpeaker] = useState<string>('Nurse');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<'line' | 'audio' | null>(null);
  const [status, setStatus] = useState<{ tone: 'good' | 'error'; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function addLine(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy('line');
    setStatus(null);
    try {
      await api.transcript(sid, speaker, text.trim());
      await api.override(sid, 'refresh_context');
      setText('');
      setStatus({ tone: 'good', text: t('transcript.added') });
    } catch (err) {
      setStatus({ tone: 'error', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function upload(file: File) {
    setBusy('audio');
    setStatus(null);
    try {
      const res = await api.sessionAudio(sid, file, file.name || 'room-audio.webm');
      await api.override(sid, 'refresh_context');
      setStatus({ tone: 'good', text: t('transcript.audio_done', { n: res.segments.length }) });
    } catch (err) {
      setStatus({ tone: 'error', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {lines.length ? (
        <ul className="flex flex-col divide-y divide-line">
          {lines.map((e) => (
            <EvidenceRow key={e.id} e={e} />
          ))}
        </ul>
      ) : (
        <p className="text-muted">{t('transcript.empty')}</p>
      )}
      <form onSubmit={(e) => void addLine(e)} className="flex flex-col gap-2">
        <p className="text-sm text-muted">
          {mock ? t('transcript.mock_hint') : t('transcript.live_hint')}
        </p>
        <div className="grid grid-cols-[minmax(7rem,9rem)_1fr] gap-2">
          <label className="sr-only" htmlFor="tr-speaker">
            {t('transcript.speaker')}
          </label>
          <Select id="tr-speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value)}>
            {SPEAKERS.map((s) => (
              <option key={s} value={s}>
                {t(`transcript.speaker.${s}` as Key)}
              </option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="tr-text">
            {t('transcript.line')}
          </label>
          <input
            id="tr-text"
            className={inputClass}
            value={text}
            maxLength={1000}
            placeholder={t('transcript.placeholder')}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" busy={busy === 'line'} disabled={!text.trim()}>
            {t('transcript.add')}
          </Button>
          <input
            ref={fileRef}
            id="tr-audio"
            type="file"
            accept="audio/*,video/webm"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void upload(f);
            }}
          />
          <label
            htmlFor="tr-audio"
            className={cx(
              'inline-flex min-h-12 cursor-pointer items-center gap-2 rounded-[var(--radius-control)] px-4 font-semibold text-ink hover:bg-wash',
              '[input:focus-visible+&]:outline-3 [input:focus-visible+&]:outline-offset-2 [input:focus-visible+&]:outline-[var(--focus)]',
              busy === 'audio' && 'pointer-events-none opacity-60',
            )}
          >
            {busy === 'audio' ? t('transcript.audio_busy') : t('transcript.audio')}
          </label>
        </div>
      </form>
      {status ? <Notice tone={status.tone}>{status.text}</Notice> : null}
      {mock ? null : <RoomMic sid={sid} />}
    </div>
  );
}

const CHUNK_MS = 8000;

function audioMime(): string | undefined {
  for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) return m;
  }
  return undefined;
}

function recordAudio(stream: MediaStream, ms: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const mimeType = audioMime();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const parts: Blob[] = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) parts.push(e.data);
    };
    rec.onerror = () => reject(new Error('recording failed'));
    rec.onstop = () => resolve(new Blob(parts, { type: rec.mimeType || 'audio/webm' }));
    rec.start();
    window.setTimeout(() => rec.state !== 'inactive' && rec.stop(), ms);
  });
}

/**
 * Room listener (live and privacy modes): records the room in 8-second chunks and sends each to
 * the transcriber. Opt-in, off by default; the backend drops anything that repeats what the phone
 * itself just said.
 */
function RoomMic({ sid }: { sid: string }) {
  const t = useT();
  const [on, setOn] = useState(false);
  const [sent, setSent] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!on) return;
    let stopped = false;
    let stream: MediaStream | null = null;
    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setOn(false);
        return;
      }
      while (!stopped && stream) {
        const blob = await recordAudio(stream, CHUNK_MS);
        if (stopped) break;
        const ext = blob.type.includes('mp4') ? 'm4a' : 'webm';
        void api
          .sessionAudio(sid, blob, `room.${ext}`)
          .then(async (res) => {
            setSent((n) => n + 1);
            if (res.segments.length) await api.override(sid, 'refresh_context');
          })
          .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
      }
    })();
    return () => {
      stopped = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [on, sid]);

  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <Switch
        checked={on}
        onChange={(v) => {
          setError(null);
          setOn(v);
        }}
        label={t('transcript.mic')}
        description={t('transcript.mic_hint')}
      />
      {on ? (
        <p role="status" className="text-sm text-muted">
          {t('transcript.mic_status', { n: sent })}
        </p>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}
    </div>
  );
}

const EVENT_KEYS: Record<string, Key> = {
  suctioned: 'event.suctioned',
  repositioned: 'event.repositioned',
  mouth_care: 'event.mouth_care',
  visitor_arrived: 'event.visitor_arrived',
  visitor_left: 'event.visitor_left',
  family_called: 'event.family_called',
  medication_given: 'event.medication_given',
  procedure_done: 'event.procedure_done',
};

export function CaregiverEvents({ sid }: { sid: string }) {
  const t = useT();
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<{ tone: 'good' | 'error'; text: string } | null>(null);

  async function log(kind: string, label?: string) {
    setBusy(kind);
    setStatus(null);
    try {
      await api.event(sid, kind, label);
      await api.override(sid, 'refresh_context');
      setStatus({
        tone: 'good',
        text: t('event.logged', { what: label ?? t(EVENT_KEYS[kind] ?? 'event.note') }),
      });
      if (kind === 'note') setNote('');
    } catch (err) {
      setStatus({ tone: 'error', text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-4">
        {Object.entries(EVENT_KEYS).map(([kind, key]) => (
          <li key={kind}>
            <Button
              className="w-full"
              busy={busy === kind}
              disabled={busy !== null && busy !== kind}
              onClick={() => void log(kind)}
            >
              {t(key)}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (note.trim()) void log('note', note.trim());
        }}
      >
        <label className="sr-only" htmlFor="ev-note">
          {t('event.note')}
        </label>
        <input
          id="ev-note"
          className={inputClass}
          maxLength={120}
          value={note}
          placeholder={t('event.note_placeholder')}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button type="submit" className="shrink-0" busy={busy === 'note'} disabled={!note.trim()}>
          {t('event.add_note')}
        </Button>
      </form>
      <p className="text-sm text-muted">{t('event.hint')}</p>
      {status ? <Notice tone={status.tone}>{status.text}</Notice> : null}
    </div>
  );
}
