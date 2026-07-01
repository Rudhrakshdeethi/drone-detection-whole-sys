# WHAT TO DO — CampusShield drone detection, end to end

A practical, command-by-command guide: from a fresh clone, to running on mock
data, to training on **real** captures with an RTL-SDR, to running the live
detector, to wiring in cheap **ESP32 edge sensors**.

This is the "just tell me what to type" companion to `README.md`. Commands are
PowerShell (Windows); on the Raspberry Pi use the same commands with `python3`.

---

## 0. The mental model (read this once)

This project has two halves:

- **The brain (offline ML)** — `ml/a1 … a10`. Trains and evaluates models. Runs
  on mock data out of the box, on real data once you record/fetch it.
- **The runtime (real-time)** — `ml/runtime/`. A continuous loop that captures
  live RF, runs it through the brain, and fires physical alerts
  (CSV + buzzer + Telegram). This is what makes it a *deployed detector*.

**Where things run:**

| Job | Hardware |
|-----|----------|
| Full RF ML stack + fusion + alerts | Raspberry Pi + RTL-SDR (the brain) |
| Vision camera (A4) | ESP32-CAM / ESP-EYE → streams to the Pi |
| Wi-Fi/BLE sniffing (optional) | cheap ESP32 → reports to the Pi |
| **You cannot** run the ML on a classic Arduino | (2 KB RAM, no Python, no USB host) |

---

## 1. First run — prove it works on mock data (no hardware, no accounts)

```powershell
# install (core stack, seconds)
powershell -ExecutionPolicy Bypass -File setup.ps1
# OR core + deep learning (A3 CNN, A4 YOLO, A5 acoustic; ~2 GB)
powershell -ExecutionPolicy Bypass -File setup.ps1 -Deep

.\.venv\Scripts\Activate.ps1        # activate (every new terminal)

python run_all.py                    # generate data → train → eval → fusion
python run_all.py --deep             # also A3 + A5 deep models
```
Artifacts land in `models/`, reports in `reports/`. Mock accuracies look very
high because synthetic classes are cleanly separable — **real numbers come from
Section 3.**

Smoke-test the live loop with no hardware:
```powershell
python -m ml.runtime.live_detector --once --mock --simulate DJI_Mavic
python -m ml.runtime.live_detector --mock        # continuous mock loop
```

---

## 2. Connect the RF module (RTL-SDR)

```powershell
# Raspberry Pi:
sudo apt install rtl-sdr
# Windows: install the RTL-SDR driver with Zadig, then get the rtl-sdr CLI tools

rtl_test          # should list your dongle; Ctrl-C to stop
```
If `rtl_test` sees the dongle, the system will too — `ml/runtime/capture.py`
auto-detects `rtl_sdr` and stops using mock. No flags needed.

---

## 3. Treat real data — two modes

### Mode A — just RUN on real RF (no training)
Instant. Classifies whatever the antenna hears, live:
```powershell
python -m ml.runtime.live_detector --interval 2 --threshold 60
```
Works immediately, **but** uses the mock-trained brain — so judgments aren't yet
calibrated to real signals. Mode B fixes that.

### Mode B — IMPROVE the brain with real captures
The on-disk format **is** `rtl_sdr`'s output (interleaved uint8), so "recording
training data" = pointing `rtl_sdr` at the right folder. Trainers read those
folders unchanged — no code edits.

**3.1 Record labeled captures, one class at a time** (increment the filename,
record 50–150+ per class, vary distance/angle):
```powershell
# Wi-Fi (your router / phone hotspot)
rtl_sdr -f 2440M -s 2.4M -n 65536 dataset/wifi/wifi_0000.bin
# Bluetooth (pair earbuds / speaker so it's actively hopping)
rtl_sdr -f 2440M -s 2.4M -n 65536 dataset/bluetooth/bt_0000.bin
# Noise (point at a quiet part of the band)
rtl_sdr -f 2440M -s 2.4M -n 65536 dataset/noise/noise_0000.bin
# Drone (power/fly one nearby)
rtl_sdr -f 2440M -s 2.4M -n 65536 dataset/drone/drone_0000.bin
```

**3.2 No drone? Pull real drone + noise from Kaggle**, record only wifi/bt yourself:
```powershell
python -m ml.datasets.fetch_rf --max-per-class 150     # real drone + noise .bin
```
> NOTE: this Kaggle set has **no wifi/bluetooth** classes — record those two with
> your own RTL-SDR (your router and earbuds are enough).

**3.3 Retrain on the real folders:**
```powershell
python -m ml.a1_rf_classifier.train      # RF classifier on real captures
python -m ml.a6_anomaly.train            # anomaly baseline from real features
python -m ml.a3_spectrogram_cnn.train    # optional (needs -Deep)
```

**3.4 Get the honest numbers + log provenance:**
```powershell
python -m ml.a9_evaluation.distance_test
python -m ml.a9_evaluation.false_positive_test
python -m ml.a10_registry.registry --drone DJI_Tello --distance 20 --location Lab --files 50
```

**3.5 Real A2 fingerprinting (exact drone model):** capture each model into its
own folder, then train:
```powershell
# dataset/fingerprint/DJI_Tello/*.bin , dataset/fingerprint/DJI_Mavic/*.bin , ...
python -m ml.a2_fingerprinting.train
```
Needs access to the actual drone models (or the per-model labels from the Kaggle
set, which require un-collapsing in `ml/datasets/fetch_rf.py` first).

---

## 4. Train the other modalities on real data

### A5 — Acoustic (real, fully automatic, no account)
```powershell
python -m ml.datasets.fetch_audio --max 300     # real DroneAudioDataset
python -m ml.a5_acoustic.train --epochs 8        # needs -Deep
```

### A4 — Vision (real images, YOLO format)
```powershell
python -m ml.datasets.fetch_vision               # real Kaggle drone images
python -m ml.a4_yolo_vision.train --epochs 30     # needs -Deep
python -m ml.a4_yolo_vision.infer                 # laptop webcam
python -m ml.a4_yolo_vision.infer --source http://ESP_EYE_IP:81/stream   # ESP32-CAM
```

---

## 5. Run the live detector (deployment)

```powershell
# Raspberry Pi — real RTL-SDR + buzzer + Telegram (auto-detects hardware):
$env:TELEGRAM_BOT_TOKEN="123:abc"; $env:TELEGRAM_CHAT_ID="456"
python -m ml.runtime.live_detector --interval 2 --threshold 60
```

Pipeline per capture: capture → A1 RF class → A2 fingerprint → A6 anomaly →
Wi-Fi SSID scan → A7 threat score → A8 explanation → alert cascade.

Key flags:

| Flag | Meaning |
|------|---------|
| `--once` | single capture then exit (smoke test) |
| `--mock` | force mock even if an SDR is attached |
| `--simulate CLASS` | mock-only: force a class/model |
| `--simulate-ssid NAME` | inject a fake Wi-Fi SSID for demos |
| `--interval N` / `--threshold N` / `--cooldown N` | loop timing / escalation / alert de-dup |
| `--no-wifi` / `--no-csv` / `--no-buzzer` / `--no-telegram` | turn channels off |

Detections append to `reports/live_detections.csv`. Full reference:
`ml/runtime/README.md`.

**The improvement loop:** record → retrain → run live → record the cases it gets
wrong → retrain again. Each pass closes the gap between mock and your real site.

---

## 6. Cheap ESP32 edge sensors (recommended distributed setup)

You **cannot** run the ML on a classic Arduino (2 KB RAM, no Python, no USB host
for the SDR). The right pattern is a tiny board as a **sensor that reports to the
Pi brain**, not a brain on the chip.

| Board | Role | Status |
|-------|------|--------|
| **ESP32-CAM / ESP-EYE** | Vision sensor → streams MJPEG to the Pi's A4 YOLO | ✅ supported today (Section 4) |
| **Plain ESP32** | Wi-Fi/BLE sniffer → drone SSIDs + MAC prefixes → MQTT → A7 | ⚠️ needs a sketch + Pi wiring |
| **Raspberry Pi + RTL-SDR** | The brain — full RF ML + fusion + alerts | ✅ this repo |

Recommended architecture: **1 Pi (brain) + ESP32-CAM (eye) + optional ESP32
(ear).** The ESP firmware stays a few KB; all heavy ML stays on the Pi.

ESP32-CAM as the vision source is plug-and-play — flash a camera-stream firmware,
then run the A4 `--source http://ESP_EYE_IP:81/stream` command in Section 4.

---

## 7. Troubleshooting

- **`Activate.ps1 cannot be loaded`** → use the `-ExecutionPolicy Bypass` form, or
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- **A3/A4/A5 import errors (torch/ultralytics/librosa)** → you skipped `-Deep`;
  re-run `setup.ps1 -Deep`.
- **`rtl_sdr` not found** → install the rtl-sdr package (Section 2); until then the
  loop runs in mock mode.
- **Buzzer/Telegram silent on a laptop** → expected; GPIO is Pi-only and Telegram
  needs the two env vars. They no-op gracefully elsewhere.
- **Fetcher says "no data"** → drop the Kaggle `.zip` into the folder it prints and
  re-run; leave it zipped (the fetcher extracts it).
```
