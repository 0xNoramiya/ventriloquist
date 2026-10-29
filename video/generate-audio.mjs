// Narration, music and effects for the demo video, from cues.json (timeline in docs/DEMO_SCRIPT.md).
//   npm run audio                      everything that isn't made yet
//   npm run audio -- narration N3 sfx  only these parts or cue ids
//   npm run audio -- N3 --force        make it again (spends credits)
// The key comes from ../.env.local (ELEVENLABS_API_KEY), loaded by the npm script.
import { ElevenLabsClient } from '@elevenlabs/elevenlabs-js';
import { execFileSync } from 'node:child_process';
import { createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const cues = JSON.parse(readFileSync(here('cues.json'), 'utf8'));
const script = readFileSync(here('../docs/DEMO_SCRIPT.md'), 'utf8');
const outDir = here('media/audio/');
mkdirSync(outDir, { recursive: true });

const args = process.argv.slice(2);
const force = args.includes('--force');
const picks = args.filter((a) => a !== '--force');
const wanted = (part, id) => !picks.length || picks.includes(part) || picks.includes(id);

const client = new ElevenLabsClient();
const durations = {};

function seconds(file) {
  const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]);
  return Number(out.toString());
}

/** Writes <id>.mp3 from the request unless it exists, and records its length. */
async function make(id, request) {
  const file = `${outDir}${id}.mp3`;
  if (force || !existsSync(file)) {
    // every SDK call returns a web ReadableStream
    await pipeline(Readable.fromWeb(await request()), createWriteStream(file));
  }
  durations[id] = Number(seconds(file).toFixed(2));
  return durations[id];
}

const { voice, narration, phoneVoice, phone, music, sfx } = cues;
for (const [i, line] of narration.entries()) {
  if (!wanted('narration', line.id)) continue;
  if (!script.includes(line.text)) console.warn(`${line.id}: text differs from docs/DEMO_SCRIPT.md`);
  const s = await make(line.id, () =>
    client.textToSpeech.convert(voice.id, {
      text: line.say ?? line.text, // `say`: a spelling for the voice only, e.g. "Base-ten"
      modelId: voice.model,
      languageCode: 'en',
      voiceSettings: { stability: voice.stability, similarityBoost: voice.similarityBoost },
      // neighbouring lines as context, so the joins sound like one take
      previousText: narration[i - 1]?.text,
      nextText: narration[i + 1]?.text,
    }),
  );
  console.log(`${line.id} ${s.toFixed(1)} s of a ${line.slot} s slot${s > line.slot ? '  <- too long' : ''}`);
}

// the phone's lines, in a separate voice through a small-speaker filter
for (const line of phone) {
  if (!wanted('phone', line.id)) continue;
  const s = await make(line.id, () =>
    client.textToSpeech.convert(phoneVoice.id, {
      text: line.text,
      modelId: phoneVoice.model,
      languageCode: 'en',
      voiceSettings: { stability: phoneVoice.stability, similarityBoost: phoneVoice.similarityBoost },
      audioEffects: phoneVoice.effects,
    }),
  );
  console.log(`${line.id} ${s.toFixed(1)} s`);
}

if (wanted('music', music.id)) {
  const s = await make(music.id, () =>
    client.music.compose({
      // section text is performed (sung or spoken), so cues.json keeps it to "[Instrumental]"
      compositionPlan: { chunks: music.chunks },
      modelId: music.model,
      respectSectionsDurations: true, // force_instrumental is only accepted with a plain prompt
    }),
  );
  console.log(`${music.id} ${s.toFixed(1)} s`);
}

for (const fx of sfx) {
  if (!wanted('sfx', fx.id)) continue;
  const s = await make(fx.id, () =>
    client.textToSoundEffects.convert({ text: fx.text, durationSeconds: fx.seconds, loop: fx.loop ?? false }),
  );
  console.log(`${fx.id} ${s.toFixed(1)} s`);
}

// the HyperFrames composition reads the lengths from here
const manifest = here('media/audio/durations.json');
const previous = existsSync(manifest) ? JSON.parse(readFileSync(manifest, 'utf8')) : {};
writeFileSync(manifest, JSON.stringify({ ...previous, ...durations }, null, 2) + '\n');
