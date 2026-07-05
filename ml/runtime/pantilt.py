"""Pan-tilt closed-loop tracker — aim a 2-axis rig at a detected drone.

This is the *aiming* half of the response side: given a normalized bounding box
from the vision detector, it nudges a pan-tilt head so the target drifts back to
the centre of frame. Two SG90/MG90 servos ride a PCA9685 16-channel PWM driver
on the Raspberry Pi 5's I2C bus.

Seamless degradation — identical to the rest of the runtime:
    * PCA9685 present on I2C (adafruit_pca9685 + board/busio import & the chip
      ACKs)                       -> real servo PWM.
    * libs/hardware absent (e.g. a Windows laptop) -> a mock that just records
      the last commanded angles, so import and `__main__` still run anywhere.

The controller is deliberately simple: a proportional law on the bbox centre
offset. `track()` maps the horizontal/vertical error (scaled by the camera FoV)
into a small angular step and steers toward centre — no PID, no calibration rig
needed for a demo, and stable because each step is clamped and gain < 1.

    pt = PanTilt()                       # auto-detects PCA9685 or falls back
    pan, tilt = pt.track((0.8, 0.3, 0.1, 0.1))   # target high-right -> move
"""
from __future__ import annotations
import os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Standard hobby-servo pulse band (microseconds). SG90/MG90 honour ~0.5-2.5 ms
# across their full mechanical travel; we treat that as -90..+90 degrees.
SERVO_MIN_US = 500.0
SERVO_MAX_US = 2500.0
SERVO_RANGE_DEG = 180.0
PWM_FREQ_HZ = 50            # analog servos expect a 50 Hz frame

# Proportional gain: fraction of the measured angular error corrected per step.
# < 1 keeps the loop critically-damped-ish and jitter-free without a real PID.
TRACK_GAIN = 0.5
# Ignore sub-pixel wobble so a centred target holds still (dead-band, fraction
# of frame from centre on each axis).
TRACK_DEADBAND = 0.02


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* into the inclusive [low, high] range."""
    return max(low, min(high, value))


class PanTilt:
    """Closed-loop 2-axis tracker over a PCA9685 (with mock fallback)."""

    def __init__(self, pan_ch: int = 0, tilt_ch: int = 1,
                 force_mock: bool = False,
                 pan_limits: tuple[float, float] = (-90.0, 90.0),
                 tilt_limits: tuple[float, float] = (-45.0, 45.0)):
        self.pan_ch = int(pan_ch)
        self.tilt_ch = int(tilt_ch)
        self.pan_limits = (float(pan_limits[0]), float(pan_limits[1]))
        self.tilt_limits = (float(tilt_limits[0]), float(tilt_limits[1]))
        self._pan = 0.0            # last commanded angles (degrees, rig-centred)
        self._tilt = 0.0
        self._pca = None
        self._real = False
        if not force_mock:
            self._init_pca9685()
        # Drive to a known home position so the rig starts level and centred.
        self.set_angles(0.0, 0.0)

    # ---- availability ---------------------------------------------------------
    def _init_pca9685(self) -> None:
        """Try once to bring up the PCA9685; stay in mock mode on any failure."""
        try:
            import board, busio                       # Raspberry Pi only
            from adafruit_pca9685 import PCA9685
            i2c = busio.I2C(board.SCL, board.SDA)
            pca = PCA9685(i2c)
            pca.frequency = PWM_FREQ_HZ
            self._pca = pca
            self._real = True
        except Exception as e:
            print(f"[pantilt] PCA9685 unavailable ({type(e).__name__}); "
                  f"running in mock mode (angles recorded only)")
            self._pca = None
            self._real = False

    # ---- servo I/O ------------------------------------------------------------
    def _angle_to_duty(self, angle_deg: float) -> int:
        """Map a rig angle to a 16-bit PCA9685 duty cycle via the pulse band."""
        # Rig angles are centred on 0; servos expect 0..180.
        servo_deg = _clamp(angle_deg + SERVO_RANGE_DEG / 2.0, 0.0, SERVO_RANGE_DEG)
        us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * (servo_deg / SERVO_RANGE_DEG)
        period_us = 1_000_000.0 / PWM_FREQ_HZ          # 20 000 us at 50 Hz
        return int(_clamp(us / period_us, 0.0, 1.0) * 0xFFFF)

    def _write(self, channel: int, angle_deg: float) -> None:
        """Push one channel to *angle_deg* (no-op in mock mode)."""
        if not self._real or self._pca is None:
            return
        try:
            self._pca.channels[channel].duty_cycle = self._angle_to_duty(angle_deg)
        except Exception as e:
            print(f"[pantilt] servo write failed ({type(e).__name__}); "
                  f"dropping to mock")
            self._real = False

    # ---- public ---------------------------------------------------------------
    def set_angles(self, pan_deg: float, tilt_deg: float) -> tuple[float, float]:
        """Clamp to the configured limits, move both servos, return (pan, tilt)."""
        self._pan = _clamp(float(pan_deg), *self.pan_limits)
        self._tilt = _clamp(float(tilt_deg), *self.tilt_limits)
        self._write(self.pan_ch, self._pan)
        self._write(self.tilt_ch, self._tilt)
        return self._pan, self._tilt

    def track(self, bbox: tuple[float, float, float, float],
              hfov_deg: float = 62.2, vfov_deg: float = 48.8) -> tuple[float, float]:
        """Proportionally re-centre on a normalized bbox (cx, cy, w, h).

        `cx`/`cy` are the target centre in [0, 1] frame coordinates (origin top-
        left). The offset from frame centre (0.5, 0.5), scaled by the camera's
        field of view, is the angular error; we step a fraction (TRACK_GAIN) of
        it. Pan increases to the right; tilt increases upward (so a target above
        centre, smaller cy, tilts up). Returns the new (pan, tilt).
        """
        cx, cy = float(bbox[0]), float(bbox[1])
        err_x = cx - 0.5              # >0 : target right of centre
        err_y = 0.5 - cy             # >0 : target above centre
        pan, tilt = self._pan, self._tilt
        if abs(err_x) > TRACK_DEADBAND:
            pan = self._pan + TRACK_GAIN * err_x * hfov_deg
        if abs(err_y) > TRACK_DEADBAND:
            tilt = self._tilt + TRACK_GAIN * err_y * vfov_deg
        return self.set_angles(pan, tilt)

    def current(self) -> tuple[float, float]:
        """Return the last commanded (pan, tilt) in degrees."""
        return self._pan, self._tilt

    @property
    def mode(self) -> str:
        """`"pca9685"` when driving real servos, else `"mock"`."""
        return "pca9685" if self._real else "mock"


def main(argv=None):
    """Self-test: feed off-centre bboxes and watch the rig converge to centre."""
    pt = PanTilt(force_mock=True)
    print(f"mode: {pt.mode}")
    print(f"home: pan={pt.current()[0]:+.1f} tilt={pt.current()[1]:+.1f}")
    # A drone parked high-right of frame; centre is (0.5, 0.5).
    cx, cy, w, h = 0.85, 0.20, 0.10, 0.10
    print("\ntracking a target at frame (cx=0.85, cy=0.20) -> expect pan+, tilt+:")
    for step in range(1, 13):
        pan, tilt = pt.track((cx, cy, w, h))
        # Simulate the rig closing the gap: the target drifts toward centre as we
        # aim (proportional to how far we just slewed).
        cx += (0.5 - cx) * TRACK_GAIN
        cy += (0.5 - cy) * TRACK_GAIN
        print(f"  step {step:2d}: pan={pan:+6.2f}  tilt={tilt:+6.2f}  "
              f"bbox_centre=({cx:.3f},{cy:.3f})")
        time.sleep(0.02)
    off = (abs(cx - 0.5), abs(cy - 0.5))
    print(f"\nconverged: bbox centre offset now ({off[0]:.4f}, {off[1]:.4f}) "
          f"-> {'OK' if max(off) < 0.02 else 'still drifting'}")


if __name__ == "__main__":
    main()
