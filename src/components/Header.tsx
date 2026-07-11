import { useState, useEffect, useRef } from 'react'
import { useSystem } from '../lib/SystemContext'
import { LEVEL_COLOR, type Level } from '../lib/api'

export default function Header() {
  const { connected, snapshot, lastUpdate, land } = useSystem()

  const [time, setTime] = useState(new Date())

  // Hardware telemetry (simulated — the backend has no environmental sensors).
  const [temp, setTemp] = useState(42.1)
  const [humidity, setHumidity] = useState(31)
  const [battery, setBattery] = useState(98)
  const [voltage, setVoltage] = useState(12.4)
  const [servoAngle, setServoAngle] = useState(0)
  const [lidarDist, setLidarDist] = useState(12.4)
  const [tamper, setTamper] = useState(false)
  const [beamLights, setBeamLights] = useState(false)

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    let t = 0
    const id = setInterval(() => {
      t += 0.05
      setTemp(42.1 + Math.sin(t) * 0.5)
      setHumidity(h => Math.max(20, Math.min(60, h + (Math.random() - 0.5) * 0.6)))
      setVoltage(12.4 + Math.sin(t * 0.6) * 0.15)
      // Battery drains slowly, then "recharges" so the demo never flatlines.
      setBattery(b => (b <= 22 ? 98 : b - (Math.random() < 0.02 ? 1 : 0)))
      setServoAngle(90 + Math.sin(t * 1.2) * 90) // sweeps 0 to 180
      setLidarDist(Math.max(0.5, 12.4 + (Math.random() - 0.5) * 0.3))
      if (Math.random() < 0.01) {
        setTamper(true)
        setTimeout(() => setTamper(false), 2000)
      }
    }, 100)
    return () => clearInterval(id)
  }, [])

  const timeStr = time.toTimeString().slice(0, 8)
  const dateStr = time.toISOString().slice(0, 10)

  const level: Level | null = connected && snapshot ? snapshot.threat.level : null
  const score = connected && snapshot ? Math.round(snapshot.threat.score) : null

  return (
    <header
      style={{
        background: '#0a130a',
        borderBottom: '1px solid #1a3320',
        fontFamily: "'JetBrains Mono', monospace",
      }}
      className="flex items-center justify-between px-5 py-2 gap-4"
    >
      {/* Logo */}
      <div className="flex items-center gap-3 shrink-0">
        <svg width="32" height="32" viewBox="0 0 36 36" fill="none">
          <circle cx="18" cy="18" r="17" stroke="#00ff41" strokeWidth="1.5" opacity="0.4" />
          <circle cx="18" cy="18" r="11" stroke="#00ff41" strokeWidth="1.5" opacity="0.7" />
          <circle cx="18" cy="18" r="5" stroke="#00ff41" strokeWidth="1.5" />
          <line x1="18" y1="18" x2="18" y2="1" stroke="#00ff41" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="18" cy="7" r="1.5" fill="#00ff41" />
          <path d="M14 18h8M18 14v8M12 14l2 2M24 14l-2 2M12 22l2-2M24 22l-2-2" stroke="#00ff41" strokeWidth="1" strokeLinecap="round" opacity="0.6" />
        </svg>
        <div>
          <div style={{ fontFamily: "'Rajdhani', sans-serif", color: '#00ff41', fontSize: '18px', fontWeight: 700, letterSpacing: '3px', lineHeight: 1 }}>DRONEWATCH</div>
          <div style={{ color: '#2d4f32', fontSize: '8px', letterSpacing: '2px' }}>AERIAL THREAT DETECTION</div>
        </div>
      </div>

      {/* Hardware Telemetry Ticker */}
      <div className="flex items-center gap-4 flex-1 justify-center px-4 min-w-0 overflow-hidden">
        {/* Health */}
        <div className="flex gap-4 border-l border-r border-[#1a3320] px-4">
          <MiniStat label="TEMP" value={`${temp.toFixed(1)}°C`} color={temp > 45 ? '#ff8c00' : '#00ff41'} />
          <MiniStat label="HUM" value={`${Math.round(humidity)}%`} color="#00b4d8" />
          <MiniStat label="BAT" value={`${Math.round(battery)}%`} color={battery > 20 ? '#00ff41' : '#ff3131'} />
          <MiniStat label="VOLT" value={`${voltage.toFixed(1)}V`} color="#00ff41" />
        </div>

        {/* Antenna */}
        <div className="flex items-center gap-3 border-r border-[#1a3320] pr-4">
          <MiniStat label="YAGI SWEEP" value={`${Math.round(servoAngle)}°`} color="#00ff41" />
          <div style={{ width: 14, height: 14, borderRadius: '50%', border: '1px solid #00ff41', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
             <div style={{ position: 'absolute', width: 1, height: 7, background: '#00ff41', bottom: '50%', transformOrigin: 'bottom', transform: `rotate(${servoAngle - 90}deg)` }} />
          </div>
        </div>

        {/* Perimeter */}
        <div className="flex items-center gap-4 pr-1">
          <MiniStat label="LIDAR" value={`${lidarDist.toFixed(1)}m`} color={lidarDist < 2 ? '#ff3131' : '#00b4d8'} />
          <MiniStat label="GY-521" value={tamper ? 'WARN' : 'OK'} color={tamper ? '#ff3131' : '#00ff41'} blink={tamper} />

          {/* Actuator */}
          <div className="flex flex-col items-center gap-1 cursor-pointer" onClick={() => setBeamLights(!beamLights)}>
            <div style={{ color: '#2d4f32', fontSize: '7px', letterSpacing: '1px' }}>BEAM SSR</div>
            <div style={{
              color: beamLights ? '#000' : '#2d4f32',
              background: beamLights ? '#ff8c00' : 'transparent',
              border: `1px solid ${beamLights ? '#ff8c00' : '#1a3320'}`,
              fontSize: '9px', fontWeight: 700, padding: '1px 6px', borderRadius: 2
            }}>
              {beamLights ? 'ON' : 'OFF'}
            </div>
          </div>
        </div>
      </div>

      {/* Threat + operator controls */}
      <div className="flex items-center gap-3 shrink-0">
        <ThreatChip level={level} score={score} />
        <LandControl connected={connected} armed={!!snapshot?.armed} land={land} lastLand={snapshot?.last_land ?? null} />
        <ConnectionBadge connected={connected} lastUpdate={lastUpdate} />
      </div>

      {/* Clock */}
      <div className="text-right shrink-0">
        <div style={{ color: '#00ff41', fontSize: '18px', fontWeight: 600, letterSpacing: '2px', fontFamily: "'JetBrains Mono', monospace" }}>{timeStr}</div>
        <div style={{ color: '#2d4f32', fontSize: '9px', letterSpacing: '1px' }}>{dateStr} · UTC</div>
      </div>
    </header>
  )
}

function ThreatChip({ level, score }: { level: Level | null; score: number | null }) {
  const color = level ? LEVEL_COLOR[level] : '#2d4f32'
  const label = level ?? 'DEMO'
  return (
    <div
      className={level === 'CRITICAL' ? 'blink' : ''}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        border: `1px solid ${level ? color : '#1a3320'}`,
        borderRadius: 3,
        padding: '3px 10px',
        minWidth: 74,
        background: level ? `${color}18` : 'transparent',
      }}
      title="Current fused threat level from the backend"
    >
      <div style={{ color: '#2d4f32', fontSize: '7px', letterSpacing: '1px' }}>THREAT</div>
      <div style={{ color, fontSize: '13px', fontWeight: 700, letterSpacing: '1px', lineHeight: 1.1 }}>{label}</div>
      {score !== null && <div style={{ color: '#5a8a60', fontSize: '8px' }}>{score}/100</div>}
    </div>
  )
}

function ConnectionBadge({ connected, lastUpdate }: { connected: boolean; lastUpdate: number | null }) {
  const color = connected ? '#00ff41' : '#ff8c00'
  const ago = lastUpdate ? Math.max(0, Math.round((Date.now() - lastUpdate) / 1000)) : null
  return (
    <div className="flex flex-col items-center" title={connected ? 'Connected to CampusShield backend' : 'Backend offline — showing built-in simulation'}>
      <div className="flex items-center gap-1">
        <span className={connected ? '' : 'blink'} style={{ width: 6, height: 6, borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}`, display: 'inline-block' }} />
        <span style={{ color, fontSize: '10px', fontWeight: 700, letterSpacing: '1px' }}>{connected ? 'LIVE' : 'DEMO'}</span>
      </div>
      <div style={{ color: '#2d4f32', fontSize: '7px', letterSpacing: '0.5px' }}>
        {connected ? (ago !== null ? `sync ${ago}s` : 'linked') : 'no backend'}
      </div>
    </div>
  )
}

type LandState = { action: 'idle' | 'land' | 'none' | 'error'; detail: string } | null

function LandControl({
  connected,
  armed,
  land,
  lastLand,
}: {
  connected: boolean
  armed: boolean
  land: () => Promise<{ action: string; detail: string }>
  lastLand: LandState
}) {
  const [phase, setPhase] = useState<'idle' | 'armed' | 'sending'>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const disabled = !connected || !armed
  const onClick = async () => {
    if (disabled || phase === 'sending') return
    if (phase === 'idle') {
      setPhase('armed')
      timer.current = setTimeout(() => setPhase('idle'), 4000)
      return
    }
    // armed -> execute
    if (timer.current) clearTimeout(timer.current)
    setPhase('sending')
    try {
      await land()
    } finally {
      setPhase('idle')
    }
  }

  const label =
    phase === 'sending' ? 'SENDING…' : phase === 'armed' ? '⚠ CONFIRM LAND' : 'RF LAND'
  const color = disabled ? '#2d4f32' : phase === 'armed' ? '#ff8c00' : '#ff3131'

  const outcome = lastLand && lastLand.action !== 'idle' ? lastLand : null

  return (
    <div className="flex flex-col items-center gap-0.5">
      <button
        onClick={onClick}
        disabled={disabled}
        className={phase === 'armed' ? 'blink' : ''}
        title={
          !connected
            ? 'Requires the CampusShield backend (python -m ml.runtime.dashboard)'
            : !armed
              ? 'No target link configured (set PLUTO_SSID on the backend)'
              : 'Own-drone LAND only — allow-list gated, never jams third-party aircraft'
        }
        style={{
          background: disabled ? 'transparent' : `${color}1a`,
          border: `1px solid ${disabled ? '#1a3320' : color}`,
          color,
          padding: '5px 12px',
          fontSize: '10px',
          fontWeight: 700,
          letterSpacing: '1.5px',
          cursor: disabled ? 'not-allowed' : phase === 'sending' ? 'progress' : 'pointer',
          fontFamily: 'inherit',
          borderRadius: 3,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </button>
      <div
        style={{
          fontSize: '7px',
          letterSpacing: '0.5px',
          color: outcome?.action === 'land' ? '#00ff41' : outcome?.action === 'error' ? '#ff3131' : '#2d4f32',
          maxWidth: 150,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={outcome?.detail || ''}
      >
        {outcome ? outcome.detail : 'own-drone land-only'}
      </div>
    </div>
  )
}

function MiniStat({ label, value, color, blink }: { label: string; value: string; color: string; blink?: boolean }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <div style={{ color: '#2d4f32', fontSize: '7px', letterSpacing: '1px' }}>{label}</div>
      <div style={{ color, fontSize: '12px', fontWeight: 700, lineHeight: 1 }} className={blink ? 'blink' : ''}>{value}</div>
    </div>
  )
}
