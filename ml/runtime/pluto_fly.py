"""pluto_fly.py — talk to YOUR OWN Pluto over the confirmed control link.

Run this WHILE the laptop is connected to the drone's Wi-Fi (you already proved
192.168.4.1:23 is open). It is staged for safety:

  --mode info      (default)  connect + READ telemetry (battery, height,
                              attitude). NO motion. Proves the two-way link.
  --mode motors               arm -> wait 2s -> disarm. Props spin on the GROUND
                              only, to confirm motor command. Keep clear.
  --mode takeoff              arm -> take_off -> hover --hover s -> land -> disarm.
                              REAL FLIGHT. Open area only, hand on the kill.

Everything is logged to pluto-fly-log.txt so you can reconnect the internet and
share the result. A finally-block always tries to land + disarm on any error.

    python -m ml.runtime.pluto_fly --mode info
    python -m ml.runtime.pluto_fly --mode takeoff --hover 4
"""
from __future__ import annotations
import os, sys, time, argparse

LOG = os.path.join(os.path.dirname(__file__), "..", "..", "pluto-fly-log.txt")


def _log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _safe(label, fn):
    try:
        _log(f"  {label}: {fn()}")
    except Exception as e:
        _log(f"  {label}: err({type(e).__name__}: {e})")


def main(argv=None):
    p = argparse.ArgumentParser(description="Fly/telemetry YOUR OWN Pluto.")
    p.add_argument("--host", default=os.environ.get("PLUTO_HOST", "192.168.4.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PLUTO_PORT", "23")))
    p.add_argument("--mode", choices=["info", "motors", "takeoff"], default="info")
    p.add_argument("--hover", type=float, default=4.0, help="seconds to hover before landing")
    a = p.parse_args(argv)

    try:
        open(LOG, "w", encoding="utf-8").close()   # fresh log
    except Exception:
        pass
    _log(f"=== pluto_fly mode={a.mode} host={a.host}:{a.port} ===")

    try:
        from plutocontrol import Pluto
    except Exception as e:
        _log(f"plutocontrol not importable: {e}")
        return 1

    d = Pluto()
    connect = getattr(d, "connect", None)
    try:
        try:
            connect(a.host, a.port)
        except TypeError:
            connect()
        _log("connected.")
    except Exception as e:
        _log(f"CONNECT FAILED: {type(e).__name__}: {e} "
             f"(are you on the drone Wi-Fi? is {a.host}:{a.port} open?)")
        return 1

    try:
        time.sleep(1.0)
        _log("--- telemetry ---")
        _safe("battery", d.get_battery)
        _safe("battery %", d.get_battery_percentage)
        _safe("height", d.get_height)
        _safe("roll", d.get_roll)
        _safe("pitch", d.get_pitch)
        _safe("yaw", d.get_yaw)

        if a.mode == "info":
            _log("info-only; no motion. Re-run --mode motors or --mode takeoff to move.")
            return 0

        if a.mode == "motors":
            _log("ARM (props will spin on the ground) ...")
            d.arm(); time.sleep(2.0)
            _log("DISARM.")
            d.disarm()
            return 0

        if a.mode == "takeoff":
            _log("ARM ...");      d.arm();      time.sleep(2.0)
            _log("TAKE OFF ...");  d.take_off(); time.sleep(max(1.0, a.hover))
            _log("LAND ...");      d.land();     time.sleep(3.0)
            _log("DISARM.");       d.disarm()
            return 0
    except Exception as e:
        _log(f"ERROR mid-flight: {type(e).__name__}: {e} -> forcing LAND+DISARM")
        try: d.land(); time.sleep(2.0)
        except Exception: pass
        try: d.disarm()
        except Exception: pass
        return 1
    finally:
        try: d.disconnect()
        except Exception: pass
        _log("=== done — reconnect internet and share pluto-fly-log.txt ===")


if __name__ == "__main__":
    sys.exit(main())
