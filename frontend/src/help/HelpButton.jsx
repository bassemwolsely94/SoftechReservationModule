import useHelpStore from './helpStore'
import { useCurrentHelp } from './useHelpIndex'

/**
 * The "؟ مساعدة" button for the top bars. Shows a dot when this screen's help
 * changed since the user last read it. `variant="mobile"` = white-on-brand header.
 */
export default function HelpButton({ variant = 'desktop' }) {
  const toggle = useHelpStore((s) => s.toggle)
  const { screen, isNew } = useCurrentHelp()
  const title = 'مساعدة — شرح هذه الشاشة (F1)'

  if (variant === 'mobile') {
    return (
      <button type="button" onClick={toggle} title={title} aria-label={title}
              className="relative w-9 h-9 rounded-lg bg-white/15 active:bg-white/30 flex items-center justify-center font-bold text-base">
        ؟
        {screen && isNew && <span className="absolute -top-0.5 -end-0.5 w-2.5 h-2.5 rounded-full bg-amber-400 ring-2 ring-brand-600" />}
      </button>
    )
  }
  return (
    <button type="button" onClick={toggle} title={title} aria-label={title}
            className="relative flex items-center gap-1.5 text-xs text-faint hover:text-brand-600 bg-surface-2 hover:bg-brand-50 border border-line rounded-lg px-2.5 py-1.5 transition-colors">
      <span className="w-4 h-4 rounded-full border border-current flex items-center justify-center text-[10px] font-bold">؟</span>
      <span className="hidden md:inline">مساعدة</span>
      {screen && isNew && <span className="absolute -top-1 -end-1 w-2.5 h-2.5 rounded-full bg-amber-400 ring-2 ring-surface" title="شرح جديد" />}
    </button>
  )
}
