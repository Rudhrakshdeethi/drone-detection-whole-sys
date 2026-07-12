import { useState, useEffect } from 'react'

type LogEntry = {
  id: number
  ts: string
  level: 'INFO' | 'WARN' | 'ALERT' | 'CLEAR'
  message: string
  coords?: string
  freq?: string
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

export default function LiveLog() {
  const [entries, setEntries] = useState<LogEntry[]>(() => {
    const base = new Date()
    return seedEvents.map((e, i) => ({
      ...e,
      id: logId++,
      ts: formatTime(new Date(base.getTime() - (seedEvents.length - i) * 18000)),
    }))
  })

  const msgIdx = { current: 0 }
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    const delay = 3000 + Math.random() * 4000
    const id = setTimeout(() => {
      const next = liveMessages[idx % liveMessages.length]
      setEntries(prev => [{ ...next, id: logId++, ts: now() }, ...prev].slice(0, 60))
      setIdx(i => i + 1)
    }, delay)
    return () => clearTimeout(id)
  }, [idx])

  return (
    <div style={{
      background: '#0a120a',
      border: '1px solid #1a3320',
      gridColumn: '1 / 6',
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
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: '8px' }}>
          {(['ALERT', 'WARN', 'INFO', 'CLEAR'] as const).map(l => (
            <span key={l} style={{ color: levelColor[l], letterSpacing: '1px' }}>■ {l}</span>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'hidden', fontFamily: "'JetBrains Mono', monospace" }}>
        {entries.map((e, i) => (
          <div
            key={e.id}
            className={i === 0 ? 'fade-in-down' : ''}
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
            {e.level === 'ALERT' && (
              <div style={{
                padding: '2px 6px',
                background: '#3a0000',
                border: '1px solid #ff313155',
                fontSize: '8px',
                color: '#ff3131',
                letterSpacing: '1px',
                borderRadius: 2,
                whiteSpace: 'nowrap',
              }}>
                ⚠ THREAT
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
