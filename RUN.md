# RUN.md — how to run this, from zero

A copy-paste runbook for the DRONEWATCH / CampusShield counter-drone system.
If you want to understand *how it works* line by line, read **`learn.md`**. This
file is just **the commands**.

> **Legal scope:** every action here targets **your own drone + your own phone**
> in an authorized demo. The deauth and LAND paths are allow-list gated and refuse
> any device that isn't yours. Never point this at third-party devices.

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
python -m ml.runtime.interceptor --dry-run --deauth --deauth-firmware deauther \
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

Pick your deauth board once (see §5) and remember it:
```bash
export DEAUTH_FW=deauther     # ESP8266 (Spacehuhn Deauther).  ESP32 => marauder
```

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

# Real, foreground:
python -m ml.runtime.interceptor --deauth --deauth-firmware deauther \
  --drone-prefix Pluto --password THIS_SESSION_PW --house YOUR_HOME_WIFI

# Real, autonomous (survives the hop):
setsid python -m ml.runtime.interceptor --deauth --deauth-firmware deauther \
  --drone-prefix Pluto --password THIS_SESSION_PW --house YOUR_HOME_WIFI \
  > intercept.log 2>&1 < /dev/null &
tail -f intercept.log
```

Useful flags: `--drone-ssid` (exact name, skips prefix scan) · `--host/--port`
(control link, default `192.168.4.1:23`) · `--grab-delay` (seconds after deauth
before seizing the slot) · `--stay` (don't rejoin house Wi-Fi).

**Windows equivalent** (laptop, one radio, PowerShell): `npm run intercept`.

### Run it on boot / on demand as a service (Pi)
`/etc/systemd/system/interceptor.service`:
```ini
[Unit]
Description=Drone interceptor (deauth + land)
After=NetworkManager.service
[Service]
Type=oneshot
Environment=DEAUTH_FW=deauther
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

## 5. Deauth board — pick your firmware

The deauth ESP frees the drone's single client slot. Two boards, two firmwares —
tell the software which with `--deauth-firmware` (or `$DEAUTH_FW`):

| Board | Firmware | Software token |
|-------|----------|----------------|
| **ESP8266** (NodeMCU / Wemos) | Spacehuhn **ESP8266 Deauther 2.x** | `deauther` |
| **ESP32** (S2/S3/C3/orig) | **Marauder** | `marauder` |

Test the board directly (mock first, then drop `--force-mock` on the Pi):
```bash
python -m ml.runtime.deauth_esp32 --force-mock --firmware deauther --ssid Pluto_2025_2242
python -m ml.runtime.deauth_esp32 --firmware deauther --ssid Pluto_2025_2242 --duration 6
# if your build has no serial CLI, skip the scan and target an index directly:
python -m ml.runtime.deauth_esp32 --firmware deauther --ssid Pluto_2025_2242 --index 0
```
Serial port auto-detects; override with `--port /dev/ttyUSB0` or `$DEAUTH_PORT`.
Flash the ESP8266 from **https://deauther.com** (ESP Web Tools) with the **serial
CLI enabled at 115200**.

---

## 6. Command index (cheat sheet)

| Goal | Command |
|------|---------|
| Train mock models | `python run_all.py` |
| Dashboard | `python -m ml.runtime.dashboard --host 0.0.0.0 --port 8080` |
| Detector (real) | `python -m ml.runtime.live_detector` |
| Detector (demo) | `python -m ml.runtime.live_detector --mock --simulate-ssid Pluto_2025_2242` |
| Land (connected) | `python -m ml.runtime.pluto_control --enabled --authorized Pluto --ssid <ssid>` |
| Deauth test | `python -m ml.runtime.deauth_esp32 --firmware deauther --ssid <ssid>` |
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
- **Deauth prints `(mock)` on the Pi** — the board wasn't opened. Check the cable,
  `ls /dev/ttyUSB* /dev/ttyACM*`, that you're in the `dialout` group (re-login), and
  pass `--port` explicitly.
- **`AP '<ssid>' not seen in scan`** — your Deauther build may be web-UI-only (no
  serial list). Pass `--index N` (the drone AP is usually the strongest `Pluto_*`).
- **LAND says mock / "no drone reachable"** — you're not on the drone's Wi-Fi, or the
  gateway/port is wrong. Confirm you joined `Pluto_*`, then set `PLUTO_HOST`/`PLUTO_PORT`.
- **Deauth doesn't drop the phone** — the AP may enforce **PMF/802.11w** (deauth
  blocked). Verify the drone AP does NOT enable Protected Management Frames.
- **Pi drops SSH mid-intercept** — expected; it left the house Wi-Fi. Always launch
  via `setsid`/systemd (§4) so the run survives, and it will rejoin at the end.

---

See **`learn.md`** for the architecture and a line-by-line walkthrough, and
**`HARDWARE.md`** for the pre-demo provisioning checklist.
