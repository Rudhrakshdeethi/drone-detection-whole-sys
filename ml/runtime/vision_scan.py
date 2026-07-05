"""A4 vision vector for the fusion loop — laptop webcam or ESP32-CAM stream.

The live detector fuses RF, Wi-Fi/Remote-ID and (optionally) sound; this module
adds the *camera* vector by wrapping the A4 YOLO drone detector behind the same
tiny, poll-once interface the rest of the runtime uses (`.read()` + `.mode`).

Seamless degradation — identical to the rest of the runtime:
    * webcam/ESP32-CAM reachable + ultralytics + cv2 + weights present
                                          -> real YOLO detections each frame.
    * any of cv2 / ultralytics / camera / weights missing (e.g. a bare Windows
      laptop)                             -> mock, so the fusion loop still runs.
    * `simulate=True`                     -> mock only, forced, for hardware-free
                                             demos that still light up the camera
                                             vector.

    vs = VisionScanner(source=0)                 # laptop webcam index 0
    vs = VisionScanner(source="http://ESP_IP:81/stream")   # ESP32-CAM MJPEG
    hit = vs.read()
    # {"confidence": 0.0..1.0, "bbox": (cx,cy,w,h)|None, "label": str,
    #  "source": "yolo"|"mock"}

`confidence` is the highest drone-class probability in the frame; `bbox` is that
detection's box as normalised (cx, cy, w, h) in [0, 1], or None when nothing
drone-like is seen.
"""
from __future__ import annotations
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import A4_YOLO_MODEL, VISION_CLASSES

# The class name A4 was trained to flag; keep in step with VISION_CLASSES[0].
DRONE_CLASS = VISION_CLASSES[0]


class VisionScanner:
    """Grab one frame and report the strongest drone detection (mock fallback)."""

    def __init__(self, source=0, force_mock: bool = False, simulate: bool = False,
                 weights: str = A4_YOLO_MODEL, conf: float = 0.4,
                 seed: int | None = None):
        self.source = source            # webcam index (0) or MJPEG stream URL
        self.weights = weights
        self.conf = float(conf)
        self.simulate = simulate
        self.force_mock = force_mock
        self.rng = np.random.default_rng(seed)
        self._warned = False
        self._cv2 = None
        self._model = None
        self._cap = None
        # "real" = we managed to load YOLO + open the camera; else we mock.
        self.real = (not force_mock and not simulate and self._setup())

    # ---- availability ---------------------------------------------------------
    def _setup(self) -> bool:
        """Lazily import cv2 + ultralytics, load weights, open the source.

        Every heavy import lives here so the module imports (and __main__ runs)
        on a laptop with none of cv2/ultralytics/torch installed.
        """
        try:
            import cv2
            from ultralytics import YOLO
        except Exception:
            return False
        try:
            weights = self.weights if os.path.exists(self.weights) else "yolov8n.pt"
            model = YOLO(weights)                       # may download pretrained
            src = 0 if self.source in (0, "0") else self.source
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                cap.release()
                return False
        except Exception:
            return False
        self._cv2, self._model, self._cap = cv2, model, cap
        return True

    # ---- real YOLO ------------------------------------------------------------
    def _read_yolo(self) -> dict:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("frame grab failed")
        res = self._model.predict(frame, conf=self.conf, verbose=False)[0]
        names = res.names
        best_conf, best_box = 0.0, None
        for b in res.boxes:
            if names[int(b.cls)] != DRONE_CLASS:
                continue
            c = float(b.conf)
            if c > best_conf:
                best_conf = c
                # xywhn = normalised (cx, cy, w, h) in [0, 1].
                xywhn = b.xywhn[0].tolist()
                best_box = (round(xywhn[0], 4), round(xywhn[1], 4),
                            round(xywhn[2], 4), round(xywhn[3], 4))
        return {"confidence": round(best_conf, 3), "bbox": best_box,
                "label": DRONE_CLASS if best_box else "clear", "source": "yolo"}

    # ---- mock -----------------------------------------------------------------
    def _read_mock(self) -> dict:
        """Mostly-clear frames with the occasional plausible centred drone."""
        if self.rng.random() < 0.35:                    # a drone this frame
            conf = float(self.rng.uniform(0.6, 0.9))
            cx = float(np.clip(0.5 + self.rng.normal(0, 0.08), 0.1, 0.9))
            cy = float(np.clip(0.5 + self.rng.normal(0, 0.08), 0.1, 0.9))
            w = float(self.rng.uniform(0.08, 0.22))
            h = float(self.rng.uniform(0.06, 0.18))
            return {"confidence": round(conf, 3),
                    "bbox": (round(cx, 4), round(cy, 4), round(w, 4), round(h, 4)),
                    "label": DRONE_CLASS, "source": "mock"}
        return {"confidence": round(float(self.rng.uniform(0.0, 0.15)), 3),
                "bbox": None, "label": "clear", "source": "mock"}

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """Return one frame's strongest drone hit. Falls back to mock on error."""
        if self.real:
            try:
                return self._read_yolo()
            except Exception as e:      # camera unplugged mid-run, decode error…
                if not self._warned:
                    print(f"[vision] read failed ({type(e).__name__}: {e}); "
                          f"using mock this frame")
                    self._warned = True
                return self._read_mock()
        return self._read_mock()

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    @property
    def mode(self) -> str:
        if self.simulate:
            return "mock(sim)"
        return "yolo" if self.real else "mock"


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="A4 vision drone scanner (mock-safe)")
    p.add_argument("--source", default="0",
                   help="0=webcam | http://ESP_IP:81/stream | video path")
    p.add_argument("--simulate", action="store_true",
                   help="force mock drone frames — no camera/weights needed")
    p.add_argument("-n", "--frames", type=int, default=5,
                   help="how many read() results to print (default 5)")
    args = p.parse_args(argv)
    src = 0 if args.source == "0" else args.source
    vs = VisionScanner(source=src, simulate=args.simulate)
    print(f"mode: {vs.mode}")
    for i in range(args.frames):
        print(f"frame {i}: {json.dumps(vs.read())}")
    vs.close()


if __name__ == "__main__":
    main()
