"""Authorized own-drone LAND for a DJI/Ryze Tello — demo interceptor path.

The Tello speaks a tiny **UDP ASCII SDK** on ``192.168.10.1:8889``. To land:

    -> "command"   (enter SDK mode)   <- "ok"
    -> "land"                          <- "ok"

This mirrors :class:`ml.runtime.pluto_control.PlutoDefence` (same ``engage()``
contract and safety model) so the dashboard can route LAND to whichever drone is
configured. Own-drone, land-only, allow-list gated — never touches other drones.

IMPORTANT — single client: a stock Tello accepts only ONE WiFi connection at a
time, so the laptop must HOLD the link (phone disconnected) to command the land.
That is the "interceptor seizes the link and lands it" demo.

With no Tello reachable (e.g. still on the internet) it runs in mock and only
prints what it *would* do.
"""
from __future__ import annotations
import os, socket, time

TELLO_HOST = os.environ.get("TELLO_HOST", "192.168.10.1")
TELLO_PORT = int(os.environ.get("TELLO_PORT", "8889"))


class TelloDefence:
    def __init__(self, host: str = TELLO_HOST, port: int = TELLO_PORT,
                 authorized=None, enabled: bool = False, force_mock: bool = False):
        self.host = host
        self.port = int(port)
        self.authorized = {str(a).upper() for a in (authorized or []) if str(a).strip()}
        self.enabled = bool(enabled)
        self.force_mock = bool(force_mock)
        self._sock = None

    # ---- is this detection our own, allow-listed drone? -----------------------
    def match(self, verdict: dict) -> str | None:
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

    # ---- UDP send / receive one ack -------------------------------------------
    def _send(self, cmd: str, timeout: float = 3.0) -> str:
        self._sock.sendto(cmd.encode(), (self.host, self.port))
        self._sock.settimeout(timeout)
        try:
            data, _ = self._sock.recvfrom(1024)
            # ASCII-only: Tello acks are 'ok'/'error'/numbers. Dropping non-ASCII
            # bytes here stops a stray/binary packet from crashing the Windows
            # console (cp1252) when we print the ack (UnicodeEncodeError).
            return data.decode("ascii", "ignore").strip()
        except OSError:
            return ""

    # ---- public ---------------------------------------------------------------
    def engage(self, verdict: dict) -> dict:
        """Land our own Tello IFF every safety gate passes."""
        if not self.enabled:
            return {"action": "none", "reason": "tello response disabled"}
        who = self.match(verdict)
        if not who:
            return {"action": "none",
                    "reason": "not an authorized own-drone (allow-list miss)"}
        if self.force_mock:
            print(f"[tello] (mock) would LAND own drone '{who}' - no drone reachable")
            return {"action": "land", "target": who, "mode": "mock", "sent": False}
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # The Tello SDK replies to local UDP 8889; bind it so we get the acks.
            try:
                self._sock.bind(("", TELLO_PORT))
            except OSError:
                self._sock.bind(("", 0))  # fall back to ephemeral if 8889 is busy
            # Enter SDK mode; the Tello needs a moment before it accepts motion cmds.
            ack1 = self._send("command")
            time.sleep(1.5)
            self._send("command")            # some units want it twice to lock SDK mode
            time.sleep(0.8)
            # Land, retrying: 'error' usually means "not airborne yet / still settling".
            # Between tries, neutralize any drift with a hover rc so it's landable.
            ack2 = ""
            for attempt in range(4):
                ack2 = self._send("land", timeout=7.0)
                print(f"[tello] land attempt {attempt+1}: {ack2!r}")
                if "ok" in ack2.lower():
                    break
                self._send("rc 0 0 0 0")     # stop drift
                time.sleep(1.5)
            sent = "ok" in (ack1 + ack2).lower()
            print(f"[tello] own-drone '{who}' -> command={ack1!r} land={ack2!r}")
            return {"action": "land", "target": who, "mode": "tello-udp",
                    "method": "land", "sent": sent, "ack": ack2 or ack1 or "no-reply"}
        except Exception as e:
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
    p = argparse.ArgumentParser(description="Authorized own-drone LAND (Tello). Own drone only.")
    p.add_argument("--authorized", nargs="*", default=["TELLO"])
    p.add_argument("--enabled", action="store_true")
    p.add_argument("--force-mock", action="store_true")
    p.add_argument("--ssid", default="TELLO-954B1F")
    args = p.parse_args(argv)
    td = TelloDefence(authorized=args.authorized, enabled=args.enabled, force_mock=args.force_mock)
    print(f"mode: {td.mode}")
    own = {"wifi_hits": [{"ssid": args.ssid, "model": "Tello"}]}
    other = {"wifi_hits": [{"ssid": "DJI-Mavic-9Z", "model": "Mavic 3"}]}
    print("own drone  ->", json.dumps(td.engage(own)))
    print("other drone->", json.dumps(td.engage(other)))
    td.close()


if __name__ == "__main__":
    main()
