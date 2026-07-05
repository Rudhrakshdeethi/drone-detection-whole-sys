"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { getStatus, Snapshot } from "@/lib/api";
import ThreatGauge from "@/components/ThreatGauge";
import SensorGrid from "@/components/SensorGrid";
import Localization from "@/components/Localization";
import DetectionFeed from "@/components/DetectionFeed";
import LandControl from "@/components/LandControl";
import ContactDossier from "@/components/ContactDossier";
import ConfigPanel from "@/components/ConfigPanel";

// Leaflet touches window — load the map client-only.
const MapPanel = dynamic(() => import("@/components/MapPanel"), { ssr: false });

const EMPTY: Snapshot = {
  threat: { score: 0, level: "SAFE", modifiers: "", source: "-", time: "-", fingerprint: "-" },
  fix: null,
  sensors: [],
  feed: [],
  last_land: { action: "idle", at: null, detail: "" },
  armed: false,
  target_configured: false,
};

function utc() {
  return new Date().toISOString().slice(11, 19) + "Z";
}

export default function Page() {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [online, setOnline] = useState(false);
  const [clock, setClock] = useState("--:--:--");
  const [panel, setPanel] = useState(false);
  const clicks = useRef(0);
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const s = await getStatus();
        if (alive) { setSnap(s); setOnline(true); }
      } catch {
        if (alive) setOnline(false);
      }
    };
    poll();
    const id = setInterval(poll, 1200);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    const t = () => setClock(utc());
    t();
    const id = setInterval(t, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "`") { e.preventDefault(); setPanel((p) => !p); }
      else if (e.key === "Escape") setPanel(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onSigil = useCallback(() => {
    clicks.current += 1;
    if (clickTimer.current) clearTimeout(clickTimer.current);
    if (clicks.current >= 3) { clicks.current = 0; setPanel(true); }
    clickTimer.current = setTimeout(() => (clicks.current = 0), 600);
  }, []);

  const contacts = snap.feed.filter((r) => r.threat_level !== "SAFE").length;

  return (
    <>
      <div className="topbar">
        <div className="sigil" onClick={onSigil} title="" />
        <div className="brand">
          <h1>CAMPUSSHIELD</h1>
          <div className="sub">RF COUNTER-DRONE · GROUND CONTROL</div>
        </div>
        <div className="telem">
          <div className="cell">
            <span className="k">Threat State</span>
            <span className={`statechip ${snap.threat.level}`}>{snap.threat.level}</span>
          </div>
          <div className="cell">
            <span className="k">Contacts</span>
            <span className="v big">{String(contacts).padStart(2, "0")}</span>
          </div>
          <div className="cell">
            <span className="k">Uplink</span>
            <span className={`v led ${online ? "up" : "down"}`}>
              <i />{online ? "ONLINE" : "OFFLINE"}
            </span>
          </div>
          <div className="cell">
            <span className="k">Zulu Time</span>
            <span className="v big">{clock}</span>
          </div>
        </div>
      </div>

      <div className="grid">
        <div className="col left">
          <ThreatGauge threat={snap.threat} />
          <LandControl lastLand={snap.last_land} />
        </div>

        <div className="col center">
          <MapPanel fix={snap.fix} />
          <Localization fix={snap.fix} />
          <DetectionFeed feed={snap.feed} />
        </div>

        <div className="col right">
          <SensorGrid sensors={snap.sensors} />
          <ContactDossier feed={snap.feed} fix={snap.fix} />
        </div>
      </div>

      <button className="cog" title="" onClick={() => setPanel(true)} />
      <ConfigPanel open={panel} onClose={() => setPanel(false)} />
    </>
  );
}
