# Live runtime layer (`ml/runtime/`)

The real-time front-end. It turns the offline ML stack (A1–A10) into a continuously
running, **multi-sensor** detector that fuses every vector into a 0–100 threat score,
localizes the drone, and drives physical outputs — all with **graceful mock fallback**
so the exact same code runs on a laptop (no hardware) and on the Raspberry Pi (real
sensors). Each module prints its `mode` (`kismet`/`mock`, `tfluna`/`mock`, …) so you
always know whether it's live or simulated.

---

## Module index (by function)

### Core loop
| Module | Role |
|--------|------|
| `live_detector.py` | The loop: capture → all sensor vectors → A7 fusion → A8 explain → localization → actuation. Entry point. |
| `capture.py` | Live IQ from `rtl_sdr` (Pi) or the mock synthesizer (laptop); exact interleaved-uint8 format. |

### Detection sensors (presence)
| Module | Detects | Real hardware |
|--------|---------|---------------|
| `kismet_scan.py` | **Wi-Fi DroneID / Remote ID** (DJI + FAA) incl. drone & operator GPS | AR271 + Kismet |
| `ble_remoteid.py` | **Bluetooth Remote ID** (ASTM F3411 OpenDroneID) | ESP32 / BLE |
| `wifi_scan.py` | `nmcli` SSID match against drone-name patterns (fallback vector) | any Wi-Fi |
| `vision_scan.py` | **YOLOv8** camera detection (+ bbox) → `visual_conf` | ESP32-CAM / webcam |
| `acoustic_scan.py` | **A5 acoustic** MFCC classifier → `acoustic_conf` | USB mic |
| `control_link_scan.py` | **Sub-GHz control links** (ELRS/Crossfire 433/868/915 MHz) | RTL-SDR V4 |
| `adsb_scan.py` | **ADS-B 1090 MHz** manned-aircraft suppression | RTL-SDR V4 |

### Localization & tracking
| Module | Gives |
|--------|-------|
| `localize.py` | Camera bbox + pan/tilt → **bearing**; + range → ENU → **drone GPS** |
| `lidar.py` | **TF-Luna** range (checksum-validated, gated, median+EMA smoothed) |
| `direction_finding.py` | **RF bearing** from a rotating Yagi (RSSI peak, parabolic-interpolated) |
| `pantilt.py` | **PTZ auto-tracking** (PCA9685 servo PID re-centering) |
| `gps.py` | **NEO-6M** — the sensor's own position (auto-fills the localization origin) |
| `triangulate.py` | **Multi-node position** — cross-bearing + RSSI multilateration |

### Actuation & output
| Module | Does |
|--------|------|
| `alerts.py` | CSV log + buzzer (GPIO 18) + Telegram, with cooldown + schema-safe CSV rotation |
| `response.py` | Deter-only spotlight/strobe + buzzer (SSR relay) — **no jamming** |
| `light_tower.py` | Green→Yellow→Orange→Red LED tower by threat level (+buzzer on CRITICAL) |
| `display.py` | On-device OLED status (SSD1306) |
| `lora_mesh.py` | Relay detections to other nodes over SX1262 LoRa |
| `recorder.py` | Incident capture → `reports/incidents/<ts>/` (JSON + snapshot) |
| `pluto_control.py` | **Authorized OWN-drone LAND** (Pluto via MSP/WiFi). Allow-list-gated, OFF by default, land-only — never touches third-party drones (no jamming/takeover) |

### Ops & analysis
| Module | Does |
|--------|------|
| `power_monitor.py` | Battery telemetry (INA219: V / mA / %) |
| `health_monitor.py` | CPU temp/%, RAM, disk, per-subsystem up/down |
| `spectrum_recorder.py` | RF spectrum/IQ snapshots for offline analysis + training |
| `timeline.py` | Builds a per-encounter **event timeline** from the detection log |

---

## Pipeline, per capture

1. **Capture** live IQ (`capture.py`).
2. **A1** RF classifier → noise/drone/wifi/bluetooth + confidence.
3. **A2** fingerprint → exact model (when a drone looks present).
4. **A6** anomaly → known / unknown flag.
5. **Sensors** → Wi-Fi/BLE Remote ID (+GPS), vision, acoustic, sub-GHz control link.
6. **Localization** → pan-tilt tracks the target; camera bearing + LiDAR range + GPS
   origin → **drone position**; Remote ID GPS when broadcast.
7. **ADS-B** cross-check → suppress manned aircraft.
8. **A7** threat score → 0–100 + SAFE/WATCH/WARNING/CRITICAL (Remote ID floors at
   WARNING; aircraft match subtracts; lingering/unknown add).
9. **A8** explanation (on escalation).
10. **Actuation** → alerts (CSV/buzzer/Telegram) + response (spotlight) + light tower
    + OLED + LoRa relay + incident record.

---

## Run

```powershell
# Single smoke-test pass, simulated drone, no hardware:
python -m ml.runtime.live_detector --once --mock --simulate DJI_Mavic

# Full multi-sensor demo (Wi-Fi+BLE Remote ID, control-link, tracking, LiDAR, GPS origin):
python -m ml.runtime.live_detector --once --mock --simulate-ssid DJI-Mavic-1A2B --track

# Continuous mock loop on a laptop:
python -m ml.runtime.live_detector --mock

# Real deployment on the Pi:
sudo apt install rtl-sdr
pip install -r ../../requirements-runtime.txt      # requests, gpiozero, pyserial, ...
python -m ml.runtime.live_detector --interval 2 --threshold 60

# Any module standalone (prints its mock self-test):
python -m ml.runtime.lidar --n 5
python -m ml.runtime.timeline --last 2
python -m ml.runtime.triangulate
python -m ml.runtime.kismet_scan --simulate-ssid DJI-Mavic-1A2B
```

## Key flags

| Flag | Meaning |
|------|---------|
| `--once` / `--mock` | one pass then exit / force mock capture |
| `--simulate CLASS` | force `noise\|wifi\|bluetooth\|drone\|DJI_Mavic\|DJI_Tello\|Syma_X5C\|Parrot_Anafi` |
| `--simulate-ssid NAME` | inject a mock Remote ID drone (e.g. `DJI-Mavic-1A2B`) |
| `--track` | enable pan-tilt auto-tracking |
| `--lat` / `--lon` | sensor position (else taken from the NEO-6M GPS) |
| `--vision-source` | webcam index or ESP32-CAM `http://IP:81/stream` |
| `--interval` / `--threshold` / `--cooldown` | loop timing + escalation |
| `--no-wifi`/`-ble`/`-vision`/`-acoustic`/`-lidar`/`-response`/`-lora`/`-csv`/`-buzzer`/`-telegram` | turn vectors/outputs off |

## Hardware auto-detection

The **same command** runs on both targets; every capability degrades to mock/off:

| Capability | Raspberry Pi | This laptop |
|------------|--------------|-------------|
| RF capture | `rtl_sdr` | mock synth |
| Wi-Fi DroneID | Kismet + AR271 | `--simulate-ssid` |
| BLE Remote ID | `bleak` + BLE | `--simulate-ssid` |
| Vision | camera + YOLO | synthetic bbox |
| LiDAR / GPS | TF-Luna / NEO-6M | mock range / fixed origin |
| Servos / relay / LEDs / OLED / LoRa | GPIO/I2C/UART | printed no-ops |

If a sensor drops mid-run, that pass falls back to mock and the loop keeps going.

## Output

Each detection appends a **31-field record** to `reports/live_detections.csv` and is
mirrored to the `campusshield/detection` MQTT topic; escalations also write
`reports/incidents/<ts>/` (JSON + snapshot). Fields cover: time/source, RF class +
fingerprint + anomaly, Wi-Fi/BLE Remote ID (manuf/model/serial + drone & pilot GPS),
per-sensor confidences (visual/acoustic/control + band), localization
(loc_lat/lon/alt, azimuth, elevation, range_m), ADS-B suppression, and the fused
threat score/level/modifiers/duration. See `../../new-tings.md` for the full list.
```
