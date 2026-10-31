import type {
  CalibrationSummary,
  FramingResult,
  MemoryEntry,
  MemoryView,
  OverrideAction,
  Patient,
  PatientProfile,
  PublicConfig,
  SimResults,
  Snapshot,
} from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (d && typeof d === 'object' && 'msg' in d) {
          const loc = Array.isArray((d as { loc?: unknown }).loc)
            ? (d as { loc: unknown[] }).loc.slice(1).join('.')
            : '';
          return loc ? `${loc}: ${String((d as { msg: unknown }).msg)}` : String(d.msg);
        }
        return String(d);
      })
      .join('; ');
  }
  return '';
}

const PASSCODE_KEY = 'ventriloquist.livePasscode';

/** On a public deployment, live mode is for browsers that entered the passcode in Settings. */
export function livePasscode(): string | null {
  try {
    return window.localStorage.getItem(PASSCODE_KEY);
  } catch {
    return null;
  }
}

export function setLivePasscode(passcode: string | null): void {
  try {
    if (passcode) window.localStorage.setItem(PASSCODE_KEY, passcode);
    else window.localStorage.removeItem(PASSCODE_KEY);
  } catch {
    // not kept: this visit only
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const passcode = livePasscode();
  const headers = new Headers(init.headers);
  if (passcode) headers.set('X-Live-Passcode', passcode);
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      message = detailText(body.detail) || message;
    } catch {
      // the body was not JSON; keep the status line
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

function json<T>(path: string, method: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function upload<T>(path: string, fields: Record<string, string | Blob>, filename?: string) {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (v instanceof Blob) form.append(k, v, filename ?? k);
    else form.append(k, v);
  }
  return request<T>(path, { method: 'POST', body: form });
}

export function extFor(blob: Blob): string {
  if (blob.type.includes('mp4')) return 'mp4';
  if (blob.type.includes('webm')) return 'webm';
  if (blob.type.includes('png')) return 'png';
  if (blob.type.includes('jpeg')) return 'jpg';
  if (blob.type.includes('ogg')) return 'ogg';
  if (blob.type.includes('wav')) return 'wav';
  return 'bin';
}

export interface SettingsUpdate {
  app_mode?: 'mock' | 'live';
  privacy_mode?: boolean;
  language?: 'en' | 'id';
  window_s?: number;
  tau_confirm?: number;
  budget_max_usd?: number;
  keep_clips_for_evaluation?: boolean;
  use_sam?: boolean;
  use_spark_judge?: boolean;
  use_transcribe?: boolean;
  use_wonder?: boolean;
  idle_watch?: boolean;
  passcode?: string;
}

export const api = {
  config: () => request<PublicConfig>('/config'),
  updateSettings: (body: SettingsUpdate) => json<PublicConfig>('/settings', 'PUT', body),

  startScenario: (name: string, body: { simulated: boolean; noise?: number; language?: string }) =>
    json<Snapshot>(`/scenarios/${encodeURIComponent(name)}`, 'POST', body),

  createPatient: (profile: PatientProfile) => json<Patient>('/patients', 'POST', profile),
  patient: (pid: string) => request<Patient>(`/patients/${encodeURIComponent(pid)}`),

  createSession: (body: { patient_id: string; privacy?: boolean; passcode?: string }) =>
    json<Snapshot>('/sessions', 'POST', body),
  start: (sid: string) => json<Snapshot>(`/sessions/${encodeURIComponent(sid)}/start`, 'POST'),

  framing: (pid: string, image: Blob) =>
    upload<FramingResult>(
      `/calibration/${encodeURIComponent(pid)}/framing`,
      { file: image },
      `framing.${extFor(image)}`,
    ),
  calibrationClip: (pid: string, label: string, clip: Blob) =>
    upload<{ label: string; index: number; counts: Record<string, number> }>(
      `/calibration/${encodeURIComponent(pid)}/clip`,
      { label, file: clip },
      `${label}.${extFor(clip)}`,
    ),
  resetCalibrationClips: (pid: string) =>
    request<{ counts: Record<string, number> }>(`/calibration/${encodeURIComponent(pid)}/clips`, {
      method: 'DELETE',
    }),
  finalizeCalibration: (pid: string, body: { hint?: string; skip?: boolean }) =>
    json<CalibrationSummary>(`/calibration/${encodeURIComponent(pid)}/finalize`, 'POST', body),
  editDescription: (pid: string, body: Record<string, unknown>) =>
    json<CalibrationSummary>(`/calibration/${encodeURIComponent(pid)}/description`, 'PUT', body),

  sessionSnapshotImage: (sid: string, image: Blob) =>
    upload<{ facts: string[] }>(
      `/sessions/${encodeURIComponent(sid)}/snapshot`,
      { file: image },
      `snapshot.${extFor(image)}`,
    ),
  sessionClip: (sid: string, promptId: string, clip: Blob) =>
    upload<{ accepted: boolean }>(
      `/sessions/${encodeURIComponent(sid)}/clip`,
      { prompt_id: promptId, file: clip },
      `clip.${extFor(clip)}`,
    ),
  idleClip: (sid: string, clip: Blob) =>
    upload<{ answer: string }>(
      `/sessions/${encodeURIComponent(sid)}/idle`,
      { file: clip },
      `idle.${extFor(clip)}`,
    ),
  sessionAudio: (sid: string, audio: Blob, filename: string) =>
    upload<{ segments: unknown[] }>(
      `/sessions/${encodeURIComponent(sid)}/audio`,
      { file: audio },
      filename,
    ),
  transcript: (sid: string, speaker: string, text: string) =>
    json<unknown>(`/sessions/${encodeURIComponent(sid)}/transcript`, 'POST', { speaker, text }),
  event: (sid: string, kind: string, label?: string) =>
    json<unknown>(`/sessions/${encodeURIComponent(sid)}/event`, 'POST', { kind, label }),
  override: (sid: string, action: OverrideAction) =>
    json<{ ok: boolean; snapshot: Snapshot }>(
      `/sessions/${encodeURIComponent(sid)}/override`,
      'POST',
      { action },
    ),
  unlock: (passcode: string) => json<{ ok: boolean }>('/unlock', 'POST', { passcode }),
  relayAction: (sid: string, relayId: string, action: 'approve' | 'cancel' | 'read') =>
    json<{ ok: boolean; snapshot: Snapshot }>(
      `/sessions/${encodeURIComponent(sid)}/relays/${encodeURIComponent(relayId)}/${action}`,
      'POST',
    ),
  ackMessage: (sid: string, messageId: string) =>
    json<{ ok: boolean; snapshot: Snapshot }>(
      `/sessions/${encodeURIComponent(sid)}/messages/${encodeURIComponent(messageId)}/ack`,
      'POST',
    ),

  memory: (pid: string) => request<MemoryView>(`/memory/${encodeURIComponent(pid)}`),
  addMemory: (pid: string, text: string, category?: string) =>
    json<MemoryEntry>(`/memory/${encodeURIComponent(pid)}`, 'POST', { text, category }),
  curate: (pid: string) =>
    json<{ proposed: number; rejected: unknown[] }>(
      `/memory/${encodeURIComponent(pid)}/curate`,
      'POST',
      {},
    ),
  approveOp: (pid: string, op: string) =>
    json<unknown>(
      `/memory/${encodeURIComponent(pid)}/ops/${encodeURIComponent(op)}/approve`,
      'POST',
    ),
  rejectOp: (pid: string, op: string) =>
    json<unknown>(
      `/memory/${encodeURIComponent(pid)}/ops/${encodeURIComponent(op)}/reject`,
      'POST',
    ),
  deleteMemory: (pid: string, entry: string) =>
    request<unknown>(`/memory/${encodeURIComponent(pid)}/${encodeURIComponent(entry)}`, {
      method: 'DELETE',
    }),

  simResults: () => request<SimResults>('/sim/results'),
  runSim: (trials: number) => json<SimResults>('/sim/run', 'POST', { trials, seed: 7 }),
};
