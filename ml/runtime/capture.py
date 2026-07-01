"""Live IQ capture.

On the Raspberry Pi this shells out to `rtl_sdr` and reads the interleaved-uint8
file it writes — which is byte-for-byte the format `ml.common.iq.load_iq` already
expects, so real captures need zero conversion.

On a machine with no RTL-SDR (e.g. this Windows laptop) it falls back to the
mock synthesizer in `ml.common.rf_synth`, so the whole live loop still runs for
development and demos.

    cap = Capture(freq_hz=2.44e9, sample_rate=2.4e6)
    iq, source = cap.read()          # complex64 array, "rtl_sdr" or "mock"
"""
from __future__ import annotations
import os, sys, shutil, subprocess, tempfile
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import CENTER_FREQ, SAMPLE_RATE, IQ_SAMPLES_PER_FILE
from ml.common.iq import load_iq
from ml.common.rf_synth import synth, synth_drone_model

RTL_SDR_BIN = shutil.which("rtl_sdr")


class Capture:
    def __init__(self, freq_hz: float = CENTER_FREQ, sample_rate: float = SAMPLE_RATE,
                 n_samples: int = IQ_SAMPLES_PER_FILE, gain: str | None = None,
                 force_mock: bool = False, simulate: str | None = None,
                 seed: int | None = None):
        self.freq = int(freq_hz)
        self.rate = int(sample_rate)
        self.n = int(n_samples)
        self.gain = gain
        self.simulate = simulate            # mock-only: force a class each read
        self.rng = np.random.default_rng(seed)
        self.real = bool(RTL_SDR_BIN) and not force_mock and simulate is None

    # ---- real hardware --------------------------------------------------------
    def _read_rtl_sdr(self) -> np.ndarray:
        # rtl_sdr -n counts complex samples; output is interleaved uint8 I/Q.
        tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
        tmp.close()
        try:
            cmd = [RTL_SDR_BIN, "-f", str(self.freq), "-s", str(self.rate),
                   "-n", str(self.n)]
            if self.gain is not None:
                cmd += ["-g", str(self.gain)]
            cmd += [tmp.name]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
            return load_iq(tmp.name, max_samples=self.n)
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    # ---- mock fallback --------------------------------------------------------
    def _read_mock(self) -> np.ndarray:
        if self.simulate in ("DJI_Mavic", "DJI_Tello", "Syma_X5C", "Parrot_Anafi"):
            return synth_drone_model(self.simulate, self.rng, snr_db=13)
        if self.simulate in ("noise", "wifi", "bluetooth", "drone"):
            return synth(self.simulate, self.rng, snr_db=13)
        # No forced class: mostly quiet air, with the occasional drone/interferer
        # so the loop visibly reacts during a demo.
        kind = self.rng.choice(
            ["noise", "noise", "noise", "wifi", "bluetooth", "drone"],
            p=[0.45, 0.15, 0.10, 0.12, 0.08, 0.10])
        if kind == "drone":
            model = self.rng.choice(["DJI_Mavic", "DJI_Tello", "Syma_X5C", "Parrot_Anafi"])
            return synth_drone_model(str(model), self.rng, snr_db=float(self.rng.uniform(8, 16)))
        return synth(str(kind), self.rng, snr_db=float(self.rng.uniform(8, 16)))

    # ---- public ---------------------------------------------------------------
    def read(self) -> tuple[np.ndarray, str]:
        """Return (complex64 IQ, source-tag). Falls back to mock on any SDR error."""
        if self.real:
            try:
                return self._read_rtl_sdr(), "rtl_sdr"
            except Exception as e:  # SDR unplugged mid-run, driver hiccup, etc.
                print(f"[capture] rtl_sdr failed ({type(e).__name__}: {e}); "
                      f"using mock for this read")
        return self._read_mock(), "mock"

    @property
    def mode(self) -> str:
        return "rtl_sdr" if self.real else "mock"
