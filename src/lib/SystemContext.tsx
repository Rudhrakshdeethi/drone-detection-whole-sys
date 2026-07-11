import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { getStatus, postLand, type LastLand, type Snapshot } from './api'

// Shared system state, polled once for the whole app and handed to every panel.
//
// `connected` is the single source of truth for LIVE vs DEMO: when the Python
// backend answers, panels bind to `snapshot`; when it doesn't, each panel keeps
// its own built-in simulation. Panels never fetch on their own.

interface SystemState {
  snapshot: Snapshot | null
  connected: boolean
  /** True until the first poll settles, so panels can avoid a DEMO flash. */
  loading: boolean
  /** ISO-ish time of the last successful poll, for the header readout. */
  lastUpdate: number | null
  land: () => Promise<LastLand>
}

const SystemCtx = createContext<SystemState | null>(null)

const POLL_MS = 1500

export function SystemProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<number | null>(null)
  // Tolerate a single dropped poll before flipping to DEMO — avoids the UI
  // flickering between LIVE/DEMO on a momentary network blip.
  const missesRef = useRef(0)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>

    const tick = async () => {
      try {
        const s = await getStatus()
        if (!alive) return
        missesRef.current = 0
        setSnapshot(s)
        setConnected(true)
        setLastUpdate(Date.now())
      } catch {
        if (!alive) return
        missesRef.current += 1
        if (missesRef.current >= 2) setConnected(false)
      } finally {
        if (alive) {
          setLoading(false)
          timer = setTimeout(tick, POLL_MS)
        }
      }
    }

    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [])

  const land = async () => {
    const result = await postLand()
    // Fold the outcome straight back into the snapshot so the whole UI reacts
    // without waiting for the next poll.
    setSnapshot(prev => (prev ? { ...prev, last_land: result } : prev))
    return result
  }

  return (
    <SystemCtx.Provider value={{ snapshot, connected, loading, lastUpdate, land }}>
      {children}
    </SystemCtx.Provider>
  )
}

export function useSystem(): SystemState {
  const ctx = useContext(SystemCtx)
  if (!ctx) throw new Error('useSystem must be used within a SystemProvider')
  return ctx
}

/** True only when we have a live backend AND a snapshot to render. */
export function useLive(): { live: boolean; snapshot: Snapshot | null } {
  const { connected, snapshot } = useSystem()
  return { live: connected && snapshot !== null, snapshot }
}
