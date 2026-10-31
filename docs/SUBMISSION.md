# Submission

Meta Global AI Developer Hackathon 2026. **Indie Developer track**, theme **Build for Your World**.
Submissions close 2026-11-04 21:00 ET (2026-11-05 02:00 UTC). Judging 2026-11-04 to 11-08.

## Links

| | |
|---|---|
| Film (3:00) | https://github.com/0xNoramiya/ventriloquist/releases/download/v0.2.0/ventriloquist-demo.mp4 |
| Demo, no install | https://0xnoramiya.github.io/ventriloquist/ |
| The app | https://ventriloquist.fly.dev |
| Code | https://github.com/0xNoramiya/ventriloquist |

## One line

The patient does the talking. The phone just moves its lips.

## Short description (about 150 words)

An awake patient on a ventilator cannot speak, and about 5% of what they try to say is understood.
Ventriloquist is a phone on the bed rail that gives them a voice. The nurse calibrates whatever
movement the patient still has, an eyebrow raise or a long blink; Muse Spark names it and SAM 3.1
tracks it from then on. The phone then asks the yes/no question that narrows things down fastest,
reads the answer from a four-second clip, and speaks the message aloud in the first person only
after the patient confirms it. Muse Spark reads the room for context and must cite its evidence;
plain code bounds how far that can move a guess. A judge that never sees the question checks every
answer. Anything not on the list gets spelled. With the patient's yes, the message goes to a
relative on WhatsApp. Not a medical device.

## Meta models

Muse Spark 1.3 (calibration describer, scene reader, evidence-cited prior builder, question
proposer, blind answer judge, spelling and sentence builder, sensitive-topic classifier, reader of
family replies), SAM 3.1 (tracks the patient's own signal), Muse Voice Transcribe (room transcript
with an Indonesian language bias), Muse Wonder (memory curator across the stay), Muse Image (the 34
AAC pictograms), Muse Spark Open on Baseten (privacy mode on open weights), Muse Glimmer (optional
on-premises tier), WhatsApp Cloud API (family relay).

## What is real, and what is not

Say this plainly; it is the difference between a demo and a claim.

- **Real:** the engine, the safety rules and the console. Every model call in the film is a live call.
  2,000-trial seeded simulations behind every engine number (`make sim` reproduces them). The
  detector scored three times over on generated clips: no confidently wrong answer in 39 judgments.
- **Not real:** every patient is fictional and every clip is generated. No real patient, and no real
  human face, has been in front of this. The family relay runs end to end against a simulated
  relative, because a WhatsApp Business account is not connected yet.
- **Not a medical device.** No diagnosis, no advice, no vital signs. It would need ethics approval
  and a clinical study before any use with a patient.

## Checklist before submitting

- [ ] Film uploaded somewhere that streams (YouTube or X), in case judges will not download 80 MB
- [ ] Links above all open in a private window
- [ ] `make test` green, CI green on `main`
- [ ] Live app redeployed from `main` (`make deploy`)
- [ ] Clips from one consenting adult, if there is time: the first numbers from a real face
