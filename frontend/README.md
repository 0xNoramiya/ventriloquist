# Ventriloquist frontend

React 18 + TypeScript + Vite. Four screens share one session through the backend's WebSocket:
the patient phone (`/patient/:sid`), the caregiver console (`/caregiver/:sid`), and the setup,
calibration, memory, simulation and settings pages around them. Not a medical device.

## Run it

```sh
# terminal 1: backend in mock mode (no API spend)
cd backend && APP_MODE=mock PYTHONPATH=$PWD:$PWD/.. .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# terminal 2: frontend
cd frontend && npm install && npm run dev
```

Open <https://localhost:5173> and accept the self-signed certificate once. Pick a demo scenario on
the home page: it opens the caregiver console, which shows a QR code for the patient screen.

The dev server proxies `/api` and `/ws` to the backend, so the browser only ever talks HTTPS to one
origin. Set `VENTRILOQUIST_API=http://127.0.0.1:8001` to point the proxy at another backend.

## Using a phone on the LAN

The phone camera only works on a secure origin, which is why the dev server runs HTTPS
(`@vitejs/plugin-basic-ssl`).

1. Put the phone and the laptop on the same Wi-Fi network.
2. `npm run dev` prints the laptop's network addresses (`https://192.168.x.y:5173`). The QR code
   on the caregiver console uses the first LAN address it finds; change it with "Change address"
   if it picked the wrong one (Docker and VPN interfaces are skipped).
3. Scan the QR code, accept the certificate warning on the phone, and tap "Tap to start". That tap
   unlocks speech, keeps the screen awake and, in live mode, starts the camera.

On WSL2 or networks that block device-to-device traffic, use a tunnel instead:

```sh
cloudflared tunnel --url https://localhost:5173 --no-tls-verify
```

Then open the printed `https://….trycloudflare.com` address on the phone and enter that hostname in
"Change address" on the caregiver console so the QR code matches.

## Scripts

| script              | what it does                                                                                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev`       | HTTPS dev server on port 5173, reachable from the LAN                                                                                                      |
| `npm run build`     | type-check, then production build into `dist/`                                                                                                             |
| `npm run preview`   | serve the production build (also proxies `/api` and `/ws`)                                                                                                 |
| `npm run typecheck` | `tsc --noEmit` (strict)                                                                                                                                    |
| `npm run lint`      | ESLint, zero warnings allowed                                                                                                                              |
| `npm test`          | Vitest: store reducer, i18n completeness, spelling and signal helpers                                                                                      |
| `npm run smoke`     | Playwright end-to-end run against a running dev server and mock backend; screenshots go to `smoke-screens/` (or pass `node scripts/smoke.mjs <url> <dir>`) |
| `npm run a11y`      | axe-core pass over every route and the main patient-screen states                                                                                          |

## Mock mode keys

On the patient screen in mock mode: `Y` yes, `N` no, `U` unclear, `E` emergency (the triple-YES
signal). Speech uses the Web Speech API; when no voice exists for the language, the screen shows
the text and moves on after a short reading pause.

## Where things live

- `src/routes/` one file per page
- `src/components/caregiver/` the console panels (bars and chips, trail, banners, overlay, events)
- `src/store/session.ts` session state; `reduceServerMessage` is a pure reducer
- `src/lib/` speech, camera and clip recording, alarm tone, spelling helpers
- `src/i18n/en.json`, `src/i18n/id.json` every visible string, in English and Indonesian
- `public/pictograms/` AAC picture symbols, one per message type
