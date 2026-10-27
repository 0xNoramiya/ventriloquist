// Helpers for build.mjs: cutting footage, reading the recording timelines, captions, the mix.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const here = (p) => fileURLToPath(new URL(p, import.meta.url));
export const MEDIA = here('../media/');
export const ASSETS = here('assets/');
mkdirSync(ASSETS, { recursive: true });

export const FORCE = process.argv.includes('--force');

export function seconds(file) {
  const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]);
  return Number(out.toString());
}

/**
 * A silent H.264 piece of a source clip: `from` seconds in, `dur` seconds of output, played at
 * `speed`. Returns the asset's file name. Existing pieces are kept unless --force.
 */
export function cut(id, src, from, dur, { speed = 1, vf = [], until } = {}) {
  const name = `${id}.mp4`;
  const out = ASSETS + name;
  if (FORCE || !existsSync(out)) {
    const filters = [`setpts=(PTS-STARTPTS)/${speed}`, ...vf, 'fps=30', 'format=yuv420p'];
    // `until`: stop reading the source there (a tpad in vf then holds the last frame)
    const read = Math.min(dur * speed + 0.1, until === undefined ? Infinity : until - from);
    execFileSync('ffmpeg', [
      '-y', '-v', 'error', '-ss', from.toFixed(3), '-t', read.toFixed(3), '-i', src,
      '-vf', filters.join(','), '-t', dur.toFixed(3), '-an',
      '-c:v', 'libx264', '-crf', '17', '-preset', 'medium', '-movflags', '+faststart', out,
    ]);
  }
  return name;
}

/** An app recording's timeline: `at(page, test)` is the seconds into that page's video. */
export function take(name) {
  const { clips, events } = JSON.parse(readFileSync(`${MEDIA}app/${name}/events.json`, 'utf8'));
  const start = Object.fromEntries(clips.map((c) => [c.name, c.start]));
  const file = (page) => `${MEDIA}app/${name}/${page}.mp4`;
  const find = (test, nth = 0) => {
    const hits = events.filter((e) => (typeof test === 'string' ? e.what === test : test(e)));
    if (!hits[nth]) throw new Error(`${name}: no event #${nth} for ${test}`);
    return hits[nth].t;
  };
  return { file, events, at: (page, test, nth = 0) => find(test, nth) - start[page] };
}

/**
 * Caption groups from word timings: up to `max` words, broken after sentence ends and at
 * pauses, so each group reads as a phrase.
 */
export function groups(words, offset, max = 6) {
  const out = [];
  let cur = [];
  const flush = () => {
    if (!cur.length) return;
    out.push({
      text: cur.map((w) => w.text).join(' '),
      start: offset + cur[0].start,
      end: offset + cur.at(-1).end,
    });
    cur = [];
  };
  words.forEach((w, i) => {
    cur.push(w);
    const next = words[i + 1];
    const pause = next ? next.start - w.end : 0;
    if (cur.length >= max || /[.?!:]$/.test(w.text) || pause > 0.35) flush();
  });
  flush();
  // hold each group until just before the next one, so captions don't flicker off between phrases
  out.forEach((g, i) => {
    const next = out[i + 1];
    g.end = next ? Math.min(next.start - 0.04, g.end + 0.6) : g.end + 0.5;
  });
  return out;
}

/**
 * The film's whole soundtrack as one WAV: every cue placed at its time and level, the music
 * ducked by a sidechain on everything spoken, then normalised to -16 LUFS.
 */
export function mix(out, total, { speech, effects, music }) {
  const inputs = [];
  const parts = [];
  const add = (cue, label) => {
    const i = inputs.length / 2; // ffmpeg's input index; each input adds '-i' and a path
    inputs.push('-i', cue.file);
    const ms = Math.round(cue.at * 1000);
    const trim = cue.dur ? `atrim=0:${cue.dur},` : '';
    const fade = cue.fade ? `afade=t=in:d=${cue.fade},afade=t=out:st=${(cue.dur ?? seconds(cue.file)) - cue.fade}:d=${cue.fade},` : '';
    parts.push(`[${i}:a]aresample=48000,aformat=channel_layouts=stereo,${trim}${fade}volume=${cue.gain ?? 1},adelay=${ms}|${ms}[${label}${i}]`);
    return `[${label}${i}]`;
  };
  const sp = speech.map((c) => add(c, 's'));
  const fx = effects.map((c) => add(c, 'f'));
  const mu = add(music, 'm');
  // music dips: [from, to, gain], ramped over 0.8 s at each end so the level change doesn't click
  const dips = (music.dips ?? [])
    .map(([a, b, g]) => `volume='1-${1 - g}*clip((t-${a})/0.8,0,1)*clip((${b}-t)/0.8,0,1)':eval=frame`)
    .join(',');
  const graph = [
    ...parts,
    `${sp.join('')}amix=inputs=${sp.length}:normalize=0,apad=whole_dur=${total}[speech]`,
    `[speech]asplit=2[sp1][key]`,
    `${mu}${dips ? dips + ',' : ''}apad=whole_dur=${total}[mus]`,
    `[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=60:release=450[ducked]`,
    `${fx.join('')}amix=inputs=${fx.length}:normalize=0,apad=whole_dur=${total}[fx]`,
    `[sp1][ducked][fx]amix=inputs=3:normalize=0,atrim=0:${total},loudnorm=I=-16:TP=-1.5:LRA=11[out]`,
  ];
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', ...inputs, '-filter_complex', graph.join(';'), '-map', '[out]',
    '-ar', '48000', '-c:a', 'pcm_s16le', out,
  ]);
}
