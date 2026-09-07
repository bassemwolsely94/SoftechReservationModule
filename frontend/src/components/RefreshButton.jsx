/**
 * RefreshButton.jsx
 *
 * Drop-in replacement for every تحديث button in the app.
 * When `loading` is true:
 *   • A spinning icon appears next to the label
 *   • An animated progress bar sweeps across the bottom of the button
 *   • The button is disabled (prevents double-clicks)
 *
 * Props
 * ──────
 *   loading   boolean  — true while the request is in-flight
 *   onClick   fn       — click handler
 *   variant   'primary' | 'secondary' | 'ghost'   (default: 'secondary')
 *   size      'sm' | 'md'                          (default: 'md')
 *   children  node     — button label
 *   className string   — extra Tailwind classes
 *   disabled  boolean  — extra disabled flag (merged with `loading`)
 *
 * Usage examples
 * ──────────────
 *   <RefreshButton loading={isFetching} onClick={() => refetch()}>تحديث</RefreshButton>
 *   <RefreshButton loading={loading} onClick={load} variant="ghost" size="sm">🔄 تحديث</RefreshButton>
 */
export default function RefreshButton({
  loading   = false,
  onClick,
  variant   = 'secondary',
  size      = 'md',
  children,
  className = '',
  disabled  = false,
  ...rest
}) {
  const base = {
    primary:   'btn-primary',
    secondary: 'btn-secondary',
    ghost:     'btn-ghost',
  }[variant] ?? 'btn-secondary'

  const sizeOverride = size === 'sm' ? '!text-xs !px-3 !py-1.5' : ''

  return (
    <button
      onClick={onClick}
      disabled={loading || disabled}
      className={`relative overflow-hidden ${base} ${sizeOverride} ${className}`}
      {...rest}
    >
      {/* Label + optional spinner */}
      <span className={`inline-flex items-center gap-1.5 ${loading ? 'opacity-75' : ''}`}>
        {loading && (
          <svg
            className="h-3.5 w-3.5 animate-spin shrink-0"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12" cy="12" r="10"
              stroke="currentColor" strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}
        {children}
      </span>

      {/* Sweeping progress bar at the bottom of the button */}
      {loading && (
        <span
          className="refresh-btn-bar"
          aria-hidden="true"
        />
      )}
    </button>
  )
}
