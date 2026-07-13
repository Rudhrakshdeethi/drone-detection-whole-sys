// Target-drone selection driven by the `.env.local` SSID.
//
// The operator names ONE drone by its WiFi SSID in `.env.local`:
//
//     VITE_SSID=DJI-Mavic-1A2B
//
// Vite inlines `VITE_*` vars at build time, so `import.meta.env.VITE_SSID`
// reaches the browser. `useTarget()` then watches the live detection feed for a
// row whose `wifi_ssids` matches, flags it across the UI (camera, map, log), and
// unlocks the LAND button for exactly that aircraft.
//
// With no backend running the SSID still "detects" — we synthesize a demo
// contact so the whole console lights up hardware-free.

import { useLive } from './SystemContext'
import { num, type FeedRow } from './api'

/** The target drone's SSID, read from `.env.local` (VITE_SSID). '' when unset. */
export const TARGET_SSID = ((import.meta.env.VITE_SSID as string | undefined) ?? '').trim()

/** Base-station reference coordinate used for the demo map / fallback plotting. */
export const BASE = { lat: 40.7128, lon: -74.006 }

/** Split a raw `wifi_ssids` CSV/semicolon field into individual SSID tokens. */
export function ssidTokens(field: string | undefined | null): string[] {
  if (!field) return []
  return field
    .split(/[;,]/)
    .map(s => s.trim())
    .filter(Boolean)
}

/** True when `field` contains `target` (exact token, or case-insensitive substring). */
export function ssidMatch(field: string | undefined | null, target: string = TARGET_SSID): boolean {
  if (!target || !field) return false
  const t = target.toLowerCase()
  return ssidTokens(field).some(s => s.toLowerCase() === t) || field.toLowerCase().includes(t)
}

export interface TargetState {
  /** Configured target SSID from `.env.local` ('' when none set). */
  ssid: string
  /** Whether an SSID was provided at all. */
  configured: boolean
  /** Whether the target drone is currently detected (real feed match or demo). */
  detected: boolean
  /** True when `detected` comes from the demo simulation rather than real data. */
  simulated: boolean
  /** The matched detection row, when live. */
  row: FeedRow | null
  /** Target position (drone lat/lon), when known. */
  lat: number | null
  lon: number | null
}

/**
 * Track the drone named by `VITE_SSID` across the whole app. Safe to call from
 * any panel — it polls no network of its own, just reads the shared snapshot.
 */
export function useTarget(): TargetState {
  const { live, snapshot } = useLive()
  const ssid = TARGET_SSID
  const configured = ssid.length > 0

  if (!configured) {
    return { ssid, configured, detected: false, simulated: false, row: null, lat: null, lon: null }
  }

  if (live && snapshot) {
    const row = snapshot.feed.find(r => ssidMatch(r.wifi_ssids, ssid)) ?? null
    const lat = row ? num(row.drone_lat) : snapshot.fix ? num(snapshot.fix.lat) : null
    const lon = row ? num(row.drone_lon) : snapshot.fix ? num(snapshot.fix.lon) : null
    return { ssid, configured, detected: !!row, simulated: false, row, lat, lon }
  }

  // No backend, but a target SSID is configured → simulate a detection so the
  // camera, map, and LAND control all light up for a hardware-free demo.
  return {
    ssid,
    configured,
    detected: true,
    simulated: true,
    row: null,
    lat: BASE.lat + 0.0016,
    lon: BASE.lon + 0.0022,
  }
}
