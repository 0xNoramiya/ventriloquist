import { create } from 'zustand';
import type { ClientMessage, ServerEvent, ServerMessage, Snapshot } from '../api/types';

export type Connection = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'missing';

export interface Banner {
  id: number;
  kind: 'alert' | 'error';
  text: string;
}

export interface AlarmState {
  active: boolean;
  text: string | null;
  textEn: string | null;
}

export interface SessionData {
  sid: string | null;
  snapshot: Snapshot | null;
  connection: Connection;
  alarm: AlarmState;
  banners: Banner[];
  /** Increments on every alarm event so views can replay the tone even if already active. */
  alarmSeq: number;
  nextBannerId: number;
  /** The latest server event, numbered so a view can react to each one exactly once. */
  lastEvent: { seq: number; event: ServerEvent } | null;
}

export const initialSession: SessionData = {
  sid: null,
  snapshot: null,
  connection: 'idle',
  alarm: { active: false, text: null, textEn: null },
  banners: [],
  alarmSeq: 0,
  nextBannerId: 1,
  lastEvent: null,
};

const MAX_BANNERS = 4;

/** Pure reducer for server messages. Kept free of side effects so it can be unit tested. */
export function reduceServerMessage(state: SessionData, msg: ServerMessage): SessionData {
  if (msg.type === 'pong') return state;
  if (msg.type === 'error') return { ...state, connection: 'missing' };

  const snap = msg.snapshot;
  const event = msg.event;
  let next: SessionData = { ...state, snapshot: snap, connection: 'open' };
  if (event) {
    next = { ...next, lastEvent: { seq: (state.lastEvent?.seq ?? 0) + 1, event } };
  }

  if (event?.type === 'alarm') {
    next = {
      ...next,
      alarm: {
        active: true,
        text: event.text ?? null,
        textEn: event.text_en ?? event.text ?? null,
      },
      alarmSeq: state.alarmSeq + 1,
    };
  } else if (snap.emergency && !state.alarm.active) {
    // Joined while an alarm was already running (for example after a reload).
    next = {
      ...next,
      alarm: { active: true, text: null, textEn: null },
      alarmSeq: state.alarmSeq + 1,
    };
  } else if (!snap.emergency && state.alarm.active) {
    next = { ...next, alarm: { active: false, text: null, textEn: null } };
  }

  if ((event?.type === 'alert' || event?.type === 'error') && event.text) {
    const banner: Banner = { id: state.nextBannerId, kind: event.type, text: event.text };
    next = {
      ...next,
      banners: [...next.banners, banner].slice(-MAX_BANNERS),
      nextBannerId: state.nextBannerId + 1,
    };
  }
  return next;
}

export function dismissBanner(state: SessionData, id: number): SessionData {
  return { ...state, banners: state.banners.filter((b) => b.id !== id) };
}

interface SessionStore extends SessionData {
  receive: (msg: ServerMessage) => void;
  setConnection: (c: Connection) => void;
  dismiss: (id: number) => void;
  reset: (sid: string | null) => void;
  send: (msg: ClientMessage) => boolean;
  setSender: (fn: (msg: ClientMessage) => boolean) => void;
}

export const useSession = create<SessionStore>((set) => ({
  ...initialSession,
  receive: (msg) => set((s) => reduceServerMessage(s, msg)),
  setConnection: (connection) => set({ connection }),
  dismiss: (id) => set((s) => dismissBanner(s, id)),
  reset: (sid) => set({ ...initialSession, sid }),
  send: () => false,
  setSender: (fn) => set({ send: fn }),
}));

export function sendMessage(msg: ClientMessage): boolean {
  return useSession.getState().send(msg);
}
