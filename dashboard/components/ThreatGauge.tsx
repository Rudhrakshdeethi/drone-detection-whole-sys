import Panel from "./Panel";
import { Threat } from "@/lib/api";

const CX = 105, CY = 105, R = 82, START = 225, SWEEP = 270;
const COLOR: Record<string, string> = {
  SAFE: "var(--ok)", WATCH: "var(--watch)", WARNING: "var(--warn)", CRITICAL: "var(--crit)",
};

// polar: degrees measured 0 = top (12 o'clock), increasing clockwise. Coords are
// rounded to a fixed precision so server and client render byte-identical SVG (no
// hydration mismatch from floating-point tail digits).
function polar(deg: number, r = R): [string, string] {
  const a = (deg * Math.PI) / 180;
  return [(CX + r * Math.sin(a)).toFixed(2), (CY - r * Math.cos(a)).toFixed(2)];
}
function arc(a0: number, a1: number): string {
  const [x0, y0] = polar(a0);
  const [x1, y1] = polar(a1);
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${R} ${R} 0 ${large} 1 ${x1} ${y1}`;
}

export default function ThreatGauge({ threat }: { threat: Threat }) {
  const pct = Math.max(0, Math.min(100, threat.score));
  const col = COLOR[threat.level] ?? "var(--ok)";
  const ticks = Array.from({ length: 21 }, (_, i) => {
    const major = i % 2 === 0;
    const deg = START + (i / 20) * SWEEP;
    const [xo, yo] = polar(deg, R + 9);
    const [xi, yi] = polar(deg, major ? R + 1 : R + 4);
    return { xo, yo, xi, yi, major, on: (i / 20) * 100 <= pct };
  });

  return (
    <Panel idx="01" title="Threat Assessment" right={threat.time?.slice(11) || "--:--:--"}>
      <div className="gauge-wrap">
        <div className="gauge">
          <svg viewBox="0 0 210 210">
            {ticks.map((t, i) => (
              <line
                key={i}
                x1={t.xi} y1={t.yi} x2={t.xo} y2={t.yo}
                stroke={t.on ? col : "var(--edge-hi)"}
                strokeWidth={t.major ? 1.6 : 1}
                opacity={t.on ? 0.9 : 0.5}
              />
            ))}
            <path d={arc(START, START + SWEEP)} fill="none" stroke="var(--edge)" strokeWidth="12" strokeLinecap="round" />
            <path
              d={arc(START, START + (SWEEP * pct) / 100)}
              fill="none" stroke={col} strokeWidth="12" strokeLinecap="round"
              style={{ transition: "all .5s cubic-bezier(.4,0,.2,1)", filter: `drop-shadow(0 0 6px ${col})` }}
            />
          </svg>
          <div className="center">
            <div className="num mono">{Math.round(threat.score)}</div>
            <div className="den">INDEX / 100</div>
            <div className={`lvl ${threat.level}`}>{threat.level}</div>
          </div>
        </div>

        <div className="gauge-meta">
          <div className="r"><span className="k">SOURCE</span><span className="v">{threat.source || "—"}</span></div>
          <div className="r"><span className="k">CLASSIFIED</span><span className="v">{threat.fingerprint || "—"}</span></div>
        </div>
        {threat.modifiers ? <div className="gauge-mods">▸ {threat.modifiers}</div> : null}
      </div>
    </Panel>
  );
}
