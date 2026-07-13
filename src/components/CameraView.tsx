import { useState, useEffect, useRef } from 'react'
import { useLive } from '../lib/SystemContext'
import { num } from '../lib/api'
import { useTarget } from '../lib/target'

const overlayLines = [
  { x1: '10%', y1: '10%', x2: '10%', y2: '16%' }, { x1: '10%', y1: '10%', x2: '16%', y2: '10%' },
  { x1: '90%', y1: '10%', x2: '84%', y2: '10%' }, { x1: '90%', y1: '10%', x2: '90%', y2: '16%' },
  { x1: '10%', y1: '90%', x2: '16%', y2: '90%' }, { x1: '10%', y1: '90%', x2: '10%', y2: '84%' },
  { x1: '90%', y1: '90%', x2: '84%', y2: '90%' }, { x1: '90%', y1: '90%', x2: '90%', y2: '84%' },
]

const FALLBACK_IMG = 'https://images.unsplash.com/photo-1508444845599-5c89863b1c44?w=900&h=500&fit=crop&auto=format'

type CamState = 'connecting' | 'live' | 'none'

export default function CameraView() {
  const { live, snapshot } = useLive()
  const target = useTarget()
  const videoRef = useRef<HTMLVideoElement>(null)

  const [crosshairX, setCrosshairX] = useState(38)
  const [crosshairY, setCrosshairY] = useState(45)
  const [simTracking, setSimTracking] = useState(false)
  const [showGrid, setShowGrid] = useState(true)
  const [cameraMode, setCameraMode] = useState<'NIGHT' | 'THERMAL' | 'NORMAL'>('NORMAL')

  const [cam, setCam] = useState<CamState>('connecting')
  const [camLabel, setCamLabel] = useState('SECTOR ALPHA')

  // Connect to a physically-attached camera. If one is present, its live video
  // fills the panel; otherwise we fall back to the stock surveillance still so
  // the console is never blank.
  useEffect(() => {
    let stream: MediaStream | null = null
    let cancelled = false

    const connect = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCam('none')
        return
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        if (cancelled) {
          stream.getTracks().forEach(t => t.stop())
          return
        }
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => {})
        }
        const label = stream.getVideoTracks()[0]?.label
        if (label) setCamLabel(label.replace(/\s*\(.*\)\s*$/, '').toUpperCase().slice(0, 22))
        setCam('live')
      } catch {
        if (!cancelled) setCam('none')
      }
    }
    connect()

    return () => {
      cancelled = true
      stream?.getTracks().forEach(t => t.stop())
    }
  }, [])

  // Real localization / vision readout when the backend is live.
  const fix = live && snapshot ? snapshot.fix : null
  const latestFeed = live && snapshot ? snapshot.feed[0] : undefined
  const visionConf = latestFeed ? num(latestFeed.visual_conf) : null
  const realLat = target.lat ?? (fix ? num(fix.lat) : null)
  const realLon = target.lon ?? (fix ? num(fix.lon) : null)
  const realThreat = live && snapshot ? snapshot.threat.level : null

  // Lock onto the configured target SSID whenever it's detected; otherwise fall
  // back to threat-driven / simulated tracking.
  const tracking = target.detected
    ? true
    : live
      ? realThreat === 'WARNING' || realThreat === 'CRITICAL' || (visionConf ?? 0) > 0
      : simTracking

  const getFilter = () => {
    switch (cameraMode) {
      case 'THERMAL': return 'invert(1) grayscale(100%) contrast(1.5) brightness(1.2)'
      case 'NIGHT': return 'grayscale(100%) brightness(0.55) sepia(1) hue-rotate(80deg) saturate(3)'
      case 'NORMAL': default: return 'contrast(1.05) brightness(1)'
    }
  }

  useEffect(() => {
    let t = 0
    const id = setInterval(() => {
      t += 0.015
      setCrosshairX(38 + Math.sin(t * 0.7) * 18)
      setCrosshairY(45 + Math.cos(t * 0.5) * 12)
    }, 60)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (live || target.detected) return
    const id = setInterval(() => setSimTracking(v => !v), 3200)
    return () => clearInterval(id)
  }, [live, target.detected])

  const camConnected = cam === 'live'

  return (
    <div
      style={{
        background: '#0a120a',
        border: `1px solid ${tracking ? '#3a1414' : '#1a3320'}`,
        gridColumn: '1 / 4',
        gridRow: '1',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Panel label */}
      <PanelLabel connected={camConnected}>
        CAM-01 · {camConnected ? camLabel : cam === 'connecting' ? 'CONNECTING…' : 'NO CAMERA · DEMO'} · LIVE FEED
      </PanelLabel>

      {/* Camera image — 80% of panel height */}
      <div style={{ position: 'relative', width: '100%', height: '80%', background: '#000' }}>
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            filter: getFilter(),
            display: camConnected ? 'block' : 'none',
          }}
        />
        {!camConnected && (
          <img
            src={FALLBACK_IMG}
            alt="Surveillance feed (no camera connected)"
            style={{ width: '100%', height: '100%', objectFit: 'cover', filter: getFilter(), display: 'block' }}
          />
        )}

        {/* Scan line */}
        <div
          className="scan-line"
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            height: '2px',
            background: 'linear-gradient(to right, transparent, rgba(0,255,65,0.3), transparent)',
            pointerEvents: 'none',
          }}
        />

        {/* SVG overlays */}
        <svg
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
        >
          {/* Corner brackets */}
          {overlayLines.map((l, i) => (
            <line key={i} {...l} stroke="#00ff41" strokeWidth="1.5" opacity="0.6" />
          ))}

          {/* Center crosshair */}
          <line x1="50%" y1="47%" x2="50%" y2="53%" stroke="#00ff41" strokeWidth="0.8" opacity="0.3" />
          <line x1="47%" y1="50%" x2="53%" y2="50%" stroke="#00ff41" strokeWidth="0.8" opacity="0.3" />

          {/* Tracking box — nested <svg> positions the group at a percentage of
              the viewport (SVG transform translate() does not accept % units). */}
          <svg x={`${crosshairX}%`} y={`${crosshairY}%`} overflow="visible" style={{ transition: 'x 0.06s linear, y 0.06s linear' }}>
            <rect x="-20" y="-14" width="40" height="28" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" fill="none" opacity="0.8" />
            <line x1="-24" y1="0" x2="-22" y2="0" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            <line x1="22" y1="0" x2="24" y2="0" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            <line x1="0" y1="-18" x2="0" y2="-16" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            <line x1="0" y1="16" x2="0" y2="18" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            {target.detected && (
              <text x="24" y="-16" fill="#ff3131" fontSize="9" fontFamily="'JetBrains Mono', monospace">{target.ssid}</text>
            )}
          </svg>

          {/* Grid overlay */}
          {showGrid && [1,2,3].map(i => (
            <line key={`hg-${i}`} x1="0" y1={`${i * 25}%`} x2="100%" y2={`${i * 25}%`} stroke="#00ff41" strokeWidth="0.3" opacity="0.1" />
          ))}
          {showGrid && [1,2,3].map(i => (
            <line key={`vg-${i}`} x1={`${i * 25}%`} y1="0" x2={`${i * 25}%`} y2="100%" stroke="#00ff41" strokeWidth="0.3" opacity="0.1" />
          ))}
        </svg>

        {/* HUD data overlay */}
        <div style={{ position: 'absolute', bottom: 8, left: 10, fontSize: '9px', color: '#00ff41', opacity: 0.7, letterSpacing: '1px', lineHeight: 1.8 }}>
          <div>VISION: {live ? (visionConf !== null ? `${visionConf.toFixed(0)}%` : '—') : '142m'}</div>
          <div>SRC: {camConnected ? 'CAM' : 'DEMO'}</div>
          <div>FPS: {camConnected ? 30 : 24}</div>
        </div>
        <div style={{ position: 'absolute', bottom: 8, right: 10, fontSize: '9px', color: '#00ff41', opacity: 0.7, letterSpacing: '1px', lineHeight: 1.8, textAlign: 'right' }}>
          <div>LAT: {realLat !== null ? `${realLat.toFixed(4)}°` : live ? '—' : '40.7128°N'}</div>
          <div>LON: {realLon !== null ? `${realLon.toFixed(4)}°` : live ? '—' : '74.0060°W'}</div>
          <div>{tracking ? <span style={{ color: '#ff3131' }}>{target.detected ? 'TARGET LOCK' : 'TRACKING'}</span> : 'SCANNING'}</div>
        </div>

        {/* REC indicator */}
        <div style={{ position: 'absolute', top: 8, right: 10, display: 'flex', alignItems: 'center', gap: 5, fontSize: '9px', color: '#ff3131', letterSpacing: '2px' }}>
          <span className="blink" style={{ width: 6, height: 6, borderRadius: '50%', background: '#ff3131', display: 'inline-block' }} />
          REC
        </div>
      </div>

      {/* Interactive Controls */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 12px' }}>
        <button
          onClick={() => setShowGrid(!showGrid)}
          style={{ background: 'transparent', border: '1px solid #1a3320', color: showGrid ? '#00ff41' : '#2d4f32', padding: '4px 8px', fontSize: '9px', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          GRID
        </button>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['NIGHT', 'THERMAL', 'NORMAL'] as const).map(mode => (
            <button
              key={mode}
              onClick={() => setCameraMode(mode)}
              style={{ background: cameraMode === mode ? '#1a3320' : 'transparent', border: '1px solid #1a3320', color: cameraMode === mode ? '#00ff41' : '#2d4f32', padding: '4px 8px', fontSize: '9px', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function PanelLabel({ children, connected }: { children: React.ReactNode; connected: boolean }) {
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
    }}>
      <span
        className={connected ? '' : 'blink'}
        style={{ width: 5, height: 5, borderRadius: '50%', background: connected ? '#00ff41' : '#ff8c00', boxShadow: `0 0 6px ${connected ? '#00ff41' : '#ff8c00'}`, display: 'inline-block' }}
      />
      {children}
    </div>
  )
}
