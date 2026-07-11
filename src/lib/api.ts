// Data layer for the DRONEWATCH dashboard.
//
// Talks to the CampusShield Python backend (`ml/runtime/dashboard.py`), which
// serves the real detection stream from `reports/live_detections.csv`:
//
//   GET  /api/status   -> Snapshot (threat, fix, sensors, feed, land state)
//   GET  /api/config    -> ConfigInfo (host/port, ssid_set)
//   POST /api/land      -> LastLand   (commands the own drone to LAND)
//
// Every call fails soft: when the backend isn't running the UI keeps its own
// built-in simulation, so the dashboard is a full working demo with zero
// hardware and lights up with real data the moment the detector is live.

export type Level = 'SAFE' | 'WATCH' | 'WARNING' | 'CRITICAL'

export interface Threat {
  score: number
  level: Level
  modifiers: string
  source: string
  time: string
  fingerprint: string
}

export interface Fix {
  lat: string
  lon: string
  az: string | number
  el: string | number
  range_m: string | number
}

export interface Sensor {
  key: string
  name: string
  active: boolean
  detail: string
}

// The backend forwards raw CSV rows, so every column is an optional string.
export interface FeedRow {
  timestamp: string
  source: string
  rf_label: string
  threat_score: string
  threat_level: Level
  rid_manuf?: string
  rid_model?: string
  rid_serial?: string
  fingerprint?: string
  wifi_ssids?: string
  drone_lat?: string
  drone_lon?: string
  pilot_lat?: string
  pilot_lon?: string
  control_band_mhz?: string
  control_conf?: string
  visual_conf?: string
  acoustic_conf?: string
}

export interface LastLand {
  action: 'idle' | 'land' | 'none' | 'error'
  at: string | null
  detail: string
  raw?: unknown
}

export interface Snapshot {
  threat: Threat
  fix: Fix | null
  sensors: Sensor[]
  feed: FeedRow[]
  last_land: LastLand
  armed: boolean
  target_configured: boolean
}

export interface ConfigInfo {
  host: string
  port: number
  ssid_set: boolean
  force_mock: boolean
}

// Where the Python backend lives. In dev, Vite proxies `/api` there (see
// vite.config.ts). Override with `VITE_API_BASE` to point at a remote Pi, e.g.
// VITE_API_BASE="http://raspberrypi.local:8080".
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

async function req<T>(path: string, init?: RequestInit, timeoutMs = 4000): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      cache: 'no-store',
      signal: ctrl.signal,
      ...init,
    })
    if (!r.ok) throw new Error(`${path} -> ${r.status}`)
    return (await r.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

export function getStatus(): Promise<Snapshot> {
  return req<Snapshot>('/api/status')
}

export function getConfig(): Promise<ConfigInfo> {
  return req<ConfigInfo>('/api/config')
}

export function postLand(): Promise<LastLand> {
  return req<LastLand>('/api/land', { method: 'POST' }, 8000)
}

export function saveConfig(body: {
  ssid?: string
  host?: string
  port?: string | number
}): Promise<{ ok: boolean; ssid_set: boolean }> {
  return req('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// ---- small shared helpers ----------------------------------------------------

/** Parse a possibly-empty backend string field into a finite number, else null. */
export function num(v: string | number | undefined | null): number | null {
  if (v === undefined || v === null || v === '') return null
  const n = typeof v === 'number' ? v : parseFloat(v)
  return Number.isFinite(n) ? n : null
}

export const LEVEL_COLOR: Record<Level, string> = {
  SAFE: '#00ff41',
  WATCH: '#00b4d8',
  WARNING: '#ff8c00',
  CRITICAL: '#ff3131',
}

/** Map the backend threat level onto the dashboard's log severity vocabulary. */
export function levelToLogLevel(l: Level): 'INFO' | 'WARN' | 'ALERT' | 'CLEAR' {
  switch (l) {
    case 'CRITICAL':
    case 'WARNING':
      return 'ALERT'
    case 'WATCH':
      return 'WARN'
    case 'SAFE':
    default:
      return 'INFO'
  }
}
