"""Event timeline builder — turn the raw detection log into a human story.

`reports/live_detections.csv` is a flat, one-row-per-scan log. Operators don't
want to read hundreds of near-identical rows; they want the *narrative* of each
encounter: when RF first appeared, when Wi-Fi Remote ID decoded the model, when
the camera locked on, when a position was fixed, the peak threat, and when the
target was finally lost.

This module groups consecutive rows into **events** (a fresh event starts after
a detection gap longer than `gap_sec`) and renders each as an ordered list of
milestone lines:

    13:22:05  RF first seen (drone 88%)
    13:22:07  Wi-Fi Remote ID: DJI Mavic 3
    13:22:09  Camera lock (vision 91%)
    13:22:10  Position fixed: 12.9718,77.5947 (340 m)
    13:22:41  peak threat WARNING 75
    13:23:02  target lost

Seamless degradation — identical in spirit to the rest of the runtime:
    * A populated CSV  -> one timeline per encounter.
    * Missing / empty  -> a clear message, never a traceback.

    events = build_events()          # list of event dicts (oldest -> newest)
    print(format_event(events[-1]))  # render the most recent encounter
"""
from __future__ import annotations
import os, sys, csv, math
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ml.common.config import REPORTS_DIR

DEFAULT_CSV = os.path.join(REPORTS_DIR, "live_detections.csv")

# Timestamps in the log are written as "YYYY-mm-dd HH:MM:SS".
_TS_FMT = "%Y-%m-%d %H:%M:%S"

# A visual_conf / acoustic_conf at/above this (percent) counts as a real "lock".
_LOCK_PCT = 50.0


# ---- small parsing helpers ----------------------------------------------------
def _parse_ts(raw: str) -> datetime | None:
    """Parse a log timestamp, tolerating fractional seconds / ISO 'T'."""
    raw = (raw or "").strip().replace("T", " ")
    if not raw:
        return None
    if "." in raw:                       # drop microseconds if present
        raw = raw.split(".", 1)[0]
    try:
        return datetime.strptime(raw, _TS_FMT)
    except ValueError:
        return None


def _f(row: dict, key: str) -> float | None:
    """Best-effort float from a CSV cell; None if blank/unparseable."""
    val = (row.get(key) or "").strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _truthy(row: dict, key: str) -> bool:
    """CSV booleans arrive as text ('True'/'False'/'1'/'')."""
    return (row.get(key) or "").strip().lower() in ("true", "1", "yes")


def _hhmmss(ts: datetime) -> str:
    return ts.strftime("%H:%M:%S")


def _haversine_m(a_lat, a_lon, b_lat, b_lon) -> float | None:
    """Great-circle distance in metres between two lat/lon pairs (or None)."""
    if None in (a_lat, a_lon, b_lat, b_lon):
        return None
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


# ---- CSV -> raw rows ----------------------------------------------------------
def _read_rows(csv_path: str) -> list[dict]:
    """Read + timestamp-sort the detection log (dropping untimestamped rows)."""
    if not os.path.exists(csv_path):
        return []
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = _parse_ts(row.get("timestamp", ""))
            if ts is None:
                continue
            row["_ts"] = ts
            rows.append(row)
    rows.sort(key=lambda r: r["_ts"])
    return rows


# ---- milestone extraction -----------------------------------------------------
def _milestones(group: list[dict]) -> list[str]:
    """Turn one time-contiguous run of rows into ordered milestone strings.

    Each fact is emitted the *first* time it becomes true, so the timeline reads
    as a sequence of discoveries rather than a repeat of every scan.
    """
    lines: list[tuple[datetime, str]] = []
    seen = set()

    def once(key: str, ts: datetime, text: str):
        if key not in seen:
            seen.add(key)
            lines.append((ts, text))

    peak = max(group, key=lambda r: _f(r, "threat_score") or -1.0)

    for row in group:
        ts = row["_ts"]

        # RF first seen — label + drone probability (or RF confidence).
        label = (row.get("rf_label") or "").strip()
        if label:
            prob = _f(row, "drone_prob")
            conf = prob * 100 if (label == "drone" and prob is not None) \
                else _f(row, "rf_confidence")
            pct = f" ({label} {conf:.0f}%)" if conf is not None else f" ({label})"
            once("rf", ts, f"RF first seen{pct}")

        # Wi-Fi Remote ID decode — richest identity we get.
        manuf = (row.get("rid_manuf") or "").strip()
        model = (row.get("rid_model") or "").strip()
        if manuf or model:
            ident = " ".join(p for p in (manuf, model) if p) or "unknown model"
            once("rid", ts, f"Wi-Fi Remote ID: {ident}")
        elif (row.get("wifi_ssids") or "").strip():
            ssid = row["wifi_ssids"].split(";")[0].strip()
            once("wifi", ts, f"Wi-Fi SSID match: {ssid}")

        # Camera lock — vision confidence crossing the lock threshold.
        vis = _f(row, "visual_conf")
        if vis is not None and vis >= _LOCK_PCT:
            once("vision", ts, f"Camera lock (vision {vis:.0f}%)")

        # Acoustic corroboration.
        aco = _f(row, "acoustic_conf")
        if aco is not None and aco >= _LOCK_PCT:
            once("acoustic", ts, f"Acoustic confirm ({aco:.0f}%)")

        # Position fix — prefer a real lat/lon, else note bearing-only tracking.
        dlat, dlon = _f(row, "drone_lat"), _f(row, "drone_lon")
        if dlat is None or dlon is None:
            dlat, dlon = _f(row, "loc_lat"), _f(row, "loc_lon")
        if dlat is not None and dlon is not None:
            rng = _f(row, "range_m")
            if rng is None:                      # derive from observer -> drone
                rng = _haversine_m(_f(row, "loc_lat"), _f(row, "loc_lon"),
                                   dlat, dlon)
            tail = f" ({rng:.0f} m)" if rng is not None else ""
            once("pos", ts, f"Position fixed: {dlat:.4f},{dlon:.4f}{tail}")
        elif _f(row, "azimuth_deg") is not None:
            az = _f(row, "azimuth_deg")
            once("pos", ts, f"Bearing only: azimuth {az:.0f}°")

        # Aircraft-nearby safety flag.
        if _truthy(row, "aircraft_nearby"):
            once("aircraft", ts, "manned aircraft nearby")

    # Peak threat + end-of-encounter, appended after the discovery sequence.
    pscore = _f(peak, "threat_score")
    plevel = (peak.get("threat_level") or "").strip() or "?"
    if pscore is not None:
        lines.append((peak["_ts"], f"peak threat {plevel} {pscore:.0f}"))
    lines.append((group[-1]["_ts"], "target lost"))

    lines.sort(key=lambda t: t[0])
    return [f"{_hhmmss(ts)}  {text}" for ts, text in lines]


# ---- public API ---------------------------------------------------------------
def build_events(csv_path: str = DEFAULT_CSV, gap_sec: float = 30) -> list[dict]:
    """Group the detection log into encounters (oldest -> newest).

    A new event begins whenever more than `gap_sec` elapses between consecutive
    rows. Each event is a dict:

        {"start": datetime, "end": datetime, "peak_level": str,
         "peak_score": float, "milestones": list[str], "rows": int}
    """
    rows = _read_rows(csv_path)
    if not rows:
        return []

    groups: list[list[dict]] = [[rows[0]]]
    for prev, cur in zip(rows, rows[1:]):
        if (cur["_ts"] - prev["_ts"]).total_seconds() > gap_sec:
            groups.append([cur])
        else:
            groups[-1].append(cur)

    events: list[dict] = []
    for g in groups:
        peak = max(g, key=lambda r: _f(r, "threat_score") or -1.0)
        events.append({
            "start": g[0]["_ts"],
            "end": g[-1]["_ts"],
            "peak_level": (peak.get("threat_level") or "").strip() or "?",
            "peak_score": _f(peak, "threat_score") or 0.0,
            "milestones": _milestones(g),
            "rows": len(g),
        })
    return events


def format_event(event: dict) -> str:
    """Render one event dict as a titled, multi-line timeline block."""
    start: datetime = event["start"]
    end: datetime = event["end"]
    dur = int((end - start).total_seconds())
    header = (f"=== Encounter {start.strftime('%Y-%m-%d %H:%M:%S')} "
              f"-> {_hhmmss(end)}  ({dur}s, peak {event['peak_level']} "
              f"{event['peak_score']:.0f}) ===")
    return "\n".join([header, *event["milestones"]])


# ---- self-test ----------------------------------------------------------------
def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Build event timelines from the log")
    p.add_argument("--csv", default=DEFAULT_CSV, help="detection log CSV path")
    p.add_argument("--gap-sec", type=float, default=30,
                   help="seconds of quiet that ends an event (default 30)")
    p.add_argument("--last", type=int, default=1,
                   help="how many most-recent events to print (default 1)")
    args = p.parse_args(argv)

    events = build_events(csv_path=args.csv, gap_sec=args.gap_sec)
    if not events:
        if not os.path.exists(args.csv):
            print(f"[timeline] no log found at {args.csv}; nothing to show")
        else:
            print(f"[timeline] {args.csv} has no timestamped detections yet")
        return

    n = max(1, args.last)
    print(f"{len(events)} event(s) in log; showing last {min(n, len(events))}:\n")
    for ev in events[-n:]:
        print(format_event(ev))
        print()


if __name__ == "__main__":
    main()
