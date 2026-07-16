"""CampusShield operations dashboard — view the whole system + LAND control.

A single-file, **standard-library-only** web dashboard (no Flask/FastAPI needed,
so it runs anywhere the rest of the runtime does, with the same graceful mock
fallback). It:

  * reads the real detection stream from ``reports/live_detections.csv`` (written
    by ``live_detector.py``) and renders a live feed, threat gauge, localization
    read-out, and a sensor grid inferred from the actual data;
  * exposes one operator control — **INITIATE RF LANDING** — which commands YOUR
    OWN allow-listed drone to LAND via the existing ``pluto_control.PlutoDefence``
    (own-drone, land-only, no jamming/takeover — see that module's legal note).

Presentation note (why the SSID field is hidden):
  The landing path talks to a WiFi drone (the Pluto) over its own control link,
  identified by an SSID / allow-list token. For a clean "RF counter-drone" demo
  that token is NOT shown on the main console — it lives in a hidden config panel
  revealed only by a secret gesture (press the backtick ` key, or click the dim
  dot in the bottom-right). Pre-fill it once from the environment and you never
  have to open the panel during a demo:

      $env:PLUTO_SSID = "PLUTO"        # your drone's SSID / allow-list token
      $env:PLUTO_HOST = "192.168.4.1"  # Pluto MSP host (default)
      python -m ml.runtime.dashboard

Run:
      python -m ml.runtime.dashboard                 # http://127.0.0.1:8080
      python -m ml.runtime.dashboard --port 8080 --host 0.0.0.0
      python -m ml.runtime.dashboard --mock          # force land path to mock

Pair it with the detector in another terminal so the feed populates:
      python -m ml.runtime.live_detector --mock --simulate-ssid DJI-Mavic-1A2B
"""
from __future__ import annotations
import os, sys, csv, json, time, argparse, threading, webbrowser, platform, shutil, ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CSV_PATH = os.path.join(REPO_ROOT, "reports", "live_detections.csv")

# ---- shared runtime config (mutable via the hidden panel / env) --------------
CONFIG = {
    # The drone's SSID / allow-list token — hidden from the main UI on purpose.
    "ssid": os.environ.get("PLUTO_SSID", "PLUTO"),
    "host": os.environ.get("PLUTO_HOST", "192.168.4.1"),
    "port": int(os.environ.get("PLUTO_PORT", "23")),
    "force_mock": False,
}
_LAST_LAND: dict = {"action": "idle", "at": None, "detail": "no landing commanded yet"}
_LOCK = threading.Lock()


# ---- detection feed ----------------------------------------------------------
def _read_all() -> list[dict]:
    """All detection rows (oldest first), robust to a concurrently-written CSV."""
    if not os.path.exists(CSV_PATH):
        return []
    try:
        with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _tail_detections(limit: int = 25) -> list[dict]:
    """Return the most recent detection rows (newest first)."""
    return list(reversed(_read_all()[-limit:]))


def _stream_status() -> dict:
    """Is the detector actually writing? Honest heartbeat from the CSV's mtime —
    no fake 'online' lights, just whether fresh rows are landing."""
    try:
        age = time.time() - os.path.getmtime(CSV_PATH)
    except OSError:
        return {"live": False, "age_s": None, "label": "no stream"}
    live = age < 15
    return {"live": live, "age_s": int(age),
            "label": "live" if live else f"stale {int(age)}s"}


def _analytics(rows: "list[dict] | None" = None) -> dict:
    """Today's tally, computed from the real detection log (nothing invented).
    Pass ``rows`` to reuse an already-loaded CSV (avoids a second read per poll —
    matters on the Pi where the log grows)."""
    if rows is None:
        rows = _read_all()
    today = time.strftime("%Y-%m-%d")
    todays = [r for r in rows if (r.get("timestamp", "") or "").startswith(today)]
    scores = [_f(r, "threat_score") for r in todays if r.get("threat_score")]
    alerts = sum(1 for r in todays
                 if (r.get("threat_level", "") or "") in ("WARNING", "CRITICAL"))
    return {
        "today": len(todays),
        "avg_score": round(sum(scores) / len(scores)) if scores else 0,
        "peak_score": round(max(scores)) if scores else 0,
        "alerts": alerts,
    }


def _f(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, "") or default)
    except (TypeError, ValueError):
        return default


# ---- system health (real host metrics, standard-library only) ----------------
# All best-effort and cross-platform: anything we can't read on this OS comes back
# as None and renders "—" in the UI rather than a fabricated number. On the Pi
# (Linux/ARM) all six are real; on a Windows dev box temp is usually unavailable.
_PROC_START = time.time()
_CPU_PREV: dict = {"idle": None, "total": None}   # for CPU% between successive polls


def _cpu_percent():
    """CPU utilization %, computed from the delta since the last call (non-blocking).
    Returns None on the very first sample (no delta yet) or if unreadable."""
    sysname = platform.system()
    try:
        if sysname == "Linux":
            with open("/proc/stat") as f:
                vals = [float(x) for x in f.readline().split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)   # idle + iowait
            total = sum(vals)
        elif sysname == "Windows":
            idle_ft, kern_ft, user_ft = (ctypes.c_ulonglong() for _ in range(3))
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle_ft),
                                                  ctypes.byref(kern_ft),
                                                  ctypes.byref(user_ft))
            idle = float(idle_ft.value)
            total = float(kern_ft.value + user_ft.value)   # kernel time includes idle
        else:
            return min(100.0, os.getloadavg()[0] / (os.cpu_count() or 1) * 100)
    except Exception:
        return None
    prev_idle, prev_total = _CPU_PREV["idle"], _CPU_PREV["total"]
    _CPU_PREV["idle"], _CPU_PREV["total"] = idle, total
    if prev_idle is None or prev_total is None:
        return None
    dt = total - prev_total
    if dt <= 0:
        return None
    return max(0.0, min(100.0, (1.0 - (idle - prev_idle) / dt) * 100.0))


def _mem_percent():
    """(used %, total GB) of physical RAM, or (None, None)."""
    sysname = platform.system()
    try:
        if sysname == "Linux":
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k] = float(v.strip().split()[0])   # kB
            total = info.get("MemTotal", 0.0)
            avail = info.get("MemAvailable", info.get("MemFree", 0.0))
            if total <= 0:
                return None, None
            return (1.0 - avail / total) * 100.0, total / 1048576.0
        if sysname == "Windows":
            class _MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _MEM(); m.dwLength = ctypes.sizeof(_MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return float(m.dwMemoryLoad), m.ullTotalPhys / 1e9
    except Exception:
        return None, None
    return None, None


def _cpu_temp():
    """CPU temperature in °C (Raspberry Pi / Linux thermal zone), or None.
    Prefers a zone whose ``type`` names the CPU (Pi 5 = 'cpu-thermal'); falls back
    to thermal_zone0. Reads are in milli-°C."""
    base = "/sys/class/thermal"
    try:
        zones = [z for z in os.listdir(base) if z.startswith("thermal_zone")]
    except OSError:
        return None
    # Try to pick the CPU zone by its declared type, else just use zone0.
    ordered = []
    for z in sorted(zones):
        try:
            with open(os.path.join(base, z, "type")) as f:
                ztype = f.read().strip().lower()
        except OSError:
            ztype = ""
        (ordered.insert(0, z) if ("cpu" in ztype or "soc" in ztype)
         else ordered.append(z))
    for z in ordered or ["thermal_zone0"]:
        try:
            with open(os.path.join(base, z, "temp")) as f:
                milli = int(f.read().strip())
            if milli > 0:
                return round(milli / 1000.0, 1)
        except (OSError, ValueError):
            continue
    return None


def _disk_usage():
    """(used %, total GB, free GB) for the repo's volume, or (None, None, None)."""
    try:
        du = shutil.disk_usage(REPO_ROOT)
        return du.used / du.total * 100.0, du.total / 1e9, du.free / 1e9
    except Exception:
        return None, None, None


def _uptime_seconds():
    """System uptime in seconds, falling back to this process's uptime."""
    sysname = platform.system()
    try:
        if sysname == "Linux":
            with open("/proc/uptime") as f:
                return float(f.read().split()[0])
        if sysname == "Windows":
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        pass
    return time.time() - _PROC_START


def _fmt_uptime(s) -> str:
    if s is None:
        return "—"
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _system_health() -> dict:
    """Live host metrics for the System Health panel — all real, all stdlib."""
    cpu = _cpu_percent()
    mem_pct, mem_total = _mem_percent()
    disk_pct, disk_total, disk_free = _disk_usage()
    up = _uptime_seconds()
    r1 = lambda v: None if v is None else round(v, 1)
    return {
        "cpu": r1(cpu),
        "mem_pct": r1(mem_pct),
        "mem_total_gb": r1(mem_total),
        "temp_c": _cpu_temp(),
        "disk_pct": r1(disk_pct),
        "disk_total_gb": r1(disk_total),
        "disk_free_gb": r1(disk_free),
        "uptime_s": None if up is None else int(up),
        "uptime": _fmt_uptime(up),
        "platform": f"{platform.system()} {platform.machine()}".strip(),
        "cores": os.cpu_count(),
    }


def _system_snapshot() -> dict:
    """Whole-system view derived honestly from the real detection stream: current
    threat, localization, and which sensors have actually contributed data."""
    all_rows = _read_all()                       # read the CSV once per poll
    rows = list(reversed(all_rows[-40:]))        # newest-first tail for the feed
    latest = rows[0] if rows else {}

    # Which vectors are live — inferred from populated fields in recent rows.
    def any_field(pred) -> bool:
        return any(pred(r) for r in rows[:15])

    sensors = [
        {"key": "rf",       "name": "RF Classifier (A1)",
         "active": any_field(lambda r: _f(r, "drone_prob") > 0 or r.get("rf_label")),
         "detail": (latest.get("rf_label", "-") or "-").upper()},
        {"key": "wifi",     "name": "Wi-Fi / Remote ID",
         "active": any_field(lambda r: bool(r.get("wifi_ssids"))),
         "detail": (latest.get("rid_model") or latest.get("wifi_ssids") or "-")},
        {"key": "vision",   "name": "Vision (YOLO)",
         "active": any_field(lambda r: _f(r, "visual_conf") > 0),
         "detail": f"{_f(latest,'visual_conf'):.0f}%"},
        {"key": "acoustic", "name": "Acoustic (A5)",
         "active": any_field(lambda r: _f(r, "acoustic_conf") > 0),
         "detail": f"{_f(latest,'acoustic_conf'):.0f}%"},
        {"key": "control",  "name": "Control Link (sub-GHz)",
         "active": any_field(lambda r: _f(r, "control_conf") > 0),
         "detail": (f"{_f(latest,'control_band_mhz'):.0f} MHz"
                    if _f(latest, "control_band_mhz") else "-")},
        {"key": "localize", "name": "Localization",
         "active": any_field(lambda r: r.get("loc_lat") or r.get("azimuth_deg")),
         "detail": (f"az {_f(latest,'azimuth_deg'):.0f}deg"
                    if latest.get("azimuth_deg") else "-")},
    ]

    fix = None
    if latest:
        fix = {
            "lat": latest.get("loc_lat") or latest.get("drone_lat") or "",
            "lon": latest.get("loc_lon") or latest.get("drone_lon") or "",
            "az": latest.get("azimuth_deg", ""),
            "el": latest.get("elevation_deg", ""),
            "range_m": latest.get("range_m", ""),
        }

    with _LOCK:
        last_land = dict(_LAST_LAND)

    return {
        "threat": {
            "score": _f(latest, "threat_score"),
            "level": latest.get("threat_level", "SAFE") or "SAFE",
            "modifiers": latest.get("modifiers", ""),
            "source": latest.get("source", "-"),
            "time": latest.get("timestamp", "-"),
            "fingerprint": latest.get("fingerprint", "")
                           or latest.get("rid_model", ""),
        },
        "fix": fix,
        "sensors": sensors,
        "feed": rows[:20],
        "last_land": last_land,
        "stream": _stream_status(),
        "analytics": _analytics(all_rows),
        # NB: ssid intentionally NOT exposed here — it stays in the hidden panel.
        "armed": bool(CONFIG["ssid"].strip()),
        "target_configured": bool(CONFIG["ssid"].strip()),
    }


# ---- landing control ---------------------------------------------------------
def _drone_type(token: str) -> str:
    """Pick the control stack from an explicit override or the SSID shape."""
    forced = os.environ.get("DRONE_TYPE", "").strip().lower()
    if forced in ("tello", "pluto"):
        return forced
    t = token.upper()
    if t.startswith("TELLO") or t.startswith("RMTT"):
        return "tello"
    return "pluto"


def _command_land(method: str = "land") -> dict:
    """Command the operator's OWN allow-listed drone down. Routes to the right
    control stack (Tello UDP SDK vs Pluto MSP) by SSID; own-drone + land-only.

    ``method="emergency"`` cuts the Tello's motors instantly instead of a
    controlled descent (Tello only; Pluto falls back to its normal land)."""
    global _LAST_LAND
    method = "emergency" if str(method).lower() == "emergency" else "land"
    token = CONFIG["ssid"].strip() or "PLUTO"
    drone = _drone_type(token)
    try:
        if drone == "tello":
            from ml.runtime.tello_control import TelloDefence
            td = TelloDefence(authorized=[token], enabled=True,
                              force_mock=CONFIG["force_mock"])
            verdict = {"wifi_hits": [{"ssid": token, "model": token}]}
            result = td.engage(verdict, method=method)
            td.close()
        else:
            os.environ["PLUTO_HOST"] = CONFIG["host"]
            os.environ["PLUTO_PORT"] = str(CONFIG["port"])
            from ml.runtime.pluto_control import PlutoDefence
            pd = PlutoDefence(host=CONFIG["host"], port=CONFIG["port"],
                              authorized=[token], enabled=True,
                              force_mock=CONFIG["force_mock"])
            # Synthetic own-drone verdict so the allow-list gate authorizes the LAND.
            verdict = {"wifi_hits": [{"ssid": token, "serial": token, "model": token}]}
            result = pd.engage(verdict)
            pd.close()
    except Exception as e:
        result = {"action": "error", "reason": f"{type(e).__name__}: {e}"}

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    action = result.get("action", "error")
    if action in ("land", "emergency"):
        verb = "EMERGENCY (motor cutoff)" if action == "emergency" else "LAND"
        detail = (f"{verb} commanded to '{result.get('target', token)}' "
                  f"via {result.get('mode', '?')}"
                  + ("" if result.get("sent") else " (mock — no drone reachable)"))
    elif action == "none":
        detail = result.get("reason", "no action")
    else:
        detail = result.get("reason", "landing failed")
    with _LOCK:
        _LAST_LAND = {"action": action, "at": stamp, "detail": detail,
                      "raw": result}
        snapshot = dict(_LAST_LAND)
    return snapshot


# ---- HTTP handler ------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the console clean
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/api/status"):
            self._json(_system_snapshot())
        elif self.path.startswith("/api/system"):
            self._json(_system_health())
        elif self.path.startswith("/api/config"):
            # Return only non-secret host/port; SSID stays server-side by design.
            self._json({"host": CONFIG["host"], "port": CONFIG["port"],
                        "ssid_set": bool(CONFIG["ssid"].strip()),
                        "force_mock": CONFIG["force_mock"]})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            data = {}
        if self.path.startswith("/api/land"):
            method = "emergency" if data.get("emergency") else "land"
            self._json(_command_land(method))
        elif self.path.startswith("/api/config"):
            if "ssid" in data:
                CONFIG["ssid"] = str(data["ssid"])
            if data.get("host"):
                CONFIG["host"] = str(data["host"])
            if data.get("port"):
                try:
                    CONFIG["port"] = int(data["port"])
                except (TypeError, ValueError):
                    pass
            if "force_mock" in data:
                CONFIG["force_mock"] = bool(data["force_mock"])
            self._json({"ok": True, "ssid_set": bool(CONFIG["ssid"].strip())})
        else:
            self._send(404, b"not found", "text/plain")


# ---- front-end (self-contained, no external assets) --------------------------
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>CampusShield — Operations Console</title>
<style>
  :root{
    --bg:#0a0e14; --panel:#111823; --panel2:#0d1420; --line:#1e2a3a;
    --txt:#c7d3e0; --dim:#5f7186; --accent:#22d3ee; --ok:#34d399;
    --warn:#fbbf24; --crit:#f43f5e; --grid:#16202e;
  }
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 700px at 70% -10%,#12202e 0,var(--bg) 60%);
    color:var(--txt);font:14px/1.4 'Segoe UI',system-ui,sans-serif;min-height:100vh}
  header{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--line);
    background:linear-gradient(180deg,rgba(34,211,238,.06),transparent)}
  header .logo{width:34px;height:34px;border-radius:7px;border:1px solid var(--accent);
    display:grid;place-items:center;color:var(--accent);font-weight:700;cursor:pointer;user-select:none}
  header h1{font-size:16px;letter-spacing:.14em;margin:0;font-weight:600}
  header .sub{color:var(--dim);font-size:11px;letter-spacing:.18em}
  header .clock{margin-left:auto;color:var(--dim);font-variant-numeric:tabular-nums}
  .wrap{display:grid;grid-template-columns:340px 1fr;gap:16px;padding:16px 22px;max-width:1400px;margin:0 auto}
  .col{display:flex;flex-direction:column;gap:16px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;
    box-shadow:0 10px 30px rgba(0,0,0,.25)}
  .card h2{margin:0 0 12px;font-size:11px;letter-spacing:.2em;color:var(--dim);text-transform:uppercase}

  /* threat gauge */
  .gauge{display:flex;align-items:center;gap:16px}
  .ring{--pct:0;width:120px;height:120px;border-radius:50%;flex:none;
    background:conic-gradient(var(--gc) calc(var(--pct)*1%),var(--grid) 0);
    display:grid;place-items:center;position:relative}
  .ring::after{content:"";position:absolute;inset:11px;border-radius:50%;background:var(--panel2)}
  .ring .val{position:relative;text-align:center}
  .ring .val b{font-size:30px;font-variant-numeric:tabular-nums}
  .ring .val span{display:block;font-size:10px;color:var(--dim);letter-spacing:.1em}
  .lvl{font-size:22px;font-weight:700;letter-spacing:.06em}
  .lvl.SAFE{color:var(--ok)} .lvl.WATCH{color:var(--accent)}
  .lvl.WARNING{color:var(--warn)} .lvl.CRITICAL{color:var(--crit)}
  .meta{color:var(--dim);font-size:12px;margin-top:6px}
  .meta b{color:var(--txt);font-weight:600}

  /* sensor grid */
  .sensors{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .sensor{border:1px solid var(--line);border-radius:9px;padding:9px 10px;background:var(--panel2)}
  .sensor .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:7px;
    background:var(--dim);box-shadow:0 0 0 0 transparent}
  .sensor.on .dot{background:var(--ok);box-shadow:0 0 10px var(--ok)}
  .sensor .n{font-size:12px} .sensor .d{color:var(--dim);font-size:11px;margin-top:3px}

  /* system health strip */
  .health{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
  .hm{border:1px solid var(--line);border-radius:9px;padding:11px 8px;background:var(--panel2);text-align:center}
  .hm .k{display:block;font-size:9px;letter-spacing:.14em;color:var(--dim);text-transform:uppercase}
  .hm b{display:block;font-size:19px;margin-top:5px;font-variant-numeric:tabular-nums;font-weight:600}
  .hm b.sm{font-size:13px;font-weight:500}
  .hm b.ok{color:var(--ok)} .hm b.warn{color:var(--warn)} .hm b.crit{color:var(--crit)}
  @media(max-width:760px){.health{grid-template-columns:repeat(3,1fr)}}

  /* small status pill in a card header (e.g. detector stream heartbeat) */
  .st{float:right;font-size:9px;letter-spacing:.08em;color:var(--dim);text-transform:none;font-weight:500}
  .st .d{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--dim);
    margin-right:5px;vertical-align:middle}
  .st.on .d{background:var(--ok);box-shadow:0 0 8px var(--ok)}
  .st.off .d{background:var(--crit)}

  /* land control */
  .landcard{text-align:center}
  .landbtn{width:100%;padding:20px;border-radius:12px;border:1px solid var(--crit);
    background:linear-gradient(180deg,rgba(244,63,94,.16),rgba(244,63,94,.05));
    color:#fff;font-size:16px;font-weight:700;letter-spacing:.16em;cursor:pointer;
    transition:.15s;text-transform:uppercase}
  .landbtn:hover{background:linear-gradient(180deg,rgba(244,63,94,.32),rgba(244,63,94,.12));
    box-shadow:0 0 26px rgba(244,63,94,.35)}
  .landbtn.confirm{border-color:var(--warn);animation:pulse 1s infinite;
    background:linear-gradient(180deg,rgba(251,191,36,.22),rgba(251,191,36,.06));color:#fff}
  .landbtn:disabled{opacity:.5;cursor:progress}
  @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(251,191,36,.5)}50%{box-shadow:0 0 26px 4px rgba(251,191,36,.35)}}
  .landnote{color:var(--dim);font-size:11px;margin-top:10px;min-height:16px}
  .landstat{margin-top:12px;padding:10px;border-radius:9px;background:var(--panel2);
    border:1px solid var(--line);font-size:12px;text-align:left;min-height:20px}
  .landstat.ok{border-color:var(--ok)} .landstat.err{border-color:var(--crit)}

  /* feed */
  table{width:100%;border-collapse:collapse;font-size:12px}
  th{text-align:left;color:var(--dim);font-weight:500;font-size:10px;letter-spacing:.12em;
    text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--line)}
  td{padding:7px 8px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
  tr:hover td{background:rgba(34,211,238,.04)}
  .pill{padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.05em}
  .pill.SAFE{background:rgba(52,211,153,.15);color:var(--ok)}
  .pill.WATCH{background:rgba(34,211,238,.15);color:var(--accent)}
  .pill.WARNING{background:rgba(251,191,36,.15);color:var(--warn)}
  .pill.CRITICAL{background:rgba(244,63,94,.15);color:var(--crit)}
  .empty{color:var(--dim);text-align:center;padding:26px}

  /* hidden config panel */
  #cog{position:fixed;right:12px;bottom:10px;width:10px;height:10px;border-radius:50%;
    background:#1b2634;opacity:.35;cursor:pointer}
  #panel{position:fixed;inset:0;background:rgba(5,8,12,.72);display:none;place-items:center;z-index:50}
  #panel.show{display:grid}
  #panel .box{width:380px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}
  #panel h3{margin:0 0 4px;font-size:13px;letter-spacing:.1em}
  #panel p{color:var(--dim);font-size:11px;margin:0 0 14px}
  #panel label{display:block;font-size:11px;color:var(--dim);margin:10px 0 4px;letter-spacing:.08em}
  #panel input{width:100%;padding:9px 10px;border-radius:8px;border:1px solid var(--line);
    background:var(--panel2);color:var(--txt);font:13px monospace}
  #panel .row{display:flex;gap:10px} #panel .row>div{flex:1}
  #panel .actions{display:flex;gap:10px;margin-top:16px}
  #panel button{flex:1;padding:10px;border-radius:8px;border:1px solid var(--line);
    background:var(--panel2);color:var(--txt);cursor:pointer;font-weight:600}
  #panel button.save{border-color:var(--accent);color:var(--accent)}
</style>
</head>
<body>
<header>
  <div class="logo" id="logo" title="">CS</div>
  <div>
    <h1>CAMPUSSHIELD</h1>
    <div class="sub">RF COUNTER-DRONE OPERATIONS CONSOLE</div>
  </div>
  <div class="clock" id="clock">--:--:--</div>
</header>

<div class="wrap">
  <div class="col">
    <div class="card">
      <h2>Threat Assessment</h2>
      <div class="gauge">
        <div class="ring" id="ring" style="--pct:0;--gc:var(--ok)">
          <div class="val"><b id="score">0</b><span>/ 100</span></div>
        </div>
        <div>
          <div class="lvl SAFE" id="level">SAFE</div>
          <div class="meta">source <b id="src">-</b></div>
          <div class="meta">vectors <b id="agree">—</b></div>
          <div class="meta">id <b id="fp">-</b></div>
          <div class="meta" id="ts">-</div>
        </div>
      </div>
      <div class="meta" id="mods" style="margin-top:10px"></div>
    </div>

    <div class="card landcard">
      <h2>RF Neutralization</h2>
      <button class="landbtn" id="land">Initiate RF Landing</button>
      <div class="landnote" id="landnote">One tap arms · tap again within 4s to execute</div>
      <div class="landstat" id="landstat">Standing by.</div>
    </div>

    <div class="card">
      <h2>Target Localization</h2>
      <div class="meta">lat/lon <b id="loc">— , —</b></div>
      <div class="meta">bearing <b id="brg">—</b> · elev <b id="elv">—</b></div>
      <div class="meta">range <b id="rng">—</b></div>
    </div>
  </div>

  <div class="col">
    <div class="card">
      <h2>System Health</h2>
      <div class="health" id="health">
        <div class="hm"><span class="k">CPU</span><b id="h-cpu">—</b></div>
        <div class="hm"><span class="k">RAM</span><b id="h-ram">—</b></div>
        <div class="hm"><span class="k">Temp</span><b id="h-temp">—</b></div>
        <div class="hm"><span class="k">Disk</span><b id="h-disk">—</b></div>
        <div class="hm"><span class="k">Uptime</span><b id="h-up" class="sm">—</b></div>
        <div class="hm"><span class="k">Platform</span><b id="h-plat" class="sm">—</b></div>
      </div>
    </div>
    <div class="card">
      <h2>Sensor Fusion Grid</h2>
      <div class="sensors" id="sensors"></div>
    </div>
    <div class="card">
      <h2>Today
        <span class="st" id="stream"><span class="d"></span><span id="streamlbl">—</span></span>
      </h2>
      <div class="health" style="grid-template-columns:repeat(4,1fr)">
        <div class="hm"><span class="k">Detections</span><b id="a-today">0</b></div>
        <div class="hm"><span class="k">Alerts</span><b id="a-alerts">0</b></div>
        <div class="hm"><span class="k">Avg Score</span><b id="a-avg">0</b></div>
        <div class="hm"><span class="k">Peak Score</span><b id="a-peak">0</b></div>
      </div>
    </div>
    <div class="card">
      <h2>Live Detection Feed</h2>
      <table>
        <thead><tr><th>Time</th><th>Src</th><th>Class</th><th>Score</th><th>Level</th><th>ID / SSID</th></tr></thead>
        <tbody id="feed"><tr><td class="empty" colspan="6">Waiting for detector stream…</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<div id="cog" title=""></div>
<div id="panel">
  <div class="box">
    <h3>Link Configuration</h3>
    <p>Own-drone control link. Land-only, allow-list gated — never jams or takes over third-party aircraft.</p>
    <label>Drone SSID / allow-list token</label>
    <input id="cf-ssid" placeholder="PLUTO" autocomplete="off"/>
    <div class="row">
      <div><label>Control host</label><input id="cf-host" placeholder="192.168.4.1"/></div>
      <div><label>Port</label><input id="cf-port" placeholder="23"/></div>
    </div>
    <div class="actions">
      <button id="cf-cancel">Close</button>
      <button class="save" id="cf-save">Save</button>
    </div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const GC={SAFE:'var(--ok)',WATCH:'var(--accent)',WARNING:'var(--warn)',CRITICAL:'var(--crit)'};

function tick(){const d=new Date();$('clock').textContent=d.toLocaleTimeString();}
setInterval(tick,1000);tick();

async function refresh(){
  let s; try{s=await (await fetch('/api/status')).json();}catch(e){return;}
  const t=s.threat;
  $('score').textContent=Math.round(t.score);
  $('ring').style.setProperty('--pct',Math.max(0,Math.min(100,t.score)));
  $('ring').style.setProperty('--gc',GC[t.level]||'var(--ok)');
  const lv=$('level');lv.textContent=t.level;lv.className='lvl '+t.level;
  $('src').textContent=t.source||'-';
  $('fp').textContent=t.fingerprint||'-';
  $('ts').textContent=t.time||'-';
  $('mods').textContent=t.modifiers||'';

  const f=s.fix||{};
  $('loc').textContent=((f.lat||'—')+' , '+(f.lon||'—'));
  $('brg').textContent=f.az?(Math.round(f.az)+'°'):'—';
  $('elv').textContent=f.el?(Math.round(f.el)+'°'):'—';
  $('rng').textContent=f.range_m?(f.range_m+' m'):'—';

  const sensors=s.sensors||[];
  $('sensors').innerHTML=sensors.map(x=>`
    <div class="sensor ${x.active?'on':''}">
      <div class="n"><span class="dot"></span>${x.name}</div>
      <div class="d">${x.detail||'—'}</div>
    </div>`).join('');

  // vectors: honest count of how many sensors are actually contributing
  const act=sensors.filter(x=>x.active);
  $('agree').textContent = sensors.length
    ? act.length+'/'+sensors.length+(act.length?(' · '+act.map(x=>x.name.split(' ')[0]).join(', ')):'')
    : '—';

  // detector heartbeat + today's tally
  const sm=s.stream||{}, st=$('stream');
  st.className='st '+(sm.live?'on':'off');$('streamlbl').textContent=sm.label||'—';
  const an=s.analytics||{};
  $('a-today').textContent=an.today||0;
  $('a-alerts').textContent=an.alerts||0;
  $('a-avg').textContent=an.avg_score||0;
  $('a-peak').textContent=an.peak_score||0;
  $('a-alerts').className=an.alerts>0?'warn':'';
  $('a-avg').className=an.avg_score>=60?'crit':(an.avg_score>=35?'warn':'');
  $('a-peak').className=an.peak_score>=60?'crit':(an.peak_score>=35?'warn':'');

  const feed=s.feed||[];
  $('feed').innerHTML = feed.length? feed.map(r=>`
    <tr><td>${(r.timestamp||'').slice(11)}</td><td>${r.source||''}</td>
    <td>${(r.rf_label||'').toUpperCase()}</td>
    <td>${Math.round(parseFloat(r.threat_score||0))}</td>
    <td><span class="pill ${r.threat_level}">${r.threat_level||''}</span></td>
    <td>${r.rid_model||r.fingerprint||r.wifi_ssids||'—'}</td></tr>`).join('')
    : '<tr><td class="empty" colspan="6">Waiting for detector stream…</td></tr>';

  if(s.last_land && s.last_land.action!=='idle' && !landBusy){
    const ok=s.last_land.action==='land';
    setLandStat(s.last_land.detail, ok?'ok':(s.last_land.action==='error'?'err':''));
  }
}
setInterval(refresh,1200);refresh();

/* ---- system health strip (real host metrics from /api/system) ---- */
function hcls(v,warn,crit){return v==null?'':(v>=crit?'crit':(v>=warn?'warn':'ok'));}
async function refreshHealth(){
  let h; try{h=await (await fetch('/api/system')).json();}catch(e){return;}
  const set=(id,txt,cls,keepSm)=>{const el=$(id);el.textContent=txt;
    el.className=(keepSm?'sm ':'')+(cls||'');};
  const pct=v=>v==null?'—':Math.round(v)+'%';
  set('h-cpu', pct(h.cpu),  hcls(h.cpu,60,85));
  set('h-ram', pct(h.mem_pct), hcls(h.mem_pct,75,90));
  set('h-temp',h.temp_c==null?'—':Math.round(h.temp_c)+'°C', hcls(h.temp_c,65,78));
  set('h-disk',pct(h.disk_pct), hcls(h.disk_pct,80,92));
  set('h-up',  h.uptime||'—', '', true);
  set('h-plat',h.platform||'—','', true);
  $('h-ram').title = h.mem_total_gb?('total '+h.mem_total_gb+' GB'):'';
  $('h-disk').title = (h.disk_free_gb!=null)?(h.disk_free_gb+' GB free of '+h.disk_total_gb+' GB'):'';
  $('h-cpu').title = h.cores?(h.cores+' cores'):'';
}
setInterval(refreshHealth,3000);refreshHealth();

/* ---- land button: tap to arm, tap again to execute ---- */
let armed=false,armTimer=null,landBusy=false;
function setLandStat(msg,cls){const el=$('landstat');el.textContent=msg;el.className='landstat '+(cls||'');}
function disarm(){armed=false;clearTimeout(armTimer);const b=$('land');
  b.classList.remove('confirm');b.textContent='Initiate RF Landing';
  $('landnote').textContent='One tap arms · tap again within 4s to execute';}
$('land').onclick=async()=>{
  if(!armed){armed=true;const b=$('land');b.classList.add('confirm');
    b.textContent='⚠ Confirm — Execute Landing';
    $('landnote').textContent='Tap again to send LAND to the target';
    armTimer=setTimeout(disarm,4000);return;}
  clearTimeout(armTimer);armed=false;landBusy=true;
  const b=$('land');b.disabled=true;b.classList.remove('confirm');b.textContent='Sending LAND…';
  setLandStat('Transmitting landing command…','');
  try{const r=await (await fetch('/api/land',{method:'POST'})).json();
    const ok=r.action==='land';
    setLandStat(r.detail||'done',ok?'ok':(r.action==='error'?'err':''));
  }catch(e){setLandStat('request failed: '+e,'err');}
  b.disabled=false;b.textContent='Initiate RF Landing';
  $('landnote').textContent='One tap arms · tap again within 4s to execute';
  setTimeout(()=>{landBusy=false;},1500);
};

/* ---- hidden config panel: backtick key, corner dot, or triple-click logo ---- */
const panel=$('panel');
async function openPanel(){
  try{const c=await (await fetch('/api/config')).json();
    $('cf-host').value=c.host||'';$('cf-port').value=c.port||'';
    $('cf-ssid').value='';$('cf-ssid').placeholder=c.ssid_set?'•••••• (set — leave blank to keep)':'PLUTO';
  }catch(e){}
  panel.classList.add('show');$('cf-ssid').focus();
}
function closePanel(){panel.classList.remove('show');}
$('cog').onclick=openPanel;
let clicks=0,ct=null;$('logo').onclick=()=>{clicks++;clearTimeout(ct);
  if(clicks>=3){clicks=0;openPanel();}ct=setTimeout(()=>clicks=0,600);};
document.addEventListener('keydown',e=>{
  if(e.key==='`'){e.preventDefault();panel.classList.contains('show')?closePanel():openPanel();}
  if(e.key==='Escape')closePanel();});
$('cf-cancel').onclick=closePanel;
$('cf-save').onclick=async()=>{
  const body={host:$('cf-host').value,port:$('cf-port').value};
  const ss=$('cf-ssid').value.trim(); if(ss)body.ssid=ss;
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)});
  closePanel();
};
</script>
</body>
</html>
"""


def main(argv=None):
    p = argparse.ArgumentParser(description="CampusShield operations dashboard")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (use 0.0.0.0 to reach from other devices)")
    p.add_argument("--port", type=int, default=8080, help="HTTP port (default 8080)")
    p.add_argument("--mock", action="store_true",
                   help="force the LAND path to mock (never touch a real link)")
    p.add_argument("--no-open", action="store_true",
                   help="do not auto-open the browser")
    args = p.parse_args(argv)

    CONFIG["force_mock"] = bool(args.mock)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}"
    print("=== CampusShield operations dashboard ===")
    print(f"serving : {url}")
    print(f"feed    : {CSV_PATH}")
    print(f"target  : SSID token {'set' if CONFIG['ssid'].strip() else 'UNSET'} "
          f"-> {CONFIG['host']}:{CONFIG['port']}  "
          f"(land path: {'mock' if CONFIG['force_mock'] else 'live-if-reachable'})")
    print("hidden config panel: press ` (backtick), triple-click the logo, "
          "or click the dim dot bottom-right")
    print("Ctrl+C to stop.")
    if not args.no_open:
        try:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        srv.shutdown()


if __name__ == "__main__":
    main()
