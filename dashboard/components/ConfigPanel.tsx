"use client";
import { useEffect, useState } from "react";
import { getConfig, saveConfig } from "@/lib/api";

// The SSID / allow-list token lives here — deliberately kept off the main
// console so the demo presents as pure RF. Opened only by a secret gesture
// (handled in page.tsx: backtick key, triple-click sigil, or the corner dot).
export default function ConfigPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [ssid, setSsid] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [ph, setPh] = useState("PLUTO");

  useEffect(() => {
    if (!open) return;
    getConfig()
      .then((c) => {
        setHost(c.host || "");
        setPort(String(c.port || ""));
        setSsid("");
        setPh(c.ssid_set ? "•••••• (set — blank keeps current)" : "PLUTO");
      })
      .catch(() => {});
  }, [open]);

  if (!open) return null;

  const save = async () => {
    const body: { host: string; port: string; ssid?: string } = { host, port };
    if (ssid.trim()) body.ssid = ssid.trim();
    await saveConfig(body);
    onClose();
  };

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="m-hd">
          <h3>Control Link · Restricted</h3>
          <p>
            Own-drone link. LAND-only, allow-list gated — never jams, spoofs, or
            seizes third-party aircraft.
          </p>
        </div>
        <div className="m-bd">
          <label>Drone SSID / allow-list token</label>
          <input value={ssid} placeholder={ph} autoComplete="off" onChange={(e) => setSsid(e.target.value)} />
          <div className="row">
            <div>
              <label>Control host</label>
              <input value={host} placeholder="192.168.4.1" onChange={(e) => setHost(e.target.value)} />
            </div>
            <div>
              <label>Port</label>
              <input value={port} placeholder="23" onChange={(e) => setPort(e.target.value)} />
            </div>
          </div>
          <div className="actions">
            <button onClick={onClose}>Close</button>
            <button className="save" onClick={save}>
              Commit
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
