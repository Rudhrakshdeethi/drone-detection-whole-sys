# CampusShield — Next.js Operations Console

A Next.js (App Router + TypeScript) front-end for the drone-detection system. It
renders the live threat gauge, sensor-fusion grid, localization read-out, and
detection feed, plus the **Initiate RF Landing** control.

It is a thin client over the Python API in `ml/runtime/dashboard.py`
(`/api/status`, `/api/land`, `/api/config`). `next.config.mjs` proxies `/api/*`
to that backend, so the browser stays same-origin (no CORS).

Panels: threat gauge (SVG arc), RF-neutralization land control, a Leaflet dark
tactical map with a pulsing contact blip, bearing/range telemetry, a live
detection log, the sensor-fusion grid, and a Primary Contact dossier.

## Run — one command (recommended)

Boots the Python API backend **and** the Next.js frontend together (via
`concurrently`):

```powershell
$env:PLUTO_SSID = "PLUTO"      # your drone's SSID / allow-list token
$env:PLUTO_HOST = "192.168.4.1"
npm install
npm run dev:all                # API on :8080  +  UI on http://localhost:3000
```

## Run — two processes (if you prefer separate terminals)

```powershell
# 1) Backend API (from the repo root):
$env:PLUTO_SSID = "PLUTO"; $env:PLUTO_HOST = "192.168.4.1"
python -m ml.runtime.dashboard --no-open        # JSON API on :8080

# 2) Feed it detections (optional, another terminal):
python -m ml.runtime.live_detector --mock --simulate-ssid DJI-Mavic-1A2B

# 3) Frontend (from dashboard/):
npm install
npm run dev                                      # http://localhost:3000
```

> Port note: if another app already holds `:3000`, Next bounces to `:3001` —
> watch the terminal for the real URL. The map uses CartoDB dark tiles; offline
> the tiles are blank but the contact pin still renders.

Point the frontend at a non-default backend with `BACKEND_URL`:

```powershell
$env:BACKEND_URL = "http://127.0.0.1:9000"; npm run dev
```

## The hidden SSID field

The drone's SSID / allow-list token is intentionally **not** on the main
console. Open the "Link Configuration" panel with any of:

- press the **`` ` ``** (backtick) key
- **triple-click** the `CS` logo
- click the **dim dot** in the bottom-right corner

Pre-fill it from `PLUTO_SSID` on the backend and you never need to open it live.

## Production build

```powershell
npm run build
npm run start        # http://localhost:3000
```

## Landing scope

The land button commands **your own allow-listed drone** to LAND over its own
control link (via `ml/runtime/pluto_control.py`). Land-only, allow-list gated —
no RF jamming, takeover, or GPS spoofing. See that module's legal note.
