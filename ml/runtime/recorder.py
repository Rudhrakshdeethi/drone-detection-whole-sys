"""Incident recorder — persist an escalation to the 256GB microSD for forensics.

When the threat fuser escalates, we snapshot the moment to disk so there's a
durable record independent of any network alert: one folder per incident under
REPORTS_DIR/incidents/<timestamp>/ containing:

    incident.json   the full detection row/dict (always written)
    snapshot.jpg    the camera frame, *only if* one is supplied and OpenCV is
                    available — the JSON never depends on cv2.

Seamless degradation — identical to the rest of the runtime:
    * cv2 installed + a frame passed  -> snapshot.jpg alongside the JSON.
    * No cv2 / no frame               -> JSON-only incident, still complete.

    rec = IncidentRecorder()
    path = rec.record(detection_row, frame=bgr_ndarray)   # -> incident dir
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import REPORTS_DIR

INCIDENTS_DIR = os.path.join(REPORTS_DIR, "incidents")


class IncidentRecorder:
    """Write each escalation to its own timestamped folder on disk."""

    def __init__(self, base_dir: str = INCIDENTS_DIR):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    # ---- helpers --------------------------------------------------------------
    def _new_dir(self) -> str:
        """A unique <YYYYmmdd-HHMMSS-ffffff> folder for this incident."""
        # Real wall-clock time (this runs live, not in a seeded workflow).
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = os.path.join(self.base_dir, stamp)
        os.makedirs(path, exist_ok=True)
        return path

    def _save_frame(self, path: str, frame) -> bool:
        """Best-effort JPEG snapshot; returns True only if cv2 wrote a file."""
        try:
            import cv2                              # optional — image only
        except Exception:
            return False
        try:
            return bool(cv2.imwrite(os.path.join(path, "snapshot.jpg"), frame))
        except Exception as e:
            print(f"[recorder] snapshot failed ({type(e).__name__}); JSON kept")
            return False

    # ---- public ---------------------------------------------------------------
    def record(self, row: dict, frame=None) -> str:
        """Persist one incident and return its directory path.

        `row` is always written to incident.json. If `frame` is provided and
        OpenCV is importable, a snapshot.jpg is added; otherwise the incident is
        JSON-only. Never requires cv2.
        """
        path = self._new_dir()
        payload = dict(row)
        payload.setdefault("recorded_at", datetime.now().isoformat(timespec="seconds"))
        with open(os.path.join(path, "incident.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        if frame is not None:
            self._save_frame(path, frame)
        return path


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Incident recorder self-test")
    p.add_argument("--base", default=INCIDENTS_DIR, help="incidents base dir")
    args = p.parse_args(argv)
    rec = IncidentRecorder(base_dir=args.base)
    fake = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "threat": "HIGH", "score": 0.93,
        "manufacturer": "DJI", "model": "Mavic 3", "serial": "SIM-1581F2E4A7B9",
        "source": "kismet(mock)",
    }
    path = rec.record(fake, frame=None)
    print(f"incident written to: {path}")
    print(f"  incident.json exists: {os.path.exists(os.path.join(path, 'incident.json'))}")


if __name__ == "__main__":
    main()
