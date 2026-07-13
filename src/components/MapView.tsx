import { useEffect, useState } from 'react'
import { useLive } from '../lib/SystemContext'
import { num } from '../lib/api'
import { useTarget, ssidMatch, BASE } from '../lib/target'

// Self-contained tactical map — no external tiles, so it works fully offline and
// matches the console aesthetic. It plots everything around the base station:
// the target drone (named by VITE_SSID), its pilot, and any other live contacts.

const RANGE_M = 600 // half-width the map covers, in metres
const CENTER = 150
const PLOT_R = 132 // px radius the range maps onto in the 300x300 viewBox

// Convert a lat/lon into map pixels relative to the base station. Returns null
// when out of frame so we don't draw markers off the plotted disc.
function project(lat: number, lon: number): { x: number; y: number; clamped: boolean } {
  const mPerDegLat = 111320
  const mPerDegLon = 111320 * Math.cos((BASE.lat * Math.PI) / 180)
  const mx = (lon - BASE.lon) * mPerDegLon
  const my = (lat - BASE.lat) * mPerDegLat
  let x = (mx / RANGE_M) * PLOT_R
  let y = -(my / RANGE_M) * PLOT_R
  const d = Math.sqrt(x * x + y * y)
  let clamped = false
  if (d > PLOT_R) {
    x = (x / d) * PLOT_R
    y = (y / d) * PLOT_R
    clamped = true
  }
  return { x: CENTER + x, y: CENTER + y, clamped }
}

type Contact = { id: string; lat: number; lon: number; threat: boolean; target: boolean; label: string }

export default function MapView() {
  const { live, snapshot } = useLive()
  const target = useTarget()

  // Slow demo drift so the target visibly moves when there's no backend.
  const [t, setT] = useState(0)
  useEffect(() => {
    if (live) return
    const id = setInterval(() => setT(v => v + 1), 120)
    return () => clearInterval(id)
  }, [live])

  const contacts: Contact[] = []
  let pilot: { x: number; y: number } | null = null

  if (live && snapshot) {
    // Real contacts straight from the detection feed.
    snapshot.feed.forEach((r, i) => {
      const lat = num(r.drone_lat)
      const lon = num(r.drone_lon)
      if (lat === null || lon === null) return
      const isTarget = ssidMatch(r.wifi_ssids)
      contacts.push({
        id: `f${i}`,
        lat,
        lon,
        threat: r.threat_level === 'WARNING' || r.threat_level === 'CRITICAL',
        target: isTarget,
        label: isTarget ? target.ssid : r.rid_model || r.fingerprint || 'CONTACT',
      })
      if (isTarget) {
        const plat = num(r.pilot_lat)
        const plon = num(r.pilot_lon)
        if (plat !== null && plon !== null) {
          const p = project(plat, plon)
          pilot = { x: p.x, y: p.y }
        }
      }
    })
  } else if (target.configured) {
    // Demo: orbit the configured target slowly around the base station.
    const ang = t * 0.02
    const lat = BASE.lat + 0.0016 * Math.cos(ang) + 0.0006 * Math.sin(ang * 0.5)
    const lon = BASE.lon + 0.0022 * Math.sin(ang)
    contacts.push({ id: 'demo-target', lat, lon, threat: true, target: true, label: target.ssid })
    const p = project(BASE.lat - 0.0009, BASE.lon + 0.0004)
    pilot = { x: p.x, y: p.y }
    // A couple of ambient contacts.
    contacts.push({ id: 'a1', lat: BASE.lat + 0.0031, lon: BASE.lon - 0.0018, threat: false, target: false, label: 'RF-01' })
    contacts.push({ id: 'a2', lat: BASE.lat - 0.0024, lon: BASE.lon - 0.0026, threat: false, target: false, label: 'RF-02' })
  }

  const targetContact = contacts.find(c => c.target) ?? null
  const threatCount = contacts.filter(c => c.threat).length

  return (
    <div
      style={{
        background: '#0a120a',
        border: `1px solid ${targetContact ? '#3a1414' : '#1a3320'}`,
        gridColumn: '1 / 6',
        gridRow: '2',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        minHeight: 0,
      }}
    >
      <div style={{
        background: '#0d1a0d',
        borderBottom: '1px solid #1a3320',
        padding: '7px 12px',
        fontSize: '9px',
        letterSpacing: '2px',
        color: '#2d8a40',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        flexShrink: 0,
      }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#00ff41', boxShadow: '0 0 6px #00ff41', display: 'inline-block' }} />
        TACTICAL MAP · {RANGE_M * 2}m FIELD
        <span style={{ marginLeft: 'auto', fontSize: '8px', letterSpacing: '1px', color: targetContact ? '#ff3131' : '#2d4f32' }}>
          {target.configured
            ? targetContact
              ? `TARGET ${target.ssid} LOCKED`
              : `TARGET ${target.ssid} · NO FIX`
            : 'NO TARGET SSID'}
        </span>
      </div>

      <div style={{ flex: 1, position: 'relative', minHeight: 0, padding: 10 }}>
        <svg viewBox="0 0 300 300" style={{ position: 'absolute', inset: 10, width: 'calc(100% - 20px)', height: 'calc(100% - 20px)', overflow: 'visible' }}>
          <defs>
            <radialGradient id="mapBg" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#062611" stopOpacity="0.5" />
              <stop offset="100%" stopColor="#040a06" stopOpacity="1" />
            </radialGradient>
            <clipPath id="mapClip"><circle cx={CENTER} cy={CENTER} r={PLOT_R} /></clipPath>
          </defs>

          <circle cx={CENTER} cy={CENTER} r={PLOT_R} fill="url(#mapBg)" stroke="#1a3320" strokeWidth="1" />

          <g clipPath="url(#mapClip)">
            {/* Lat/lon grid */}
            {[-2, -1, 1, 2].map(i => (
              <line key={`gx${i}`} x1={CENTER + (i * PLOT_R) / 2.5} y1={CENTER - PLOT_R} x2={CENTER + (i * PLOT_R) / 2.5} y2={CENTER + PLOT_R} stroke="#00ff41" strokeWidth="0.3" opacity="0.1" />
            ))}
            {[-2, -1, 1, 2].map(i => (
              <line key={`gy${i}`} x1={CENTER - PLOT_R} y1={CENTER + (i * PLOT_R) / 2.5} x2={CENTER + PLOT_R} y2={CENTER + (i * PLOT_R) / 2.5} stroke="#00ff41" strokeWidth="0.3" opacity="0.1" />
            ))}
            {/* Range rings (200 / 400 / 600 m) */}
            {[1 / 3, 2 / 3, 1].map((f, i) => (
              <circle key={i} cx={CENTER} cy={CENTER} r={PLOT_R * f} fill="none" stroke="#00ff41" strokeWidth="0.5" opacity="0.14" />
            ))}
            <line x1={CENTER - PLOT_R} y1={CENTER} x2={CENTER + PLOT_R} y2={CENTER} stroke="#00ff41" strokeWidth="0.4" opacity="0.12" />
            <line x1={CENTER} y1={CENTER - PLOT_R} x2={CENTER} y2={CENTER + PLOT_R} stroke="#00ff41" strokeWidth="0.4" opacity="0.12" />
          </g>

          {/* Pilot marker + link line to target */}
          {pilot && (
            <g>
              {targetContact && (() => {
                const tp = project(targetContact.lat, targetContact.lon)
                return <line x1={pilot!.x} y1={pilot!.y} x2={tp.x} y2={tp.y} stroke="#ff8c00" strokeWidth="0.6" strokeDasharray="3 3" opacity="0.5" />
              })()}
              <rect x={pilot.x - 4} y={pilot.y - 4} width="8" height="8" fill="none" stroke="#ff8c00" strokeWidth="1.2" transform={`rotate(45 ${pilot.x} ${pilot.y})`} />
              <text x={pilot.x + 8} y={pilot.y + 3} fill="#ff8c00" fontSize="7" fontFamily="'JetBrains Mono', monospace" opacity="0.8">PILOT</text>
            </g>
          )}

          {/* Contacts */}
          {contacts.map(c => {
            const p = project(c.lat, c.lon)
            const color = c.target ? '#ff3131' : c.threat ? '#ff8c00' : '#00ff41'
            return (
              <g key={c.id}>
                {c.target && (
                  <circle cx={p.x} cy={p.y} r={9 + (t % 30) * 0.25} fill="none" stroke="#ff3131" strokeWidth="0.8" opacity={Math.max(0, 0.5 - (t % 30) * 0.015)} />
                )}
                <circle cx={p.x} cy={p.y} r={c.target ? 4.5 : 3} fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }} />
                {c.target && (
                  <>
                    <line x1={p.x - 9} y1={p.y} x2={p.x - 5} y2={p.y} stroke="#ff3131" strokeWidth="1" />
                    <line x1={p.x + 5} y1={p.y} x2={p.x + 9} y2={p.y} stroke="#ff3131" strokeWidth="1" />
                    <line x1={p.x} y1={p.y - 9} x2={p.x} y2={p.y - 5} stroke="#ff3131" strokeWidth="1" />
                    <line x1={p.x} y1={p.y + 5} x2={p.x} y2={p.y + 9} stroke="#ff3131" strokeWidth="1" />
                  </>
                )}
                <text x={p.x + 7} y={p.y - 6} fill={color} fontSize="7.5" fontFamily="'JetBrains Mono', monospace" opacity="0.9">{c.label}</text>
              </g>
            )
          })}

          {/* Base station (own position) */}
          <g>
            <circle cx={CENTER} cy={CENTER} r="5" fill="none" stroke="#00b4d8" strokeWidth="1.4" />
            <circle cx={CENTER} cy={CENTER} r="1.6" fill="#00b4d8" />
            <text x={CENTER + 8} y={CENTER + 12} fill="#00b4d8" fontSize="7" fontFamily="'JetBrains Mono', monospace" opacity="0.8">BASE</text>
          </g>
        </svg>
      </div>

      {/* Footer readout */}
      <div style={{ display: 'flex', gap: 14, padding: '6px 12px', borderTop: '1px solid #1a3320', fontSize: '8px', letterSpacing: '1px', flexShrink: 0 }}>
        <span style={{ color: '#00b4d8' }}>◆ BASE {BASE.lat.toFixed(4)},{BASE.lon.toFixed(4)}</span>
        <span style={{ color: '#ff3131' }}>● {threatCount} THREAT</span>
        {targetContact && (
          <span style={{ color: '#ff3131', marginLeft: 'auto' }}>
            {target.ssid} @ {targetContact.lat.toFixed(4)},{targetContact.lon.toFixed(4)}
          </span>
        )}
      </div>
    </div>
  )
}
