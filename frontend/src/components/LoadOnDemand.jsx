import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'

// Full audit FE-19: shell pieces that open on demand (the Ctrl+K palette, the Customer-360 and
// drug-assistant drawers) are not in the entry bundle. Until first use this renders nothing and
// only listens for what opens the piece; then it loads the code, mounts it, and replays the event
// that triggered it — so the very first Ctrl+K / «customer360:open» still opens it, just as
// before. After that the piece's own listeners take over.
//
//   <LoadOnDemand load={() => import('./CommandPalette')} events={['palette:open']}
//                 keys={e => (e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')} />

function replay(ev) {
  if (ev.type === 'keydown') {
    const { key, code, ctrlKey, metaKey, shiftKey, altKey } = ev
    window.dispatchEvent(new KeyboardEvent('keydown', { key, code, ctrlKey, metaKey, shiftKey, altKey, bubbles: true, cancelable: true }))
  } else {
    window.dispatchEvent(new CustomEvent(ev.type, { detail: ev.detail }))
  }
}

// Mounted right after the loaded piece in the same commit: React runs the piece's effects (its
// listeners) first, then this one, so the replayed event reaches them.
function AfterMount({ onMount }) {
  useEffect(() => { onMount() }, [onMount])
  return null
}

export default function LoadOnDemand({ load, events = [], keys = null, ...props }) {
  const Piece = useMemo(() => lazy(load), [load])
  const [wanted, setWanted] = useState(false)
  const pendingEvent = useRef(null)
  const eventsKey = events.join('|')

  useEffect(() => {
    if (wanted) return undefined
    const trigger = (e) => {
      if (pendingEvent.current) return
      if (e.type === 'keydown') {
        if (!keys || !keys(e)) return
        e.preventDefault()                                // e.g. the browser's own Ctrl+K
      }
      pendingEvent.current = { type: e.type, detail: e.detail, key: e.key, code: e.code,
        ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, altKey: e.altKey }
      setWanted(true)
    }
    const names = eventsKey ? eventsKey.split('|') : []
    names.forEach(n => window.addEventListener(n, trigger))
    if (keys) window.addEventListener('keydown', trigger)
    return () => {
      names.forEach(n => window.removeEventListener(n, trigger))
      if (keys) window.removeEventListener('keydown', trigger)
    }
  }, [wanted, eventsKey, keys])

  const mounted = useMemo(() => () => {
    const ev = pendingEvent.current
    pendingEvent.current = null
    if (ev) replay(ev)
  }, [])

  if (!wanted) return null
  return (
    <Suspense fallback={null}>
      <Piece {...props} />
      <AfterMount onMount={mounted} />
    </Suspense>
  )
}
