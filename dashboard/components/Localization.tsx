import { Fix } from "@/lib/api";

const val = (v: string | number | undefined, suffix = "") =>
  v !== undefined && v !== null && v !== "" ? `${Math.round(Number(v))}${suffix}` : "—";

// Bearing / elevation / range read-out strip that sits beneath the map.
export default function Localization({ fix }: { fix: Fix | null }) {
  const f = fix ?? ({} as Fix);
  return (
    <div className="panel">
      <div className="telemstrip">
        <div className="t">
          <div className="k">Bearing</div>
          <div className="v">{val(f.az, "°")}</div>
        </div>
        <div className="t">
          <div className="k">Elevation</div>
          <div className="v">{val(f.el, "°")}</div>
        </div>
        <div className="t">
          <div className="k">Slant Range</div>
          <div className="v">{f.range_m ? `${f.range_m} m` : "—"}</div>
        </div>
        <div className="t">
          <div className="k">Fix Type</div>
          <div className="v">{f.lat ? "3D GPS" : f.az ? "BRG-ONLY" : "NONE"}</div>
        </div>
      </div>
    </div>
  );
}
