// Shapes of the backend payloads (see docs/PROTOCOL.md and docs/snapshot_example.json).

export type Lang = 'en' | 'id';
export type Honorific = 'Bapak' | 'Ibu' | 'Anda';

export type SessionState =
  | 'IDLE'
  | 'CONTEXT_REFRESH'
  | 'ASKING'
  | 'LISTENING'
  | 'PROCESSING'
  | 'CONFIRMING'
  | 'SPEAKING'
  | 'POST_CHECK'
  | 'DONE'
  | 'EMERGENCY'
  | 'PAUSED'
  | 'SPELLING'
  | 'CAREGIVER_NEEDED';

export type AnswerValue = 'yes' | 'no' | 'unclear' | 'emergency' | 'none';

export type PromptKind =
  | 'ask'
  | 'confirm'
  | 'offer_spell'
  | 'spelling'
  | 'post_check'
  | 'refine_offer'
  | 'worse'
  | 'message';

export interface Question {
  id: string;
  kind: string;
  text_en: string;
  text_id: string;
  text: string;
  yes_ids: string[];
  target_id?: string | null;
  evidence_ids?: string[];
  group?: string[];
}

export interface Prompt {
  id: string;
  kind: PromptKind;
  stage: string;
  sub: 'letter' | 'checkpoint' | 'word' | null;
  text: string;
  text_en: string;
  question: Question | null;
  group: string[];
  word: string | null;
  rephrased: boolean;
  asked_at?: string;
}

export interface Chip {
  evidence_id: string;
  factor: number;
  reason: string;
}

export interface Hypothesis {
  id: string;
  text_en: string;
  text_id: string;
  p: number;
  prior: number | null;
  chips: Chip[];
  bounded: string | null;
  personal: number | null;
  source: string;
  urgent: boolean;
}

export interface SourceOutput {
  answer?: string;
  ok?: boolean;
  top?: string;
  p?: number;
  probs?: Record<string, number>;
  error?: string;
  observed?: string;
  observed_movement?: string;
  pending?: boolean;
  [key: string]: unknown;
}

export interface TrailItem {
  n: number;
  prompt_id: string;
  kind: PromptKind;
  stage: string;
  text: string;
  text_en: string;
  answer: AnswerValue | string;
  confidence: number;
  overridden: boolean;
  source: string;
  rephrased: boolean;
  sources: Record<string, SourceOutput>;
  group: string[];
  at?: string;
  top_after?: Hypothesis[];
}

export interface Spelling {
  text: string;
  top: [string, number][];
  completions: [string, number][];
}

export type MessageStatus = 'speaking' | 'needs_verification' | 'confirmed' | 'retracted';

export interface PatientMessage {
  id: string;
  hypothesis_id: string | null;
  text_en: string;
  text_id: string;
  source: string;
  status: MessageStatus;
  urgent: boolean;
  sensitive: boolean;
  categories: string[];
  questions: number;
  at?: string;
  /** A caregiver tapped "I'm coming". */
  acknowledged_at?: string | null;
  /** Times the phone has said it. */
  announced?: number;
  /** Still unacknowledged after every repeat. */
  escalated?: boolean;
}

export type EvidenceKind = 'scene' | 'transcript' | 'event' | 'memory' | 'history';

export interface Evidence {
  id: string;
  kind: EvidenceKind | string;
  text: string;
  at: string;
  ref?: string;
  minutes_ago: number | null; // null when the evidence has no time
  speaker?: string;
  event_kind?: string;
  source_type?: string;
}

export interface Alert {
  kind: 'emergency' | 'urgent' | 'sensitive' | string;
  text: string;
  at: string;
  message_id?: string;
  source?: string;
}

export interface SignalSpec {
  body_part: string;
  motion: string;
  sam_prompt?: string;
  description: string;
}

export interface Signals {
  yes?: SignalSpec;
  no?: SignalSpec;
  distinct?: boolean;
  notes?: string;
}

export interface OverlayObject {
  id: number | string;
  box: [number, number, number, number];
  score?: number;
}

export interface Overlay {
  provider: string;
  prompt: string;
  frames: { t: number; objects: OverlayObject[] }[];
  prompt_id?: string;
}

export interface ModeInfo {
  requested: string;
  effective: 'mock' | 'live' | 'privacy' | string;
  reason: string;
}

export interface LlmCall {
  role: string;
  provider: string;
  model: string;
  latency_ms: number;
  usd?: number;
  fallback: boolean;
  error?: string | null;
  repaired?: boolean;
}

export type BudgetLevel = 'ok' | 'warn' | 'mock';

export interface Budget {
  spent_usd: number;
  max_usd: number;
  fraction: number;
  level: BudgetLevel | string;
}

export interface Snapshot {
  session_id: string;
  patient: { id: string; display_name: string; language: Lang; honorific: Honorific };
  mode: ModeInfo;
  state: SessionState;
  stage: string;
  prompt: Prompt | null;
  listening: boolean;
  posterior: Hypothesis[];
  other_p: number | null;
  questions: number;
  max_questions: number;
  trail: TrailItem[];
  spelling: Spelling | null;
  message: PatientMessage | null;
  messages: PatientMessage[];
  /** Spoken messages no caregiver has acknowledged yet, oldest first. */
  pending_ack?: PatientMessage[];
  /** Family relay: messages carried to relatives on WhatsApp and their replies. */
  relays?: Relay[];
  evidence: Evidence[];
  caregiver_reason: string | null;
  caregiver_text: string | null;
  alerts: Alert[];
  emergency: boolean;
  signals: Signals;
  calibration: {
    skipped: boolean;
    error_rates: { a: number; b: number };
    accuracy: Record<string, number>;
  };
  overlay: Overlay | null;
  llm_calls: LlmCall[];
  message_index: number;
  ended: boolean;
  budget: Budget;
}

export interface ServerEvent {
  type: 'alarm' | 'alert' | 'sensitive' | 'error' | 'reminder' | 'acknowledged' | string;
  /** For a reminder: the words to say again, only when the phone is idle. */
  text?: string | null;
  text_en?: string;
  message_id?: string;
  urgent?: boolean;
}

export type ServerMessage =
  | { type: 'snapshot'; snapshot: Snapshot; event?: ServerEvent }
  | { type: 'pong' }
  | { type: 'error'; error: string };

export type OverrideAction =
  | 'yes'
  | 'no'
  | 'unclear'
  | 'skip'
  | 'spell'
  | 'pause'
  | 'resume'
  | 'emergency'
  | 'ack_emergency'
  | 'ack_sensitive'
  | 'ack_sensitive_silent'
  | 'new_message'
  | 'refresh_context'
  | 'end';

export type ClientMessage =
  | { type: 'start' }
  | { type: 'spoken'; prompt_id: string }
  | { type: 'answer'; prompt_id: string; answer: AnswerValue }
  | { type: 'override'; action: OverrideAction }
  | { type: 'ping' };

export type RelayStatus =
  | 'awaiting_approval'
  | 'sending'
  | 'sent'
  | 'delivered'
  | 'read'
  | 'review'
  | 'replied'
  | 'read_to_patient'
  | 'no_reply'
  | 'cancelled'
  | 'failed';

export interface Relay {
  id: string;
  message_id: string;
  to: string;
  relation: string;
  /** Masked, for example "+62 ••• 7890". */
  phone: string;
  patient_text: string;
  status: RelayStatus;
  simulated: boolean;
  send_kind: string | null;
  reply: {
    text: string;
    spoken: string;
    needs_review: boolean;
    reason: string;
    at: string;
    read_at: string | null;
  } | null;
  events: { at: string; kind: string; text?: string }[];
  created: string;
}

export interface FamilyMember {
  name: string;
  relation: string;
  /** WhatsApp number for the family relay; used only with `relay_consent`. */
  phone?: string | null;
  relay_consent?: boolean;
}

export interface PatientProfile {
  display_name: string;
  language: Lang;
  honorific: Honorific;
  family: FamilyMember[];
  notes: string[];
  spiritual_preference: string | null;
  simulation_consent: boolean;
}

export interface Patient extends PatientProfile {
  id: string;
  created_at?: string;
  calibrated?: boolean;
}

export interface CalibrationSummary {
  mode?: string;
  skipped: boolean;
  description: Signals & { yes: SignalSpec; no: SignalSpec };
  accuracy: Record<string, number>;
  error_rates: { a: number; b: number };
  ok: boolean;
  suggestion: string | null;
  clips?: Record<string, number>;
}

export interface FramingResult {
  face_visible: boolean;
  upper_body_visible: boolean;
  lighting_ok: boolean;
  advice: string;
}

export interface PublicConfig {
  engine: { tau_confirm: number; finalize_threshold: number; max_questions: number };
  perception: {
    window_s: number;
    idle_watch_interval_s?: number;
    window_delay_ms: number;
    width: number;
    height: number;
    fps: number;
  };
  speech: { rate?: number; voices?: Record<string, string> };
  flags: Record<string, boolean>;
  mode: string;
  privacy_default: boolean;
  language: Lang;
  keep_clips_for_evaluation: boolean;
  budget: Budget;
  passcode_required: boolean;
  /** This browser sent the right passcode (public deployment). */
  unlocked?: boolean;
  scenarios: { id: string; title: string }[];
  event_kinds: string[];
  models: Record<string, string>;
}

export interface MemoryEntry {
  id: string;
  text: string;
  category: string | null;
  source_type: 'caregiver' | 'transcript' | 'patient_confirmed' | string;
  source_ref: string | null;
  created_at: string;
  last_used_at: string | null;
  status: 'approved' | 'retired' | string;
}

export interface MemoryOp {
  id: string;
  op: 'add' | 'update' | 'retire';
  entry_id: string | null;
  text: string | null;
  category: string | null;
  source_refs: { id: string; ref: string }[];
  reason: string | null;
  status: string;
  created_at: string;
}

export interface LearningPoint {
  session_id: string;
  started_at: string | null;
  messages: number;
  mean_questions: number;
}

export interface MemoryView {
  entries: MemoryEntry[];
  ops: MemoryOp[];
  learning_curve: LearningPoint[];
}

export interface SimResult {
  strategy: string;
  noise: number;
  context: 'none' | 'weak' | 'strong' | string;
  trials: number;
  mean_q: number | null;
  success_rate: number;
  wrong_rate?: number;
  handover_rate?: number;
}

export interface SimResults {
  trials: number;
  seed: number;
  label: string;
  results: SimResult[];
}
