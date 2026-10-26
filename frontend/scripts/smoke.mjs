// End-to-end smoke test against a running mock backend and `npm run dev`.
// Drives the daughter demo with keyboard answers, raises and acknowledges an emergency, opens the
// spelling board, and screenshots every route at phone and laptop sizes.
//
//   node scripts/smoke.mjs [baseUrl] [screenshotDir]
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright';

const BASE = process.argv[2] ?? 'https://localhost:5173';
const OUT = process.argv[3] ?? 'smoke-screens';
mkdirSync(OUT, { recursive: true });

const PHONE = { width: 390, height: 844 };
const LAPTOP = { width: 1440, height: 900 };
const log = (...a) => console.log('[smoke]', ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({
  args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
});
const ctxOpts = { ignoreHTTPSErrors: true, permissions: ['camera', 'microphone'] };
const laptop = await browser.newContext({ ...ctxOpts, viewport: LAPTOP });
const phone = await browser.newContext({
  ...ctxOpts,
  viewport: PHONE,
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});

const api = laptop.request;
async function snap(sid) {
  const r = await api.get(`${BASE}/api/sessions/${sid}`);
  if (!r.ok()) throw new Error(`session ${sid}: ${r.status()}`);
  return r.json();
}

async function shot(page, name, full = true) {
  const file = join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: full });
  log('screenshot', file);
}

const errors = [];
for (const ctx of [laptop, phone]) {
  ctx.on('page', (p) => {
    p.on('pageerror', (e) => errors.push(`${p.url()}: ${e.message}`));
    p.on('console', (m) => {
      if (m.type() === 'error') errors.push(`${p.url()}: console ${m.text()}`);
    });
  });
}

/** Answer like the fictional patient whose true message is `truth`. */
function oracle(s, truth, spell) {
  const p = s.prompt;
  if (!p) return null;
  if (p.kind === 'post_check') return 'y';
  if (p.kind === 'confirm') return p.question?.target_id === truth ? 'y' : 'n';
  if (p.kind === 'offer_spell') return spell ? 'y' : 'n';
  if (p.kind === 'spelling') {
    const done = (s.spelling?.text ?? '').replace(/ /g, '');
    const next = spell[done.length];
    if (p.sub === 'letter') return p.group.includes(next ?? 'END') ? 'y' : 'n';
    if (p.sub === 'word') return p.word === spell ? 'y' : 'n';
    return 'y';
  }
  const yes = p.question?.yes_ids ?? [];
  return yes.includes(truth) ? 'y' : 'n';
}

/** Wait until the backend is listening for prompt `id` (i.e. the patient screen sent `spoken`). */
async function waitListening(sid, pid, ms = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const s = await snap(sid);
    if (s.prompt?.id !== pid || s.state === 'LISTENING') return s;
    await sleep(250);
  }
  throw new Error(`prompt ${pid} never reached LISTENING (spoken not sent?)`);
}

// ------------------------------------------------------------------ landing
const page = await laptop.newPage();
await page.goto(BASE);
await page.getByRole('heading', { level: 1 }).waitFor();
await sleep(5200); // let the trail play
await shot(page, 'landing-laptop');

// ------------------------------------------------------------------ daughter demo
await page.getByRole('button', { name: 'Start a demo session' }).click();
await page.waitForURL(/\/caregiver\/ses_/);
const sid = page.url().split('/caregiver/')[1];
log('daughter session', sid);
await page.getByText('Open the patient screen on the phone').waitFor();
await shot(page, 'caregiver-laptop-waiting', false);

const patient = await phone.newPage();
await patient.goto(`${BASE}/patient/${sid}`);
await patient.getByRole('button', { name: /Tap to start/ }).waitFor();
await shot(patient, 'patient-phone-start', false);
await patient.getByRole('button', { name: /Tap to start/ }).click();

let spokeMessage = false;
for (let i = 0; i < 16; i += 1) {
  let s = await snap(sid);
  if (s.state === 'DONE' && s.messages.some((m) => m.status === 'confirmed')) break;
  if (s.state === 'SPEAKING' && s.prompt?.kind === 'message') {
    await patient.getByText('I want to see my daughter, Aisyah.').first().waitFor();
    await shot(patient, 'patient-phone-message', false);
    await shot(page, 'caregiver-laptop-speaking');
    spokeMessage = true;
    // The patient screen sends `spoken` after speaking (or a reading delay with no voice).
    const t0 = Date.now();
    while ((await snap(sid)).state === 'SPEAKING') {
      if (Date.now() - t0 > 15000) throw new Error('message was never marked spoken');
      await sleep(250);
    }
    continue;
  }
  if (!s.prompt) {
    await sleep(300);
    continue;
  }
  s = await waitListening(sid, s.prompt.id);
  if (!s.prompt) continue;
  const key = oracle(s, 'see_person:aisyah');
  log(`Q: ${s.prompt.text} -> ${key}`);
  await patient.getByRole('heading', { name: s.prompt.text }).waitFor();
  if (i === 1) {
    await shot(patient, 'patient-phone-listening', false);
    await shot(page, 'caregiver-laptop-listening');
  }
  if (s.prompt.kind === 'confirm') {
    await sleep(500);
    await shot(patient, 'patient-phone-confirm', false);
    await patient.setViewportSize({ width: 844, height: 390 });
    await sleep(300);
    await shot(patient, 'patient-phone-landscape-confirm', false);
    await patient.setViewportSize(PHONE);
  }
  if (i === 1) {
    // The caregiver answers this one: the trail must carry an override badge.
    await page.getByRole('button', { name: key === 'y' ? 'YES' : 'NO', exact: true }).click();
  } else {
    await patient.keyboard.press(key);
  }
  const t0 = Date.now();
  while ((await snap(sid)).prompt?.id === s.prompt.id) {
    if (Date.now() - t0 > 8000) throw new Error('answer not accepted');
    await sleep(150);
  }
}
const done = await snap(sid);
if (
  !spokeMessage ||
  !done.messages.some((m) => m.status === 'confirmed' && m.text_en.includes('Aisyah'))
) {
  throw new Error(`daughter message not confirmed: state=${done.state}`);
}
log('daughter message spoken and post-checked; questions', done.messages[0].questions);
await patient.getByText("I'm listening when you're ready.").waitFor();
await shot(patient, 'patient-phone-done', false);

// Caregiver shows bars, chips and the trail.
await page.getByText('Message from patient (confirmed)').first().waitFor();
await page.getByRole('heading', { name: 'Question trail' }).waitFor();
await page.getByText('Override', { exact: true }).first().waitFor();
log('override badge shown for the caregiver-entered answer');
const chip = page.getByRole('button', { name: /^T1/ }).first();
if (await chip.count()) {
  await chip.click();
  await page.getByText('Nurse: Your daughter Aisyah went home to rest').first().waitFor();
}
await shot(page, 'caregiver-laptop-done');

// ------------------------------------------------------------------ emergency
await page.getByRole('button', { name: 'New message' }).click();
await sleep(800);
await patient.keyboard.press('e');
await page.getByRole('alert').filter({ hasText: 'The patient needs help now.' }).waitFor();
await patient.getByText('A caregiver is coming now.').waitFor();
await shot(page, 'caregiver-laptop-emergency', false);
await shot(patient, 'patient-phone-emergency', false);
await page.getByRole('button', { name: /Acknowledge, I'm going/ }).click();
await page
  .getByRole('alert')
  .filter({ hasText: 'The patient needs help now.' })
  .waitFor({ state: 'detached' });
const afterAck = await snap(sid);
log('emergency acknowledged, state', afterAck.state);
await patient.getByText('Paused').first().waitFor();
await shot(patient, 'patient-phone-paused', false);

// Caregiver at phone width.
const cgPhone = await phone.newPage();
await cgPhone.goto(`${BASE}/caregiver/${sid}`);
await cgPhone.getByRole('heading', { name: 'Likely messages' }).waitFor();
await shot(cgPhone, 'caregiver-phone');
await cgPhone.close();

// ------------------------------------------------------------------ spelling
const sp = await (
  await api.post(`${BASE}/api/scenarios/spelling`, { data: { simulated: false } })
).json();
const spSid = sp.session_id;
log('spelling session', spSid);
const spPatient = await phone.newPage();
await spPatient.goto(`${BASE}/patient/${spSid}`);
await spPatient.getByRole('button', { name: /Ketuk untuk mulai/ }).click();
const spCare = await laptop.newPage();
await spCare.goto(`${BASE}/caregiver/${spSid}`);
let letters = 0;
for (let i = 0; i < 30 && letters < 5; i += 1) {
  let s = await snap(spSid);
  if (!s.prompt) {
    await sleep(300);
    continue;
  }
  s = await waitListening(spSid, s.prompt.id);
  if (!s.prompt) continue;
  const key = oracle(s, '__none__', 'KUCING');
  if (s.prompt.kind === 'spelling') {
    letters += 1;
    if (letters === 1) {
      await spPatient.getByRole('group', { name: /Huruf/ }).waitFor();
      await shot(spPatient, 'patient-phone-spelling', false);
    }
  }
  log(`Q: ${s.prompt.text} -> ${key}`);
  await spPatient.keyboard.press(key);
  const t0 = Date.now();
  while ((await snap(spSid)).prompt?.id === s.prompt.id) {
    if (Date.now() - t0 > 8000) throw new Error('spelling answer not accepted');
    await sleep(150);
  }
}
await spPatient.getByRole('group', { name: /Huruf/ }).waitFor();
await shot(spPatient, 'patient-phone-spelling-progress', false);
await spCare.getByRole('heading', { name: 'Question trail' }).waitFor();
await shot(spCare, 'caregiver-laptop-spelling');
const spLaptop = await laptop.newPage();
await spLaptop.goto(`${BASE}/patient/${spSid}`);
await spLaptop.getByRole('button', { name: /Ketuk untuk mulai/ }).click();
await spLaptop.getByRole('group', { name: /Huruf/ }).waitFor();
await shot(spLaptop, 'patient-laptop-spelling', false);

const pid = done.patient.id;

// ------------------------------------------------------------------ other routes
await api.post(`${BASE}/api/memory/${pid}`, {
  data: { text: 'Likes the blinds half open', category: 'preference' },
});
await api.post(`${BASE}/api/sessions/${sid}/transcript`, {
  data: { speaker: 'Nurse', text: 'He always likes the radio on in the morning.' },
});
await api.post(`${BASE}/api/memory/${pid}/curate`, { data: {} });

const routes = [
  ['landing', '/'],
  ['setup', '/setup'],
  ['calibrate', `/calibrate/${pid}`],
  ['patient-waiting', `/patient/${sid}`],
  ['caregiver', `/caregiver/${sid}`],
  ['memory', `/memory/${pid}`],
  ['eval', '/eval'],
  ['settings', '/settings'],
  ['notfound', '/nope'],
];
const tablet = await browser.newContext({ ...ctxOpts, viewport: { width: 1024, height: 768 } });
{
  const p = await tablet.newPage();
  for (const [name, path] of [
    ['caregiver', `/caregiver/${sid}`],
    ['patient-waiting', `/patient/${sid}`],
  ]) {
    await p.goto(`${BASE}${path}`);
    await p.getByRole('heading').first().waitFor();
    await sleep(700);
    await shot(p, `${name}-tablet`);
  }
  await tablet.close();
}
for (const [ctxName, ctx] of [
  ['phone', phone],
  ['laptop', laptop],
]) {
  const p = await ctx.newPage();
  for (const [name, path] of routes) {
    await p.goto(`${BASE}${path}`);
    await p
      .getByRole('heading')
      .first()
      .waitFor()
      .catch(() => undefined);
    await sleep(name === 'landing' ? 5200 : 700);
    await shot(p, `${name}-${ctxName}`);
  }
  await p.close();
}

// ------------------------------------------------------------------ sensitive message
// A simulated patient spells a sensitive word: it must be held for in-person verification.
const sens = await (
  await api.post(`${BASE}/api/sessions`, {
    data: { patient_id: pid, simulated_patient: 'spell:DNR', simulated_noise: 0 },
  })
).json();
const sensPage = await laptop.newPage();
await sensPage.goto(`${BASE}/caregiver/${sens.session_id}`);
await sensPage.getByRole('button', { name: 'Start without the phone' }).click();
{
  const t0 = Date.now();
  let s = await snap(sens.session_id);
  while (s.caregiver_reason !== 'sensitive_verify') {
    if (Date.now() - t0 > 150000) throw new Error(`no sensitive hold; state ${s.state}`);
    await sleep(1000);
    s = await snap(sens.session_id);
  }
}
await sensPage.getByText('Verify in person with the patient').first().waitFor();
await shot(sensPage, 'caregiver-laptop-sensitive', false);
await sensPage.getByRole('button', { name: 'Acknowledge without speaking' }).click();
await sensPage
  .getByText('Verify in person with the patient')
  .first()
  .waitFor({ state: 'detached' });
log('sensitive message held, then acknowledged without speaking');
await sensPage.close();

// Calibration: fake camera, framing check.
const cal = await laptop.newPage();
await cal.goto(`${BASE}/calibrate/${pid}`);
await cal.getByRole('button', { name: 'Turn on the camera' }).click();
await cal.getByRole('button', { name: 'Check framing' }).click();
await cal.getByText('Face visible').waitFor();
await shot(cal, 'calibrate-framing-laptop');
await cal.getByRole('button', { name: 'Continue' }).click();
await shot(cal, 'calibrate-record-laptop');
// Record every example with the fake camera: rest 15 s, YES x3, NO x3, emergency x1.
for (let n = 0; n < 8; n += 1) {
  await cal.getByRole('button', { name: /^Record \d+ seconds$/ }).click();
  await cal
    .getByRole('button', { name: /^Record \d+ seconds$|^Continue$/ })
    .waitFor({ timeout: 40000 });
}
await cal.getByText('All examples are recorded').waitFor();
await cal.getByRole('button', { name: 'Continue' }).click();
await cal.getByRole('combobox').selectOption('eyebrows');
await cal.getByRole('button', { name: 'Analyse examples' }).click();
await cal.getByText('Accuracy per source').waitFor({ timeout: 120000 });
await shot(cal, 'calibrate-results-laptop');
log('calibration finalized from recorded clips');
await cal.close();

// Skip path: new patient through setup, skip calibration, land on the caregiver screen.
const sk = await laptop.newPage();
await sk.goto(`${BASE}/setup`);
await sk.getByLabel('Display name').fill('Ibu Rina (fictional)');
await sk.getByLabel('Language spoken to the patient').selectOption('id');
await sk.getByLabel('Honorific').selectOption('Ibu');
await sk.getByRole('checkbox').check();
await sk.getByRole('button', { name: 'Save patient' }).click();
await sk.getByRole('button', { name: 'Skip and start a session' }).click();
await sk.waitForURL(/\/caregiver\/ses_/);
await sk.getByRole('heading', { name: 'Ibu Rina (fictional)' }).waitFor();
log('setup -> skip calibration -> caregiver OK');
await sk.close();

// Setup validation (consent required).
const setup = await phone.newPage();
await setup.goto(`${BASE}/setup`);
await setup.getByRole('button', { name: 'Save patient' }).click();
await setup.getByText('Tick the box to confirm').waitFor();
await shot(setup, 'setup-errors-phone');
await setup.close();

await browser.close();
if (errors.length) {
  log('page errors:');
  for (const e of errors) log('  ', e);
}
log('OK');
