type Detection = {
  id: string
  drone: string
  time: string
  date: string
  duration: string
  coords: string
  freq: string
  threat: 'HIGH' | 'MED' | 'LOW'
  status: 'RESOLVED' | 'ONGOING' | 'ESCAPED'
}

const previousDetections: Detection[] = [
  {
    id: 'EVT-0047',
    drone: 'DJI Mavic 3 Enterprise',
    time: '14:22:08',
    date: '2026-07-10',
    duration: '4m 32s',
    coords: '40.7142°N 74.0059°W',
    freq: '5.8 GHz',
    threat: 'HIGH',
    status: 'RESOLVED',
  },
  {
    id: 'EVT-0046',
    drone: 'Autel EVO II',
    time: '11:05:44',
    date: '2026-07-10',
    duration: '1m 58s',
    coords: '40.7138°N 74.0067°W',
    freq: '2.4 GHz',
    threat: 'MED',
    status: 'RESOLVED',
  },
  {
    id: 'EVT-0045',
    drone: 'Unknown — Spoofed SSID',
    time: '22:41:19',
    date: '2026-07-09',
    duration: '9m 11s',
    coords: '40.7166°N 74.0031°W',
    freq: '5.1 GHz',
    threat: 'HIGH',
    status: 'ESCAPED',
  },
  {
    id: 'EVT-0044',
    drone: 'Phantom 4 RTK',
    time: '16:18:33',
    date: '2026-07-09',
    duration: '2m 45s',
    coords: '40.7131°N 74.0071°W',
    freq: '2.4 GHz',
    threat: 'MED',
    status: 'RESOLVED',
  },
  {
    id: 'EVT-0043',
    drone: 'DJI Mini 3 Pro',
    time: '08:03:12',
    date: '2026-07-08',
    duration: '0m 47s',
    coords: '40.7155°N 74.0044°W',
    freq: '2.4 GHz',
    threat: 'LOW',
    status: 'RESOLVED',
  },
]

const threatColors = { HIGH: '#ff3131', MED: '#ff8c00', LOW: '#00ff41' }
const statusColors = { RESOLVED: '#00ff41', ONGOING: '#ff8c00', ESCAPED: '#ff3131' }
const statusBg = { RESOLVED: '#003310', ONGOING: '#1a0e00', ESCAPED: '#1a0000' }

export default function PreviousLogs() {
  const handleExportCSV = () => {
    const header = "ID,Drone,Date,Time,Duration,Coords,Freq,Threat,Status\n"
    const rows = previousDetections.map(d => 
      `${d.id},"${d.drone}",${d.date},${d.time},${d.duration},"${d.coords}",${d.freq},${d.threat},${d.status}`
    ).join("\n")
    const blob = new Blob([header + rows], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'detection_history.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

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
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#00ff41', boxShadow: '0 0 6px #00ff41', display: 'inline-block' }} />
          DETECTION HISTORY
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: '8px', color: '#2d4f32' }}>{previousDetections.length} RECORDS</span>
          <button 
            onClick={handleExportCSV}
            style={{ background: 'transparent', border: '1px solid #1a3320', color: '#00ff41', padding: '2px 6px', fontSize: '8px', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            EXPORT CSV
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {previousDetections.map((d, i) => (
          <div
            key={d.id}
            style={{
              padding: '8px 12px',
              borderBottom: '1px solid #0f1f0f',
              background: i % 2 === 0 ? 'transparent' : '#0b150b',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: '8px', color: '#2d4f32', letterSpacing: '1px' }}>{d.id}</span>
                <span style={{
                  fontSize: '7px',
                  padding: '1px 4px',
                  background: `${threatColors[d.threat]}22`,
                  color: threatColors[d.threat],
                  borderRadius: 2,
                  letterSpacing: '1px',
                  fontWeight: 700,
                }}>
                  {d.threat}
                </span>
              </div>
              <span style={{
                fontSize: '7px',
                padding: '1px 5px',
                background: statusBg[d.status],
                color: statusColors[d.status],
                borderRadius: 2,
                letterSpacing: '1px',
              }}>
                {d.status}
              </span>
            </div>

            <div style={{ fontSize: '10px', color: '#8ab890', letterSpacing: '0.3px', marginBottom: 3 }}>
              {d.drone}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1px 12px' }}>
              <Detail label="DATE" value={d.date} />
              <Detail label="TIME" value={d.time} />
              <Detail label="DURATION" value={d.duration} />
              <Detail label="FREQ" value={d.freq} />
              <Detail label="COORDS" value={d.coords} span />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Detail({ label, value, span }: { label: string; value: string; span?: boolean }) {
  return (
    <div style={{ gridColumn: span ? '1 / -1' : undefined }}>
      <span style={{ fontSize: '7px', color: '#2d4f32', letterSpacing: '1px' }}>{label}: </span>
      <span style={{ fontSize: '8px', color: '#5a8a60' }}>{value}</span>
    </div>
  )
}
