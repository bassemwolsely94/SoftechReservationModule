import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { auditApi } from '../api/client'
import useHelpStore from '../help/helpStore'

/**
 * useScreenUsage() — P-57 screen-usage telemetry. Called once in Layout and in
 * MobileLayout. On every route / tab change it posts the PATH (the server turns
 * ids into ":id" and drops the query string) and the page's useHelpTab value.
 * The same route + tab inside 30 s is not re-sent; a failure is silent and never
 * blocks the screen.
 */
const DEBOUNCE_MS = 30_000
const lastSent = new Map()

export default function useScreenUsage() {
  const { pathname } = useLocation()
  const tab = useHelpStore((s) => s.tab)
  useEffect(() => {
    const key = `${pathname}|${tab || ''}`
    const now = Date.now()
    if (now - (lastSent.get(key) || 0) < DEBOUNCE_MS) return
    lastSent.set(key, now)
    auditApi.screenView({ route: pathname, tab: tab || '' }).catch(() => {})
  }, [pathname, tab])
}
