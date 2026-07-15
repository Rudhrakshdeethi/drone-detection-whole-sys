# CampusShield — ML Subsystem (Part A)

> **New here / just want to run it?** → **[RUN.md](RUN.md)** has every command
> (laptop mock + Raspberry Pi real). **[learn.md](learn.md)** explains how the
> whole workflow works line by line. **[HARDWARE.md](HARDWARE.md)** is the
> pre-demo provisioning checklist.

Machine-learning stack for the drone-detection system. Everything here involves
**training data → model → inference**. Part B (DSP / engineering / integration)
lives elsewhere and is intentionally kept out of this folder.

All 10 tasks are scaffolded, runnable today on **mock data that mimics real
2.4 GHz signals**, and designed so you drop in real recordings later *without
code changes* — just put real files in the same `dataset/` folders.

---

## Quick start

```powershell
# 1. Environment (Windows PowerShell)
powershell -ExecutionPolicy Bypass -File setup.ps1          # core stack
powershell -ExecutionPolicy Bypass -File setup.ps1 -Deep    # + torch/yolo/librosa

# 2. Activate
.\.venv\Scripts\Activate.ps1

# 3. Run the whole core pipeline (gen data → train → eval → fusion demo)
python run_all.py            # A1,A2,A6,A7,A8,A9,A10  (fast, CPU)
python run_all.py --deep     # also A3 spectrogram CNN + A5 acoustic CNN
```

Outputs land in `models/` (artifacts) and `reports/` (A9 tables + plots).

---

## Live detection (real-time runtime) — `ml/runtime/`

The tasks above are the **offline brain** (train / evaluate). The runtime layer is
the **real-time front-end** that makes the system behave like a deployed detector:
a continuous loop that captures live RF, runs it through the ML stack, and fires
physical alerts — the same shape as the original Team-Nayara single-file detector,
but driven by a confident, explained ML verdict instead of a raw power threshold.

```
capture (RTL-SDR @ 2.44 GHz) ─► A1 RF class ─► A2 fingerprint ─► A6 anomaly
        + Wi-Fi SSID scan ────────────────────────────────────┘
                                   └─► A7 threat score ─► A8 explanation
                                            └─► alert cascade: CSV + buzzer(GPIO18) + Telegram
```

```powershell
# Laptop demo (no SDR needed — runs on mock captures, console + CSV only):
python -m ml.runtime.live_detector --once --mock --simulate DJI_Mavic
python -m ml.runtime.live_detector --mock            # continuous mock loop

# Raspberry Pi (real RTL-SDR + buzzer + Telegram). Auto-detects hardware:
$env:TELEGRAM_BOT_TOKEN="..."; $env:TELEGRAM_CHAT_ID="..."
python -m ml.runtime.live_detector --interval 2 --threshold 60
```

It auto-switches: **real** `rtl_sdr` + GPIO buzzer + `nmcli` Wi-Fi scan when present
(the Pi), **mock/no-op** otherwise (this laptop) — same command either way. Needs
A1 trained first (`python run_all.py`); A2/A6 load if trained, else skip cleanly.
Pi extras: `pip install -r requirements-runtime.txt` + `sudo apt install rtl-sdr`.
Detections are appended to `reports/live_detections.csv`. Full reference:
[`ml/runtime/README.md`](ml/runtime/README.md).

---

## Full walkthrough — what to do, step by step

If you just cloned this repo and want to go from zero to real results, follow
these in order. Steps 1–4 need **no datasets and no accounts** — they run on
mock data. Steps 5–7 swap in real public data.

### Step 0 — Prerequisites
- **Python 3.10+** on PATH (`python --version`).
- **Git**, to clone the repo.
- Windows PowerShell (commands below are PowerShell). On macOS/Linux use the
  equivalent `python3 -m venv .venv && source .venv/bin/activate`.

### Step 1 — Clone and enter the repo
```powershell
git clone <this-repo-url> drone-detection-whole-sys
cd drone-detection-whole-sys
```

### Step 2 — Install dependencies
```powershell
# core stack only (A1/A2/A6/A7/A8/A9/A10) — installs in seconds
powershell -ExecutionPolicy Bypass -File setup.ps1

# OR core + deep-learning extras (adds A3 CNN, A4 YOLO, A5 acoustic; ~2 GB)
powershell -ExecutionPolicy Bypass -File setup.ps1 -Deep
```

### Step 3 — Activate the environment
```powershell
.\.venv\Scripts\Activate.ps1
```
You should see `(.venv)` at the start of your prompt. Re-run this in every new
terminal.

### Step 4 — Run the whole pipeline on mock data (proves it works)
```powershell
python run_all.py            # core tasks, fast, CPU-only
python run_all.py --deep     # also A3 spectrogram CNN + A5 acoustic CNN
```
This generates synthetic data, trains every model, runs the evaluation harness,
and prints the fusion demo. When it finishes, look in:
- `models/` — trained model artifacts
- `reports/` — A9 distance + false-positive tables and plots

> Mock accuracies look very high because synthetic classes are cleanly
> separable. Real numbers come from steps 5–7.

### Step 5 — Get REAL data
No physical drones needed — these pull real public datasets into the same
folders the trainers already read.

**Audio (A5) — fully automatic, no account:**
```powershell
python -m ml.datasets.fetch_audio --max 300
```

**RF (A1) and Vision (A4) — from Kaggle, NO API token needed:**
1. Run the fetcher once to see the exact URL + target folder it wants:
   ```powershell
   python -m ml.datasets.fetch_rf          # for RF IQ data
   python -m ml.datasets.fetch_vision      # for drone images
   ```
2. Open the printed Kaggle page in a browser and click **Download**
   (a free Kaggle login may be asked — that's a normal account, not a token).
3. Move the downloaded `.zip` into the folder the fetcher printed
   (`dataset/_raw/rf_v2/` or `dataset/_raw/yolo_drone/`). **Leave it zipped.**
4. Re-run the same fetch command — it extracts and adapts automatically.

(Full table + the optional API-token path are in
[Swapping mock data for real data](#swapping-mock-data-for-real-data) below.)

### Step 6 — Retrain on the real data
```powershell
python -m ml.a1_rf_classifier.train      # after fetch_rf
python -m ml.a5_acoustic.train --epochs 8   # after fetch_audio (needs -Deep)
python -m ml.a4_yolo_vision.train --epochs 30   # after fetch_vision (needs -Deep)
```
No code changes — the trainers read the same folders whether the files are mock
or real.

### Step 7 — Run the experiments judges ask for first
```powershell
python -m ml.a9_evaluation.distance_test
python -m ml.a9_evaluation.false_positive_test
```
Results (tables + plots) land in `reports/`. These are the *honest* real-world
numbers — see [Known mock-data caveats](#known-mock-data-caveats-be-honest-in-the-demo).

### Troubleshooting
- **`Activate.ps1 cannot be loaded`** → run PowerShell as the same user and use
  the `-ExecutionPolicy Bypass` form shown in Step 2, or
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- **A3/A4/A5 import errors (torch/ultralytics/librosa)** → you skipped `-Deep`;
  re-run `setup.ps1 -Deep`.
- **Fetcher says "no data"** → you haven't dropped the Kaggle `.zip` in yet, or
  you unzipped it manually (leave it zipped; the fetcher extracts it).

---

## Task status (verified end-to-end on this machine)

| Task | What it does | Algorithm | Status |
|------|--------------|-----------|--------|
| **A1** | RF classifier: noise/drone/wifi/bluetooth + conf% | RF / XGBoost / SVM (best by CV) | ✅ runs |
| **A2** | RF fingerprint: exact drone model | SVM (RBF) | ✅ runs (~86% mock) |
| **A3** | Spectrogram CNN, 4-class | MobileNetV2 transfer (PyTorch) | ✅ runs (~98% mock) |
| **A4** | YOLOv8 vision — laptop cam **and** ESP-EYE | YOLOv8n fine-tune | ✅ trains + infers |
| **A5** | Acoustic: drone/noise/motor | CNN on MFCC (PyTorch) | ✅ runs |
| **A6** | Unknown-drone anomaly detection | Isolation Forest | ✅ runs |
| **A7** | Threat scoring 0–100 + level | Weighted ensemble + rules | ✅ runs |
| **A8** | Explainable AI: "detected because…" | feature_importances_ + SHAP | ✅ runs |
| **A9** | Distance test + false-positive analysis | evaluation harness | ✅ runs |
| **A10** | Dataset versioning registry | JSON log | ✅ runs |

> Mock-data accuracies are high because synthetic classes are cleanly separable.
> **Real-world numbers come from A9** once you record real captures — that gap is
> the point of the distance/false-positive experiments.

---

## Folder layout

```
ml/
  common/            config.py · iq.py · rf_synth.py · bus.py   (shared)
  a1_rf_classifier/  feature_extraction.py · generate_mock_data · train · infer
  a2_fingerprinting/ generate_mock_data · train · infer
  a3_spectrogram_cnn/make_spectrograms · train · infer
  a4_yolo_vision/    collect_laptop_camera_images · make_synthetic_images · train · infer
  a5_acoustic/       generate_mock_audio · features · model · train · infer
  a6_anomaly/        train · infer
  a7_threat_scoring/ threat_score.py
  a8_explainability/ explain.py
  a9_evaluation/     distance_test.py · false_positive_test.py
  a10_registry/      registry.py
  fusion_demo.py     A1→A2→A6→A5 → A7 score → A8 explanation
dataset/   models/   reports/        (git-ignored; regenerable)
run_all.py   setup.ps1   requirements-core.txt   requirements-deep.txt
```

---

## Run any task individually

```powershell
# A1  RF classifier
python -m ml.a1_rf_classifier.generate_mock_data --per-class 120
python -m ml.a1_rf_classifier.train
python -m ml.a1_rf_classifier.infer dataset/drone/drone_0000.bin

# A2  fingerprint
python -m ml.a2_fingerprinting.generate_mock_data --per-model 100
python -m ml.a2_fingerprinting.train

# A3  spectrogram CNN   (needs -Deep)
python -m ml.a3_spectrogram_cnn.make_spectrograms
python -m ml.a3_spectrogram_cnn.train --epochs 5

# A4  YOLOv8            (needs -Deep)
python -m ml.a4_yolo_vision.make_synthetic_images --per-class 60
python -m ml.a4_yolo_vision.train --epochs 30
python -m ml.a4_yolo_vision.infer                                  # laptop webcam
python -m ml.a4_yolo_vision.infer --source http://ESP_EYE_IP:81/stream   # A4b

# A5  acoustic          (needs -Deep)
python -m ml.a5_acoustic.generate_mock_audio --per-class 80
python -m ml.a5_acoustic.train --epochs 8

# A6  anomaly  /  A7 threat  /  A8 explain
python -m ml.a6_anomaly.train
python -m ml.a7_threat_scoring.threat_score
python -m ml.a8_explainability.explain dataset/drone/drone_0000.bin

# A9  experiments (judges ask for these first)
python -m ml.a9_evaluation.distance_test
python -m ml.a9_evaluation.false_positive_test

# A10 register a recording session
python -m ml.a10_registry.registry --drone DJI_Tello --distance 20 \
    --location Lab_Room3 --weather indoor_clear --files 30
```

---

## Swapping mock data for real data

The on-disk format **already matches `rtl_sdr`** (interleaved uint8 I/Q), so:

1. Record real captures and drop `.bin` files into `dataset/<class>/` (A1) or
   `dataset/fingerprint/<model>/` (A2). Delete/keep mock files as you wish.
2. Re-run the relevant `train.py`. No code change needed.
3. Log the session with A10 so every dataset version is traceable.

### Real-dataset fetchers (since you have no physical drones)

One command per modality pulls a real public dataset and adapts it into the same
`dataset/` folders the trainers already read — **no code changes**, mock stays as
fallback. **No Kaggle API token is required** (see the manual path below).

```powershell
# A5 audio — REAL, fully automatic, no login (saraalemadi/DroneAudioDataset, ~281 MB)
python -m ml.datasets.fetch_audio --max 300
python -m ml.a5_acoustic.train --epochs 8

# A1 RF — REAL IQ data (Kaggle: sgluege/noisy-drone-rf-signal-classification-v2)
python -m ml.datasets.fetch_rf --max-per-class 150
python -m ml.a1_rf_classifier.train

# A4 vision — REAL images, YOLO format (Kaggle: muki2003/yolo-drone-detection-dataset)
python -m ml.datasets.fetch_vision
python -m ml.a4_yolo_vision.train --epochs 30
```

The **audio** fetcher needs nothing — it downloads from GitHub automatically.
The **RF** and **vision** datasets live on Kaggle. Get them with **no API token**:

#### Getting the Kaggle data WITHOUT an API token (browser download)

This is the recommended path — anyone can do it, no `kaggle.json` needed.

1. **Run the fetcher once.** It will say it has no data and print the exact
   Kaggle URL plus the folder to drop the file into. For reference:

   | Fetcher | Kaggle page to download from | Drop the `.zip` into |
   |---------|------------------------------|----------------------|
   | `fetch_rf` | `https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2` | `dataset/_raw/rf_v2/` |
   | `fetch_vision` | `https://www.kaggle.com/datasets/muki2003/yolo-drone-detection-dataset` | `dataset/_raw/yolo_drone/` |

2. **Open the page in a browser** and click **Download** (a free Kaggle login
   may be required — that's a normal account, *not* an API token).
3. **Move the downloaded `.zip`** into the folder shown above.
   ⚠️ Leave it zipped — **do not unzip it yourself**; the fetcher does that.
4. **Re-run the same command.** It finds the `.zip`, extracts it, and adapts it
   into the trainer's folders automatically.

```powershell
# example: after dropping the RF zip into dataset/_raw/rf_v2/
python -m ml.datasets.fetch_rf --max-per-class 150   # extracts + adapts, no token
python -m ml.a1_rf_classifier.train
```

#### Optional: API token (only if you want full automation)

1. kaggle.com → Account → *Create New API Token* → downloads `kaggle.json`
2. Move it to `%USERPROFILE%\.kaggle\kaggle.json`
3. Re-run the fetcher — it now downloads on its own.

Mapping & caveats the fetchers print for you:
- **Audio**: `yes_drone → drone`, `unknown (ESC-50/silence) → noise`. Keep the
  mock `motor` class for 3-class, or drop it.
- **RF**: real classes are *drone models + Noise* → mapped to `drone` / `noise`.
  This dataset has **no wifi/bluetooth** — keep those two classes mock, or record
  real wifi/bt with an RTL-SDR later. A2 fingerprinting stays **mock-only** (you
  have no drones to fingerprint).
- **Vision**: already YOLO-format; the fetcher locates/copies its `data.yaml`.

---

## Engineering decisions (why it differs slightly from the brief)

- **One DL framework (PyTorch), not Keras+Torch.** A3 uses `torchvision`'s
  MobileNetV2 (same architecture the brief specifies); A4 uses Ultralytics YOLO;
  A5 uses a small Torch CNN. Saves ~2.5 GB and avoids TF/Torch version clashes.
- **Single canonical IQ format** (`ml/common/iq.py`) shared by the mock
  generator, feature extractor, and future real captures — so files and the
  734-feature extractor can never disagree. (The feature vector is actually 735
  values; the brief rounds it to "734".)
- **Tiered installs.** Core (A1/A2/A6/A7/A8/A9/A10) installs in seconds; deep
  (A3/A4/A5) is opt-in.
- **MQTT is optional** (`ml/common/bus.py` no-ops without a broker) so ML dev
  never blocks on the messaging layer.
- **A7 bugfix:** the brief's `level='SAFE','n'` made `level` a tuple; fixed to a
  proper level + icon.

---

## Milestone mapping (from the project brief)

| Milestone | ML deliverables |
|-----------|-----------------|
| **M1 (W3–4)** | A1 RF classifier, A2 fingerprint, A4 vision, A5 acoustic data + first models |
| **M2** | A3 spectrogram CNN, A6 anomaly, A7 threat scoring; A4b ESP-EYE source |
| **M3** | A8 explainability, A9 distance + false-positive report, A10 versioning, final fusion |

---

## Known mock-data caveats (be honest in the demo)

- Distance test shows ~100% at all ranges because the synthetic drone stays
  distinct even at low SNR — **real captures will degrade with range**; that's
  what the experiment measures.
- False-positive test flags **microwave ovens ~96% as "drone"** — a real,
  expected failure mode (wide continuous 2.45 GHz looks drone-like). Fix per the
  brief: add a `microwave` class or a bursting/duty-cycle filter. This is a great
  finding to show judges, not something to hide.
```
