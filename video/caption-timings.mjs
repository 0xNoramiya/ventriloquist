// Word timings for the narration captions. ElevenLabs speech-to-text gives each spoken word's
// start and end; the caption text stays the script's (so "Aisyah", not the transcriber's "Aisha").
// Writes media/audio/captions.json: { N1: [{ text, start, end }], ... } in seconds from line start.
import { ElevenLabsClient } from '@elevenlabs/elevenlabs-js';
import { createReadStream, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const { narration } = JSON.parse(readFileSync(here('cues.json'), 'utf8'));
const client = new ElevenLabsClient();
const norm = (w) => w.toLowerCase().replace(/[^a-z0-9]/g, '');

const out = {};
for (const line of narration) {
  const res = await client.speechToText.convert({
    file: createReadStream(here(`media/audio/${line.id}.mp3`)),
    modelId: 'scribe_v2',
    timestampsGranularity: 'word',
  });
  const spoken = res.words.filter((w) => w.type === 'word');
  const script = line.text.split(/\s+/);
  // walk both lists; when a word was transcribed differently ("Hasan" as "Hassan"), it still
  // takes the next spoken word's timing, since the counts match word for word in practice
  const words = [];
  let j = 0;
  for (const text of script) {
    let k = j;
    while (k < spoken.length && norm(spoken[k].text) !== norm(text) && k - j < 3) k++;
    const hit = k < spoken.length && norm(spoken[k].text) === norm(text) ? k : j;
    const w = spoken[Math.min(hit, spoken.length - 1)];
    words.push({ text, start: w.start, end: w.end });
    j = Math.min(hit + 1, spoken.length - 1);
  }
  out[line.id] = words;
  console.log(line.id, script.length, 'script words,', spoken.length, 'spoken');
}
writeFileSync(here('media/audio/captions.json'), JSON.stringify(out, null, 1) + '\n');
