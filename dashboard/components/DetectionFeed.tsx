import Panel from "./Panel";
import { FeedRow } from "@/lib/api";

export default function DetectionFeed({ feed }: { feed: FeedRow[] }) {
  return (
    <Panel idx="05" title="Detection Log" right={`${feed.length} EVENTS`} flush>
      <table>
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Src</th>
            <th>Class</th>
            <th>Idx</th>
            <th>State</th>
            <th>Identity / SSID</th>
          </tr>
        </thead>
        <tbody>
          {feed.length === 0 ? (
            <tr>
              <td className="empty" colSpan={6}>
                ⋯ AWAITING DETECTOR STREAM
              </td>
            </tr>
          ) : (
            feed.map((r, i) => (
              <tr key={`${r.timestamp}-${i}`}>
                <td>{(r.timestamp || "").slice(11) || "—"}</td>
                <td>{r.source}</td>
                <td>{(r.rf_label || "").toUpperCase()}</td>
                <td>{Math.round(parseFloat(r.threat_score || "0"))}</td>
                <td>
                  <span className={`pill ${r.threat_level}`}>{r.threat_level}</span>
                </td>
                <td className="id">{r.rid_model || r.fingerprint || r.wifi_ssids || "—"}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </Panel>
  );
}
