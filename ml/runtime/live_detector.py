"""CampusShield live detector — the real-time loop.

This is the Team-Nayara detector's shape (continuous scan -> alert cascade) with
the brain swapped in: instead of a raw power threshold, every capture is run
through the trained ML stack and fused into an explained threat score.

Per iteration:
    1. capture live IQ (RTL-SDR, or mock on a laptop)         [capture.py]
    2. A1 RF classifier  -> noise/drone/wifi/bluetooth + conf
    3. A2 fingerprint    -> exact drone model        (if a drone looks present)
    4. A6 anomaly        -> known / unknown / suspicious
    5. Wi-Fi SSID scan   -> drone-name match         [wifi_scan.py, optional]
    6. A7 threat score   -> 0-100 + SAFE/WATCH/WARNING/CRITICAL
    7. A8 explanation    -> "detected because ..."   (on escalation)
    8. alert cascade     -> CSV + buzzer + Telegram  [alerts.py]

Run:
    python -m ml.runtime.live_detector                 # continuous, auto hw/mock
    python -m ml.runtime.live_detector --once          # single pass (smoke test)
    python -m ml.runtime.live_detector --mock --simulate DJI_Mavic   # force a drone
    python -m ml.runtime.live_detector --interval 3 --threshold 60

Prereq: train A1 (and optionally A2/A6) first ->  python run_all.py
"""
from __future__ import annotations
import os, sys, time, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8")   # emoji-safe on Windows consoles
except Exception:
    pass

from ml.common.config import CENTER_FREQ, SAMPLE_RATE
from ml.common.bus import publish
from ml.a1_rf_classifier.infer import RFClassifier
from ml.a7_threat_scoring.threat_score import compute_threat_score, ThreatInputs
from ml.runtime.capture import Capture
from ml.runtime.wifi_scan import WifiScanner
from ml.runtime.alerts import AlertManager, AlertConfig


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class LiveDetector:
    def __init__(self, args):
        self.args = args
        self.clf = RFClassifier()                      # A1 — required

        # A2 / A6 are optional: load if their models were trained, else skip.
        self.fp = self._maybe("ml.a2_fingerprinting.infer", "FingerprintID")
        self.anom = self._maybe("ml.a6_anomaly.infer", "AnomalyDetector")

        self.cap = Capture(freq_hz=args.freq, sample_rate=args.rate,
                           gain=args.gain, force_mock=args.mock,
                           simulate=args.simulate)
        self.wifi = (WifiScanner(force_mock=args.mock,
                                 simulate_ssid=args.simulate_ssid)
                     if args.wifi else None)

        self.alerts = AlertManager(AlertConfig(
            csv=not args.no_csv, buzzer=not args.no_buzzer,
            telegram=not args.no_telegram, cooldown_sec=args.cooldown))

        # Lingering-target tracking -> feeds A7's duration modifiers.
        self._drone_since: float | None = None

    @staticmethod
    def _maybe(module: str, cls: str):
        try:
            mod = __import__(module, fromlist=[cls])
            return getattr(mod, cls)()
        except Exception as e:
            print(f"[init] {cls} disabled ({type(e).__name__}) — "
                  f"train it to enable")
            return None

    # ---- one capture -> verdict ----------------------------------------------
    def step(self) -> dict:
        iq, source = self.cap.read()
        rf = self.clf.predict(iq)
        drone_prob = rf["probabilities"].get("drone", 0.0) / 100.0
        bt_prob = rf["probabilities"].get("bluetooth", 0.0) / 100.0
        looks_droney = rf["label"] == "drone" or drone_prob > 0.3

        # A2 fingerprint only when a drone plausibly present (saves work).
        fp_model, fp_conf = None, 0.0
        if self.fp is not None and looks_droney:
            try:
                fpr = self.fp.predict(iq)
                fp_model, fp_conf = fpr["model"], fpr["confidence"] / 100.0
            except Exception:
                pass

        # A6 anomaly / unknown-model flag.
        is_unknown, anom_verdict = False, None
        if self.anom is not None:
            try:
                av = self.anom.classify(iq)
                anom_verdict = av["verdict"]
                is_unknown = av["kind"] == "unknown"
            except Exception:
                pass

        # Wi-Fi SSID detector (Team-Nayara vector).
        wifi_hits = self.wifi.scan() if self.wifi else []
        wifi_conf = max((h["confidence"] for h in wifi_hits), default=0.0)

        # Lingering-target duration -> A7 modifiers (+10 >30s, +10 >60s).
        active = looks_droney or bool(wifi_hits)
        now = time.monotonic()
        if active:
            self._drone_since = self._drone_since or now
            duration = now - self._drone_since
        else:
            self._drone_since = None
            duration = 0.0

        # A7 fusion. A named-SSID match is near-certain drone ID, so we feed it
        # in as fingerprint-grade evidence on top of the RF confidence.
        score = compute_threat_score(ThreatInputs(
            rf_conf=drone_prob,
            visual_conf=0.0,                      # no camera in this loop
            acoustic_conf=0.0,                    # add A5 mic capture later
            fingerprint_conf=max(fp_conf, wifi_conf),
            bluetooth_conf=bt_prob,
            duration_sec=duration,
            is_unknown=is_unknown))

        return {"iq": iq, "source": source, "rf": rf, "drone_prob": drone_prob,
                "fp_model": fp_model, "fp_conf": fp_conf,
                "anom_verdict": anom_verdict, "is_unknown": is_unknown,
                "wifi_hits": wifi_hits, "duration": duration, "score": score}

    # ---- escalation + messaging ----------------------------------------------
    def _handle(self, v: dict) -> None:
        score = v["score"]
        escalate = score["score"] >= self.args.threshold or bool(v["wifi_hits"])

        rf = v["rf"]
        bits = [f"{rf['label'].upper()} {rf['confidence']}%"]
        if v["fp_model"] and v["fp_conf"] > 0.3:
            bits.append(f"model~{v['fp_model']} ({v['fp_conf']*100:.0f}%)")
        if v["wifi_hits"]:
            bits.append("SSID:" + ",".join(h["ssid"] for h in v["wifi_hits"]))
        if v["is_unknown"]:
            bits.append("UNKNOWN-MODEL")
        detail = " | ".join(bits)

        line = (f"{_now_iso()}  {score['icon']} {score['level']:<8} "
                f"{score['score']:5.1f}/100  [{v['source']}]  {detail}")
        print(line)

        # A8 explanation only when we actually escalate (it's the expensive head).
        explanation = ""
        if escalate:
            explanation = self._explain(v)

        row = {"timestamp": _now_iso(), "source": v["source"],
               "rf_label": rf["label"], "rf_confidence": rf["confidence"],
               "drone_prob": round(v["drone_prob"] * 100, 1),
               "fingerprint": v["fp_model"] or "",
               "fingerprint_conf": round(v["fp_conf"] * 100, 1),
               "wifi_ssids": ";".join(h["ssid"] for h in v["wifi_hits"]),
               "unknown_model": v["is_unknown"],
               "duration_sec": round(v["duration"], 1),
               "threat_score": score["score"], "threat_level": score["level"],
               "modifiers": "; ".join(score["modifiers"])}

        msg = (f"🚨 CampusShield: {score['level']} {score['score']}/100\n"
               f"{detail}\nlingering: {v['duration']:.0f}s")
        if explanation:
            msg += f"\nwhy: {explanation}"

        # Mirror onto the optional MQTT bus the rest of CampusShield listens on.
        publish("campusshield/detection", row, verbose=False)
        self.alerts.fire(row=row, message=msg, escalate=escalate)

    def _explain(self, v: dict) -> str:
        # A8 re-extracts features from the IQ it's given, so pass the same capture
        # this verdict came from (not the A1 feature vector).
        try:
            from ml.a8_explainability.explain import explain_prediction
            ex = explain_prediction(v["iq"], top_k=3)
            return ", ".join(f"{d['feature']} {d['share']}%" for d in ex["drivers"])
        except Exception as e:
            return f"(explain skipped: {type(e).__name__})"

    # ---- run loop -------------------------------------------------------------
    def run(self) -> None:
        print(f"=== CampusShield live detector ===")
        print(f"capture : {self.cap.mode}  @ {self.args.freq/1e9:.3f} GHz, "
              f"{self.args.rate/1e6:.2f} MS/s")
        print(f"wifi    : {self.wifi.mode if self.wifi else 'off'}")
        print(f"alerts  : csv={not self.args.no_csv} buzzer={not self.args.no_buzzer} "
              f"telegram={not self.args.no_telegram}  (cooldown {self.args.cooldown}s)")
        print(f"escalate threshold: {self.args.threshold}/100")
        print(f"A2 fingerprint: {'on' if self.fp else 'off'}   "
              f"A6 anomaly: {'on' if self.anom else 'off'}")
        print("-" * 72)
        try:
            while True:
                self._handle(self.step())
                if self.args.once:
                    break
                time.sleep(self.args.interval)
        except KeyboardInterrupt:
            print("\nstopped.")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="CampusShield real-time drone detector")
    p.add_argument("--interval", type=float, default=2.0,
                   help="seconds between captures (default 2)")
    p.add_argument("--threshold", type=float, default=60.0,
                   help="threat score that triggers buzzer+Telegram (default 60)")
    p.add_argument("--freq", type=float, default=CENTER_FREQ,
                   help=f"center frequency Hz (default {CENTER_FREQ:.3e})")
    p.add_argument("--rate", type=float, default=SAMPLE_RATE,
                   help=f"sample rate S/s (default {SAMPLE_RATE:.3e})")
    p.add_argument("--gain", default=None, help="RTL-SDR gain (default auto)")
    p.add_argument("--cooldown", type=float, default=30.0,
                   help="min seconds between escalated alerts (default 30)")
    p.add_argument("--once", action="store_true", help="run a single capture and exit")
    p.add_argument("--mock", action="store_true",
                   help="force mock capture even if an SDR is present")
    p.add_argument("--simulate", default=None,
                   help="mock-only: force a class/model "
                        "(noise|wifi|bluetooth|drone|DJI_Mavic|DJI_Tello|Syma_X5C|Parrot_Anafi)")
    p.add_argument("--simulate-ssid", default=None, dest="simulate_ssid",
                   help="inject a fake Wi-Fi SSID (e.g. DJI-Mavic-1A2B) for demos")
    p.add_argument("--no-wifi", dest="wifi", action="store_false",
                   help="disable the Wi-Fi SSID detector")
    p.add_argument("--no-csv", action="store_true", help="disable CSV logging")
    p.add_argument("--no-buzzer", action="store_true", help="disable GPIO buzzer")
    p.add_argument("--no-telegram", action="store_true", help="disable Telegram alerts")
    p.set_defaults(wifi=True)
    return p.parse_args(argv)


def main(argv=None):
    LiveDetector(parse_args(argv)).run()


if __name__ == "__main__":
    main()
