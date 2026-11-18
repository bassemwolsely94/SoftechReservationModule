/**
 * ItemSearchHotkeyProvider — the single Ctrl+F1 owner for a page.
 *
 * Every ItemSearchWidget registers here (useItemSearchRegistration). One
 * window keydown listener opens the advanced-search modal of the widget that
 * was focused last; else the first enabled widget with a mounted input, in DOM
 * order; else the first enabled widget. With no enabled widget it does nothing
 * and does not preventDefault.
 * Plain F1 / Shift+F1 / Alt+F1 belong to HelpPanel and are ignored here.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from 'react'

const Ctx = createContext(null)

export default function ItemSearchHotkeyProvider({ children }) {
  const entries = useRef(new Map())   // id -> { open, disabled, inputRef }
  const lastFocused = useRef(null)
  const seq = useRef(0)

  const register = useCallback((entry) => {
    const id = ++seq.current
    entries.current.set(id, entry)
    return id
  }, [])
  const unregister = useCallback((id) => {
    entries.current.delete(id)
    if (lastFocused.current === id) lastFocused.current = null
  }, [])

  useEffect(() => {
    function onFocusIn(e) {
      for (const [id, en] of entries.current) {
        const el = en.inputRef?.current
        if (el && (el === e.target || el.contains(e.target))) { lastFocused.current = id; return }
      }
    }
    function onKey(e) {
      if (!(e.ctrlKey && !e.shiftKey && !e.altKey && e.key === 'F1')) return
      if (!entries.current.size) return
      const enabled = [...entries.current.entries()].filter(([, en]) => !en.disabled)
      if (!enabled.length) return            // all disabled: swallow nothing
      e.preventDefault()
      let pick = enabled.find(([id]) => id === lastFocused.current)
      if (!pick) {
        // Prefer widgets with a mounted input, in DOM order; else first enabled.
        const withInput = enabled.filter(([, en]) => en.inputRef?.current)
        withInput.sort(([, a], [, b]) =>
          a.inputRef.current.compareDocumentPosition(b.inputRef.current) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1)
        pick = withInput[0] || enabled[0]
      }
      pick[1].open()
    }
    document.addEventListener('focusin', onFocusIn)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('focusin', onFocusIn)
      window.removeEventListener('keydown', onKey)
    }
  }, [])

  const value = useMemo(() => ({ register, unregister }), [register, unregister])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Register a widget. Outside a provider this is a no-op (nothing crashes). */
export function useItemSearchRegistration({ open, disabled, inputRef }) {
  const ctx = useContext(Ctx)
  const live = useRef({})
  live.current = { open, disabled, inputRef }
  useEffect(() => {
    if (!ctx) return undefined
    // Entry reads the latest props through a stable proxy.
    const id = ctx.register({
      open: () => live.current.open(),
      get disabled() { return live.current.disabled },
      get inputRef() { return live.current.inputRef },
    })
    return () => ctx.unregister(id)
  }, [ctx])
}
