# Demo video script (3:00)

One fictional patient, Mr Hasan, from the moment the phone goes on the bed rail to his daughter's
reply. The story carries the four judging criteria: impact (an awake patient who is alone and
can't speak), Meta tooling (each model shows up doing its job on screen), technical depth (bounded
evidence, the blind judge, the eval numbers) and the demo itself. It also carries the agentic
bonus (the family relay).

Rules from the brief, kept:

- Show only features built during the hackathon.
- English captions throughout. Show the Indonesian toggle once (in the spelling beat).
- If an answer in the app footage came from a caregiver override, the override badge stays on
  screen. Better: retake until the camera reads every answer.

Rule changed: the brief planned a consenting actor. The patient, nurse and daughter are now
AI-generated fictional people (Higgsfield), so the label changes to match. On screen for the first
five seconds and again on the end card:

> AI-generated fictional patient. App footage recorded from the running app. Not a medical device.

## As built

The film is built and rendered by [`video/`](../video/README.md): narration and sound from
ElevenLabs, story scenes from Higgsfield, app footage from live takes on https://ventriloquist.fly.dev,
assembled with HyperFrames. Timings below are the plan; `video/edit/build.mjs` holds the exact cut.

## Three kinds of footage

| Tag | What it is | Made with |
|---|---|---|
| **GEN** | Story scenes: the bed, the empty room at night, the nurses' station, Aisyah on her phone | Higgsfield: GPT Image 2.5 start frames from the same Mr Hasan reference as the website photos, then Seedance 2.0 image-to-video |
| **APP** | Real screen recordings of the running app: caregiver console at 1440x900, patient phone at 390x844 | Playwright on https://ventriloquist.fly.dev in live mode. The camera feed is the generated Mr Hasan gesture clips (the same ones as the detector eval), so SAM 3.1 and the judge really read every answer |
| **CARD** | Title, captions, the model list, eval numbers | HyperFrames |

GEN never shows the app doing something it didn't do. Every probability bar, overlay, chime and
status change on screen comes from APP footage. Live questions take about 10 s end to end, so the
session beat is sped up and says so on screen.

## Timeline

Narration lines (N1 to N9) are what ElevenLabs reads. They also live in
[`video/cues.json`](../video/cues.json), which the audio script reads; keep the two the same. Words
in *italics* are the phone speaking. The app speaks with the device's built-in text-to-speech,
which a screen recording can't capture, so in the video an ElevenLabs voice through a small-speaker
filter stands in for it (lines P1 to P7 in `video/cues.json`).

| Time | Picture | Narration | Sound |
|---|---|---|---|
| 0:00-0:15 | **GEN** Mr Hasan in bed, tube taped at the mouth, lips moving without sound; a nurse leans in, unsure. **CARD** over the end of the shot: "A 2025 review reports that only about 5% of the messages ventilated patients try to convey are correctly understood by healthcare providers (Çelebi and Öztepe Yeşilyurt, Cyprus J Med Sci 2025)." Title: **Ventriloquist.** | **N1** Mr Hasan is awake, but a breathing tube means he can't say a word. So here, he is the ventriloquist. The phone only moves its lips, and it says nothing he hasn't confirmed. | Music: sparse piano. SFX: ICU room tone. |
| 0:15-0:30 | **GEN** the nurse clamps the phone to the bed rail. **APP** calibration: the signal picker, "Eyebrows up / Eyes squeezed shut" selected; the recording countdown; results: Muse Spark's description of each movement and the accuracy per source (Muse Spark, SAM 3.1, local motion). | **N2** A nurse clamps a phone to the bed rail, and Mr Hasan picks a movement he can still make. Eyebrows up means yes. Muse Spark names the movement, and SAM 3.1 learns to follow it. | SFX: clamp click. Music: soft pulse comes in. |
| 0:30-1:05 | **APP** console and phone side by side. Evidence chips light up: T1 (the nurse said Aisyah went home and will be back at four), S1 (family photo), E3 (visitor left). Phone: *"Is it about a person?"* **GEN** close-up, eyebrows rise. **APP** SAM overlay, bars move, judge verdict on the trail. *"Do you want to see Aisyah?"* yes (Muse Spark words the questions live, so the take's wording is what's on screen). *"Is this your message: I want to see my daughter, Aisyah?"* yes. The phone speaks: *"I want to see my daughter, Aisyah."* Then *"Did I say it right?"* yes. Notes on screen: "Live · every answer read from the camera" and, over the middle questions, "Sped up 1.6×" (live, a question takes about 12 s end to end). | **N3** First, Muse Spark reads the room: what the nurse just said, the family photo he keeps looking at, the visitor who left ten minutes ago. Each clue can only nudge the odds, and each one shows where it came from. Then the phone asks the one question that narrows things most. SAM 3.1 tracks his eyebrows, and a second, blind Muse Spark judge checks every answer. | Phone voice. Music: pulse builds a little. |
| 1:05-1:35 | Phone: *"Shall I send this to Aisyah on WhatsApp?"* **GEN** eyebrows rise. **GEN** the room at night: nobody there, only the phone lit on the rail. **APP** the console at the nurses' station: the yellow "The patient says" card with its chime, and the approval card "Send to Aisyah (daughter) on WhatsApp? The patient said yes." Caption "1 minute later": the phone repeats the message, "said 2 times" on the card. **GEN** a nurse at the station looks up. **APP** she taps "I'm coming", then Send (approving the relay also counts as seeing the message). Phone: *"A caregiver has seen your message and is coming."* | **N4** But the room is empty, and he can't press a call bell. So his words chime at the nurses' station and stay there until someone taps "I'm coming". If nobody does, the phone says them again and the alert gets louder. The WhatsApp message to Aisyah waits for a nurse's approval too. | Music thins to sustained strings. SFX: night ward hum; the app's own chime (rendered from the app, see Sound). |
| 1:35-2:00 | **APP** relay card: Sent, Delivered, Read. **GEN** Aisyah at home; her phone buzzes; she reads (screen not visible), exhales, types. **APP** reply arrives; the trail shows Muse Spark's reading: not about his health, safe to read aloud. Phone reads her reply. **GEN** Mr Hasan's face relaxes. Caption: "No reply? It asks him about his son next." | **N5** Now an agent takes over. It watches the message reach Aisyah's phone and get read. When she answers, Muse Spark reads the reply first. Anything about his health waits for a nurse. This one doesn't, so he hears it. | SFX: phone buzz. Phone voice. Music: warm, rising. |
| 2:00-2:15 | **APP** a second patient's spelling run in mock mode with the simulated patient, sped up and labelled "Simulated answers": *"Is this your message: I'm cold?"* no. *"Do you want to spell it?"* yes. Letter groups; K, U, C. The console flips EN to ID once: *"Apakah kata Bapak KUCING?"* yes. *"Who is feeding my cat?"* yes. Caption: "Simulated answers · sped up 13×". | **N6** Wrong guesses happen. He says no and spells it: three letters, and the completer finds "kucing", cat. The message: who is feeding my cat? | Music: light, playful. |
| 2:15-2:25 | **GEN** eyebrows up three times, fast. **APP** the console turns red: "The patient needs help now." A note gives the real delay: "Alarm 15 s after the signal". A nurse taps "Acknowledge, I'm going". | **N7** Three quick yeses, at any moment, raise the alarm on every screen. | Music cuts. The app's own alarm (rendered from the app). |
| 2:25-2:45 | **CARD** the models, one line each as they're named: Muse Spark (calibration, room reader, questions, blind judge, spelling, reply reader), SAM 3.1, Muse Voice Transcribe, Muse Wonder, Muse Image (pictograms), WhatsApp Cloud API. **APP** two seconds of the memory page: a proposed fact with its source, approved by a nurse. **CARD** "Generated test clips: 11 of 13 answers read, 0 wrong, 2 asked again." and the simulation chart from the README. | **N8** Under the hood it's Meta's stack: Muse Spark from calibration to the blind judge, SAM 3.1, Voice Transcribe, Muse Wonder for a memory nurses approve, and the WhatsApp Cloud API. On generated test clips it read eleven of thirteen answers, none wrong, and asked again on the other two. | Music: steady, clean pulse. |
| 2:45-3:00 | **GEN** four o'clock: Aisyah at the bedside, holding his hand; he raises his eyebrows. **CARD** end card: "Try it: ventriloquist.fly.dev", "github.com/0xNoramiya/ventriloquist", and the label. | **N9** Built in Indonesia, for patients who are awake and unheard. The patient does the talking. The phone just moves its lips. | Music: the piano theme returns and resolves. |

**Privacy mode.** Only if privacy mode has run live on Muse Spark Open before recording (needs
`BASETEN_API_KEY`), add to N8: "Privacy mode runs the same steps on Muse Spark Open, an open-weight
model." and show the "What leaves this device" panel for two seconds. Otherwise leave it out: the
video claims nothing that hasn't run.

**WhatsApp.** If the WhatsApp Business account is connected by recording day, the 1:35 beat shows a
real phone receiving the template (a consenting person's phone, number masked). If not, the APP
footage shows the simulated relative, and the console's "Simulated relative" line stays visible.

## Shots to generate (Higgsfield)

Same Mr Hasan reference as the website photos; same room, light and gown in every shot. Aisyah
and the nurse are new fictional people, made once as reference stills and reused.

| Shot | Length | Content |
|---|---|---|
| G1 | 6 s | Mr Hasan awake, tube taped, lips moving soundlessly; nurse leaning in, puzzled |
| G2 | 4 s | Nurse clamps the phone in a gooseneck mount on the bed rail (matches the mount photo) |
| G3 | 3 s | Close-up, eyebrows rise once (reuse the eval's `brows` clip if it cuts well) |
| G4 | 5 s | Night, room empty except Mr Hasan; monitors glow; phone lit on the rail |
| G5 | 4 s | Nurses' station at night; a nurse hears a chime and looks at the laptop |
| G6 | 6 s | Aisyah at home in the evening; phone buzzes; she reads, exhales, types. Screen never visible |
| G7 | 3 s | Close-up, eyebrows up three times fast |
| G8 | 6 s | Aisyah at the bedside, holding his hand; he raises his eyebrows |

## App footage to record (Playwright, fly.io, live mode)

| Clip | Screen | What happens |
|---|---|---|
| A1 | Calibrate, 1440x900 | Picker, eyebrows card, examples recorded, results with description and boxes |
| A2 | Console 1440x900 + phone 390x844 | Daughter scenario to the confirmed message and "Did I say it right?" |
| A3 | Console + phone | Relay offer, pending card with chime, repeat after a minute, Send, "I'm coming", phone acknowledgement |
| A4 | Console | Relay statuses, reply, Muse Spark's reading, reply read to the patient |
| A5 | Console + phone | Spelling KUCING, with the EN to ID toggle |
| A6 | Console | Emergency alarm and acknowledgement |
| A7 | Memory page | One fact with provenance, approved |

## Sound

- **Narration:** N1 to N9 from `video/cues.json`, ElevenLabs `eleven_v4`, one voice, each line
  generated with the lines before and after it as context so the joins sound like one take.
- **Music:** one 3:00 instrumental from ElevenLabs Music, built from a composition plan whose
  sections follow the timeline above (piano, pulse, thin strings, warm swell, light, steady,
  piano resolve). No vocals.
- **Effects:** ICU room tone, night ward hum, clamp click, phone buzz, soft whoosh for the
  section cuts. Generated with ElevenLabs.
- **App sounds stay the app's:** the chime and the alarm are synthesized in the browser by
  `frontend/src/lib/alarm.ts`. Render them from that code; never substitute a generated sound.
- **The phone's voice:** the app speaks with the device's own text-to-speech. Screen recordings
  carry no audio, so a second ElevenLabs voice (Sarah, `bright_phone` filter) reads the phone's
  lines. The words are the app's words, copied from the recording.

## Assembly (HyperFrames)

The composition lives in `video/`. Layers, bottom to top: GEN and APP clips, captions (narration
and phone lines), CARD overlays, the label. Audio: narration on top, phone voice and app sounds
next, effects, then music ducked under every spoken line. Render 1920x1080 at 30 fps.

## X post draft

268 of 280 characters, counting each link as 23.

> Awake on a ventilator. Can't speak. Alone.
>
> Ventriloquist reads the one movement he still has, asks yes/no questions until it knows what he means, and says it aloud. With his yes, it texts his daughter.
>
> #MetaAIHackathon [video] [link]
