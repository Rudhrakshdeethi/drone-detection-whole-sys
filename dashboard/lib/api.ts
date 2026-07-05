// Types + fetch helpers for the CampusShield Python API (ml/runtime/dashboard.py).

export type Level = "SAFE" | "WATCH" | "WARNING" | "CRITICAL";

export interface Threat {
  score: number;
  level: Level;
  modifiers: string;
  source: string;
  time: string;
  fingerprint: string;
}

export interface Fix {
  lat: string;
  lon: string;
  az: string | number;
  el: string | number;
  range_m: string | number;
}

export interface Sensor {
  key: string;
  name: string;
  active: boolean;
  detail: string;
}

// Backend returns raw CSV rows, so every column is present as an optional field.
export interface FeedRow {
  timestamp: string;
  source: string;
  rf_label: string;
  threat_score: string;
  threat_level: Level;
  rid_manuf?: string;
  rid_model?: string;
  rid_serial?: string;
  fingerprint?: string;
  wifi_ssids?: string;
  drone_lat?: string;
  drone_lon?: string;
  pilot_lat?: string;
  pilot_lon?: string;
  control_band_mhz?: string;
  control_conf?: string;
  visual_conf?: string;
  acoustic_conf?: string;
}

export interface LastLand {
  action: "idle" | "land" | "none" | "error";
  at: string | null;
  detail: string;
}

export interface Snapshot {
  threat: Threat;
  fix: Fix | null;
  sensors: Sensor[];
  feed: FeedRow[];
  last_land: LastLand;
  armed: boolean;
  target_configured: boolean;
}

export interface ConfigInfo {
  host: string;
  port: number;
  ssid_set: boolean;
  force_mock: boolean;
}

export const LEVEL_COLOR: Record<Level, string> = {
  SAFE: "var(--ok)",
  WATCH: "var(--accent)",
  WARNING: "var(--warn)",
  CRITICAL: "var(--crit)",
};

export async function getStatus(): Promise<Snapshot> {
  const r = await fetch("/api/status", { cache: "no-store" });
  if (!r.ok) throw new Error(`status ${r.status}`);
  return r.json();
}

export async function getConfig(): Promise<ConfigInfo> {
  const r = await fetch("/api/config", { cache: "no-store" });
  return r.json();
}

export async function postLand(): Promise<LastLand> {
  const r = await fetch("/api/land", { method: "POST" });
  return r.json();
}

export async function saveConfig(body: {
  ssid?: string;
  host?: string;
  port?: string | number;
}): Promise<{ ok: boolean; ssid_set: boolean }> {
  const r = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}
