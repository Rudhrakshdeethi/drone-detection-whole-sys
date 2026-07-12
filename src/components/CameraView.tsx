import { useState, useEffect } from 'react'

const overlayLines = [
  { x1: '10%', y1: '10%', x2: '10%', y2: '16%' }, { x1: '10%', y1: '10%', x2: '16%', y2: '10%' },
  { x1: '90%', y1: '10%', x2: '84%', y2: '10%' }, { x1: '90%', y1: '10%', x2: '90%', y2: '16%' },
  { x1: '10%', y1: '90%', x2: '16%', y2: '90%' }, { x1: '10%', y1: '90%', x2: '10%', y2: '84%' },
  { x1: '90%', y1: '90%', x2: '84%', y2: '90%' }, { x1: '90%', y1: '90%', x2: '90%', y2: '84%' },
]

export default function CameraView() {
  const [crosshairX, setCrosshairX] = useState(38)
  const [crosshairY, setCrosshairY] = useState(45)
  const [tracking, setTracking] = useState(false)
  const [showGrid, setShowGrid] = useState(true)
  const [cameraMode, setCameraMode] = useState<'NIGHT' | 'THERMAL' | 'NORMAL'>('NIGHT')

  const getFilter = () => {
    switch (cameraMode) {
      case 'THERMAL': return 'invert(1) grayscale(100%) contrast(1.5) brightness(1.2)'
      case 'NORMAL': return 'contrast(1.1) brightness(0.9)'
      case 'NIGHT': default: return 'grayscale(100%) brightness(0.55) sepia(1) hue-rotate(80deg) saturate(3)'
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
    const id = setInterval(() => setTracking(v => !v), 3200)
    return () => clearInterval(id)
  }, [])

  return (
    <div
      style={{
        background: '#0a120a',
        border: '1px solid #1a3320',
        gridColumn: '1 / 4',
        gridRow: '1',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Panel label */}
      <PanelLabel>CAM-01 · SECTOR ALPHA · LIVE FEED</PanelLabel>

      {/* Camera image — 80% of panel height */}
      <div style={{ position: 'relative', width: '100%', height: '80%' }}>
        <img
          src="https://images.unsplash.com/photo-1508444845599-5c89863b1c44?w=900&h=500&fit=crop&auto=format"
          alt="Live aerial surveillance feed"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            filter: getFilter(),
            display: 'block',
          }}
        />

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

          {/* Tracking box */}
          <g transform={`translate(${crosshairX}%, ${crosshairY}%)`}>
            <rect x="-20" y="-14" width="40" height="28" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" fill="none" opacity="0.8" />
            <line x1="-24" y1="0" x2="-22" y2="0" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            <line x1="22" y1="0" x2="24" y2="0" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            <line x1="0" y1="-18" x2="0" y2="-16" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
            <line x1="0" y1="16" x2="0" y2="18" stroke={tracking ? '#ff3131' : '#00ff41'} strokeWidth="1" opacity="0.8" />
          </g>

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
          <div>ALT: 142m</div>
          <div>ZOOM: 4.2x</div>
          <div>FPS: 30</div>
        </div>
        <div style={{ position: 'absolute', bottom: 8, right: 10, fontSize: '9px', color: '#00ff41', opacity: 0.7, letterSpacing: '1px', lineHeight: 1.8, textAlign: 'right' }}>
          <div>LAT: 40.7128°N</div>
          <div>LON: 74.0060°W</div>
          <div>{tracking ? <span style={{ color: '#ff3131' }}>TRACKING</span> : 'SCANNING'}</div>
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
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#00ff41', boxShadow: '0 0 6px #00ff41', display: 'inline-block' }} />
      {children}
    </div>
  )
}
