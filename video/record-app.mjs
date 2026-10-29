// Screen recordings of the running app for the demo video (APP footage in docs/DEMO_SCRIPT.md).
//
//   VENT_PASSCODE=... node record-app.mjs calibrate   live: calibrate the daughter-scenario patient
//   VENT_PASSCODE=... node record-app.mjs session     live: the session, relay, acknowledgement, alarm
//   VENT_PASSCODE=... node record-app.mjs privacy     privacy: answers read by Muse Spark Open
//   node record-app.mjs spelling                      mock: spelling with the simulated patient
//
// VENT_BASE points it at another server running the same build (default: the fly.io app).
//
// The camera is the generated Mr Hasan clips from data/labeled_generated (the detector eval set):
// getUserMedia returns a canvas that loops a rest clip, and the moment the app starts a
// MediaRecorder the canvas switches to the clip queued for that answer. So in live mode SAM 3.1 and
// the blind judge really read every answer. Frames come from Chrome's screencast and are encoded
// afterwards; events.json has the timeline for the edit.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const BASE = process.env.VENT_BASE ?? 'https://ventriloquist.fly.dev';
const FLY_IP = '66.241.124.160'; // WSL can't resolve the fly hostname
const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const CLIP_DIR = here('../data/labeled_generated/');
const OUT = here('media/app/');
const STATE = `${OUT}state.json`;
const TRUTH = 'see_person:aisyah';

const CLIPS = {
  cal_rest_0: 'calibration/rest_0.mp4',
  cal_yes_0: 'calibration/yes_0.mp4',
  cal_yes_1: 'calibration/yes_1.mp4',
  cal_yes_2: 'calibration/yes_2.mp4',
  cal_no_0: 'calibration/no_0.mp4',
  cal_no_1: 'calibration/no_1.mp4',
  cal_no_2: 'calibration/no_2.mp4',
  cal_emergency_0: 'calibration/emergency_0.mp4',
  yes_1: 'yes/yes_eval_1.mp4',
  yes_2: 'yes/yes_eval_2.mp4',
  yes_3: 'yes/yes_eval_3.mp4',
  no_0: 'no/no_eval_0.mp4',
  no_1: 'no/no_eval_1.mp4',
  no_2: 'no/no_eval_2.mp4',
  no_3: 'no/no_eval_3.mp4',
  emergency_0: 'emergency/emergency_eval_0.mp4',
};

/** Runs in every page before the app: the fake camera, and the passcode for live mode. */
function pageSetup({ passcode }) {
  if (passcode) localStorage.setItem('ventriloquist.livePasscode', passcode);
  const W = 640;
  const H = 480;
  let canvas = null;
  let current = null;
  let queued = null;
  const urls = {};
  const src = (name) =>
    (urls[name] ??= fetch(`/__cam/${name}.mp4`)
      .then((r) => r.blob())
      .then((b) => URL.createObjectURL(b)));
  async function play(name, loop) {
    const v = document.createElement('video');
    v.muted = true;
    v.playsInline = true;
    v.loop = loop;
    v.src = await src(name);
    await v.play().catch(() => undefined);
    if (!loop) v.onended = () => void play('cal_rest_0', true);
    current = v;
  }
  function ensure() {
    if (canvas) return;
    canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext('2d');
    // keep drawing the previous clip until the next one has a frame, so there's never a black frame
    setInterval(() => current?.readyState >= 2 && ctx.drawImage(current, 0, 0, W, H), 33);
    void play('cal_rest_0', true);
  }
  window.__cam = { queue: (name) => (queued = name) };
  const md = navigator.mediaDevices;
  if (md) {
    const gum = md.getUserMedia.bind(md);
    md.getUserMedia = async (c) => {
      if (!c?.video) return gum(c);
      ensure();
      await new Promise((r) => setTimeout(r, 400));
      return canvas.captureStream(30);
    };
  }
  const start = MediaRecorder.prototype.start;
  MediaRecorder.prototype.start = function (...args) {
    if (queued) void play(queued, false);
    queued = null;
    return start.apply(this, args);
  };
}

const events = [];
const note = (what, extra = {}) => {
  events.push({ t: Date.now() / 1000, what, ...extra });
  console.log(new Date().toISOString().slice(11, 19), what, Object.keys(extra).length ? JSON.stringify(extra) : '');
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function newPage(browser, { width, height, live, name }) {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1.5,
    permissions: ['camera'],
  });
  await context.route('**/__cam/*.mp4', (route) => {
    const name = new URL(route.request().url()).pathname.split('/').pop().replace('.mp4', '');
    return route.fulfill({ path: CLIP_DIR + CLIPS[name], contentType: 'video/mp4' });
  });
  await context.addInitScript(pageSetup, { passcode: live ? process.env.VENT_PASSCODE : null });
  const page = await context.newPage();
  page.on('pageerror', (e) => note('pageerror', { page: name, error: String(e).slice(0, 200) }));
  return page;
}

/** Chrome's screencast, frame by frame with timestamps; stop() encodes a constant 30 fps mp4. */
async function screencast(page, name, dir) {
  const frameDir = `${dir}${name}-frames/`;
  rmSync(frameDir, { recursive: true, force: true });
  mkdirSync(frameDir, { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  let stopped = false;
  cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
    if (stopped) return; // a frame can still arrive after stopScreencast
    const file = `${frameDir}${String(frames.length).padStart(6, '0')}.jpg`;
    writeFileSync(file, Buffer.from(data, 'base64'));
    frames.push({ file, t: metadata.timestamp });
    void cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => undefined);
  });
  const vp = page.viewportSize();
  await cdp.send('Page.startScreencast', {
    format: 'jpeg',
    quality: 90,
    maxWidth: Math.round(vp.width * 1.5),
    maxHeight: Math.round(vp.height * 1.5),
  });
  return async () => {
    stopped = true;
    await cdp.send('Page.stopScreencast').catch(() => undefined);
    const end = Date.now() / 1000;
    const lines = frames.flatMap((f, i) => [
      `file '${f.file}'`,
      `duration ${Math.max(0.001, (frames[i + 1]?.t ?? end) - f.t).toFixed(4)}`,
    ]);
    lines.push(`file '${frames.at(-1).file}'`);
    writeFileSync(`${frameDir}list.txt`, lines.join('\n'));
    const out = `${dir}${name}.mp4`;
    execFileSync('ffmpeg', [
      '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', `${frameDir}list.txt`,
      '-vf', 'fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p',
      '-c:v', 'libx264', '-crf', '16', '-preset', 'medium', out,
    ]);
    rmSync(frameDir, { recursive: true, force: true });
    return { name, file: out, start: frames[0].t, end };
  };
}

/** API calls go through the page: it can resolve the host, and it carries the passcode. */
async function api(page, method, path, body) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const headers = { 'content-type': 'application/json' };
      const pc = localStorage.getItem('ventriloquist.livePasscode');
      if (pc) headers['X-Live-Passcode'] = pc;
      const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
      if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`);
      return r.json();
    },
    { method, path, body },
  );
}

const state = () => (existsSync(STATE) ? JSON.parse(readFileSync(STATE, 'utf8')) : {});
const saveState = (s) => writeFileSync(STATE, JSON.stringify({ ...state(), ...s }, null, 2));

async function calibrate(browser, dir) {
  const page = await newPage(browser, { width: 1280, height: 800, live: true, name: 'console' });
  await page.goto(BASE + '/');
  const snap = await api(page, 'POST', '/api/scenarios/daughter', { language: 'en' });
  note('patient', { pid: snap.patient.id, mode: snap.mode.effective });
  if (snap.mode.effective !== 'live') throw new Error('not live: check VENT_PASSCODE');
  saveState({ pid: snap.patient.id });
  await api(page, 'POST', `/api/sessions/${snap.session_id}/end`).catch(() => undefined);

  await page.goto(`${BASE}/calibrate/${snap.patient.id}`);
  await page.getByText('Small nod').waitFor();
  const stop = await screencast(page, 'calibrate', dir);
  await sleep(1500);
  await page.getByText('Eyebrows up', { exact: true }).first().click();
  note('picked eyebrows');
  await sleep(2500);
  await page.getByRole('button', { name: 'Turn on the camera' }).click();
  await page.getByRole('button', { name: 'Check framing' }).click();
  note('framing check');
  await page.getByText('Face visible').waitFor({ timeout: 60_000 });
  note('framing result');
  await sleep(2500);
  await page.getByRole('button', { name: 'Continue' }).click();

  const tasks = ['rest', 'yes', 'yes', 'yes', 'no', 'no', 'no', 'emergency'];
  const seen = { yes: 0, no: 0, emergency: 0 };
  for (const label of tasks) {
    const clip = label === 'rest' ? null : `cal_${label}_${seen[label]++}`;
    await page.evaluate((c) => window.__cam.queue(c), clip);
    const button = page.getByRole('button', { name: /^Record \d+ seconds$/ });
    await button.click();
    note('record', { label, clip });
    // the button reads "Recording" until the clip is uploaded
    await page.getByRole('button', { name: /^Record \d+ seconds$|^Continue$/ }).waitFor({ timeout: 90_000 });
    await sleep(500);
  }
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByRole('button', { name: 'Analyse examples' }).click();
  note('analyse');
  await page.getByRole('button', { name: /Start a session/ }).waitFor({ timeout: 240_000 });
  note('results');
  await sleep(2000);
  await page.mouse.wheel(0, 500);
  await sleep(3000);
  await page.mouse.wheel(0, 700);
  await sleep(3000);
  return [await stop()];
}

function answerFor(prompt) {
  const yes = new Set(prompt.question?.yes_ids ?? []);
  if (prompt.kind === 'ask' || prompt.kind === 'confirm') return yes.has(TRUTH) ? 'yes' : 'no';
  if (prompt.kind === 'post_check' || prompt.kind === 'relay_offer') return 'yes';
  return 'no';
}

/** Polls the session; queues the camera clip that answers each new question truthfully. */
function driver(cg, ph, sid) {
  let lastPrompt = null;
  let lastState = null;
  let trail = 0;
  const counter = { yes: 0, no: 0 };
  const poll = () => api(cg, 'GET', `/api/sessions/${sid}`);
  const step = async () => {
    const s = await poll();
    if (s.state !== lastState) note('state', { state: s.state });
    lastState = s.state;
    if (s.prompt && s.prompt.id !== lastPrompt) {
      lastPrompt = s.prompt.id;
      const answer = answerFor(s.prompt);
      const clip = answer === 'yes' ? `yes_${(counter.yes++ % 3) + 1}` : `no_${counter.no++ % 4}`;
      await ph.evaluate((c) => window.__cam.queue(c), clip);
      note('prompt', { kind: s.prompt.kind, text: s.prompt.text_en, answer, clip });
    }
    for (const row of s.trail.slice(trail)) {
      note('read', { q: row.text_en, answer: row.answer, source: row.source, confidence: row.confidence, sources: row.sources });
    }
    trail = s.trail.length;
    return s;
  };
  return { poll, step };
}

async function session(browser, dir) {
  const { pid } = state();
  if (!pid) throw new Error('run calibrate first');
  // tall, so the bars, the trail and the latest clip are all in the recording; the edit pans
  const cg = await newPage(browser, { width: 1280, height: 1800, live: true, name: 'console' });
  const ph = await newPage(browser, { width: 390, height: 844, live: true, name: 'phone' });
  await cg.goto(BASE + '/');
  const snap = await api(cg, 'POST', '/api/sessions', { patient_id: pid, scenario: 'daughter' });
  const sid = snap.session_id;
  note('session', { sid, mode: snap.mode.effective });
  saveState({ sid });

  await cg.goto(`${BASE}/caregiver/${sid}`);
  await ph.goto(`${BASE}/patient/${sid}`);
  await ph.getByText('Tap to start').waitFor();
  const stops = [await screencast(cg, 'console', dir), await screencast(ph, 'phone', dir)];
  await sleep(1500);
  await cg.getByRole('button', { name: 'Turn on alarm sound' }).click();
  await sleep(1500);
  await ph.getByText('Tap to start').click();
  note('tap to start');

  const { poll, step } = driver(cg, ph, sid);

  // questions until the message is spoken, checked, and offered to Aisyah
  let s;
  for (let i = 0; i < 600; i++) {
    s = await step();
    if (s.relays?.some((r) => r.status === 'awaiting_approval')) break;
    if (['CAREGIVER_NEEDED'].includes(s.state)) throw new Error('caregiver needed: ' + s.caregiver_reason);
    await sleep(300);
  }
  note('relay offered');
  // the room is empty: wait for the phone to repeat the message
  for (let i = 0; i < 400; i++) {
    s = await step();
    if ((s.pending_ack?.[0]?.announced ?? 1) >= 2) break;
    await sleep(500);
  }
  note('repeated', { announced: s.pending_ack?.[0]?.announced });
  await sleep(3000);
  // "I'm coming" first: approving the relay also acknowledges the message, which removes the card
  await cg.getByRole('button', { name: "I'm coming" }).first().click();
  note("I'm coming");
  await sleep(3500);
  await cg.getByRole('button', { name: 'Send', exact: true }).click();
  note('send approved');
  for (let i = 0; i < 400; i++) {
    s = await step();
    const r = s.relays?.[0];
    if (r?.status === 'review') {
      await sleep(2500);
      await cg.getByRole('button', { name: 'Read it to the patient' }).click();
      note('released for reading');
    }
    if (r?.status === 'read_to_patient') break;
    await sleep(500);
  }
  note('reply read', { reply: s.relays?.[0]?.reply });
  await sleep(6000);

  // the emergency signal during a new message
  await cg.getByRole('button', { name: 'New message' }).click();
  note('new message');
  for (let i = 0; i < 200; i++) {
    s = await poll();
    if (s.state === 'ASKING' || s.state === 'LISTENING') break;
    await sleep(300);
  }
  await ph.evaluate(() => window.__cam.queue('emergency_0'));
  note('emergency queued', { prompt: s.prompt?.text_en });
  for (let i = 0; i < 200; i++) {
    s = await poll();
    if (s.emergency) break;
    await sleep(300);
  }
  note('alarm', { emergency: Boolean(s.emergency) });
  await sleep(4000);
  await cg.getByRole('button', { name: "Acknowledge, I'm going" }).click();
  note('alarm acknowledged');
  await sleep(4000);
  return Promise.all(stops.map((stop) => stop()));
}

async function privacy(browser, dir) {
  const { pid } = state();
  if (!pid) throw new Error('run calibrate first');
  const cg = await newPage(browser, { width: 1280, height: 1800, live: true, name: 'console' });
  const ph = await newPage(browser, { width: 390, height: 844, live: true, name: 'phone' });
  await cg.goto(BASE + '/');
  const snap = await api(cg, 'POST', '/api/sessions', { patient_id: pid, scenario: 'daughter', privacy: true });
  const sid = snap.session_id;
  note('session', { sid, mode: snap.mode.effective, reason: snap.mode.reason });
  if (snap.mode.effective !== 'privacy') throw new Error(`not privacy: ${snap.mode.reason}`);

  await cg.goto(`${BASE}/caregiver/${sid}`);
  await ph.goto(`${BASE}/patient/${sid}`);
  await ph.getByText('Tap to start').waitFor();
  const stops = [await screencast(cg, 'console', dir), await screencast(ph, 'phone', dir)];
  await sleep(1500);
  await cg.getByRole('button', { name: /^Privacy/ }).click(); // shows which models run
  note('mode shown');
  await sleep(2000);
  await ph.getByText('Tap to start').click();
  note('tap to start');
  const { step } = driver(cg, ph, sid);
  // three answers read by the open-weight judge, then a moment to read the trail
  for (let i = 0; i < 600; i++) {
    const s = await step();
    const judged = s.trail.filter((r) => r.sources?.spark && !r.sources.spark.pending);
    if (judged.length >= 3) break;
    if (s.state === 'CAREGIVER_NEEDED') throw new Error('caregiver needed: ' + s.caregiver_reason);
    await sleep(300);
  }
  note('three judged');
  await sleep(5000);
  return Promise.all(stops.map((stop) => stop()));
}

async function spelling(browser, dir) {
  const cg = await newPage(browser, { width: 1280, height: 1800, live: false, name: 'console' });
  const ph = await newPage(browser, { width: 390, height: 844, live: false, name: 'phone' });
  await cg.goto(BASE + '/');
  const snap = await api(cg, 'POST', '/api/scenarios/spelling', { language: 'en', simulated: true, noise: 0 });
  const sid = snap.session_id;
  note('session', { sid, mode: snap.mode.effective });
  await cg.goto(`${BASE}/caregiver/${sid}`);
  await ph.goto(`${BASE}/patient/${sid}`);
  await ph.getByText('Tap to start').waitFor();
  const stops = [await screencast(cg, 'console', dir), await screencast(ph, 'phone', dir)];
  await sleep(1500);
  await ph.getByText('Tap to start').click();
  let switched = false;
  for (let i = 0; i < 900; i++) {
    const s = await api(cg, 'GET', `/api/sessions/${sid}`);
    if (!switched && (s.spelling?.text?.length ?? 0) >= 2) {
      await cg.getByRole('button', { name: /Bahasa Indonesia/ }).click();
      switched = true;
      note('console in Indonesian', { spelled: s.spelling.text });
    }
    if (s.messages?.some((m) => m.status === 'confirmed')) break;
    await sleep(300);
  }
  note('message confirmed');
  await sleep(4000);
  return Promise.all(stops.map((stop) => stop()));
}

const phases = { calibrate, session, privacy, spelling };
const which = process.argv[2];
if (!phases[which]) throw new Error(`usage: node record-app.mjs ${Object.keys(phases).join('|')}`);
const dir = `${OUT}${which}/`;
mkdirSync(dir, { recursive: true });
const browser = await chromium.launch({
  args: [`--host-resolver-rules=MAP ventriloquist.fly.dev ${FLY_IP}`, '--autoplay-policy=no-user-gesture-required'],
});
try {
  const clips = await phases[which](browser, dir);
  writeFileSync(`${dir}events.json`, JSON.stringify({ clips, events }, null, 2));
  for (const c of clips) console.log(c.name, c.file, (c.end - c.start).toFixed(1), 's');
} finally {
  writeFileSync(`${dir}events.partial.json`, JSON.stringify({ events }, null, 2));
  await browser.close();
}
