/**
 * ThemeToggle — one-tap light ⇄ dark ⇄ system cycle for the app chrome.
 *
 * Personal, per-device (localStorage) — see src/theme/useThemeMode. Shows the
 * icon of the CURRENT choice; the title names what a click switches to next.
 */
import { useThemeMode } from '../theme/useThemeMode'

const NEXT_LABEL = {
  light:  'التبديل إلى الوضع الداكن',   // → dark
  dark:   'التبديل إلى وضع النظام',      // → system
  system: 'التبديل إلى الوضع الفاتح',   // → light
}

function SunIcon(props)  { return (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} {...props}>
    <circle cx="12" cy="12" r="4" />
    <path strokeLinecap="round" d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
) }
function MoonIcon(props) { return (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} {...props}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </svg>
) }
function SystemIcon(props) { return (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} {...props}>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path strokeLinecap="round" d="M8 20h8m-4-4v4" />
  </svg>
) }

const ICON = { light: SunIcon, dark: MoonIcon, system: SystemIcon }

export default function ThemeToggle({ className = '' }) {
  const { mode, cycle } = useThemeMode()
  const Icon = ICON[mode] || SystemIcon
  return (
    <button
      type="button"
      onClick={cycle}
      title={NEXT_LABEL[mode]}
      aria-label={NEXT_LABEL[mode]}
      className={`text-faint hover:text-brand-600 transition-colors p-1 rounded-lg hover:bg-brand-50 ${className}`}
    >
      <Icon className="w-4 h-4" />
    </button>
  )
}
