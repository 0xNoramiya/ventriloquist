# Demo video script (3:00)

Show only features built during the hackathon. Label it on screen: "Simulation with a consenting
actor. Not a medical device." English captions throughout; show the Indonesian toggle once. If any
answer in the recording came from a caregiver override, keep the override badge visible.

Setup: actor in a hospital-style bed with a simulated tube taped at the mouth (no real equipment in
the airway), phone on a bed-rail mount facing them, laptop with the caregiver view beside the bed.
A framed family photo on the bedside table. A second person plays the nurse.

| Time | Picture | Words (voice-over or caption) |
|---|---|---|
| 0:00-0:15 | Actor in bed, tube taped, tries to speak, nothing. Nurse leans in, guessing. Cut to title card. | Caption: "A 2025 review reports that only about 5% of the messages ventilated patients try to convey are correctly understood by healthcare providers (Çelebi and Öztepe Yeşilyurt, Cyprus J Med Sci 2025)." Title: **Ventriloquist. The patient does the talking. The phone just moves its lips.** VO: "In a bad system the machine puts words in the patient's mouth. Here the patient is the ventriloquist. The phone is only the voice." |
| 0:15-0:35 | Calibration wizard on the phone. Actor raises eyebrows three times for YES, squeezes eyes for NO. Caregiver screen: Muse Spark's description "raises both eyebrows" and the SAM prompt "eyebrows"; SAM 3.1 boxes tracking the brows on the clip. | VO: "No fixed gestures. The patient shows whatever they can do. Muse Spark names the movement, SAM 3.1 tracks it." |
| 0:35-1:20 | Nurse says "Your daughter Aisyah went home to rest, she'll be back at four" (transcript chip T1 appears). Session starts. Phone asks aloud, "Is it about your body?" Actor: eyebrows still, eyes shut = NO. Bars move. "Is it about Aisyah?" YES. Caregiver screen: chips S1 photo, T1 transcript, E3 visitor left; SAM overlay on the last clip. "Is this your message: I want to see my daughter, Aisyah?" YES. Phone speaks it. "Did I say it right?" YES. | VO: "Muse Spark reads the room: the nurse's words, the photo the patient keeps looking at, the visitor who just left. It can only nudge the odds, and every nudge cites its evidence. The engine asks the one question that splits the possibilities best, and it never speaks before the patient confirms." |
| 1:20-1:40 | Second message. Wrong guess: "Is this your message: I'm cold?" NO. "Do you want to spell it?" YES. Letter groups highlighted; K, U, C; "Is your word KUCING?" YES; "Do you mean: Who is feeding my cat?" YES. Phone speaks it. | VO: "When it's not on the list, the patient spells it, with completions doing the heavy lifting." |
| 1:40-1:55 | Actor raises eyebrows three times fast. Laptop goes red, loud tone, "The patient needs help now." Nurse acknowledges. | VO: "Three quick YES signals raise the alarm from any screen, any time." |
| 1:55-2:20 | Memory page: Muse Wonder's proposed facts with provenance ("Daughter Aisyah usually visits after work", cited to transcript T4), nurse approves one. Learning curve chart: fewer questions per message over sessions. A later session resolves "I want to see Aisyah" in two questions. | VO: "Muse Wonder curates a memory from the whole stay. A caregiver approves every fact, and every fact shows where it came from." |
| 2:20-2:40 | Settings: privacy toggle, the "What leaves this device" panel. Session runs on Muse Spark Open via Baseten. | VO: "Privacy mode runs the same pipeline on Muse Spark Open, an open-weight model on Baseten." |
| 2:40-3:00 | Architecture diagram, then the simulation chart (EIG with context vs a fixed-order board). Back to the actor, smiling at the phone. | Caption: "Simulation, not clinical evidence." VO: "Built in Indonesia for ICU patients who are awake and unheard. The patient does the talking. The phone just moves its lips." |

## Shot checklist

- Front camera at about 50 cm, face and shoulders in frame, soft light from the side (not behind).
- Record the caregiver screen with a screen recorder at 1440x900; record the phone screen too.
- Use the mock scenario `daughter` for rehearsal; switch to live mode for the real take.
- Keep the actor's face out of any committed file: recordings stay in `data/` (gitignored).

## X post draft

> An ICU patient on a ventilator can't speak. A 2025 review reports that only about 5% of the messages they try to convey are correctly understood by healthcare providers.
>
> Ventriloquist turns a phone into their voice: it asks the single yes/no question that narrows things most, reads whatever movement the patient can make (eyebrows, a blink, a finger), and only speaks after the patient confirms.
>
> The patient does the talking. The phone just moves its lips.
>
> Built on Muse Spark, SAM 3.1, Muse Wonder and Muse Spark Open for #MetaAIHackathon. [video] [repo]
