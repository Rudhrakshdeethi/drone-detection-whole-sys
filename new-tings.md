# New Things — Multi-Sensor Drone Detection & Localization

This document records everything added in this work session, and the **hardware-free
verification** proving it runs today. Every module degrades to a mock on a laptop and
switches to real hardware on the Raspberry Pi automatically — no code changes.

_Verified: 2026-07-02 · Windows laptop · project `.venv` · zero hardware, zero paid services._

---

## Files created / edited

**Created — 22 runtime modules** (`ml/runtime/`)
`kismet_scan.py` · `ble_remoteid.py` · `vision_scan.py` · `acoustic_scan.py` ·
`control_link_scan.py` · `adsb_scan.py` · `lidar.py` · `localize.py` ·
`direction_finding.py` · `pantilt.py` · `response.py` · `display.py` ·
`lora_mesh.py` · `recorder.py` · `power_monitor.py` · `gps.py` ·
`health_monitor.py` · `timeline.py` · `spectrum_recorder.py` · `light_tower.py` ·
`triangulate.py` · `pluto_control.py`

**Created — docs / notebooks (3)**
`ml/runtime/KISMET_SETUP.md` · `ml/colab_train_rf.ipynb` · `new-tings.md` (this file)

**Edited (4)**

| File | What changed |
|------|--------------|
| `ml/runtime/live_detector.py` | Fused all new sensor vectors (Kismet/BLE Remote ID, vision, acoustic, control-link, ADS-B); pan-tilt tracking + LiDAR localization; **GPS auto-origin**; actuation on escalation (response, recorder, LoRa, OLED, **light tower**); health/GPS/tower status header; many new CLI flags (`--track`, `--lat/--lon`, `--no-vision/-acoustic/-ble/-lidar/-response/-lora`, `--vision-source`) |
| `ml/a7_threat_scoring/threat_score.py` | Added `remote_id_decoded` (floors score at WARNING 75) and `aircraft_match` (ADS-B −20 false-positive suppression) |
| `ml/runtime/alerts.py` | CSV log **auto-rotates** when the record schema changes (new Remote ID / localization columns) so rows never misalign |
| `requirements-runtime.txt` | Added `pyserial` (TF-Luna + LoRa UART); noted optional `bleak` (BLE Remote ID) |

## Changes made in this file (`new-tings.md`)
- Added this **Files created / edited** section at the top.
- Documented all **21 runtime modules** (two build rounds) with their real-hardware vs. mock mapping.
- Recorded the **hardware-free verification**: 22/22 module self-tests + integrated fusion,
  single-node position, and the threat-score logic matrix (with actual numbers).
- Added the **fusion / position architecture diagram** and "run it free" commands.
- Listed **honest limitations** and **deliberately-not-built** items (with reasons).

---

## TL;DR — what changed and why

The original stack detected drones from **RF presence** (RTL-SDR + trained classifiers).
Two realities reshaped the system:

1. **The RTL-SDR V4 cannot tune 2.4 GHz** (it tops out at ~1.766 GHz). So live 2.4 GHz
   drone RF capture is impossible with our hardware. The RTL-SDR's *real* jobs are
   **sub-GHz control links (433/868/915 MHz)** and **ADS-B (1090 MHz)**.
2. **RF alone gives presence, not position.** Position comes from a **bearing**
   (camera / pan-tilt, or a rotating Yagi) **plus a range** (TF-Luna LiDAR), or from
   **Remote ID** (the drone broadcasting its own GPS over Wi-Fi/Bluetooth).

So we added the **real** detection + localization vectors the hardware supports, and
fused them all into the existing A7 threat score.

---

## Verification results (no hardware)

### All module self-tests — 22 / 22 PASS
```
kismet_scan · ble_remoteid · vision_scan · acoustic_scan · control_link_scan
adsb_scan · lidar · localize · direction_finding · pantilt · response
display · lora_mesh · recorder · power_monitor · threat_score          (16)
gps · health_monitor · timeline · spectrum_recorder · light_tower · triangulate  (+6)
=> 22 passed, 0 failed
```

The GPS reader now **auto-supplies the sensor origin** — running the detector with
no `--lat/--lon` prints `origin: 12.971600,77.594600 (from GPS)`, so single-node
position computation is hands-free (was manual before).

### Integrated fusion loop (`live_detector`, mock)
```
1) Fused detection (Kismet + BLE + control-link):
   WARNING 75.0/100  WIFI 88.5% | SSID:DJI-Mavic-1A2B | RID:DJI Mavic 3 |
   drone@12.97280,77.59545 | pilot@12.97120,77.59445

2) Single-node POSITION (camera bearing + LiDAR range):
   az=13.2  el=9.0  range=3.57m  ->  GPS 12.971631,77.594607  alt=0.56

3) Threat-score logic matrix:
   RF-only weak            :  10.5 SAFE
   decoded Remote ID floor :  75.0 WARNING
   vision+acoustic+control :  49.2 WATCH
   ADS-B aircraft suppress :  31.5 WATCH   (pulled down from a false positive)
```

---

## New modules (`ml/runtime/`)

| Module | Role | Real hardware | Mock fallback |
|--------|------|---------------|---------------|
| `kismet_scan.py` | **Wi-Fi DroneID / Remote ID** via Kismet REST API — DJI DroneID + FAA Remote ID incl. drone & operator GPS | AR271 Wi-Fi + Kismet | `--simulate-ssid` |
| `ble_remoteid.py` | **Bluetooth Remote ID** (ASTM F3411 OpenDroneID over BLE) | ESP32 / BLE + `bleak` | `--simulate-ssid` |
| `vision_scan.py` | **A4 YOLO** camera vector → `visual_conf` + bbox | ESP32-CAM / webcam | synthetic bbox |
| `acoustic_scan.py` | **A5 acoustic** vector → `acoustic_conf` | USB mic | varied conf |
| `control_link_scan.py` | **Sub-GHz control links** (ELRS/Crossfire 433/868/915 MHz) via `rtl_power` | RTL-SDR V4 | synthetic hop |
| `adsb_scan.py` | **ADS-B 1090 MHz** manned-aircraft suppression via dump1090 | RTL-SDR V4 | fake aircraft |
| `lidar.py` | **TF-Luna LiDAR range** — checksum-validated frames, amp/range gating, median + EMA smoothing | TF-Luna UART | smooth mock range |
| `localize.py` | **3D localization** — bbox+pan/tilt → bearing, +range → ENU → GPS | pure math | n/a |
| `direction_finding.py` | **RF bearing** — rotate Yagi, RSSI peak (parabolic-interpolated) | Yagi + pan-tilt | mock lobe (~2°) |
| `pantilt.py` | **Pan-tilt auto-tracking** (PCA9685 servo PID re-centering) | PCA9685 + SG90/MG90 | records angles |
| `response.py` | **Deter-only response** — SSR spotlight/strobe + buzzer (NO jamming) | SSR relay + buzzer | prints intent |
| `display.py` | **On-device OLED** status | SSD1306 OLED | ASCII frame |
| `lora_mesh.py` | **LoRa mesh** relay of detections | SX1262 UART | loopback buffer |
| `recorder.py` | **Incident recorder** → `reports/incidents/<ts>/` (JSON + snapshot) | SD card | JSON only |
| `power_monitor.py` | **Battery telemetry** (voltage/current/%) | INA219 I2C | draining mock |
| `gps.py` | **NEO-6M GPS** — sensor's own position (NMEA parse); auto-fills the localization origin | NEO-6M UART | fixed mock fix |
| `health_monitor.py` | **System health** — CPU temp/%, RAM, disk, per-subsystem up/down | Pi thermal + psutil | best-effort/basic |
| `timeline.py` | **Event timeline** — groups the log into encounters + milestone lines | reads CSV | works on any log |
| `light_tower.py` | **Green→Red LED tower** by threat level (+buzzer on CRITICAL) | SMD LEDs + buzzer | prints lamp state |
| `spectrum_recorder.py` | **RF spectrum/IQ snapshot** for offline analysis + future training | RTL-SDR (rtl_power/rtl_sdr) | synthetic spectrum |
| `triangulate.py` | **Multi-node position** — cross-bearing + RSSI trilateration (honest TDOA alternative) | ≥2–3 nodes | pure math |

## New docs
- `ml/runtime/KISMET_SETUP.md` — full Pi + AR271 Kismet install (open-source), monitor
  mode, first-run login, env wiring, `--simulate-ssid` demo, troubleshooting.
- `ml/colab_train_rf.ipynb` — Colab T4 trainer for the 170 GB Kaggle RF dataset by
  **streaming** (download batch → featurize → discard), 4-class (real drone/noise +
  mock wifi/bluetooth), GPU XGBoost, drop-in `.pkl` artifacts.

## Modified files
| File | Change |
|------|--------|
| `ml/runtime/live_detector.py` | Fuses all new vectors; pan-tilt tracking + LiDAR localization; response/recorder/LoRa/OLED on escalation; new CLI flags + status header |
| `ml/a7_threat_scoring/threat_score.py` | Added `remote_id_decoded` (floors score at WARNING) and `aircraft_match` (−20 ADS-B suppression) |
| `ml/runtime/alerts.py` | CSV auto-rotates when the schema changes (new Remote ID / localization columns) |
| `requirements-runtime.txt` | Added `pyserial` (TF-Luna + LoRa UART); noted optional `bleak` |

---

## How detection + position now work

```
                 ┌──────────── RF PRESENCE (never position alone) ───────────┐
 RTL-SDR ──────► control_link_scan (433/868/915 MHz)  ─┐
 AR271/Kismet ─► Wi-Fi DroneID  ─┐                      │
 ESP32/BLE ────► BT Remote ID  ──┤ Remote ID = drone's  │
                                 │ own GPS (self-report) │
 USB mic ──────► acoustic_scan ──┼──────────────────────┼──► A7 THREAT SCORE
 ESP32-CAM ────► vision_scan ────┤                       │        │
                                 │                       │        ▼
                        camera bearing (az/el)           │   SAFE/WATCH/
                                 │                        │   WARNING/CRITICAL
   pan-tilt tracks the target ◄──┘                        │        │
                                 │                        │        ▼
   TF-Luna ─► range ─► localize(bearing + range) ─► GPS   │   response (spotlight)
                                                          │   recorder · LoRa · OLED
 RTL-SDR @1090 ─► adsb_scan ─► "that's a plane" ──────────┘   (−20 suppression)
```

**Position, honestly:**
- One omni RF receiver → **presence only**.
- Directional antenna (Yagi) rotated → **bearing** (a line, not a point).
- Two bearing nodes → **triangulation** → position (needs a 2nd node — not built yet).
- **Single node**: camera **bearing** + TF-Luna **range** → **GPS position** (built & verified).
- Remote ID → drone's **self-reported GPS** (compliant drones only).

---

## Run it free (no hardware)

```powershell
# One fused pass with a simulated DJI drone (Wi-Fi + BLE Remote ID + control-link)
python -m ml.runtime.live_detector --once --mock --simulate-ssid DJI-Mavic-1A2B `
    --track --lat 12.9716 --lon 77.5946 --no-buzzer --no-telegram

# Any single module's self-test, e.g.:
python -m ml.runtime.lidar --n 5
python -m ml.runtime.localize
python -m ml.runtime.direction_finding
python -m ml.runtime.kismet_scan --simulate-ssid DJI-Mavic-1A2B
```

Every subsystem prints its `mode` (`kismet`/`mock`, `tfluna`/`mock`, …) in the header,
so you always know whether it's on real hardware or mock.

---

## Honest limitations (do not oversell in the demo)

- **RTL-SDR V4 ≤ 1.766 GHz** — no live 2.4 GHz drone RF. Use Wi-Fi/BT Remote ID for
  2.4 GHz drones; RTL-SDR for control-link + ADS-B only.
- **TF-Luna ≤ ~8 m** — precise position for *close* drones; beyond 8 m the system
  correctly degrades to **bearing-only** (no fabricated range). Long range → TF03/radar.
- **wifi/bluetooth RF classes are mock-trained** until real captures exist.
- **nRF24L01** is a coarse 2.4 GHz *energy* flag only (no promiscuous mode) — not wired.
- **`pluto_control.py` is own-drone only** — it lands *your* allow-listed Pluto (legal, you
  own it), is **OFF by default** (`--pluto-land` + `--own-drone PLUTO` to arm), commands a
  controlled **LAND** (not a crash), and **refuses any drone not on your allow-list**. It does
  **no jamming or takeover** of third-party drones (illegal without authorization).

## Not done yet / next candidates
- **TF03 long-range LiDAR profile** for far drones (fusion math already supports it).
- **Dashboard / map / heatmap / remote UI** (lives in the **Part-B web repo**, not this
  backend) — the data it needs (GPS, bearings, node positions, timeline, health) is now
  all flowing / queryable.
- Real-hardware bring-up on the Pi (Kismet, camera, servos, LiDAR, GPS) per `KISMET_SETUP.md`.

## Deliberately NOT built (with reasons)
- **True LoRa TDOA** — needs sub-microsecond clock sync the hardware can't do; shipped
  **`triangulate.py`** (cross-bearing + RSSI multilateration) as the honest, working alternative.
- **Offline AI assistant / OTA updates / plugin-architecture refactor** — out of scope for a
  hackathon runway (matches the planning doc's own Tier-4 cuts).
- **YOLOv12** — not a stable release; stack stays on YOLOv8 (upgradeable to v11).
- **Raw IQ+audio+video replay** — `recorder.py` already saves per-incident evidence;
  `spectrum_recorder.py` saves RF snapshots. Full raw replay deferred.

## Planning-doc coverage (round 2)
Built the genuinely-missing items from the tiered plan: **event timeline**, **health
monitoring** (CPU/RAM/disk/subsystem status), **NEO-6M GPS reader** (auto sensor origin),
**Green→Red light tower**, **RF spectrum recorder**, and **multi-node triangulation**.
Dashboard-family items stay in Part B; Tier-4 items intentionally cut.
