/**
 * Main-thread side of the hosted demo. One worker per tab runs the Python session; this module
 * exposes the same operations the HTTP API and WebSocket provide, so the rest of the app is
 * unchanged.
 */
import type { PublicConfig, ServerMessage, Snapshot } from '../api/types';
import type { WorkerReply, WorkerRequest } from './pyodideWorker';

export const isBrowserDemo = import.meta.env.VITE_DEMO === 'browser';

export type DemoStage = 'idle' | 'python' | 'packages' | 'engine' | 'ready' | 'error';

type Pending = { resolve: (v: string | null) => void; reject: (e: Error) => void };
type Distribute<T> = T extends unknown ? Omit<T, 'id'> : never;

class DemoBridge {
  private worker: Worker | null = null;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private listeners = new Set<(msg: ServerMessage) => void>();
  private stageListeners = new Set<(stage: DemoStage) => void>();
  private ready: Promise<void> | null = null;
  stage: DemoStage = 'idle';

  private setStage(stage: DemoStage): void {
    this.stage = stage;
    this.stageListeners.forEach((fn) => fn(stage));
  }

  onStage(fn: (stage: DemoStage) => void): () => void {
    this.stageListeners.add(fn);
    fn(this.stage);
    return () => this.stageListeners.delete(fn);
  }

  subscribe(fn: (msg: ServerMessage) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private call(req: Distribute<WorkerRequest>): Promise<string | null> {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker?.postMessage({ ...req, id });
    });
  }

  init(): Promise<void> {
    if (this.ready) return this.ready;
    this.worker = new Worker(new URL('./pyodideWorker.ts', import.meta.url), { type: 'module' });
    this.worker.onmessage = (e: MessageEvent<WorkerReply>) => {
      const msg = e.data;
      if (msg.type === 'push') {
        const parsed = JSON.parse(msg.data) as ServerMessage;
        this.listeners.forEach((fn) => fn(parsed));
      } else if (msg.type === 'progress') {
        this.setStage(msg.stage);
      } else {
        const p = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (!p) return;
        if (msg.ok) p.resolve(msg.value);
        else p.reject(new Error(msg.error));
      }
    };
    const bundleUrl = new URL(`${import.meta.env.BASE_URL}pyodide/backend.zip`, window.location.href).href;
    this.ready = this.call({ cmd: 'init', bundleUrl }).then(
      () => undefined,
      (err: Error) => {
        this.setStage('error');
        this.ready = null;
        throw err;
      },
    );
    return this.ready;
  }

  async config(): Promise<PublicConfig> {
    await this.init();
    return JSON.parse((await this.call({ cmd: 'config' })) ?? '{}') as PublicConfig;
  }

  async scenario(name: string, simulated: boolean, noise = 0.05, language?: string): Promise<Snapshot> {
    await this.init();
    const raw = await this.call({ cmd: 'scenario', name, simulated, noise, language: language ?? null });
    return JSON.parse(raw ?? 'null') as Snapshot;
  }

  async snapshot(): Promise<Snapshot | null> {
    await this.init();
    return JSON.parse((await this.call({ cmd: 'snapshot' })) ?? 'null') as Snapshot | null;
  }

  async send(message: Record<string, unknown>): Promise<void> {
    await this.init();
    await this.call({ cmd: 'send', message: JSON.stringify(message) });
  }
}

declare global {
  interface Window {
    __ventriloquistDemo?: DemoBridge;
  }
}

/** One engine per tab: the patient phone on the demo page is a same-origin iframe that reuses
 * the parent's bridge instead of loading a second Python runtime. */
function sharedBridge(): DemoBridge {
  try {
    const parentBridge = window.parent !== window ? window.parent.__ventriloquistDemo : undefined;
    if (parentBridge) return parentBridge;
  } catch {
    // cross-origin parent: fall through to our own engine
  }
  const bridge = new DemoBridge();
  window.__ventriloquistDemo = bridge;
  return bridge;
}

export const demoBridge = sharedBridge();
