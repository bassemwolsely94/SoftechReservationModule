/**
 * helpStore — state of the in-app help panel (دليل الاستخدام).
 *
 *   open / toggle / close   — the side panel (F1, the header "؟" button, or
 *                             window event 'help:open' with { detail: { key, tab } })
 *   tabs / tab              — the tab(s) the current page is showing, reported by
 *                             useHelpTab(tab). A stack: a drawer's tabs sit on top of
 *                             the page's tabs; the innermost one wins, and closing the
 *                             drawer falls back to the page tab.
 *   lang                    — help reading language; independent of the UI language
 *   tour                    — a running «اعرض لي» tour: { key, steps, i } (not persisted)
 *   seen                    — screen key → 'updated' date the user last read, for the
 *                             "new" dot (per browser; a convenience, not a record)
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const useHelpStore = create(
  persist(
    (set, get) => ({
      isOpen: false,
      forcedKey: null,      // a specific screen (from search / related links) instead of the page's own
      forcedTab: null,
      tabs: [],             // [{ id, tab }] — registration order, innermost last
      tab: null,
      lang: null,           // null → follow the UI language
      seen: {},
      tour: null,

      startTour(key, steps) { if (steps?.length) set({ tour: { key, steps, i: 0 }, isOpen: false }) },
      tourStep(i) { const t = get().tour; if (t) set({ tour: { ...t, i: Math.max(0, Math.min(i, t.steps.length - 1)) } }) },
      endTour() { set({ tour: null }) },
      open(key = null, tab = null) { set({ isOpen: true, forcedKey: key, forcedTab: tab }) },
      close() { set({ isOpen: false, forcedKey: null, forcedTab: null }) },
      toggle() { get().isOpen ? get().close() : get().open() },
      reportTab(id, tab) {
        // keep each reporter's place in the stack (a page changing its tab must not
        // jump above an open drawer); new reporters go on top
        const cur = get().tabs
        const tabs = tab == null
          ? cur.filter((t) => t.id !== id)
          : cur.some((t) => t.id === id)
            ? cur.map((t) => (t.id === id ? { id, tab } : t))
            : [...cur, { id, tab }]
        set({ tabs, tab: tabs.length ? tabs[tabs.length - 1].tab : null })
      },
      setLang(lang) { set({ lang }) },
      markSeen(key, updated) {
        if (!key || !updated || get().seen[key] === updated) return
        set({ seen: { ...get().seen, [key]: updated } })
      },
    }),
    {
      name: 'elrezeiky-help',
      version: 1,
      partialize: (s) => ({ lang: s.lang, seen: s.seen }),
    }
  )
)

export default useHelpStore
