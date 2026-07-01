"""Wi-Fi SSID scan — the Team-Nayara second detection vector, ported in as an
extra evidence source for the threat fuser.

Uses `nmcli` (Linux/Raspberry Pi) to list nearby networks and matches their
SSIDs against known drone-manufacturer name patterns. On a machine without
nmcli it returns no hits (or a simulated one, for demos).

    hits = WifiScanner().scan()      # [{"ssid": "DJI-Mavic-xxxx", "signal": 72}, ...]
"""
from __future__ import annotations
import shutil, subprocess

# Same name signatures the original detector watched for, 2.4 GHz drone radios.
DRONE_SSID_PATTERNS = ["TELLO", "DJI", "MAVIC", "PHANTOM", "MINI", "AIR3",
                       "ANAFI", "PARROT", "SYMA", "SPARK", "AVATA", "NEO"]

NMCLI_BIN = shutil.which("nmcli")


def _signal_to_conf(signal: int) -> float:
    """Map nmcli signal % (0-100) to a [0,1] confidence."""
    return max(0.0, min(1.0, signal / 100.0))


class WifiScanner:
    def __init__(self, patterns=None, force_mock: bool = False,
                 simulate_ssid: str | None = None):
        self.patterns = [p.upper() for p in (patterns or DRONE_SSID_PATTERNS)]
        self.simulate_ssid = simulate_ssid
        self.real = bool(NMCLI_BIN) and not force_mock and simulate_ssid is None

    def _matches(self, ssid: str) -> bool:
        u = ssid.upper()
        return any(p in u for p in self.patterns)

    def _scan_nmcli(self) -> list[dict]:
        # -t terse, -f fields -> "SSID:SIGNAL" per line.
        out = subprocess.run(
            [NMCLI_BIN, "-t", "-f", "SSID,SIGNAL", "device", "wifi", "list"],
            check=True, capture_output=True, text=True, timeout=20).stdout
        hits = []
        for line in out.splitlines():
            if ":" not in line:
                continue
            ssid, _, signal = line.rpartition(":")
            ssid = ssid.strip()
            if ssid and self._matches(ssid):
                try:
                    sig = int(signal)
                except ValueError:
                    sig = 0
                hits.append({"ssid": ssid, "signal": sig,
                             "confidence": _signal_to_conf(sig)})
        return hits

    def scan(self) -> list[dict]:
        """Return drone-name SSID hits. Empty list = clean / no Wi-Fi detector."""
        if self.simulate_ssid:
            return [{"ssid": self.simulate_ssid, "signal": 80, "confidence": 0.8}]
        if not self.real:
            return []
        try:
            return self._scan_nmcli()
        except Exception as e:
            print(f"[wifi] nmcli failed ({type(e).__name__}); skipping Wi-Fi scan")
            return []

    @property
    def mode(self) -> str:
        return "nmcli" if self.real else "off"
