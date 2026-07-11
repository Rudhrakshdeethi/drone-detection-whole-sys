# DRONEWATCH — operator dashboard (Vite + React)

The green-phosphor situational-awareness console in `src/` (Figma Make export).
It runs as a **self-contained demo with zero backend**, and **lights up with real
detections** the moment the CampusShield detector is streaming — no code changes,
no rebuild.

```
Header      LIVE/DEMO badge · fused threat level · RF LAND control · telemetry
CameraView  live feed + tracking box, HUD bound to the real localization fix
Radar       5 km sweep; plots the real bearing/target blip from the backend
SignalIntel sensor-fusion grid + spectrum + detected contacts
LiveLog     the real detection stream (falls back to a simulated log)
History     detection history + CSV export (real rows when live)
```

## Two ways to run it

### 1. DEMO — no backend, no hardware
Everything animates from a built-in simulation. Good for a quick look or a UI demo.

```powershell
npm install       # first time (Node 20+; pnpm also works)
npm run dev        # http://localhost:8443
```

The header shows a **DEMO** badge and the `RF LAND` control is disabled (it needs
a real link).

### 2. LIVE — wired to the real detector
Start the Python backend and the detector, then the UI flips to **LIVE** and every
panel binds to real data from `reports/live_detections.csv`.

```powershell
# terminal 1 — the dashboard API (stdlib only, no extra installs)
python -m ml.runtime.dashboard --port 8080 --no-open

# terminal 2 — feed it detections (mock is fine; real SDR auto-detected)
python -m ml.runtime.live_detector --mock --simulate-ssid DJI-Mavic-1A2B

# terminal 3 — the UI
npm run dev        # http://localhost:8443  -> shows LIVE
```

Vite proxies `/api/*` to the backend (see `vite.config.ts`). When the backend is
unreachable the UI falls back to the DEMO simulation after a couple of missed
polls, so a dropped connection never blanks the screen.

## Pointing at another host (e.g. a Raspberry Pi)

The detector usually runs on the Pi. Point the dev proxy at it:

```powershell
$env:BACKEND_URL = "http://raspberrypi.local:8080"
npm run dev
```

For a production build served from somewhere other than the backend, bake the API
base into the bundle instead:

```powershell
$env:VITE_API_BASE = "http://raspberrypi.local:8080"
npm run build       # output in dist/
```

## RF LAND control

The `RF LAND` button is the one operator action: it commands **your own
allow-listed drone to LAND** via `ml/runtime/pluto_control.py` (land-only,
allow-list gated — it never jams or takes over third-party aircraft). It is:

- **disabled** in DEMO and whenever the backend has no target link configured;
- **two-step**: one tap arms it, a second tap within 4 s executes.

Configure the target link on the backend (kept server-side, never shown in the UI):

```powershell
$env:PLUTO_SSID = "PLUTO"          # your drone's SSID / allow-list token
$env:PLUTO_HOST = "192.168.4.1"
python -m ml.runtime.dashboard
```

## How the data maps

The backend `/api/status` snapshot (`ml/runtime/dashboard.py`) drives the panels:

| UI panel            | Backend field(s)                                            |
|---------------------|-------------------------------------------------------------|
| Threat chip / banner| `threat.level`, `threat.score`                              |
| Sensor Fusion grid  | `sensors[]` (rf / wifi / vision / acoustic / control / loc) |
| Live Detection Log  | `feed[]` rows                                               |
| Detection History   | `feed[]` rows → history + CSV export                        |
| Radar target blip   | `fix.az`, `fix.range_m`                                     |
| Camera HUD          | `fix.lat/lon`, latest `visual_conf`                         |
| Detected Contacts   | `feed[]` identities (Remote ID / fingerprint / SSID)       |
| RF LAND             | `armed`, `POST /api/land`, `last_land`                     |

The data layer lives in `src/lib/api.ts`; polling + LIVE/DEMO state is shared by
all panels through `src/lib/SystemContext.tsx`.
