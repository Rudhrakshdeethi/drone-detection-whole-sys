"""Raspberry Pi interceptor orchestrator — the Linux twin of interceptor.ps1.

The Windows script uses `netsh wlan`; the Pi uses **NetworkManager (`nmcli`)**.
Same job, one WiFi radio: remember the house WiFi -> (optionally) fire the ESP32
deauth to free the drone's single client slot -> join the drone's `Pluto_*`/
`TELLO-*` AP -> send a LAND over its control link -> rejoin the house WiFi so the
laptop's SSH/dashboard reconnects.

SCOPE / LEGAL: this only ever deauths + lands YOUR OWN allow-listed demo drone
(see deauth_esp32.py and pluto_control.py). It never touches third-party devices.

Designed to run **autonomously** and survive the WiFi hop (systemd or
`setsid python -m ml.runtime.interceptor ...`), because the moment it leaves the
house WiFi the SSH session that launched it may drop.

Everything degrades to mock on a laptop / with no hardware, so it is safe to
dry-run anywhere:

    python -m ml.runtime.interceptor --dry-run
    python -m ml.runtime.interceptor --drone-prefix Pluto --deauth
    python -m ml.runtime.interceptor --drone-ssid Pluto_2025_2242 --house NxtWave_Te@m
"""
from __future__ import annotations
import os, sys, time, shutil, subprocess, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

NMCLI = shutil.which("nmcli")


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def _nmcli(*args, timeout: int = 30) -> tuple[int, str]:
    """Run an nmcli command; return (rc, output). rc=127 if nmcli is absent."""
    if not NMCLI:
        return 127, ""
    try:
        r = subprocess.run([NMCLI, *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def current_ssid() -> str:
    """SSID we are connected to right now (empty if none / no nmcli)."""
    rc, out = _nmcli("-t", "-f", "ACTIVE,SSID", "device", "wifi")
    if rc != 0:
        return ""
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line.split(":", 1)[1].strip()
    return ""


def find_drone_ssid(prefix: str) -> str:
    """Return the first visible SSID starting with `prefix` (e.g. 'Pluto'), or ''.

    The Pluto SSID changes each session (Pluto_2025_XXXX), so we match the prefix
    rather than a fixed name — same rule the join scripts use.
    """
    rc, out = _nmcli("-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes")
    if rc != 0:
        return ""
    for line in out.splitlines():
        ssid = line.strip()
        if ssid.upper().startswith(prefix.upper()):
            return ssid
    return ""


def join(ssid: str, password: str | None) -> bool:
    """Connect to `ssid` (creating the NM connection if needed). True on success."""
    args = ["device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    rc, out = _nmcli(*args, timeout=45)
    if rc == 0:
        return True
    # If a saved profile exists, `connection up` reuses it (open or WPA2).
    rc2, _ = _nmcli("connection", "up", ssid, timeout=45)
    return rc2 == 0


def gateway_ip() -> str:
    """Default gateway on the current link (the drone's AP after we join it)."""
    rc, out = _nmcli("-t", "-f", "IP4.GATEWAY", "device", "show")
    for line in out.splitlines():
        if line.startswith("IP4.GATEWAY:") and line.split(":", 1)[1].strip():
            return line.split(":", 1)[1].strip()
    return ""


def send_land(ssid: str, host: str, port: int, force_mock: bool) -> dict:
    """Command the OWN allow-listed drone to LAND via pluto_control."""
    os.environ["PLUTO_HOST"] = host
    os.environ["PLUTO_PORT"] = str(port)
    from ml.runtime.pluto_control import PlutoDefence
    pd = PlutoDefence(host=host, port=port, authorized=[ssid],
                      enabled=True, force_mock=force_mock)
    verdict = {"wifi_hits": [{"ssid": ssid, "serial": ssid, "model": ssid}]}
    result = pd.engage(verdict)
    pd.close()
    return result


def run(a) -> int:
    if not NMCLI and not a.dry_run:
        log("nmcli not found — this orchestrator needs NetworkManager (Raspberry "
            "Pi OS has it). Use --dry-run to rehearse the sequence on a laptop.")
    house = a.house or current_ssid()
    log(f"house WiFi to return to : {house or '(unknown — pass --house)'}")

    # --- 1. Optional deauth to free the drone's single client slot -------------
    if a.deauth:
        from ml.runtime.deauth_esp32 import DeauthESP32
        target = a.drone_ssid or a.drone_prefix
        # Allow-list both the prefix and the exact SSID so a TELLO-* target isn't
        # refused just because --drone-prefix still defaults to Pluto.
        allow = [x for x in (a.drone_prefix, a.drone_ssid) if x]
        d = DeauthESP32(authorized=allow, force_mock=a.dry_run,
                        firmware=a.deauth_firmware)
        log(f"ESP deauth ({d.mode}/{d.firmware}) on '{target}' "
            f"for {a.deauth_seconds:.0f}s ...")
        log(f"  {d.run_targeted(target, a.deauth_seconds, select_index=a.deauth_index)}")
        d.close()
        # Give the phone a beat to drop and the AP to free the slot before we grab it.
        time.sleep(a.grab_delay)

    # --- 2. Join the drone -----------------------------------------------------
    ssid = a.drone_ssid
    if not ssid:
        ssid = find_drone_ssid(a.drone_prefix) if NMCLI else f"{a.drone_prefix}_dryrun"
        log(f"resolved drone SSID by prefix '{a.drone_prefix}': {ssid or '(none seen)'}")
    if not ssid:
        log("no drone AP visible — is it powered on and broadcasting?")
        return 2

    if a.dry_run:
        log(f"(dry-run) would join {ssid}, LAND, then rejoin {house}")
    else:
        log(f"joining drone WiFi {ssid} ...")
        if not join(ssid, a.password):
            log(f"could not join {ssid}")
            _restore(house)
            return 3
        for _ in range(20):
            if current_ssid() == ssid:
                break
            time.sleep(1)
        log(f"joined {ssid}")

    # --- 3. LAND ---------------------------------------------------------------
    gw = a.host or (gateway_ip() if (NMCLI and not a.dry_run) else "") or "192.168.4.1"
    log(f"drone gateway: {gw}  -> sending LAND ...")
    try:
        result = send_land(ssid, gw, a.port, force_mock=a.dry_run)
        log(f"  land result: {result}")
    except Exception as e:
        log(f"  LAND failed: {type(e).__name__}: {e}")

    # --- 4. Rejoin the house WiFi ----------------------------------------------
    if not a.stay:
        _restore(house)
    return 0


def _restore(house: str) -> None:
    if not house:
        log("no house SSID to restore (pass --house next time)")
        return
    log(f"rejoining house WiFi {house} ...")
    join(house, None)
    time.sleep(3)
    log(f"now on: {current_ssid() or '(unknown)'}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Raspberry Pi drone interceptor (nmcli).")
    p.add_argument("--drone-prefix", default="Pluto",
                   help="SSID prefix of the session-changing drone AP (default Pluto)")
    p.add_argument("--drone-ssid", default=None,
                   help="exact drone SSID (skips prefix auto-resolve)")
    p.add_argument("--password", default=None,
                   help="drone WiFi password (omit to reuse a saved NM profile / open AP)")
    p.add_argument("--house", default=None,
                   help="house WiFi SSID to return to (default: whatever we're on now)")
    p.add_argument("--host", default=None, help="drone control host (default: gateway/192.168.4.1)")
    p.add_argument("--port", type=int, default=23, help="drone control port (Pluto MSP = 23)")
    p.add_argument("--deauth", action="store_true",
                   help="fire the ESP deauth to free the single client slot first")
    p.add_argument("--deauth-firmware", choices=["marauder", "deauther"],
                   default=os.environ.get("DEAUTH_FW", "marauder"),
                   help="marauder (ESP32) or deauther (ESP8266). Default $DEAUTH_FW/marauder")
    p.add_argument("--deauth-seconds", type=float, default=6.0)
    p.add_argument("--deauth-index", type=int, default=None,
                   help="skip the ESP scan and deauth this AP index directly")
    p.add_argument("--grab-delay", type=float, default=2.0,
                   help="seconds after deauth before we seize the freed slot")
    p.add_argument("--stay", action="store_true",
                   help="stay on the drone WiFi after LAND (do not rejoin house)")
    p.add_argument("--dry-run", action="store_true",
                   help="rehearse the whole sequence in mock — touches no radio")
    return p.parse_args(argv)


def main(argv=None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
