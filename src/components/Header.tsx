import { useState, useEffect } from 'react'

export default function Header() {
  const [time, setTime] = useState(new Date())

  // Telemetry state
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

  return (
    <header
      style={{
        background: '#0a130a',
        borderBottom: '1px solid #1a3320',
        fontFamily: "'JetBrains Mono', monospace",
      }}
      className="flex items-center justify-between px-5 py-2"
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
      <div className="flex items-center gap-4 flex-1 justify-center px-4">
        {/* Health */}
        <div className="flex gap-4 border-l border-r border-[#1a3320] px-4">
          <MiniStat label="TEMP" value={`${temp.toFixed(1)}°C`} color={temp > 45 ? '#ff8c00' : '#00ff41'} />
          <MiniStat label="HUM" value={`${humidity}%`} color="#00b4d8" />
          <MiniStat label="BAT" value={`${battery}%`} color={battery > 20 ? '#00ff41' : '#ff3131'} />
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
        <div className="flex items-center gap-4 border-r border-[#1a3320] pr-4">
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

      {/* Clock */}
      <div className="text-right shrink-0">
        <div style={{ color: '#00ff41', fontSize: '18px', fontWeight: 600, letterSpacing: '2px', fontFamily: "'JetBrains Mono', monospace" }}>{timeStr}</div>
        <div style={{ color: '#2d4f32', fontSize: '9px', letterSpacing: '1px' }}>{dateStr} · UTC</div>
      </div>
    </header>
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
