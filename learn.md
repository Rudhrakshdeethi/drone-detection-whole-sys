# learn.md — how the whole thing works, end to end

This explains the DRONEWATCH / CampusShield counter-drone system the way the code
actually runs it, plus the two new pieces added for the Raspberry Pi demo:

- `ml/runtime/deauth_esp32.py` — drives the deauth board (**ESP32/Marauder** by
  default; ESP8266/Deauther also supported) to deauth **your own** drone's AP.
- `ml/runtime/interceptor.py` — the Pi's Linux orchestrator (nmcli) that joins the
  drone, sends LAND, and rejoins the house WiFi.

> **Legal scope (unchanged):** everything here targets **your own drone and your
> own phone** in an authorized demo. Deauth and LAND are gated by allow-lists that
> refuse any device not on your list. Never point this at third-party devices.

---

## 0. The cast — three boxes, one radio each

| Box | Role | The one job only it can do |
|-----|------|-----------------------------|
| **ESP32 (Marauder)** | deauth radio | transmit 802.11 deauth to knock the pilot's phone off the drone's WiFi |
| **Raspberry Pi 5** | interceptor brain | detect → trigger ESP32 → join the freed drone link → send LAND → host the backend |
| **Laptop** | operator console | show the DRONEWATCH dashboard over the house WiFi |

The reason the ESP32 exists: the Pluto/Tello AP is **first-connection-holds** — while
the phone holds the single client slot, the Pi is refused. A short **targeted** deauth
frees the slot; the Pi grabs it within a couple of seconds and lands the drone.

---

## 1. Two workflows, not one

There are two independent loops. Understand them separately.

### Workflow A — DETECTION (the always-on fusion loop)
`ml/runtime/live_detector.py` runs continuously, fuses every sensor into a 0–100 threat
score, and writes each verdict to `reports/live_detections.csv`.

### Workflow B — INTERCEPT & LAND (the on-demand action)
When you decide to act, the ESP32 deauths, the Pi joins the drone, and a LAND is sent.
This is `ml/runtime/interceptor.py` (Pi) or `interceptor.ps1` (Windows), and the LAND
button on the dashboard hits the same `pluto_control` code.

The dashboard (`ml/runtime/dashboard.py`) is the glue: it **reads** Workflow A's CSV and
**triggers** Workflow B's LAND.

```
   [ sensors ] → live_detector.py → live_detections.csv → dashboard.py → browser
                                                              │
                              LAND button / interceptor.py →  ▼
                                            deauth_esp32.py → pluto_control.py → drone
```

---

## 2. Workflow A line by line — `live_detector.py`

The loop shape is "capture → classify → fuse → score → alert", repeated every
`--interval` seconds. Follow `step()` (one capture → one verdict):

- **`iq, source = self.cap.read()`** (line ~162) — grab one chunk of raw radio
  (I/Q samples) from the RTL-SDR. On a laptop with no SDR, `Capture` returns *mock*
  samples so the loop still runs.
- **`rf = self.clf.predict(iq)`** — the **A1** classifier labels the chunk
  `noise / wifi / bluetooth / drone` with a confidence. This is the primary brain.
- **`looks_droney = ...`** — only if a drone plausibly appears do we spend effort on:
  - **A2 fingerprint** (`self.fp.predict`) — *which* drone model, and
  - **A6 anomaly** (`self.anom.classify`) — known vs unknown/suspicious.
- **`wifi_hits = self.wifi.scan()`** — the **Wi-Fi vector** (`wifi_scan.py`): runs
  `nmcli` on the Pi, matches SSIDs against drone-name patterns (`TELLO`, `DJI`,
  `MAVIC`, …). Bluetooth Remote ID (`self.ble.scan()`) is merged in with the same shape.
- **vision / acoustic / control-link** (`self.vision.read()`, `.acoustic.read()`,
  `.control.read()`) — extra evidence vectors, each degrading to mock/off if the
  hardware or model is absent.
- **localization** — if the camera has a bounding box, `bbox_to_bearing` gives an
  azimuth/elevation; TF-Luna LiDAR adds a range; together with a GPS origin,
  `localize()` produces a lat/lon fix. Without range it honestly reports "bearing only".
- **ADS-B suppression** — `self.adsb.aircraft_nearby(...)` down-weights a "drone" that
  is actually a manned aircraft at that position.
- **`score = compute_threat_score(ThreatInputs(...))`** (line ~257) — **A7 fusion**.
  All vectors combine into 0–100 + `SAFE/WATCH/WARNING/CRITICAL`. A decoded Remote ID
  or SSID match is treated as near-certain ID; a sub-GHz control link lifts RF confidence;
  lingering >30s/>60s adds modifiers.

Then `_handle(v)` (line ~279) turns that verdict into outputs:

- builds a human `detail` string (which vectors fired, at what confidence),
- **A8 explanation** (`_explain`) only on escalation (it's the expensive head),
- writes the `row` dict to `reports/live_detections.csv`,
- `self.alerts.fire(...)` — CSV + GPIO buzzer + Telegram (each optional),
- on escalation, actuates: `response.engage` (spotlight/strobe/buzzer),
  `recorder.record`, `lora.send`, and — **only if you passed `--pluto-land` and
  `--own-drone`** — `self.pluto.engage(v)` to auto-LAND your allow-listed drone.

**Key line for the demo:** auto-LAND is OFF unless you explicitly opt in with
`--pluto-land --own-drone Pluto`. By default the detector only *watches*.

Run it (mock, on a laptop):
```bash
python -m ml.runtime.live_detector --mock --simulate-ssid Pluto_2025_2242
```

---

## 3. The brain of LAND — `pluto_control.py` line by line

This is the single most important file to trust, because it is what actually commands
the drone down. Every safety gate lives here.

- **`match(verdict)`** (line ~63) — returns the matched token **only if** the detection's
  SSID/serial/model contains one of your `authorized` allow-list strings. No match → no LAND.
- **`_connect()`** (line ~79) — tries three paths in order:
  1. the official **`plutocontrol`** library (`connect()/land()/disarm()`),
  2. a raw **MSP-over-TCP** socket to `192.168.4.1:23` (fallback),
  3. **mock** — if nothing is reachable, it only prints what it *would* do.
- **`_do_land(conn)`** (line ~104) — calls `land()` (or `disarm()`); the raw-MSP path
  sends neutral RC + minimum throttle (`MSP_SET_RAW_RC = 200`), which disarms most
  MultiWii stacks.
- **`engage(verdict)`** (line ~123) — the public entry. It refuses unless **all** hold:
  1. `self.enabled` is True (master switch, off by default),
  2. `match()` finds your own drone,
  3. the drone is reachable (else it no-ops in mock).

So `engage` returns one of: `action=land` (sent or mock), `action=none` (disabled or
allow-list miss), or `action=error`. The dashboard and the interceptor both read that
`action` to report success.

Send a LAND directly (already on the drone WiFi):
```bash
PLUTO_HOST=192.168.4.1 PLUTO_PORT=23 \
python -m ml.runtime.pluto_control --enabled --authorized Pluto --ssid Pluto_2025_2242
```

---

## 4. The console — `dashboard.py` line by line

A standard-library-only web server (no Flask), so it runs anywhere the runtime does.

- **`_tail_detections()`** / **`_system_snapshot()`** (lines ~56, ~76) — read the last
  rows of `live_detections.csv` and derive the threat gauge, sensor grid, and
  localization read-out **honestly from the real data** (a sensor shows "active" only if
  recent rows actually populated its field).
- **`_command_land()`** (line ~154) — the LAND button's server handler. It routes by SSID:
  `TELLO*`/`RMTT*` → `TelloDefence`, else → `PlutoDefence`, builds a synthetic own-drone
  verdict so the allow-list authorizes it, calls `engage()`, and records the result.
- **HTTP routes** (lines ~215–251): `GET /api/status` (the snapshot the UI polls every
  1.2s), `POST /api/land` (fires the LAND), `GET/POST /api/config` (host/port/ssid;
  the **SSID stays server-side** and is never shown on the main console).
- **Front-end** (the `PAGE` string): the LAND button is **two-tap** — one tap arms, a
  second within 4s executes (`land.onclick`, line ~483). The SSID lives in a hidden panel
  opened by pressing `` ` `` (backtick), triple-clicking the logo, or the dim corner dot.

Run it:
```bash
PLUTO_SSID=Pluto_2025_2242 python -m ml.runtime.dashboard --host 0.0.0.0 --port 8080
```

---

## 5. THE ADDITIONS

### 5a. `ml/runtime/deauth_esp32.py` — the ESP deauth driver (NEW; ESP32/Marauder default)

Before this file, **nothing in the repo drove the deauth board** — the only `esp32`
references were the ESP32-*CAM* video stream. This closes that gap. **We drive an
ESP32 running Marauder** (the default). An ESP8266 running Spacehuhn's Deauther 2.x
also works — the class carries both dialects.

**The board defaults to `marauder` (ESP32).** Override with `firmware="deauther"` (or
`$DEAUTH_FW=deauther`) only for an ESP8266, because the serial CLI words differ:

| | `firmware="marauder"` (ESP32, default) | `firmware="deauther"` (ESP8266) |
|---|---|---|
| scan | `scanap` | `scan ap` |
| list | `list -a` | `show ap` |
| select | `select -a <idx>` | `select ap <idx>` |
| attack | `attack -t deauth` | `attack deauth` |
| stop | `stop` | `stop` |

Both are 2.4 GHz — fine for Pluto/Tello. The dialects live in the `FIRMWARES` dict at the
top of the file; add a build there if yours differs.

What it does, method by method:
- **`_autodetect()`** — finds the board's serial port (pyserial enumeration, then
  `/dev/ttyUSB0`, `/dev/ttyACM0`, `COM3`…). The USB-serial chip is CP210x or CH340;
  install the matching driver. Override the port with `$DEAUTH_PORT`.
- **`_open()`** — opens the port at 115200 baud; if that fails (no board), it silently
  drops to **mock** so the code still runs on a laptop.
- **`scan_aps()` / `_index_for_ssid()`** — send the dialect's scan→stop→list, then find
  the target AP. `_index_for_ssid` is **firmware-agnostic**: it doesn't fully parse the
  table, it finds the row that mentions your SSID and reads the leading index both
  firmwares print first. *(Layout varies by build; bypass parsing entirely with
  `select_index=`.)*
- **`run_targeted(ssid, duration)`** — the high-level action. It **refuses unless the
  SSID is on the allow-list**, finds the matching AP, then `select` → `attack` → wait →
  `stop`. Targeted (one AP), never broadcast.
- **`mode`** — reports `serial` (real board) or `mock` (dry).

Test it (mock, anywhere — ESP32/Marauder is the default, no flag needed):
```bash
python -m ml.runtime.deauth_esp32 --force-mock --ssid Pluto_2025_2242
# ESP8266 instead? add --firmware deauther
# refusal proof: a non-allow-listed SSID returns {"action":"none", ...}
```
On the Pi with the board plugged in, drop `--force-mock`. Add the Pi user to `dialout`
first (`sudo usermod -aG dialout $USER`, then re-login) for serial access. Flash the
ESP32 with **Marauder** (ESP Web Tools / esptool) and confirm the serial CLI at 115200.

> **If a scan returns no APs:** the firmware's list layout may differ from the parser.
> Pass an explicit `--index N` (the drone AP is usually the strongest/only `Pluto_*`)
> instead of relying on the scan.

### 5b. `ml/runtime/interceptor.py` — the Pi orchestrator (NEW)

The Linux twin of `interceptor.ps1`. Windows uses `netsh`; the Pi uses **`nmcli`**.
`run()` executes the whole hand-off in order:

1. **remember the house WiFi** — `current_ssid()` (or `--house`).
2. **`--deauth`** (optional) — `DeauthESP32.run_targeted(...)` frees the single slot,
   then waits `--grab-delay` seconds.
3. **join the drone** — `find_drone_ssid("Pluto")` matches the session-changing
   `Pluto_2025_XXXX` by **prefix** (not a fixed name), then `join()`.
4. **LAND** — reads the drone gateway, calls `send_land()` → `pluto_control.engage()`.
5. **rejoin the house WiFi** — `_restore()` so the laptop's SSH/dashboard reconnects.

Because it leaves the house WiFi mid-run, launch it so it **survives the hop** — via
`setsid`/`nohup` or a systemd unit (see §7), not from an interactive SSH shell that will
drop.

Rehearse the entire sequence in mock (touches no radio):
```bash
python -m ml.runtime.interceptor --dry-run --deauth \
  --drone-ssid Pluto_2025_2242 --house NxtWave_Te@m
```
Real run on the Pi (ESP32/Marauder is the default deauth board):
```bash
python -m ml.runtime.interceptor --deauth \
  --drone-prefix Pluto --password <this-session-pw> --house <house-ssid>
```
Using an ESP8266 instead? Add `--deauth-firmware deauther` (or `export DEAUTH_FW=deauther`).

---

## 6. Bringing it up on the Raspberry Pi 5 — step by step

```bash
# 6.1  OS deps
sudo apt update && sudo apt install -y rtl-sdr network-manager python3-pip git
# 6.2  code + Python deps
git clone <this-repo> && cd drone-detection-whole-sys
pip install -r requirements-core.txt -r requirements-runtime.txt
pip install plutocontrol pyserial
# 6.3  serial access to the ESP32 (log out/in after)
sudo usermod -aG dialout $USER   # ESP32/Marauder is the default; ESP8266 => export DEAUTH_FW=deauther
# 6.4  prove the ML stack runs on the Pi (mock, no drone needed)
python run_all.py
# 6.5  prove each new piece in mock
python -m ml.runtime.deauth_esp32 --force-mock --ssid Pluto_2025_2242
python -m ml.runtime.interceptor --dry-run --deauth --drone-ssid Pluto_2025_2242 --house <house-ssid>
```

Point the laptop dashboard at the Pi backend: set `VITE_API_BASE=http://interceptor.local:8080`
(the Pi runs `python -m ml.runtime.dashboard --host 0.0.0.0 --port 8080`).

---

## 7. Run it autonomously (survives the WiFi hop)

Quick and dirty:
```bash
setsid python -m ml.runtime.interceptor --deauth \
  --drone-prefix Pluto --password <pw> --house <house-ssid> \
  > intercept.log 2>&1 < /dev/null &
```

Or a systemd unit `/etc/systemd/system/interceptor.service`:
```ini
[Unit]
Description=Drone interceptor (deauth + land)
After=NetworkManager.service

[Service]
Type=oneshot
WorkingDirectory=/home/pi/drone-detection-whole-sys
ExecStart=/usr/bin/python3 -m ml.runtime.interceptor --deauth --drone-prefix Pluto --house YOUR_HOUSE_SSID
User=pi

[Install]
WantedBy=multi-user.target
```
`sudo systemctl daemon-reload && sudo systemctl start interceptor` — it runs
independent of your SSH session, so the WiFi hop can't kill it.

---

## 8. Acceptance test (all must pass — from HARDWARE.md §5)

1. Phone flies the drone.
2. Operator triggers INTERCEPT (dashboard LAND, or `interceptor.py --deauth`).
3. ESP32 deauth fires; **phone visibly loses control** (no manual disconnect).
4. Pi joins the freed drone slot within a few seconds.
5. Pi sends LAND; **drone lands**.
6. Pi rejoins house WiFi; laptop SSH/dashboard reconnects; log shows `commanded land`.

The still-open item to prove first (per the checklist): **that `land()` actually brings
THIS drone down.** Do §5b real run once, on the bench, before wiring in the deauth.

---

## 9. Mock vs real — the one thing to remember

Every module in `ml/runtime/` degrades gracefully: no SDR → mock IQ; no `nmcli` →
no WiFi vector; no ESP32 → mock deauth; no drone reachable → mock LAND. So you can
dry-run the **entire** pipeline on a Windows laptop, and the *same* commands do the
real thing on the Pi with the hardware attached. Nothing is stubbed differently between
demo and production — only the presence of hardware changes.
```
mock  = code runs, prints what it WOULD do, touches no radio
real  = same code, hardware present, actually transmits / lands
```
