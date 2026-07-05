"""System health monitor — the node's honest self-report.

A field-deployed detector should never fail silently. This module lets the
running system answer "am I healthy, and which of my subsystems are up?" so an
operator (or the judges at a demo) can see CPU load, thermals, memory, disk, and
uptime at a glance, plus a live per-subsystem up/down map (sdr, gps, lora,
camera, ...).

Seamless degradation — same idiom as the rest of the runtime:
    * psutil installed             -> full stats (cpu %, ram %, disk %, temp).
    * psutil missing (bare laptop) -> best-effort via os / statvfs /
                                      shutil.disk_usage; anything unknowable is
                                      reported as None. read() NEVER raises.
    * Raspberry Pi                 -> CPU temp read straight from the kernel's
                                      /sys thermal zone (milli-Celsius) even
                                      without psutil.

    h = HealthMonitor()
    h.register_status("gps", True)
    h.read()
    # {"cpu_temp_c","cpu_percent","ram_percent","disk_percent","uptime_s",
    #  "source","subsystems": {"gps": True, ...}}
"""
from __future__ import annotations
import os, sys, time, shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Raspberry Pi / most Linux SoCs expose CPU temperature here, in milli-Celsius.
PI_THERMAL = "/sys/class/thermal/thermal_zone0/temp"


class HealthMonitor:
    """Report system health + per-subsystem status (degrades gracefully)."""

    def __init__(self, disk_path: str | None = None):
        self.disk_path = disk_path or os.path.abspath(os.sep)   # "/" or "C:\\"
        self._start = time.time()
        self._statuses: dict[str, bool] = {}
        self._psutil = self._load_psutil()

    def _load_psutil(self):
        try:
            import psutil                            # optional
            return psutil
        except Exception:
            return None

    # ---- subsystem registry ---------------------------------------------------
    def register_status(self, name: str, ok: bool) -> None:
        """Record that subsystem `name` is up (True) or down (False).

        Called by the detector for each channel it owns — sdr, gps, lora,
        camera, etc. — so read() can surface a live health map.
        """
        self._statuses[str(name)] = bool(ok)

    def statuses(self) -> dict:
        """A copy of the current per-subsystem up/down map."""
        return dict(self._statuses)

    # ---- individual metrics (each returns None rather than raising) -----------
    def _cpu_temp_c(self) -> float | None:
        # Preferred on a Pi: kernel thermal zone, no dependencies at all.
        try:
            if os.path.exists(PI_THERMAL):
                with open(PI_THERMAL) as fh:
                    return round(int(fh.read().strip()) / 1000.0, 1)
        except Exception:
            pass
        if self._psutil is not None:
            try:
                temps = self._psutil.sensors_temperatures()  # not on all OSes
                for entries in (temps or {}).values():
                    for e in entries:
                        if e.current:
                            return round(float(e.current), 1)
            except Exception:
                pass
        return None

    def _cpu_percent(self) -> float | None:
        if self._psutil is not None:
            try:
                return round(float(self._psutil.cpu_percent(interval=None)), 1)
            except Exception:
                pass
        # Best effort without psutil: load average / core count -> rough %.
        try:
            load1, _, _ = os.getloadavg()            # Unix only
            cores = os.cpu_count() or 1
            return round(min(100.0, load1 / cores * 100.0), 1)
        except (OSError, AttributeError):
            return None

    def _ram_percent(self) -> float | None:
        if self._psutil is not None:
            try:
                return round(float(self._psutil.virtual_memory().percent), 1)
            except Exception:
                pass
        try:                                          # Linux fallback
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            avail = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            if total > 0:
                return round((1.0 - avail / total) * 100.0, 1)
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def _disk_percent(self) -> float | None:
        try:
            usage = shutil.disk_usage(self.disk_path)  # cross-platform stdlib
            if usage.total > 0:
                return round(usage.used / usage.total * 100.0, 1)
        except Exception:
            pass
        return None

    def _uptime_s(self) -> float:
        """Seconds since this monitor started (process/subsystem uptime)."""
        return round(time.time() - self._start, 1)

    # ---- public ---------------------------------------------------------------
    def read(self) -> dict:
        """One health snapshot. Never raises; unknown fields come back as None."""
        return {
            "cpu_temp_c": self._cpu_temp_c(),
            "cpu_percent": self._cpu_percent(),
            "ram_percent": self._ram_percent(),
            "disk_percent": self._disk_percent(),
            "uptime_s": self._uptime_s(),
            "source": self.mode,
            "subsystems": self.statuses(),
        }

    @property
    def mode(self) -> str:
        return "full" if self._psutil is not None else "basic"


def main(argv=None):
    import argparse, json
    p = argparse.ArgumentParser(description="System health monitor")
    p.add_argument("--disk", default=None, help="path whose disk to report")
    args = p.parse_args(argv)
    hm = HealthMonitor(disk_path=args.disk)
    # A couple of example subsystem registrations, as the detector would do.
    hm.register_status("sdr", True)
    hm.register_status("gps", True)
    hm.register_status("lora", False)
    hm.register_status("camera", True)
    print(f"mode: {hm.mode}")
    print(json.dumps(hm.read(), indent=2))


if __name__ == "__main__":
    main()
