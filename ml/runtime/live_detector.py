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
from ml.runtime.kismet_scan import make_drone_rf_scanner
from ml.runtime.alerts import AlertManager, AlertConfig
# Extra sensor vectors + actuation — every one degrades to mock/off on a laptop.
from ml.runtime.vision_scan import VisionScanner
from ml.runtime.acoustic_scan import AcousticScanner
from ml.runtime.control_link_scan import ControlLinkScanner
from ml.runtime.ble_remoteid import BleRemoteIDScanner
from ml.runtime.adsb_scan import AdsbScanner
from ml.runtime.pantilt import PanTilt
from ml.runtime.response import ResponseLayer
from ml.runtime.display import StatusDisplay
from ml.runtime.lora_mesh import LoraMesh
from ml.runtime.recorder import IncidentRecorder
from ml.runtime.power_monitor import PowerMonitor
from ml.runtime.lidar import LidarTFLuna
from ml.runtime.gps import GpsReader
from ml.runtime.health_monitor import HealthMonitor
from ml.runtime.light_tower import LightTower
from ml.runtime.pluto_control import PlutoDefence
from ml.runtime.localize import localize, bbox_to_bearing


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
        self.wifi = (make_drone_rf_scanner(force_mock=args.mock,
                                           simulate_ssid=args.simulate_ssid)
                     if args.wifi else None)

        self.alerts = AlertManager(AlertConfig(
            csv=not args.no_csv, buzzer=not args.no_buzzer,
            telegram=not args.no_telegram, cooldown_sec=args.cooldown))

        # ---- extra fused vectors + actuation (each degrades to mock/off) ------
        self.vision = self._build("vision", lambda: VisionScanner(
            source=args.vision_source, force_mock=args.mock)) if args.vision else None
        self.acoustic = self._build("acoustic", lambda: AcousticScanner(
            force_mock=args.mock)) if args.acoustic else None
        self.control = self._build("control-link",
                                   lambda: ControlLinkScanner(force_mock=args.mock))
        self.ble = self._build("ble-remoteid", lambda: BleRemoteIDScanner(
            force_mock=args.mock, simulate_ssid=args.simulate_ssid)) if args.ble else None
        self.adsb = self._build("adsb", lambda: AdsbScanner(force_mock=args.mock))
        self.pantilt = self._build("pan-tilt",
                                   lambda: PanTilt(force_mock=args.mock)) if args.track else None
        self.lidar = self._build("lidar",
                                 lambda: LidarTFLuna(force_mock=args.mock)) if args.lidar else None
        self.response = self._build("response",
                                    lambda: ResponseLayer(force_mock=args.mock)) if args.response else None
        self.display = self._build("display", lambda: StatusDisplay(force_mock=args.mock))
        self.lora = self._build("lora",
                                lambda: LoraMesh(force_mock=args.mock)) if args.lora else None
        self.recorder = self._build("recorder", lambda: IncidentRecorder())
        self.power = self._build("power", lambda: PowerMonitor(force_mock=args.mock))
        self.gps = self._build("gps", lambda: GpsReader(force_mock=args.mock))
        self.health = self._build("health", lambda: HealthMonitor())
        self.tower = self._build("light-tower", lambda: LightTower(force_mock=args.mock))
        # Authorized OWN-DRONE land response — OFF unless --pluto-land + --own-drone.
        self.pluto = self._build("pluto", lambda: PlutoDefence(
            authorized=args.own_drone, enabled=args.pluto_land, force_mock=args.mock))
        self._pan, self._tilt = 0.0, 0.0        # current pan-tilt aim (degrees)

        # Sensor origin for localization: manual --lat/--lon, else the NEO-6M GPS.
        self.sensor_lat, self.sensor_lon = args.lat, args.lon
        if self.sensor_lat is None and self.gps is not None:
            try:
                g = self.gps.read()
                if g.get("fix"):
                    self.sensor_lat, self.sensor_lon = g["lat"], g["lon"]
                    print(f"[init] sensor position from GPS "
                          f"({self.gps.mode}): {self.sensor_lat:.6f},{self.sensor_lon:.6f}")
            except Exception:
                pass

        # Per-subsystem health status (real vs mock/off) for the health snapshot.
        if self.health is not None:
            for nm, sub in [("sdr", self.cap), ("wifi", self.wifi), ("gps", self.gps),
                            ("lidar", self.lidar), ("camera", self.vision),
                            ("lora", self.lora)]:
                try:
                    live = sub is not None and getattr(sub, "mode", "off") not in ("off", "mock")
                    self.health.register_status(nm, live)
                except Exception:
                    pass

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

    @staticmethod
    def _build(label: str, factory):
        """Construct an optional subsystem; never let one break startup."""
        try:
            return factory()
        except Exception as e:
            print(f"[init] {label} disabled ({type(e).__name__}: {e})")
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

        # Wi-Fi (Kismet DroneID / nmcli SSID) + Bluetooth Remote ID — same schema.
        wifi_hits = self.wifi.scan() if self.wifi else []
        if self.ble is not None:
            wifi_hits = wifi_hits + self.ble.scan()
        wifi_conf = max((h["confidence"] for h in wifi_hits), default=0.0)
        rid_decoded = any(h.get("decoded_remote_id") for h in wifi_hits)

        # Vision (A4 YOLO), acoustic (A5), sub-GHz control link (RTL-SDR-reachable).
        vis = self.vision.read() if self.vision else {}
        visual_conf = float(vis.get("confidence", 0.0))
        bbox = vis.get("bbox")
        aco = self.acoustic.read() if self.acoustic else {}
        acoustic_conf = float(aco.get("confidence", 0.0))
        cl = self.control.read() if self.control else {}
        control_conf = float(cl.get("confidence", 0.0))

        # Pan-tilt tracking -> camera BEARING; TF-Luna -> RANGE; fuse -> POSITION.
        # A single omni RF receiver only proves presence — position needs a
        # bearing (camera/pan-tilt) plus a range (LiDAR). Without a valid range
        # we honestly report a bearing-only fix rather than inventing a distance.
        fix = None
        if bbox is not None:
            if self.pantilt is not None:
                self._pan, self._tilt = self.pantilt.track(bbox)
            az, el = bbox_to_bearing(bbox[0], bbox[1], self._pan, self._tilt)
            rng = None
            if self.lidar is not None:
                lr = self.lidar.read()
                if lr.get("valid"):
                    rng = lr["range_m"]
            if rng is not None and self.sensor_lat is not None:
                try:
                    fix = localize(bbox[0], bbox[1], rng, self._pan, self._tilt,
                                   self.sensor_lat, self.sensor_lon)
                except Exception:
                    fix = None
            if fix is None:              # bearing only (no valid range or no GPS origin)
                fix = {"azimuth_deg": az, "elevation_deg": el, "range_m": rng,
                       "lat": None, "lon": None, "alt": None, "bearing_only": True}

        # ADS-B: suppress a "drone" that is really a manned aircraft at that spot.
        aircraft_match = False
        if self.adsb is not None:
            drone_ll = None
            if fix:
                drone_ll = (fix["lat"], fix["lon"])
            else:
                rl = next((h for h in wifi_hits if h.get("drone_lat")), None)
                if rl:
                    drone_ll = (rl["drone_lat"], rl["drone_lon"])
            if drone_ll:
                try:
                    aircraft_match = self.adsb.aircraft_nearby(*drone_ll)
                except Exception:
                    aircraft_match = False

        # Lingering-target duration -> A7 modifiers (+10 >30s, +10 >60s).
        active = (looks_droney or bool(wifi_hits) or visual_conf > 0.5
                  or acoustic_conf > 0.5 or control_conf > 0.5)
        now = time.monotonic()
        if active:
            self._drone_since = self._drone_since or now
            duration = now - self._drone_since
        else:
            self._drone_since = None
            duration = 0.0

        # A7 fusion. All vectors combine; a decoded Remote ID / SSID match is
        # near-certain ID (fingerprint-grade), and a sub-GHz control link is an
        # RF drone emitter, so it lifts the RF confidence.
        score = compute_threat_score(ThreatInputs(
            rf_conf=max(drone_prob, control_conf),
            visual_conf=visual_conf,
            acoustic_conf=acoustic_conf,
            fingerprint_conf=max(fp_conf, wifi_conf),
            bluetooth_conf=bt_prob,
            duration_sec=duration,
            is_unknown=is_unknown,
            remote_id_decoded=rid_decoded,
            aircraft_match=aircraft_match))

        return {"iq": iq, "source": source, "rf": rf, "drone_prob": drone_prob,
                "fp_model": fp_model, "fp_conf": fp_conf,
                "anom_verdict": anom_verdict, "is_unknown": is_unknown,
                "wifi_hits": wifi_hits, "duration": duration, "score": score,
                "visual_conf": visual_conf, "bbox": bbox, "vis": vis,
                "acoustic_conf": acoustic_conf, "control": cl,
                "control_conf": control_conf, "fix": fix,
                "aircraft_match": aircraft_match,
                "pan": self._pan, "tilt": self._tilt}

    # ---- escalation + messaging ----------------------------------------------
    def _handle(self, v: dict) -> None:
        score = v["score"]
        escalate = score["score"] >= self.args.threshold or bool(v["wifi_hits"])

        rf = v["rf"]
        bits = [f"{rf['label'].upper()} {rf['confidence']}%"]
        if v["fp_model"] and v["fp_conf"] > 0.3:
            bits.append(f"model~{v['fp_model']} ({v['fp_conf']*100:.0f}%)")
        if v["wifi_hits"]:
            ssids = list(dict.fromkeys(h["ssid"] for h in v["wifi_hits"]))
            bits.append("SSID:" + ",".join(ssids))
        rid = next((h for h in v["wifi_hits"] if h.get("model")), None)
        if rid:                                   # decoded DJI/Remote ID payload
            bits.append(f"RID:{rid.get('manufacturer','?')} {rid['model']}".strip())
            if rid.get("drone_lat") is not None:
                bits.append(f"drone@{rid['drone_lat']:.5f},{rid['drone_lon']:.5f}")
            if rid.get("pilot_lat") is not None:
                bits.append(f"pilot@{rid['pilot_lat']:.5f},{rid['pilot_lon']:.5f}")
        if v.get("visual_conf", 0) > 0.4:
            bits.append(f"VIS {v['visual_conf']*100:.0f}%")
        if v.get("acoustic_conf", 0) > 0.4:
            bits.append(f"AUD {v['acoustic_conf']*100:.0f}%")
        if v.get("control_conf", 0) > 0.4:
            band = (v.get("control") or {}).get("band_hz")
            bits.append(f"CTRL {v['control_conf']*100:.0f}%"
                        + (f"@{band/1e6:.0f}MHz" if band else ""))
        if v.get("fix"):
            f = v["fix"]
            brg = f"az{f['azimuth_deg']:.0f}/el{f['elevation_deg']:.0f}"
            if f.get("lat") is not None:                     # full 3D position
                bits.append(f"loc@{f['lat']:.5f},{f['lon']:.5f} "
                            f"({brg}, {f['range_m']:.1f}m)")
            elif f.get("range_m") is not None:               # bearing + range, no GPS origin
                bits.append(f"bearing {brg}, {f['range_m']:.1f}m (pass --lat/--lon for GPS)")
            else:                                            # bearing only (drone out of LiDAR range)
                bits.append(f"bearing {brg} (no range: >8m or no LiDAR)")
        if v.get("aircraft_match"):
            bits.append("AIRCRAFT-NEARBY(-20)")
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
               "modifiers": "; ".join(score["modifiers"]),
               # Remote ID / DJI DroneID enrichment (blank unless Kismet decoded it)
               "rid_manuf": (rid or {}).get("manufacturer", ""),
               "rid_model": (rid or {}).get("model", ""),
               "rid_serial": (rid or {}).get("serial", ""),
               "drone_lat": (rid or {}).get("drone_lat", "") or "",
               "drone_lon": (rid or {}).get("drone_lon", "") or "",
               "pilot_lat": (rid or {}).get("pilot_lat", "") or "",
               "pilot_lon": (rid or {}).get("pilot_lon", "") or "",
               # multi-sensor fusion + single-node localization
               "visual_conf": round(v.get("visual_conf", 0.0) * 100, 1),
               "acoustic_conf": round(v.get("acoustic_conf", 0.0) * 100, 1),
               "control_conf": round(v.get("control_conf", 0.0) * 100, 1),
               "control_band_mhz": round(((v.get("control") or {}).get("band_hz")
                                          or 0) / 1e6, 1),
               "loc_lat": (v.get("fix") or {}).get("lat") or "",
               "loc_lon": (v.get("fix") or {}).get("lon") or "",
               "loc_alt": (v.get("fix") or {}).get("alt") or "",
               "azimuth_deg": (v.get("fix") or {}).get("azimuth_deg", ""),
               "elevation_deg": (v.get("fix") or {}).get("elevation_deg", ""),
               "range_m": (v.get("fix") or {}).get("range_m") or "",
               "aircraft_nearby": v.get("aircraft_match", False)}

        msg = (f"🚨 CampusShield: {score['level']} {score['score']}/100\n"
               f"{detail}\nlingering: {v['duration']:.0f}s")
        if explanation:
            msg += f"\nwhy: {explanation}"

        # Mirror onto the optional MQTT bus the rest of CampusShield listens on.
        publish("campusshield/detection", row, verbose=False)
        self.alerts.fire(row=row, message=msg, escalate=escalate)

        # On-device OLED + Green->Red light tower every pass; actuation on escalation.
        if self.display is not None:
            try:
                self.display.show(score["level"], score["score"], detail[:40])
            except Exception:
                pass
        if self.tower is not None:
            try:
                self.tower.set_level(score["level"])
            except Exception:
                pass
        if escalate:
            if self.response is not None:
                try:
                    self.response.engage(score["level"])       # spotlight/strobe/buzzer
                except Exception:
                    pass
            if self.recorder is not None:
                try:
                    self.recorder.record(row, frame=(v.get("vis") or {}).get("frame"))
                except Exception:
                    pass
            if self.lora is not None:
                try:
                    self.lora.send(row)                        # relay to mesh nodes
                except Exception:
                    pass
            if self.pluto is not None:                         # OWN authorized drone only
                try:
                    self.pluto.engage(v)                       # logs its own result
                except Exception:
                    pass
        elif self.response is not None:
            try:
                self.response.disengage()
            except Exception:
                pass

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
        def _m(x):
            return x.mode if x is not None else "off"
        print(f"wifi    : {_m(self.wifi)}   ble: {_m(self.ble)}")
        print(f"vision  : {_m(self.vision)}   acoustic: {_m(self.acoustic)}   "
              f"control-link: {_m(self.control)}   adsb: {_m(self.adsb)}")
        print(f"track   : {_m(self.pantilt)}   lidar: {_m(self.lidar)}   "
              f"response: {_m(self.response)}   display: {_m(self.display)}   "
              f"lora: {_m(self.lora)}")
        print(f"gps     : {_m(self.gps)}   light-tower: {_m(self.tower)}   "
              f"health: {_m(self.health)}   pluto-land: {_m(self.pluto)}")
        if self.sensor_lat is not None:
            print(f"origin  : {self.sensor_lat:.6f},{self.sensor_lon:.6f} "
                  f"(sensor position for localization)")
        if self.power is not None:
            try:
                pw = self.power.read()
                print(f"power   : {pw['voltage_v']:.2f}V  {pw['percent']:.0f}%  "
                      f"({self.power.mode})")
            except Exception:
                pass
        if self.health is not None:
            try:
                h = self.health.read()
                print(f"health  : CPU {h.get('cpu_temp_c')}C  cpu {h.get('cpu_percent')}%  "
                      f"ram {h.get('ram_percent')}%  disk {h.get('disk_percent')}%  "
                      f"subsystems={h.get('subsystems')}")
            except Exception:
                pass
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
                   help="disable the Wi-Fi / Kismet detector")
    p.add_argument("--no-ble", dest="ble", action="store_false",
                   help="disable the Bluetooth Remote ID scanner")
    p.add_argument("--no-vision", dest="vision", action="store_false",
                   help="disable the A4 YOLO camera vector")
    p.add_argument("--no-acoustic", dest="acoustic", action="store_false",
                   help="disable the A5 acoustic vector")
    p.add_argument("--no-response", dest="response", action="store_false",
                   help="disable the spotlight/strobe/buzzer response layer")
    p.add_argument("--no-lora", dest="lora", action="store_false",
                   help="disable the LoRa mesh relay")
    p.add_argument("--track", action="store_true",
                   help="enable pan-tilt auto-tracking of the camera target")
    p.add_argument("--no-lidar", dest="lidar", action="store_false",
                   help="disable the TF-Luna LiDAR range (localization -> bearing only)")
    p.add_argument("--pluto-land", dest="pluto_land", action="store_true",
                   help="AUTHORIZED OWN-DRONE ONLY: command your allow-listed Pluto to LAND on escalation")
    p.add_argument("--own-drone", nargs="*", default=[], dest="own_drone",
                   help="allow-list tokens (SSID/serial) identifying YOUR OWN drone(s), e.g. PLUTO")
    p.add_argument("--vision-source", default=0, dest="vision_source",
                   help="webcam index or ESP32-CAM stream URL (http://IP:81/stream)")
    p.add_argument("--lat", type=float, default=None,
                   help="sensor latitude — enables single-node GPS localization")
    p.add_argument("--lon", type=float, default=None, help="sensor longitude")
    p.add_argument("--no-csv", action="store_true", help="disable CSV logging")
    p.add_argument("--no-buzzer", action="store_true", help="disable GPIO buzzer")
    p.add_argument("--no-telegram", action="store_true", help="disable Telegram alerts")
    p.set_defaults(wifi=True, ble=True, vision=True, acoustic=True,
                   response=True, lora=True, lidar=True)
    return p.parse_args(argv)


def main(argv=None):
    LiveDetector(parse_args(argv)).run()


if __name__ == "__main__":
    main()
