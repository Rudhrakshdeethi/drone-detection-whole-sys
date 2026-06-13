"""Fetch REAL drone images (A4) — muki2003/yolo-drone-detection-dataset (Kaggle).

Already in YOLO format (images + labels). This downloads it and writes/locates a
data.yaml our trainer can use, then prints the train command.

    python -m ml.datasets.fetch_vision

NO Kaggle API token required: either drop the manually-downloaded .zip into
dataset/_raw/yolo_drone/ and re-run, or use a token. See ml/datasets/kaggle_helper.py.
"""
from __future__ import annotations
import os, sys, glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import DATASET_DIR
from ml.datasets.kaggle_helper import download_dataset

SLUG = "muki2003/yolo-drone-detection-dataset"
RAW = os.path.join(DATASET_DIR, "_raw", "yolo_drone")


def main():
    # Ensures data is present: uses an already-extracted copy, a manually
    # downloaded .zip dropped into RAW (no token), or the Kaggle API.
    if not download_dataset(SLUG, RAW, unzip=True):
        sys.exit(1)

    # Prefer a shipped data.yaml; else locate train/val image dirs.
    yamls = glob.glob(os.path.join(RAW, "**", "*.yaml"), recursive=True) + \
            glob.glob(os.path.join(RAW, "**", "*.yml"), recursive=True)
    if yamls:
        print(f"[vision] dataset data.yaml found: {yamls[0]}")
        print("Train with it directly:")
        print(f'  python -m ml.a4_yolo_vision.train --epochs 30   '
              f'# edit train.py "data=" or pass this yaml')
        # write a convenience copy at our standard location
        target = os.path.join(DATASET_DIR, "drone_visual", "data_real.yaml")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(yamls[0]) as f:
            content = f.read()
        open(target, "w").write(content)
        print(f"[vision] copied -> {target}")
    else:
        train_dirs = glob.glob(os.path.join(RAW, "**", "train", "images"),
                               recursive=True)
        print(f"[vision] no data.yaml shipped. Image dirs found: {train_dirs}")
        print("         Create a data.yaml pointing at train/val images + labels,")
        print("         classes: ['drone']. See ml/a4_yolo_vision/make_synthetic_images.py")
    print(f"[vision] raw data under: {RAW}")


if __name__ == "__main__":
    main()
