"use client";
import { useEffect, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";
import Panel from "./Panel";
import { Fix } from "@/lib/api";

// Plain Leaflet (no react-leaflet) driven imperatively so it plays nicely with
// React 19 / Next 15 and stays client-only. Dark CartoDB tiles + pulsing contact.
export default function MapPanel({ fix }: { fix: Fix | null }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const marker = useRef<any>(null);
  const L = useRef<any>(null);
  const [hasFix, setHasFix] = useState(false);

  useEffect(() => {
    let dead = false;
    (async () => {
      const leaflet = (await import("leaflet")).default;
      if (dead || !el.current || map.current) return;
      L.current = leaflet;
      const m = leaflet
        .map(el.current, { zoomControl: false, attributionControl: false })
        .setView([12.9716, 77.5946], 15);
      leaflet
        .tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
          maxZoom: 20,
          subdomains: "abcd",
        })
        .addTo(m);
      map.current = m;
    })();
    return () => {
      dead = true;
      if (map.current) {
        map.current.remove();
        map.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const leaflet = L.current;
    const m = map.current;
    if (!leaflet || !m) return;
    const lat = fix && fix.lat ? parseFloat(String(fix.lat)) : NaN;
    const lon = fix && fix.lon ? parseFloat(String(fix.lon)) : NaN;
    const ok = Number.isFinite(lat) && Number.isFinite(lon);
    setHasFix(ok);
    if (!ok) {
      if (marker.current) {
        m.removeLayer(marker.current);
        marker.current = null;
      }
      return;
    }
    const icon = leaflet.divIcon({
      className: "",
      html: '<div class="blip"><div class="ring"></div><div class="core"></div></div>',
      iconSize: [12, 12],
    });
    if (!marker.current) {
      marker.current = leaflet.marker([lat, lon], { icon }).addTo(m);
      m.setView([lat, lon], 16, { animate: true });
    } else {
      marker.current.setLatLng([lat, lon]);
      m.panTo([lat, lon], { animate: true });
    }
  }, [fix]);

  const lat = fix?.lat || "—";
  const lon = fix?.lon || "—";

  return (
    <Panel idx="03" title="Tactical Localization" right="CARTO · DARK" flush>
      <div className="map-shell">
        <div className="map" ref={el} />
        {!hasFix && <div className="map-empty">◎ AWAITING POSITIONAL FIX</div>}
        <div className="map-ovl tl">
          <div className="chip">CONTACT <b>{hasFix ? "LOCKED" : "SEARCHING"}</b></div>
        </div>
        <div className="map-ovl br">
          <div className="chip">LAT <b>{lat}</b></div>{" "}
          <div className="chip">LON <b>{lon}</b></div>
        </div>
      </div>
    </Panel>
  );
}
