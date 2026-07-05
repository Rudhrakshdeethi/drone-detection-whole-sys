"""u-blox NEO-6M GPS reader — gives *this node* its own position.

Localization needs a fixed anchor: the camera gives a *bearing*, the LiDAR gives
a *range*, and this module gives the *origin* those two are measured from. Without
knowing where the sensor itself sits, "drone is 40 m north-east" cannot be turned
into an actual latitude/longitude. So this is the reference frame for the whole
bearing + range -> drone-GPS computation.

Hardware: u-blox NEO-6M over UART (default 9600 baud, 8N1). The module streams
plain-text NMEA sentences once per second; we parse two of them:

    $GPGGA / $GNGGA  -> fix time, lat, lon, fix quality, satellites, HDOP, altitude
    $GPRMC / $GNRMC  -> fix status, lat, lon (fallback when GGA is sparse)

(The GN* variants are emitted when the module tracks multiple constellations,
e.g. GPS + GLONASS; we accept both talker IDs.) NMEA encodes coordinates as
ddmm.mmmm — degrees and *minutes* concatenated — so decimal degrees are
`deg + minutes/60`, then negated for the S / W hemispheres.

Seamless degradation — identical idiom to the rest of the runtime:
    * NEO-6M on a real UART port      -> live GPS fixes parsed from NMEA.
    * pyserial missing OR no port set  -> mock fixed fix (sim_lat/sim_lon), so
                                          the localization path runs free on a
                                          Windows laptop with zero hardware.

    fix = GpsReader().read()
    # {"lat","lon","alt","fix": bool,"sats": int,"hdop": float|None,"source"}

Env config (all optional):  GPS_PORT (e.g. /dev/serial0 or COM4)   GPS_BAUD
"""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

GPS_PORT = os.environ.get("GPS_PORT")               # None -> mock unless given
GPS_BAUD = int(os.environ.get("GPS_BAUD", "9600"))


def _nmea_checksum_ok(sentence: str) -> bool:
    """Validate the `*HH` XOR checksum NMEA appends to every sentence.

    Returns True when there is no checksum at all (some cheap modules omit it)
    so we stay permissive rather than dropping otherwise-good fixes.
    """
    if "*" not in sentence:
        return True
    body, _, chk = sentence.partition("*")
    body = body.lstrip("$")
    try:
        want = int(chk[:2], 16)
    except ValueError:
        return True
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == want


def _dm_to_deg(dm: str, hemi: str) -> float | None:
    """Convert an NMEA ddmm.mmmm / dddmm.mmmm field to signed decimal degrees.

    Latitude uses 2 leading degree digits, longitude 3. The remainder is minutes,
    so decimal = degrees + minutes/60, negated for the S / W hemispheres.
    """
    if not dm:
        return None
    try:
        val = float(dm)
    except ValueError:
        return None
    deg = int(val // 100)               # ddmm.mmmm -> the dd (or ddd) part
    minutes = val - deg * 100           # ...and the mm.mmmm minutes remainder
    dec = deg + minutes / 60.0
    if hemi in ("S", "W"):
        dec = -dec
    return dec


class GpsReader:
    """Read this node's own position from a NEO-6M (with mock fallback)."""

    def __init__(self, port: str | None = None, baud: int = GPS_BAUD,
                 force_mock: bool = False, sim_lat: float = 12.9716,
                 sim_lon: float = 77.5946, sim_alt: float = 0.0):
        self.port = port if port is not None else GPS_PORT
        self.baud = int(baud)
        self.sim_lat = float(sim_lat)
        self.sim_lon = float(sim_lon)
        self.sim_alt = float(sim_alt)
        self._warned = False
        self._ser = None
        # "real" = an actual serial NEO-6M we should parse NMEA from.
        self.real = (self._open() if (not force_mock and self.port) else False)
        self._src = "neo6m" if self.real else "mock"

    # ---- serial ---------------------------------------------------------------
    def _open(self) -> bool:
        try:
            import serial                            # pyserial, optional
            self._ser = serial.Serial(self.port, self.baud, timeout=1.0)
            return True
        except Exception as e:
            print(f"[gps] serial open failed ({type(e).__name__}: {e}); "
                  f"using mock position")
            return False

    # ---- NMEA parsing ---------------------------------------------------------
    def _parse_gga(self, f: list[str]) -> dict | None:
        """$--GGA: lat, lon, fix quality, satellites, HDOP, altitude."""
        if len(f) < 10:
            return None
        lat = _dm_to_deg(f[2], f[3])
        lon = _dm_to_deg(f[4], f[5])
        try:
            quality = int(f[6]) if f[6] else 0
        except ValueError:
            quality = 0
        try:
            sats = int(f[7]) if f[7] else 0
        except ValueError:
            sats = 0
        try:
            hdop = float(f[8]) if f[8] else None
        except ValueError:
            hdop = None
        try:
            alt = float(f[9]) if f[9] else None
        except ValueError:
            alt = None
        if lat is None or lon is None:
            return None
        return {"lat": lat, "lon": lon, "alt": alt, "fix": quality > 0,
                "sats": sats, "hdop": hdop, "source": "neo6m"}

    def _parse_rmc(self, f: list[str]) -> dict | None:
        """$--RMC: fallback fix (status A/V, lat, lon) — no altitude/sats/HDOP."""
        if len(f) < 7:
            return None
        active = f[2] == "A"
        lat = _dm_to_deg(f[3], f[4])
        lon = _dm_to_deg(f[5], f[6])
        if lat is None or lon is None:
            return None
        return {"lat": lat, "lon": lon, "alt": None, "fix": active,
                "sats": 0, "hdop": None, "source": "neo6m"}

    def _parse_line(self, line: str) -> dict | None:
        line = line.strip()
        if not line.startswith("$") or not _nmea_checksum_ok(line):
            return None
        body = line.split("*", 1)[0]
        f = body.split(",")
        tag = f[0][3:] if len(f[0]) >= 6 else ""     # strip $GP / $GN talker id
        if tag == "GGA":
            return self._parse_gga(f)
        if tag == "RMC":
            return self._parse_rmc(f)
        return None

    # ---- mock -----------------------------------------------------------------
    def _mock(self) -> dict:
        """Fixed simulated fix so the localization path runs with no hardware."""
        return {"lat": self.sim_lat, "lon": self.sim_lon, "alt": self.sim_alt,
                "fix": True, "sats": 9, "hdop": 0.9, "source": "mock"}

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """One position fix. Prefers GGA (richest); RMC as fallback within a read.

        Reads a bounded burst of NMEA lines, returning the first usable fix. If
        nothing valid arrives it reports the last-seen coordinates with fix=False
        rather than crashing.
        """
        if not self.real:
            return self._mock()
        best: dict | None = None
        try:
            for _ in range(20):                      # ~a couple of 1 Hz cycles
                raw = self._ser.readline()
                if not raw:
                    break
                try:
                    line = raw.decode("ascii", "ignore")
                except Exception:
                    continue
                fix = self._parse_line(line)
                if fix is None:
                    continue
                best = fix
                if fix["fix"] and fix["source"] == "neo6m" and fix["alt"] is not None:
                    return fix                       # a full GGA fix — done
        except Exception as e:
            if not self._warned:
                print(f"[gps] read failed ({type(e).__name__}: {e}); mock position")
                self._warned = True
            return self._mock()
        self._warned = False
        if best is not None:
            return best
        return {"lat": None, "lon": None, "alt": None, "fix": False,
                "sats": 0, "hdop": None, "source": self._src}

    @property
    def mode(self) -> str:
        return self._src

    def close(self) -> None:
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="u-blox NEO-6M GPS reader")
    p.add_argument("--port", default=GPS_PORT, help="serial port (e.g. COM4, /dev/serial0)")
    p.add_argument("--baud", type=int, default=GPS_BAUD)
    p.add_argument("--sim-lat", type=float, default=12.9716)
    p.add_argument("--sim-lon", type=float, default=77.5946)
    p.add_argument("--sim-alt", type=float, default=0.0)
    p.add_argument("--n", type=int, default=3, help="reads to print")
    args = p.parse_args(argv)
    gps = GpsReader(port=args.port, baud=args.baud, sim_lat=args.sim_lat,
                    sim_lon=args.sim_lon, sim_alt=args.sim_alt)
    print(f"mode: {gps.mode}")
    for _ in range(args.n):
        print(json.dumps(gps.read()))
    gps.close()


if __name__ == "__main__":
    main()
