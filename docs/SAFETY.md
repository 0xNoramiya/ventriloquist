# Safety design

Ventriloquist is an augmentative and alternative communication (AAC) aid. It helps an awake patient
who cannot speak say what they want to say, and routes it to people. **It is not a medical device.**
It does not replace the nurse call system, monitors or clinical assessment, and it has not been
clinically validated. It never diagnoses, recommends treatment, interprets vital signs or answers
medical questions.

The name carries the main risk. In facilitated communication, a well-meaning helper ends up
authoring the words attributed to a patient. A system that guesses messages can do the same thing
faster. In Ventriloquist the patient is the ventriloquist and the phone is only the voice. The rules
below exist to keep it that way, and each one is enforced in code and covered by tests.

| # | Rule | Where it lives | Tests |
|---|---|---|---|
| 1 | Not a medical device | UI footer on every page, README, this file | n/a |
| 2 | No advice | role prompts (`backend/app/prompts/_common.md`); output validators reject dosages, drug names, "you should", diagnosis words (`safety/advice.py`) and fall back safely | `test_llm_questions_validated`, `test_sensitive_or_uncited_instantiations_rejected` |
| 3 | The AI never proposes sensitive messages | templates are the only way to add messages; every LLM message, question, word completion and sentence passes the EN/ID keyword detector (`safety/sensitive.py`, about 1,260 phrases in six categories) | `test_no_generated_hypothesis_is_sensitive` (property test), `test_completions_never_offer_sensitive_words` |
| 3 | Spelled sensitive messages go to a person | keywords, plus the LLM classifier in live mode, on every spelled word and message; the caregiver sees "Verify in person with the patient" at once; nothing is spoken until a caregiver acknowledges; the stored message text is redacted and never reaches memory | `test_sensitive_spelled_message_held_for_caregiver`, `test_sensitive_ack_speaks_then_post_checks` |
| 4 | Confirm before speaking | the policy finalizes only after a confirmation answered YES that lifts the posterior to at least 0.95; the state machine only reaches SPEAKING from PROCESSING (finalized) or CAREGIVER_NEEDED (acknowledged) | `test_confirm_gating` (property test), `test_nothing_spoken_before_confirmation_yes`, `test_speaking_only_reachable_from_processing_or_caregiver` |
| 5 | Verify after speaking | "Did I say it right?" after every spoken message; NO marks it retracted on the caregiver screen and resumes; two retractions hand over to the caregiver | `test_post_speak_retraction`, `test_post_speak_retraction_resumes` |
| 6 | Emergency path always active | triple YES within 4 s (detector repetition count, blind judge class, or keyboard E), or the caregiver button, from any state: full-screen alarm, loud tone, "The patient needs help now."; false alarms are accepted | `test_emergency_from_every_state`, `test_emergency_reachable_from_every_state`, `test_triple_yes_observation_triggers_alarm`, `test_emergency_bypasses_engine` |
| 7 | Blind judging | the Spark judge receives only the clip and the patient's calibrated signal description (`roles.judge`); clips are uploaded with a prompt id, never the question text | `test_meta_vision_language_request_and_response` checks the request body |
| 8 | Bounded priors | before any answer: no message above 0.40, "something else" at least 0.08, every message at least 0.005; LLM multipliers only from {0.25, 0.5, 2, 4}, each must cite evidence, product clipped to [0.1, 8]; personal factor clipped to [0.5, 3] | `test_bounds_hold_against_adversarial_inputs`, `test_build_prior_bounded_with_adversarial_multipliers`, `test_uncited_multiplier_forced_to_one` |
| 9 | Fatigue and consistency | at most 10 questions per message (confirmations and re-asks count); 3 unclear answers in a row, or 2 confirmation NOs on messages above 0.9, pause with "Responses unclear. Please check with the patient in person."; no condition is ever named; spelling has its own caps (80 prompts, 3 sentence rounds) | `test_question_cap`, `test_two_high_confirmation_nos_pause`, `test_unclear_three_times_hands_to_caregiver`, `test_spelling_loop_is_capped` |
| 10 | Human override everywhere | caregiver YES / NO / UNCLEAR, skip, spell, pause, resume, new message, end; overrides are logged and carry a badge in the trail; while the alarm is active only acknowledge and end are accepted | `test_caregiver_override_applies_and_is_badged`, `test_monkey.py` (random patient answers and caregiver actions in strict mode: no invalid transition, nothing spoken without a confirmation YES or acknowledgement; 300 seeds checked, 40 in the default suite) |
| 11 | Transparency | the caregiver view shows the top messages with probabilities, evidence chips for each prior, the question trail with per-source detector outputs, rejected model proposals and every model call | `docs/PROTOCOL.md` snapshot fields |
| 12 | Privacy | fictional patients and consenting actors only (the API refuses a profile without the simulation box); data stays in `./data` (gitignored); raw clips are deleted after processing unless "keep for evaluation" is on; "Delete patient" wipes the database rows, logs and media; no face recognition; scene prompts forbid identifying people; `store: false` on every Meta request | `test_delete_patient_wipes_everything` |
| 13 | Memory hygiene | memory only holds facts entered by a caregiver, said in the room (with a transcript citation) or confirmed by the patient; Muse Wonder only proposes, a caregiver approves each operation; every entry has provenance and a delete button; sensitive and clinical facts are rejected | `memory/curator.py` validators |

## What leaves the device

| Mode | Leaves the machine running the backend |
|---|---|
| Mock | nothing |
| Live | answer clips, room snapshots and room audio go to the Meta Model API with `store: false`; prompts carry evidence text and the profile's first names |
| Privacy | text-only roles go to Muse Glimmer on the hospital's own server if `LOCAL_LLM_URL` is set; roles with images or video go to Muse Spark Open on Baseten (synchronous Model APIs fall under Baseten's zero-data-retention policy) if a key is set, otherwise they stay on-device; SAM runs on a self-hosted endpoint if configured, otherwise the on-device optical-flow tracker. With Glimmer on-prem and no Baseten key, nothing leaves the building. With neither, privacy mode stays fully on-device with mock models |

Meta offers zero data retention as an organisation-level setting enabled on request; there is no
per-request flag (docs/API_NOTES.md section 13). A hospital deployment would need it, plus a data
protection assessment: Indonesia's Personal Data Protection Law (UU No. 27/2022) treats health data
as specific personal data.

## Known limits

- The detector has only been evaluated on synthetic cartoon clips (`docs/DETECTOR_EVAL_SYNTHETIC.md`).
  Real patients with sedation, delirium, weakness, poor lighting or a taped face will be harder.
- The sensitive keyword lists need review by ICU clinicians and native Indonesian speakers.
- Base rates are starting guesses, not clinical data.
- The simulation results in `docs/EVAL.md` compare strategies under simulated patients; they are not
  clinical evidence.
- Clinical use would need ethics approval, a clinical study and regulatory review.
