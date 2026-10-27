# Architecture

```mermaid
flowchart LR
  subgraph Browser["Browsers (HTTPS, one origin)"]
    P["/patient/:sid<br/>phone on the bed rail<br/>speech, camera, Y/N keys in mock"]
    C["/caregiver/:sid<br/>bars, evidence chips, trail,<br/>overrides, alarm"]
  end
  subgraph Backend["Backend (FastAPI, owns all state and every model call)"]
    WS["WebSocket /ws/sessions/:sid<br/>full snapshot after every change"]
    S["Session orchestrator<br/>explicit state machine"]
    E["Decision engine<br/>bounded priors, EIG, Bayes,<br/>confirm gating, spelling"]
    PER["Perception<br/>ffmpeg, SAM boxes + DTW,<br/>blind judge, fusion, triple YES"]
    CTX["Context<br/>evidence store S/T/E/M/H"]
    MEM["Memory<br/>curator + selector,<br/>caregiver approval"]
    SAF["Safety<br/>sensitive detector,<br/>advice validators"]
    DB[("SQLite + JSONL logs<br/>./data, gitignored")]
  end
  subgraph Models["Models (chosen per mode and budget)"]
    SPARK["Muse Spark 1.3<br/>describer, scene, priors,<br/>questions, judge, completer"]
    SAM["SAM 3.1<br/>video tracking"]
    ASR["Muse Voice Transcribe"]
    WONDER["Muse Wonder<br/>memory curator"]
    OPEN["Muse Spark Open on Baseten<br/>privacy mode"]
    LOCAL["On-device optical flow<br/>mock + privacy fallback"]
  end
  P <--> WS
  C <--> WS
  P -- "answer clip (prompt id only)" --> PER
  C -- "events, transcript, overrides" --> S
  WS --- S
  S --> E
  S --> PER
  S --> CTX
  S --> SAF
  S --> DB
  CTX --> MEM
  PER --> SAM
  PER --> SPARK
  PER --> LOCAL
  CTX --> SPARK
  CTX --> ASR
  MEM --> WONDER
  S -. privacy .-> OPEN
```

## One message, step by step

```mermaid
sequenceDiagram
  autonumber
  participant Pt as Patient phone
  participant S as Session
  participant Spark as Muse Spark
  participant E as Engine
  participant Per as Perception
  participant CG as Caregiver view
  Pt->>S: start (tap) + room snapshot
  S->>Spark: scene facts (S#)
  S->>Spark: prior builder (evidence S/T/E/M/H, candidate messages)
  Spark-->>S: multipliers citing evidence + up to 3 template messages
  S->>E: bounded prior (cap 0.40, floor 0.005, other >= 0.08)
  loop until one message is very likely
    E-->>S: question with the highest EIG - lambda * words
    S-->>Pt: speak question
    Pt->>Per: 4 s clip (no question text)
    Per->>Per: SAM 3.1 boxes -> DTW vs calibrated templates
    Per->>Spark: blind judge (clip + signal description only)
    Per-->>S: fused YES / NO / UNCLEAR / EMERGENCY
    S->>E: Bayes update with calibrated error rates
    S-->>CG: snapshot (bars, chips, trail, overlay)
  end
  E-->>S: confirm top message (p >= 0.70)
  S-->>Pt: "Is this your message: ...?"
  Pt->>Per: YES -> p >= 0.95
  S-->>Pt: speak the message in first person
  S-->>Pt: "Did I say it right?"
  S-->>CG: "Message from patient (confirmed)"
```

## Modules

| Path | What it does |
|---|---|
| `backend/app/engine/` | taxonomy v1 (EN/ID), priors with bounds (`priors.py`), closed-form EIG (`eig.py`), Bayes update (`posterior.py`), question pool and LLM-question validation (`questions.py`), the per-message policy (`policy.py`), spelling (`spelling.py`), personal base rates (`personal.py`), pain refinement (`refine.py`), template validation (`instantiation.py`) |
| `backend/app/sessions/` | state machine (`state_machine.py`), session orchestrator (`session.py`), session manager and WebSocket fan-out (`manager.py`), simulated patient (`simulated.py`), JSONL logs (`log.py`) |
| `backend/app/perception/` | ffmpeg normalisation (`media.py`), SAM box features (`features.py`), DTW (`dtw.py`), fusion (`fusion.py`), calibration wizard backend (`calibration.py`), answer pipeline (`pipeline.py`) |
| `backend/app/providers/` | interfaces (`base.py`), Meta Model API (`meta_api.py`), Baseten (`baseten.py`), Modal SAM (`modal_sam.py`), on-device tracker (`local.py`), mock (`mock.py`), selection by mode and budget (`registry.py`), structured calls with repair and fallback (`llm.py`), cost (`cost.py`) |
| `backend/app/roles.py` + `backend/app/prompts/*.md` | every model role: prompt (versioned), inputs, schema, fallback |
| `backend/app/context/`, `backend/app/memory/` | evidence store; Wonder curator, provenance validation, learning curve |
| `backend/app/safety/` | sensitive-topic detector (EN/ID keywords + LLM layer), advice and wording validators |
| `backend/app/relay/` | family relay agent (offer, approval, send, receipts, reply triage, follow-up) and its channels: WhatsApp Cloud API, or a simulated relative |
| `frontend/` | Vite + React + TypeScript views |
| `sim/` | engine simulation (`make sim`) |
| `scripts/` | API probes, live check, detector evaluation, letter statistics, synthetic media |

## Modes and where each role runs

| Role | Mock | Live | Privacy (partner) | Privacy (on-premises) |
|---|---|---|---|---|
| Spark text roles (priors, questions, completions, sentences, sensitive classifier) | rule-based mock | Muse Spark 1.3 | Muse Spark Open (Baseten or Modal) | Muse Glimmer on the hospital's server |
| Spark media roles (describer, framing, scene, blind judge) | mock | Muse Spark 1.3 | Muse Spark Open | stays on-device (mock describer; judge off) |
| Tracker | on-device optical flow | SAM 3.1 | self-hosted SAM 3.1 if configured, else on-device | same |
| Room transcript | typed lines | Muse Voice Transcribe | Muse Spark Open audio input | off (typed lines) |
| Memory curator | rule-based mock | Muse Wonder | Muse Spark Open | Muse Glimmer |

The budget guard can drop any live or privacy session to mock mid-way (90% of the budget).

## In-browser demo

`backend/app/browser.py` wraps the same `Session` for Pyodide (Python compiled to WebAssembly). The
hosted demo loads it in a Web Worker with numpy, pydantic, pyyaml and sqlite3 from the Pyodide CDN,
unpacks the backend sources (`scripts/build_pyodide_bundle.py`) and swaps the WebSocket for
`postMessage`. Same engine, same safety checks, mock providers, no server, no camera, no keys.

## Design decisions

- **The LLM supplies intuition; code decides.** Every model output is a proposal: multipliers are
  snapped to a fixed set, must cite evidence and are clipped; new messages come only from templates;
  questions are validated; the choice of question and the decision to speak are plain math.
- **Blind perception.** The judge never sees the question, so it cannot answer for the patient.
- **Same code in every mode.** Mock, live and privacy share the session, engine and roles; only the
  provider behind each role changes. The budget guard can switch a live session to mock mid-way.
- **One snapshot, two screens.** The backend pushes the whole session view; the patient screen
  simply never renders the probabilities.
