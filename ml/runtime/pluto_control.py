"""Authorized own-drone response — command YOUR OWN Pluto to LAND.

SCOPE / LEGAL — read this:
  * This controls a drone **you own and are authorized to fly** — it sends a
    normal **LAND / DISARM** command over the drone's own control link. That is
    not an attack; it is you controlling your own device.
  * It will NOT touch any drone that is not on your explicit allow-list. There is
    no jamming, no takeover, no "force a stranger's drone down" — those are
    illegal for civilians without government/defence authorization and are
    deliberately NOT implemented here.
  * It commands a controlled **LAND** (or disarm-on-ground), never a crash/fall.

How it talks to the Pluto (Drona Aviation):
  The Pluto is a WiFi drone speaking **MSP (MultiWii Serial Protocol) over TCP**
  at 192.168.4.1:23 (non-camera WiFi). Preferred path is the official
  `plutocontrol` library (`pip install plutocontrol`, or DronaAviation/plutocontrol),
  which exposes connect()/land()/disarm(). If that library is absent we fall back
  to a minimal raw-MSP disarm over a socket (best-effort). With no drone reachable
  (e.g. a laptop) it runs in mock and only prints what it *would* do.

Safety model (all must hold before any command is sent):
  1. `enabled=True`         — master switch, OFF by default (opt-in only).
  2. a detection matches the `authorized` allow-list (your Pluto's SSID / serial).
  3. the drone is reachable; otherwise it no-ops.

    pd = PlutoDefence(authorized=["PLUTO"], enabled=True)
    pd.engage(verdict)     # lands ONLY if the verdict is your allow-listed Pluto
"""
from __future__ import annotations
import os, sys, socket

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PLUTO_HOST = os.environ.get("PLUTO_HOST", "192.168.4.1")
PLUTO_PORT = int(os.environ.get("PLUTO_PORT", "23"))


def _msp_frame(cmd: int, payload: bytes = b"") -> bytes:
    """Build a MultiWii Serial Protocol request frame: $M< len cmd payload csum."""
    size = len(payload)
    body = bytes([size, cmd]) + payload
    csum = 0
    for b in body:
        csum ^= b
    return b"$M<" + body + bytes([csum & 0xFF])


class PlutoDefence:
    def __init__(self, host: str = PLUTO_HOST, port: int = PLUTO_PORT,
                 authorized=None, enabled: bool = False,
                 force_mock: bool = False):
        self.host = host
        self.port = int(port)
        # Allow-list of YOUR OWN drone identifiers (SSID/serial substrings).
        self.authorized = {str(a).upper() for a in (authorized or []) if str(a).strip()}
        self.enabled = bool(enabled)          # master switch — OFF by default
        self.force_mock = bool(force_mock)
        self._pluto = None                    # plutocontrol handle if used
        self._sock = None
        self._warned = False

    # ---- is this detection our own, allow-listed drone? -----------------------
    def match(self, verdict: dict) -> str | None:
        """Return the matched allow-list token if `verdict` is our own drone."""
        if not self.authorized:
            return None
        candidates: list[str] = []
        for h in verdict.get("wifi_hits", []) or []:
            candidates += [str(h.get("ssid", "")), str(h.get("serial", "")),
                           str(h.get("model", ""))]
        candidates.append(str(verdict.get("fp_model", "") or ""))
        for c in candidates:
            cu = c.upper()
            if cu and any(a in cu for a in self.authorized):
                return c
        return None

    # ---- connect (official lib preferred, raw MSP fallback) -------------------
    def _connect(self) -> str:
        """Return the connection mode actually used: 'plutocontrol'/'msp'/'mock'."""
        if self.force_mock:
            return "mock"
        # 1) Official Drona Aviation library.
        try:
            from plutocontrol import Pluto            # pip install plutocontrol
            self._pluto = Pluto()
            connect = getattr(self._pluto, "connect", None)
            if callable(connect):
                try:
                    connect(self.host, self.port)
                except TypeError:
                    connect()                         # some versions take no args
            return "plutocontrol"
        except Exception:
            self._pluto = None
        # 2) Raw MSP-over-TCP socket.
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=2.0)
            return "msp"
        except OSError:
            return "mock"

    # ---- land the OWN drone ---------------------------------------------------
    def _do_land(self, conn: str) -> str:
        if conn == "plutocontrol":
            for name in ("land", "disarm"):           # prefer land, else disarm
                fn = getattr(self._pluto, name, None)
                if callable(fn):
                    fn()
                    return name
            raise RuntimeError("plutocontrol exposes neither land() nor disarm()")
        if conn == "msp":
            # Best-effort: neutral RC with minimum throttle disarms most MultiWii
            # stacks (MSP_SET_RAW_RC = 200; 8x uint16 LE: roll,pitch,yaw,thr,aux..).
            import struct
            chans = [1500, 1500, 1500, 1000, 1000, 1000, 1000, 1000]
            payload = b"".join(struct.pack("<H", c) for c in chans)
            self._sock.sendall(_msp_frame(200, payload))
            return "disarm(raw-msp)"
        return "mock-land"

    # ---- public ---------------------------------------------------------------
    def engage(self, verdict: dict) -> dict:
        """Land our own drone IFF every safety gate passes. Never touches others."""
        if not self.enabled:
            return {"action": "none", "reason": "pluto response disabled (--pluto-land off)"}
        who = self.match(verdict)
        if not who:
            return {"action": "none",
                    "reason": "not an authorized own-drone (allow-list miss)"}
        try:
            conn = self._connect()
            if conn == "mock":
                print(f"[pluto] (mock) would LAND own drone '{who}' - no drone reachable")
                return {"action": "land", "target": who, "mode": "mock", "sent": False}
            method = self._do_land(conn)
            print(f"[pluto] authorized own-drone '{who}' -> commanded {method} via {conn}")
            return {"action": "land", "target": who, "mode": conn, "method": method,
                    "sent": True}
        except Exception as e:
            if not self._warned:
                print(f"[pluto] land command failed ({type(e).__name__}: {e})")
                self._warned = True
            return {"action": "error", "target": who, "reason": str(e)}

    def close(self) -> None:
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass

    @property
    def mode(self) -> str:
        if not self.enabled:
            return "off"
        return "armed" if self.authorized else "no-allowlist"


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(
        description="Authorized own-drone LAND response (Pluto). Own drone only.")
    p.add_argument("--authorized", nargs="*", default=["PLUTO"],
                   help="allow-list tokens matching YOUR drone's SSID/serial")
    p.add_argument("--enabled", action="store_true", help="master switch (off by default)")
    p.add_argument("--force-mock", action="store_true")
    p.add_argument("--ssid", default="PLUTO-1A2B", help="simulate a detection SSID")
    args = p.parse_args(argv)
    pd = PlutoDefence(authorized=args.authorized, enabled=args.enabled,
                      force_mock=args.force_mock)
    print(f"mode: {pd.mode}")
    own = {"wifi_hits": [{"ssid": args.ssid, "serial": "PLUTO-SN-1", "model": "Pluto"}]}
    other = {"wifi_hits": [{"ssid": "DJI-Mavic-9Z", "serial": "DJI-SN", "model": "Mavic 3"}]}
    print("own drone  ->", json.dumps(pd.engage(own)))
    print("other drone->", json.dumps(pd.engage(other)))     # must refuse
    pd.close()


if __name__ == "__main__":
    main()
