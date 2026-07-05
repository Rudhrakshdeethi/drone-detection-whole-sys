"use client";
import { useEffect, useRef, useState } from "react";
import Panel from "./Panel";
import { LastLand, postLand } from "@/lib/api";

// One tap arms (amber, 4s window); a second tap sends LAND to the operator's own
// allow-listed drone via the Python backend (land-only, allow-list gated).
export default function LandControl({ lastLand }: { lastLand: LastLand }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stat, setStat] = useState({ msg: "Link idle · no landing commanded.", cls: "" });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!busy && lastLand && lastLand.action !== "idle") {
      const cls = lastLand.action === "land" ? "ok" : lastLand.action === "error" ? "err" : "";
      setStat({ msg: lastLand.detail, cls });
    }
  }, [lastLand, busy]);

  const disarm = () => {
    setArmed(false);
    if (timer.current) clearTimeout(timer.current);
  };

  const onClick = async () => {
    if (!armed) {
      setArmed(true);
      timer.current = setTimeout(disarm, 4000);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    setArmed(false);
    setBusy(true);
    setStat({ msg: "▸ transmitting landing command…", cls: "" });
    try {
      const r = await postLand();
      const cls = r.action === "land" ? "ok" : r.action === "error" ? "err" : "";
      setStat({ msg: r.detail || "done", cls });
    } catch (e) {
      setStat({ msg: `request failed: ${e}`, cls: "err" });
    }
    setBusy(false);
  };

  return (
    <Panel idx="02" title="RF Neutralization" right={armed ? "ARMED" : "SAFE"}>
      <div className="land">
        <div className="landframe">
          <button className={`landbtn ${armed ? "armed" : ""}`} disabled={busy} onClick={onClick}>
            {busy ? "· SENDING LAND ·" : armed ? "⚠ CONFIRM LANDING" : "◈ INITIATE RF LANDING"}
          </button>
          <div className="landnote">
            {armed ? "TAP AGAIN TO EXECUTE" : "TAP TO ARM · CONFIRM WITHIN 4S"}
          </div>
        </div>
        <div className={`landstat ${stat.cls}`}>
          <span className="tag">STATUS// </span>{stat.msg}
        </div>
      </div>
    </Panel>
  );
}
