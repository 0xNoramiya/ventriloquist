# Client protocol

The backend (FastAPI, port 8000) owns all state and every model call. Two browser views share one
session: `/patient/:sid` (the phone facing the patient) and `/caregiver/:sid` (laptop or tablet).
Both receive the same full snapshot over a WebSocket after every change. The Vite dev server proxies
`/api` and `/ws` to the backend so the phone only talks HTTPS to one origin.

## WebSocket `/ws/sessions/{sid}`

Server → client, after every change:
```json
{"type": "snapshot", "snapshot": { ...see below... }, "event": {"type": "alarm" | "alert" | "sensitive" | "error", "text": "..."}}
```
`event` is present only for one-shot happenings (play the alarm, show a banner).

Client → server:
| message | who | meaning |
|---|---|---|
| `{"type": "start"}` | patient view after "Tap to start" | builds context and asks the first question |
| `{"type": "spoken", "prompt_id"}` | patient view | finished speaking `snapshot.prompt.text` (question or message) |
| `{"type": "answer", "prompt_id", "answer": "yes"\|"no"\|"unclear"\|"emergency"}` | patient view, mock mode keyboard (Y/N/U/E) | the patient's answer |
| `{"type": "override", "action"}` | caregiver view | see actions below |
| `{"type": "ping"}` | either | keep-alive, answered with `{"type": "pong"}` |

Caregiver override actions: `yes`, `no`, `unclear` (answer for the patient; shown with an override
badge), `skip`, `spell`, `pause`, `resume`, `emergency`, `ack_emergency`, `ack_sensitive` (speak the
held message), `ack_sensitive_silent` (acknowledge without speaking), `new_message`,
`refresh_context`, `end`.

## Prompt lifecycle (patient view)

1. Snapshot arrives with a new `prompt.id` and `state` in `ASKING | CONFIRMING | SPELLING | POST_CHECK`:
   speak `prompt.text` (Web Speech API, `id-ID` or `en-US`, rate 0.9), then send `spoken`.
2. State becomes `LISTENING`: show the listening indicator. Live mode: wait 300 ms, record a
   4.0 s clip with MediaRecorder and `POST /api/sessions/{sid}/clip` (multipart `prompt_id`, `file`).
   Mock mode: keys Y/N/U/E send `answer`.
3. State `SPEAKING` with `prompt.kind == "message"`: speak the confirmed message (first person),
   then send `spoken`. A post-check question follows.
4. `EMERGENCY`: full-screen alarm. `PAUSED`, `CAREGIVER_NEEDED`, `DONE`: calm status screens.
   The patient view never shows probabilities.

## Snapshot (abridged; full example in `docs/snapshot_example.json`)

| field | meaning |
|---|---|
| `state` | `IDLE, CONTEXT_REFRESH, ASKING, LISTENING, PROCESSING, CONFIRMING, SPEAKING, POST_CHECK, DONE, EMERGENCY, PAUSED, SPELLING, CAREGIVER_NEEDED` |
| `stage` | `main, spelling, sentence, refine, refine_offer, worse, post_check, done` |
| `prompt` | `{id, kind: ask\|confirm\|offer_spell\|spelling\|post_check\|refine_offer\|worse\|message, stage, sub: letter\|checkpoint\|word (spelling), text (patient language), text_en, question {id, kind, text_en, text_id, yes_ids, ...}, group: [letters], word, rephrased}` |
| `listening` | true while the patient should answer |
| `posterior` | top 8 `{id, text_en, text_id, p, prior, chips: [{evidence_id, factor, reason}], bounded, personal, source, urgent}` (caregiver view only) |
| `other_p` | probability of "something else" |
| `questions`, `max_questions` | questions asked for this message, cap (10) |
| `trail` | `{n, prompt_id, kind, stage, text, text_en, answer, confidence, overridden, source, rephrased, sources: {tracker\|local\|spark\|keyboard\|caregiver: {...}}, group, top_after}` |
| `spelling` | `{text, top: [[symbol, p]], completions: [[word, p]]}` or null |
| `rejected` | model proposals the code refused `{what, text, why}`: uncited multipliers, sensitive or advice-like messages and questions |
| `pending_ack` | spoken messages still waiting for someone to tap "I'm coming" (Safety rule 14) |
| `relays` | family relays `{id, to, relation, phone (masked), patient_text, status, simulated, reply}` (Safety rule 15) |
| `sentence_options` | candidate sentences while a spelled word is turned into a sentence, or null |
| `message` | current message `{id, hypothesis_id, text_en, text_id, source, status: speaking\|needs_verification\|confirmed\|retracted, urgent, sensitive, categories, questions}` |
| `messages` | this session's spoken messages with status (retracted ones are shown struck through) |
| `evidence` | `{id: S1\|T1\|E1\|M1\|H1, kind, text, at, minutes_ago}` |
| `caregiver_reason`, `caregiver_text` | why the caregiver is needed (`sensitive_verify` shows the "Verify in person with the patient" banner) |
| `alerts` | recent `{kind: emergency\|urgent\|sensitive, text, at}` |
| `emergency` | alarm active |
| `signals` | calibrated `{yes: {body_part, motion, description}, no: {...}}` (patient view shows "Eyebrows up = YES") |
| `calibration` | `{skipped, error_rates: {a, b}, accuracy}` |
| `overlay` | latest clip tracking boxes `{provider, prompt, frames: [{t, objects: [{id, box: [x0,y0,x1,y1] normalised]}]}], prompt_id}` |
| `mode` | `{requested, effective, reason}`: badge mock / live / privacy |
| `llm_calls` | recent model calls `{role, provider, model, latency_ms, usd, fallback}` |
| `budget` | `{spent_usd, max_usd, fraction, level: ok\|warn\|mock}` |

## REST

| route | purpose |
|---|---|
| `GET /api/health`, `GET /api/config`, `GET/PUT /api/settings`, `GET /api/budget` | status, public config (taxonomy, event kinds, scenarios, flags), runtime settings |
| `POST /api/patients`, `GET /api/patients`, `GET/PUT/DELETE /api/patients/{pid}` | profile (`display_name, language, honorific, family[{name, relation}], notes[], spiritual_preference, simulation_consent`); DELETE wipes everything |
| `POST /api/calibration/{pid}/framing` (image), `POST .../clip` (multipart `label`: rest\|yes\|no\|emergency, `file`), `DELETE .../clips`, `POST .../finalize` (`{hint?, description?, skip?, privacy?}`), `GET /api/calibration/{pid}`, `PUT .../description` | bring-your-own-signal calibration |
| `POST /api/sessions` (`{patient_id, privacy, simulated_patient?, simulated_noise, scenario?, passcode?}`), `POST /api/scenarios/{name}` (`{simulated?, noise?, language?, privacy?}`) | create a session (scenario = fictional patient + evidence) |
| `GET /api/sessions/{sid}`, `POST .../start`, `.../spoken`, `.../answer`, `.../clip`, `.../idle`, `.../audio`, `.../transcript` (`{speaker, text}`), `.../snapshot` (image), `.../event` (`{kind, label}`), `.../override` (`{action}`), `.../end`, `GET .../log` | session control |
| `GET /api/memory/{pid}`, `POST /api/memory/{pid}` (caregiver fact), `POST .../curate`, `POST .../ops/{op}/approve\|reject`, `DELETE /api/memory/{pid}/{entry}` | memory with provenance and approvals; learning curve |
| `GET /api/sim/results`, `POST /api/sim/run` (`{trials, seed}`) | simulation |
