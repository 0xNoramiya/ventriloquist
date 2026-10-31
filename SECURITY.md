# Security

Ventriloquist is a research prototype, not a medical device. Do not run it with real patients
without clinical validation and ethics approval.

## Reporting a vulnerability

Please report security issues privately through GitHub (Security tab, "Report a vulnerability")
rather than in a public issue. I aim to reply within a week.

## How the app handles data

- API keys live only in `.env`, which is gitignored. The browser never sees them; every model call
  goes through the backend.
- Switching to live or privacy mode from the UI needs the `LIVE_PASSCODE` set in `.env`. An open
  deployment (`PUBLIC_LIVE=true`) gives every visitor live mode instead, capped by the budget guard;
  the passcode then only guards Settings.
- Every Meta Model API request is sent with `store: false`.
- Session logs identify a patient by a pseudonymous id; profile names are redacted.
- Clips, audio and the database stay in `data/` on the machine running the backend. That folder is
  gitignored, and nothing in this repository comes from a real patient.
