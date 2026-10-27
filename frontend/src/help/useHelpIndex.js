import { useMemo } from 'react'
import { matchPath, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useHelpStore from './helpStore'

/** The help index (modules + screens + routes). Small, cached for the session. */
export function useHelpIndex() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return useQuery({
    queryKey: ['help', 'index'],
    queryFn: () => helpApi.index().then((r) => r.data),
    staleTime: 10 * 60_000,
    enabled: !!isAuthenticated,
  })
}

/** Most specific route wins: static segments beat :params, longer beats shorter. */
function routeScore(pattern) {
  const parts = pattern.split('/').filter(Boolean)
  return parts.reduce((n, p) => n + (p.startsWith(':') ? 1 : 3), 0)
}

export function findScreen(index, pathname) {
  if (!index) return null
  let best = null
  let bestScore = -1
  for (const s of index.screens) {
    for (const r of s.routes) {
      if (matchPath({ path: r, end: true }, pathname)) {
        const sc = routeScore(r)
        if (sc > bestScore) { best = s; bestScore = sc }
      }
    }
  }
  return best
}

/**
 * The help for what the user is looking at: { index, screen, tab, isNew }.
 * Tab = what the page reported (useHelpTab) → else ?tab= in the URL.
 */
export function useCurrentHelp() {
  const { data: index } = useHelpIndex()
  const location = useLocation()
  const reportedTab = useHelpStore((s) => s.tab)
  const seen = useHelpStore((s) => s.seen)

  return useMemo(() => {
    const screen = findScreen(index, location.pathname)
    const urlTab = new URLSearchParams(location.search).get('tab')
    const tab = reportedTab || urlTab || null
    const isNew = !!(screen && screen.updated && seen[screen.key] !== screen.updated)
    return { index, screen, tab, isNew }
  }, [index, location.pathname, location.search, reportedTab, seen])
}
