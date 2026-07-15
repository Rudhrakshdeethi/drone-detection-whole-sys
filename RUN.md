# RUN.md — how to run this, from zero

A copy-paste runbook for the DRONEWATCH / CampusShield counter-drone system.
If you want to understand *how it works* line by line, read **`learn.md`**. This
file is just **the commands**.

> **Legal scope:** every action here targets **your own drone + your own phone**
> in an authorized demo. The deauth and LAND paths are allow-list gated and refuse
> any device that isn't yours. Never point this at third-party devices.

---

## ★ Counter-drone — the one command (Windows)

`counter.ps1` is the single command: **detect → deauth → seize the slot → LAND**,
auto-routed by drone type. Run from the repo root with the ESP8266 on `COM8`.

```powershell
.\counter.ps1                                  # DETECT - list drones in range
.\counter.ps1 -Test                            # DRY-RUN the whole pipeline (mock, no radio)
.\counter.ps1 -Engage -Target TELLO-954B1F     # FULL takeover -> lands the Tello  ✅ works end-to-end
.\counter.ps1 -Engage -Target PlutoX_2025_1129 # Pluto: lands only if you hold the link (PMF blocks takeover)
```

- **Tello** (open Wi-Fi, no PMF): deauths the controller, laptop seizes the open slot,
  sends the UDP `land` — **verified landing a real Tello.** This is the working neutralize.
- **Pluto** (WPA2 **+ PMF**): deauth is blocked at the protocol level, and it's single-client,
  so takeover from an active pilot isn't possible; detection still works, and it lands when
  the laptop already holds the link (see `ml/runtime/pluto_fly.py`).
- Detect-only, no ESP needed: **`.\detect_drone.ps1`** (add `-Watch` to keep scanning).
- Internet drops during `-Engage` (one radio) and is restored at the end; full log in `counter-log.md`.

---

## 0. TL;DR — 60-second dry run (any laptop, no hardware)

Everything degrades to **mock** with no hardware, so you can rehearse the whole
pipeline on any machine with Python:

```bash
# 1. install Python deps
pip install -r requirements-core.txt

# 2. train the mock models (writes to models/ and reports/)
python run_all.py

# 3a. start the detection dashboard  -> http://127.0.0.1:8080
python -m ml.runtime.dashboard

# 3b. in a second terminal, feed it a simulated drone
python -m ml.runtime.live_detector --mock --simulate-ssid Pluto_2025_2242

# 4. rehearse the full deauth -> join -> LAND -> rejoin sequence (touches no radio)
python -m ml.runtime.interceptor --dry-run --deauth \
  --drone-ssid Pluto_2025_2242 --house YOUR_HOME_WIFI
```

Open `http://127.0.0.1:8080`, watch the threat gauge move, tap **Initiate RF
Landing** twice — it will report a mock LAND. That proves the software works end
to end. Everything below is the same commands with real hardware attached.

---

## 1. Install

### 1a. Windows laptop (operator console + mock)
```powershell
# Python side
pip install -r requirements-core.txt
# Dashboard UI (React/Vite) side
npm install
```

### 1b. Raspberry Pi 5 (the real interceptor)
```bash
sudo apt update && sudo apt install -y rtl-sdr network-manager python3-pip git
git clone <this-repo> && cd drone-detection-whole-sys
pip install -r requirements-core.txt -r requirements-runtime.txt
pip install plutocontrol pyserial          # drone control + ESP serial
sudo usermod -aG dialout $USER             # serial access to the ESP — then LOG OUT/IN
```

The deauth board defaults to **ESP8266 + Spacehuhn Deauther 2.x** — no flag needed.
(If you ever use an ESP32 instead, set `export DEAUTH_FW=marauder`; see §5.)

---

## 2. Run the detection system

### The dashboard (operator console)
```bash
# Pi (reachable from the laptop):
PLUTO_SSID=Pluto_2025_2242 python -m ml.runtime.dashboard --host 0.0.0.0 --port 8080
# Laptop (local only):
python -m ml.runtime.dashboard
```
`--mock` forces the LAND path to never touch a real link. `--no-open` skips the
browser. Open it at `http://<host>:8080`.

### The detector (fills the live feed)
```bash
# Real hardware (RTL-SDR + nmcli Wi-Fi scan, auto-detected):
python -m ml.runtime.live_detector

# Demo / no hardware — inject a fake drone so the feed populates:
python -m ml.runtime.live_detector --mock --simulate-ssid Pluto_2025_2242
python -m ml.runtime.live_detector --mock --simulate DJI_Mavic --once   # single pass

# Auto-LAND your OWN drone when a detection escalates (opt-in, allow-list gated):
python -m ml.runtime.live_detector --pluto-land --own-drone Pluto
```

Point the React dashboard at the Pi backend (laptop):
`VITE_API_BASE=http://interceptor.local:8080`, then `npm run dev`.

---

## 3. Just LAND a drone you're already connected to

You (or the Pi) are already on the drone's Wi-Fi:

```bash
# cross-platform (Pi or laptop):
PLUTO_HOST=192.168.4.1 PLUTO_PORT=23 \
python -m ml.runtime.pluto_control --enabled --authorized Pluto --ssid Pluto_2025_2242
```
```powershell
# Windows shortcut (auto-targets the Pluto_* you're connected to):
npm run land:now
```
A successful run prints `commanded land ... via plutocontrol/msp`. If nothing is
reachable it prints a mock line instead (no drone found).

---

## 4. The full intercept (deauth → join → LAND → rejoin)

This is the whole hand-off on one radio. **Run it so it survives the Wi-Fi hop** —
not from an SSH shell that will drop when the Pi leaves the house network.

```bash
# Dry run first (mock, proves the sequence):
python -m ml.runtime.interceptor --dry-run --deauth --drone-ssid Pluto_2025_2242 --house YOUR_HOME_WIFI

# Real, foreground (ESP8266/Deauther is the default deauth board):
python -m ml.runtime.interceptor --deauth \
  --drone-prefix Pluto --password THIS_SESSION_PW --house YOUR_HOME_WIFI

# Real, autonomous (survives the hop):
setsid python -m ml.runtime.interceptor --deauth \
  --drone-prefix Pluto --password THIS_SESSION_PW --house YOUR_HOME_WIFI \
  > intercept.log 2>&1 < /dev/null &
tail -f intercept.log
```

Useful flags: `--drone-ssid` (exact name, skips prefix scan) · `--host/--port`
(control link, default `192.168.4.1:23`) · `--grab-delay` (seconds after deauth
before seizing the slot) · `--stay` (don't rejoin house Wi-Fi).

**Windows equivalent** (laptop, one radio, PowerShell): `npm run intercept` — this now
does the **full chain**: ESP8266 deauth (frees the slot) → join Pluto → LAND → rejoin
internet. It auto-detects the ESP serial port; pin it with
`-File interceptor.ps1 -Deauth -DeauthPort COM8` (or `$env:DEAUTH_PORT`), skip the scan
with `-DeauthIndex 0`. `npm run intercept:nodeauth` is the old join+LAND only (no deauth,
for when the slot is already free). With no ESP board the deauth degrades to a harmless
mock and the join still runs.

> `npm run land` / `land:now` is **LAND only** — it needs the laptop to already be on the
> drone's Wi-Fi. It does not deauth or join, so it can't get past a phone that's holding
> the slot. Use `npm run intercept` for the whole hand-off.

### Run it on boot / on demand as a service (Pi)
`/etc/systemd/system/interceptor.service`:
```ini
[Unit]
Description=Drone interceptor (deauth + land)
After=NetworkManager.service
[Service]
Type=oneshot
WorkingDirectory=/home/pi/drone-detection-whole-sys
ExecStart=/usr/bin/python3 -m ml.runtime.interceptor --deauth --drone-prefix Pluto --house YOUR_HOME_WIFI
User=pi
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl start interceptor     # fire it
journalctl -u interceptor -f         # watch it
```

---

## 5. Deauth board — ESP8266 + Deauther (default)

The deauth board frees the drone's single client slot. **We use an ESP8266 running
Spacehuhn Deauther 2.x**, which is the default — no firmware flag needed. Full setup:
**`esp8266setup.md`**.

| Board | Firmware | Software token |
|-------|----------|----------------|
| **ESP8266** (NodeMCU / Wemos) — *what we use* | **Spacehuhn Deauther 2.x** | `deauther` *(default)* |
| ESP32 (S2/S3/C3/orig) — *alternative* | Marauder | `marauder` |

Flash the ESP8266 with **Deauther 2.x** (serial build; web installer / esptool), confirm
the serial CLI at 115200 (`scan ap` → `show ap` → `select ap 0` → `attack deauth` → `stop`).

Test the board directly (mock first, then drop `--force-mock` on the Pi):
```bash
python -m ml.runtime.deauth_esp32 --selftest          # is the board answering on serial?
python -m ml.runtime.deauth_esp32 --force-mock --ssid Pluto_2025_2242
python -m ml.runtime.deauth_esp32 --ssid Pluto_2025_2242 --duration 6
# skip the scan and target an index directly if the list is empty:
python -m ml.runtime.deauth_esp32 --ssid Pluto_2025_2242 --index 0
```
`--selftest` sends no attack — it just confirms the port opened and the firmware
replies (`"ok": true`). In the full intercept, the same escape hatch is
`--deauth-index N`.
Serial port auto-detects; override with `--port /dev/ttyUSB0` or `$DEAUTH_PORT`.
(Using an ESP32 instead? add `--firmware marauder` or `export DEAUTH_FW=marauder`.)

---

## 6. Command index (cheat sheet)

| Goal | Command |
|------|---------|
| Train mock models | `python run_all.py` |
| Dashboard | `python -m ml.runtime.dashboard --host 0.0.0.0 --port 8080` |
| Detector (real) | `python -m ml.runtime.live_detector` |
| Detector (demo) | `python -m ml.runtime.live_detector --mock --simulate-ssid Pluto_2025_2242` |
| Land (connected) | `python -m ml.runtime.pluto_control --enabled --authorized Pluto --ssid <ssid>` |
| Deauth self-test | `python -m ml.runtime.deauth_esp32 --selftest` |
| Deauth test | `python -m ml.runtime.deauth_esp32 --ssid <ssid>` (ESP8266/Deauther default) |
| Full intercept | `python -m ml.runtime.interceptor --deauth --drone-prefix Pluto --house <wifi>` |
| Dry-run intercept | `python -m ml.runtime.interceptor --dry-run --deauth --drone-ssid <ssid> --house <wifi>` |
| Windows: land | `npm run land:now` |
| Windows: intercept | `npm run intercept` |
| React UI | `npm run dev` |

---

## 7. Troubleshooting

- **`nmcli not found`** — you're not on Linux/Raspberry Pi OS. The interceptor's
  Wi-Fi hop needs NetworkManager. Use `--dry-run` on a laptop, or `npm run intercept`
  on Windows.
- **Deauth prints `(mock)` on the Pi** — the board wasn't opened. Run
  `python -m ml.runtime.deauth_esp32 --selftest`; if it says `"ok": false`, check the
  cable, `ls /dev/ttyUSB* /dev/ttyACM*`, that you're in the `dialout` group (re-login),
  and pass `--port` explicitly.
- **`AP '<ssid>' not seen in scan`** — the scan didn't list the drone AP (or the
  firmware's list format differs). Pass `--index N` (the drone AP is usually the
  strongest `Pluto_*`) to skip the scan and target it directly.
- **LAND says mock / "no drone reachable"** — you're not on the drone's Wi-Fi, or the
  gateway/port is wrong. Confirm you joined `Pluto_*`, then set `PLUTO_HOST`/`PLUTO_PORT`.
- **Deauth doesn't drop the phone** — the AP may enforce **PMF/802.11w** (deauth
  blocked). Verify the drone AP does NOT enable Protected Management Frames.
- **Pi drops SSH mid-intercept** — expected; it left the house Wi-Fi. Always launch
  via `setsid`/systemd (§4) so the run survives, and it will rejoin at the end.

---

See **`learn.md`** for the architecture and a line-by-line walkthrough, and
**`HARDWARE.md`** for the pre-demo provisioning checklist.
