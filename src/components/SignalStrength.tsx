import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useLive } from '../lib/SystemContext'
import { num, type FeedRow, type Sensor } from '../lib/api'

function LiveChart() {
  const [data, setData] = useState<{ time: number, wifi24: number, wifi5: number, bt: number }[]>(() => {
    return Array.from({ length: 30 }, (_, i) => ({ time: i, wifi24: 50, wifi5: 50, bt: 50 }))
  })

  useEffect(() => {
    const id = setInterval(() => {
      setData(prev => {
        const last = prev[prev.length - 1]
        const next = [...prev.slice(1), {
          time: last.time + 1,
          wifi24: Math.max(0, Math.min(100, last.wifi24 + (Math.random() - 0.5) * 20)),
          wifi5: Math.max(0, Math.min(100, last.wifi5 + (Math.random() - 0.5) * 20)),
          bt: Math.max(0, Math.min(100, last.bt + (Math.random() - 0.5) * 20)),
        }]
        return next
      })
    }, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{ height: 160, width: '100%', marginBottom: 16 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 5, right: 0, left: -25, bottom: 0 }}>
          <XAxis dataKey="time" hide />
          <YAxis domain={[0, 100]} stroke="#1a3320" fontSize={8} tick={{ fill: '#2d4f32' }} />
          <Tooltip
            contentStyle={{ background: '#0d1a0d', border: '1px solid #1a3320', fontSize: '10px', color: '#00ff41' }}
            itemStyle={{ color: '#00ff41' }}
          />
          <Line type="monotone" dataKey="wifi24" stroke="#00ff41" strokeWidth={2} dot={false} isAnimationActive={false} name="2.4GHz" />
          <Line type="monotone" dataKey="wifi5" stroke="#ff8c00" strokeWidth={2} dot={false} isAnimationActive={false} name="5.8GHz" />
          <Line type="monotone" dataKey="bt" stroke="#00b4d8" strokeWidth={2} dot={false} isAnimationActive={false} name="Bluetooth" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

const rfBands: { band: string; freq: string; power: number; note: string }[] = [
  { band: '433 MHz', freq: '433.92', power: 12, note: 'ISM — low ctrl' },
  { band: '868 MHz', freq: '868.0', power: 8, note: 'EU drone band' },
  { band: '900 MHz', freq: '915.0', power: 31, note: 'ISM / LTE' },
  { band: '1.2 GHz', freq: '1280.0', power: 48, note: 'FPV video' },
  { band: '2.4 GHz', freq: '2412.0', power: 72, note: 'Ctrl + telemetry' },
  { band: '5.8 GHz', freq: '5800.0', power: 55, note: 'HD video link' },
]

type Device = { id: string; mac: string; rssi: number; dist: string; proto: string }

const knownDevices: Device[] = [
  { id: 'DJI-M30T-7F2A', mac: 'A4:C3:F0:7F:2A:11', rssi: -62, dist: '340m', proto: 'WIFI' },
  { id: 'PHANTOM-4-3B8C', mac: 'B8:27:EB:3B:8C:44', rssi: -74, dist: '780m', proto: 'BT5' },
  { id: 'MAVIC-AIR-9D1E', mac: 'D8:3A:DD:9D:1E:F2', rssi: -88, dist: '1.2km', proto: 'WIFI' },
]

// Derive a device list from the real detection feed: one entry per unique
// drone identity (Remote ID model / fingerprint / SSID), most recent first.
function devicesFromFeed(feed: FeedRow[]): Device[] {
  const seen = new Map<string, Device>()
  for (const r of feed) {
    const id = r.rid_model || r.fingerprint || r.wifi_ssids || ''
    if (!id || seen.has(id)) continue
    const proto = r.wifi_ssids ? 'WIFI' : r.rid_manuf ? 'RID' : (r.rf_label || 'RF').toUpperCase().slice(0, 4)
    const score = num(r.threat_score) ?? 0
    // No real RSSI in the stream — approximate a signal read from threat score.
    const rssi = Math.round(-95 + (score / 100) * 45)
    const band = num(r.control_band_mhz)
    seen.set(id, {
      id: id.toUpperCase().replace(/\s+/g, '-').slice(0, 18),
      mac: r.rid_serial || r.source || '—',
      rssi,
      dist: band !== null ? `${band.toFixed(0)}MHz` : '—',
      proto,
    })
    if (seen.size >= 4) break
  }
  return [...seen.values()]
}

function RFWaterfall() {
  const cols = 40
  const rows = 10
  const [grid, setGrid] = useState<number[][]>(() =>
    Array.from({ length: rows }, () => Array.from({ length: cols }, () => Math.random() * 0.2))
  )

  useEffect(() => {
    const id = setInterval(() => {
      setGrid(prev => {
        const newRow = Array.from({ length: cols }, (_, i) => {
          const base = i < 15 ? 0.1 : i < 25 ? 0.55 + Math.random() * 0.35 : 0.35 + Math.random() * 0.3
          return Math.min(1, base + (Math.random() - 0.5) * 0.25)
        })
        return [newRow, ...prev.slice(0, rows - 1)]
      })
    }, 500)
    return () => clearInterval(id)
  }, [])

  const cellColor = (v: number) => {
    if (v < 0.25) return '#001a00'
    if (v < 0.45) return '#003310'
    if (v < 0.6) return '#006618'
    if (v < 0.75) return '#00a028'
    if (v < 0.88) return '#ff8c00'
    return '#ff3131'
  }

  return (
    <div style={{ display: 'grid', gridTemplateRows: `repeat(${rows}, 4px)`, gap: 1 }}>
      {grid.map((row, ri) => (
        <div key={ri} style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 1 }}>
          {row.map((v, ci) => (
            <div key={ci} style={{ height: 4, background: cellColor(v), borderRadius: 0.5, opacity: 1 - ri * 0.07 }} />
          ))}
        </div>
      ))}
    </div>
  )
}

function FusionStrip({ sensors }: { sensors: Sensor[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 12 }}>
      {sensors.map(s => (
        <div
          key={s.key}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '5px 7px',
            border: '1px solid #1a3320',
            borderRadius: 3,
            background: '#0d1a0d',
          }}
        >
          <span style={{
            width: 7, height: 7, borderRadius: '50%',
            background: s.active ? '#00ff41' : '#2d4f32',
            boxShadow: s.active ? '0 0 6px #00ff41' : 'none',
            flexShrink: 0,
          }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '8px', color: s.active ? '#8ab890' : '#2d4f32', letterSpacing: '0.5px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
            <div style={{ fontSize: '8px', color: '#5a8a60', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.detail || '—'}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function SignalStrength() {
  const { live, snapshot } = useLive()
  const devices = live && snapshot ? devicesFromFeed(snapshot.feed) : knownDevices

  return (
    <div style={{
      background: '#0a120a',
      border: '1px solid #1a3320',
      gridColumn: '8 / 11',
      gridRow: '1',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      minHeight: 0,
    }}>
      <PanelLabel>SIGNAL INTELLIGENCE</PanelLabel>

      <div style={{ flex: 1, overflowY: 'auto', padding: '10px' }}>

        {/* Sensor fusion — only meaningful with the real backend */}
        {live && snapshot && (
          <>
            <SectionTitle icon="▸" label="SENSOR FUSION" />
            <FusionStrip sensors={snapshot.sensors} />
            <div style={{ height: 1, background: '#1a3320', margin: '8px 0' }} />
          </>
        )}

        {/* Live Signal Chart Section */}
        <SectionTitle icon="▸" label="LIVE SIGNAL STRENGTH" />
        <div style={{ display: 'flex', gap: 16, marginBottom: 8, fontSize: '9px', fontWeight: 600 }}>
          <span style={{ color: '#00ff41' }}>● 2.4GHz</span>
          <span style={{ color: '#ff8c00' }}>● 5.8GHz</span>
          <span style={{ color: '#00b4d8' }}>● BLUETOOTH</span>
        </div>
        <LiveChart />

        <div style={{ height: 1, background: '#1a3320', margin: '8px 0' }} />

        {/* RF Spectrum Section */}
        <SectionTitle icon="▸" label="RF SPECTRUM MONITOR" />
        <div style={{ marginBottom: 16 }}>
          {rfBands.map(rb => {
            const isHot = rb.power > 50
            const color = isHot ? '#ff8c00' : '#00ff41'
            return (
              <div key={rb.band} style={{ marginBottom: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ fontSize: '8px', color: isHot ? '#ff8c00' : '#2d8a40', fontWeight: 600, letterSpacing: '0.5px' }}>{rb.band}</span>
                  <span style={{ fontSize: '7px', color: '#2d4f32', letterSpacing: '0.5px' }}>{rb.note}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ flex: 1, height: 5, background: '#1a3320', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      width: `${rb.power}%`,
                      background: isHot
                        ? 'linear-gradient(to right, #ff8c00, #ff5500)'
                        : 'linear-gradient(to right, #00ff41, #00c832)',
                      borderRadius: 2,
                      boxShadow: isHot ? '0 0 5px #ff8c0066' : '0 0 4px #00ff4166',
                    }} />
                  </div>
                  <span style={{ fontSize: '8px', color, width: 28, textAlign: 'right' }}>{rb.power}%</span>
                </div>
                <div style={{ fontSize: '7px', color: '#2d4f32', marginTop: 1 }}>{rb.freq} MHz</div>
              </div>
            )
          })}

          {/* Waterfall mini-display */}
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: '8px', color: '#2d4f32', letterSpacing: '1px', marginBottom: 4 }}>WATERFALL · 2.4–5.8 GHz</div>
            <RFWaterfall />
          </div>
        </div>

        <div style={{ height: 1, background: '#1a3320', margin: '8px 0' }} />

        {/* Detected devices */}
        <SectionTitle icon="▸" label={live ? 'DETECTED CONTACTS' : 'DETECTED DEVICES'} />
        <div>
          {devices.length === 0 && (
            <div style={{ fontSize: '9px', color: '#2d4f32', padding: '6px 0' }}>No contacts in the current stream.</div>
          )}
          {devices.map(d => (
            <div
              key={d.id + d.mac}
              style={{
                marginBottom: 8,
                padding: '8px',
                background: '#0d1a0d',
                border: '1px solid #1a3320',
                borderRadius: 2,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ fontSize: '9px', color: '#00ff41', letterSpacing: '1px', fontWeight: 600 }}>{d.id}</span>
                <span style={{
                  fontSize: '8px',
                  padding: '1px 5px',
                  background: d.proto === 'WIFI' ? '#003310' : '#001a2a',
                  color: d.proto === 'WIFI' ? '#00ff41' : '#00b4d8',
                  borderRadius: 2,
                  letterSpacing: '1px',
                }}>
                  {d.proto}
                </span>
              </div>
              <div style={{ fontSize: '8px', color: '#2d4f32', letterSpacing: '0.5px', marginBottom: 2 }}>{d.mac}</div>
              <div style={{ display: 'flex', gap: 12, fontSize: '8px' }}>
                <span style={{ color: '#5a8a60' }}>RSSI: <span style={{ color: '#00c832' }}>{d.rssi}dBm</span></span>
                <span style={{ color: '#5a8a60' }}>DIST: <span style={{ color: '#00c832' }}>{d.dist}</span></span>
              </div>
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}

function PanelLabel({ children }: { children: React.ReactNode }) {
  return (
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
      {children}
    </div>
  )
}

function SectionTitle({ icon, label }: { icon: string; label: string }) {
  return (
    <div style={{ fontSize: '8px', color: '#00c832', letterSpacing: '2px', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
      <span style={{ color: '#2d4f32' }}>{icon}</span>
      {label}
    </div>
  )
}
