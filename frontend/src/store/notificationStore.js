/**
 * notificationStore.js
 *
 * Holds per-module unread counts for notifications that are intentionally kept
 * OUT of the global bell (demand, followups). Powers:
 *   - the tiny unread hint on the sidebar nav items (Layout)
 *   - the in-module notification panels
 *
 * The global NotificationBell hook keeps this in sync (WS + periodic refresh);
 * in-module panels call refresh() after marking their feed read.
 */
import { create } from 'zustand'
import { notificationsApi } from '../api/client'

// Quiet categories kept OUT of the main bell — each has its own UI surface:
// demand/followups (sidebar hint + module bell), monitoring (📡), settings (⚙️),
// reports (📊 periodic digests), mentions (💬 personal @-mentions).
const MODULE_CATEGORIES = ['demand', 'followups', 'monitoring', 'settings', 'reports', 'mentions']

const ALL_CATEGORIES = ['global', 'demand', 'followups', 'delivery', 'transfers',
  'reservations', 'monitoring', 'settings', 'reports', 'mentions']

const useNotificationStore = create((set) => ({
  // Unread counts for the quiet categories (kept out of the main bell).
  moduleCounts: { demand: 0, followups: 0, monitoring: 0, settings: 0, reports: 0, mentions: 0 },
  // Notifier categories this user's role may see (per-role visibility). Default:
  // all visible until the first category-counts reconcile narrows it.
  visible: new Set(ALL_CATEGORIES),

  setModuleCounts: (counts) =>
    set({ moduleCounts: Object.fromEntries(MODULE_CATEGORIES.map(c => [c, counts[c] ?? 0])) }),

  // Optimistic local bump (used on WS arrival before the next reconcile).
  bumpCategory: (category, delta = 1) =>
    set((s) => {
      if (!(category in s.moduleCounts)) return s
      return {
        moduleCounts: {
          ...s.moduleCounts,
          [category]: Math.max(0, s.moduleCounts[category] + delta),
        },
      }
    }),

  // Authoritative reconcile from the server (single call, all categories).
  refresh: async () => {
    try {
      const { data } = await notificationsApi.categoryCounts()
      set({
        moduleCounts: Object.fromEntries(MODULE_CATEGORIES.map(c => [c, data[c] ?? 0])),
        visible: new Set(Array.isArray(data.visible) ? data.visible : ALL_CATEGORIES),
      })
    } catch { /* silent */ }
  },
}))

export default useNotificationStore
