import Panel from "./Panel";
import { FeedRow, Fix } from "@/lib/api";

function Line({ k, v }: { k: string; v: string }) {
  return (
    <div className="dz-row">
      <span className="dz-k">{k}</span>
      <span className="dz-v">{v || "—"}</span>
    </div>
  );
}

// Dossier on the highest-priority current contact — the newest logged event.
export default function ContactDossier({
  feed,
  fix,
}: {
  feed: FeedRow[];
  fix: Fix | null;
}) {
  const c = feed[0];
  if (!c) {
    return (
      <Panel idx="06" title="Primary Contact">
        <div className="dz-empty">◎ NO ACTIVE CONTACT</div>
      </Panel>
    );
  }
  const designation =
    [c.rid_manuf, c.rid_model].filter(Boolean).join(" ") || c.fingerprint || "UNIDENTIFIED";
  const drone =
    c.drone_lat || fix?.lat ? `${c.drone_lat || fix?.lat}, ${c.drone_lon || fix?.lon}` : "";
  const pilot = c.pilot_lat ? `${c.pilot_lat}, ${c.pilot_lon}` : "";
  const band = c.control_band_mhz && Number(c.control_band_mhz) ? `${c.control_band_mhz} MHz` : "";

  return (
    <Panel idx="06" title="Primary Contact" right={c.threat_level}>
      <div className="dz">
        <Line k="DESIGNATION" v={designation} />
        <Line k="CLASS" v={(c.rf_label || "").toUpperCase()} />
        <Line k="SERIAL" v={c.rid_serial || ""} />
        <Line k="SSID" v={c.wifi_ssids || ""} />
        <Line k="CTRL BAND" v={band} />
        <Line k="DRONE GPS" v={drone} />
        <Line k="PILOT GPS" v={pilot} />
      </div>
    </Panel>
  );
}
