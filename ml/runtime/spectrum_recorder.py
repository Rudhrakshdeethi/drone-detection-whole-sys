"""Spectrum / IQ snapshot recorder — freeze the RF band for offline study.

When something interesting happens we want a durable capture of the airwaves for
later forensic analysis *and* to grow the training set. This mirrors the runtime
capture idiom (`ml.runtime.capture`): shell out to the RTL-SDR CLI tools when
they exist, and synthesize a realistic file when they don't — so the pipeline is
identical on the Raspberry Pi and on a bare Windows laptop.

Backends, in priority order:
    * `rtl_power` present -> a quick power-vs-frequency sweep written as CSV.
    * `rtl_sdr`   present -> a short interleaved-uint8 IQ capture (.bin), the
                             exact format `ml.common.iq.load_iq` already reads.
    * neither             -> a plausible synthetic power-spectrum CSV (numpy),
                             so downstream analysis / demos still have real data.

Snapshots land under REPORTS_DIR/spectra/<timestamp>_<tag>.{csv,bin}.

    rec = SpectrumRecorder()
    path = rec.record(tag="alert")     # -> .../spectra/20260702-150538_alert.csv
    print(rec.mode)                    # "rtl_power" | "rtl_sdr" | "mock"
"""
from __future__ import annotations
import os, sys, shutil, subprocess
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import REPORTS_DIR, CENTER_FREQ, SAMPLE_RATE

SPECTRA_DIR = os.path.join(REPORTS_DIR, "spectra")

RTL_POWER_BIN = shutil.which("rtl_power")
RTL_SDR_BIN = shutil.which("rtl_sdr")

# Mock sweep geometry: samples spanning +/- half the sample rate about center.
_MOCK_BINS = 512
_MOCK_INTEG_SEC = 1


class SpectrumRecorder:
    """Capture one RF spectrum/IQ snapshot to disk, with a mock fallback."""

    def __init__(self, base_dir: str = SPECTRA_DIR, force_mock: bool = False,
                 n_samples: int = 262144, seed: int | None = None):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.n = int(n_samples)
        self.rng = np.random.default_rng(seed)
        self.force_mock = force_mock

    # ---- backend selection ----------------------------------------------------
    @property
    def mode(self) -> str:
        """Which backend `record()` will use right now."""
        if self.force_mock:
            return "mock"
        if RTL_POWER_BIN:
            return "rtl_power"
        if RTL_SDR_BIN:
            return "rtl_sdr"
        return "mock"

    # ---- path helpers ---------------------------------------------------------
    def _out_path(self, tag: str, ext: str) -> str:
        """A unique <YYYYmmdd-HHMMSS-ffffff>_<tag>.<ext> path (tag sanitized)."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safe = "".join(c if (c.isalnum() or c in "-._") else "_" for c in tag).strip("_")
        name = f"{stamp}_{safe}.{ext}" if safe else f"{stamp}.{ext}"
        return os.path.join(self.base_dir, name)

    # ---- real backends --------------------------------------------------------
    def _record_rtl_power(self, path: str, center_hz: float, sample_rate: float) -> str:
        """One-shot rtl_power sweep across the sample-rate window -> CSV."""
        lo = int(center_hz - sample_rate / 2)
        hi = int(center_hz + sample_rate / 2)
        bin_hz = max(1, int(sample_rate / _MOCK_BINS))
        cmd = [RTL_POWER_BIN, "-f", f"{lo}:{hi}:{bin_hz}",
               "-i", str(_MOCK_INTEG_SEC), "-1", path]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        return path

    def _record_rtl_sdr(self, path: str, center_hz: float, sample_rate: float) -> str:
        """Short IQ grab -> interleaved-uint8 .bin (load_iq-compatible)."""
        cmd = [RTL_SDR_BIN, "-f", str(int(center_hz)), "-s", str(int(sample_rate)),
               "-n", str(self.n), path]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
        return path

    # ---- mock backend ---------------------------------------------------------
    def _record_mock(self, path: str, center_hz: float, sample_rate: float) -> str:
        """Synthesize a believable power-spectrum CSV (freq_hz, power_dbm).

        A noise floor near -95 dBm with a couple of Gaussian humps standing in
        for a Wi-Fi/drone-control carrier, so downstream sweep analysis has
        realistic structure to chew on.
        """
        lo = center_hz - sample_rate / 2
        hi = center_hz + sample_rate / 2
        freqs = np.linspace(lo, hi, _MOCK_BINS)
        floor = -95.0 + self.rng.normal(0.0, 1.5, _MOCK_BINS)
        power = floor.copy()
        for _ in range(int(self.rng.integers(1, 4))):        # 1-3 carriers
            fc = self.rng.uniform(lo, hi)
            width = sample_rate * self.rng.uniform(0.01, 0.05)
            amp = self.rng.uniform(15.0, 45.0)
            power += amp * np.exp(-0.5 * ((freqs - fc) / width) ** 2)
        header = (f"# mock spectrum  center={int(center_hz)}Hz  "
                  f"rate={int(sample_rate)}Hz  bins={_MOCK_BINS}\n"
                  f"freq_hz,power_dbm")
        np.savetxt(path, np.column_stack([freqs, power]),
                   delimiter=",", header=header, comments="", fmt="%.3f")
        return path

    # ---- public ---------------------------------------------------------------
    def record(self, tag: str = "", center_hz: float = CENTER_FREQ,
               sample_rate: float = SAMPLE_RATE) -> str:
        """Capture one snapshot and return its file path.

        Tries rtl_power then rtl_sdr; on any failure (or no hardware) falls back
        to a synthetic CSV so the caller always gets a usable artifact.
        """
        if not self.force_mock and RTL_POWER_BIN:
            path = self._out_path(tag, "csv")
            try:
                return self._record_rtl_power(path, center_hz, sample_rate)
            except Exception as e:
                print(f"[spectrum] rtl_power failed ({type(e).__name__}: {e}); "
                      f"falling back")
        if not self.force_mock and RTL_SDR_BIN:
            path = self._out_path(tag, "bin")
            try:
                return self._record_rtl_sdr(path, center_hz, sample_rate)
            except Exception as e:
                print(f"[spectrum] rtl_sdr failed ({type(e).__name__}: {e}); "
                      f"falling back to mock")
        return self._record_mock(self._out_path(tag, "csv"), center_hz, sample_rate)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Spectrum/IQ snapshot recorder self-test")
    p.add_argument("--tag", default="selftest", help="label embedded in the filename")
    p.add_argument("--center-hz", type=float, default=CENTER_FREQ)
    p.add_argument("--sample-rate", type=float, default=SAMPLE_RATE)
    p.add_argument("--mock", action="store_true", help="force the synthetic backend")
    args = p.parse_args(argv)

    rec = SpectrumRecorder(force_mock=args.mock)
    print(f"mode: {rec.mode}")
    path = rec.record(tag=args.tag, center_hz=args.center_hz,
                      sample_rate=args.sample_rate)
    print(f"snapshot written to: {path}")
    print(f"  size: {os.path.getsize(path)} bytes")
    if path.endswith(".csv"):
        with open(path, encoding="utf-8") as f:
            for _, line in zip(range(5), f):
                print("  " + line.rstrip())
    else:
        print("  (binary IQ capture)")


if __name__ == "__main__":
    main()
