// perf Stage 5 — live events from the notification socket replace the always-on polls.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

vi.mock('../api/client', () => ({ notificationsApi: { categoryCounts: vi.fn() } }))

const { default: useLiveStore, pollWhileSocketDown, touches, useOnFreshnessChange,
  FALLBACK_POLL_MS, SAFETY_POLL_MS } = await import('./liveStore')
const { default: useNotificationStore } = await import('./notificationStore')
const { QUERY_DEFAULTS } = await import('../api/queryDefaults')

afterEach(() => useLiveStore.setState({ socketUp: false, freshness: { seq: 0, domains: [] } }))

describe('liveStore', () => {
  it('polls slowly only while the socket is down', () => {
    expect(pollWhileSocketDown(false)).toBe(FALLBACK_POLL_MS)
    expect(pollWhileSocketDown(true)).toBe(SAFETY_POLL_MS)
    expect(FALLBACK_POLL_MS).toBeGreaterThanOrEqual(5 * 60_000)
  })

  it('matches events to the domains a screen shows', () => {
    expect(touches(['stock', 'sales'], ['sales'])).toBe(true)
    expect(touches(['calls'], ['stock', 'sales'])).toBe(false)
    expect(touches(['calls'], undefined)).toBe(true)
  })

  it('calls back once per event that concerns the screen', () => {
    const cb = vi.fn()
    renderHook(() => useOnFreshnessChange(cb, ['stock']))
    act(() => useLiveStore.getState().freshnessChanged(['calls']))
    expect(cb).not.toHaveBeenCalled()
    act(() => useLiveStore.getState().freshnessChanged(['stock', 'sales']))
    act(() => useLiveStore.getState().freshnessChanged(['stock']))
    expect(cb).toHaveBeenCalledTimes(2)
  })

  it('stops listening on unmount', () => {
    const cb = vi.fn()
    const { unmount } = renderHook(() => useOnFreshnessChange(cb))
    unmount()
    act(() => useLiveStore.getState().freshnessChanged(['stock']))
    expect(cb).not.toHaveBeenCalled()
  })
})

describe('notificationStore.applyCounts (pushed category_counts)', () => {
  it('takes the quiet-feed counts and visibility from the event', () => {
    useNotificationStore.getState().applyCounts({ event: 'category_counts', bell: 3, demand: 2,
      mentions: 1, visible: ['global', 'demand', 'mentions'] })
    const s = useNotificationStore.getState()
    expect(s.moduleCounts.demand).toBe(2)
    expect(s.moduleCounts.mentions).toBe(1)
    expect(s.moduleCounts.followups).toBe(0)
    expect(s.visible.has('reports')).toBe(false)
  })

  it('ignores an empty payload', () => {
    const before = useNotificationStore.getState().moduleCounts
    useNotificationStore.getState().applyCounts(null)
    expect(useNotificationStore.getState().moduleCounts).toBe(before)
  })
})

// ── Polling guard: the always-on polls must not come back ──────────────────────────────────────
const SRC = join(process.cwd(), 'src')
const read = (p) => readFileSync(join(SRC, p), 'utf8')
function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(jsx?|tsx?)$/.test(name) && !/\.test\./.test(name)) out.push(p)
  }
  return out
}

describe('polling guard (perf Stage 5)', () => {
  it('no screen refetches in a hidden tab', () => {
    expect(QUERY_DEFAULTS.refetchIntervalInBackground).toBe(false)
    const offenders = walk(SRC).filter(p => /refetchIntervalInBackground\s*:\s*true/.test(readFileSync(p, 'utf8')))
      .map(p => relative(SRC, p))
    expect(offenders).toEqual([])
  })

  it('the bell has no reconcile timer and a slow fallback', () => {
    const src = read('hooks/useNotificationSocket.js')
    expect(src).not.toMatch(/REFRESH_INTERVAL/)
    expect(src).toMatch(/FALLBACK_POLL_INTERVAL = 120_000/)
  })

  it('freshness bar, sync chip and dashboard follow the freshness event', () => {
    for (const f of ['components/DataFreshnessBar.jsx', 'components/Layout.jsx', 'pages/DashboardPage.jsx']) {
      expect(read(f), f).toMatch(/useOnFreshnessChange\(/)
    }
    expect(read('pages/DashboardPage.jsx')).not.toMatch(/refetchInterval:\s*90_000/)
    expect(read('components/Layout.jsx')).not.toMatch(/queryKey: \['syncStatus'\][^}]*refetchInterval: 60_000/s)
  })

  it('the call pop-up is event-driven, never a 6 s poll', () => {
    const src = read('components/CallPopBanner.jsx')
    expect(src).not.toMatch(/setInterval\(poll,\s*6000\)/)
    expect(src).toMatch(/subscribePbxEvents\(/)
  })
})
