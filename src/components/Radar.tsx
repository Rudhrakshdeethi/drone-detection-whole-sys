import { useState, useEffect, useRef } from 'react'
import { useLive } from '../lib/SystemContext'
import { num } from '../lib/api'

type Blip = { id: number; x: number; y: number; vx: number; vy: number; age: number; maxAge: number; threat: boolean }

let blipId = 0

// Radar covers 5 km; a single-node fix range is in metres. Clamp the plotted
// radius so a real bearing is always visible (mid-ring minimum) rather than
// collapsing onto the centre.
const RADAR_RANGE_M = 5000

export default function Radar() {
  const { live, snapshot } = useLive()

  const [blips, setBlips] = useState<Blip[]>([
    { id: blipId++, x: 0.2, y: -0.4, vx: -0.002, vy: 0.001, age: 0, maxAge: 800, threat: true },
    { id: blipId++, x: -0.5, y: 0.5, vx: 0.001, vy: -0.002, age: 100, maxAge: 900, threat: false },
    { id: blipId++, x: 0.8, y: 0.1, vx: -0.0015, vy: 0.0005, age: 50, maxAge: 700, threat: false },
  ])
  const [sweepAngle, setSweepAngle] = useState(0)
  const angleRef = useRef(0)

  useEffect(() => {
    const id = setInterval(() => {
      angleRef.current = (angleRef.current + 1.5) % 360
      setSweepAngle(angleRef.current)

      // Live mode shows the real target only — freeze the ambient simulation.
      if (live) return

      // Move blips according to their velocity and occasionally add new ones
      setBlips(prev => {
        const next = prev
          .map(b => ({ ...b, x: b.x + b.vx, y: b.y + b.vy, age: b.age + 1 }))
          .filter(b => b.age < b.maxAge && Math.sqrt(b.x*b.x + b.y*b.y) < 1.1)

        if (Math.random() < 0.02 && next.length < 8) {
          const angle = Math.random() * Math.PI * 2
          const dist = 1.0
          const targetAngle = angle + Math.PI + (Math.random() - 0.5) * 1.5
          const speed = 0.0005 + Math.random() * 0.0015
          next.push({
            id: blipId++,
            x: Math.cos(angle) * dist,
            y: Math.sin(angle) * dist,
            vx: Math.cos(targetAngle) * speed,
            vy: Math.sin(targetAngle) * speed,
            age: 0,
            maxAge: 400 + Math.random() * 800,
            threat: Math.random() < 0.2,
          })
        }
        return next
      })
    }, 20)
    return () => clearInterval(id)
  }, [live])

  // Build the real target blip from the backend localization fix (bearing +
  // range), when one is available.
  const fix = live && snapshot ? snapshot.fix : null
  const realThreat = live && snapshot ? snapshot.threat.level : null
  const az = fix ? num(fix.az) : null
  const realBlips: Blip[] = []
  if (az !== null) {
    const rng = fix ? num(fix.range_m) : null
    const rNorm = rng !== null ? Math.min(1, Math.max(0.35, rng / RADAR_RANGE_M)) : 0.6
    const rad = (az * Math.PI) / 180 // 0° = North (up)
    realBlips.push({
      id: -1,
      x: Math.sin(rad) * rNorm,
      y: -Math.cos(rad) * rNorm,
      vx: 0, vy: 0, age: 0, maxAge: 1,
      threat: realThreat === 'WARNING' || realThreat === 'CRITICAL',
    })
  }

  const activeBlips = live ? realBlips : blips

  const cx = 130
  const cy = 130
  const r = 110

  const blipCoords = (b: Blip) => {
    return {
      x: cx + b.x * r,
      y: cy + b.y * r,
    }
  }

  // Sweep gradient — trail behind sweep line
  const sweep1 = (sweepAngle - 90) * (Math.PI / 180)
  const sweep2 = (sweepAngle - 90 + 60) * (Math.PI / 180)
  const x1 = cx + Math.cos(sweep1) * r
  const y1 = cy + Math.sin(sweep1) * r
  const x2 = cx + Math.cos(sweep2) * r
  const y2 = cy + Math.sin(sweep2) * r

  const hasCriticalThreat = live
    ? realThreat === 'CRITICAL'
    : activeBlips.some(b => b.threat && Math.sqrt(b.x*b.x + b.y*b.y) < 0.5)

  return (
    <div 
      className={hasCriticalThreat ? 'critical-alert' : ''}
      style={{
      background: '#0a120a',
      border: '1px solid #1a3320',
      gridColumn: '4 / 8',
      gridRow: '1',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      minHeight: 0,
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
        gap: 8,
      }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#00ff41', boxShadow: '0 0 6px #00ff41', display: 'inline-block' }} />
        RADAR · 5km RANGE · ACTIVE SWEEP
        {live && (
          <span style={{ marginLeft: 'auto', fontSize: '8px', color: az !== null ? '#00ff41' : '#2d4f32', letterSpacing: '1px' }}>
            {az !== null ? `BRG ${Math.round(az)}°` : 'NO FIX'}
          </span>
        )}
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '16px 12px 12px', minHeight: 0 }}>
        <div style={{ flex: 1, width: '100%', position: 'relative', minHeight: 0 }}>
          <svg viewBox="0 0 260 260" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', overflow: 'visible' }}>
            <defs>
              <radialGradient id="radarBg" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#003310" stopOpacity="0.6" />
                <stop offset="100%" stopColor="#000d04" stopOpacity="1" />
              </radialGradient>
              <radialGradient id="sweepGrad" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#00ff41" stopOpacity="0.3" />
                <stop offset="100%" stopColor="#00ff41" stopOpacity="0" />
              </radialGradient>
              <clipPath id="radarClip">
                <circle cx={cx} cy={cy} r={r} />
              </clipPath>
            </defs>

            {/* Background */}
            <circle cx={cx} cy={cy} r={r} fill="url(#radarBg)" />

            {/* Range rings */}
            {[0.25, 0.5, 0.75, 1].map((frac, i) => (
              <circle key={i} cx={cx} cy={cy} r={r * frac} fill="none" stroke="#00ff41" strokeWidth="0.5" opacity="0.15" />
            ))}

            {/* Cross hairs */}
            <line x1={cx - r} y1={cy} x2={cx + r} y2={cy} stroke="#00ff41" strokeWidth="0.5" opacity="0.15" />
            <line x1={cx} y1={cy - r} x2={cx} y2={cy + r} stroke="#00ff41" strokeWidth="0.5" opacity="0.15" />
            <line x1={cx - r * 0.707} y1={cy - r * 0.707} x2={cx + r * 0.707} y2={cy + r * 0.707} stroke="#00ff41" strokeWidth="0.4" opacity="0.08" />
            <line x1={cx + r * 0.707} y1={cy - r * 0.707} x2={cx - r * 0.707} y2={cy + r * 0.707} stroke="#00ff41" strokeWidth="0.4" opacity="0.08" />

            {/* Sweep trail */}
            <g clipPath="url(#radarClip)">
              <path
                d={`M ${cx} ${cy} L ${x2} ${y2} A ${r} ${r} 0 0 0 ${x1} ${y1} Z`}
                fill="#00ff41"
                opacity="0.12"
              />
            </g>

            {/* Sweep line */}
            <line
              x1={cx}
              y1={cy}
              x2={cx + Math.cos(sweep1) * r}
              y2={cy + Math.sin(sweep1) * r}
              stroke="#00ff41"
              strokeWidth="1.5"
              opacity="0.9"
              style={{ filter: 'drop-shadow(0 0 3px #00ff41)' }}
            />

            {/* Blips */}
            {activeBlips.map(b => {
              const pos = blipCoords(b)
              const opacity = live ? 1 : Math.max(0, 1 - b.age / b.maxAge)
              return (
                <g key={b.id}>
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={b.threat ? 4 : 3}
                    fill={b.threat ? '#ff3131' : '#00ff41'}
                    opacity={opacity}
                    style={{ filter: b.threat ? 'drop-shadow(0 0 4px #ff3131)' : 'drop-shadow(0 0 3px #00ff41)' }}
                  />
                  {b.threat && (
                    <circle
                      cx={pos.x}
                      cy={pos.y}
                      r={4 + (b.age % 60) * 0.15}
                      fill="none"
                      stroke="#ff3131"
                      strokeWidth="0.8"
                      opacity={opacity * 0.5}
                    />
                  )}
                </g>
              )
            })}

            {/* Outer border */}
            <circle cx={cx} cy={cy} r={r} fill="none" stroke="#00ff41" strokeWidth="1" opacity="0.4" />

            {/* Cardinal labels */}
            {[['N', 0, -r - 12], ['E', r + 12, 4], ['S', 0, r + 16], ['W', -r - 12, 4]].map(([label, dx, dy]) => (
              <text
                key={label as string}
                x={cx + (dx as number)}
                y={cy + (dy as number)}
                textAnchor="middle"
                fill="#00c832"
                fontSize="9"
                fontFamily="'JetBrains Mono', monospace"
                opacity="0.6"
              >
                {label}
              </text>
            ))}
          </svg>
        </div>

        {/* Range labels */}
        <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
          {['1.25km', '2.5km', '3.75km', '5km'].map(l => (
            <span key={l} style={{ fontSize: '8px', color: '#2d4f32', letterSpacing: '0.5px' }}>{l}</span>
          ))}
        </div>

        {/* Blip count */}
        <div style={{ marginTop: 8, display: 'flex', gap: 16, fontSize: '9px', letterSpacing: '1px' }}>
          <span style={{ color: '#00ff41' }}>● {activeBlips.filter(b => !b.threat).length} CONTACTS</span>
          <span style={{ color: '#ff3131' }}>● {activeBlips.filter(b => b.threat).length} THREATS</span>
        </div>
      </div>
    </div>
  )
}
