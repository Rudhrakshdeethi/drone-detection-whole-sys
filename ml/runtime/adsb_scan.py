"""ADS-B scanner — manned-aircraft awareness for false-positive suppression.

Why this exists: manned aircraft (light planes, helicopters, airliners on
approach) are a major source of *false* drone alarms — they show up on radar,
acoustic and vision channels and can look drone-ish at a distance. Happily they
are legally required to broadcast **ADS-B on 1090 MHz**, and 1090 MHz sits well
inside the RTL-SDR V4's range (it tops out ~1.766 GHz, far above 1090 MHz —
whereas the 2.4 GHz drone video band is out of reach). So the *same* SDR family
that can't see 2.4 GHz drone video can positively identify nearby manned traffic.

We don't decode Mode-S ourselves; we poll a running **dump1090** instance (the
standard RTL-SDR ADS-B decoder) over its JSON HTTP endpoint. Any aircraft it
reports near a candidate detection lets the fuser *suppress* that detection as a
manned false positive.

Seamless degradation — identical to the rest of the runtime:
    * dump1090 reachable on its JSON URL -> real live aircraft.
    * dump1090 not running (e.g. laptop) -> mock (0-2 fake aircraft, often none).
    * `simulate=True`                    -> always emit a mock aircraft for demos.

    sc = AdsbScanner()
    planes = sc.scan()                        # list of aircraft dicts
    if sc.aircraft_nearby(lat, lon, 3.0):     # suppress manned false positives
        ...
"""
from __future__ import annotations
import os, sys, math, random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import CENTER_FREQ  # noqa: F401  (kept for constant parity)

ADSB_URL = os.environ.get("DUMP1090_URL",
                          "http://localhost:8080/data/aircraft.json")

# Demo origin (matches kismet_scan's simulated GPS) for placing mock aircraft.
_DEMO_LAT, _DEMO_LON = 12.97160, 77.59460


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometres."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2.0) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2.0) ** 2)
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


class AdsbScanner:
    """Poll dump1090 for nearby manned aircraft (with mock fallback)."""

    def __init__(self, url: str = ADSB_URL, force_mock: bool = False,
                 simulate: bool = False, seed: int | None = None):
        self.url = url
        self.simulate = bool(simulate)      # mock-only: always emit an aircraft
        self.rng = random.Random(seed)
        self._warned = False
        # "real" = we should actually query dump1090.
        self.real = not force_mock and not self.simulate

    # ---- real hardware --------------------------------------------------------
    def _query(self) -> list[dict]:
        import requests
        r = requests.get(self.url, timeout=4)
        r.raise_for_status()
        data = r.json()
        out: list[dict] = []
        for ac in data.get("aircraft", []) if isinstance(data, dict) else []:
            lat = ac.get("lat")
            lon = ac.get("lon")
            out.append({
                "hex": str(ac.get("hex", "")).strip(),
                "flight": str(ac.get("flight", "")).strip(),
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "alt": ac.get("alt_baro", ac.get("altitude")),
                "source": "dump1090",
            })
        return out

    # ---- mock fallback --------------------------------------------------------
    def _mock_aircraft(self, force: bool = False) -> list[dict]:
        if force:
            n = 1
        else:
            # Often empty sky; occasionally 1-2 manned aircraft passing through.
            n = self.rng.choice([0, 0, 0, 1, 1, 2])
        out: list[dict] = []
        for i in range(n):
            hexid = "".join(self.rng.choice("0123456789abcdef") for _ in range(6))
            flight = self.rng.choice(["AIC201", "VTIGR", "IGO455", "N512SP",
                                      "SEJ88", "HELI7"])
            out.append({
                "hex": hexid,
                "flight": flight,
                "lat": round(_DEMO_LAT + self.rng.uniform(-0.05, 0.05), 5),
                "lon": round(_DEMO_LON + self.rng.uniform(-0.05, 0.05), 5),
                "alt": self.rng.choice([1200, 2500, 4500, 9000, 33000]),
                "source": "dump1090(mock)",
            })
        return out

    # ---- public ---------------------------------------------------------------
    def scan(self) -> list[dict]:
        """Return the list of currently-tracked manned aircraft."""
        if self.simulate:
            return self._mock_aircraft(force=True)
        if self.real:
            try:
                return self._query()
            except Exception as e:  # dump1090 down, bad JSON, timeout, etc.
                if not self._warned:
                    print(f"[adsb] query failed ({type(e).__name__}: {e}); "
                          f"using mock for this scan")
                    self._warned = True
                return self._mock_aircraft()
        return self._mock_aircraft()

    def aircraft_nearby(self, lat: float, lon: float,
                        radius_km: float = 3.0) -> bool:
        """True if any tracked aircraft (with a fix) is within radius_km.

        Used by the fuser to suppress a candidate drone detection that is really
        a manned aircraft.
        """
        for ac in self.scan():
            aclat, aclon = ac.get("lat"), ac.get("lon")
            if aclat is None or aclon is None:
                continue
            if haversine_km(lat, lon, aclat, aclon) <= radius_km:
                return True
        return False

    @property
    def mode(self) -> str:
        if self.simulate:
            return "dump1090(sim)"
        return "dump1090" if self.real else "mock"


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(
        description="ADS-B (dump1090 @ 1090 MHz) manned-aircraft scanner")
    p.add_argument("--url", default=ADSB_URL, help="dump1090 aircraft.json URL")
    p.add_argument("--simulate", action="store_true",
                   help="always emit one mock aircraft — no hardware required")
    p.add_argument("--force-mock", action="store_true",
                   help="ignore dump1090 even if reachable")
    p.add_argument("--near", nargs=2, type=float, metavar=("LAT", "LON"),
                   help="test aircraft_nearby() against this point")
    args = p.parse_args(argv)
    sc = AdsbScanner(url=args.url, force_mock=args.force_mock,
                     simulate=args.simulate)
    print(f"mode: {sc.mode}")
    planes = sc.scan()
    print(f"{len(planes)} aircraft:")
    print(json.dumps(planes, indent=2))
    if args.near:
        near = sc.aircraft_nearby(args.near[0], args.near[1])
        print(f"aircraft within 3.0 km of {tuple(args.near)}: {near}")


if __name__ == "__main__":
    main()
