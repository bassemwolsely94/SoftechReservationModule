/**
 * useThemeMode — personal light/dark/system preference hook.
 *
 * Reads the per-device mode from localStorage (via theme.js), applies it to
 * <html data-theme>, and keeps 'system' live against the OS preference. Mode is
 * intentionally client-only — it never touches the global server brand theme.
 *
 *   const { mode, resolvedMode, setMode, cycle } = useThemeMode()
 *   mode         → 'light' | 'dark' | 'system'  (the stored choice)
 *   resolvedMode → 'light' | 'dark'             (what's actually rendered)
 */
import { useCallback, useEffect, useState } from 'react'
import {
  applyMode, cacheMode, loadCachedMode, resolveMode, watchSystemMode,
} from './theme'

const ORDER = ['light', 'dark', 'system']

export function useThemeMode() {
  const [mode, setModeState]         = useState(() => loadCachedMode())
  const [resolvedMode, setResolved]  = useState(() => resolveMode())

  // Apply on mount + whenever the stored choice changes, and follow the OS while
  // in 'system'. watchSystemMode re-applies data-theme; we mirror it into state.
  useEffect(() => {
    applyMode(mode)
    setResolved(resolveMode(mode))
    const stop = watchSystemMode()
    const onSys = () => setResolved(resolveMode())
    let mql
    try {
      mql = window.matchMedia('(prefers-color-scheme: dark)')
      mql.addEventListener?.('change', onSys)
    } catch { /* noop */ }
    return () => { stop(); mql?.removeEventListener?.('change', onSys) }
  }, [mode])

  const setMode = useCallback((next) => {
    cacheMode(next)
    applyMode(next)
    setModeState(next)
    setResolved(resolveMode(next))
  }, [])

  const cycle = useCallback(() => {
    setMode(ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length])
  }, [mode, setMode])

  return { mode, resolvedMode, setMode, cycle }
}
