"""RF direction finding — recover an emitter's bearing by sweeping a Yagi.

Why this exists: an omni antenna tells you a drone's radio is *nearby* but not
*which way*. A directional antenna (a small Yagi bolted to the same pan-tilt head
the camera uses) has a narrow main lobe — point it at the emitter and the RSSI
peaks. So we sweep the servo across a set of angles, sample the received signal
strength at each, and the angle of maximum RSSI is the bearing to the emitter.

Two refinements make the number useful:

    * **Parabolic interpolation.** The true peak rarely lands exactly on a
      sampled angle. Fitting a parabola through the strongest sample and its two
      neighbours gives a sub-step estimate of the real peak angle.
    * **A confidence score.** A sharp, high main lobe standing well above the
      surrounding samples is trustworthy; a flat, noisy sweep is not. We fold
      lobe sharpness and peak-above-floor SNR into a single 0..1 number.

No hardware required: if you pass no ``rssi_fn`` the class synthesizes a mock
Gaussian main lobe at a hidden true bearing plus noise, so the ``__main__``
self-test recovers that bearing within a few degrees on any machine.

    df = DirectionFinder()                      # mock sweep, hidden bearing
    result = df.find_bearing()
    # {"bearing_deg", "peak_dbm", "confidence", "samples": [(angle, dbm), ...]}
"""
from __future__ import annotations
import numpy as np

# Mock antenna model: main-lobe half-power width (deg) and signal levels (dBm).
_MOCK_LOBE_WIDTH_DEG = 30.0     # Gaussian sigma of the synthetic main lobe
_MOCK_PEAK_DBM = -45.0          # RSSI when the Yagi points straight at the source
_MOCK_FLOOR_DBM = -92.0         # off-lobe noise floor
_MOCK_NOISE_DBM = 1.5           # per-sample gaussian noise (std, dB)


class DirectionFinder:
    """Sweep a directional antenna and locate the RSSI peak (with mock fallback).

    Args:
        rssi_fn:  callable ``rssi_fn(angle_deg) -> dBm`` that aims the antenna at
                  ``angle_deg`` and returns the measured signal strength. If
                  ``None`` a built-in mock lobe is used (mode == "mock").
        angles:   iterable of sweep angles in degrees. Default sweeps the pan-tilt
                  from -90 to +90 in 10 deg steps.
    """

    def __init__(self, rssi_fn=None, angles=range(-90, 91, 10)):
        self.angles = [float(a) for a in angles]
        if len(self.angles) < 3:
            raise ValueError("need at least 3 sweep angles for peak interpolation")
        if rssi_fn is None:
            # Hidden true bearing somewhere in the swept range; the self-test must
            # recover it without ever reading this value.
            lo, hi = min(self.angles), max(self.angles)
            self._true_bearing = float(np.random.uniform(lo + 15, hi - 15))
            self.rssi_fn = self._mock_rssi
            self._mode = "mock"
        else:
            self._true_bearing = None
            self.rssi_fn = rssi_fn
            self._mode = "live"

    # ---- mock antenna ---------------------------------------------------------
    def _mock_rssi(self, angle_deg: float) -> float:
        """Synthetic Yagi: a Gaussian main lobe over a noise floor.

        RSSI falls off as a Gaussian in the pointing error ``angle - true``::

            gain = exp(-0.5 * (error / sigma)^2)          # 1 on-axis -> 0 far off
            dbm  = floor + (peak - floor) * gain + noise

        so the strongest reading sits at the hidden true bearing.
        """
        error = float(angle_deg) - self._true_bearing
        gain = np.exp(-0.5 * (error / _MOCK_LOBE_WIDTH_DEG) ** 2)
        dbm = _MOCK_FLOOR_DBM + (_MOCK_PEAK_DBM - _MOCK_FLOOR_DBM) * gain
        return float(dbm + np.random.normal(0.0, _MOCK_NOISE_DBM))

    # ---- sweep ----------------------------------------------------------------
    def find_bearing(self) -> dict:
        """Sweep every angle, find the RSSI peak, refine it, and score it.

        Returns a dict with:
            bearing_deg: parabola-interpolated peak angle (sub-step accuracy),
            peak_dbm:    the strongest sampled RSSI,
            confidence:  0..1 from lobe sharpness and peak-above-floor SNR,
            samples:     the raw ``[(angle, dbm), ...]`` sweep.
        """
        samples = [(a, float(self.rssi_fn(a))) for a in self.angles]
        angles = np.array([s[0] for s in samples], dtype=float)
        dbm = np.array([s[1] for s in samples], dtype=float)

        k = int(np.argmax(dbm))
        peak_angle = angles[k]
        peak_dbm = float(dbm[k])

        # Parabolic (3-point) interpolation around the max for a sub-step peak.
        # Fit y = a*x^2 + b*x + c through the peak and its two neighbours; the
        # vertex offset is  delta = 0.5*(y_left - y_right)/(y_left - 2*y_mid +
        # y_right), in units of the local step. Only valid with both neighbours
        # present and a genuine (concave-down) peak.
        if 0 < k < len(dbm) - 1:
            y0, y1, y2 = dbm[k - 1], dbm[k], dbm[k + 1]
            denom = (y0 - 2.0 * y1 + y2)
            if denom < 0:  # concave down -> real peak
                delta = 0.5 * (y0 - y2) / denom
                delta = float(np.clip(delta, -1.0, 1.0))
                # Neighbours may be unevenly spaced; scale by the nearer step.
                step = (angles[k + 1] - angles[k - 1]) / 2.0
                peak_angle = angles[k] + delta * step

        confidence = self._confidence(dbm)
        return {
            "bearing_deg": round(float(peak_angle), 2),
            "peak_dbm": round(peak_dbm, 2),
            "confidence": round(confidence, 3),
            "samples": samples,
        }

    @staticmethod
    def _confidence(dbm: np.ndarray) -> float:
        """Blend peak-above-median SNR and lobe sharpness into 0..1.

        Two independent cues, each squashed to [0, 1] and averaged:
            * SNR    = (peak - median) dB, saturating at ~25 dB. A strong emitter
              far above the ambient sweep -> high SNR.
            * sharpness = (peak - mean)/spread — a tight lobe concentrates energy
              at one angle, so the peak sits many std devs above the mean.
        A flat/noisy sweep scores near 0; a clean tall lobe near 1.
        """
        peak = float(np.max(dbm))
        med = float(np.median(dbm))
        snr = np.clip((peak - med) / 25.0, 0.0, 1.0)
        spread = float(np.std(dbm))
        sharp = np.clip((peak - float(np.mean(dbm))) / (spread + 1e-9) / 3.0,
                        0.0, 1.0)
        return float(0.5 * snr + 0.5 * sharp)

    @property
    def mode(self) -> str:
        """"live" if driven by a real ``rssi_fn``, else "mock"."""
        return self._mode


def main(argv=None):
    import json
    np.random.seed(7)  # deterministic self-test
    df = DirectionFinder()                      # mock sweep, hidden bearing
    result = df.find_bearing()
    truth = df._true_bearing                     # peek only to grade the test

    print(f"mode: {df.mode}")
    print(f"hidden true bearing : {truth:.2f} deg")
    print(f"recovered bearing   : {result['bearing_deg']:.2f} deg  "
          f"(peak {result['peak_dbm']} dBm, conf {result['confidence']})")
    print("sweep samples (angle deg -> dBm):")
    for a, d in result["samples"]:
        mark = "  <== peak" if abs(a - round(result["bearing_deg"])) < 1e-6 \
            or a == max(result["samples"], key=lambda s: s[1])[0] else ""
        print(f"  {a:+6.1f} : {d:7.2f}{mark}")

    err = abs(result["bearing_deg"] - truth)
    print(f"\nabsolute error: {err:.2f} deg")
    assert err < 6.0, f"mock bearing not recovered (err {err:.2f} deg)"
    print("self-test OK (recovered hidden bearing within a few degrees)")
    _ = json  # keep import meaningful if extended later


if __name__ == "__main__":
    main()
