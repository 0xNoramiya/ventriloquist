import { useEffect } from 'react';
import type { ClientMessage, ServerMessage } from '../api/types';
import { demoBridge, isBrowserDemo } from '../demo/bridge';
import { useSession } from '../store/session';

const PING_MS = 20_000;

// Hosted demo: one shared subscription to the in-browser session, however many views are mounted
// (the demo page shows the caregiver and patient views side by side).
let demoRefs = 0;
let demoUnsubscribe: (() => void) | null = null;

function attachDemo(sid: string): () => void {
  const store = useSession.getState();
  if (store.sid !== sid) store.reset(sid);
  store.setConnection('connecting');
  store.setSender((msg: ClientMessage) => {
    if (msg.type !== 'ping') void demoBridge.send(msg);
    return true;
  });
  demoRefs += 1;
  if (!demoUnsubscribe) {
    demoUnsubscribe = demoBridge.subscribe((m) => useSession.getState().receive(m));
  }
  void demoBridge.snapshot().then(
    (snap) => {
      if (snap) useSession.getState().receive({ type: 'snapshot', snapshot: snap });
      else useSession.getState().setConnection('missing');
    },
    () => useSession.getState().setConnection('missing'),
  );
  return () => {
    demoRefs -= 1;
    if (demoRefs === 0 && demoUnsubscribe) {
      demoUnsubscribe();
      demoUnsubscribe = null;
    }
  };
}

function wsUrl(sid: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/sessions/${encodeURIComponent(sid)}`;
}

/**
 * Keeps one WebSocket open to the session, reconnecting with backoff, and feeds every server
 * message into the session store. The backend sends a full snapshot after every change.
 */
export function useSessionSocket(sid: string | undefined): void {
  useEffect(() => {
    if (!sid) return;
    if (isBrowserDemo) return attachDemo(sid);
    const store = useSession.getState();
    store.reset(sid);
    store.setConnection('connecting');

    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let retryTimer: number | undefined;
    let pingTimer: number | undefined;
    const queue: ClientMessage[] = [];

    const send = (msg: ClientMessage): boolean => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
        return true;
      }
      // Hold a few messages until the socket is back; drop pings.
      if (msg.type !== 'ping') queue.push(msg);
      return false;
    };
    store.setSender(send);

    const open = () => {
      ws = new WebSocket(wsUrl(sid));
      ws.onopen = () => {
        attempt = 0;
        useSession.getState().setConnection('open');
        while (queue.length && ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(queue.shift()));
        }
        window.clearInterval(pingTimer);
        pingTimer = window.setInterval(() => send({ type: 'ping' }), PING_MS);
      };
      ws.onmessage = (e: MessageEvent<string>) => {
        try {
          useSession.getState().receive(JSON.parse(e.data) as ServerMessage);
        } catch (err) {
          console.error('bad message from server', err);
        }
      };
      ws.onclose = (e) => {
        window.clearInterval(pingTimer);
        if (closed) return;
        if (e.code === 4404) {
          useSession.getState().setConnection('missing');
          return;
        }
        useSession.getState().setConnection('reconnecting');
        attempt += 1;
        const delay = Math.min(8000, 500 * 2 ** Math.min(attempt, 4));
        retryTimer = window.setTimeout(open, delay);
      };
    };
    open();

    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pingTimer);
      ws?.close();
      useSession.getState().setSender(() => false);
    };
  }, [sid]);
}
