# API notes: Meta Model API, Baseten, Modal

Engineering notes for the Ventriloquist adapters. Facts come from the official docs (URLs inline) and from live probes run 2026-10-26 UTC (`scripts/probe_*.py`; raw responses in `backend/tests/fixtures/meta_api/`). "Observed" means measured by a probe. "Docs" means stated in the docs but not exercised. **UNTESTED** marks code that has not run against the live API.

Docs index (Markdown for every page): https://ai.developer.meta.com/docs/llms.txt. Each page is also served as raw Markdown at `https://dev.meta.ai/docs/<page>.md`.

Probe spend so far: **≈ $0.08** at list prices (ledger: `data/probe_media/spend_ledger.jsonl`).

## 0. Quick reference

| Need | Endpoint | Model | Media in | Read result at | Observed latency | Observed cost |
|---|---|---|---|---|---|---|
| question plan JSON | `POST /v1/responses` | `muse-spark-1.3` | text | `output[type=message].content[type=output_text].text` (JSON string) | 1.3–1.7 s (minimal) | ~$0.0013 |
| still-image judge | `POST /v1/responses` | `muse-spark-1.3` | `input_image.image_url` = data URL | same | 2.3–2.5 s | ~$0.001–0.002 |
| clip judge (4 s) | `POST /v1/responses` | `muse-spark-1.3` | `input_video.video_url` = data URL (+`fps`) or `file_id` | same | 3.8–5.1 s (one 13.3 s outlier) | $0.0028 (default fps) / $0.0066 (`fps: 8`) |
| image segmentation | `POST /v1/responses` | `sam-3.1` | `input_image.image_url` | SAM wire text in `output_text` | 1.4–2.6 s | $0.0025 |
| video tracking (4 s @ 15 fps) | `POST /v1/responses` (stream) | `sam-3.1` | `input_video.video_url` / `file_id` | one SSE `response.output_text.delta` per frame | 3.2–6.0 s total, 1st frame 1.4–2.7 s | $0.012 (60 frames) |
| transcript (file/chunk) | `POST /v1/asr/transcribe` | `muse-voice-transcribe-1.0` | multipart WAV, mono s16, 16/24 kHz | `transcript`, `turns[]` | 1.6–3.5 s for 4–13 s clips | $0.003/min |
| live transcript | `wss://api.meta.ai/v1/asr/realtime` | same | raw PCM frames | `speechComplete.transcript` | final ≈ 0.3 s after end of speech | same |
| context/memory extraction | `POST /v1/responses` | `muse-wonder-1.0` | text | same as Spark | 1.3–4.1 s (minimal) | ~$0.004 |
| open model (Baseten) | `POST https://inference.baseten.co/v1/chat/completions` | `meta-models/muse-spark-open[-1026]` | `image_url`/`video_url`/`audio_url` parts | `choices[0].message.content` | UNTESTED | $1.25 / $4.25 per M |

## 1. Common to all Meta endpoints

Sources: https://dev.meta.ai/docs/authentication, /docs/protocols/responses, /docs/error-handling, /docs/pricing-rate-limits, /docs/api-reference.

- **Base URL** `https://api.meta.ai/v1`. **Auth** `Authorization: Bearer $MODEL_API_KEY`. Keys look like `LLM_<numeric id>_<secret>`. No SDK reads `MODEL_API_KEY` by itself, so pass it explicitly: `OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])`. Observed working with `openai` 3.38 (Python).
- **Endpoints**: `POST /responses` (recommended; also used for SAM and Muse Image), `POST /chat/completions`, `POST /messages` (Messages-format compatible), `POST /responses/input_tokens` (token count, no generation), `GET/DELETE /responses/{id}`, `POST /responses/{id}/cancel`, `POST/GET/DELETE /files`, `GET /models`, `GET /models/{id}`, `GET /status` (no auth; observed `{"is_alive":true,"service_status":"operational",...}`), `POST /asr/transcribe`, `wss /asr/realtime`, `POST /images/generations|edits`.
- **`store` defaults to `true`** on Responses, which keeps the response server-side for `GET /responses/{id}` and `previous_response_id`. For patient data, send `store: false` (all probes do). Prompt caching still works with `store: false` (docs: /docs/prompt-caching). A non-streaming `store: true` request with large inline base64 media can return **413** after inference succeeds, so use `store: false` or `file_id` (docs: /docs/error-handling#413).
- **Error envelope**: `{"error": {"message", "type", "param", "code"}}`. `type` is one of `invalid_request_error` (4xx), `authentication_error` (401), `rate_limit_error` (429) or `server_error` (5xx). `code` is often `null` on validation errors. An unknown path returns **404 with an empty body**. Observed example: `fixtures/meta_api/spark_error_reasoning_none.json`.
- **Retry**: retry 429/500/503 with exponential backoff and jitter (start 0.5–1 s, honour `Retry-After`; 503 `service_overloaded`/`backend_unavailable` send `Retry-After: 60`). Do not retry 400/401/402/403/404/413. On **504** (`gateway_timeout`, non-streaming over the server time limit), stream the request, use `background: true`, or reduce the work. Do not blindly retry. Mid-stream failures arrive as a `response.failed` event or a top-level `error` SSE event (e.g. `code: server_shutting_down`), never as an HTTP status.
- **Rate-limit headers** (observed on Spark/Wonder): `x-ratelimit-limit-requests: 3000`, `x-ratelimit-limit-tokens: 4000000`, `x-ratelimit-remaining-*`, `x-request-id`. SAM returns only the request headers. Transcription returns none. Limits are per team, not per key.
- **Injected tokens**: Meta adds a hidden system prompt that is not billed. `POST /responses/input_tokens` includes it, so the count runs higher than billed `usage.input_tokens` (observed 212 vs 185 for text, 583 vs 456 with a 640×480 image).
- **Sampling**: leave `temperature`/`top_p` at defaults (docs). `logprobs` → 400 on Spark. `truncation: "auto"` → 400. `n>1`, `stop` and `verbosity` are not implemented on Responses.
- `safety_identifier` (≤64 chars, hashed user id) is recommended when there is an end user (docs: /docs/protocols/responses#safety-identifiers).

## 2. Muse Spark — text, structured output, reasoning

Sources: https://dev.meta.ai/docs/models, /docs/reasoning, /docs/structured-output, /docs/protocols/responses, /docs/protocols/chat-completions. Fixtures: `spark_responses_text_minimal.json`, `spark_responses_json_schema.json`, `spark_chat_json_schema.json`, `spark_responses_incomplete.json`, `spark_error_reasoning_none.json`, `spark_chat_error_reasoning_none.json`, `spark_input_tokens_count.json`.

- Models: `muse-spark-1.3` (recommended), `muse-spark-1.2`, `muse-spark-1.1`; `-contributor` variants of 1.3/1.2 are cheaper but your content may be used for training (do not use for patient data). Context window 1,048,576 tokens. Input: text, image, video, audio and PDF. Output: text.
- **Reasoning effort**: Responses `reasoning: {"effort": ...}`; Chat top-level `reasoning_effort`. Values `minimal | low | medium | high | xhigh | max`. **`none` → HTTP 400** (observed on both endpoints: `"reasoning_effort 'none' is not supported for model 'muse-spark-1.3'. Supported values: [minimal, low, medium, high, xhigh, max]"`, `param: "reasoning.effort"`). Reasoning tokens count toward `max_output_tokens` and are billed as output.
- Observed for "reply with one word": `minimal` took 1.62 s with 25 output tokens (15 reasoning); `low` took 2.11 s with 112 output tokens (102 reasoning).
- **Structured output (Responses)**: `text={"format": {"type": "json_schema", "name": "...", "schema": {...}, "strict": true}}`. Decoding is constrained, so output always conforms. `strict: true` additionally validates the schema against the strict subset (root object, `additionalProperties: false` everywhere, `required` lists every key, no `allOf`/`oneOf`). Recursive schemas → 400. Limits: depth 10, 5,000 properties, 1,000 enum values. On Chat Completions use `response_format={"type": "json_schema", "json_schema": {"name", "schema", "strict"}}`. `response_format` on Responses is accepted but ignored.
- Observed: both endpoints returned JSON that parsed on the first try, 1.3–1.7 s at `minimal`, ~185 in / 250–270 out tokens (160–180 reasoning), $0.0012–0.0014.
- **Response shape (Responses)**: `status` (`completed` | `incomplete`), `incomplete_details.reason` (e.g. `"max_output_tokens"`), `output[0]` = `{type: "reasoning", id: "rs_<resp>:rs_<uuid>", encrypted_content (only with include), summary: []}`, `output[1]` = `{type: "message", role: "assistant", content: [{type: "output_text", text, annotations: [], logprobs: []}]}`. Find the message item by `type`, not by index. Usage: `usage.input_tokens`, `usage.input_tokens_details.cached_tokens`, `usage.output_tokens`, `usage.output_tokens_details.reasoning_tokens`, `usage.total_tokens`.
- **Response shape (Chat)**: `choices[0].message.content`, `choices[0].finish_reason`. Usage: `usage.prompt_tokens`, `usage.completion_tokens`, `usage.prompt_tokens_details.cached_tokens`, `usage.completion_tokens_details.reasoning_tokens`. `reasoning_content` is redacted to empty for external keys.
- `max_output_tokens` minimum is 16. With 16, observed `status: "incomplete"`, `incomplete_details.reason: "max_output_tokens"` (14 of the 16 tokens went to reasoning). Budget **≥ 400–600** for small JSON at `minimal`.
- Multi-turn: `previous_response_id` (needs `store: true`) **or** stateless replay with `include: ["reasoning.encrypted_content"]` + `store: false`, never both (400). `instructions` is not carried over by `previous_response_id`, so resend it each turn.

## 3. Muse Spark — image understanding

Sources: https://dev.meta.ai/docs/image-understanding, /docs/file-handling. Fixtures: `spark_responses_image_grounding.json`, `spark_responses_image_face.json`.

- Responses content part: `{"type": "input_image", "image_url": "<https URL or data:image/png;base64,...>"}` (a plain string), or `{"type": "input_image", "file_id": "file-..."}`, or `{"type": "input_file", "file_id"|"file_data"|"file_url"}`. Optional `detail`: `high | low | auto | original`. Chat Completions: `{"type": "image_url", "image_url": {"url": ...}}`. Images are read only in `user` messages.
- Formats: png, jpeg, gif, webp, x-icon. Limits: 50 MB inline, 1 GiB via Files, **≤ 50 images per request** (more → 400). Undecodable image → 400 `invalid_request_error`.
- Tokens: ≈ 350–400 billed input tokens for a 640×480 PNG (observed: 456 with a ~90-token prompt, 420 with a ~30-token prompt; the docs give ~1,300–1,500 for a ~1280 px image).
- Grounding uses a **0–1000 normalised grid** (x right, y down), relative to the image as sent. Values may slightly exceed 1000, so clamp. Observed with a json_schema of `x_min..y_max`, scaled to px against ground truth: photo frame `[110,180,176,252]` (truth `[110,180,175,250]`), bed `[259,170,602,431]`, table `[84,252,207,432]`, `people_present: false`.
- Observed face judge (`face_still.png`, eyebrows at peak): `{"eyebrows_raised": true, "eyes_open": true, "confidence": 0.95}` in 2.33 s, 420 in / 145 out tokens.

## 4. Muse Spark — video (and audio)

Sources: https://dev.meta.ai/docs/video-understanding, /docs/file-handling, /docs/api-reference/responses/schemas (Input Video Content). Fixtures: `spark_responses_video_inline.json`, `spark_responses_video_inline_fps4.json`, `spark_responses_video_file_id.json`, `files_upload_video.json`.

- **Three accepted ways** (all observed working):
  1. Inline: `{"type": "input_video", "video_url": "data:video/mp4;base64,..."}` (≤ 50 MB). No upload needed.
  2. Upload, then reference by `input_video`: `client.files.create(file=("clip.mp4", bytes, "video/mp4"), purpose="user_data", expires_after={"anchor": "created_at", "seconds": 3600})`. The response is `{id: "file-<digits>", object: "file", bytes, created_at, filename, purpose: "user_data", status: "uploaded", expires_at}`. Upload is synchronous (1.8–3.0 s observed). Then `{"type": "input_video", "file_id": id}`.
  3. Upload, then reference by `input_file`: `{"type": "input_file", "file_id": id}`.
  `expires_after.seconds` ranges 3600–2592000. Without it, files never expire and count toward the 100 GiB team storage. Delete with `client.files.delete(id)` → `deleted: true` (3.6–4.6 s observed). Note: ZDR orgs cannot use file uploads.
- Formats (Spark): **MP4 only** (`video/mp4`); embedded audio is read too, and clips without audio are fine. (SAM also accepts MOV.)
- **Frame sampling / `fps`**: `input_video.fps` (number) exists in the schema and **works** (observed). Billed input tokens for the same 4 s 640×480 clip: default 1,086, `fps: 4` 2,126, `fps: 8` 4,206. That is ≈ 130 tokens per frame plus ~46, which implies a **default of ≈ 2 fps** (inferred). Accuracy on the synthetic YES clip (truth: 2 eyebrow raises + 1 blink): default counted 1 raise, 0 blinks; `fps: 4` counted 1 raise, 1 blink; **`fps: 8` counted 2 raises, 1 blink (correct)**. On the NOD clip (truth 2 nods) the default fps counted 1 nod, signal `HEAD_NOD`. On the REST clip (truth 3 blinks) it counted 1 blink, signal `NONE`. Short movements need `fps ≥ 8`.
- **Gotcha**: `POST /responses/input_tokens` does **not** count video frames (it returned 203 for every fps while billing was 1,086–4,206). Estimate video cost from billed usage instead.
- Latency at `minimal`: 3.8–5.1 s, one outlier of 13.3 s (`fps: 4`). The config `perception.judge_timeout_s: 6` will occasionally time out.
- Max frames or duration per Spark request is not documented, beyond the 50 MB inline and 1 GiB upload limits.
- Background mode (`background: true`) caps the JSON body at 1 MiB, so use `file_id` for video there.
- Audio input: `{"type": "input_audio", "input_audio": {"data": "<base64>", "format": "wav"|"mp3"}}`. The docs say audio on 1.3 "is not fully supported, quality may be degraded" and recommend `muse-spark-1.2` or Voice Transcribe. Set `max_output_tokens ≥ 4000` for transcription (docs). Not probed.

## 5. SAM 3.1 — image segmentation

Sources: https://dev.meta.ai/docs/media-segmentation, /docs/sam/overview, /docs/sam/segmenting, /docs/sam/reading-segmentation, /docs/sam/client-libraries. Fixtures: `sam_image_stream_lossless.json`, `sam_image_nonstream_one_bit.json`, `sam_image_stream_one_bit_eyebrows.json`.

- Request: `POST /v1/responses`, `model: "sam-3.1"`, one user message holding `{"type": "input_text", "text": "<short noun phrase>"}` plus `{"type": "input_image", "image_url": "<data URL or https>"}`. `stream: true` is recommended; `stream: false` returns the same text in one body (observed). `metadata` values are **strings**: `{"mask_encoding": "one_bit"|"lossless", "include_confidence": "true"}`.
- Prompt rules (docs): one concrete noun phrase per request. No lists, commands, negation or spatial phrases (filter by box in code). Plural, case and punctuation are ignored. Alternative: box/point prompts in the same grammar (`<0f>1<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H|>`), ≤ 16 objects, never mixed with a phrase. `w`/`h` must be the media size, and a wrong aspect ratio → 400.
- **Output is not JSON.** Read it from `output[0].content[0].text` (non-stream) or by concatenating `response.output_text.delta` (stream). There is one line per frame. An image is one line:
  `<0f>0<|box;x1=110;y1=180;x2=175;y2=250;w=640;h=480;c=0.8828|><|mask;x=0;y=0;c=0.8828;data=71,66,~<base85>|>,1<|box;...|><|mask;...|>`
  The leading integer is the object id. Box corners are source pixels, and `x2`/`y2` are **inclusive**. `w`,`h` give the frame size. `c` (confidence 0–1) appears only with `include_confidence`. The mask `data=H,W,<enc><payload>` covers the **box only**: `H = y2−y1+1`, `W = x2−x1+1` (observed), so place it at `(x1, y1)`. `~` marks lossless (8-bit coverage, which the official parser thresholds at ≥129) and `!` marks one_bit. The payload is base85 range-coded: decode it with the official **`meta-sam-parser`** (`pip install meta-sam-parser`, v0.1.0, pure Python, no dependencies): `decode_mask_to_raster(SegmentationMask(encoding="one_bit", payload="!<payload>", width=W, height=H))` returns row-major 0/1 bytes. **The payload passed in must keep its leading marker.** `decode_mask_to_rle` gives COCO RLE. The parser's stream API is async-only.
- Zero matches: `completed` with empty `output_text` and no delta events. This is not an error.
- Usage: `usage.input_tokens = output_tokens = 0`, **`usage.images_processed: 1`**. Billing is per image.
- Observed: `photo frame` → 1 match, box exactly the truth `[110,180,175,250]`, c 0.88, 2.56 s stream (first delta 2.05 s). `bed` → `[280,226,601,400]` (misses the headboard), 1.40 s non-stream. `eyebrows` on the face still → **one object covering both brows** `[222,128,417,155]`, c 0.89, 1.88 s. Decoded mask foreground: 4,657 of 4,686 box pixels (frame), 2,140 of 5,488 (eyebrows).
- Stream event order (image): `response.created`, `response.in_progress`, `response.output_item.added`, `response.content_part.added`, `response.output_text.delta` ×1, `response.output_text.done`, `response.content_part.done`, `response.output_item.done`, `response.completed`.

## 6. SAM 3.1 — video segmentation and tracking

Sources: same as §5. Fixtures: `sam_video_stream_one_bit_eyebrows.json`, `sam_video_stream_file_id_face.json`, `sam_video_nonstream_lossless_eyebrows.json`.

- Media part: `{"type": "input_video", "video_url": "data:video/mp4;base64,..."}` (observed inline) or `{"type": "input_video", "file_id": "file-..."}` (observed). Containers MP4/MOV with H.264, H.265 or MPEG-4 video (not VP9/WebM, so browser MediaRecorder WebM must be transcoded). Up to 15,000 frames (~10 min). Up to 16 tracked objects per frame.
- **Output**: one `response.output_text.delta` per frame line `<Nf>id<|box..|><|mask..|>,...`. `N` is the zero-based **source frame index**: it can skip frames with no object, and it is not ascending for `both` box/point propagation. **There are no timestamps on the wire**, so compute `t = N / source_fps`. Object ids are stable across frames while the object stays visible ("identity-preserving tracks"); key by id, not position. Concept prompts return ascending frames (observed 0..59).
- Every source frame is processed: 60 frames for 4 s @ 15 fps → `usage.video_frames_processed: 60` → $0.012. Billing minimum is 50 frames per request. To cut cost, downsample fps before upload (e.g. 15 → 8 fps).
- `metadata.propagation_direction`: `both` (default) | `forward` | `backward`, for box/point prompts only.
- Observed YES clip, `eyebrows`, inline, stream, one_bit+c: 60 lines, 1 object (id 0). Box top `y1` is 163 at rest, **128 at frame 15 and 130 at frames 40–41**, matching the truth peaks at frames 15 and 40 (28 px raise plus arch). c is constant at 0.89. Total 5.04 s, first frame line after 2.67 s.
- Observed NOD clip, `face`, uploaded `file_id`, stream: box centre-y 272 → **310 at frames 15 and 40–41** (truth 15, 40). 3.21 s total, first line 1.44 s.
- Observed REST clip, `eyebrows`, inline, **non-stream**, lossless: `y1` flat at 163 on all 60 frames. 6.00 s, 73 KB text.
- **Conclusion**: SAM box geometry alone separates YES (eyebrow `y1` dips ≥ 30 px) from NOD (face centre moves ~38 px) from REST (flat) on synthetic media. The decision logic can run on boxes, so masks are optional.
- "Live" frame inference is not offered. The API takes whole clips (docs cookbook: "The model APIs currently process uploaded files rather than exposing live frame inference").

## 7. Muse Voice Transcribe

Sources: https://dev.meta.ai/docs/speech-to-text, /docs/api-reference/voice/transcribe, /docs/api-reference/voice/realtime, /docs/api-reference/voice/schemas, /docs/pricing-rate-limits. Fixtures: `asr_transcribe_en_push_to_talk.json`, `asr_transcribe_id_language_bias.json`, `asr_transcribe_id_no_bias_endpointing.json`, `asr_transcribe_diarization.json`, `asr_transcribe_endpointing_sse.json`, `asr_realtime_endpointing_events.json`, `asr_error_48khz.json`.

**File / chunk endpoint** `POST https://api.meta.ai/v1/asr/transcribe?sessionId=<optional>` (`Authorization: Bearer`):
- `multipart/form-data` with two parts: `request` (JSON) = `{"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"|"ENDPOINTING"|"DIARIZATION", "languageBias": ["Indonesian"], "keywords": ["Aisyah"], "partialMode", "emitAudioProgress"}`, and `audio` (the WAV file).
- Audio must be **RIFF WAV, mono, signed 16-bit PCM, 16 kHz or 24 kHz**. A 48 kHz file → **400** `"Unsupported WAV format: channels=1, sampleRate=48000, bitsPerSample=16; expected mono s16le at 16000 or 24000 Hz"` (observed). Convert with `ffmpeg -i in -ac 1 -ar 24000 -c:a pcm_s16le -map_metadata -1 out.wav`. Limits: body ≤ 32 MB (413), audio ≤ 10 min (400).
- `Accept`: `application/json` (default) | `text/event-stream` (realtime-format events, no summary) | `text/plain` (`A:text` lines in DIARIZATION). Anything else → 406.
- JSON response: `sessionId`, `transcript` (all modes), `audioDurationMs`, `turns[]` = `{turnId, startMs, endMs, transcript, speaker?}`. `turns` is empty in PUSH_TO_TALK. **`turnId` starts at 0** (observed; the docs examples start at 1). Timestamps are turn-level only, with no word timings or confidences.
- Errors: 400 / 406 / 413 / 429 (rate) / 500 (retry once). Error JSON = `{"sessionId", "error": {"code", "param", "type", "message"}}`.

**Streaming**: two options.
1. The file endpoint with `Accept: text/event-stream`. Observed events: `speechStart`, `transcript` (partials), `speechEnd`, `speechComplete`, each as `event: <type>\ndata: {"type":..., "audioProcessedMs":..., "turnId":..., "transcript":...}`.
2. **Realtime WebSocket** `wss://api.meta.ai/v1/asr/realtime?sessionId=<optional>`. The HTTP `Authorization` header is ignored. Within 10 s of connecting, send the first text frame `{"authorization": {"accessToken": "Bearer <key>"}, "audioEncoding": "PCM_24KHZ"|"PCM_16KHZ", "model": "muse-voice-transcribe-1.0", "mode": ..., "partialMode": "CUMULATIVE"|"DELTA", "emitAudioProgress": bool, "languageBias": [...], "keywords": [...]}`. The server acks with `{"sessionId"}` (no `type`). Then send **binary frames of raw s16le mono PCM paced at real time** (observed with 80 ms frames). Sending more than 5 s ahead, or slower than real time, closes with 1008. Keep sending silence while live. Send `{"type": "endStream"}` and read until close **1000**. Other close codes: 1008 bad request/pacing (do not retry), 1011 internal (retry; reconnect when the 60 min max session is reached), 1013 rate limited. Events: `speechStart`, `transcript` (partial; under CUMULATIVE replace, do not append), `speechEnd`, `speechComplete` (final turn text), `speaker` (DIARIZATION), `audioProgress`, `error`. Ignore unknown types.
- Observed realtime (Indonesian clip, ENDPOINTING, with languageBias): ack at 1.46 s, first partial 1.45 s after audio began, `speechComplete` ≈ 0.3 s after the speech audio ended, WER 0.00. **After `endStream`, ENDPOINTING emits one extra `transcript` with `final: true` and empty text**, so ignore it. The key travels in the handshake, so a browser cannot connect directly without exposing it: **proxy through the backend**.

**Quality (observed, espeak-ng synthetic speech, WER on words, digits normalised)**:

| clip | settings | WER | transcript |
|---|---|---|---|
| EN | none | 0.08 | "your daughter **Asia** went home to rest, she will be back at four." |
| EN | `keywords: ["Aisyah"]` | **0.00** | "your daughter Aisyah went home ..." |
| ID | none (PUSH_TO_TALK and ENDPOINTING, run twice) | **1.00, empty transcript** | `""` (still billed) |
| ID | `languageBias: ["Indonesian"]` | 0.08 | "anak bapak, **ayah**, pulang dulu untuk istirahat, nanti jam empat dia kembali," |
| ID | `languageBias: ["Indonesian"]` + `keywords: ["Aisyah"]` | **0.00** | "anak bapak, Aisyah, pulang dulu untuk istirahat, nanti jam empat dia kembali." |
| ID | `languageBias: ["Indonesian", "English"]` | 0.25 | first three words dropped |
| ID realtime | `languageBias: ["Indonesian"]` + keywords | 0.00 | exact |
| two voices | DIARIZATION | 0.03 | 3 turns with speakers **A / B / A**, correct (one duplicated word "nurse nurse") |

Rule: **always send `languageBias` with the single expected language, plus `keywords` for family names.** In ENDPOINTING, speaker B's two sentences came back as two turns, while DIARIZATION kept them as one.

- Pricing: **$0.18 per audio hour** ($0.003/min), billed per whole second. Streaming and file transcription cost the same. ZDR is priced at parity. Failed and 429 requests are not billed. Limits: 256 concurrent streams, 16,000 streams/hour per team, shared by both endpoints. No `x-ratelimit-*` headers.
- Docs list **25 supported languages** (including Indonesian and Malay) with code-switching. They also say: no word-level timestamps, no emotion or sound events, no TTS.

## 8. Muse Wonder

Sources: https://dev.meta.ai/docs/models#muse-wonder, /docs/pricing-rate-limits, model page https://dev.meta.ai/models/muse-wonder. Fixtures: `wonder_responses_json_schema.json`, `wonder_responses_previous_response_id.json`.

- `muse-wonder-1.0` (preview). Same requests and endpoints as Spark. Context 1,048,576 tokens. Input: text, image, video, audio and PDF. Reasoning `minimal`…`max` (`none` → 400 like Spark, per docs). Standard mode only (no contributor). Pricing: $4.00 in / $0.20 cached / $20.00 out per M.
- Observed json_schema fact extraction from a 4-line bedside transcript: 1.93 s, 94 in / 165 out (71 reasoning), $0.0037. Output was correct (`"Daughter Aisyah went home to rest; will return at 4"`).
- **"Active memory" is a model-page marketing claim. There is no memory API in the docs.** Cross-call state exists only through (a) `store: true` + `previous_response_id`, (b) client-side history, or (c) encrypted reasoning replay. Observed: a chained call recalled a code word (`PELANGI`); a fresh call returned `unknown`. Keep Ventriloquist memory in our own store and select it into the prompt. `DELETE /v1/responses/{id}` → `{"id", "object": "response.deleted", "deleted": true}`; a repeat delete → 404.

## 9. Muse Image (docs only, not probed)

Sources: https://dev.meta.ai/docs/image-generation, /docs/api-reference/images/create-image, /docs/pricing-rate-limits.
- `muse-image-1.0` on `POST /v1/images/generations` and `/v1/images/edits` (single-shot), or on Responses for multi-turn edits. $0.01 per generated image, with built-in web search included. 150 RPM. An undeclared field such as `seed` → 400. The probe image `hospital_room.png` was drawn with OpenCV instead.

## 10. Muse Spark Open on Baseten (tested live 2026-10-29)

Sources: https://docs.baseten.co/inference/model-apis/overview, /inference/model-apis/vision, /inference/model-apis/audio, /inference/model-apis/reasoning, /inference/structured-outputs, /inference/model-apis/pricing-and-limits, https://www.baseten.co/library/muse-spark-open, https://dev.meta.ai/docs/muse-spark-open/deploy#baseten.

- OpenAI-compatible Chat Completions at `https://inference.baseten.co/v1/chat/completions` with `Authorization: Bearer $BASETEN_API_KEY` (a Messages-format endpoint at `/v1/messages` is in beta). No Responses API.
- **Model slug**: every Baseten and Meta page lists `meta-models/muse-spark-open`. The organizer's `meta-models/muse-spark-open-1026` appears nowhere in the docs. Baseten does publish dated slugs for other models (e.g. `deepseek-ai/DeepSeek-V4.1-Flash-1017`), so it is plausible. `probe_baseten.py` tries the config id first and falls back to the documented slug on 404. **Observed 2026-10-29:** `GET /v1/models` lists both `meta-models/muse-spark-open` and `meta-models/muse-spark-open-1026`, and the organizer's id answers.
- Input parts: `{"type": "image_url", "image_url": {"url", "detail"}}`, `{"type": "video_url", "video_url": {"url"}}`, `{"type": "audio_url", "audio_url": {"url"}}`. URLs are fetched by Baseten (https only; localhost and internal IPs are rejected), or use `data:` URLs (these count toward the 100 MiB body). Muse Spark Open limits: ≤ 8 images (≤ 10 MB each by URL), ≤ 2 videos (≤ 200 MB, ≤ 300 s, MP4/MOV/MKV/WebM with H.264/H.265/VP9/AV1, ≤ 4K60). Video is **sampled at ≤ 96 frames and the audio track is ignored**, so send speech as a separate `audio_url`. Audio: WAV/MP3/FLAC/OGG/M4A, 8–48 kHz, ≤ 4 files, ≤ 25 MB and ≤ 5 min each. Total media ≤ 200 MB. **No PDF.** Observed: 5 videos in one request → `400 "Too many videos: 5 (max 2)"`, so the calibration describer sends Muse Spark Open one YES and one NO clip (`VisionLanguage.max_videos`).
- **Video is sampled at 2 frames per second of video time**, and no request field sets the rate (measured 2026-10-29 with numbered frames: a 6 s clip at 15 fps came back as 7 numbers; 12 s clips cost 1,566 prompt tokens at both 2 and 4 fps; 48 frames played at 2 fps came back complete). Meta's Responses API takes `fps` per video; here a 4 s answer window shows about 8 frames, and three quick eyebrow raises read as one long lift. The adapter honours the role's `_video_fps` by slowing the clip, capped at `providers.baseten.video_fps` (see `docs/DETECTOR_EVAL_GENERATED_PRIVACY.md` for the trade-off).
- **Reasoning is always on**: `reasoning_effort` takes `low|medium|high|xhigh` (default **xhigh**), and `none`/`minimal` run as `low`. Reasoning text comes back in `choices[0].message.reasoning_content`. Set `reasoning_effort="low"` for latency.
- **Structured output is not enforced**: `json_schema` is accepted but the schema is not applied, so validate and repair JSON yourself. Tool calling works. `logprobs` is ignored, `n>1` → 400.
- Usage: `usage.prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens`. Price $1.25 in / $0.15 cached / $4.25 out per M. Rate limits depend on account tier (Basic unverified 15 RPM/100k TPM, verified 120 RPM/500k TPM, Pro 120 RPM/1M TPM), with the same `x-ratelimit-*` headers. A `529` means overloaded, so back off. Optional `x-session-affinity: <uuid>` header improves cache hits.
- Synchronous Model API requests fall under Baseten's zero-data-retention policy (docs).
- Observed latency at `reasoning_effort=low`: text 1.3-1.4 s, one image 4.1-4.5 s, one 6 s video 4.8 s, one audio clip 5.4 s. This account's headers: 100 requests and 2M tokens per minute. The espeak probe sentence "Your daughter Aisyah went home to rest" came back as "Your dog raised me. I went home to rest" (no name hints in the probe; the room transcriber sends them).
- **Labels**: the adapter first sent a media part's label ("YES clip 1") only for images, so the describer could not tell which video showed YES. Labels now precede every media part.

## 11. Modal (brief)

- Modal lists **Muse Spark Open** as an OpenAI-compatible shared endpoint, model id `meta-models/Muse-Spark-Open-816B-A42B`, at $1.25 / $0.15 / $4.25 per M (https://modal.com/library/meta/muse-spark-open). Its library page shows **no hosted SAM 3.1 endpoint** (checked https://modal.com/library). SAM 3.1 on Modal would be a self-written Modal app serving the open weights (`facebook/sam3.1` on Hugging Face per third-party listings, not verified). Meta-hosted `sam-3.1` already covers our needs at $0.012 per 4 s clip.

## 11b. Muse Glimmer (open weights, on-premises tier)

- Sources: https://campustechnology.com/articles/2026/08/26/meta-releases-muse-glimmer-an-open-weight-ai-model-designed-to-run-on-consumer-hardware.aspx , https://www.vktr.com/ai-platforms/meta-releases-muse-glimmer/ (news coverage, checked 2026-10-26; read the model card before deploying).
- Reported: 30B dense parameters, distilled from Muse Spark 1.2, Apache 2.0, weights on Hugging Face, quantized to under 20 GB to run on consumer hardware.
- Ventriloquist talks to it through any OpenAI-compatible Chat Completions server (`LOCAL_LLM_URL`, `LOCAL_LLM_MODEL`). Like Baseten, structured output is put in the system prompt and validated with one repair. Text-only roles only; requests with media are routed to Baseten or stay on-device (`providers/onprem.py`).
- UNTESTED against a real Glimmer server; contract test against a mock endpoint.

## 11c. WhatsApp Cloud API (family relay)

Read on 2026-10-27 from Meta's developer docs (send-messages guide, template overview, webhook
endpoint, text and status webhook references). **Not yet run against a real account**: the shapes
below are the documented ones, and `backend/tests/test_relay.py` checks our requests and parsing
against them. Without an account a simulated relative replies, so the loop still runs end to end.

- **Send:** `POST https://graph.facebook.com/v26.0/<WHATSAPP_BUSINESS_PHONE_NUMBER_ID>/messages`,
  `Authorization: Bearer <token>`, JSON body with `messaging_product: "whatsapp"`,
  `recipient_type: "individual"`, `to`, and `type` with the matching object. The response has
  `messages[0].id` (a `wamid.` id); acceptance is not delivery, which arrives by webhook.
- **24-hour window:** free-form messages only within 24 hours of the person's last message to the
  business number; otherwise only an approved template. We always open with the template and use
  text only inside the window (`WhatsAppChannel.body`).
- **Template message:** `type: "template"`, `template: {name, language: {code}, components:
  [{type: "body", parameters: [{type: "text", text}]}]}`; positional parameters follow the order of
  `{{1}}`, `{{2}}`. Templates must be `APPROVED` before sending. Register this one in WhatsApp
  Manager (category Utility):
  - name `patient_message`, language `en`: `{{1}} asked us to send you this message from the
    hospital: "{{2}}". Reply here and we will read your reply to them.`
  - same name, language `id`: `{{1}} meminta kami mengirimkan pesan ini dari rumah sakit: "{{2}}".
    Balas pesan ini dan kami akan membacakan balasan Anda kepadanya.`
- **Webhook verification:** `GET <callback>?hub.mode=subscribe&hub.challenge=…&hub.verify_token=…`;
  answer 200 with the challenge when the token matches (`WHATSAPP_VERIFY_TOKEN`). Our callback is
  `/api/relay/whatsapp`; it needs a public HTTPS address (fly.io).
- **Webhook payloads:** signed with `X-Hub-Signature-256: sha256=<hex>`, HMAC-SHA256 of the raw body
  with the app secret (`WHATSAPP_APP_SECRET`). Replies at `entry[].changes[].value.messages[]`
  (`from`, `id`, `timestamp`, `type: "text"`, `text.body`); receipts at `…value.statuses[]`
  (`id`, `status` sent/delivered/read/failed, `recipient_id`, `errors[]` on failure). Deliveries
  are retried for up to 7 days, so handlers must tolerate duplicates.
- **Opt-in:** WhatsApp requires that people opt in before a business messages them; the patient
  profile records each relative's agreement (`relay_consent`) and nothing is sent without it.

## 12. Prices (verified 2026-10-26, https://dev.meta.ai/docs/pricing-rate-limits; config.yaml updated)

| Model | Unit | Price |
|---|---|---|
| `muse-spark-1.3` / `1.2` / `1.1` | per 1M tokens in / cached in / out | $1.25 / $0.15 / $4.25 |
| `muse-spark-1.3-contributor`, `1.2-contributor` | same | $0.10 / $0.002 / $0.20 (content may train Meta models) |
| `muse-wonder-1.0` | same | $4.00 / $0.20 / $20.00 |
| `sam-3.1` | image / video frame | $2.50 per 1,000 images; $0.20 per 1,000 frames, **min 50 frames per request** |
| `muse-voice-transcribe-1.0` | audio | $0.18 per hour (whole seconds) |
| `muse-image-1.0` | image | $0.01 |
| web_search tool | query | $2.50 per 1,000 |
| Baseten / Modal Muse Spark Open | per 1M tokens | $1.25 / $0.15 / $4.25 |

Rate limits (per team): Spark 1.3/1.2/1.1 and Wonder 3,000 RPM and 4M TPM; contributor variants 150 RPM and 3M TPM; `sam-3.1` 3,000 RPM; `muse-image-1.0` 150 RPM; transcribe 256 concurrent and 16,000 streams per hour; background submissions 600/min.

## 13. Data retention

- Standard mode: content is not used for training (https://dev.meta.ai/docs/pricing-rate-limits#standard-mode). Contributor mode content may be used for training.
- **ZDR** is an organisation-level setting enabled by Meta after a sales request (https://dev.meta.ai/help/policies-and-privacy/zero-data-retention). There is no request parameter. ZDR "may vary by model". Under ZDR, stateful requests (`store`/`previous_response_id`), background requests, **file uploads**, web search and contributor mode are unavailable. Content flagged for policy violations may be kept up to 2 years. Voice Transcribe ZDR is priced at parity.
- Without ZDR, use `store: false`, inline media instead of Files (or `expires_after` + immediate delete), and `DELETE /v1/responses/{id}` for anything stored.

## 14. Fixtures index (`backend/tests/fixtures/meta_api/`)

Raw JSON bodies, sanitized (secrets redacted, `encrypted_content` truncated). Streamed calls are saved as `{"events": [...]}`, one SDK event dict per SSE event.

| file | what |
|---|---|
| `models_list.json`, `models_retrieve_spark.json`, `status.json` | GET /models, /models/{id}, /status |
| `spark_responses_text_minimal.json` | Responses text, effort minimal |
| `spark_responses_json_schema.json` / `spark_chat_json_schema.json` | structured output, Responses / Chat |
| `spark_responses_incomplete.json` | `status: incomplete`, `max_output_tokens` |
| `spark_error_reasoning_none.json`, `spark_chat_error_reasoning_none.json` | 400 error envelopes |
| `spark_input_tokens_count.json` | POST /responses/input_tokens |
| `spark_responses_image_grounding.json`, `spark_responses_image_face.json` | image + json_schema |
| `spark_responses_video_inline.json`, `..._inline_fps4.json`, `..._file_id.json`, `files_upload_video.json` | video paths, upload |
| `sam_image_stream_lossless.json`, `sam_image_nonstream_one_bit.json`, `sam_image_stream_one_bit_eyebrows.json` | SAM image, stream / non-stream |
| `sam_video_stream_one_bit_eyebrows.json`, `sam_video_stream_file_id_face.json`, `sam_video_nonstream_lossless_eyebrows.json` | SAM video, 60 frames |
| `asr_*.json` | transcribe JSON, SSE, realtime events, 48 kHz error |
| `wonder_responses_json_schema.json`, `wonder_responses_previous_response_id.json` | Wonder |
| `baseten_models_list.json`, `baseten_spark_open_{text,image,video,audio}.json` | Muse Spark Open on Baseten, Chat Completions (2026-10-29) |

Synthetic media and its ground truth: `data/probe_media/` (gitignored), regenerated by `scripts/make_probe_media.py`. `media_manifest.json` holds event frames and reference transcripts.

## Differences from the build brief

1. **Spark accepts audio.** Docs list text, image, video, audio and PDF input for Spark and Wonder. Audio on `muse-spark-1.3` is "not fully supported", so use `muse-spark-1.2` or Voice Transcribe.
2. **Reasoning `none` → 400** (confirmed, both endpoints). `minimal` is the fastest level (~1.3–1.7 s for small JSON).
3. **SAM 3.1 output is a special-token text grammar, not JSON**: boxes in px with inclusive x2/y2, box-local base85 range-coded masks, frame indices with no timestamps. It needs `meta-sam-parser` (not in `pyproject.toml` yet) or a custom decoder. Tracking ids are stable (confirmed). SAM uses the Responses API (confirmed).
4. **SAM pricing**: $0.0025/image and $0.0002/frame with a 50-frame minimum, so ≥ $0.01 per video call and $0.012 per 4 s @ 15 fps clip. Config previously had $0.01/call.
5. **Spark price** is $1.25 / $4.25 (config had $1.00 / $4.00), with cached input $0.15. Muse Image is $0.01 (config had $0.04).
6. **Voice Transcribe**: the docs claim **25** supported languages; no "70+" claim was found. ZDR is an org-level sales enablement, not a tier picked per request. **Indonesian returns an empty transcript unless `languageBias: ["Indonesian"]` is sent** (observed, reproduced). Streaming is a WebSocket with the key inside the handshake frame (backend proxy required). There is also an SSE mode on the file endpoint. Input must be 16/24 kHz mono s16 WAV; phone 48 kHz audio must be resampled.
7. **Muse Wonder**: price and 1M context confirmed. No native memory API (only `previous_response_id`).
8. **Baseten**: the docs slug is `meta-models/muse-spark-open`; the `-1026` id is listed and works (2026-10-29). Structured output is **not enforced**. Reasoning is always on (default xhigh). Video is capped at 96 sampled frames and **video audio is ignored**. No PDF.
9. **Spark video** works inline as a data URL (no upload required) and honours `input_video.fps`. The default is about 2 fps, which misses fast eyebrow raises. The token-count endpoint ignores video.

10. **Spark accepts at most 5 videos per request** (observed 2026-10-26: `400 "request contains 7 videos, exceeding the maximum of 5 allowed per request"`; not in the docs). The calibration describer sends 1 rest + 2 YES + 2 NO clips.
11. **Strict structured output rejects free-form maps**: a `dict[str, str]` field fails with `"'additionalProperties' is required to be supplied and to be false."` Template slots are therefore explicit nullable fields (`name`, `relation`, `item`, `item_id`).
12. **Reasoning budgets**: at effort `low`, the prior builder used more than 1,500 output tokens and came back `incomplete` (still billed). Reasoning roles now get 3,000-4,000 `max_output_tokens`; an incomplete reply is accounted and falls back without a repair retry.
13. **Adapter choice**: the probes use the OpenAI SDK with `base_url`; the production adapters call the same OpenAI-compatible endpoints with `httpx` directly so retries (429/5xx with `Retry-After`), timeouts and Meta-specific fields (`input_video.fps`, SAM `metadata`) stay explicit. Request bodies are covered by contract tests (`backend/tests/test_providers.py`).
14. **Blind judge timeout**: observed Spark video latency (3.8-5.1 s, one 13.3 s outlier) is close to the brief's 6 s. The judge keeps `judge_timeout_s: 6` (+2 s grace); on timeout the tracker path decides alone with reduced confidence.

15. **Resolution and latency** (observed 2026-10-26, synthetic YES clip, 4 s): SAM 3.1 at 640x480 took 5.0 s, at 320x240 3.2 s (same 60 frames billed, eyebrow box still moves 17 px of 240). The Spark judge took 4.1-4.8 s at either size, with half the input tokens at 320x240 (2,390 vs 4,694 at `fps: 8`). Answer windows are now normalised to 320x240; when SAM is at least 90% sure the engine decides without waiting for the judge and attaches the judge's verdict later.

## Open questions

1. Is `meta-models/muse-spark-open-1026` live on Baseten? Run `scripts/probe_baseten.py --media` once `BASETEN_API_KEY` is set. It also checks video/audio acceptance.
2. ZDR for the hackathon team: it needs a sales request. Until then, assume Standard-mode retention (period not stated in docs).
3. `input_video.fps`: what are the documented maximum and the maximum frames or duration per Spark request? Why does `/responses/input_tokens` ignore video?
4. Indonesian without `languageBias` came back empty on synthetic espeak audio. Does it also happen with natural speech? Re-test with consented, team-recorded audio.
5. Spark video latency tail (13.3 s seen once) against `judge_timeout_s: 6`. Is a p95 needed? Should the judge use streaming or lower fps?
6. SAM video `c` was constant (0.89) across all frames for a track. Is it per-track rather than per-frame in practice?
7. Muse Image was not probed. Does generation risk adding people to scene images? (We use OpenCV drawings.)
8. A probe that would cost more than $0.50 was never needed. Untested at scale: SAM on long clips (> 1,000 frames) and Wonder at high effort.

## Probe log

Appended by `scripts/_probe_common.py`; newest last.

### 2026-10-26 16:59 UTC `probe_models`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| GET /models | `-` | HTTP 200 | 1.06s | `{}` | 0.00000 |
| GET /models/muse-spark-1.3 | `muse-spark-1.3` | HTTP 200 | 1.57s | `{}` | 0.00000 |
| GET /models/sam-3.1 | `sam-3.1` | HTTP 200 | 0.91s | `{}` | 0.00000 |
| GET /models/muse-voice-transcribe-1.0 | `muse-voice-transcribe-1.0` | HTTP 200 | 0.28s | `{}` | 0.00000 |
| GET /models/muse-wonder-1.0 | `muse-wonder-1.0` | HTTP 200 | 1.16s | `{}` | 0.00000 |
| GET /models/muse-image-1.0 | `muse-image-1.0` | HTTP 200 | 1.35s | `{}` | 0.00000 |
| GET /status (no auth) | `-` | HTTP 200 | 0.86s | `{}` | 0.00000 |
- GET /v1/models ids: muse-wonder-1.0, sam-3.1, muse-spark-1.3-contributor, muse-voice-transcribe-1.0, muse-spark-1.3, muse-image-1.0, muse-spark-1.2-contributor, muse-spark-1.2, muse-spark-1.1

### 2026-10-26 17:00 UTC `probe_spark_text`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| basic effort=minimal | `muse-spark-1.3` | ok text='ready' | 1.62s | `{"input_tokens": 15, "output_tokens": 25, "reasoning_tokens": 15}` | 0.00013 |
| effort=none (Responses) | `muse-spark-1.3` | HTTP 400 {"error": {"code": null, "message": "reasoning_effort 'none' is not supported for model 'muse-spark-1.3'. Supported values: [minimal, low, medium, high, xhigh, max]", "param": "reasoning.effort", "type": "invali | 0.96s | `{}` | 0.00000 |
| basic effort=low | `muse-spark-1.3` | ok text='ready' | 2.11s | `{"input_tokens": 15, "output_tokens": 112, "reasoning_tokens": 102}` | 0.00049 |
| json_schema Responses | `muse-spark-1.3` | ok parsed OK: {"hypotheses": [{"label": "Needs oral suctioning", "p": 0.6}, {"label": "Thirsty / dry mouth", "p": 0.25}, {"label": "Mouth or throat pain", "p": 0.15}], "langu | 1.71s | `{"input_tokens": 185, "output_tokens": 267, "reasoning_tokens": 180}` | 0.00137 |
| json_schema Chat | `muse-spark-1.3` | ok parsed OK: {"hypotheses": [{"label": "needs mouth or airway suctioning", "p": 0.5}, {"label": "mouth is dry or thirsty", "p": 0.3}, {"label": "breathing tube causes pain o | 1.32s | `{"prompt_tokens": 185, "completion_tokens": 252, "cached_tokens": 113, "reasoning_tokens": 161}` | 0.00118 |
| effort=none (Chat) | `muse-spark-1.3` | HTTP 400 {"error": {"code": null, "message": "reasoning_effort 'none' is not supported for model 'muse-spark-1.3'. Supported values: [minimal, low, medium, high, xhigh, max]", "param": "reasoning_effort", "type": "invali | 0.79s | `{}` | 0.00000 |
| max_output_tokens=16 | `muse-spark-1.3` | ok status=incomplete incomplete_details={'reason': 'max_output_tokens'} | 1.29s | `{"input_tokens": 16, "output_tokens": 16, "reasoning_tokens": 14}` | 0.00009 |
| POST /responses/input_tokens | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 212} | 0.82s | `{}` | 0.00000 |
- rate-limit headers on Responses: {"x-ratelimit-limit-requests": "3000", "x-ratelimit-remaining-requests": "2999", "x-ratelimit-limit-tokens": "4000000", "x-ratelimit-remaining-tokens": "4000000", "x-request-id": "524baee3-e02f-48ec-a8d2-6b1f8ff6b3b7"}
- rate-limit headers on Chat Completions: {"x-ratelimit-limit-requests": "3000", "x-ratelimit-remaining-requests": "2996", "x-ratelimit-limit-tokens": "4000000", "x-ratelimit-remaining-tokens": "3999381", "x-request-id": "a5d4a08c-f602-4f8c-8d4c-83244ebd19d2"}

### 2026-10-26 17:01 UTC `probe_spark_image`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| input_tokens 640x480 png | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 583} | 2.01s | `{}` | 0.00000 |
| room grounding json_schema | `muse-spark-1.3` | ok photo_frame=True people=False boxes_px={"bed": [259, 170, 602, 431], "bedside table": [84, 252, 207, 432], "photo frame": [110, 180, 176, 252]} | 2.54s | `{"input_tokens": 456, "output_tokens": 336, "reasoning_tokens": 206}` | 0.00200 |
| face eyebrows json_schema | `muse-spark-1.3` | ok out={"confidence": 0.95, "eyebrows_raised": true, "eyes_open": true} | 2.33s | `{"input_tokens": 420, "output_tokens": 145, "reasoning_tokens": 113}` | 0.00114 |
- room ground truth px boxes (approx): {"bed": [260, 170, 600, 400], "bedside table": [85, 252, 205, 400], "photo frame": [110, 180, 175, 250]}

### 2026-10-26 17:01 UTC `probe_spark_video`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| input_tokens video default fps | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 203} | 3.89s | `{}` | 0.00000 |
| input_tokens video fps=2 | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 203} | 3.97s | `{}` | 0.00000 |
| input_tokens video fps=15 | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 203} | 4.06s | `{}` | 0.00000 |
| YES clip inline data URL | `muse-spark-1.3` | ok truth=2 eyebrow raises, 1 blink out={"blinks": 0, "confidence": 0.9, "eyebrow_raises": 1, "head_nods": 0, "signal": "EYEBROW_RAISE"} | 4.15s | `{"input_tokens": 1086, "output_tokens": 329, "reasoning_tokens": 277}` | 0.00276 |
| POST /files face_nod.mp4 | `-` | ok id=file-4596767220544260 status=uploaded expires_at=1793037718 | 1.83s | `{}` | 0.00000 |
| NOD clip input_video file_id | `muse-spark-1.3` | ok truth=2 head nods out={"blinks":0,"confidence":0.8,"eyebrow_raises":0,"head_nods":1,"signal":"HEAD_NOD"} | 3.81s | `{"input_tokens": 1086, "output_tokens": 322, "reasoning_tokens": 281}` | 0.00273 |
| POST /files face_rest_blinks.mp4 | `-` | ok id=file-1786918805862401 status=uploaded expires_at=1793037724 | 3.00s | `{}` | 0.00000 |
| REST clip input_file file_id | `muse-spark-1.3` | ok truth=3 blinks only out={"blinks": 1, "confidence": 0.6, "eyebrow_raises": 0, "head_nods": 0, "signal": "NONE"} | 4.20s | `{"input_tokens": 1086, "output_tokens": 405, "cached_tokens": 6, "reasoning_tokens": 357}` | 0.00307 |
| DELETE /files/file-4596767220544260 | `-` | ok deleted=True | 4.55s | `{}` | 0.00000 |
| DELETE /files/file-1786918805862401 | `-` | ok deleted=True | 3.59s | `{}` | 0.00000 |
- clip sizes: yes=21579 B, nod=47238 B, rest=18852 B; 640x480, 15 fps, 60 frames, H.264, no audio track
- token counts for the 4 s clip: {"default fps": 203, "fps=2": 203, "fps=15": 203}; per-call upper estimate $0.0037
- ground truth: {"face_yes_eyebrows.mp4": ["eyebrow_raise", "eyebrow_raise", "blink"], "face_nod.mp4": ["head_nod_down", "head_nod_down"], "face_rest_blinks.mp4": ["blink", "blink", "blink"]}

### 2026-10-26 17:02 UTC `probe_spark_video`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| input_tokens video default fps | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 203} | 3.35s | `{}` | 0.00000 |
| input_tokens video fps=2 | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 203} | 2.90s | `{}` | 0.00000 |
| input_tokens video fps=15 | `muse-spark-1.3` | ok {"object": "response.input_tokens", "input_tokens": 203} | 10.91s | `{}` | 0.00000 |
| YES clip inline fps=4 | `muse-spark-1.3` | ok truth=2 eyebrow raises, 1 blink out={"blinks": 1, "confidence": 0.9, "eyebrow_raises": 1, "head_nods": 0, "signal": "EYEBROW_RAISE"} | 13.29s | `{"input_tokens": 2126, "output_tokens": 413, "cached_tokens": 6, "reasoning_tokens": 361}` | 0.00441 |
| YES clip inline fps=8 | `muse-spark-1.3` | ok truth=2 eyebrow raises, 1 blink out={"blinks": 1, "confidence": 0.9, "eyebrow_raises": 2, "head_nods": 0, "signal": "EYEBROW_RAISE"} | 5.14s | `{"input_tokens": 4206, "output_tokens": 325, "cached_tokens": 6, "reasoning_tokens": 273}` | 0.00663 |
- clip sizes: yes=21579 B, nod=47238 B, rest=18852 B; 640x480, 15 fps, 60 frames, H.264, no audio track
- token counts for the 4 s clip: {"default fps": 203, "fps=2": 203, "fps=15": 203}; per-call upper estimate $0.0037

### 2026-10-26 17:03 UTC `probe_sam_image`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| photo frame stream lossless+c | `sam-3.1` | ok 1 match(es): [{"object_id": 0, "box": [110, 180, 175, 250], "c": 0.8827838897705078, "mask_h": 71, "mask_w": 66, "mask_enc": "lossless"}] decoded=0 fg_px=[] errors=1 | 2.56s (1st 2.05s) | `{"input_tokens": 0, "output_tokens": 0, "images_processed": 1}` | 0.00250 |
| bed non-stream one_bit | `sam-3.1` | ok 1 match(es): [{"object_id": 0, "box": [280, 226, 601, 400], "c": null, "mask_h": 175, "mask_w": 322, "mask_enc": "one_bit"}] decoded=0 fg_px=[] errors=1 | 1.40s | `{"input_tokens": 0, "output_tokens": 0, "images_processed": 1}` | 0.00250 |
| eyebrows stream one_bit+c | `sam-3.1` | ok 1 match(es): [{"object_id": 0, "box": [222, 128, 417, 155], "c": 0.8904109597206116, "mask_h": 28, "mask_w": 196, "mask_enc": "one_bit"}] decoded=0 fg_px=[] errors=1 | 1.88s (1st 1.85s) | `{"input_tokens": 0, "output_tokens": 0, "images_processed": 1}` | 0.00250 |
- room ground truth (approx px): {"bed": [260, 170, 600, 400], "bedside table": [85, 252, 205, 400], "photo frame": [110, 180, 175, 250]}
- SSE event types (image, stream): {"response.created": 1, "response.in_progress": 1, "response.output_item.added": 1, "response.content_part.added": 1, "response.output_text.delta": 1, "response.output_text.done": 1, "response.content_part.done": 1, "response.output_item.done": 1, "response.completed": 1}
- SAM response headers: {"x-ratelimit-limit-requests": "3000", "x-ratelimit-remaining-requests": "2999", "x-request-id": "1fc1a798-fa96-4bf5-9548-3aad3b23a2db"}

### 2026-10-26 17:04 UTC `probe_sam_video`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| YES eyebrows inline stream | `sam-3.1` | ok 60 frame lines, 60 records, object ids=[0]; frames 0..59 ascending=True; obj0: y1 range 128..163 peak frames [15] c 0.89..0.89; decoded 60 masks, errors 0 | 5.04s (1st 2.67s) | `{"input_tokens": 0, "output_tokens": 0, "video_frames_processed": 60}` | 0.01200 |
| POST /files face_nod.mp4 | `-` | ok id=file-1833545754320143 | 2.62s | `{}` | 0.00000 |
| NOD face file_id stream | `sam-3.1` | ok 60 frame lines, 60 records, object ids=[0]; frames 0..59 ascending=True; obj0: cy range 272..310 peak frames [15, 40, 41]; decoded 60 masks, errors 0 | 3.21s (1st 1.44s) | `{"input_tokens": 0, "output_tokens": 0, "video_frames_processed": 60}` | 0.01200 |
| REST eyebrows inline non-stream | `sam-3.1` | ok 60 frame lines, 60 records, object ids=[0]; frames 0..59 ascending=True; obj0: y1 range 163..163 peak frames [0, 1, 2, 3]; decoded 60 masks, errors 0; text bytes 72729 | 6.00s | `{"input_tokens": 0, "output_tokens": 0, "video_frames_processed": 60}` | 0.01200 |
- truth face_yes_eyebrows.mp4: (event, peak frame) [('eyebrow_raise', 15), ('eyebrow_raise', 40), ('blink', 54)]
- truth face_nod.mp4: (event, peak frame) [('head_nod_down', 15), ('head_nod_down', 40)]
- YES eyebrows obj 0 y1 (px, median 163): [163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 160, 151, 140, 132, 128, 132, 140, 151, 160, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 162, 156, 145, 136, 130, 130, 136, 145, 155, 162, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163]
- SSE event types (video, stream): {"response.created": 1, "response.in_progress": 1, "response.output_item.added": 1, "response.content_part.added": 1, "response.output_text.delta": 60, "response.output_text.done": 1, "response.content_part.done": 1, "response.output_item.done": 1, "response.completed": 1}
- NOD face obj 0 cy (px, median 272): [272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 274, 281, 291, 301, 307, 310, 307, 301, 291, 281, 274, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 277, 286, 296, 305, 310, 310, 305, 296, 286, 277, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272, 272]
- REST eyebrows obj 0 y1 (px, median 163): [163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163, 163]

### 2026-10-26 17:06 UTC `probe_transcribe`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| EN plain | `muse-voice-transcribe-1.0` | ok WER=0.08 hyp='your daughter Asia went home to rest, she will be back at four.' | 2.84s | `{"audio_ms": 4320}` | 0.00020 |
| EN keywords | `muse-voice-transcribe-1.0` | ok WER=0.00 hyp='your daughter Aisyah went home to rest, she will be back at four.' | 1.64s | `{"audio_ms": 4320}` | 0.00020 |
| ID plain | `muse-voice-transcribe-1.0` | ok WER=1.00 hyp='' | 1.57s | `{"audio_ms": 6960}` | 0.00030 |
| ID languageBias+keywords | `muse-voice-transcribe-1.0` | ok WER=0.00 hyp='anak bapak, Aisyah, pulang dulu untuk istirahat, nanti jam empat dia kembali.' | 1.92s | `{"audio_ms": 6960}` | 0.00030 |
| two voices DIARIZATION | `muse-voice-transcribe-1.0` | ok WER=0.03 turns=[["A", 60, 3260, "Good morning. Did you sleep at all last night?"], ["B", 4300, 9260, "She slept a little after midnight. The nurse nurse gave her something for pain."], ["A", 9740, 12620, "Okay, let us | 3.54s | `{"audio_ms": 13120}` | 0.00065 |
| two voices ENDPOINTING SSE | `muse-voice-transcribe-1.0` | ok content-type=text/event-stream events={"speechStart": 4, "transcript": 26, "speechEnd": 4, "speechComplete": 4} | 2.90s | `{"audio_ms": 13047}` | 0.00065 |
| EN DIARIZATION text/plain | `muse-voice-transcribe-1.0` | ok body='A:your daughter Azia went home to rest, she will be back at four' | 1.67s | `{"audio_ms": 4302}` | 0.00020 |
| EN 48 kHz WAV | `muse-voice-transcribe-1.0` | HTTP 400 {"sessionId":"voyager/transcribe/CBD30AAB9E1A446ABDA6AD2C498C9C37","error":{"code":null,"param":null,"type":"invalid_request_error","message":"Unsupported WAV format: channels=1, sampleRate=48000, bitsPerSample= | 0.92s | `{}` | 0.00000 |
| realtime WS ID ENDPOINTING | `muse-voice-transcribe-1.0` | ok close=1000 first_partial_at=2.908s audio_sent_by=9.39s final_at=8.748s WER=0.00 events={"ack": 1, "speechStart": 1, "transcript": 13, "speechEnd": 1, "speechComplete": 1} hyp='anak bapak, Aisyah, pulang dulu untuk ist | 9.76s | `{"audio_ms": 7900}` | 0.00035 |
- truth turns: A / B / A (Good morning. Did you sleep at all last night? | She slept a little after midnight. The nurse gave her something for pain. | Okay. Let us check the breathing tube in an hour.)

### 2026-10-26 17:07 UTC `probe_transcribe`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| ID plain | `muse-voice-transcribe-1.0` | ok WER=1.00 hyp='' | 3.03s | `{"audio_ms": 6960}` | 0.00030 |
| ID languageBias+keywords | `muse-voice-transcribe-1.0` | ok WER=0.00 hyp='anak bapak, Aisyah pulang dulu untuk istirahat nanti jam empat dia kembali' | 1.91s | `{"audio_ms": 6960}` | 0.00030 |
| ID languageBias only | `muse-voice-transcribe-1.0` | ok WER=0.08 hyp='anak bapak, ayah, pulang dulu untuk istirahat, nanti jam empat dia kembali,' | 2.05s | `{"audio_ms": 6960}` | 0.00030 |
| ID languageBias [Indonesian, English] | `muse-voice-transcribe-1.0` | ok WER=0.25 hyp='pulang dulu untuk istirahat, nanti jam empat dia kembali.' | 1.87s | `{"audio_ms": 6960}` | 0.00030 |
| ID plain ENDPOINTING | `muse-voice-transcribe-1.0` | ok WER=1.00 hyp='' | 1.55s | `{"audio_ms": 6960}` | 0.00030 |

### 2026-10-26 17:07 UTC `probe_wonder`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| extract facts json_schema | `muse-wonder-1.0` | ok out={"facts": [{"category": "family", "fact": "Daughter Aisyah went home to rest; will return at 4"}, {"category": "other", "fact": "Slept a little after midnight"}, {"category": "other", "fact": "Nurse gave something | 1.93s | `{"input_tokens": 94, "output_tokens": 165, "reasoning_tokens": 71}` | 0.00368 |
| store=true turn 1 | `muse-wonder-1.0` | ok id=resp_6adf88e4450812b966b246d9 out='noted' | 1.74s | `{"input_tokens": 24, "output_tokens": 17, "reasoning_tokens": 6}` | 0.00044 |
| previous_response_id turn 2 | `muse-wonder-1.0` | ok out='PELANGI' | 4.13s | `{"input_tokens": 48, "output_tokens": 21, "reasoning_tokens": 8}` | 0.00061 |
| fresh call, no chaining | `muse-wonder-1.0` | ok out='unknown' | 1.32s | `{"input_tokens": 28, "output_tokens": 50, "reasoning_tokens": 40}` | 0.00111 |
| DELETE /responses/{id} | `muse-wonder-1.0` | ok HTTP 200 body={"id":"resp_6adf88e4450812b966b246d9","object":"response.deleted","deleted":true} | 1.67s | `{}` | 0.00000 |
- Wonder rate-limit headers: {"x-ratelimit-limit-requests": "3000", "x-ratelimit-remaining-requests": "2999", "x-ratelimit-limit-tokens": "4000000", "x-ratelimit-remaining-tokens": "4000000", "x-request-id": "080a8431-acd8-4c19-bdd2-012e7e718b74"}

### 2026-10-29 03:08 UTC `probe_baseten`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| GET /models | `-` | ok muse ids=['meta-models/muse-spark-open', 'meta-models/muse-spark-open-1026'] | - | `{}` | 0.00000 |
| text effort=low | `meta-models/muse-spark-open-1026` | ok content='ready' reasoning_chars=420 | 1.44s | `{"prompt_tokens": 152, "completion_tokens": 101, "cached_tokens": 128, "reasoning_tokens": 90}` | 0.00048 |
| image data URL | `meta-models/muse-spark-open-1026` | ok content='The room contains a hospital bed and a three-drawer nightstand dresser.\n\nNo people are present in the room.' reasoning_chars=1019 | 4.48s | `{"prompt_tokens": 553, "completion_tokens": 250, "cached_tokens": 128, "reasoning_tokens": 216}` | 0.00161 |
- Baseten headers: {"x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "2000000", "x-ratelimit-remaining-requests": "50", "x-ratelimit-remaining-tokens": "2000000"}
- Baseten headers: {"x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "2000000", "x-ratelimit-remaining-requests": "50", "x-ratelimit-remaining-tokens": "2000000"}

### 2026-10-29 03:08 UTC `probe_baseten`

| call | model | status | latency | usage | est. USD |
|---|---|---|---|---|---|
| GET /models | `-` | ok muse ids=['meta-models/muse-spark-open', 'meta-models/muse-spark-open-1026'] | - | `{}` | 0.00000 |
| text effort=low | `meta-models/muse-spark-open-1026` | ok content='ready' reasoning_chars=665 | 1.25s | `{"prompt_tokens": 152, "completion_tokens": 142, "cached_tokens": 128, "reasoning_tokens": 131}` | 0.00065 |
| image data URL | `meta-models/muse-spark-open-1026` | ok content='The room contains a hospital bed and a three-drawer nightstand; there are no people present.' reasoning_chars=337 | 4.10s | `{"prompt_tokens": 553, "completion_tokens": 100, "cached_tokens": 128, "reasoning_tokens": 70}` | 0.00098 |
| video data URL | `meta-models/muse-spark-open-1026` | ok content='1' reasoning_chars=459 | 4.78s | `{"prompt_tokens": 714, "completion_tokens": 129, "cached_tokens": 128, "reasoning_tokens": 118}` | 0.00130 |
| audio data URL | `meta-models/muse-spark-open-1026` | ok content='Your dog raised me. I went home to rest. She will be back at four.' reasoning_chars=590 | 5.35s | `{"prompt_tokens": 211, "completion_tokens": 153, "cached_tokens": 128, "reasoning_tokens": 125}` | 0.00077 |
- Baseten headers: {"x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "2000000", "x-ratelimit-remaining-requests": "50", "x-ratelimit-remaining-tokens": "2000000"}
- Baseten headers: {"x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "2000000", "x-ratelimit-remaining-requests": "50", "x-ratelimit-remaining-tokens": "2000000"}
- Baseten headers: {"x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "2000000", "x-ratelimit-remaining-requests": "50", "x-ratelimit-remaining-tokens": "2000000"}
- Baseten headers: {"x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "2000000", "x-ratelimit-remaining-requests": "50", "x-ratelimit-remaining-tokens": "2000000"}
