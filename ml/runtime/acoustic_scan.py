"""A5 acoustic vector for the fusion loop — one mic snapshot -> drone score.

The live detector already fuses RF, Wi-Fi/Remote-ID and (optionally) vision; this
module adds the *sound* vector by capturing ~1 s of microphone audio and running
the trained A5 CNN behind the same poll-once interface the runtime expects
(`.read()` + `.mode`).

Seamless degradation — identical to the rest of the runtime:
    * a mic (sounddevice OR pyaudio) + torch/librosa + trained A5 weights present
                                          -> real drone/noise/motor classification.
    * any of those missing (e.g. a bare Windows laptop)
                                          -> mock, so the fusion loop still runs.
    * `simulate="drone"` / `"noise"` …    -> mock only, forced, for hardware-free
                                             demos of the acoustic vector.

    ac = AcousticScanner()
    hit = ac.read()
    # {"confidence": 0.0..1.0 (drone-class prob), "label": str,
    #  "source": "mic"|"mock"}

`confidence` is the drone-class probability from the A5 softmax, so it drops
straight into the fuser's `acoustic_conf` input.
"""
from __future__ import annotations
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import ACOUSTIC_CLASSES, A5_CNN_MODEL

SR = 16000              # A5 features expect 16 kHz mono (see a5_acoustic.features)
DURATION_SEC = 1.0      # how much audio to grab per read()


class AcousticScanner:
    """Capture ~1 s of mic audio and score it with A5 (mock fallback)."""

    def __init__(self, force_mock: bool = False, simulate: str | None = None,
                 duration_sec: float = DURATION_SEC, seed: int | None = None):
        self.duration = float(duration_sec)
        self.simulate = simulate            # mock-only: force a class each read
        self.force_mock = force_mock
        self.rng = np.random.default_rng(seed)
        self._warned = False
        self._cnn = None
        self._record = None                 # bound mic-capture callable, once set
        # "real" = A5 weights loaded AND a mic backend available; else we mock.
        self.real = (not force_mock and simulate is None and self._setup())

    # ---- availability ---------------------------------------------------------
    def _setup(self) -> bool:
        """Lazily load the A5 CNN and pick a mic backend.

        All heavy imports (torch via AcousticCNN, sounddevice/pyaudio) live here
        so the module imports and __main__ runs with none of them installed.
        """
        try:
            from ml.a5_acoustic.infer import AcousticCNN
            cnn = AcousticCNN(A5_CNN_MODEL)     # imports torch, loads weights
        except Exception:
            return False
        record = self._pick_mic()
        if record is None:
            return False
        self._cnn, self._record = cnn, record
        return True

    def _pick_mic(self):
        """Return a `() -> float32 mono array` recorder, or None if no backend."""
        try:
            import sounddevice as sd

            def rec_sd():
                n = int(self.duration * SR)
                a = sd.rec(n, samplerate=SR, channels=1, dtype="float32")
                sd.wait()
                return np.asarray(a, dtype=np.float32).reshape(-1)

            return rec_sd
        except Exception:
            pass
        try:
            import pyaudio

            def rec_pa():
                pa = pyaudio.PyAudio()
                n = int(self.duration * SR)
                stream = pa.open(format=pyaudio.paFloat32, channels=1, rate=SR,
                                 input=True, frames_per_buffer=1024)
                raw = stream.read(n, exception_on_overflow=False)
                stream.stop_stream(); stream.close(); pa.terminate()
                return np.frombuffer(raw, dtype=np.float32)

            return rec_pa
        except Exception:
            return None

    # ---- real A5 --------------------------------------------------------------
    def _read_mic(self) -> dict:
        audio = self._record()
        # Reuse the exact A5 pipeline (MFCC -> CNN -> softmax) but keep the full
        # class distribution so we can report the *drone* probability directly.
        m = _mfcc(audio)
        t = self._cnn.torch
        x = t.tensor(m).unsqueeze(0).unsqueeze(0)
        with t.no_grad():
            p = t.softmax(self._cnn.net(x), 1)[0]
        classes = self._cnn.classes
        top = classes[int(p.argmax())]
        drone_i = classes.index("drone") if "drone" in classes else int(p.argmax())
        return {"confidence": round(float(p[drone_i]), 3),
                "label": top, "source": "mic"}

    # ---- mock -----------------------------------------------------------------
    def _read_mock(self) -> dict:
        names = list(ACOUSTIC_CLASSES)                  # ["noise","drone","motor"]
        if self.simulate in names:
            label = self.simulate
        else:
            # Mostly quiet, with the occasional drone/motor so the loop reacts.
            label = str(self.rng.choice(names, p=[0.5, 0.3, 0.2]))
        if label == "drone":
            conf = float(self.rng.uniform(0.55, 0.9))
        else:
            conf = float(self.rng.uniform(0.02, 0.3))
        return {"confidence": round(conf, 3), "label": label, "source": "mock"}

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """Capture + classify one clip. Falls back to mock on any capture error."""
        if self.real:
            try:
                return self._read_mic()
            except Exception as e:      # mic yanked, driver hiccup, decode error…
                if not self._warned:
                    print(f"[acoustic] read failed ({type(e).__name__}: {e}); "
                          f"using mock this clip")
                    self._warned = True
                return self._read_mock()
        return self._read_mock()

    @property
    def mode(self) -> str:
        if self.simulate is not None:
            return "mock(sim)"
        return "mic" if self.real else "mock"


def _mfcc(audio):
    """Thin wrapper over the shared A5 MFCC extractor (librosa imported there)."""
    from ml.a5_acoustic.features import wav_to_mfcc
    return wav_to_mfcc(audio)


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="A5 acoustic drone scanner (mock-safe)")
    p.add_argument("--simulate", default=None,
                   help="force a mock class (noise|drone|motor) — no mic needed")
    p.add_argument("-n", "--clips", type=int, default=5,
                   help="how many read() results to print (default 5)")
    args = p.parse_args(argv)
    ac = AcousticScanner(simulate=args.simulate)
    print(f"mode: {ac.mode}")
    for i in range(args.clips):
        print(f"clip {i}: {json.dumps(ac.read())}")


if __name__ == "__main__":
    main()
