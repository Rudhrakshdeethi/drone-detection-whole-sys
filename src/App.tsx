import Header from './components/Header'
import CameraView from './components/CameraView'
import Radar from './components/Radar'
import MapView from './components/MapView'
import SignalStrength from './components/SignalStrength'
import LiveLog from './components/LiveLog'
import PreviousLogs from './components/PreviousLogs'

export default function App() {
  return (
    <div style={{
      height: '100vh',
      overflow: 'hidden',
      background: '#070c07',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <Header />
      <main style={{
        flex: 1,
        minHeight: 0,
        display: 'grid',
        gridTemplateColumns: 'repeat(10, 1fr)',
        gridTemplateRows: 'minmax(0, 1.05fr) minmax(0, 1fr) minmax(0, 0.75fr)',
        gap: '12px',
        padding: '12px',
        overflow: 'hidden',
      }}>
        <CameraView />
        <Radar />
        <SignalStrength />
        <MapView />
        <LiveLog />
        <PreviousLogs />
      </main>
    </div>
  )
}
