"""Control-link scanner — the sub-GHz drone *remote-control* RF vector.

Why this exists: the RTL-SDR V4 tops out at ~1.766 GHz, so it physically cannot
tune the 2.4 GHz band where most drone video/telemetry lives. But the *control
link* — the pilot's radio commanding the aircraft — very often runs in the
sub-GHz ISM bands the RTL-SDR reaches comfortably:

    * **433 MHz** (433.05-434.79 ISM)  — ExpressLRS / TBS Crossfire low band.
    * **868 MHz** (EU SRD)             — ExpressLRS 868.
    * **915 MHz** (US ISM 902-928)     — ExpressLRS / Crossfire 915.

These long-range control links use **FHSS** (frequency-hopping spread spectrum):
short bursts that skip across dozens of channels spanning a wide span, dwelling a
millisecond or two per hop. That signature — many elevated, bursty bins scattered
across a wide span above the noise floor — is exactly what a cheap `rtl_power`
sweep can surface, even though the 2.4 GHz video downlink is invisible to us.

Seamless degradation — identical to the rest of the runtime:
    * `rtl_power` present + RTL-SDR plugged in -> real FHSS-energy detection.
    * `rtl_power` absent (e.g. Windows laptop)  -> mock, so the loop still runs.
    * `simulate=...`                            -> force a mock outcome for demos.

    det = ControlLinkScanner().read()
    # {"confidence": 0.0..1.0, "band_hz": 915e6|None, "detail": str,
    #  "source": "rtl_power"|"mock"}
"""
from __future__ import annotations
import os, sys, shutil, subprocess, tempfile, csv, math, random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import SAMPLE_RATE  # noqa: F401  (kept for constant parity)

RTL_POWER_BIN = shutil.which("rtl_power")

# Default control-link centres the RTL-SDR V4 can actually reach.
DEFAULT_BANDS = (433.9e6, 868e6, 915e6)

# How wide a span to sweep around each band centre (Hz). FHSS control links
# hop across the whole ISM allocation, so we sweep a couple of MHz to catch
# the scatter of active channels.
SPAN_HZ = float(os.environ.get("CTRL_SPAN_HZ", "2e6"))
# rtl_power bin size (Hz) and integration/dwell (seconds) per band.
BIN_HZ = float(os.environ.get("CTRL_BIN_HZ", "25e3"))
DWELL_SEC = float(os.environ.get("CTRL_DWELL_SEC", "2"))
# A bin this many dB over the estimated noise floor counts as "active".
ACTIVE_DB_OVER_FLOOR = float(os.environ.get("CTRL_ACTIVE_DB", "6"))

# Human-friendly band label for the detail string.
_BAND_LABEL = {433: "433 MHz (ELRS/Crossfire)",
               868: "868 MHz (ELRS EU)",
               915: "915 MHz (ELRS/Crossfire US)"}


def _band_name(hz: float) -> str:
    return _BAND_LABEL.get(int(round(hz / 1e6)), f"{hz/1e6:.1f} MHz")


class ControlLinkScanner:
    """Detect FHSS drone control links in the sub-GHz bands (with mock fallback)."""

    def __init__(self, bands=DEFAULT_BANDS, force_mock: bool = False,
                 simulate: str | None = None, seed: int | None = None):
        self.bands = tuple(float(b) for b in bands)
        self.simulate = simulate            # mock-only: "hopping"/"quiet" to force
        self.rng = random.Random(seed)
        self._warned = False
        # "real" = we have rtl_power and are not being forced to mock.
        self.real = bool(RTL_POWER_BIN) and not force_mock and simulate is None

    # ---- real hardware --------------------------------------------------------
    def _sweep_band(self, center_hz: float) -> list[float]:
        """Run one short `rtl_power` sweep; return the dB reading of every bin."""
        lo = int(center_hz - SPAN_HZ / 2.0)
        hi = int(center_hz + SPAN_HZ / 2.0)
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        tmp.close()
        try:
            cmd = [RTL_POWER_BIN, "-f", f"{lo}:{hi}:{int(BIN_HZ)}",
                   "-i", f"{DWELL_SEC:g}", "-1", tmp.name]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=DWELL_SEC + 25)
            dbs: list[float] = []
            with open(tmp.name, newline="") as fh:
                for row in csv.reader(fh):
                    # rtl_power rows: date,time,Hz_low,Hz_high,Hz_step,samples,db,db,...
                    for cell in row[6:]:
                        try:
                            dbs.append(float(cell))
                        except ValueError:
                            pass
            return dbs
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    def _score_band(self, dbs: list[float]) -> tuple[float, int]:
        """Turn a band's power bins into (confidence 0..1, n_active_bins).

        FHSS control links show up as many elevated bins scattered above the
        noise floor (bursty wideband occupancy), rather than one fat carrier.
        We estimate the floor as the median, count bins that poke well above it,
        and reward a *spread* of active bins across the span.
        """
        if not dbs:
            return 0.0, 0
        s = sorted(dbs)
        floor = s[len(s) // 2]                       # median ~= noise floor
        active = [d for d in dbs if d >= floor + ACTIVE_DB_OVER_FLOOR]
        n = len(active)
        occupancy = n / float(len(dbs))
        peak_over = (max(dbs) - floor) if dbs else 0.0
        # Hopping signature: a non-trivial fraction of the span is momentarily
        # hot (occupancy) AND the hottest hop stands clearly above the floor.
        occ_term = min(1.0, occupancy / 0.10)        # ~10% span active -> full
        peak_term = min(1.0, peak_over / 20.0)       # ~20 dB peak -> full
        conf = 0.5 * occ_term + 0.5 * peak_term
        return max(0.0, min(1.0, conf)), n

    def _read_real(self) -> dict:
        best_conf, best_band, best_n = 0.0, None, 0
        for b in self.bands:
            dbs = self._sweep_band(b)
            conf, n = self._score_band(dbs)
            if conf > best_conf:
                best_conf, best_band, best_n = conf, b, n
        if best_band is None or best_conf < 0.4:
            return {"confidence": round(best_conf, 2), "band_hz": None,
                    "detail": "no FHSS control-link energy above noise floor",
                    "source": "rtl_power"}
        return {
            "confidence": round(best_conf, 2),
            "band_hz": best_band,
            "detail": (f"FHSS control-link energy at {_band_name(best_band)}: "
                       f"{best_n} bins active across {SPAN_HZ/1e6:.1f} MHz span"),
            "source": "rtl_power",
        }

    # ---- mock fallback --------------------------------------------------------
    def _read_mock(self) -> dict:
        forced = self.simulate
        if forced == "quiet":
            hopping = False
        elif forced in ("hopping", "control", "elrs", "crossfire"):
            hopping = True
        else:
            # Mostly quiet air, with the occasional hopping-control detection so
            # the loop visibly reacts during a hardware-free demo.
            hopping = self.rng.random() < 0.35
        if not hopping:
            return {"confidence": round(self.rng.uniform(0.0, 0.2), 2),
                    "band_hz": None,
                    "detail": "quiet: no control-link hopping detected (mock)",
                    "source": "mock"}
        band = self.rng.choice(self.bands)
        conf = round(self.rng.uniform(0.5, 0.85), 2)
        n = self.rng.randint(6, 24)
        return {
            "confidence": conf,
            "band_hz": band,
            "detail": (f"FHSS control-link energy at {_band_name(band)}: "
                       f"{n} bins active across {SPAN_HZ/1e6:.1f} MHz span (mock)"),
            "source": "mock",
        }

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """Sweep the control bands once. Falls back to mock on any SDR error."""
        if self.real:
            try:
                return self._read_real()
            except Exception as e:  # SDR unplugged mid-run, driver hiccup, etc.
                if not self._warned:
                    print(f"[control_link] rtl_power failed "
                          f"({type(e).__name__}: {e}); using mock for this read")
                    self._warned = True
        return self._read_mock()

    @property
    def mode(self) -> str:
        return "rtl_power" if self.real else "mock"


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(
        description="Sub-GHz drone control-link (ExpressLRS/Crossfire) scanner")
    p.add_argument("--simulate", default=None,
                   choices=["hopping", "quiet"],
                   help="force a mock outcome — no hardware required")
    p.add_argument("--force-mock", action="store_true",
                   help="ignore rtl_power even if present")
    args = p.parse_args(argv)
    sc = ControlLinkScanner(force_mock=args.force_mock, simulate=args.simulate)
    print(f"mode: {sc.mode}")
    det = sc.read()
    print(json.dumps(det, indent=2))


if __name__ == "__main__":
    main()
