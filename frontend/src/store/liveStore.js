/**
 * liveStore.js — live events from the notification WebSocket (performance Stage 5).
 *
 * The bell hook (useNotificationSocket) owns the one socket. It records here whether the socket is
 * up, and turns each server `freshness_changed` event (a sync run / lane finished; domain keys +
 * time only) into `freshnessChanged(domains)`. Screens that used to poll every 60–90 s subscribe
 * with useOnFreshnessChange and refetch only when their domains changed; while the socket is down
 * they fall back to a slow poll (pollWhileSocketDown).
 *
 * Plan: docs/superpowers/plans/2026-11-19-perf-stage5-live-updates.md
 */
import { useEffect, useRef } from 'react'
import { create } from 'zustand'

// Spread 40 tabs' refetches over a few seconds instead of hitting the server in the same instant.
export const FRESHNESS_JITTER_MS = 4000
// Poll used only while the socket is down (it used to be the normal 60 s poll).
export const FALLBACK_POLL_MS = 5 * 60_000
// Long safety net while the socket is up: covers domains that announce nothing (snapshots).
export const SAFETY_POLL_MS = 15 * 60_000
// The main SOFTECH sync lanes — what the sync-status chip and the dashboard's sync block follow.
export const MAIN_SYNC_DOMAINS = ['stock', 'sales', 'branches', 'catalog', 'customers', 'users']

const useLiveStore = create((set) => ({
  socketUp: false,
  freshness: { seq: 0, domains: [] },
  setSocketUp: (up) => set({ socketUp: !!up }),
  freshnessChanged: (domains) => set((s) => ({
    freshness: { seq: s.freshness.seq + 1, domains: Array.isArray(domains) ? domains.map(String) : [] },
  })),
}))

/** refetchInterval for a screen that refetches on events: slow while the socket is up, fallback when down. */
export function pollWhileSocketDown(socketUp, downMs = FALLBACK_POLL_MS, upMs = SAFETY_POLL_MS) {
  return socketUp ? upMs : downMs
}

/** Does an event about `changed` domains concern a screen that shows `wanted`? (no list = everything) */
export function touches(changed, wanted) {
  if (!wanted || !wanted.length) return true
  return (changed || []).some((d) => wanted.includes(d))
}

/** Call `callback` each time the server says one of `domains` has new freshness. */
export function useOnFreshnessChange(callback, domains) {
  const cbRef = useRef(callback)
  const wantedRef = useRef(domains)
  cbRef.current = callback
  wantedRef.current = domains
  useEffect(() => useLiveStore.subscribe((state, prev) => {
    if (state.freshness.seq === prev.freshness.seq) return
    if (touches(state.freshness.domains, wantedRef.current)) cbRef.current()
  }), [])
}

export default useLiveStore
