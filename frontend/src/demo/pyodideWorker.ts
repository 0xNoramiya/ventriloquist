/// <reference lib="webworker" />
/**
 * Hosted demo: runs the real mock-mode session (backend/app/browser.py) in Pyodide, Python
 * compiled to WebAssembly, inside this worker. Same engine and safety code as the server; no
 * server, no camera, no keys. The page talks to it with postMessage instead of a WebSocket.
 */

const PYODIDE_VERSION = '0.27.7';
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

export type WorkerRequest =
  | { id: number; cmd: 'init'; bundleUrl: string }
  | { id: number; cmd: 'config' }
  | {
      id: number;
      cmd: 'scenario';
      name: string;
      simulated: boolean;
      noise: number;
      language: string | null;
    }
  | { id: number; cmd: 'send'; message: string }
  | { id: number; cmd: 'snapshot' };

export type WorkerReply =
  | { type: 'reply'; id: number; ok: true; value: string | null }
  | { type: 'reply'; id: number; ok: false; error: string }
  | { type: 'push'; data: string }
  | { type: 'progress'; stage: 'python' | 'packages' | 'engine' | 'ready' };

interface PyCallable {
  (...args: unknown[]): unknown;
}

interface BrowserDemo {
  config: PyCallable;
  scenario: PyCallable;
  handle: PyCallable;
  snapshot: PyCallable;
}

interface Pyodide {
  loadPackage(names: string[]): Promise<unknown>;
  unpackArchive(buffer: ArrayBuffer, format: string, options: { extractDir: string }): void;
  runPython(code: string): unknown;
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(name: string, value: unknown): void };
}

// The project's DOM lib types `self` as Window; this module only ever runs as a dedicated worker.
const scope = self as unknown as DedicatedWorkerGlobalScope;
let demo: BrowserDemo | null = null;

function post(msg: WorkerReply): void {
  scope.postMessage(msg);
}

async function init(bundleUrl: string): Promise<void> {
  post({ type: 'progress', stage: 'python' });
  const mod = (await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)) as {
    loadPyodide(opts: { indexURL: string }): Promise<Pyodide>;
  };
  const py = await mod.loadPyodide({ indexURL: PYODIDE_URL });
  post({ type: 'progress', stage: 'packages' });
  await py.loadPackage(['numpy', 'pydantic', 'pyyaml', 'sqlite3']);
  post({ type: 'progress', stage: 'engine' });
  const bundle = await (await fetch(bundleUrl)).arrayBuffer();
  py.unpackArchive(bundle, 'zip', { extractDir: '/vent' });
  py.runPython('import sys; sys.path.insert(0, "/vent/backend")');
  py.globals.set('push', (data: string) => post({ type: 'push', data }));
  demo = (await py.runPythonAsync(
    'from app.browser import BrowserDemo\nBrowserDemo(push, "/tmp/vent")',
  )) as BrowserDemo;
  post({ type: 'progress', stage: 'ready' });
}

async function handle(req: WorkerRequest): Promise<string | null> {
  if (req.cmd === 'init') {
    if (!demo) await init(req.bundleUrl);
    return null;
  }
  if (!demo) throw new Error('demo engine not loaded');
  switch (req.cmd) {
    case 'config':
      return String(demo.config());
    case 'scenario':
      return String(
        await (demo.scenario(req.name, req.simulated, req.noise, req.language) as Promise<unknown>),
      );
    case 'send':
      return String(await (demo.handle(req.message) as Promise<unknown>));
    case 'snapshot':
      return String(demo.snapshot());
  }
}

scope.onmessage = (e: MessageEvent<WorkerRequest>) => {
  const req = e.data;
  handle(req).then(
    (value) => post({ type: 'reply', id: req.id, ok: true, value }),
    (err: unknown) => post({ type: 'reply', id: req.id, ok: false, error: String(err) }),
  );
};
