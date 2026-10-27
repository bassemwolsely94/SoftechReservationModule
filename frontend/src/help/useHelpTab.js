import { useEffect, useRef } from 'react'
import useHelpStore from './helpStore'

/**
 * useHelpTab(tab) — tell the help panel which tab this page is showing, so F1 / "؟"
 * opens the explanation of THAT tab. One line in any page with tabs:
 *
 *     const [tab, setTab] = useState('items')
 *     useHelpTab(tab)
 *
 * The value must match a tab `key` in the page's help (apps/help/content/<module>.py).
 * Pages that keep the tab in the URL (?tab=…) don't need this — the panel reads it.
 * Drawers / side panels with their own tabs can call it too: their tab wins while
 * they are open (their keys must also be listed in the page's help).
 */
let seq = 0

export default function useHelpTab(tab) {
  const report = useHelpStore((s) => s.reportTab)
  const id = useRef(null)
  if (id.current === null) id.current = ++seq
  useEffect(() => {
    report(id.current, tab ?? null)
  }, [tab, report])
  useEffect(() => () => report(id.current, null), [report])
}
