"""Kismet DroneID / Remote ID scanner — the *real* 2.4 GHz drone-RF vector.

Why this exists: the RTL-SDR V4 tops out at 1.766 GHz and cannot capture 2.4 GHz
drone radios. But modern drones announce themselves at the protocol layer:

    * DJI drones broadcast **DJI DroneID** inside their Wi-Fi beacons (OUI 26:37:12)
      — including live telemetry, drone GPS position, and *operator* position.
    * FAA / EU **Remote ID** drones broadcast ID over Wi-Fi NaN/Beacon + Bluetooth.

`kismet` (free, open-source) decodes both with any monitor-mode Wi-Fi card such as
the Wavenex AR271. This module polls Kismet's REST API and turns each detected
drone into the same hit shape the threat fuser already consumes, *plus* the rich
Remote ID fields (manufacturer / model / serial / drone & pilot GPS).

Seamless degradation — identical to the rest of the runtime:
    * Kismet reachable on host:2501  -> real DroneID/Remote ID detections.
    * Kismet not running (e.g. laptop) -> no hits, so the loop still runs free.
    * `simulate_ssid=...`             -> one rich mock DJI hit (GPS included) for
                                         zero-cost demos with no hardware at all.

    hits = KismetScanner().scan()
    # [{"ssid","confidence","manufacturer","model","serial","drone_lat",
    #   "drone_lon","drone_alt","pilot_lat","pilot_lon","source"}, ...]

Env config (all optional):  KISMET_HOST  KISMET_PORT  KISMET_USER  KISMET_PASS
"""
from __future__ import annotations
import os, sys, socket

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.runtime.wifi_scan import WifiScanner, DRONE_SSID_PATTERNS

KISMET_HOST = os.environ.get("KISMET_HOST", "localhost")
KISMET_PORT = int(os.environ.get("KISMET_PORT", "2501"))
KISMET_USER = os.environ.get("KISMET_USER")
KISMET_PASS = os.environ.get("KISMET_PASS")

# How far back to ask Kismet for active devices (negative = relative seconds).
RECENT_SEC = int(os.environ.get("KISMET_RECENT_SEC", "30"))

# Kismet stores coordinates as GeoJSON [longitude, latitude] under this key.
_GEOPOINT = "kismet.common.location.geopoint"
_ALT = "kismet.common.location.alt"


def _sig_to_conf(dbm: float | None) -> float:
    """Map a Wi-Fi signal in dBm (~-90 weak .. -30 strong) to [0, 1]."""
    if dbm is None:
        return 0.5
    return max(0.0, min(1.0, (float(dbm) + 90.0) / 60.0))


def _find_geopoints(obj) -> list[tuple[float, float, float | None]]:
    """Recursively collect every (lat, lon, alt) in a Kismet sub-tree.

    Kismet's schema for UAV telemetry shifts between versions, so instead of
    hard-coding one path we harvest any embedded GeoJSON point — robust across
    releases. Returns points in document order.
    """
    out: list[tuple[float, float, float | None]] = []

    def rec(o):
        if isinstance(o, dict):
            gp = o.get(_GEOPOINT)
            if isinstance(gp, (list, tuple)) and len(gp) >= 2 and (gp[0] or gp[1]):
                try:
                    out.append((float(gp[1]), float(gp[0]),
                                o.get(_ALT) if o.get(_ALT) else None))
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                rec(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                rec(v)

    rec(obj)
    return out


class KismetScanner:
    """Poll Kismet for DroneID / Remote ID detections (with mock fallback)."""

    def __init__(self, host: str = KISMET_HOST, port: int = KISMET_PORT,
                 user: str | None = KISMET_USER, password: str | None = KISMET_PASS,
                 recent_sec: int = RECENT_SEC, patterns=None,
                 force_mock: bool = False, simulate_ssid: str | None = None):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.recent = abs(int(recent_sec))
        self.patterns = [p.upper() for p in (patterns or DRONE_SSID_PATTERNS)]
        self.simulate_ssid = simulate_ssid
        self.force_mock = force_mock
        self._warned = False
        # "real" = a live Kismet we should actually query.
        self.real = (not force_mock and simulate_ssid is None
                     and self._reachable())

    # ---- availability ---------------------------------------------------------
    def _reachable(self) -> bool:
        """Fast, auth-free TCP probe so we never hang the loop on a dead Kismet."""
        try:
            with socket.create_connection((self.host, self.port), timeout=0.5):
                return True
        except OSError:
            return False

    def available(self) -> bool:
        """True if this scanner can produce hits (live Kismet OR a simulation)."""
        return self.real or self.simulate_ssid is not None

    # ---- real Kismet ----------------------------------------------------------
    def _query(self) -> list[dict]:
        import requests
        url = (f"http://{self.host}:{self.port}"
               f"/devices/last-time/-{self.recent}/devices.json")
        # Field simplification keeps the payload small; last item is the whole
        # UAV record (schema varies, so we grab it wholesale and dig locally).
        body = {"fields": [
            "kismet.device.base.macaddr",
            "kismet.device.base.commonname",
            "kismet.device.base.manuf",
            "kismet.device.base.type",
            ["kismet.device.base.signal/kismet.common.signal.last_signal", "sig"],
            "kismet.device.base.location",
            "uav.device",
        ]}
        auth = (self.user, self.password) if self.user else None
        r = requests.post(url, json=body, auth=auth, timeout=6)
        r.raise_for_status()
        return r.json()

    def _parse(self, dev: dict) -> dict | None:
        uav = dev.get("uav.device") or {}
        name = (dev.get("kismet.device.base.commonname")
                or dev.get("kismet.device.base.macaddr") or "unknown")
        manuf = (uav.get("uav.device.uav_manufacturer")
                 or dev.get("kismet.device.base.manuf") or "")
        model = uav.get("uav.device.uav_model") or ""
        serial = uav.get("uav.device.uav_serialnumber") or ""

        decoded = bool(uav)                       # a real DroneID/Remote ID record
        name_hit = any(p in str(name).upper() for p in self.patterns) \
            or any(p in str(manuf).upper() for p in self.patterns) \
            or "UAV" in str(dev.get("kismet.device.base.type", "")).upper() \
            or "DRONE" in str(dev.get("kismet.device.base.type", "")).upper()
        if not (decoded or name_hit):
            return None

        # Drone location from the UAV telemetry; pilot = a *second* distinct point.
        pts = _find_geopoints(uav) or _find_geopoints(
            dev.get("kismet.device.base.location") or {})
        drone_loc = pts[0] if pts else (None, None, None)
        pilot_loc = pts[1] if len(pts) > 1 else (None, None, None)

        conf = 0.97 if decoded else min(0.6, _sig_to_conf(dev.get("sig")))
        return {
            "ssid": str(name),
            "signal": dev.get("sig"),
            "confidence": round(conf, 2),
            "manufacturer": str(manuf),
            "model": str(model),
            "serial": str(serial),
            "decoded_remote_id": decoded,
            "drone_lat": drone_loc[0], "drone_lon": drone_loc[1],
            "drone_alt": drone_loc[2],
            "pilot_lat": pilot_loc[0], "pilot_lon": pilot_loc[1],
            "source": "kismet",
        }

    # ---- mock -----------------------------------------------------------------
    def _simulated(self, ssid: str) -> dict:
        """One realistic DroneID hit (with drone + operator GPS) for free demos."""
        up = ssid.upper()
        manuf = "DJI" if "DJI" in up or "MAVIC" in up or "TELLO" in up else "Unknown"
        model = next((m for m in ("Mavic 3", "Mini 4", "Air 3", "Tello", "Phantom")
                      if m.replace(" ", "").upper() in up.replace("-", "")), "Mavic 3")
        base_lat, base_lon = 12.97160, 77.59460       # demo origin
        return {
            "ssid": ssid, "signal": -52, "confidence": 0.96,
            "manufacturer": manuf, "model": model, "serial": "SIM-1581F2E4A7B9",
            "decoded_remote_id": True,
            "drone_lat": base_lat + 0.00120, "drone_lon": base_lon + 0.00085,
            "drone_alt": 84.0,
            "pilot_lat": base_lat - 0.00040, "pilot_lon": base_lon - 0.00015,
            "source": "kismet(mock)",
        }

    # ---- public ---------------------------------------------------------------
    def scan(self) -> list[dict]:
        if self.simulate_ssid:
            return [self._simulated(self.simulate_ssid)]
        if not self.real:
            return []
        try:
            devs = self._query()
        except Exception as e:  # Kismet down mid-run, auth change, timeout, etc.
            if not self._warned:
                print(f"[kismet] query failed ({type(e).__name__}: {e}); "
                      f"no Remote ID this scan")
                self._warned = True
            return []
        self._warned = False
        hits = []
        for dev in devs if isinstance(devs, list) else []:
            parsed = self._parse(dev)
            if parsed:
                hits.append(parsed)
        return hits

    @property
    def mode(self) -> str:
        if self.simulate_ssid:
            return "kismet(sim)"
        return "kismet" if self.real else "off"


def make_drone_rf_scanner(force_mock: bool = False,
                          simulate_ssid: str | None = None):
    """Pick the best available Wi-Fi drone detector, seamlessly.

    Priority: live Kismet (rich DroneID/Remote ID) -> nmcli SSID matching
    (WifiScanner) -> off. `simulate_ssid` always routes to Kismet so demos show
    the full Remote ID payload (drone + operator GPS).
    """
    ks = KismetScanner(force_mock=force_mock, simulate_ssid=simulate_ssid)
    if ks.available():
        return ks
    return WifiScanner(force_mock=force_mock, simulate_ssid=simulate_ssid)


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="Kismet DroneID / Remote ID scanner")
    p.add_argument("--simulate-ssid", default=None,
                   help="emit one mock DJI hit (e.g. DJI-Mavic-1A2B) — no hardware")
    p.add_argument("--host", default=KISMET_HOST)
    p.add_argument("--port", type=int, default=KISMET_PORT)
    args = p.parse_args(argv)
    sc = KismetScanner(host=args.host, port=args.port,
                       simulate_ssid=args.simulate_ssid)
    print(f"mode: {sc.mode}")
    hits = sc.scan()
    print(f"{len(hits)} drone hit(s):")
    print(json.dumps(hits, indent=2))


if __name__ == "__main__":
    main()
