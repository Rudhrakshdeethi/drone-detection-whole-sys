# Live runtime layer (`ml/runtime/`)

The real-time front-end. It turns the offline ML stack (A1–A10) into a
continuously-running detector with physical alerts — the **Team-Nayara detector's
shape** (scan → alert cascade) with the **CampusShield brain** swapped in.

Where the original repo flagged any RF bin over a fixed `-18 dB` threshold, this
runs every capture through the trained classifier + fingerprint + anomaly heads,
fuses them into a 0–100 threat score, and only then escalates — and tells you
*why* it escalated.

## Files

| File | Role |
|------|------|
| `capture.py` | Live IQ from `rtl_sdr` (Pi) or the mock synthesizer (laptop). Output is the exact interleaved-uint8 format the rest of the stack reads. |
| `wifi_scan.py` | `nmcli` SSID scan, matched against drone-name patterns (DJI/TELLO/MAVIC/…). The Team-Nayara second vector, fed in as extra evidence. |
| `alerts.py` | Alert cascade: CSV log + buzzer (GPIO 18) + Telegram, with a cooldown so a lingering drone doesn't spam you. |
| `live_detector.py` | The loop that wires capture → A1/A2/A6 → A7 → A8 → alerts. |

## Pipeline, per capture

1. **Capture** live IQ (`capture.py`) — RTL-SDR at 2.44 GHz, or mock.
2. **A1** RF classifier → noise/drone/wifi/bluetooth + confidence.
3. **A2** fingerprint → exact drone model (only when a drone looks present).
4. **A6** anomaly → known / unknown / suspicious (sets the unknown-model flag).
5. **Wi-Fi** SSID scan → drone-name match (optional, `--no-wifi` to disable).
6. **A7** threat score → 0–100 + SAFE/WATCH/WARNING/CRITICAL, with lingering-target
   and unknown-model modifiers. A named-SSID match is fed in as fingerprint-grade
   evidence and always escalates.
7. **A8** explanation → "detected because spectral occupancy 34%, entropy 31%…"
   (computed only on escalation — it's the expensive head).
8. **Alert cascade** (`alerts.py`) → always CSV-log; buzzer + Telegram when the
   score crosses `--threshold` (or any SSID match), gated by `--cooldown`.

## Run

```powershell
# Single smoke-test pass on a simulated drone (no hardware):
python -m ml.runtime.live_detector --once --mock --simulate DJI_Mavic

# Continuous mock loop on a laptop (console + CSV; buzzer/Telegram no-op):
python -m ml.runtime.live_detector --mock

# Real deployment on the Raspberry Pi:
sudo apt install rtl-sdr                          # provides rtl_sdr / rtl_power
pip install -r ../../requirements-runtime.txt     # requests, gpiozero, rpi.gpio
$env:TELEGRAM_BOT_TOKEN="123:abc"; $env:TELEGRAM_CHAT_ID="456"
python -m ml.runtime.live_detector --interval 2 --threshold 60
```

## Key flags

| Flag | Meaning |
|------|---------|
| `--once` | one capture then exit (smoke test) |
| `--mock` | force mock capture even if an SDR is attached |
| `--simulate CLASS` | mock-only: force `noise\|wifi\|bluetooth\|drone\|DJI_Mavic\|DJI_Tello\|Syma_X5C\|Parrot_Anafi` |
| `--simulate-ssid NAME` | inject a fake Wi-Fi SSID (e.g. `DJI-Mavic-1A2B`) for demos |
| `--interval N` | seconds between captures (default 2) |
| `--threshold N` | threat score that triggers buzzer+Telegram (default 60) |
| `--cooldown N` | min seconds between escalated alerts (default 30) |
| `--freq` / `--rate` / `--gain` | RTL-SDR tuning (defaults from `ml/common/config.py`) |
| `--no-wifi` / `--no-csv` / `--no-buzzer` / `--no-telegram` | turn channels off |

## Hardware auto-detection

Everything degrades gracefully, so the **same command** runs on both targets:

| Capability | Raspberry Pi | This laptop |
|------------|--------------|-------------|
| RF capture | real `rtl_sdr` | mock synthesizer |
| Wi-Fi scan | real `nmcli` | off (or `--simulate-ssid`) |
| Buzzer | GPIO 18 via gpiozero | no-op |
| Telegram | real (env vars) | real (env vars) |
| CSV log | `reports/live_detections.csv` | same |

If the SDR is unplugged mid-run, that capture falls back to mock and the loop
keeps going rather than crashing.

## Output

Every detection is appended to `reports/live_detections.csv`:

```
timestamp, source, rf_label, rf_confidence, drone_prob, fingerprint,
fingerprint_conf, wifi_ssids, unknown_model, duration_sec,
threat_score, threat_level, modifiers
```

Detections are also published best-effort to the `campusshield/detection` MQTT
topic (no-op if no broker), so the rest of the CampusShield system can subscribe.
