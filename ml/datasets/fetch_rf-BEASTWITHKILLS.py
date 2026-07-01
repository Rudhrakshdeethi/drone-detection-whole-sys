"""Fetch REAL RF IQ data (A1) — sgluege/noisy-drone-rf-signal-classification-v2.

Real IQ recordings of consumer drones augmented with noise (Kaggle). Each sample
is a PyTorch .pt dict: {'x_iq': [2 x N] real/imag, 'y': class idx, 'snr': dB}.
Class names come from class_stats.csv; the 'Noise' class -> our noise folder,
every drone class -> our drone folder. Output: dataset/{drone,noise}/*.bin

    python -m ml.datasets.fetch_rf                  # download/adapt
    python -m ml.datasets.fetch_rf --max-per-class 150

NO Kaggle API token required: either drop the manually-downloaded .zip into
dataset/_raw/rf_v2/ and re-run, or use a token. See ml/datasets/kaggle_helper.py.
Falls back to a clear message (mock data keeps working) if data is missing.
"""
from __future__ import annotations
import os, sys, argparse
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import DATASET_DIR
from ml.common.iq import save_iq
from ml.datasets.kaggle_helper import download_dataset

SLUG = "sgluege/noisy-drone-rf-signal-classification-v2"
RAW = os.path.join(DATASET_DIR, "_raw", "rf_v2")


def _load_class_names(raw_dir):
    import csv
    for root, _, files in os.walk(raw_dir):
        if "class_stats.csv" in files:
            with open(os.path.join(root, "class_stats.csv")) as f:
                rows = list(csv.DictReader(f))
            col = "class" if rows and "class" in rows[0] else list(rows[0])[0]
            return [r[col] for r in rows]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-class", type=int, default=150)
    ap.add_argument("--samples", type=int, default=65536,
                    help="IQ samples kept per file (trim huge captures)")
    args = ap.parse_args()

    import torch  # the .pt files need torch to load

    # Ensures data is present: uses an already-extracted copy, a manually
    # downloaded .zip dropped into RAW (no token), or the Kaggle API.
    if not download_dataset(SLUG, RAW, unzip=True):
        sys.exit(1)

    class_names = _load_class_names(RAW)
    if class_names:
        print(f"[rf] classes in dataset: {class_names}")

    pt_files = []
    for root, _, files in os.walk(RAW):
        for f in files:
            if f.startswith("IQdata_sample") and f.endswith(".pt"):
                pt_files.append(os.path.join(root, f))
    if not pt_files:
        sys.exit("[rf] no IQdata_sample*.pt files found — inspect dataset/_raw/rf_v2")
    print(f"[rf] found {len(pt_files)} IQ samples")

    counts = {"drone": 0, "noise": 0}
    for path in sorted(pt_files):
        if all(c >= args.max_per_class for c in counts.values()):
            break
        try:
            d = torch.load(path, map_location="cpu", weights_only=False)
        except Exception:
            continue
        iq = np.asarray(d["x_iq"])
        y = int(d["y"]) if np.ndim(d["y"]) == 0 else int(np.asarray(d["y"]).ravel()[0])
        name = class_names[y] if class_names and y < len(class_names) else str(y)
        cls = "noise" if name.lower().startswith("noise") else "drone"
        if counts[cls] >= args.max_per_class:
            continue
        s = (iq[0, :] + 1j * iq[1, :]).astype(np.complex64)[:args.samples]
        # normalise to ~[-1,1] for our uint8 IQ writer
        s = s / (np.max(np.abs(s)) + 1e-9)
        out = os.path.join(DATASET_DIR, cls)
        os.makedirs(out, exist_ok=True)
        save_iq(os.path.join(out, f"real_{cls}_{counts[cls]:05d}.bin"), s)
        counts[cls] += 1

    print(f"[rf] real captures -> drone={counts['drone']}  noise={counts['noise']}")
    print("Note: this dataset has no wifi/bluetooth classes — keep those mock,")
    print("      or record real wifi/bt with your RTL-SDR. Then retrain:")
    print("      python -m ml.a1_rf_classifier.train")


if __name__ == "__main__":
    main()
