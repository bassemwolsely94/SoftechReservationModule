/**
 * <ProgressBar pct={45} label="مزامنة من SOFTECH" message="سحب أرصدة الفروع…" elapsed={32} />
 * A slim loading bar for long jobs (syncs, engine runs, SOFTECH reads). `pct` null/undefined
 * → indeterminate sweep (the job doesn't report how far it is). Reuses the
 * `refresh-sweep` keyframes from index.css. `since` (Date.now() when the wait began) makes
 * the bar count the elapsed time itself, for waits the server doesn't report on.
 */
import { useEffect, useState } from 'react'

function fmtElapsed(s) {
  if (s == null) return ''
  return s < 60 ? `${s} ث` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} د`
}

export default function ProgressBar({ pct, label, message, elapsed, since, className = '' }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since == null) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [since])
  if (elapsed == null && since != null) elapsed = Math.max(0, Math.round((now - since) / 1000))
  const known = typeof pct === 'number' && Number.isFinite(pct)
  const w = known ? Math.max(3, Math.min(100, pct)) : null
  return (
    <div className={`space-y-1 ${className}`} role="progressbar"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(pct) : undefined}
      aria-label={label}>
      {(label || message) && (
        <div className="flex items-center gap-2 text-[11px] text-content/70">
          {label && <span className="font-medium text-content">{label}</span>}
          {message && <span className="truncate">{message}</span>}
          <span className="ms-auto tabular-nums text-content/50">
            {known ? `${Math.round(pct)}%` : ''}{known && elapsed != null ? ' · ' : ''}{fmtElapsed(elapsed)}
          </span>
        </div>
      )}
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-primary/15">
        {known
          ? <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${w}%` }} />
          : <div className="absolute top-0 h-full rounded-full bg-primary"
              style={{ animation: 'refresh-sweep 1.1s ease-in-out infinite' }} />}
      </div>
    </div>
  )
}
