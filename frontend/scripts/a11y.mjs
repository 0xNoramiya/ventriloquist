// axe-core accessibility pass over every route and the main patient-screen states.
//   node scripts/a11y.mjs [baseUrl]
import { AxeBuilder } from '@axe-core/playwright';
import { chromium } from 'playwright';

const BASE = process.argv[2] ?? 'https://localhost:5173';
const browser = await chromium.launch();
const ctx = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 390, height: 844 },
});
const api = ctx.request;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let serious = 0;
async function audit(page, label) {
  const res = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const bad = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  serious += bad.length;
  console.log(
    `${label}: ${res.violations.length} violations (${bad.length} serious/critical), ${res.passes.length} passes`,
  );
  for (const v of res.violations) {
    console.log(`  [${v.impact}] ${v.id}: ${v.help}`);
    for (const n of v.nodes.slice(0, 3))
      console.log(`      ${n.target.join(' ')} ${n.failureSummary?.split('\n')[1] ?? ''}`);
  }
}

const s = await (
  await api.post(`${BASE}/api/scenarios/daughter`, { data: { simulated: false } })
).json();
const sid = s.session_id;
const pid = s.patient.id;
const page = await ctx.newPage();

await page.goto(`${BASE}/patient/${sid}`);
await page.getByRole('button', { name: /Tap to start/ }).waitFor();
await audit(page, 'patient: start gate');
await page.getByRole('button', { name: /Tap to start/ }).click();
await page.getByText('Your answer now').waitFor({ timeout: 15000 });
await audit(page, 'patient: listening');
for (const key of ['n', 'y', 'y', 'y']) {
  const before = (await (await api.get(`${BASE}/api/sessions/${sid}`)).json()).prompt?.id;
  await page.keyboard.press(key);
  for (let i = 0; i < 40; i += 1) {
    const now = (await (await api.get(`${BASE}/api/sessions/${sid}`)).json()).prompt?.id;
    if (now !== before) break;
    await sleep(150);
  }
}
await page.getByText('Message from patient (confirmed)').waitFor({ timeout: 15000 });
await sleep(600);
await audit(page, 'patient: message');

const sp = await (
  await api.post(`${BASE}/api/scenarios/spelling`, { data: { simulated: false } })
).json();
await api.post(`${BASE}/api/sessions/${sp.session_id}/start`);
await api.post(`${BASE}/api/sessions/${sp.session_id}/override`, { data: { action: 'spell' } });
await page.goto(`${BASE}/patient/${sp.session_id}`);
await page.getByRole('button', { name: /Ketuk untuk mulai/ }).click();
await page.getByRole('group', { name: /Huruf/ }).waitFor();
await sleep(600);
await audit(page, 'patient: spelling (id)');

for (const [label, path] of [
  ['landing', '/'],
  ['setup', '/setup'],
  ['calibrate', `/calibrate/${pid}`],
  ['caregiver', `/caregiver/${sid}`],
  ['memory', `/memory/${pid}`],
  ['eval', '/eval'],
  ['settings', '/settings'],
]) {
  await page.goto(`${BASE}${path}`);
  await page.getByRole('heading').first().waitFor();
  await sleep(label === 'landing' ? 5200 : 800);
  await audit(page, label);
}

await browser.close();
console.log(
  serious ? `FAIL: ${serious} serious/critical` : 'OK: no serious or critical violations',
);
process.exit(serious ? 1 : 0);
