"""BLE Remote ID scanner — the *Bluetooth* drone-broadcast vector.

Why this exists: FAA / ASTM F3411 (and EU) **Remote ID** does not live only in
Wi-Fi beacons — the standard also mandates a **Bluetooth LE** broadcast path.
Most consumer drones (DJI, Autel, Skydio, Parrot, ...) periodically transmit an
*OpenDroneID* message pack over BLE advertisements so any phone or receiver can
read who/where the aircraft and its operator are:

    * Basic ID message   -> UA type + drone serial number (the "id").
    * Location message    -> live drone latitude / longitude / geodetic altitude.
    * System message      -> operator (pilot / ground-station) latitude / longitude.

Physically the beacon rides in an AD structure of **AD type 0x16 (Service Data —
16-bit UUID)** carrying UUID **0xFFFA** (the ASTM Remote ID assigned UUID),
followed by the OpenDroneID application code (0x0D) and the packed message(s).
This module is the Bluetooth sibling of ``kismet_scan.py``: it scans BLE, best-
effort-decodes those messages, and emits the *identical* hit dict the threat
fuser already consumes, so it drops straight into the same fusion path.

Seamless degradation — identical to the rest of the runtime:
    * ``bleak`` present + an adapter present -> real OpenDroneID BLE detections.
    * ``bleak`` missing (e.g. a Windows laptop) -> no hits, loop keeps running.
    * nothing decodes this scan                 -> no hits, cleanly.
    * ``simulate_ssid=...``                      -> one rich mock hit (drone +
                                                    operator GPS) for zero-cost
                                                    demos with no hardware.

    hits = BleRemoteIDScanner().scan()
    # [{"ssid","signal","confidence","manufacturer","model","serial",
    #   "decoded_remote_id","drone_lat","drone_lon","drone_alt",
    #   "pilot_lat","pilot_lon","source"}, ...]

``bleak`` is imported *lazily* inside the scan path, so this file imports and its
``__main__`` self-test runs on a laptop with bleak absent (mock/off).
"""
from __future__ import annotations
import os, sys, struct, asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.runtime.wifi_scan import DRONE_SSID_PATTERNS

# ASTM F3411 / OpenDroneID BLE assigned numbers.
ODID_SERVICE_UUID16 = 0xFFFA            # 16-bit Service Data UUID for Remote ID.
ODID_SERVICE_UUID = "0000fffa-0000-1000-8000-00805f9b34fb"  # 128-bit expansion.
ODID_AD_APP_CODE = 0x0D                 # OpenDroneID application code byte.

# OpenDroneID message-type nibble (high nibble of each 25-byte message header).
ODID_MSG_BASIC_ID = 0x0
ODID_MSG_LOCATION = 0x1
ODID_MSG_SYSTEM = 0x4
ODID_MSG_PACK = 0xF

# Default BLE scan window (seconds) — bounded so we never stall the loop.
BLE_TIMEOUT = float(os.environ.get("BLE_REMOTEID_TIMEOUT", "4.0"))


def _sig_to_conf(dbm: float | None) -> float:
    """Map a BLE RSSI in dBm (~-95 weak .. -40 strong) to [0, 1]."""
    if dbm is None:
        return 0.5
    return max(0.0, min(1.0, (float(dbm) + 95.0) / 55.0))


def _lat_lon_i32(raw: int) -> float:
    """OpenDroneID encodes lat/lon as int32 in 1e-7 degree units."""
    return raw / 1e7


class BleRemoteIDScanner:
    """Scan Bluetooth LE for OpenDroneID Remote ID beacons (with mock fallback)."""

    def __init__(self, force_mock: bool = False, simulate_ssid: str | None = None,
                 timeout: float = BLE_TIMEOUT, patterns=None):
        self.simulate_ssid = simulate_ssid
        self.force_mock = force_mock
        self.timeout = float(timeout)
        self.patterns = [p.upper() for p in (patterns or DRONE_SSID_PATTERNS)]
        self._warned = False
        # "real" = a live bleak-backed BLE scan we should actually run.
        self.real = (not force_mock and simulate_ssid is None
                     and self._bleak_available())

    # ---- availability ---------------------------------------------------------
    @staticmethod
    def _bleak_available() -> bool:
        """True only if bleak can be imported — never raises, never hangs."""
        try:
            import bleak  # noqa: F401
            return True
        except Exception:
            return False

    def available(self) -> bool:
        """True if this scanner can produce hits (live BLE OR a simulation)."""
        return self.real or self.simulate_ssid is not None

    # ---- real BLE -------------------------------------------------------------
    def _query(self) -> list[dict]:
        """Run one bounded BLE discovery pass and decode OpenDroneID beacons.

        bleak is fully async; we drive it on a throwaway event loop so callers
        stay synchronous (matching KismetScanner.scan()).
        """
        from bleak import BleakScanner

        async def _discover():
            # return_adv=True -> {address: (device, AdvertisementData)}.
            return await BleakScanner.discover(
                timeout=self.timeout, return_adv=True)

        try:
            found = asyncio.run(_discover())
        except RuntimeError:
            # An event loop is already running (embedded in async host): fall
            # back to a private loop so we still degrade cleanly, not crash.
            loop = asyncio.new_event_loop()
            try:
                found = loop.run_until_complete(_discover())
            finally:
                loop.close()

        hits: list[dict] = []
        for _addr, pair in (found or {}).items():
            device, adv = pair
            parsed = self._parse(device, adv)
            if parsed:
                hits.append(parsed)
        return hits

    def _extract_odid_payload(self, adv) -> bytes | None:
        """Pull the OpenDroneID application payload out of an advertisement.

        Preferred source is the 16-bit Service Data for UUID 0xFFFA. bleak
        exposes ``service_data`` keyed by 128-bit UUID string, so we match the
        0xFFFA expansion. The leading byte of that service data is the
        OpenDroneID application code (0x0D); the message pack follows it.
        """
        sd = getattr(adv, "service_data", None) or {}
        for uuid, data in sd.items():
            u = str(uuid).lower()
            if u == ODID_SERVICE_UUID or u.startswith("0000fffa"):
                buf = bytes(data)
                if buf and buf[0] == ODID_AD_APP_CODE:
                    return buf[1:]      # strip the app-code byte.
                return buf
        return None

    def _iter_messages(self, payload: bytes):
        """Yield each 25-byte OpenDroneID message from a payload/pack.

        A single-message beacon is 25 bytes. A "message pack" (type 0xF) has a
        2-byte header (type/version + msg size + msg count) then N*25 bytes.
        Kept defensive: anything malformed is simply skipped.
        """
        if not payload:
            return
        first_type = (payload[0] >> 4) & 0x0F
        if first_type == ODID_MSG_PACK and len(payload) >= 3:
            msg_size = payload[1] or 25
            count = payload[2]
            body = payload[3:]
            for i in range(count):
                chunk = body[i * msg_size:(i + 1) * msg_size]
                if len(chunk) >= 1:
                    yield chunk
        else:
            for i in range(0, len(payload) - (len(payload) % 25 or 25) + 1, 25):
                chunk = payload[i:i + 25]
                if len(chunk) == 25:
                    yield chunk

    def _decode_messages(self, payload: bytes) -> dict:
        """Best-effort decode of Basic ID / Location / System messages.

        Field offsets follow the ASTM F3411 / OpenDroneID packed layout. Where
        the spec is version-dependent we stay tolerant and never raise — a
        partial decode is better than dropping a real drone.
        """
        out: dict = {"serial": "", "drone_lat": None, "drone_lon": None,
                     "drone_alt": None, "pilot_lat": None, "pilot_lon": None}
        for msg in self._iter_messages(payload):
            if len(msg) < 1:
                continue
            mtype = (msg[0] >> 4) & 0x0F
            try:
                if mtype == ODID_MSG_BASIC_ID and len(msg) >= 21:
                    # byte0 hdr, byte1 id-type/ua-type, bytes 2..21 UAS ID (ASCII).
                    uas_id = msg[2:22].split(b"\x00")[0]
                    txt = uas_id.decode("ascii", "ignore").strip()
                    if txt:
                        out["serial"] = txt
                elif mtype == ODID_MSG_LOCATION and len(msg) >= 16:
                    # lat @8..12, lon @12..16 as little-endian int32 (1e-7 deg).
                    lat = struct.unpack_from("<i", msg, 8)[0]
                    lon = struct.unpack_from("<i", msg, 12)[0]
                    if lat or lon:
                        out["drone_lat"] = _lat_lon_i32(lat)
                        out["drone_lon"] = _lat_lon_i32(lon)
                    if len(msg) >= 18:
                        # Pressure/geodetic altitude: 0.5 m units, -1000 m offset.
                        alt_raw = struct.unpack_from("<H", msg, 16)[0]
                        if alt_raw:
                            out["drone_alt"] = alt_raw * 0.5 - 1000.0
                elif mtype == ODID_MSG_SYSTEM and len(msg) >= 13:
                    # Operator lat @5..9, lon @9..13 as little-endian int32.
                    plat = struct.unpack_from("<i", msg, 5)[0]
                    plon = struct.unpack_from("<i", msg, 9)[0]
                    if plat or plon:
                        out["pilot_lat"] = _lat_lon_i32(plat)
                        out["pilot_lon"] = _lat_lon_i32(plon)
            except (struct.error, ValueError, IndexError):
                continue
        return out

    def _parse(self, device, adv) -> dict | None:
        name = (getattr(adv, "local_name", None)
                or getattr(device, "name", None)
                or getattr(device, "address", None) or "unknown")
        rssi = getattr(adv, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", None)

        payload = self._extract_odid_payload(adv)
        decoded_fields = self._decode_messages(payload) if payload else {}
        decoded = bool(payload)         # a real OpenDroneID BLE beacon.

        # Fall back to name matching for drones that advertise but didn't decode.
        name_hit = any(p in str(name).upper() for p in self.patterns)
        if not (decoded or name_hit):
            return None

        up = str(name).upper()
        manuf = ("DJI" if "DJI" in up or "MAVIC" in up or "TELLO" in up
                 else "Autel" if "AUTEL" in up
                 else "Parrot" if "PARROT" in up or "ANAFI" in up
                 else "Unknown")
        model = next((m for m in ("Mavic 3", "Mini 4", "Air 3", "Tello",
                                  "Phantom", "Anafi", "EVO")
                      if m.replace(" ", "").upper() in up.replace("-", "")), "")

        conf = 0.97 if decoded else min(0.6, _sig_to_conf(rssi))
        return {
            "ssid": str(name),
            "signal": rssi,
            "confidence": round(conf, 2),
            "manufacturer": manuf,
            "model": model,
            "serial": str(decoded_fields.get("serial", "")),
            "decoded_remote_id": decoded,
            "drone_lat": decoded_fields.get("drone_lat"),
            "drone_lon": decoded_fields.get("drone_lon"),
            "drone_alt": decoded_fields.get("drone_alt"),
            "pilot_lat": decoded_fields.get("pilot_lat"),
            "pilot_lon": decoded_fields.get("pilot_lon"),
            "source": "ble",
        }

    # ---- mock -----------------------------------------------------------------
    def _simulated(self, ssid: str) -> dict:
        """One realistic OpenDroneID BLE hit (drone + operator GPS) for demos."""
        up = ssid.upper()
        manuf = ("DJI" if "DJI" in up or "MAVIC" in up or "TELLO" in up
                 else "Autel" if "AUTEL" in up
                 else "Parrot" if "PARROT" in up or "ANAFI" in up
                 else "Unknown")
        model = next((m for m in ("Mavic 3", "Mini 4", "Air 3", "Tello",
                                  "Phantom", "Anafi", "EVO")
                      if m.replace(" ", "").upper() in up.replace("-", "")),
                     "Mavic 3")
        base_lat, base_lon = 12.97160, 77.59460       # demo origin
        return {
            "ssid": ssid, "signal": -58, "confidence": 0.96,
            "manufacturer": manuf, "model": model, "serial": "SIM-BLE-7F3A2C10",
            "decoded_remote_id": True,
            "drone_lat": base_lat + 0.00105, "drone_lon": base_lon + 0.00070,
            "drone_alt": 76.0,
            "pilot_lat": base_lat - 0.00035, "pilot_lon": base_lon - 0.00010,
            "source": "ble(mock)",
        }

    # ---- public ---------------------------------------------------------------
    def scan(self) -> list[dict]:
        if self.simulate_ssid:
            return [self._simulated(self.simulate_ssid)]
        if not self.real:
            return []
        try:
            return self._query()
        except Exception as e:  # adapter yanked mid-run, permissions, timeout...
            if not self._warned:
                print(f"[ble] scan failed ({type(e).__name__}: {e}); "
                      f"no Remote ID this scan")
                self._warned = True
            return []

    @property
    def mode(self) -> str:
        if self.simulate_ssid:
            return "ble(sim)"
        return "ble" if self.real else "off"


def make_drone_rf_scanner(force_mock: bool = False,
                          simulate_ssid: str | None = None):
    """Return a BLE Remote ID scanner (Bluetooth sibling of the Kismet factory).

    Mirrors ``kismet_scan.make_drone_rf_scanner``: ``simulate_ssid`` always
    routes to the mock so demos show the full Remote ID payload (drone +
    operator GPS) with no hardware at all.
    """
    return BleRemoteIDScanner(force_mock=force_mock, simulate_ssid=simulate_ssid)


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(
        description="BLE OpenDroneID / Remote ID scanner")
    p.add_argument("--simulate-ssid", default=None,
                   help="emit one mock BLE Remote ID hit (e.g. DJI-Mavic-1A2B)")
    p.add_argument("--timeout", type=float, default=BLE_TIMEOUT,
                   help="BLE discovery window in seconds")
    args = p.parse_args(argv)
    sc = BleRemoteIDScanner(simulate_ssid=args.simulate_ssid,
                            timeout=args.timeout)
    print(f"mode: {sc.mode}")
    hits = sc.scan()
    print(f"{len(hits)} drone hit(s):")
    print(json.dumps(hits, indent=2))


if __name__ == "__main__":
    main()
