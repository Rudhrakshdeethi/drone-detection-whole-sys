"""A7 — threat scoring engine. Fuses every sensor's confidence into a single
0-100 score with a SAFE/WATCH/WARNING/CRITICAL level.

Weighted ensemble + rule modifiers (lingering target, unknown model). Pure
Python, no model file — call it from the dashboard/fusion layer.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


# sensor weights must sum to 1.0
WEIGHTS = {
    "rf": 0.35,
    "visual": 0.25,
    "acoustic": 0.15,
    "fingerprint": 0.15,
    "bluetooth": 0.10,
}

LEVELS = [
    (30, "SAFE", "🟢"),
    (60, "WATCH", "🟡"),
    (80, "WARNING", "🟠"),
    (101, "CRITICAL", "🔴"),
]


@dataclass
class ThreatInputs:
    rf_conf: float = 0.0          # all confidences in [0, 1]
    visual_conf: float = 0.0
    acoustic_conf: float = 0.0
    fingerprint_conf: float = 0.0
    bluetooth_conf: float = 0.0
    duration_sec: float = 0.0
    is_unknown: bool = False
    remote_id_decoded: bool = False   # a drone broadcast its DJI/FAA Remote ID
    aircraft_match: bool = False      # ADS-B says a manned aircraft is at that spot


def compute_threat_score(inp: ThreatInputs | dict) -> dict:
    if isinstance(inp, dict):
        inp = ThreatInputs(**inp)

    base = (inp.rf_conf * WEIGHTS["rf"]
            + inp.visual_conf * WEIGHTS["visual"]
            + inp.acoustic_conf * WEIGHTS["acoustic"]
            + inp.fingerprint_conf * WEIGHTS["fingerprint"]
            + inp.bluetooth_conf * WEIGHTS["bluetooth"])
    score = base * 100.0

    reasons = []
    if inp.duration_sec > 30:
        score += 10; reasons.append("present >30s (+10)")
    if inp.duration_sec > 60:
        score += 10; reasons.append("present >60s (+10)")
    if inp.is_unknown:
        score += 15; reasons.append("unknown model (+15)")
    # A decoded Remote ID / DJI DroneID is near-certain proof a drone is present
    # (it is literally transmitting its identity), so floor the score at WARNING
    # regardless of how the other sensors happened to read this instant.
    if inp.remote_id_decoded and score < 75:
        score = 75.0; reasons.append("Remote ID decoded (floor 75)")
    # ADS-B cross-check: a "drone" that coincides with a tracked manned aircraft
    # is very likely a false positive — pull the score down.
    if inp.aircraft_match:
        score -= 20; reasons.append("manned aircraft nearby (-20)")

    score = min(100.0, max(0.0, score))
    for threshold, name, icon in LEVELS:
        if score < threshold:
            level, level_icon = name, icon
            break

    return {"score": round(score, 1), "level": level, "icon": level_icon,
            "modifiers": reasons, "inputs": asdict(inp)}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
    except Exception:
        pass
    demo = ThreatInputs(rf_conf=0.92, visual_conf=0.80, acoustic_conf=0.6,
                        fingerprint_conf=0.7, bluetooth_conf=0.1,
                        duration_sec=45, is_unknown=True)
    r = compute_threat_score(demo)
    print(f"{r['icon']} {r['level']}  score={r['score']}/100")
    print("  modifiers:", ", ".join(r["modifiers"]) or "none")
