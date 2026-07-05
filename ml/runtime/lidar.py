"""TF-Luna LiDAR reader — turns the camera *bearing* into a 3D *position*.

This is the piece that converts "which direction" into "where": the camera +
pan-tilt give azimuth + elevation, this gives the *range*, and `localize()` fuses
them into an actual GPS fix from a single node.

Hardware: Benewake TF-Luna over UART (default 115200 baud, 8N1). Each reading is
a 9-byte frame:

    0x59 0x59  distL distH  ampL ampH  tempL tempH  checksum
    distance = distL + distH*256   (centimetres)
    amp      = signal strength (reliability of the return)
    temp     = tempL + tempH*256   (1/8 deg C, minus 256)
    checksum = low byte of the sum of the first 8 bytes

Honest limitation: the TF-Luna maxes out around **8 m**. It ranges *close* drones
precisely; a drone at 30 m is beyond it — for that you'd fit a long-range LiDAR
(TF03 ~100 m) or radar. The localization math is exact regardless; only the
sensor's reach is the ceiling. Out-of-range returns are reported as
`valid=False` so the fusion falls back to a bearing-only fix rather than lying.

Precision / "fine-tuning" built in:
  * header-synchronised, checksum-validated frame parser (rejects corrupt bytes)
  * amplitude + range gating — drops weak (amp<min), saturated (amp=0xFFFF), and
    out-of-band (<0.2 m or >8 m) returns
  * median-of-N outlier rejection + exponential smoothing (EMA) for a stable range
  * mock fallback so the whole localization path runs free on a laptop

    lr = LidarTFLuna().read()
    # {"range_m", "raw_range_m", "strength", "temp_c", "valid", "n", "source"}

Env: LIDAR_PORT (e.g. /dev/serial0 or COM5), LIDAR_BAUD.
"""
from __future__ import annotations
import os, sys, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

LIDAR_PORT = os.environ.get("LIDAR_PORT")           # None -> mock unless given
LIDAR_BAUD = int(os.environ.get("LIDAR_BAUD", "115200"))

HEADER = 0x59
MIN_RANGE_M = 0.2          # TF-Luna spec floor
MAX_RANGE_M = 8.0          # TF-Luna spec ceiling (be honest about this)
DEFAULT_MIN_AMP = 100      # Benewake: amp<100 => unreliable distance
SATURATION_AMP = 0xFFFF    # amp==65535 => target too close / too reflective


class LidarTFLuna:
    def __init__(self, port: str | None = LIDAR_PORT, baud: int = LIDAR_BAUD,
                 samples: int = 5, ema: float = 0.4, min_amp: int = DEFAULT_MIN_AMP,
                 force_mock: bool = False, simulate_range_m: float | None = None):
        self.port = port
        self.baud = int(baud)
        self.samples = max(1, int(samples))     # frames median-filtered per read
        self.ema = float(ema)                   # 0..1 smoothing (higher = snappier)
        self.min_amp = int(min_amp)
        self._sim = simulate_range_m
        self._ema_val: float | None = None
        self._t = 0                             # mock drift counter
        self._warned = False
        self._ser = None
        self.real = self._open() if (not force_mock and simulate_range_m is None
                                     and port) else False
        self._src = "tfluna" if self.real else "mock"

    # ---- serial ---------------------------------------------------------------
    def _open(self) -> bool:
        try:
            import serial                        # pyserial, optional
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
            return True
        except Exception as e:
            print(f"[lidar] serial open failed ({type(e).__name__}: {e}); "
                  f"using mock range")
            return False

    def _read_frame(self) -> tuple[float, int, float] | None:
        """Sync to the 0x59 0x59 header, validate checksum, decode one frame."""
        ser = self._ser
        for _ in range(self.samples * 12):       # bounded resync
            b = ser.read(1)
            if not b:
                return None
            if b[0] != HEADER:
                continue
            b2 = ser.read(1)
            if not b2 or b2[0] != HEADER:
                continue
            rest = ser.read(7)
            if len(rest) != 7:
                return None
            frame = bytes([HEADER, HEADER]) + rest
            if (sum(frame[:8]) & 0xFF) != frame[8]:
                continue                          # corrupt frame, keep scanning
            dist_cm = frame[2] + (frame[3] << 8)
            amp = frame[4] + (frame[5] << 8)
            temp_c = (frame[6] + (frame[7] << 8)) / 8.0 - 256.0
            return dist_cm / 100.0, amp, temp_c
        return None

    # ---- mock -----------------------------------------------------------------
    def _mock(self) -> dict:
        self._t += 1
        base = self._sim if self._sim is not None else 3.5
        r = base + 0.5 * math.sin(self._t / 7.0)      # slow, smooth drift
        r = min(MAX_RANGE_M, max(MIN_RANGE_M, r))
        self._ema_val = r if self._ema_val is None \
            else self.ema * r + (1 - self.ema) * self._ema_val
        return {"range_m": round(self._ema_val, 3), "raw_range_m": round(r, 3),
                "strength": 4200, "temp_c": 31.0, "valid": True,
                "n": self.samples, "source": "mock"}

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """One filtered range fix. valid=False when nothing passed the gates."""
        if not self.real:
            return self._mock()
        good: list[tuple[float, int, float]] = []
        try:
            for _ in range(self.samples * 2):     # oversample, keep the clean ones
                fr = self._read_frame()
                if fr is None:
                    continue
                r, amp, temp = fr
                if amp < self.min_amp or amp >= SATURATION_AMP:
                    continue                       # weak or saturated
                if not (MIN_RANGE_M <= r <= MAX_RANGE_M):
                    continue                       # out of the sensor's honest band
                good.append((r, amp, temp))
                if len(good) >= self.samples:
                    break
        except Exception as e:
            if not self._warned:
                print(f"[lidar] read failed ({type(e).__name__}: {e}); mock range")
                self._warned = True
            return self._mock()
        self._warned = False
        if not good:
            return {"range_m": None, "raw_range_m": None, "strength": 0,
                    "temp_c": None, "valid": False, "n": 0, "source": self._src}
        ranges = sorted(s[0] for s in good)
        med = ranges[len(ranges) // 2]             # median rejects single-frame spikes
        self._ema_val = med if self._ema_val is None \
            else self.ema * med + (1 - self.ema) * self._ema_val
        return {"range_m": round(self._ema_val, 3), "raw_range_m": round(med, 3),
                "strength": max(s[1] for s in good), "temp_c": round(good[-1][2], 1),
                "valid": True, "n": len(good), "source": self._src}

    @property
    def mode(self) -> str:
        return self._src

    def close(self) -> None:
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="TF-Luna LiDAR reader")
    p.add_argument("--port", default=LIDAR_PORT, help="serial port (e.g. COM5, /dev/serial0)")
    p.add_argument("--baud", type=int, default=LIDAR_BAUD)
    p.add_argument("--sim", type=float, default=None, help="mock a fixed range (m)")
    p.add_argument("--n", type=int, default=6, help="reads to print")
    args = p.parse_args(argv)
    ld = LidarTFLuna(port=args.port, baud=args.baud, simulate_range_m=args.sim)
    print(f"mode: {ld.mode}")
    for _ in range(args.n):
        print(json.dumps(ld.read()))
    ld.close()


if __name__ == "__main__":
    main()
