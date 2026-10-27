// Builds the demo film (docs/DEMO_SCRIPT.md): cuts the footage into assets/, writes index.html
// for HyperFrames, and mixes the soundtrack into assets/mix.wav.
//   node build.mjs            then   npm run check && npm run render
//   node build.mjs --force    to cut every piece again
import { readFileSync, writeFileSync } from 'node:fs';
import { ASSETS, MEDIA, cut, groups, here, mix, seconds, take } from './lib.mjs';

const TOTAL = 180;
const X = 0.6; // scene crossfade
const gen = (n) => `${MEDIA}gen/${n}`;
const audio = (n) => `${MEDIA}audio/${n}`;
const cues = JSON.parse(readFileSync(here('../cues.json'), 'utf8'));
const words = JSON.parse(readFileSync(audio('captions.json'), 'utf8'));
const dur = Object.fromEntries(
  [...cues.narration, ...cues.phone].map((c) => [c.id, seconds(audio(`${c.id}.mp3`))]),
);

const cal = take('calibrate');
const ses = take('session');
const spl = take(process.env.SPELLING ?? 'spelling');

// ---------------------------------------------------------------- where everything lands
const NARRATION = { N1: 0.7, N2: 15.5, N3: 32.9, N4: 74.4, N5: 98.4, N6: 120.6, N7: 131.9, N8: 141.4, N9: 164.2 };
const S = {
  hook: 0,
  title: 5.8,
  clamp: 15.2,
  cal: 19.8,
  session: 29.6,
  night: 74.0,
  station: 80.2,
  nurse: 90.0,
  ack: 91.6,
  relay: 97.6,
  aisyah: 102.0,
  reply: 107.4,
  spell: 120.4,
  alarm: 131.6,
  stack: 141.0,
  close: 163.6,
  end: 170.4,
};
// session footage: seconds into the recordings (both pages share one clock)
const t = (test, nth) => ses.at('phone', test, nth);
const prompt = (text) => t((e) => e.what === 'prompt' && e.text?.startsWith(text));
const replyAt = t('reply read');
const PHONE_LINES = {
  P0: S.session + 0.7,
  P3: 59.6,
  P4: 65.0,
  P6: 69.9,
  P7: 94.6,
  P8: 114.0,
};

// ---------------------------------------------------------------- footage pieces
const pieces = [];
/** One app shot: the same window of console and phone footage, cut alike. */
function appShot(id, rec, from, at, length, opts = {}) {
  const c = cut(`${id}-console`, rec.file('console'), from, length + X, opts);
  const p = rec.file('phone') ? cut(`${id}-phone`, rec.file('phone'), from, length + X, opts) : null;
  pieces.push({ id, at, length, console: c, phone: p, ...opts });
  return { id, at, length, console: c, phone: p, ...opts };
}

const session = [
  appShot('s1', ses, prompt('Is it about your body') - 0.7, S.session, 3.4),
  appShot('s2', ses, prompt('Is it about your body') + 2.7, 33.0, 6.5),
  appShot('s3', ses, prompt('Is it about your body') + 9.2, 39.5, 19.7, { speed: 1.6 }),
  appShot('s4', ses, prompt('Is this your message') - 0.2, 59.2, 5.4),
  appShot('s5', ses, prompt('I want to see my daughter') - 0.4, 64.6, 4.8),
  appShot('s6', ses, prompt('Shall I send') - 0.4, 69.4, 4.6),
];
const station = [
  appShot('c1', ses, t('relay offered') - 0.1, S.station, 5.0),
  appShot('c2', ses, t('repeated') - 1.4, 85.2, 4.8),
];
// the console shows the press about 1.6 s after the harness logged the click
const ack = appShot('a1', ses, t("I'm coming") + 0.3, S.ack, S.relay - S.ack);
const relay = appShot('r1', ses, t('send approved') + 1.0, S.relay, S.aisyah - S.relay, { speed: 2.5 });
// the reply is read at PHONE_LINES.P8; hold the last frame rather than show the next message
// the screen shows the reply about 1.6 s after the harness logged it
const replyFrom = replyAt + 1.6 - (PHONE_LINES.P8 - S.reply);
const reply = appShot('r2', ses, replyFrom, S.reply, S.spell - S.reply, {
  vf: [`tpad=stop_mode=clone:stop_duration=6`],
  until: t('new message') - 0.3,
});
const listenEmergency = t('emergency queued') + 5.8;
const alarm1 = appShot('e1', ses, listenEmergency - 0.4, S.alarm, 4.0);
// measured on the recordings: the phone starts listening 6.0 s after the harness queued the
// signal, and the red banner shows 1.4 s after the harness saw the alarm
const alarmAt = t('alarm') + 1.4;
const alarm2 = appShot('e2', ses, alarmAt - 0.4, 135.6, S.stack - 135.6, {
  vf: [`tpad=stop_mode=clone:stop_duration=3`],
});

const spellStart = 1.4;
const spellEnd = spl.at('phone', 'message confirmed');
const spellSpeed = (spellEnd - spellStart) / (S.alarm - S.spell - 0.6);
const spelling = appShot('sp', spl, spellStart, S.spell, S.alarm - S.spell, {
  speed: spellSpeed,
  vf: [`tpad=stop_mode=clone:stop_duration=3`],
});

const calShots = [
  { id: 'k1', from: cal.at('calibrate', 'picked eyebrows') - 1.1, at: S.cal, length: 3.4 },
  { id: 'k2', from: cal.at('calibrate', (e) => e.what === 'record' && e.label === 'yes') + 2.4, at: 23.2, length: 3.6 },
  { id: 'k3', from: cal.at('calibrate', 'results') + 4.3, at: 26.8, length: S.session - 26.8 },
].map((k) => ({
  ...k,
  file: cut(k.id, cal.file('calibrate'), k.from, k.length + X, { vf: ['tpad=stop_mode=clone:stop_duration=3'] }),
}));

const story = {
  g1: cut('g1', gen('G1_hook.mp4'), 0, S.title - S.hook + X),
  g2: cut('g2', gen('G2_clamp.mp4'), 0.2, S.cal - S.clamp + X),
  g5: cut('g5', gen('G5_station.mp4'), 1.6, S.ack - S.nurse + X),
  g6: cut('g6', gen('G6_aisyah_home.mp4'), 0.2, S.reply - S.aisyah + X),
  g8: cut('g8', gen('G8_bedside.mp4'), 0, S.end - S.close + X, { speed: 0.9 }),
};
// what the phone's camera saw: the same generated clips the harness fed it
const CLIPS = `${here('../../data/labeled_generated/')}`;
const cam = {
  no: cut('cam-no', `${CLIPS}no/no_eval_0.mp4`, 0, 4.0),
  yes: cut('cam-yes', `${CLIPS}yes/yes_eval_2.mp4`, 0, 4.0),
  emergency: cut('cam-emergency', `${CLIPS}emergency/emergency_eval_0.mp4`, 0, 4.0),
};
for (const still of ['still_hero.png', 'still_night.png']) {
  writeFileSync(ASSETS + still, readFileSync(gen(still)));
}

// ---------------------------------------------------------------- html
const html = [];
const gsap = [];
let n = 0;
const id = (p) => `${p}${n++}`;
const f = (x) => Number(x.toFixed(3));

function video(src, start, length, cls = 'full', extra = '') {
  return `<video id="${id('v')}" class="clip ${cls}" data-start="${f(start)}" data-duration="${f(length)}" data-track-index="${n % 7}" src="assets/${src}" muted playsinline ${extra}></video>`;
}
function img(src, start, length, cls = 'full') {
  return `<img id="${id('i')}" class="clip ${cls}" data-start="${f(start)}" data-duration="${f(length)}" data-track-index="${n % 7}" src="assets/${src}" alt="" />`;
}
function div(start, length, cls, inner, style = '') {
  return `<div id="${id('d')}" class="clip ${cls}" data-start="${f(start)}" data-duration="${f(length)}" data-track-index="${n % 7}" style="${style}">${inner}</div>`;
}

const scenes = [];
function scene(name, start, end, body, { ground = false, cutIn = false } = {}) {
  scenes.push({ name, start, end, cutIn });
  const first = scenes.length === 1 ? ' style="opacity:1"' : '';
  html.push(`<div class="scene${ground ? ' ground' : ''}" id="sc-${name}"${first}>${body}</div>`);
}

/** A sub-shot layer inside a frame, faded in over `fade` seconds at its start. */
function layer(name, at, fade, inner) {
  gsap.push(`tl.set('#${name}', { opacity: 0 }, 0);`);
  gsap.push(`tl.fromTo('#${name}', { opacity: 0 }, { opacity: 1, duration: ${fade || 0.001}, ease: 'power1.inOut' }, ${f(at)});`);
  return `<div class="wrap" id="${name}">${inner}</div>`;
}

// split layout: console window left, phone right
const CON = { x: 70, y: 74, w: 1200, h: 852 };
const PH = { x: 1404, y: 74 };
const conScale = CON.w / 1280;

function split(shots, { pans = [], camShots = [], notes = [], tagLeft = 'Caregiver console', tagRight = 'Patient phone' } = {}) {
  const panId = id('pan');
  const conLayers = shots
    .map((s, i) => layer(`cl-${s.id}`, s.at, i ? s.fade ?? 0.25 : 0, video(s.console, s.at, s.length + X, '', 'style="width:100%"')))
    .join('');
  const phLayers = shots
    .map((s, i) => layer(`pl-${s.id}`, s.at, i ? s.fade ?? 0.25 : 0, video(s.phone, s.at, s.length + X, '', 'style="width:100%;height:100%"')))
    .join('');
  const view = (p) => {
    const s = p.s ?? 1;
    return `x: ${f(-(p.x0 ?? 0) * conScale * s)}, y: ${f(-(p.y0 ?? 0) * conScale * s)}, scale: ${s}`;
  };
  pans.forEach((p, i) => {
    if (i === 0) gsap.push(`tl.set('#${panId}', { ${view(p)} }, ${f(shots[0].at - 0.01)});`);
    else gsap.push(`tl.to('#${panId}', { ${view(p)}, duration: ${p.d ?? 1.2}, ease: 'power2.inOut' }, ${f(p.at)});`);
  });
  const camHtml = camShots
    .map((c) => {
      const box = id('cam');
      gsap.push(`tl.fromTo('#${box}', { opacity: 0, scale: 0.92 }, { opacity: 1, scale: 1, duration: 0.35, ease: 'back.out(1.6)' }, ${f(c.at)});`);
      gsap.push(`tl.to('#${box}', { opacity: 0, duration: 0.25, ease: 'power2.in' }, ${f(c.at + c.length - 0.25)});`);
      return `<div class="cam" id="${box}" style="left:1094px;top:668px;width:300px;height:225px;opacity:0">${video(c.src, c.at, c.length, '', '')}<span class="lab">${c.label ?? 'Phone camera'}</span></div>`;
    })
    .join('');
  const noteHtml = notes
    .map((nt) => div(nt.at, nt.length, 'note', nt.text, `right:${1920 - CON.x - CON.w}px;top:20px`))
    .join('');
  return `
    <span class="tag" style="left:${CON.x}px;top:32px">${tagLeft}</span>
    <span class="tag" style="left:${PH.x + 6}px;top:32px">${tagRight}</span>
    <div class="window" style="left:${CON.x}px;top:${CON.y}px;width:${CON.w}px;height:${CON.h}px">
      <div class="pan" id="${panId}" style="width:${CON.w}px">${conLayers}</div>
    </div>
    <div class="phone" style="left:${PH.x}px;top:${PH.y}px">
      <div class="screen" style="width:${390 * 0.98}px;height:${844 * 0.98}px">${phLayers}</div>
    </div>
    ${camHtml}${noteHtml}`;
}

// 1. hook
scene(
  'hook',
  S.hook,
  S.title,
  `<div class="wrap" id="kb-g1">${video(story.g1, S.hook, S.title - S.hook + X)}</div>
   ${div(0.3, S.title - 0.3 + X, 'label', 'AI-generated fictional patient <i>· App footage recorded from the running app · Not a medical device</i>')}`,
);
gsap.push(`tl.fromTo('#kb-g1', { scale: 1 }, { scale: 1.05, duration: ${S.title + X}, ease: 'none' }, 0);`);

// 2. title over the bedside photo
scene(
  'title',
  S.title,
  S.clamp,
  `<div class="wrap" id="kb-hero">${img('still_hero.png', S.title, S.clamp - S.title + X)}</div>
   ${div(S.title, S.clamp - S.title + X, 'full', '', 'background:radial-gradient(1300px 1100px at 0% 55%, rgba(11,37,43,0.94) 35%, rgba(11,37,43,0) 75%)')}
   ${div(
     S.title,
     S.clamp - S.title + X,
     'full',
     `<div class="titleblock">
        <p class="kicker" id="tt-kick">A 2025 review of ICU communication</p>
        <p class="stat" id="tt-stat">Only about <b>5%</b> of the messages ventilated patients try to convey are correctly understood by healthcare providers.</p>
        <p class="source" id="tt-src">Çelebi and Öztepe Yeşilyurt, Cyprus J Med Sci 2025</p>
        <span class="rule" id="tt-rule"></span>
        <h1 id="tt-title">Ventriloquist</h1>
        <p class="tagline" id="tt-tag">The patient does the talking. The phone just moves its lips.</p>
      </div>`,
   )}`,
);
gsap.push(`tl.fromTo('#kb-hero', { scale: 1.12, x: 50 }, { scale: 1, x: 0, duration: ${S.clamp - S.title + X}, ease: 'sine.out' }, ${S.title});`);
gsap.push(`tl.fromTo('#tt-kick', { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.5, ease: 'power3.out' }, ${S.title + 0.3});`);
gsap.push(`tl.fromTo('#tt-stat', { opacity: 0, y: 22 }, { opacity: 1, y: 0, duration: 0.7, ease: 'power2.out' }, ${S.title + 0.5});`);
gsap.push(`tl.fromTo('#tt-src', { opacity: 0 }, { opacity: 1, duration: 0.5, ease: 'sine.out' }, ${S.title + 1.0});`);
gsap.push(`tl.fromTo('#tt-rule', { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: 'expo.out' }, ${S.title + 2.3});`);
gsap.push(`tl.fromTo('#tt-title', { opacity: 0, y: 30, scale: 1.04 }, { opacity: 1, y: 0, scale: 1, duration: 1.1, ease: 'expo.out', transformOrigin: '0% 50%' }, ${S.title + 2.4});`);
gsap.push(`tl.fromTo('#tt-tag', { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }, ${S.title + 3.6});`);

// 3. the nurse clamps the phone
scene('clamp', S.clamp, S.cal, `<div class="wrap" id="kb-g2">${video(story.g2, S.clamp, S.cal - S.clamp + X)}</div>`);
gsap.push(`tl.fromTo('#kb-g2', { scale: 1.03 }, { scale: 1, duration: ${S.cal - S.clamp + X}, ease: 'sine.out' }, ${S.clamp});`);

// 4. calibration on the laptop
{
  const W = { x: 256, y: 64, w: 1408, h: 880 };
  const layers = calShots
    .map((k, i) => layer(`cal-${k.id}`, k.at, i ? 0.3 : 0, video(k.file, k.at, k.length + X, '', 'style="width:100%"')))
    .join('');
  scene(
    'cal',
    S.cal,
    S.session,
    `<span class="tag" style="left:${W.x}px;top:22px">Calibration · <b>live</b> on Muse Spark and SAM 3.1</span>
     <div class="window" style="left:${W.x}px;top:${W.y}px;width:${W.w}px;height:${W.h}px"><div class="pan" style="width:${W.w}px">${layers}</div></div>`,
    { ground: true },
  );
}

// 5. the session, live: questions, answers from the camera, the message, the relay offer
{
  const camAt = S.session + 3.4 + 0.3; // the first answer window (NO, eyes squeezed)
  scene(
    'session',
    S.session,
    S.night,
    split(session, {
      pans: [
        { at: S.session },
        { at: 35.4, y0: 680, d: 1.6 }, // likely messages and their evidence chips
        { at: 47.6, x0: 366, y0: 900, s: 1.4, d: 1.4 }, // the latest clip (SAM boxes), model calls
        { at: 58.6, d: 0.9 },
      ],
      camShots: [{ src: cam.no, at: camAt, length: 4.0 }],
      notes: [
        { at: S.session, length: 9.9, text: '<b>Live</b> · every answer read from the camera' },
        { at: 39.5, length: 19.7, text: 'Sped up <b>1.6×</b>' },
      ],
    }),
    { ground: true },
  );
}

// 6. night: the room is empty
scene(
  'night',
  S.night,
  S.station,
  `<div class="wrap" id="kb-night">${img('still_night.png', S.night, S.station - S.night + X)}</div>`,
);
gsap.push(`tl.fromTo('#kb-night', { scale: 1.0, x: 0 }, { scale: 1.08, x: -30, duration: ${S.station - S.night + X}, ease: 'none' }, ${S.night});`);

// 7. the nurses' station: the message waits, and is said again a minute later
scene(
  'station',
  S.station,
  S.nurse,
  split(station, {
    tagLeft: "Console at the nurses' station",
    pans: [{ at: S.station }],
    notes: [{ at: 85.2, length: 4.8 + X, text: '<b>1 minute</b> later' }],
  }),
  { ground: true },
);

// 8. the nurse looks up
scene('nurse', S.nurse, S.ack, `<div class="wrap" id="kb-g5">${video(story.g5, S.nurse, S.ack - S.nurse + X)}</div>`);
gsap.push(`tl.fromTo('#kb-g5', { scale: 1 }, { scale: 1.04, duration: ${S.ack - S.nurse + X}, ease: 'none' }, ${S.nurse});`);

// 9. "I'm coming", and the phone tells him
scene('ack', S.ack, S.relay, split([ack], { tagLeft: "Console at the nurses' station", pans: [{ at: S.ack }] }), { ground: true });

// 10. the agent sends it and watches for receipts
scene(
  'relay',
  S.relay,
  S.aisyah,
  split([relay], {
    pans: [{ at: S.relay }, { at: S.relay + 1.0, x0: 427, y0: 200, s: 1.5, d: 1.2 }],
    notes: [{ at: S.relay, length: S.aisyah - S.relay + X, text: 'Sped up <b>2.5×</b> · simulated relative' }],
  }),
  { ground: true },
);

// 11. Aisyah at home
scene('aisyah', S.aisyah, S.reply, `<div class="wrap" id="kb-g6">${video(story.g6, S.aisyah, S.reply - S.aisyah + X)}</div>`);
gsap.push(`tl.fromTo('#kb-g6', { scale: 1.04 }, { scale: 1, duration: ${S.reply - S.aisyah + X}, ease: 'sine.out' }, ${S.aisyah});`);

// 12. her reply, checked by Muse Spark, read aloud
scene(
  'reply',
  S.reply,
  S.spell,
  split([reply], {
    pans: [
      { at: S.reply, x0: 427, y0: 200, s: 1.5 },
      { at: S.reply + 0.05, x0: 480, y0: 236, s: 1.6, d: S.spell - S.reply },
    ],
  }),
  { ground: true },
);

// 13. spelling, simulated
scene(
  'spell',
  S.spell,
  S.alarm,
  split([spelling], {
    pans: [{ at: S.spell }],
    notes: [{ at: S.spell, length: S.alarm - S.spell + X, text: `Simulated answers · sped up <b>${Math.round(spellSpeed)}×</b>` }],
  }),
  { ground: true },
);

// 14. the emergency signal: a hard cut, because that's what it is
scene(
  'alarm',
  S.alarm,
  S.stack,
  split([alarm1, { ...alarm2, fade: 0 }], {
    pans: [{ at: S.alarm }],
    camShots: [{ src: cam.emergency, at: S.alarm + 0.6, length: 3.4, label: 'Phone camera: YES three times' }],
    notes: [{ at: 136.0, length: 3.4, text: 'Alarm <b>16 s</b> after the signal' }],
  }),
  { ground: true, cutIn: true },
);

// 15. the stack
scene(
  'stack',
  S.stack,
  S.close,
  `<div class="stack">
     <div class="col">
       <p class="kicker">Under the hood</p>
       <h2 id="st-h">Meta's models, each with one job</h2>
       <ul id="st-list">
         <li><b>Muse Spark</b><span>calibration, room reader, questions, blind answer judge, spelling, reply reader</span></li>
         <li><b>SAM 3.1</b><span>tracks the patient's own movement in every answer clip</span></li>
         <li><b>Muse Voice Transcribe</b><span>the room's conversation, in English and Indonesian</span></li>
         <li><b>Muse Wonder</b><span>a memory of the stay that a nurse approves fact by fact</span></li>
         <li><b>Muse Image</b><span>the 34 pictograms on the patient's screen</span></li>
         <li><b>WhatsApp Cloud API</b><span>the family relay</span></li>
       </ul>
     </div>
     <div class="col right">
       <div class="panel" id="st-p1"><p class="big">11 <i>of</i> 13</p><p>answers read on generated test clips of Mr Hasan</p><p class="small">0 wrong · 2 asked again</p></div>
       <div class="panel" id="st-p2"><p class="big">4.89 <i>vs</i> 6.41</p><p>questions per message, against a fixed-order board, at 10% answer noise</p><p class="small">Simulation, not clinical evidence</p></div>
     </div>
   </div>`.replace(/<div class="stack">/, `<div class="clip stack" id="st" data-start="${S.stack}" data-duration="${f(S.close - S.stack + X)}" data-track-index="3">`),
  { ground: true },
);
gsap.push(`tl.fromTo('#st .kicker', { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.5, ease: 'power3.out' }, ${S.stack + 0.3});`);
gsap.push(`tl.fromTo('#st-h', { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 0.8, ease: 'expo.out' }, ${S.stack + 0.45});`);
gsap.push(`tl.fromTo('#st-list li', { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.55, ease: 'power2.out', stagger: 1.25 }, ${S.stack + 1.3});`);
gsap.push(`tl.fromTo('#st-p1', { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.7, ease: 'back.out(1.4)' }, ${S.stack + 13.4});`);
gsap.push(`tl.fromTo('#st-p2', { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.7, ease: 'back.out(1.4)' }, ${S.stack + 16.0});`);

gsap.push(`tl.fromTo('#st', { y: 10 }, { y: -14, duration: ${S.close - S.stack + X}, ease: 'sine.inOut' }, ${S.stack});`);

// 16. four o'clock: Aisyah at the bedside
scene('close', S.close, S.end, `<div class="wrap" id="kb-g8">${video(story.g8, S.close, S.end - S.close + X)}</div>`);
gsap.push(`tl.fromTo('#kb-g8', { scale: 1 }, { scale: 1.05, duration: ${S.end - S.close + X}, ease: 'none' }, ${S.close});`);

// 17. end card
scene(
  'end',
  S.end,
  TOTAL,
  `${div(
    S.end,
    TOTAL - S.end,
    'full endcard',
    `<span class="rule" id="ec-rule"></span>
     <h1 id="ec-title">Ventriloquist</h1>
     <p class="tagline" id="ec-tag">The patient does the talking. The phone just moves its lips.</p>
     <div class="links" id="ec-links"><p><i>Try it</i> ventriloquist.fly.dev</p><p><i>Code</i> github.com/0xNoramiya/ventriloquist</p></div>
     <p class="fine" id="ec-fine">AI-generated fictional patient · App footage recorded from the running app · Not a medical device</p>`,
  )}`,
  { ground: true },
);
gsap.push(`tl.fromTo('.endcard', { y: 8, scale: 1 }, { y: -10, scale: 1.015, duration: ${TOTAL - S.end}, ease: 'sine.inOut', transformOrigin: '20% 50%' }, ${S.end});`);
gsap.push(`tl.fromTo('#ec-rule', { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: 'expo.out' }, ${S.end + 0.3});`);
gsap.push(`tl.fromTo('#ec-title', { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 1.0, ease: 'expo.out' }, ${S.end + 0.35});`);
gsap.push(`tl.fromTo('#ec-tag', { opacity: 0 }, { opacity: 1, duration: 0.8, ease: 'sine.out' }, ${S.end + 1.2});`);
gsap.push(`tl.fromTo('#ec-links p', { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.6, ease: 'power3.out', stagger: 0.3 }, ${S.end + 2.6});`);
gsap.push(`tl.fromTo('#ec-fine', { opacity: 0 }, { opacity: 1, duration: 0.6, ease: 'sine.out' }, ${S.end + 3.4});`);

// scene visibility and transitions
scenes.forEach((s, i) => {
  const el = `#sc-${s.name}`;
  if (i === 0) {
    gsap.push(`tl.set('${el}', { opacity: 1 }, 0);`);
  } else if (s.cutIn) {
    gsap.push(`tl.set('${el}', { opacity: 1 }, ${f(s.start)});`);
  } else {
    gsap.push(`tl.fromTo('${el}', { opacity: 0, filter: 'blur(14px)', scale: 0.985 }, { opacity: 1, filter: 'blur(0px)', scale: 1, duration: ${X}, ease: 'sine.inOut' }, ${f(s.start)});`);
  }
  const next = scenes[i + 1];
  if (next) {
    if (next.cutIn) gsap.push(`tl.set('${el}', { opacity: 0 }, ${f(next.start)});`);
    else gsap.push(`tl.to('${el}', { opacity: 0, filter: 'blur(14px)', duration: ${X}, ease: 'sine.inOut' }, ${f(next.start)});`);
    gsap.push(`tl.set('${el}', { opacity: 0, visibility: 'hidden' }, ${f(next.start + X)});`);
  }
});
gsap.push(`tl.to('#root', { opacity: 0, duration: 0.9, ease: 'power1.in' }, ${TOTAL - 0.9});`);

// captions: narration in phrases, the phone's lines whole
const caps = [];
for (const [cid, at] of Object.entries(NARRATION)) {
  for (const g of groups(words[cid], at)) caps.push({ ...g, phone: false });
}
for (const [cid, at] of Object.entries(PHONE_LINES)) {
  const text = cues.phone.find((p) => p.id === cid).text;
  caps.push({ text, start: at, end: at + dur[cid] + 0.2, phone: true });
}
caps.sort((a, b) => a.start - b.start);
caps.forEach((c, i) => {
  const next = caps[i + 1];
  const end = next ? Math.min(c.end, next.start - 0.02) : c.end;
  html.push(div(c.start, Math.max(0.3, end - c.start), `cap${c.phone ? ' phoneline' : ''}`, `<span>${c.text}</span>`, 'z-index:50'));
});

// soundtrack
const N = (cid) => ({ file: audio(`${cid}.mp3`), at: NARRATION[cid], gain: 1.0 });
const P = (cid) => ({ file: audio(`${cid}.mp3`), at: PHONE_LINES[cid], gain: 0.9 });
mix(ASSETS + 'mix.wav', TOTAL, {
  speech: [...Object.keys(NARRATION).map(N), ...Object.keys(PHONE_LINES).map(P)],
  effects: [
    { file: audio('icu_room_tone.mp3'), at: 0, dur: 16, fade: 1.5, gain: 0.28 },
    { file: audio('icu_room_tone.mp3'), at: 14.5, dur: 15.6, fade: 1.5, gain: 0.22 },
    { file: audio('clamp_click.mp3'), at: S.clamp + 1.4, gain: 0.6 },
    { file: audio('night_ward.mp3'), at: S.night, dur: 16.6, fade: 1.5, gain: 0.35 },
    { file: audio('app_chime.wav'), at: S.station + 0.4, gain: 0.8 },
    { file: audio('app_chime.wav'), at: 86.4, gain: 0.8 },
    { file: audio('phone_buzz.mp3'), at: S.aisyah + 0.4, gain: 0.7 },
    { file: audio('app_alarm.wav'), at: 136.0, gain: 0.75 },
    { file: audio('whoosh.mp3'), at: S.title - 0.2, gain: 0.35 },
    { file: audio('whoosh.mp3'), at: S.end - 0.2, gain: 0.35 },
  ],
  // the alarm should be heard over near silence
  music: { file: audio('score.mp3'), at: 0, gain: 0.42, dips: [[S.alarm, S.stack, 0.25]] },
});

const page = readFileSync(here('page.tpl'), 'utf8')
  .replace('{{TOTAL}}', String(TOTAL))
  .replace('{{BODY}}', html.join('\n'))
  .replace('{{TIMELINE}}', gsap.join('\n      '));
writeFileSync(here('index.html'), page);
console.log(`index.html: ${scenes.length} scenes, ${caps.length} captions, ${pieces.length} app shots`);
