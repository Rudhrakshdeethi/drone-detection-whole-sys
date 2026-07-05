import Panel from "./Panel";
import { Sensor } from "@/lib/api";

// Rough signal strength (0..5 filled bars) from a sensor's detail string.
function bars(s: Sensor): number {
  if (!s.active) return 0;
  const m = s.detail.match(/(\d+(\.\d+)?)/);
  if (m) {
    const n = parseFloat(m[1]);
    if (n > 0 && n <= 100) return Math.max(1, Math.min(5, Math.round(n / 20)));
  }
  return 3;
}

export default function SensorGrid({ sensors }: { sensors: Sensor[] }) {
  const live = sensors.filter((s) => s.active).length;
  return (
    <Panel idx="04" title="Sensor Fusion" right={`${live}/${sensors.length} LIVE`}>
      <div className="sensor-list">
        {sensors.map((s) => {
          const n = bars(s);
          return (
            <div key={s.key} className={`srow ${s.active ? "on" : ""}`}>
              <div className="name">
                <span className="st" />
                <span>
                  {s.name}
                  <span className="sub">{s.active ? "TRACKING" : "STANDBY"}</span>
                </span>
              </div>
              <div className="right">
                <span className="bars">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <i key={i} className={i < n ? "f" : ""} />
                  ))}
                </span>
                <span className="val">{s.detail || "—"}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
