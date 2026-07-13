import { useState, useEffect } from 'react'
import { useLive } from '../lib/SystemContext'
import { levelToLogLevel, num, type FeedRow } from '../lib/api'
import { ssidMatch } from '../lib/target'

type LogLevel = 'INFO' | 'WARN' | 'ALERT' | 'CLEAR'

type LogEntry = {
  id: number
  ts: string
  level: LogLevel
  message: string
  coords?: string
  freq?: string
  target?: boolean
}

const seedEvents: Omit<LogEntry, 'id' | 'ts'>[] = [
  { level: 'INFO', message: 'System initialized. All sensors nominal.', },
  { level: 'INFO', message: 'Radar sweep calibrated. Range: 5km.', },
  { level: 'WARN', message: 'WiFi signal spike detected at 2.4GHz.', freq: '2.412 GHz' },
  { level: 'ALERT', message: 'DRONE DETECTED — DJI Mavic 3 Pro', coords: '40.7142°N 74.0059°W', freq: '5.8 GHz' },
  { level: 'INFO', message: 'Camera-01 locked on target. Tracking initiated.', },
  { level: 'WARN', message: 'Bluetooth device detected: unknown controller.', freq: 'BT 5.0' },
  { level: 'ALERT', message: 'DRONE DETECTED — Phantom 4 RTK', coords: '40.7131°N 74.0071°W', freq: '2.4 GHz' },
  { level: 'INFO', message: 'Geofence breach recorded. Alert sent to command.', },
]

const liveMessages: Omit<LogEntry, 'id' | 'ts'>[] = [
  { level: 'INFO', message: 'Radar sweep cycle complete. Contacts logged.', },
  { level: 'WARN', message: 'Unidentified RF burst: 5.8GHz band.', freq: '5.845 GHz' },
  { level: 'INFO', message: 'No new contacts. Area clear.', },
  { level: 'ALERT', message: 'DRONE DETECTED — DJI Mini 4 Pro', coords: '40.7155°N 74.0044°W', freq: '2.4 GHz' },
  { level: 'WARN', message: 'Signal jamming pattern detected in sector B.', freq: '5.1 GHz' },
  { level: 'CLEAR', message: 'Threat resolved. Drone exited geofence.', },
  { level: 'INFO', message: 'Bluetooth scan: 3 new devices in range.', },
  { level: 'ALERT', message: 'DRONE DETECTED — Autel EVO II Pro', coords: '40.7119°N 74.0088°W', freq: '5.8 GHz' },
]

let logId = 0

function formatTime(d: Date) {
  return d.toTimeString().slice(0, 8)
}

function now() {
  return formatTime(new Date())
}

const levelColor: Record<string, string> = {
  INFO: '#5a8a60',
  WARN: '#ff8c00',
  ALERT: '#ff3131',
  CLEAR: '#00b4d8',
}
const levelBg: Record<string, string> = {
  INFO: 'transparent',
  WARN: '#1a0e00',
  ALERT: '#1a0000',
  CLEAR: '#00111a',
}

// Turn one real backend detection row into a log line.
function feedRowToEntry(r: FeedRow, i: number): LogEntry {
  const level = levelToLogLevel(r.threat_level || 'SAFE')
  const model = r.rid_model || r.fingerprint || ''
  const rf = (r.rf_label || '').toUpperCase()
  let message: string
  if (level === 'ALERT') {
    message = model ? `DRONE DETECTED — ${model}` : `THREAT — ${rf || (r.source || 'RF').toUpperCase()}`
  } else if (model) {
    message = `Contact classified: ${model}`
  } else {
    message = `${(r.source || 'sensor').toUpperCase()} · ${rf || 'scan'} · score ${Math.round(num(r.threat_score) ?? 0)}`
  }

  const lat = num(r.drone_lat)
  const lon = num(r.drone_lon)
  const coords = lat !== null && lon !== null ? `${lat.toFixed(4)}, ${lon.toFixed(4)}` : undefined

  const band = num(r.control_band_mhz)
  const freq = band
    ? `${band.toFixed(0)} MHz`
    : r.wifi_ssids
      ? `WiFi · ${r.wifi_ssids.split(/[;,]/)[0]}`
      : undefined

  return {
    id: i,
    ts: (r.timestamp || '').slice(11, 19) || now(),
    level,
    message,
    coords,
    freq,
    target: ssidMatch(r.wifi_ssids),
  }
}

export default function LiveLog() {
  const { live, snapshot } = useLive()

  const [entries, setEntries] = useState<LogEntry[]>(() => {
    const base = new Date()
    return seedEvents.map((e, i) => ({
      ...e,
      id: logId++,
      ts: formatTime(new Date(base.getTime() - (seedEvents.length - i) * 18000)),
    }))
  })

  const [idx, setIdx] = useState(0)

  // Simulation loop — only runs while the backend is offline.
  useEffect(() => {
    if (live) return
    const delay = 3000 + Math.random() * 4000
    const id = setTimeout(() => {
      const next = liveMessages[idx % liveMessages.length]
      setEntries(prev => [{ ...next, id: logId++, ts: now() }, ...prev].slice(0, 60))
      setIdx(i => i + 1)
    }, delay)
    return () => clearTimeout(id)
  }, [idx, live])

  // When live, entries come straight from the real detection feed (newest first).
  const feedEntries: LogEntry[] | null =
    live && snapshot ? snapshot.feed.map((r, i) => feedRowToEntry(r, i)) : null
  const shown = feedEntries ?? entries

  return (
    <div style={{
      background: '#0a120a',
      border: '1px solid #1a3320',
      gridColumn: '6 / 11',
      gridRow: '2',
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      overflow: 'hidden',
    }}>
      <div style={{
        background: '#0d1a0d',
        borderBottom: '1px solid #1a3320',
        padding: '7px 12px',
        fontSize: '9px',
        letterSpacing: '2px',
        color: '#2d8a40',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="blink" style={{ width: 5, height: 5, borderRadius: '50%', background: '#ff3131', boxShadow: '0 0 6px #ff3131', display: 'inline-block' }} />
          LIVE DETECTION LOG
          <span style={{ fontSize: '7px', color: live ? '#00ff41' : '#2d4f32', letterSpacing: '1px', border: `1px solid ${live ? '#1a3320' : '#1a3320'}`, padding: '0 4px', borderRadius: 2 }}>
            {live ? 'BACKEND' : 'SIM'}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: '8px' }}>
          {(['ALERT', 'WARN', 'INFO', 'CLEAR'] as const).map(l => (
            <span key={l} style={{ color: levelColor[l], letterSpacing: '1px' }}>■ {l}</span>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', fontFamily: "'JetBrains Mono', monospace" }}>
        {shown.length === 0 && (
          <div style={{ padding: '18px 12px', fontSize: '10px', color: '#2d4f32', letterSpacing: '1px' }}>
            Waiting for detector stream… (run <span style={{ color: '#5a8a60' }}>ml.runtime.live_detector</span>)
          </div>
        )}
        {shown.map((e, i) => (
          <div
            key={e.id}
            className={i === 0 && !live ? 'fade-in-down' : ''}
            style={{
              display: 'grid',
              gridTemplateColumns: '70px 36px 1fr auto',
              alignItems: 'start',
              gap: '0 10px',
              padding: '5px 12px',
              background: i === 0 ? levelBg[e.level] : 'transparent',
              borderBottom: '1px solid #0f1f0f',
              transition: 'background 1s',
            }}
          >
            <span style={{ fontSize: '9px', color: '#2d4f32', letterSpacing: '0.5px', paddingTop: 1 }}>{e.ts}</span>
            <span style={{
              fontSize: '8px',
              fontWeight: 700,
              color: levelColor[e.level],
              letterSpacing: '1px',
              paddingTop: 1,
            }}>
              [{e.level}]
            </span>
            <div>
              <div style={{ fontSize: '10px', color: e.level === 'ALERT' ? '#ff5555' : e.level === 'WARN' ? '#ff8c00' : '#8ab890', letterSpacing: '0.3px' }}>
                {e.message}
              </div>
              {(e.coords || e.freq) && (
                <div style={{ display: 'flex', gap: 12, marginTop: 2 }}>
                  {e.coords && <span style={{ fontSize: '8px', color: '#2d4f32' }}>📍 {e.coords}</span>}
                  {e.freq && <span style={{ fontSize: '8px', color: '#2d4f32' }}>📡 {e.freq}</span>}
                </div>
              )}
            </div>
            {(e.target || e.level === 'ALERT') && (
              <div style={{
                padding: '2px 6px',
                background: e.target ? '#3a1400' : '#3a0000',
                border: `1px solid ${e.target ? '#ff8c0088' : '#ff313155'}`,
                fontSize: '8px',
                color: e.target ? '#ff8c00' : '#ff3131',
                letterSpacing: '1px',
                borderRadius: 2,
                whiteSpace: 'nowrap',
              }}>
                {e.target ? '◎ TARGET' : '⚠ THREAT'}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
