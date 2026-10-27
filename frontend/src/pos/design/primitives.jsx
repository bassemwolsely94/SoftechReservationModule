/**
 * POS design-system primitives — the shared visual vocabulary (owner brainstorm §70). Every POS
 * surface composes THESE instead of inventing badges/cards/states, so the interface reads the same
 * everywhere and we never duplicate UI. All are theme-aware (semantic tokens) and tiny/composable.
 *
 * Empty state → reuse ui.jsx `EmptyState`. Order/reservation status → reuse `StatusBadge`.
 * This file adds the pharmacy-semantic layer (stock, batch, cold-chain, offer, actions, metrics…).
 */
import { Icon } from './icons'
import { tone as toneOf, meaning as meaningOf, stockMeaning } from './semantics'

const SIZE = { xs: 'text-[9px] px-1 py-0 gap-0.5', sm: 'text-[10px] px-1.5 py-0.5 gap-1', md: 'text-xs px-2 py-1 gap-1' }

/** Base semantic chip. Pass a `meaning` key (auto icon+label+tone) OR explicit tone/icon/label. */
export function Badge({ meaning, tone, icon, label, children, size = 'sm', variant = 'soft', className = '', title }) {
  const m = meaning ? meaningOf(meaning) : null
  const t = toneOf(tone || m?.tone)
  const ic = icon ?? m?.icon
  const body = children ?? label ?? m?.label
  const skin = variant === 'solid' ? t.solid : `${t.badge} border`
  return (
    <span title={title} className={`inline-flex items-center rounded ${SIZE[size]} ${skin} ${className}`}>
      {ic && <Icon name={ic} size={size === 'xs' ? 10 : 12} />}
      {body != null && <span className="whitespace-nowrap">{body}</span>}
    </span>
  )
}

/** Stock level as a colored chip (🟢/🟡/🔴 semantics). qty=null → nothing. */
export function StockBadge({ qty, low = 3, size = 'sm', showLabel = true, className = '' }) {
  const key = stockMeaning(qty, low)
  if (key == null) return null
  const label = key === 'oos' ? 'لا رصيد' : `متاح ${qty}`
  return <Badge meaning={key} label={showLabel ? label : String(qty)} size={size} className={className} />
}

/** One branch's availability pill: 🟢 Nozha 12. */
export function BranchStockPill({ name, qty, low = 3, size = 'sm', onClick, className = '' }) {
  const t = toneOf(stockMeaning(qty, low) || 'neutral')
  const El = onClick ? 'button' : 'span'
  return (
    <El type={onClick ? 'button' : undefined} onClick={onClick}
        className={`inline-flex items-center rounded-full border ${SIZE[size]} ${t.badge} ${onClick ? 'hover:brightness-95 cursor-pointer' : ''} ${className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} />
      <span className="font-medium whitespace-nowrap">{name}</span>
      <span className="tabnum font-bold">{qty}</span>
    </El>
  )
}

export const ColdChainBadge = (p) => <Badge meaning="cold" size={p?.size || 'xs'} {...p} />
export const BatchBadge     = (p) => <Badge meaning="batch" size={p?.size || 'xs'} {...p} />
export const OfferBadge     = (p) => <Badge meaning="offer" size={p?.size || 'xs'} {...p} />
export const BundleBadge    = (p) => <Badge meaning="bundle" size={p?.size || 'xs'} {...p} />
export const LoyaltyBadge   = ({ tier, points, size = 'sm', ...p }) =>
  <Badge meaning="loyalty" size={size} label={`${tier || 'ولاء'}${points != null ? ` · ${points}` : ''}`} {...p} />

const SEV_TO_MEANING = { block: 'blocked', warn: 'pharmacist', info: 'rx' }
/** Backend-owned safety flag → semantic badge (rules 4/7: we only render the decision). */
export function SafetyBadge({ flag, size = 'xs' }) {
  const t = toneOf(SEV_TO_MEANING[flag?.severity] ? meaningOf(SEV_TO_MEANING[flag.severity]).tone : 'info')
  const ic = flag?.severity === 'block' ? 'block' : flag?.severity === 'warn' ? 'alert' : 'info'
  return (
    <span className={`inline-flex items-center rounded border ${SIZE[size]} ${t.badge}`}>
      <Icon name={ic} size={10} />{flag?.label_ar || flag?.label}
    </span>
  )
}

/** Contextual action (owner brainstorm §5): only the relevant ones are rendered by the caller.
 * `prominent` bumps it to a filled brand button. */
export function ActionTile({ icon, label, onClick, prominent = false, disabled = false, tone, title, className = '' }) {
  const t = tone ? toneOf(tone) : null
  const skin = prominent ? 'bg-brand-600 text-white hover:bg-brand-700'
    : t ? `${t.badge} border hover:brightness-95`
    : 'bg-surface border border-line text-content hover:bg-surface-2'
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title || label}
            className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition
              disabled:opacity-40 disabled:cursor-not-allowed ${skin} ${className}`}>
      {icon && <Icon name={icon} size={13} />}{label}
    </button>
  )
}

/** Adaptive workflow step (owner §34): state = done | current | todo | error. */
export function WorkflowStep({ icon, label, state = 'todo', onClick, last = false }) {
  const map = {
    done:    { ring: 'bg-emerald-600 text-white', txt: 'text-emerald-700', line: 'bg-emerald-300' },
    current: { ring: 'bg-brand-600 text-white ring-2 ring-brand-200', txt: 'text-brand-700 font-semibold', line: 'bg-line' },
    error:   { ring: 'bg-red-600 text-white', txt: 'text-red-700 font-semibold', line: 'bg-line' },
    todo:    { ring: 'bg-surface-2 text-faint border border-line', txt: 'text-faint', line: 'bg-line' },
  }[state] || {}
  return (
    <div className="flex items-center gap-1 shrink-0">
      <button type="button" onClick={onClick} className="flex items-center gap-1.5">
        <span className={`w-6 h-6 rounded-full flex items-center justify-center ${map.ring}`}>
          {state === 'done' ? <Icon name="check" size={13} /> : icon ? <Icon name={icon} size={13} /> : null}
        </span>
        <span className={`text-[11px] ${map.txt}`}>{label}</span>
      </button>
      {!last && <span className={`w-5 h-0.5 rounded ${map.line}`} />}
    </div>
  )
}

/** Compact KPI/metric chip with optional trend (owner §46). */
export function MetricChip({ icon, label, value, trend, tone, className = '' }) {
  const t = tone ? toneOf(tone) : null
  return (
    <div className={`inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1 ${className}`}>
      {icon && <Icon name={icon} size={13} className="text-muted" />}
      <span className="text-[10px] text-faint">{label}</span>
      <span className={`text-xs font-bold tabnum ${t?.text || 'text-content'}`}>{value}</span>
      {trend != null && (
        <span className={`text-[10px] tabnum ${trend >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
          {trend >= 0 ? '▲' : '▼'}{Math.abs(trend)}%
        </span>
      )}
    </div>
  )
}

/** A subtle inline suggestion (NOT a popup) — Next-Best-Action / offer-completion / refill (§6,13,14). */
export function SmartSuggestionCard({ icon = 'star', tone = 'promo', title, detail, actionLabel, onAction, onDismiss }) {
  const t = toneOf(tone)
  return (
    <div className={`flex items-center gap-2 rounded-lg border ${t.badge} px-2.5 py-1.5`}>
      <Icon name={icon} size={16} />
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold leading-tight truncate">{title}</div>
        {detail && <div className="text-[10px] opacity-80 leading-tight truncate">{detail}</div>}
      </div>
      {actionLabel && <ActionTile label={actionLabel} onClick={onAction} prominent />}
      {onDismiss && <button onClick={onDismiss} className="text-current opacity-50 hover:opacity-100"><Icon name="x" size={12} /></button>}
    </div>
  )
}

/** Actionable error state (owner §7) — one clear cause + one action, never a raw validation string. */
export function ErrorState({ icon = 'alert', title, detail, actionLabel, onAction, tone = 'warn' }) {
  const t = toneOf(tone)
  return (
    <div className={`rounded-lg border ${t.badge} p-3 flex items-start gap-2`}>
      <Icon name={icon} size={18} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{title}</div>
        {detail && <div className="text-xs opacity-80 mt-0.5">{detail}</div>}
      </div>
      {actionLabel && <ActionTile label={actionLabel} onClick={onAction} prominent />}
    </div>
  )
}

export function SuccessState({ title, detail, children }) {
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 p-3 flex items-start gap-2">
      <Icon name="check" size={18} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{title}</div>
        {detail && <div className="text-xs opacity-80 mt-0.5">{detail}</div>}
        {children}
      </div>
    </div>
  )
}

/** Sticky bottom action bar for the transaction (owner §32 checkout summary / §70). */
export function BottomActionBar({ children, className = '' }) {
  return (
    <div className={`sticky bottom-0 inset-x-0 bg-surface/95 backdrop-blur border-t border-line px-3 py-2 flex items-center gap-2 ${className}`}>
      {children}
    </div>
  )
}
