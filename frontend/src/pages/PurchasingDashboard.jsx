/**
 * pages/PurchasingDashboard.jsx
 *
 * Purchasing Optimization Engine — main dashboard.
 *
 * Tabs:
 *   📦 الشبكة (ABC)  — Cross-branch aggregated view with ABC Pareto table
 *   🏭 بالفرع        — Per-branch breakdown with needs-purchase filter
 *
 * Features:
 *   • Summary cards (A/B/C item counts, total gap value, coverage health)
 *   • ABC tab strips (A / B / C / X / كل الأصناف)
 *   • Sortable, searchable table
 *   • Live "needs purchase" toggle
 *   • Admin trigger button to kick off a fresh engine run
 *   • Last-run status badge
 */
import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { purchasingApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── Column-resize hook ────────────────────────────────────────────────────────
// useColWidths(defaults: number[]) → [widths, onResizeStart(e, colIndex)]
function useColWidths(defaults) {
  const [widths, setWidths] = useState(defaults)
  const dragRef = useRef(null)

  const onResizeStart = useCallback((e, ci) => {
    e.preventDefault()
    e.stopPropagation()
    dragRef.current = { ci, startX: e.clientX, startW: widths[ci] }

    const onMove = ev => {
      if (!dragRef.current) return
      const { ci: idx, startX, startW } = dragRef.current
      const newW = Math.max(60, startW + ev.clientX - startX)
      setWidths(prev => { const next = [...prev]; next[idx] = newW; return next })
    }
    const onUp = () => {
      dragRef.current = null
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [widths])

  return [widths, onResizeStart]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt  = (n, d = 1) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: d })
const fmtP = (n)        => Number(n || 0).toFixed(1) + '%'

const ABC_LABELS = { A: 'أ', B: 'ب', C: 'ج', X: 'بلا مبيعات' }
const ABC_COLORS = {
  A: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
  B: 'bg-blue-100   text-blue-800    ring-blue-300',
  C: 'bg-amber-100  text-amber-700   ring-amber-300',
  X: 'bg-gray-100   text-gray-500    ring-gray-200',
}

const STOCK_COLORS = {
  نفد:    'bg-red-100    text-red-700    ring-red-200',
  حرج:   'bg-orange-100 text-orange-700 ring-orange-200',
  منخفض: 'bg-yellow-100 text-yellow-700 ring-yellow-200',
  مقبول: 'bg-blue-100   text-blue-700   ring-blue-200',
  جيد:   'bg-green-100  text-green-700  ring-green-200',
}

function AbcBadge({ cls }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold ring-1 ${ABC_COLORS[cls] || ABC_COLORS.X}`}>
      {cls}
    </span>
  )
}

/**
 * MarginCell — color-coded margin badge.
 * Thresholds (standard pharmacy gross margins):
 *   ≥ 40%  → green   (healthy margin)
 *   20-39% → amber   (moderate — typical branded drugs)
 *   < 20%  → red     (tight margin)
 *   null   → gray "—"
 */
function MarginCell({ pct, title }) {
  if (pct == null) {
    return <span className="text-gray-300 text-xs">—</span>
  }
  const color = pct >= 40
    ? 'text-green-700 bg-green-50'
    : pct >= 20
      ? 'text-amber-700 bg-amber-50'
      : 'text-red-700 bg-red-50'
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold ${color}`}
      title={title}
    >
      {pct.toFixed(1)}%
    </span>
  )
}

function StockBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ring-1 ${STOCK_COLORS[status] || 'bg-gray-100 text-gray-500'}`}>
      {status}
    </span>
  )
}

function SummaryCard({ label, value, sub, color = 'brand' }) {
  const colors = {
    brand:  'bg-brand-50   border-brand-100  text-brand-700',
    green:  'bg-green-50   border-green-100  text-green-700',
    amber:  'bg-amber-50   border-amber-100  text-amber-700',
    red:    'bg-red-50     border-red-100    text-red-700',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="text-xs font-medium opacity-70">{label}</div>
      <div className="text-2xl font-black mt-1">{value}</div>
      {sub && <div className="text-xs opacity-60 mt-0.5">{sub}</div>}
    </div>
  )
}

// ── Run status header ─────────────────────────────────────────────────────────
//
//   run         = latest SUCCESSFUL run — drives the table data shown on screen.
//   lastAttempt = most recent run of ANY status — lets us warn when a newer run
//                 failed/was partial while the displayed data is still the older
//                 successful one.
//
// Three distinct signals, kept visually separate:
//   • RUN outcome + real run timestamp (date AND time it executed).
//   • DATA source (SOFTECH live vs PG cached) — a data-source note, NOT a failure.
//   • A red warning chip when a later attempt failed / did not finish cleanly.

const _fmtDateTime = (dt) =>
  dt
    ? new Date(dt).toLocaleString('en-GB', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false,
      })
    : '—'

const _fmtDate = (dt) =>
  dt ? new Date(dt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '—'

function RunStatusBadge({ run, lastAttempt }) {
  if (!run) return null

  // When did the displayed (successful) run actually execute?
  const ranAt = _fmtDateTime(run.finished_at || run.started_at)
  const secs  = run.duration_seconds != null ? ` · ${Math.round(run.duration_seconds)}ث` : ''

  // Data source is separate from run success.
  const src = run.softech_available
    ? { icon: '🟢', label: 'SOFTECH مباشر', cls: 'bg-green-50 text-green-700 ring-green-200' }
    : { icon: '💾', label: 'بيانات مخزّنة (PG)', cls: 'bg-amber-50 text-amber-700 ring-amber-200' }

  // Did a NEWER attempt fail / not finish cleanly while we still show the old data?
  const failedLater =
    lastAttempt &&
    lastAttempt.id !== run.id &&
    ['failed', 'partial', 'running'].includes(lastAttempt.status) &&
    new Date(lastAttempt.started_at) > new Date(run.started_at)

  const failInfo = failedLater
    ? {
        running: { icon: '⏳', text: 'تشغيل جارٍ الآن' },
        partial: { icon: '⚠',  text: `تشغيل ${_fmtDateTime(lastAttempt.finished_at || lastAttempt.started_at)} اكتمل جزئياً` },
        failed:  { icon: '⛔', text: `فشل تشغيل ${_fmtDateTime(lastAttempt.finished_at || lastAttempt.started_at)}` },
      }[lastAttempt.status]
    : null

  // Sales-data horizon: the latest sale the engine actually saw. Warn when it
  // lags the run — recommendations computed on stale sales are unreliable.
  let saleInfo = null
  if (run.data_through_date) {
    const dt   = new Date(run.data_through_date)
    const ref  = new Date(run.finished_at || run.started_at || Date.now())
    const days = Math.max(0, Math.floor((ref - dt) / 86_400_000))
    const cls  = days <= 2 ? 'bg-gray-50 text-gray-500 ring-gray-200'
               : days <= 7 ? 'bg-amber-100 text-amber-800 ring-amber-300'
               :             'bg-red-100 text-red-700 ring-red-300'
    saleInfo = { days, cls, warn: days > 2, date: _fmtDate(run.data_through_date) }
  }

  return (
    <div className="flex items-center gap-2 flex-wrap justify-end">
      {/* Run outcome + real timestamp */}
      <div
        className="text-xs px-3 py-1 rounded-full font-medium bg-green-100 text-green-700 ring-1 ring-green-200"
        title={`آخر تشغيل ناجح · بيانات حتى ${_fmtDate(run.calc_date)}`}
      >
        ✅ آخر تشغيل ناجح: {ranAt}{secs}
      </div>

      {/* Data source (SOFTECH vs cached) */}
      <div className={`text-xs px-2.5 py-1 rounded-full font-medium ring-1 ${src.cls}`}>
        {src.icon} المصدر: {src.label}
      </div>

      {/* Sales-data horizon + staleness warning */}
      {saleInfo ? (
        <div
          className={`text-xs px-2.5 py-1 rounded-full font-semibold ring-1 ${saleInfo.cls}`}
          title={`أحدث تاريخ مبيعات في البيانات المُستخدمة. المبيعات يجب أن تُزامَن ثم يُعاد تشغيل المحرك.`}
        >
          {saleInfo.warn ? '⚠' : '📅'} المبيعات حتى {saleInfo.date}
          {saleInfo.warn && ` — متأخرة ${saleInfo.days} يوم`}
        </div>
      ) : (
        <div className="text-xs px-2.5 py-1 rounded-full font-medium bg-gray-50 text-gray-500 ring-1 ring-gray-200">
          📅 بيانات حتى {_fmtDate(run.calc_date)}
        </div>
      )}

      {/* Warning: a newer run failed / is still running */}
      {failInfo && (
        <div
          className={`text-xs px-3 py-1 rounded-full font-semibold ring-1 ${
            lastAttempt.status === 'running'
              ? 'bg-blue-100 text-blue-700 ring-blue-200 animate-pulse'
              : lastAttempt.status === 'partial'
                ? 'bg-amber-100 text-amber-800 ring-amber-300'
                : 'bg-red-100 text-red-700 ring-red-300'
          }`}
          title={lastAttempt.error_message || ''}
        >
          {failInfo.icon} {failInfo.text}
        </div>
      )}
    </div>
  )
}

// ── Engine Run Progress Banner ────────────────────────────────────────────────
//
// Shown whenever there is an active (running) DemandCalculationRun.
// Polls the /runs/active/ endpoint and derives phase from mid-run fields:
//   Phase 1  rows_synced == 0              → SOFTECH sync in progress
//   Phase 2  rows_synced > 0, rows_written == 0 → calculation in progress
//   Phase 3  rows_written > 0              → persist + transfer recs
//
// Progress %  is time-based with an estimated ceiling per lookback window:
//   full (365d) ≈ 8 min  |  mid (~30–60d) ≈ 90 s  |  quick (<30d) ≈ 40 s
// Caps at 95 % until the run actually completes.

function EngineRunProgress({ run }) {
  const [elapsed, setElapsed] = useState(0)

  // Tick elapsed seconds from started_at
  useEffect(() => {
    if (!run?.started_at) return
    const start = new Date(run.started_at).getTime()
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [run?.started_at])

  if (!run) return null

  const lookback    = run.sync_lookback_days || 3
  const isFullSync  = lookback >= 300
  const estimatedS  = isFullSync ? 480 : lookback >= 30 ? 90 : 40

  const rowsSynced  = run.rows_synced  || 0
  const rowsWritten = run.rows_written || 0

  // Catch-up backfill phase: server reports real chunk-based % on run.progress,
  // shown as a determinate bar BEFORE the engine's own sync/calc phases begin.
  const bf         = run.progress || {}
  const isBackfill = bf.phase === 'backfill'

  const pct = isBackfill
    ? Math.min(Math.max(bf.pct || 0, 1), 99)
    : Math.min(Math.round(elapsed / estimatedS * 100), 95)

  // Phase indicator (backfill = phase 0, precedes sync)
  const phase = isBackfill ? 0 : rowsWritten > 0 ? 3 : rowsSynced > 0 ? 2 : 1
  const phaseLabel = isBackfill
    ? (bf.message || 'تعويض المبيعات المتأخرة على دفعات...')
    : phase === 1
      ? (isFullSync ? 'مزامنة SOFTECH (365 يوم) — قد تستغرق 5 – 8 دقائق...' : 'مزامنة البيانات من SOFTECH...')
      : phase === 2
        ? `حساب المعدلات والتصنيف لـ ${rowsSynced.toLocaleString('en-US')} صف...`
        : `حفظ ${rowsWritten.toLocaleString('en-US')} صف وتوليد توصيات التحويل...`

  const mins = Math.floor(elapsed / 60)
  const secs = String(elapsed % 60).padStart(2, '0')
  const elapsedStr = elapsed >= 60 ? `${mins}:${secs} دقيقة` : `${elapsed} ثانية`

  // Step dots: filled=done, pulsing=current, empty=future
  const steps = [
    { label: 'تعويض',  done: phase > 0, active: isBackfill },
    { label: 'مزامنة',  done: phase > 1, active: phase === 1 },
    { label: 'حساب',    done: phase > 2, active: phase === 2 },
    { label: 'حفظ',     done: false,     active: phase === 3 },
  ]

  return (
    <div className="bg-slate-900 text-white px-5 py-3 border-b border-slate-700" dir="rtl">
      <div className="flex items-center justify-between gap-4 mb-2 flex-wrap">

        {/* Left: pulse dot + title + full-sync badge */}
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500" />
          </span>
          <span className="text-sm font-bold text-white">
            {isBackfill ? '⟳ مزامنة التعويض' : '⚡ المحرك يعمل'}
          </span>
          {isBackfill && (
            <span className="text-[11px] bg-cyan-700 text-cyan-100 px-2 py-0.5 rounded-full font-semibold">
              تعويض المبيعات المتأخرة
            </span>
          )}
          {!isBackfill && isFullSync && (
            <span className="text-[11px] bg-blue-700 text-blue-200 px-2 py-0.5 rounded-full font-semibold">
              مزامنة كاملة 365 يوم
            </span>
          )}
        </div>

        {/* Right: step trail + elapsed */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-2">
            {steps.map((s, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${
                  s.done   ? 'bg-green-400' :
                  s.active ? 'bg-blue-400 animate-pulse' :
                             'bg-slate-600'
                }`} />
                <span className={s.done ? 'text-green-400' : s.active ? 'text-blue-300' : 'text-slate-500'}>
                  {s.label}
                </span>
                {i < steps.length - 1 && <span className="text-slate-600 mx-0.5">›</span>}
              </span>
            ))}
          </div>
          <span className="text-slate-400 tabular-nums">منذ {elapsedStr}</span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden my-1.5">
        <div
          className="h-full rounded-full bg-gradient-to-l from-cyan-400 to-blue-500 transition-all duration-1000 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Phase description + live counters */}
      <div className="flex items-center justify-between gap-2 mt-1">
        <p className="text-xs text-slate-400">{phaseLabel}</p>
        <div className="flex gap-3 text-[11px] text-slate-500 tabular-nums">
          {rowsSynced > 0 && (
            <span className="text-slate-400">
              <span className="text-slate-300 font-semibold">{rowsSynced.toLocaleString('en-US')}</span> صف مُزامَن
            </span>
          )}
          {rowsWritten > 0 && (
            <span className="text-slate-400">
              <span className="text-slate-300 font-semibold">{rowsWritten.toLocaleString('en-US')}</span> صف مُحسوب
            </span>
          )}
          <span>{pct}%</span>
        </div>
      </div>
    </div>
  )
}

// ── Aggregated (ABC) Tab ──────────────────────────────────────────────────────

// Default widths: [item_name, code, ABC, avg/mo, stock, gap, val/mo, m%, n%, cum%, branches]
const AGG_WIDTHS_DEFAULT = [260, 90, 70, 100, 100, 100, 140, 90, 90, 90, 100]

function AggregatedTab({ abcFilter, search, ordering, onSort, runId, itemFilters = {} }) {
  const [colW, onResizeStart] = useColWidths(AGG_WIDTHS_DEFAULT)

  const advParams = buildAdvParams(itemFilters)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['purchasing-agg', runId, abcFilter, search, ordering, itemFilters],
    queryFn: () => purchasingApi.aggregated({
      abc_class: abcFilter !== 'all' ? abcFilter : undefined,
      search:    search || undefined,
      ordering,
      page_size: 200,
      ...advParams,
    }).then(r => r.data.results || r.data),
    staleTime: 5 * 60_000,
    keepPreviousData: true,
    enabled: !!runId,
  })

  if (isLoading) return <TableSkeleton />

  const rows = data || []
  const totalW = colW.reduce((a, b) => a + b, 0)

  return (
    <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: 'calc(100vh - 360px)', minHeight: '280px' }}>
      {isFetching && (
        <div className="text-xs text-gray-400 px-4 py-1 animate-pulse">جارٍ التحديث...</div>
      )}
      <table style={{ tableLayout: 'fixed', width: totalW, borderCollapse: 'collapse' }} className="text-sm">
        <thead>
          <tr className="text-gray-500 text-xs font-bold">
            <SortTh label="الصنف"           field="item__name"           current={ordering} onSort={onSort}              width={colW[0]}  onResizeStart={e => onResizeStart(e, 0)} />
            <SortTh label="كود"             field="item__softech_id"     current={ordering} onSort={onSort}              width={colW[1]}  onResizeStart={e => onResizeStart(e, 1)} />
            <PlainTh align="center"                                                                                       width={colW[2]}  onResizeStart={e => onResizeStart(e, 2)}>ABC</PlainTh>
            <SortTh label="معدل/شهر"        field="-total_monthly_avg"   current={ordering} onSort={onSort} align="center" width={colW[3]}  onResizeStart={e => onResizeStart(e, 3)} />
            <SortTh label="مخزون"           field="-total_current_stock" current={ordering} onSort={onSort} align="center" width={colW[4]}  onResizeStart={e => onResizeStart(e, 4)} />
            <SortTh label="فجوة"            field="-total_gap"           current={ordering} onSort={onSort} align="center" width={colW[5]}  onResizeStart={e => onResizeStart(e, 5)} />
            <SortTh label="قيمة/شهر (ج.م)" field="-total_monthly_value" current={ordering} onSort={onSort} align="center" width={colW[6]}  onResizeStart={e => onResizeStart(e, 6)} />
            <PlainTh align="center" titleProp="هامش الربح الإجمالي = (سعر البيع − سعر الشراء) / سعر البيع"              width={colW[7]}  onResizeStart={e => onResizeStart(e, 7)}>هامش م%</PlainTh>
            <PlainTh align="center" titleProp="هامش الربح الصافي = (متوسط سعر البيع الفعلي − سعر الشراء) / سعر البيع القياسي" width={colW[8]} onResizeStart={e => onResizeStart(e, 8)}>هامش ص%</PlainTh>
            <PlainTh align="center"                                                                                       width={colW[9]}  onResizeStart={e => onResizeStart(e, 9)}>تراكمي%</PlainTh>
            <PlainTh align="center"                                                                                       width={colW[10]} onResizeStart={e => onResizeStart(e, 10)}>فروع</PlainTh>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.length === 0 && (
            <tr>
              <td colSpan={11} className="text-center py-12 text-gray-400">لا توجد بيانات — شغّل المحرك أولاً</td>
            </tr>
          )}
          {rows.map(row => (
            <tr key={row.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-3 py-2 font-medium text-gray-900 whitespace-nowrap" title={row.item_name}>{row.item_name}</td>
              <td className="px-3 py-2 text-gray-400 font-mono text-xs whitespace-nowrap">{row.item_code}</td>
              <td className="px-3 py-2 text-center"><AbcBadge cls={row.abc_class} /></td>
              <td className="px-3 py-2 text-center font-semibold">{fmt(row.total_monthly_avg)}</td>
              <td className={`px-3 py-2 text-center font-bold ${Number(row.total_gap) > 0 ? 'text-red-600' : 'text-green-600'}`}>
                {fmt(row.total_current_stock)}
              </td>
              <td className={`px-3 py-2 text-center font-bold ${Number(row.total_gap) > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                {Number(row.total_gap) > 0 ? `+${fmt(row.total_gap)}` : '—'}
              </td>
              <td className="px-3 py-2 text-center text-emerald-700 font-semibold">
                {fmt(row.total_monthly_value, 0)}
              </td>
              <td className="px-3 py-2 text-center">
                <MarginCell pct={row.std_gross_margin_pct}
                  title={`هامش إجمالي قياسي | سعر الشراء: ${Number(row.cost_price||0).toFixed(3)} ج.م`} />
              </td>
              <td className="px-3 py-2 text-center">
                <MarginCell pct={row.net_margin_pct}
                  title={`هامش صافي بعد الخصم | إيرادات فعلية: ${fmt(row.total_net_sales_revenue,0)} ج.م`} />
              </td>
              <td className="px-3 py-2 text-center text-gray-500 text-xs">
                {fmtP(row.cumulative_pct)}
              </td>
              <td className="px-3 py-2 text-center text-gray-400 text-xs">
                {row.branches_with_sales}
                {row.branches_with_gap > 0 && (
                  <span className="text-red-400 font-medium"> ({row.branches_with_gap} ناقص)</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Per-Branch Tab ────────────────────────────────────────────────────────────

// Widths: [item, ABC, branch, 30d, 90d, 365d, avg/mo, safety, stock, in-transit, coverage, gap, priority, status, last_sale, m%, n%]
const BRANCH_WIDTHS_DEFAULT = [260, 70, 120, 90, 90, 90, 110, 90, 100, 90, 90, 90, 90, 100, 100, 90, 90]

function BranchTab({ abcFilter, search, ordering, onSort, branches, runId, itemFilters = {} }) {
  const [selectedBranch, setSelectedBranch] = useState('')
  const [needsPurchase,  setNeedsPurchase]  = useState(false)
  const [colW, onResizeStart] = useColWidths(BRANCH_WIDTHS_DEFAULT)

  const advParams = buildAdvParams(itemFilters)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['purchasing-metrics', runId, abcFilter, search, ordering,
               selectedBranch, needsPurchase, itemFilters],
    queryFn: () => purchasingApi.metrics({
      abc_class:      abcFilter !== 'all' ? abcFilter : undefined,
      search:         search || undefined,
      ordering,
      branch:         selectedBranch || undefined,
      needs_purchase: needsPurchase ? '1' : undefined,
      page_size:      200,
      ...advParams,
    }).then(r => r.data.results || r.data),
    staleTime: 5 * 60_000,
    keepPreviousData: true,
    enabled: !!runId,
  })

  const rows = data || []

  return (
    <div>
      {/* Branch filter + needs-purchase toggle */}
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 bg-white border-b border-gray-100">
        <select
          value={selectedBranch}
          onChange={e => setSelectedBranch(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-brand-400"
        >
          <option value="">كل الفروع</option>
          {branches.map(b => (
            <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
          ))}
        </select>

        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-gray-700">
          <input
            type="checkbox"
            checked={needsPurchase}
            onChange={e => setNeedsPurchase(e.target.checked)}
            className="rounded"
          />
          يحتاج شراء فقط
        </label>

        {isFetching && <span className="text-xs text-gray-400 animate-pulse">جارٍ التحديث...</span>}
        <span className="text-xs text-gray-400 mr-auto">{rows.length} صنف</span>
      </div>

      {isLoading ? <TableSkeleton /> : (
        <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: 'calc(100vh - 410px)', minHeight: '280px' }}>
          <table style={{ tableLayout: 'fixed', width: colW.reduce((a,b)=>a+b,0), borderCollapse:'collapse' }} className="text-sm">
            <thead>
              <tr className="text-gray-500 text-xs font-bold">
                <SortTh label="الصنف"      field="item__name"      current={ordering} onSort={onSort}              width={colW[0]}  onResizeStart={e => onResizeStart(e, 0)} />
                <PlainTh align="center"                                                                              width={colW[1]}  onResizeStart={e => onResizeStart(e, 1)}>ABC</PlainTh>
                <PlainTh align="center"                                                                              width={colW[2]}  onResizeStart={e => onResizeStart(e, 2)}>الفرع</PlainTh>
                <SortTh label="30يوم"      field="-rate_30d"       current={ordering} onSort={onSort} align="center" width={colW[3]}  onResizeStart={e => onResizeStart(e, 3)} />
                <SortTh label="90يوم"      field="-rate_90d"       current={ordering} onSort={onSort} align="center" width={colW[4]}  onResizeStart={e => onResizeStart(e, 4)} />
                <SortTh label="365يوم"     field="-rate_365d"      current={ordering} onSort={onSort} align="center" width={colW[5]}  onResizeStart={e => onResizeStart(e, 5)} />
                <SortTh label="متوسط/شهر" field="-monthly_avg"    current={ordering} onSort={onSort} align="center" width={colW[6]}  onResizeStart={e => onResizeStart(e, 6)} />
                <SortTh label="أمان"       field="-safety_stock"   current={ordering} onSort={onSort} align="center" width={colW[7]}  onResizeStart={e => onResizeStart(e, 7)} />
                <SortTh label="مخزون"      field="-current_stock"  current={ordering} onSort={onSort} align="center" width={colW[8]}  onResizeStart={e => onResizeStart(e, 8)} />
                <SortTh label="بالطريق"    field="-in_transit_qty" current={ordering} onSort={onSort} align="center" width={colW[9]}  onResizeStart={e => onResizeStart(e, 9)} title="بضاعة في الطريق — مُرسلة للفرع ولم تُستلم بعد (تُخصم من الفجوة)" />
                <SortTh label="تغطية"      field="coverage_months" current={ordering} onSort={onSort} align="center" width={colW[10]} onResizeStart={e => onResizeStart(e, 10)} />
                <SortTh label="فجوة"       field="-gap"            current={ordering} onSort={onSort} align="center" width={colW[11]} onResizeStart={e => onResizeStart(e, 11)} />
                <SortTh label="أولوية"     field="-priority"       current={ordering} onSort={onSort} align="center" width={colW[12]} onResizeStart={e => onResizeStart(e, 12)} />
                <PlainTh align="center"                                                                              width={colW[13]} onResizeStart={e => onResizeStart(e, 13)}>الحالة</PlainTh>
                <PlainTh align="center"                                                                              width={colW[14]} onResizeStart={e => onResizeStart(e, 14)}>آخر بيع</PlainTh>
                <PlainTh align="center" titleProp="هامش الربح الإجمالي القياسي"                                      width={colW[15]} onResizeStart={e => onResizeStart(e, 15)}>هامش م%</PlainTh>
                <PlainTh align="center" titleProp="هامش الربح الصافي بعد الخصم"                                      width={colW[16]} onResizeStart={e => onResizeStart(e, 16)}>هامش ص%</PlainTh>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.length === 0 && (
                <tr>
                  <td colSpan={17} className="text-center py-12 text-gray-400">لا توجد نتائج</td>
                </tr>
              )}
              {rows.map(row => (
                <tr key={row.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-3 py-2 font-medium text-gray-900 whitespace-nowrap" title={row.item_name}>{row.item_name}</td>
                  <td className="px-3 py-2 text-center"><AbcBadge cls={row.abc_class} /></td>
                  <td className="px-3 py-2 text-center text-xs text-gray-500">{row.branch_name}</td>
                  <td className="px-3 py-2 text-center text-gray-600">{fmt(row.rate_30d)}</td>
                  <td className="px-3 py-2 text-center text-gray-600">{fmt(row.rate_90d)}</td>
                  <td className="px-3 py-2 text-center text-gray-600">{fmt(row.rate_365d)}</td>
                  <td className="px-3 py-2 text-center font-semibold text-gray-800">{fmt(row.monthly_avg)}</td>
                  <td className="px-3 py-2 text-center text-indigo-600">{fmt(row.safety_stock)}</td>
                  <td className={`px-3 py-2 text-center font-bold ${Number(row.gap) > 0 ? 'text-red-600' : 'text-green-600'}`}>
                    {fmt(row.current_stock)}
                  </td>
                  <td className="px-3 py-2 text-center text-xs"
                      title="بضاعة في الطريق — مُرسلة للفرع ولم تُستلم بعد">
                    {Number(row.in_transit_qty) > 0
                      ? <span className="font-semibold text-sky-600">🚚 {fmt(row.in_transit_qty)}</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-2 text-center text-gray-500 text-xs">
                    {row.coverage_months != null ? `${fmt(row.coverage_months)} شهر` : '—'}
                  </td>
                  <td className={`px-3 py-2 text-center font-bold text-sm ${Number(row.gap) > 0 ? 'text-red-600' : 'text-gray-300'}`}>
                    {Number(row.gap) > 0 ? `▲${fmt(row.gap)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {Number(row.priority) > 0
                      ? <span className="text-xs font-bold text-red-600">{fmt(row.priority, 2)}</span>
                      : <span className="text-gray-300 text-xs">—</span>
                    }
                  </td>
                  <td className="px-3 py-2 text-center">
                    <StockBadge status={row.stock_status} />
                  </td>
                  <td className="px-3 py-2 text-center text-xs text-gray-400">
                    {row.last_sale_date || '—'}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <MarginCell pct={row.std_gross_margin_pct}
                      title={`هامش إجمالي | سعر الشراء: ${Number(row.cost_price||0).toFixed(3)} ج.م`} />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <MarginCell pct={row.net_margin_pct}
                      title={`هامش صافي | إيرادات فعلية: ${fmt(row.net_sales_revenue||0,0)} ج.م`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Transfer Recommendations Tab ─────────────────────────────────────────────

const STATUS_COLORS = {
  pending:  'bg-amber-100  text-amber-700  ring-amber-300',
  approved: 'bg-green-100  text-green-700  ring-green-300',
  rejected: 'bg-red-100    text-red-700    ring-red-300',
  executed: 'bg-gray-100   text-gray-500   ring-gray-200',
}
const STATUS_LABELS = {
  pending: 'انتظار', approved: 'موافق', rejected: 'مرفوض', executed: 'منفّذ',
}

function TransferRecsTab({ isAdmin }) {
  const qc = useQueryClient()

  // Standard filters
  const [statusFilter,     setStatusFilter]     = useState('pending')
  const [abcFilter,        setAbcFilter]         = useState('all')
  const [fromBranchFilter, setFromBranchFilter]  = useState('')
  const [toBranchFilter,   setToBranchFilter]    = useState('')
  const [search,           setSearch]            = useState('')
  const [ordering,         setOrdering]          = useState('-priority_score')
  const [reviewing,        setReviewing]         = useState(null)
  // Advanced item filters
  const [itemFilters,      setItemFilters]       = useState({ ...EMPTY_ITEM_FILTERS })
  const [showAdvanced,     setShowAdvanced]      = useState(false)

  // Summary (header cards)
  const { data: summary } = useQuery({
    queryKey: ['purchasing-transfer-summary'],
    queryFn:  () => purchasingApi.transferRecSummary().then(r => r.data),
    staleTime: 2 * 60_000,
    retry: false,
  })

  // Branches for filter dropdowns
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data.results || r.data),
  })

  // Filter options for advanced dropdowns
  const { data: filterOpts } = useQuery({
    queryKey: ['purchasing-filter-options'],
    queryFn:  () => purchasingApi.filterOptions().then(r => r.data),
    staleTime: 10 * 60_000,
  })

  const advParams = buildAdvParams(itemFilters)

  // Recommendations list
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['purchasing-transfer-recs', statusFilter, abcFilter,
               fromBranchFilter, toBranchFilter, search, ordering, itemFilters],
    queryFn: () => purchasingApi.transferRecs({
      status:      statusFilter !== 'all' ? statusFilter : undefined,
      abc_class:   abcFilter    !== 'all' ? abcFilter    : undefined,
      from_branch: fromBranchFilter || undefined,
      to_branch:   toBranchFilter   || undefined,
      search:      search           || undefined,
      ordering,
      page_size:   300,
      ...advParams,
    }).then(r => r.data.results || r.data),
    staleTime: 2 * 60_000,
    keepPreviousData: true,
    retry: false,
  })

  const rows = data || []

  // Approve / reject mutation
  const reviewMutation = useMutation({
    mutationFn: ({ id, status, notes }) =>
      purchasingApi.transferRecStatus(id, { status, notes }),
    onSuccess: () => {
      qc.invalidateQueries(['purchasing-transfer-recs'])
      qc.invalidateQueries(['purchasing-transfer-summary'])
      setReviewing(null)
    },
  })

  const handleReview = (id, action) => {
    reviewMutation.mutate({ id, status: action, notes: '' })
  }

  const s = summary || {}

  return (
    <div dir="rtl">

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4">
          <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4">
            <div className="text-xs font-medium text-indigo-600 opacity-70">إجمالي التوصيات</div>
            <div className="text-2xl font-black text-indigo-700 mt-1">{fmt(s.total_recs, 0)}</div>
            <div className="text-xs text-indigo-500 mt-0.5">{fmt(s.items_covered, 0)} صنف</div>
          </div>
          <div className="rounded-xl border border-amber-100 bg-amber-50 p-4">
            <div className="text-xs font-medium text-amber-600 opacity-70">انتظار مراجعة</div>
            <div className="text-2xl font-black text-amber-700 mt-1">{fmt(s.pending_recs, 0)}</div>
          </div>
          <div className="rounded-xl border border-green-100 bg-green-50 p-4">
            <div className="text-xs font-medium text-green-600 opacity-70">موافق عليها</div>
            <div className="text-2xl font-black text-green-700 mt-1">{fmt(s.approved_recs, 0)}</div>
          </div>
          <div className="rounded-xl border border-emerald-100 bg-emerald-50 p-4">
            <div className="text-xs font-medium text-emerald-600 opacity-70">قيمة التحويلات (ج.م)</div>
            <div className="text-2xl font-black text-emerald-700 mt-1">{fmt(s.total_value, 0)}</div>
          </div>
        </div>
      )}

      {/* Filters bar */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-gray-100 bg-white">
        {/* Status */}
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:border-brand-400">
          <option value="all">كل الحالات</option>
          <option value="pending">انتظار</option>
          <option value="approved">موافق</option>
          <option value="rejected">مرفوض</option>
          <option value="executed">منفّذ</option>
        </select>

        {/* ABC */}
        <select value={abcFilter} onChange={e => setAbcFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:border-brand-400">
          <option value="all">كل الفئات</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>

        {/* From branch */}
        <select value={fromBranchFilter} onChange={e => setFromBranchFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:border-brand-400">
          <option value="">من: كل الفروع</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>

        {/* To branch */}
        <select value={toBranchFilter} onChange={e => setToBranchFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:border-brand-400">
          <option value="">إلى: كل الفروع</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>

        {/* Search */}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="ابحث عن صنف..."
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs w-40 focus:outline-none focus:border-brand-400"
        />

        {/* Advanced filters toggle */}
        <button
          onClick={() => setShowAdvanced(v => !v)}
          className={`text-xs px-2 py-1.5 rounded-lg border transition-colors ${
            showAdvanced
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'border-gray-200 text-gray-500 hover:border-indigo-400 hover:text-indigo-600'
          }`}
        >
          🔍 {showAdvanced ? 'إخفاء الفلاتر' : 'فلاتر متقدمة'}
        </button>

        {isFetching && <span className="text-xs text-gray-400 animate-pulse">جارٍ التحديث...</span>}
        <span className="text-xs text-gray-400 mr-auto">{rows.length} توصية</span>
      </div>

      {/* Advanced filter panel */}
      {showAdvanced && (
        <AdvancedFiltersBar
          opts={filterOpts}
          filters={itemFilters}
          onChange={setItemFilters}
        />
      )}

      {/* Table */}
      {isLoading ? <TableSkeleton /> : (
        <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: 'calc(100vh - 490px)', minHeight: '280px' }}>
          {/* ROW 1 height ≈ 28px (py-1.5 × 2 = 12px + ~10px text ≈ 26-28px) → row 2 uses top: 28 */}
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead>
              {/* Group header row — sticky row 1 (top: 0)
                  Columns: [الصنف + كود + ABC = 3] + [فرع المصدر × 3] + [فرع الهدف × 3] + [كمية+قيمة+أولوية+الحالة+إجراء = 4 or 5] */}
              <tr className="text-gray-400 text-[10px] font-semibold">
                <th colSpan={3}
                    style={{ position: 'sticky', top: 0, zIndex: 21, backgroundColor: '#f3f4f6' }} />
                <th colSpan={3} className="px-3 py-1.5 text-center text-blue-500 border-x border-gray-200"
                    style={{ position: 'sticky', top: 0, zIndex: 21, backgroundColor: '#f3f4f6' }}>فرع المصدر</th>
                <th colSpan={3} className="px-3 py-1.5 text-center text-indigo-500 border-x border-gray-200"
                    style={{ position: 'sticky', top: 0, zIndex: 21, backgroundColor: '#f3f4f6' }}>فرع الهدف</th>
                <th colSpan={isAdmin ? 7 : 6}
                    style={{ position: 'sticky', top: 0, zIndex: 21, backgroundColor: '#f3f4f6' }} />
              </tr>
              {/* Column header row — sticky row 2 (top: 28px to clear row 1) */}
              <tr className="text-gray-500 text-xs font-bold">
                <SortTh label="الصنف"          field="item__name"           current={ordering} onSort={setOrdering} stickyTop={28} />
                <th className="px-3 py-2 text-right border-b border-gray-200 whitespace-nowrap"
                    style={{ position: 'sticky', top: 28, zIndex: 20, backgroundColor: '#f9fafb' }}>كود</th>
                <th className="px-3 py-2 text-center border-b border-gray-200 whitespace-nowrap"
                    style={{ position: 'sticky', top: 28, zIndex: 20, backgroundColor: '#f9fafb' }}>ABC</th>
                {/* Source branch columns */}
                <SortTh label="من فرع"         field="from_branch__name_ar" current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <SortTh label="رصيد"           field="-from_stock"          current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <SortTh label="معدل/شهر"       field="-from_monthly_avg"    current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                {/* Destination branch columns */}
                <SortTh label="إلى فرع"        field="to_branch__name_ar"   current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <SortTh label="رصيد"           field="-to_stock"            current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <SortTh label="معدل/شهر"       field="-to_monthly_avg"      current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                {/* Transfer columns */}
                <SortTh label="كمية"           field="-quantity"            current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <SortTh label="قيمة (ج.م)"    field="-estimated_value"     current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <SortTh label="أولوية"         field="-priority_score"      current={ordering} onSort={setOrdering} align="center" stickyTop={28} />
                <th className="px-3 py-2 text-center border-b border-gray-200 whitespace-nowrap"
                    style={{ position: 'sticky', top: 28, zIndex: 20, backgroundColor: '#f9fafb' }}
                    title="هامش الربح الإجمالي القياسي">هامش م%</th>
                <th className="px-3 py-2 text-center border-b border-gray-200 whitespace-nowrap"
                    style={{ position: 'sticky', top: 28, zIndex: 20, backgroundColor: '#f9fafb' }}>الحالة</th>
                {isAdmin && (
                  <th className="px-3 py-2 text-center border-b border-gray-200 whitespace-nowrap"
                      style={{ position: 'sticky', top: 28, zIndex: 20, backgroundColor: '#f9fafb' }}>إجراء</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.length === 0 && (
                <tr>
                  <td colSpan={isAdmin ? 16 : 15} className="text-center py-12 text-gray-400">
                    لا توجد توصيات — شغّل المحرك لإنشاء توصيات التحويل
                  </td>
                </tr>
              )}
              {rows.map(rec => (
                <tr key={rec.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-3 py-2 font-medium text-gray-900 min-w-[200px]" title={rec.item_name}>{rec.item_name}</td>
                  <td className="px-3 py-2 text-gray-400 font-mono text-xs whitespace-nowrap">{rec.item_code || '—'}</td>
                  <td className="px-3 py-2 text-center"><AbcBadge cls={rec.abc_class} /></td>

                  {/* Source branch */}
                  <td className="px-3 py-2 text-center text-xs text-blue-700 font-semibold">{rec.from_branch_name}</td>
                  <td className="px-3 py-2 text-center text-xs text-blue-600">
                    <span title={`فائض: ${fmt(rec.from_surplus)}`}>{fmt(rec.from_stock)}</span>
                  </td>
                  <td className="px-3 py-2 text-center text-xs text-blue-500">{fmt(rec.from_monthly_avg, 1)}</td>

                  {/* Destination branch */}
                  <td className="px-3 py-2 text-center text-xs text-indigo-700 font-semibold">{rec.to_branch_name}</td>
                  <td className="px-3 py-2 text-center text-xs text-indigo-600">{fmt(rec.to_stock)}</td>
                  <td className="px-3 py-2 text-center text-xs text-indigo-500">{fmt(rec.to_monthly_avg, 1)}</td>

                  {/* Transfer */}
                  <td className="px-3 py-2 text-center font-bold text-gray-800">{fmt(rec.quantity)}</td>
                  <td className="px-3 py-2 text-center text-emerald-700 font-semibold">{fmt(rec.estimated_value, 0)}</td>
                  <td className="px-3 py-2 text-center">
                    <span className="text-xs font-bold text-red-600">{fmt(rec.priority_score, 2)}</span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <MarginCell pct={rec.std_gross_margin_pct}
                      title={`هامش إجمالي | سعر الشراء: ${Number(rec.cost_price||0).toFixed(3)} ج.م`} />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ring-1 ${STATUS_COLORS[rec.status] || ''}`}>
                      {STATUS_LABELS[rec.status] || rec.status}
                    </span>
                  </td>
                  {isAdmin && (
                    <td className="px-3 py-2 text-center">
                      {rec.status === 'pending' && (
                        <div className="flex gap-1 justify-center">
                          <button
                            onClick={() => handleReview(rec.id, 'approved')}
                            disabled={reviewMutation.isLoading}
                            className="text-xs px-2 py-0.5 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                          >
                            ✓ موافق
                          </button>
                          <button
                            onClick={() => handleReview(rec.id, 'rejected')}
                            disabled={reviewMutation.isLoading}
                            className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50"
                          >
                            ✕ رفض
                          </button>
                        </div>
                      )}
                      {rec.status === 'approved' && (
                        <button
                          onClick={() => handleReview(rec.id, 'executed')}
                          disabled={reviewMutation.isLoading}
                          className="text-xs px-2 py-0.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          ✓ منفّذ
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Sortable Table Header ─────────────────────────────────────────────────────

// stickyTop: pixel offset from the top of the scroll container (default 0 for single-row headers;
//            pass the first-row height in px for a second row in a 2-row header)
// width / onResizeStart: optional column-resize support
function SortTh({ label, field, current, onSort, align = 'right', stickyTop = 0, width, onResizeStart, title: titleProp }) {
  const next = current === `-${field}` ? field : `-${field}`
  const icon = current === `-${field}` ? '↑' : current === field ? '↓' : '↕'

  return (
    <th
      title={titleProp}
      className={`px-3 py-2 text-${align} cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap border-b border-gray-200`}
      style={{ position: 'sticky', top: stickyTop, zIndex: 20, backgroundColor: '#f9fafb',
               width: width || undefined, minWidth: 60, userSelect: 'none' }}
      onClick={() => onSort(next)}
    >
      {label} <span className="text-gray-400 text-xs">{icon}</span>
      {onResizeStart && (
        <span
          onMouseDown={e => onResizeStart(e)}
          onClick={e => e.stopPropagation()}
          style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 5,
                   cursor: 'col-resize', zIndex: 1 }}
          className="group"
        >
          <span className="absolute inset-0 rounded-sm opacity-0 group-hover:opacity-100 bg-brand-400 transition-opacity" />
        </span>
      )}
    </th>
  )
}

// Plain (non-sortable) th with optional resize handle
function PlainTh({ children, align = 'center', stickyTop = 0, width, onResizeStart, title: titleProp }) {
  return (
    <th
      title={titleProp}
      className={`px-3 py-2 text-${align} border-b border-gray-200 whitespace-nowrap select-none`}
      style={{ position: 'sticky', top: stickyTop, zIndex: 20, backgroundColor: '#f9fafb',
               width: width || undefined, minWidth: 60, userSelect: 'none' }}
    >
      {children}
      {onResizeStart && (
        <span
          onMouseDown={e => onResizeStart(e)}
          onClick={e => e.stopPropagation()}
          style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 5,
                   cursor: 'col-resize', zIndex: 1 }}
          className="group"
        >
          <span className="absolute inset-0 rounded-sm opacity-0 group-hover:opacity-100 bg-brand-400 transition-opacity" />
        </span>
      )}
    </th>
  )
}

// ── Advanced Filters — shared helpers ────────────────────────────────────────

// Categorical filters are MULTI-SELECT (arrays). Labels mirror the SOFTECH item
// card. Ranges + booleans handled separately.
const MULTI_KEYS = [
  'medicine_type', 'category', 'shape_code', 'effect_code', 'origin_code',
  'supplier_code', 'producer_code', 'family_code',
  'store_classif', 'nosale_classif', 'insurance_type', 'item_level',
  'branch_trans', 'supplier_trans', 'customer_trans',
]
const EMPTY_ITEM_FILTERS = {
  ...Object.fromEntries(MULTI_KEYS.map(k => [k, []])),
  requires_fridge: false, is_fast_moving: false, has_points: false,
  is_active: '',            // '' = all, '0' = archived only
  price_min: '', price_max: '',        // سعر الجمهور
  discount_min: '', discount_max: '',  // خصم أساسى %
}

/**
 * Convert itemFilters state to query params for API calls.
 * Boolean flags → '1' string; empty strings → undefined (omitted).
 */
function buildAdvParams(f) {
  const csv = a => (Array.isArray(a) && a.length) ? a.join(',') : undefined
  const num = v => (v !== '' && v != null) ? v : undefined
  const out = { }
  for (const k of MULTI_KEYS) out[k] = csv(f[k])
  out.requires_fridge = f.requires_fridge ? '1' : undefined
  out.is_fast_moving  = f.is_fast_moving  ? '1' : undefined
  out.has_points      = f.has_points      ? '1' : undefined
  out.is_active       = f.is_active       || undefined
  out.price_min       = num(f.price_min)
  out.price_max       = num(f.price_max)
  out.discount_min    = num(f.discount_min)
  out.discount_max    = num(f.discount_max)
  return out
}

/** Count how many filters are active (for the badge on the toggle button). */
function countActiveFilters(f) {
  let n = 0
  for (const k of MULTI_KEYS) if (Array.isArray(f[k]) && f[k].length) n++
  if (f.requires_fridge) n++
  if (f.is_fast_moving)  n++
  if (f.has_points)      n++
  if (f.is_active)       n++
  for (const k of ['price_min', 'price_max', 'discount_min', 'discount_max'])
    if (f[k] !== '' && f[k] != null) n++
  return n
}

// Shared select class
const SEL = 'border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand-400 bg-white'
// Shared checkbox-label class
const CHK_LBL = 'flex items-center gap-1.5 cursor-pointer select-none text-xs bg-white border border-gray-200 rounded-lg px-2 py-1'

// ── Reusable multi-select dropdown (count badge + optional type-ahead) ───────
function MultiSelect({ label, options = [], value = [], onChange,
                       getVal = o => String(o.code), getLabel = o => o.name_ar || o.name || o.code,
                       searchable = false, width = 'w-56' }) {
  const [open, setOpen] = useState(false)
  const [q, setQ]       = useState('')
  const ref = useRef(null)
  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  if (!options.length) return null
  const sel = new Set(value)
  const ql  = q.trim().toLowerCase()
  const list = (searchable && ql)
    ? options.filter(o => `${getLabel(o)} ${getVal(o)}`.toLowerCase().includes(ql))
    : options
  const toggle = v => onChange(sel.has(v) ? value.filter(x => x !== v) : [...value, v])

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen(o => !o)}
        className={`${SEL} flex items-center gap-1 ${value.length ? 'border-brand-400 text-brand-700 font-semibold' : 'text-gray-600'}`}>
        <span className="truncate max-w-[140px]">{label}</span>
        {value.length > 0 && (
          <span className="bg-brand-600 text-white rounded-full px-1.5 text-[10px] font-bold">{value.length}</span>
        )}
        <span className="text-gray-400 text-[10px]">▾</span>
      </button>
      {open && (
        <div className={`absolute z-40 mt-1 ${width} bg-white border border-gray-200 rounded-lg shadow-xl`} dir="rtl">
          {searchable && (
            <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="بحث..."
              className="w-full border-b border-gray-100 px-2.5 py-1.5 text-xs focus:outline-none" />
          )}
          {value.length > 0 && (
            <button type="button" onClick={() => onChange([])}
              className="w-full text-right px-2.5 py-1 text-[11px] text-red-500 hover:bg-red-50 border-b border-gray-100">
              ✕ مسح ({value.length})
            </button>
          )}
          <div className="max-h-56 overflow-y-auto py-0.5">
            {list.length === 0 && <div className="px-2.5 py-2 text-[11px] text-gray-400">لا نتائج</div>}
            {list.slice(0, 300).map(o => {
              const v = getVal(o)
              return (
                <label key={v} className="flex items-center gap-2 px-2.5 py-1 text-xs hover:bg-gray-50 cursor-pointer">
                  <input type="checkbox" checked={sel.has(v)} onChange={() => toggle(v)} className="rounded shrink-0" />
                  <span className="truncate">{getLabel(o)}</span>
                </label>
              )
            })}
            {list.length > 300 && (
              <div className="px-2.5 py-1 text-[10px] text-gray-400">+{list.length - 300} — ابحث للتضييق</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Numeric range (min / max) ────────────────────────────────────────────────
function RangeFilter({ label, suffix = '', vMin, vMax, onMin, onMax, step = '1' }) {
  const active = (vMin !== '' && vMin != null) || (vMax !== '' && vMax != null)
  return (
    <div className={`flex items-center gap-1 rounded-lg border px-2 py-1 bg-white ${active ? 'border-brand-400' : 'border-gray-200'}`}>
      <span className={`text-[11px] shrink-0 ${active ? 'text-brand-700 font-semibold' : 'text-gray-500'}`}>{label}</span>
      <input type="number" step={step} value={vMin} onChange={e => onMin(e.target.value)} placeholder="من"
        className="w-14 text-xs text-center focus:outline-none bg-transparent" />
      <span className="text-gray-300">–</span>
      <input type="number" step={step} value={vMax} onChange={e => onMax(e.target.value)} placeholder="إلى"
        className="w-14 text-xs text-center focus:outline-none bg-transparent" />
      {suffix && <span className="text-[10px] text-gray-400 shrink-0">{suffix}</span>}
    </div>
  )
}

function AdvancedFiltersBar({ opts = {}, filters, onChange }) {
  const hasActive = countActiveFilters(filters) > 0
  const set = (k, v) => onChange({ ...filters, [k]: v })

  return (
    <div className="bg-indigo-50/60 border-b border-indigo-100 px-4 py-2 space-y-2">

      {/* Row 1 — تصنيفات الصنف (labels match the SOFTECH item card) */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-indigo-500 shrink-0">📦 تصنيف الصنف:</span>
        <MultiSelect label="تصنيف عام" options={opts.medicine_types} value={filters.medicine_type}
          onChange={v => set('medicine_type', v)} />
        <MultiSelect label="تصنيف (الشكل الصيدلى)" options={opts.categories} value={filters.category}
          getVal={c => String(c.id)} getLabel={c => c.name_ar || c.name} searchable
          onChange={v => set('category', v)} />
        <MultiSelect label="الشكل الدوائى" options={opts.shapes} value={filters.shape_code}
          searchable onChange={v => set('shape_code', v)} />
        <MultiSelect label="الاستخدام" options={opts.effects} value={filters.effect_code}
          searchable onChange={v => set('effect_code', v)} />
        <MultiSelect label="المنشأ" options={opts.origins} value={filters.origin_code}
          onChange={v => set('origin_code', v)} />
      </div>

      {/* Row 2 — المصدر (supplier / producer / family) + ranges */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-indigo-500 shrink-0">🏭 المصدر والسعر:</span>
        <MultiSelect label="المورد" options={opts.suppliers} value={filters.supplier_code}
          getLabel={s => s.name || s.code} searchable onChange={v => set('supplier_code', v)} />
        <MultiSelect label="الشركة المنتجة" options={opts.producers} value={filters.producer_code}
          searchable onChange={v => set('producer_code', v)} />
        <MultiSelect label="العائلة" options={opts.families} value={filters.family_code}
          searchable onChange={v => set('family_code', v)} />
        <RangeFilter label="سعر الجمهور" suffix="ج.م" step="1"
          vMin={filters.price_min} vMax={filters.price_max}
          onMin={v => set('price_min', v)} onMax={v => set('price_max', v)} />
        <RangeFilter label="خصم أساسى" suffix="%" step="0.5"
          vMin={filters.discount_min} vMax={filters.discount_max}
          onMin={v => set('discount_min', v)} onMax={v => set('discount_max', v)} />
      </div>

      {/* Row 3 — تصنيفات التعاقد والتأمين + flags */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-indigo-500 shrink-0">⚙️ تعاقدات:</span>
        <MultiSelect label="تصنيف خصم التعاقدات" options={opts.store_classif_options} value={filters.store_classif}
          getLabel={s => s.name || s.code} searchable onChange={v => set('store_classif', v)} />
        <MultiSelect label="تصنيف منع الصرف" options={opts.nosale_classif_options} value={filters.nosale_classif}
          onChange={v => set('nosale_classif', v)} />
        <MultiSelect label="تصنيف التأمين الصحى" options={opts.insurance_types} value={filters.insurance_type}
          onChange={v => set('insurance_type', v)} />
        <MultiSelect label="مستوى الصنف" options={opts.item_level_options} value={filters.item_level}
          onChange={v => set('item_level', v)} />
        <label className={`${CHK_LBL} text-sky-700`}>
          <input type="checkbox" checked={filters.requires_fridge}
            onChange={e => set('requires_fridge', e.target.checked)} className="rounded" /> ❄ تبريد
        </label>
        <label className={`${CHK_LBL} text-orange-700`}>
          <input type="checkbox" checked={filters.is_fast_moving}
            onChange={e => set('is_fast_moving', e.target.checked)} className="rounded" /> ⚡ سريع التداول
        </label>
        <label className={`${CHK_LBL} text-purple-700`}>
          <input type="checkbox" checked={filters.has_points}
            onChange={e => set('has_points', e.target.checked)} className="rounded" /> 🎁 نقاط
        </label>
        <label className={`${CHK_LBL} text-gray-600`}>
          <input type="checkbox" checked={filters.is_active === '0'}
            onChange={e => set('is_active', e.target.checked ? '0' : '')} className="rounded" /> 🗃 أرشيف فقط
        </label>
      </div>

      {/* Row 4 — الصلاحيات */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-indigo-500 shrink-0">🔒 الصلاحيات:</span>
        <MultiSelect label="صلاحية الفروع" options={opts.trans_options} value={filters.branch_trans}
          onChange={v => set('branch_trans', v)} />
        <MultiSelect label="صلاحية الموردين" options={opts.trans_options} value={filters.supplier_trans}
          onChange={v => set('supplier_trans', v)} />
        <MultiSelect label="صلاحية العملاء" options={opts.trans_options} value={filters.customer_trans}
          onChange={v => set('customer_trans', v)} />
        {hasActive && (
          <button onClick={() => onChange({ ...EMPTY_ITEM_FILTERS })}
            className="text-xs text-red-500 hover:text-red-700 mr-auto whitespace-nowrap">
            ✕ مسح كل الفلاتر ({countActiveFilters(filters)})
          </button>
        )}
      </div>
    </div>
  )
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function TableSkeleton() {
  return (
    <div className="p-4 space-y-2">
      {[...Array(8)].map((_, i) => (
        <div key={i} className="h-9 bg-gray-100 rounded animate-pulse" />
      ))}
    </div>
  )
}

// ── Lost Sales Tab ────────────────────────────────────────────────────────────

const ROOT_CAUSE_LABELS = {
  purchasing: { label: 'شراء غير كافٍ',    color: 'bg-red-100    text-red-700',    icon: '🛒' },
  supplier:   { label: 'تأخر المورد',       color: 'bg-orange-100 text-orange-700', icon: '🚚' },
  transfer:   { label: 'متاح في فرع آخر',  color: 'bg-blue-100   text-blue-700',   icon: '🔄' },
  expiry:     { label: 'منتهي الصلاحية',    color: 'bg-purple-100 text-purple-700', icon: '⚠️' },
  forecast:   { label: 'ارتفاع مفاجئ',      color: 'bg-yellow-100 text-yellow-700', icon: '📈' },
  unknown:    { label: 'غير محدد',          color: 'bg-gray-100   text-gray-500',   icon: '❓' },
}

function RootCauseBadge({ cause }) {
  const meta = ROOT_CAUSE_LABELS[cause] || ROOT_CAUSE_LABELS.unknown
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${meta.color}`}>
      <span>{meta.icon}</span>
      <span>{meta.label}</span>
    </span>
  )
}

function LostSalesTab() {
  const { data: summary, isLoading, isError } = useQuery({
    queryKey: ['lost-sales-summary'],
    queryFn:  () => purchasingApi.lostSalesSummary().then(r => r.data),
    staleTime: 60_000,
  })

  if (isLoading) return (
    <div className="flex items-center justify-center py-16 text-gray-400 text-sm animate-pulse">
      جارٍ تحميل بيانات المبيعات الضائعة...
    </div>
  )

  if (isError || !summary) return (
    <div className="flex flex-col items-center justify-center py-16 text-gray-400 text-sm gap-2">
      <span className="text-3xl">💸</span>
      <span>لم يتم تشغيل محرك المبيعات الضائعة بعد</span>
      <span className="text-xs">سيُشغَّل تلقائياً مع الضغط على «تشغيل المحرك»</span>
    </div>
  )

  const fmtCur = v => Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
  const totalRev    = Number(summary.total_lost_revenue_30d || 0)
  const totalMargin = Number(summary.total_lost_margin_30d  || 0)
  const itemsCount  = summary.items_with_stockout || 0
  const avgAvail    = summary.avg_availability_pct ?? 100

  return (
    <div className="space-y-5 p-4" dir="rtl">

      {/* KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryCard
          label="الإيراد الضائع (30 يوم)"
          value={`${fmtCur(totalRev)} ج.م`}
          color={totalRev > 10000 ? 'red' : totalRev > 0 ? 'amber' : 'green'}
        />
        <SummaryCard
          label="هامش الربح الضائع (30 يوم)"
          value={`${fmtCur(totalMargin)} ج.م`}
          color={totalMargin > 5000 ? 'red' : 'amber'}
        />
        <SummaryCard
          label="أصناف مع نفاد مخزون"
          value={itemsCount}
          sub="خلال 30 يوم"
          color={itemsCount > 50 ? 'red' : itemsCount > 0 ? 'amber' : 'green'}
        />
        <SummaryCard
          label="متوسط معدل التوفر"
          value={`${avgAvail.toFixed(1)}%`}
          sub="عبر الفروع والأصناف"
          color={avgAvail < 85 ? 'red' : avgAvail < 95 ? 'amber' : 'green'}
        />
      </div>

      {/* Root cause breakdown */}
      {summary.root_cause_breakdown?.length > 0 && (
        <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm">
          <h3 className="text-sm font-bold text-gray-700 mb-3">🔍 تحليل الأسباب الجذرية</h3>
          <div className="space-y-2">
            {summary.root_cause_breakdown.map(r => {
              const meta   = ROOT_CAUSE_LABELS[r.root_cause] || ROOT_CAUSE_LABELS.unknown
              const lostRev = Number(r.lost_revenue || 0)
              const maxRev  = Number(summary.root_cause_breakdown[0]?.lost_revenue || 1)
              const barPct  = maxRev > 0 ? Math.round(lostRev / maxRev * 100) : 0
              return (
                <div key={r.root_cause} className="flex items-center gap-3">
                  <div className="w-28 flex-shrink-0">
                    <RootCauseBadge cause={r.root_cause} />
                  </div>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div
                      className="h-2 rounded-full bg-red-400 transition-all"
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                  <div className="text-xs text-gray-600 w-20 text-left font-mono">
                    {fmtCur(lostRev)} ج.م
                  </div>
                  <div className="text-xs text-gray-400 w-12 text-left">
                    {r.count} صنف
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Top items table */}
      {summary.top_items?.length > 0 && (
        <div className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-bold text-gray-700">📋 أعلى الأصناف خسارةً (30 يوم)</h3>
            <span className="text-xs text-gray-400">أول 20 صنف بترتيب الإيراد الضائع</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-gray-500 text-xs">
                  <th className="px-3 py-2 text-right font-semibold">الصنف</th>
                  <th className="px-3 py-2 text-right font-semibold">كود</th>
                  <th className="px-3 py-2 text-right font-semibold">الإيراد الضائع</th>
                  <th className="px-3 py-2 text-right font-semibold">الفروع المتأثرة</th>
                  <th className="px-3 py-2 text-right font-semibold">السبب</th>
                </tr>
              </thead>
              <tbody>
                {summary.top_items.map((item, i) => (
                  <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium text-gray-800 max-w-xs break-words">
                      {item.item_name}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-brand-600">
                      {item.item_code}
                    </td>
                    <td className="px-3 py-2 text-red-600 font-semibold">
                      {fmtCur(item.lost_revenue_30d)} ج.م
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full font-medium">
                        {item.branches_affected}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <RootCauseBadge cause={item.root_cause} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Run metadata */}
      {summary.run && (
        <div className="text-xs text-gray-400 text-center">
          آخر تشغيل محرك المبيعات الضائعة:
          {' '}{new Date(summary.run.started_at).toLocaleString('en-US')}
          {' · '}{summary.run.branch_item_pairs?.toLocaleString('en-US')} زوج (فرع × صنف)
        </div>
      )}

    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const ABC_TABS = [
  { value: 'all', label: 'كل الأصناف' },
  { value: 'A',   label: 'A — الأكثر أهمية' },
  { value: 'B',   label: 'B — متوسط' },
  { value: 'C',   label: 'C — أقل أهمية' },
  { value: 'X',   label: 'X — بلا مبيعات' },
]

const VIEW_TABS = [
  { value: 'agg',       label: '📦 الشبكة (ABC)' },
  { value: 'branch',    label: '🏭 بالفرع' },
  { value: 'transfer',  label: '🔄 التحويلات المقترحة' },
  { value: 'lostsales', label: '💸 مبيعات ضائعة' },
]

export default function PurchasingDashboard() {
  const { user }   = useAuthStore()
  const qc         = useQueryClient()
  const isAdmin    = ['admin', 'pharmacist'].includes(user?.role)

  const [viewTab,   setViewTab]   = useState('agg')
  const [abcFilter, setAbcFilter] = useState('all')
  const [search,    setSearch]    = useState('')
  const [ordering,  setOrdering]  = useState('-total_monthly_value')

  // When switching tabs, reset ordering to sensible defaults
  const handleViewTab = (v) => {
    setViewTab(v)
    setOrdering(v === 'agg' ? '-total_monthly_value' : '-priority')
  }

  // Advanced item filters — shared across Aggregated and Branch tabs
  const [itemFilters,    setItemFilters]    = useState({ ...EMPTY_ITEM_FILTERS })
  const [showAdvFilters, setShowAdvFilters] = useState(false)

  // Filter options for dropdown population (medicine_type, supplier, family, categories)
  const { data: filterOpts } = useQuery({
    queryKey: ['purchasing-filter-options'],
    queryFn:  () => purchasingApi.filterOptions().then(r => r.data),
    staleTime: 10 * 60_000,
    retry: false,
  })

  // ── Engine run tracking ───────────────────────────────────────────────────
  // triggerTime:   set when user presses a trigger button — enables fast-poll
  // isFullTrigger: true when user pressed "Full Sync 365d" (longer estimate)
  // preTriggerRunId: runId snapshot taken just before trigger fires (to detect new run)
  const [triggerTime,      setTriggerTime]      = useState(null)
  const [isFullTrigger,    setIsFullTrigger]    = useState(false)
  const [preTriggerRunId,  setPreTriggerRunId]  = useState(null)
  const wasRunning = useRef(false)

  // Fast-poll window: 12 min for full-sync (365d ≈ 8 min), 5 min for incremental
  const maxPollMs = isFullTrigger ? 12 * 60_000 : 5 * 60_000
  const isPolling = !!(triggerTime && (Date.now() - triggerTime < maxPollMs))

  // ── Active run (live progress) ────────────────────────────────────────────
  // Polls /runs/active/ fast when triggered or a run is visible, slow otherwise.
  // Returns null (not the axios response) when 404 so the UI treats it as "idle".
  const { data: activeRunData } = useQuery({
    queryKey: ['purchasing-run-active'],
    queryFn:  () => purchasingApi.activeRun()
      .then(r => r.data)
      .catch(err => (err?.response?.status === 404 ? null : Promise.reject(err))),
    refetchInterval: (data) => (isPolling || data) ? 3_000 : 20_000,
    retry: false,
    staleTime: 0,
  })

  const isRunning = activeRunData?.status === 'running'

  // When a run transitions running → done, reload all dependent data
  useEffect(() => {
    if (isRunning) {
      wasRunning.current = true
    } else if (wasRunning.current) {
      wasRunning.current = false
      setTriggerTime(null)
      setPreTriggerRunId(null)
      // Small delay so DB writes settle before we re-fetch
      setTimeout(() => {
        qc.invalidateQueries(['purchasing-run-latest'])
        qc.invalidateQueries(['purchasing-summary'])
        // Table rows auto-refresh when runId changes (they key on runId)
      }, 1_500)
    }
  }, [isRunning, qc])

  // ── Latest successful run (drives table data) ─────────────────────────────
  // Poll at 15s while waiting for engine; otherwise every 5 minutes.
  // 5s was too aggressive — caused 10+ requests/minute in the server log.
  const { data: latestRun } = useQuery({
    queryKey: ['purchasing-run-latest'],
    queryFn:  () => purchasingApi.latestRun().then(r => r.data),
    refetchInterval: isPolling ? 15_000 : 5 * 60_000,
    staleTime: isPolling ? 10_000 : 4 * 60_000,
    retry: false,
  })

  const runId = latestRun?.id

  // ── Last attempt (any status) ─────────────────────────────────────────────
  // Surfaces a failed / partial / still-running latest attempt in the header,
  // even when the table below is still showing the older successful run.
  const { data: lastAttempt } = useQuery({
    queryKey: ['purchasing-run-last-attempt'],
    queryFn:  () => purchasingApi.lastAttempt().then(r => r.data).catch(() => null),
    refetchInterval: isPolling ? 15_000 : 5 * 60_000,
    staleTime: isPolling ? 10_000 : 4 * 60_000,
    retry: false,
  })

  // Legacy stop-fast-poll on new run ID (belt + braces with the effect above)
  useEffect(() => {
    if (preTriggerRunId && runId && runId !== preTriggerRunId) {
      setTriggerTime(null)
      setPreTriggerRunId(null)
    }
  }, [runId, preTriggerRunId])

  // Branches list for filter dropdown
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data.results || r.data),
  })

  // Summary stats — keyed on runId so it always matches the visible table data
  const { data: summaryData } = useQuery({
    queryKey: ['purchasing-summary', runId],
    queryFn:  () => purchasingApi.summary().then(r => {
      const d = r.data
      return {
        totalItems:        d.total_items        || 0,
        countA:            d.count_A            || 0,
        countB:            d.count_B            || 0,
        countC:            d.count_C            || 0,
        countX:            d.count_X            || 0,
        itemsWithGap:      d.items_with_gap     || 0,
        totalGapValue:     d.total_gap_value    || 0,
        totalMonthlyValue: d.total_monthly_value|| 0,
        unmatchedSoftech:  d.unmatched_softech  || 0,
      }
    }),
    staleTime: 5 * 60_000,
    retry: false,
  })

  // ── Export state ─────────────────────────────────────────────────────────
  const [exportOpen,   setExportOpen]   = useState(false)
  const [exportBranch, setExportBranch] = useState('')
  const [exportAbc,    setExportAbc]    = useState('')
  const [advBudget,    setAdvBudget]    = useState('')
  const [exporting,    setExporting]    = useState(false)
  const exportRef = useRef(null)

  // Close export dropdown on outside click
  useEffect(() => {
    if (!exportOpen) return
    const handler = (e) => {
      if (exportRef.current && !exportRef.current.contains(e.target)) {
        setExportOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [exportOpen])

  const handleExport = useCallback(async (format, viewOverride) => {
    setExporting(true)
    setExportOpen(false)
    try {
      const view     = viewOverride || (viewTab === 'agg' ? 'aggregated' : 'metrics')
      const viewSlug = viewOverride || (viewTab === 'agg' ? 'network'    : 'branch')

      const res  = await purchasingApi.export({
        format,
        view,
        branch:    exportBranch || undefined,
        abc_class: exportAbc    || undefined,
      })

      const ext  = format === 'csv' ? 'csv' : 'xlsx'
      const mime = format === 'csv'
        ? 'text/csv;charset=utf-8-sig'
        : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

      const blob = new Blob([res.data], { type: mime })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `purchasing-${viewSlug}-${new Date().toISOString().slice(0, 10)}.${ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export failed', err)
      alert('فشل التصدير — تحقق من الاتصال وحاول مرة أخرى')
    } finally {
      setExporting(false)
    }
  }, [viewTab, exportBranch, exportAbc])

  // Experimental ADVANCED pathway — parallel current-vs-advanced comparison sheet.
  const handleAdvancedExport = useCallback(async () => {
    setExporting(true)
    setExportOpen(false)
    try {
      const res  = await purchasingApi.advancedExport({
        branch:    exportBranch || undefined,
        abc_class: exportAbc    || undefined,
        budget:    advBudget    || undefined,
      })
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url
      a.download = `purchasing-advanced-${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Advanced export failed', err)
      alert('فشل التصدير المتقدم — قد يستغرق وقتاً على كل الفروع؛ جرّب فرعاً واحداً')
    } finally {
      setExporting(false)
    }
  }, [exportBranch, exportAbc, advBudget])

  // Advanced SUPPLIER pivot — one row per item, per-branch cols, pack rounding.
  const handleAdvancedPivotExport = useCallback(async () => {
    setExporting(true)
    setExportOpen(false)
    try {
      const res = await purchasingApi.advancedPivotExport({})   // network-wide (all branches)
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url
      a.download = `advanced-supplier-order-${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Advanced pivot export failed', err)
      alert('فشل تصدير طلب الموردين — قد يستغرق دقيقة على كل الأصناف')
    } finally {
      setExporting(false)
    }
  }, [])

  // ── Engine params dialog ──────────────────────────────────────────────────
  const [paramsOpen,  setParamsOpen]  = useState(false)
  const [params,      setParams]      = useState(null)   // loaded from /config/
  const [paramsSaving, setParamsSaving] = useState(false)

  const { data: configData } = useQuery({
    queryKey: ['purchasing-config'],
    queryFn:  () => purchasingApi.config(),
    staleTime: 60_000,
    enabled: !!isAdmin,
  })
  useEffect(() => {
    if (configData?.data) setParams(configData.data)
  }, [configData])

  const handleSaveParams = async () => {
    if (!params) return
    setParamsSaving(true)
    try {
      await purchasingApi.updateConfig(params)
      qc.invalidateQueries(['purchasing-config'])
      setParamsOpen(false)
    } catch (err) {
      alert('خطأ في حفظ الإعدادات: ' + (err?.response?.data?.errors
        ? JSON.stringify(err.response.data.errors) : err.message))
    } finally {
      setParamsSaving(false)
    }
  }

  // Manual trigger mutation
  // opts may include { full: true } to force a full 365-day SOFTECH re-sync.
  const triggerMutation = useMutation({
    mutationFn: (opts = {}) => purchasingApi.triggerRun(opts),
    onSuccess: (_data, opts) => {
      setTriggerTime(Date.now())
      setIsFullTrigger(!!(opts?.full))
      setPreTriggerRunId(runId)         // snapshot old runId to detect new run
      qc.invalidateQueries(['purchasing-run-latest'])
      qc.invalidateQueries(['purchasing-run-active'])   // immediately start polling active
    },
  })

  // Catch-up: robust chunked sales backfill + engine run — used when the
  // scheduled 2 AM sync missed SOFTECH and the sales data went stale.
  const catchupMutation = useMutation({
    mutationFn: () => purchasingApi.catchupSync(),
    onSuccess: () => {
      setTriggerTime(Date.now())
      setIsFullTrigger(true)            // treat like a long run for progress polling
      setPreTriggerRunId(runId)
      qc.invalidateQueries(['purchasing-run-latest'])
      qc.invalidateQueries(['purchasing-run-active'])
    },
    onError: (err) => {
      const msg = err?.response?.data?.detail || 'تعذّرت مزامنة التعويض'
      alert(msg)
    },
  })

  const s = summaryData || {}

  // Sales-data staleness (drives the catch-up button emphasis). Days between the
  // latest sale the run saw and when it ran.
  const saleStaleDays = latestRun?.data_through_date
    ? Math.max(0, Math.floor(
        (new Date(latestRun.finished_at || Date.now()) - new Date(latestRun.data_through_date)) / 86_400_000))
    : 0
  const salesStale = saleStaleDays > 2

  // ── Derived helpers for params modal ────────────────────────────────────────
  const weightsSum = params
    ? +((params.weight_30d || 0) + (params.weight_90d || 0) + (params.weight_365d || 0)).toFixed(4)
    : 0
  const weightsOk = Math.abs(weightsSum - 1) < 0.001

  const handleParamChange = (field, raw) => {
    const v = raw === '' ? '' : parseFloat(raw)
    setParams(prev => ({ ...prev, [field]: v }))
  }

  // Run engine with the currently-displayed params as one-time overrides (does NOT save to DB)
  const handleRunWithParams = () => {
    if (!weightsOk) {
      alert('مجموع الأوزان يجب أن يكون 1.0 قبل التشغيل')
      return
    }
    setPreTriggerRunId(runId)
    triggerMutation.mutate({ params, full: false })
    setParamsOpen(false)
  }

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* ── Engine params modal ──────────────────────────────────────────────── */}
      {paramsOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
          onClick={e => { if (e.target === e.currentTarget) setParamsOpen(false) }}
        >
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm flex flex-col max-h-[90vh]" dir="rtl">
            {/* Modal header — sticky */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
              <h3 className="font-black text-gray-900 text-base">⚙ إعدادات محرك الطلب</h3>
              <button
                onClick={() => setParamsOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none"
              >✕</button>
            </div>

            {/* Scrollable body */}
            <div className="px-5 py-4 space-y-5 overflow-y-auto flex-1 min-h-0">

              {/* Weights section */}
              <div>
                <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">
                  أوزان المعدل الموزون
                </p>
                <div className="space-y-2.5">
                  {[
                    { field: 'weight_30d',  label: 'وزن معدل 30 يوم',  hint: '0.0 – 1.0' },
                    { field: 'weight_90d',  label: 'وزن معدل 90 يوم',  hint: '0.0 – 1.0' },
                    { field: 'weight_365d', label: 'وزن معدل 365 يوم', hint: '0.0 – 1.0' },
                  ].map(({ field, label, hint }) => (
                    <label key={field} className="flex items-center justify-between gap-3">
                      <span className="text-sm text-gray-700 flex-1">{label}</span>
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-400">{hint}</span>
                        <input
                          type="number"
                          step="0.05"
                          min="0"
                          max="1"
                          value={params?.[field] ?? ''}
                          onChange={e => handleParamChange(field, e.target.value)}
                          className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center
                                     focus:outline-none focus:border-brand-400"
                        />
                      </div>
                    </label>
                  ))}
                </div>
                {/* Weights sum indicator */}
                <div className={`mt-2 text-xs font-semibold px-2 py-1 rounded-lg inline-flex items-center gap-1 ${
                  weightsOk ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
                }`}>
                  {weightsOk ? '✓' : '⚠'} المجموع: {weightsSum}
                  {!weightsOk && ' (يجب أن يكون 1.0)'}
                </div>
              </div>

              {/* ── Safety stock tiers ─────────────────────────────────────── */}
              <div className="border border-amber-200 bg-amber-50/50 rounded-xl p-3.5 space-y-3">
                <p className="text-xs font-bold text-amber-800 uppercase tracking-wide">
                  ⚖ كمية الأمان (MinRequired)
                </p>

                {/* Explanation banner */}
                <div className="text-[11px] text-amber-700 bg-amber-100/60 rounded-lg px-3 py-2 leading-relaxed">
                  المنطق: يُضرب المتوسط الشهري × المعامل للحصول على <b>الفعّال</b>،
                  ثم يُختار الصف المناسب من الجدول أدناه.
                  الخانات الثابتة (◼) قابلة للتعديل مباشرة.
                </div>

                {/* Multiplier + high-threshold row */}
                <div className="grid grid-cols-2 gap-2">
                  <label className="flex flex-col gap-0.5">
                    <span className="text-[11px] font-semibold text-gray-600">المعامل (×)</span>
                    <span className="text-[10px] text-gray-400">يُضرب في المتوسط · 1.0 = Excel</span>
                    <input
                      type="number" step="0.1" min="0.5" max="3.0"
                      value={params?.ss_multiplier ?? ''}
                      onChange={e => handleParamChange('ss_multiplier', e.target.value)}
                      className="border border-amber-200 rounded-lg px-2 py-1 text-sm text-center
                                 focus:outline-none focus:border-amber-400 bg-white"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5">
                    <span className="text-[11px] font-semibold text-gray-600">حد الصيغة (≥)</span>
                    <span className="text-[10px] text-gray-400">الفعّال ≥ هذا → تقريب لأعلى</span>
                    <input
                      type="number" step="0.5" min="0.5" max="10"
                      value={params?.ss_high_threshold ?? ''}
                      onChange={e => handleParamChange('ss_high_threshold', e.target.value)}
                      className="border border-amber-200 rounded-lg px-2 py-1 text-sm text-center
                                 focus:outline-none focus:border-amber-400 bg-white"
                    />
                  </label>
                </div>

                {/* Tier table — header */}
                <div className="rounded-lg overflow-hidden border border-amber-200 text-[11px]">
                  <div className="grid grid-cols-3 bg-amber-100 text-amber-800 font-bold px-2 py-1.5 text-center">
                    <span>نطاق الفعّال</span>
                    <span>القاعدة</span>
                    <span>كمية الأمان</span>
                  </div>

                  {/* Tier rows — rendered live using current param values */}
                  {(() => {
                    const m    = parseFloat(params?.ss_multiplier)     || 1.0
                    const high = parseFloat(params?.ss_high_threshold) || 2.0
                    const mid  = parseFloat(params?.ss_tier_mid)       ?? 2.0
                    const low  = parseFloat(params?.ss_tier_low)       ?? 1.0
                    const vlow = parseFloat(params?.ss_tier_vlow)      ?? 0.5

                    const rowCls = 'grid grid-cols-3 px-2 py-1.5 text-center items-center border-t border-amber-100'
                    const inputCls = 'w-14 border border-amber-300 rounded px-1 py-0.5 text-center text-xs bg-white focus:outline-none focus:border-amber-500 mx-auto block'

                    return (
                      <>
                        {/* High-demand tier: formula */}
                        <div className={`${rowCls} bg-red-50`}>
                          <span className="text-red-700 font-semibold">≥ {high}</span>
                          <span className="text-gray-500">تقريب لأعلى<br/><span className="text-[10px]">⌈فعّال⌉</span></span>
                          <span className="text-red-700 font-bold">
                            مثال: {high} → {Math.ceil(high * m)}, {high * 2} → {Math.ceil(high * 2 * m)}
                          </span>
                        </div>

                        {/* Mid tier */}
                        <div className={`${rowCls} bg-orange-50`}>
                          <span className="text-orange-700">0.5 – {high}</span>
                          <span className="text-gray-500">ثابت ◼</span>
                          <input
                            type="number" step="0.5" min="0" max="50"
                            value={params?.ss_tier_mid ?? ''}
                            onChange={e => handleParamChange('ss_tier_mid', e.target.value)}
                            className={inputCls}
                          />
                        </div>

                        {/* Low tier */}
                        <div className={`${rowCls} bg-yellow-50`}>
                          <span className="text-yellow-700">0.16 – 0.5</span>
                          <span className="text-gray-500">ثابت ◼</span>
                          <input
                            type="number" step="0.5" min="0" max="50"
                            value={params?.ss_tier_low ?? ''}
                            onChange={e => handleParamChange('ss_tier_low', e.target.value)}
                            className={inputCls}
                          />
                        </div>

                        {/* Very-low tier */}
                        <div className={`${rowCls} bg-green-50`}>
                          <span className="text-green-700">0.016 – 0.16</span>
                          <span className="text-gray-500">ثابت ◼</span>
                          <input
                            type="number" step="0.5" min="0" max="50"
                            value={params?.ss_tier_vlow ?? ''}
                            onChange={e => handleParamChange('ss_tier_vlow', e.target.value)}
                            className={inputCls}
                          />
                        </div>

                        {/* Zero tier */}
                        <div className={`${rowCls} bg-gray-50`}>
                          <span className="text-gray-400">{'< 0.016'}</span>
                          <span className="text-gray-400">لا يُحسب</span>
                          <span className="text-gray-400 font-bold">0</span>
                        </div>
                      </>
                    )
                  })()}
                </div>

                {/* Live preview examples */}
                <div className="text-[11px] bg-white/80 rounded-lg border border-amber-100 px-2.5 py-2">
                  <div className="font-semibold text-amber-800 mb-1.5">معاينة حية — أمثلة:</div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                    {[0.01, 0.05, 0.3, 0.8, 2, 5, 15].map(avg => {
                      const m    = parseFloat(params?.ss_multiplier)     || 1.0
                      const high = parseFloat(params?.ss_high_threshold) || 2.0
                      const mid  = parseFloat(params?.ss_tier_mid)       ?? 2.0
                      const low  = parseFloat(params?.ss_tier_low)       ?? 1.0
                      const vlow = parseFloat(params?.ss_tier_vlow)      ?? 0.5
                      const eff  = avg * m
                      const ss   = eff >= high ? Math.ceil(eff)
                                 : eff >= 0.5  ? mid
                                 : eff >= 0.16 ? low
                                 : eff >= 0.016 ? vlow
                                 : 0
                      const tier = eff >= high ? 'عالي' : eff >= 0.5 ? 'متوسط' : eff >= 0.16 ? 'منخفض' : eff >= 0.016 ? 'نادر' : 'صفر'
                      return (
                        <div key={avg} className="flex justify-between text-gray-600 py-0.5 border-b border-gray-50">
                          <span>متوسط <b>{avg}</b>/شهر</span>
                          <span>→ أمان <b className="text-amber-700">{ss}</b> <span className="text-gray-400">({tier})</span></span>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Reset all to defaults */}
                <button
                  type="button"
                  onClick={() => {
                    handleParamChange('ss_multiplier',     '1.0')
                    handleParamChange('ss_high_threshold', '2.0')
                    handleParamChange('ss_tier_mid',       '2.0')
                    handleParamChange('ss_tier_low',       '1.0')
                    handleParamChange('ss_tier_vlow',      '0.5')
                  }}
                  className="text-[11px] text-amber-600 hover:text-amber-800 underline"
                >
                  إعادة جميع إعدادات الأمان للافتراضي
                </button>
              </div>

              {/* ABC thresholds */}
              <div>
                <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">
                  حدود تصنيف ABC (تراكمي %)
                </p>
                <div className="space-y-2.5">
                  {[
                    { field: 'abc_a_threshold', label: 'نهاية فئة A (%)', hint: 'افتراضي: 70' },
                    { field: 'abc_b_threshold', label: 'نهاية فئة B (%)', hint: 'افتراضي: 90' },
                  ].map(({ field, label, hint }) => (
                    <label key={field} className="flex items-center justify-between gap-3">
                      <span className="text-sm text-gray-700 flex-1">{label}</span>
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-gray-400">{hint}</span>
                        <input
                          type="number"
                          step="1"
                          min="1"
                          max="99"
                          value={params?.[field] ?? ''}
                          onChange={e => handleParamChange(field, e.target.value)}
                          className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center
                                     focus:outline-none focus:border-brand-400"
                        />
                      </div>
                    </label>
                  ))}
                </div>
                <p className="text-xs text-gray-400 mt-1.5">
                  A ≤ {params?.abc_a_threshold ?? '—'}% &nbsp;·&nbsp;
                  B ≤ {params?.abc_b_threshold ?? '—'}% &nbsp;·&nbsp;
                  C ≤ 100%
                </p>
              </div>

              {/* ── Coverage horizon (per ABC class) ────────────────────────── */}
              <div className="border border-indigo-200 bg-indigo-50/50 rounded-xl p-3.5 space-y-3">
                <p className="text-xs font-bold text-indigo-800 uppercase tracking-wide">
                  📦 أشهر التغطية (لكل فئة ABC)
                </p>

                <div className="text-[11px] text-indigo-700 bg-indigo-100/60 rounded-lg px-3 py-2 leading-relaxed">
                  عدد أشهر الاستهلاك التي يُملأ إليها المخزون لكل فئة.
                  الهدف = <b>الأكبر</b> من ( كمية الأمان ، المتوسط الشهري × أشهر التغطية ).
                  كمية الأمان تبقى ثابتة (شهر واحد) فلا تتضخم الأصناف بطيئة الحركة والمرتفعة الثمن —
                  التغطية تُضاعف فقط الاستهلاك الفعلي.
                  <b> 1.0 = السلوك الحالي.</b>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  {[
                    { field: 'coverage_months_a', label: 'فئة A', tone: 'text-emerald-700' },
                    { field: 'coverage_months_b', label: 'فئة B', tone: 'text-amber-700' },
                    { field: 'coverage_months_c', label: 'فئة C', tone: 'text-sky-700' },
                  ].map(({ field, label, tone }) => (
                    <label key={field} className="flex flex-col gap-0.5">
                      <span className={`text-[11px] font-bold ${tone}`}>{label}</span>
                      <span className="text-[10px] text-gray-400">شهر</span>
                      <input
                        type="number" step="0.25" min="0.1" max="6"
                        value={params?.[field] ?? ''}
                        onChange={e => handleParamChange(field, e.target.value)}
                        className="border border-indigo-200 rounded-lg px-2 py-1 text-sm text-center
                                   focus:outline-none focus:border-indigo-400 bg-white"
                      />
                    </label>
                  ))}
                </div>

                {/* Live preview — how a rate/mo maps to target per class */}
                <div className="text-[11px] bg-white/80 rounded-lg border border-indigo-100 px-2.5 py-2">
                  <div className="font-semibold text-indigo-800 mb-1.5">
                    معاينة — الهدف حسب المتوسط الشهري (مخزون أمان مثال):
                  </div>
                  <div className="space-y-0.5">
                    {(() => {
                      const m    = parseFloat(params?.ss_multiplier)     || 1.0
                      const high = parseFloat(params?.ss_high_threshold) || 2.0
                      const mid  = parseFloat(params?.ss_tier_mid)  ?? 2.0
                      const low  = parseFloat(params?.ss_tier_low)  ?? 1.0
                      const vlow = parseFloat(params?.ss_tier_vlow) ?? 0.5
                      const cA = parseFloat(params?.coverage_months_a) || 1.0
                      const cB = parseFloat(params?.coverage_months_b) || 1.0
                      const cC = parseFloat(params?.coverage_months_c) || 1.0
                      const floorOf = (avg) => {
                        const eff = avg * m
                        return eff >= high ? Math.ceil(eff)
                             : eff >= 0.5  ? mid
                             : eff >= 0.16 ? low
                             : eff >= 0.016 ? vlow : 0
                      }
                      const tgt = (avg, c) => {
                        const t = Math.max(floorOf(avg), avg * c)
                        return Math.round(t * 100) / 100
                      }
                      return [0.08, 0.3, 1, 5].map(avg => (
                        <div key={avg} className="flex justify-between text-gray-600 border-b border-gray-50 py-0.5">
                          <span>متوسط <b>{avg}</b>/شهر</span>
                          <span className="tabular-nums">
                            A→<b className="text-emerald-700">{tgt(avg, cA)}</b> &nbsp;
                            B→<b className="text-amber-700">{tgt(avg, cB)}</b> &nbsp;
                            C→<b className="text-sky-700">{tgt(avg, cC)}</b>
                          </span>
                        </div>
                      ))
                    })()}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    handleParamChange('coverage_months_a', '1.0')
                    handleParamChange('coverage_months_b', '1.0')
                    handleParamChange('coverage_months_c', '1.0')
                  }}
                  className="text-[11px] text-indigo-600 hover:text-indigo-800 underline"
                >
                  إعادة التغطية للافتراضي (1 شهر)
                </button>
              </div>

              {/* ── In-transit freshness cutoff ─────────────────────────────── */}
              <div className="border border-sky-200 bg-sky-50/50 rounded-xl p-3.5 space-y-2">
                <p className="text-xs font-bold text-sky-800 uppercase tracking-wide">
                  🚚 عمر البضاعة بالطريق
                </p>
                <div className="text-[11px] text-sky-700 bg-sky-100/60 rounded-lg px-3 py-2 leading-relaxed">
                  التحويلات الأقدم من هذا العمر تُعتبر مستندات قديمة/غير مطابقة (استُلمت ولم يُربط سند الاستلام، أو مكرّرة/ملغاة)
                  ولا تُحتسب ضمن البضاعة بالطريق. التحويلات الحقيقية تُستلم خلال ~٣ أيام.
                  <b> 0 = بدون حد.</b>
                </div>
                <label className="flex items-center justify-between gap-3">
                  <span className="text-sm text-gray-700 flex-1">أقصى عمر (أيام)</span>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-400">افتراضي 14</span>
                    <input
                      type="number" step="1" min="0" max="365"
                      value={params?.in_transit_max_age_days ?? ''}
                      onChange={e => handleParamChange('in_transit_max_age_days', e.target.value)}
                      className="w-20 border border-sky-200 rounded-lg px-2 py-1 text-sm text-center
                                 focus:outline-none focus:border-sky-400 bg-white"
                    />
                  </div>
                </label>
              </div>

            </div>

            {/* Modal footer — sticky */}
            <div className="flex gap-2 px-5 py-4 border-t border-gray-100 bg-gray-50 rounded-b-2xl shrink-0">
              {/* Save as default (writes to DB) */}
              <button
                onClick={handleSaveParams}
                disabled={paramsSaving || !params}
                className="flex-1 text-xs px-3 py-2 rounded-lg bg-gray-700 text-white hover:bg-gray-800
                           disabled:opacity-50 font-semibold transition-colors"
              >
                {paramsSaving ? '⏳ حفظ...' : '💾 حفظ كافتراضي'}
              </button>
              {/* Run now with these params as one-time overrides */}
              <button
                onClick={handleRunWithParams}
                disabled={triggerMutation.isLoading || !params || !weightsOk}
                className="flex-1 text-xs px-3 py-2 rounded-lg bg-brand-600 text-white hover:bg-brand-700
                           disabled:opacity-50 font-semibold transition-colors"
              >
                {triggerMutation.isLoading ? '⏳ جارٍ...' : '▶ تشغيل الآن'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Page Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-10">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-black text-gray-900">لوحة المشتريات الأمثل</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              تحليل معدلات الطلب · مخزون الأمان · الفجوات · تصنيف ABC
            </p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <RunStatusBadge run={latestRun} lastAttempt={lastAttempt} />

            {/* Export button + dropdown */}
            <div className="relative" ref={exportRef}>
              <button
                onClick={() => setExportOpen(v => !v)}
                disabled={exporting}
                className="text-xs px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-gray-700
                           hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1.5"
              >
                {exporting ? '⏳ جارٍ التصدير...' : '⬇ تصدير'}
              </button>

              {exportOpen && (
                <div className="absolute left-0 top-full mt-1 z-50 bg-white rounded-xl shadow-xl border border-gray-200 p-3 w-72 max-h-[75vh] overflow-y-auto">
                  <p className="text-xs font-semibold text-gray-500 mb-2">خيارات التصدير</p>

                  {/* Branch filter (only relevant in branch view) */}
                  {viewTab === 'branch' && (
                    <div className="mb-2">
                      <label className="text-xs text-gray-500 block mb-1">الفرع</label>
                      <select
                        value={exportBranch}
                        onChange={e => setExportBranch(e.target.value)}
                        className="w-full border border-gray-200 rounded px-2 py-1 text-xs"
                      >
                        <option value="">كل الفروع</option>
                        {branches.map(b => (
                          <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* ABC filter */}
                  <div className="mb-3">
                    <label className="text-xs text-gray-500 block mb-1">تصنيف ABC</label>
                    <select
                      value={exportAbc}
                      onChange={e => setExportAbc(e.target.value)}
                      className="w-full border border-gray-200 rounded px-2 py-1 text-xs"
                    >
                      <option value="">كل الفئات</option>
                      <option value="A">A فقط</option>
                      <option value="B">B فقط</option>
                      <option value="C">C فقط</option>
                      <option value="X">X فقط</option>
                    </select>
                  </div>

                  <div className="flex gap-2 mb-2">
                    <button
                      onClick={() => handleExport('xlsx')}
                      className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-emerald-600 text-white
                                 hover:bg-emerald-700 font-semibold"
                    >
                      📊 Excel
                    </button>
                    <button
                      onClick={() => handleExport('csv')}
                      className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-gray-100 text-gray-700
                                 hover:bg-gray-200 font-semibold"
                    >
                      📄 CSV
                    </button>
                  </div>

                  {/* Pivot Excel — matches Power Query reference format */}
                  <div className="border-t border-gray-100 pt-2">
                    <p className="text-xs text-gray-400 mb-1.5">تصدير المحوري (مطابق لنموذج Power Query)</p>
                    <button
                      onClick={() => handleExport('xlsx', 'pivot')}
                      className="w-full text-xs px-2 py-1.5 rounded-lg bg-indigo-600 text-white
                                 hover:bg-indigo-700 font-semibold flex items-center justify-center gap-1.5"
                    >
                      🗂 Pivot Excel (أولويات النواقص)
                    </button>
                  </div>

                  {/* Experimental advanced pathway — parallel comparison */}
                  <div className="border-t border-gray-100 pt-2">
                    <p className="text-xs text-gray-400 mb-1.5">تحليل متقدم (تجريبى — مقارنة الحالى بالمتقدم)</p>
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <span className="text-[11px] text-gray-500 shrink-0">💰 ميزانية الشراء</span>
                      <input type="number" min="0" step="1000" value={advBudget}
                        onChange={e => setAdvBudget(e.target.value)} placeholder="بلا حد"
                        className="flex-1 border border-gray-200 rounded-lg px-2 py-1 text-xs text-center focus:outline-none focus:border-fuchsia-400" />
                      <span className="text-[10px] text-gray-400">ج.م</span>
                    </div>
                    <button
                      onClick={handleAdvancedExport}
                      className="w-full text-xs px-2 py-1.5 rounded-lg bg-fuchsia-600 text-white
                                 hover:bg-fuchsia-700 font-semibold flex items-center justify-center gap-1.5"
                      title="محرك موازٍ لا يمسّ الحساب الحالى: تنقية الجملة، الاتجاه، الموسمية، أمان إحصائى، نقطة إعادة الطلب، تصنيف الطلب، وأولوية الشراء حسب العائد ضمن ميزانية. يُفضّل اختيار فرع واحد."
                    >
                      🧪 تحليل متقدم (A–E)
                    </button>
                    <p className="text-[10px] text-gray-400 mt-1">حدّد ميزانية لترتيب المشتريات حسب العائد وتمييز الممول/المؤجل. على كل الفروع قد يستغرق دقيقة — اختر فرعاً للأسرع.</p>

                    <button
                      onClick={handleAdvancedPivotExport}
                      className="w-full mt-2 text-xs px-2 py-1.5 rounded-lg bg-fuchsia-100 text-fuchsia-800
                                 hover:bg-fuchsia-200 font-semibold flex items-center justify-center gap-1.5 border border-fuchsia-300"
                      title="ورقة طلب الموردين: صف واحد لكل صنف، أعمدة الفروع، القطع لكل فرع بوحدات كاملة والشراء بعبوات كاملة. تشمل ورقة شرح للطريقة."
                    >
                      📦 طلب الموردين (محورى — صف لكل صنف)
                    </button>
                    <p className="text-[10px] text-gray-400 mt-1">صف واحد لكل صنف · قطع كل فرع (وحدات) · شراء بعبوات كاملة · ورقة «الشرح» بالملف.</p>
                  </div>
                </div>
              )}
            </div>

            {isAdmin && (
              <div className="flex items-center gap-2 flex-wrap">
                {/* ── Catch-up ── robust chunked backfill for when the scheduled
                    sync missed SOFTECH and sales went stale. Emphasised when stale. */}
                <button
                  onClick={() => {
                    if (isRunning || catchupMutation.isLoading) return
                    if (!window.confirm(
                      (salesStale ? `المبيعات متأخرة ${saleStaleDays} يوم. ` : '') +
                      'مزامنة تعويضية: تجلب المبيعات المتأخرة على دفعات ثم تعيد تشغيل المحرك.\n'
                      + 'قد تستغرق عدة دقائق. هل تريد المتابعة؟'
                    )) return
                    catchupMutation.mutate()
                  }}
                  disabled={isRunning || triggerMutation.isLoading || catchupMutation.isLoading}
                  className={`text-xs px-3 py-1.5 rounded-lg border font-semibold transition-colors
                             flex items-center gap-1.5 disabled:opacity-40 ${
                    salesStale
                      ? 'border-red-400 bg-red-50 text-red-700 hover:bg-red-100 animate-pulse'
                      : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                  title="تعويض المبيعات المتأخرة (مزامنة على دفعات لا تتوقف عند الفجوات الكبيرة) ثم إعادة تشغيل المحرك — استخدمها إذا لم تصل مزامنة الـ2 صباحاً إلى SOFTECH"
                >
                  {catchupMutation.isLoading ? '⏳ جارٍ...' : '⟳ تعويض المبيعات'}
                  {salesStale && !catchupMutation.isLoading && ` (${saleStaleDays}ي)`}
                </button>

                {/* ── Full Sync 365d ── re-syncs the complete rolling year from SOFTECH */}
                <button
                  onClick={() => {
                    if (isRunning) return
                    if (!window.confirm(
                      'مزامنة كاملة 365 يوم من SOFTECH — ستستغرق 5 – 8 دقائق.\nهل تريد المتابعة؟'
                    )) return
                    triggerMutation.mutate({ full: true })
                  }}
                  disabled={isRunning || triggerMutation.isLoading}
                  className="text-xs px-3 py-1.5 rounded-lg border border-amber-400 bg-amber-50
                             text-amber-700 hover:bg-amber-100 disabled:opacity-40 font-semibold
                             transition-colors flex items-center gap-1.5"
                  title="مزامنة كاملة 365 يوم من SOFTECH — تستغرق 5-8 دقائق"
                >
                  🔄 مزامنة كاملة
                </button>

                {/* ── Settings + Quick Run ── */}
                <div className="flex items-center rounded-lg overflow-hidden border border-brand-600 shadow-sm">
                  {/* ⚙ Settings — opens params modal */}
                  <button
                    onClick={() => setParamsOpen(true)}
                    className="text-xs px-2.5 py-1.5 bg-white text-brand-700 hover:bg-brand-50
                               border-r border-brand-200 transition-colors"
                    title="ضبط معاملات المحرك"
                  >
                    ⚙
                  </button>
                  {/* ▶ Run — incremental (gap-based lookback, typically < 1 min) */}
                  <button
                    onClick={() => triggerMutation.mutate({ full: false })}
                    disabled={isRunning || triggerMutation.isLoading}
                    className="text-xs px-3 py-1.5 bg-brand-600 text-white hover:bg-brand-700
                               disabled:opacity-50 font-semibold transition-colors"
                    title="تشغيل سريع — يزامن من آخر تاريخ بيانات فقط (< دقيقة)"
                  >
                    {isRunning ? '⏳ جارٍ...' : '▶ تشغيل'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Engine progress banner — visible while a run is active ── */}
      {isRunning && <EngineRunProgress run={activeRunData} />}

      <div className="max-w-screen-2xl mx-auto px-4 py-6 space-y-5">

        {/* Summary cards */}
        {summaryData && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
            <SummaryCard
              label="إجمالي الأصناف"
              value={fmt(s.totalItems, 0)}
              color="brand"
            />
            <SummaryCard
              label="فئة A (أعلى 70%)"
              value={fmt(s.countA, 0)}
              color="green"
              sub="الأعلى قيمةً"
            />
            <SummaryCard
              label="فئة B (70–90%)"
              value={fmt(s.countB, 0)}
              color="brand"
              sub="متوسطة"
            />
            <SummaryCard
              label="فئة C (90–100%)"
              value={fmt(s.countC, 0)}
              color="brand"
              sub="الأقل قيمةً"
            />
            <SummaryCard
              label="أصناف تحتاج شراء"
              value={fmt(s.itemsWithGap, 0)}
              color={s.itemsWithGap > 0 ? 'red' : 'green'}
              sub={s.itemsWithGap > 0 ? 'فجوة في المخزون' : 'مخزون كافٍ'}
            />
            <SummaryCard
              label="قيمة الفجوة (ج.م)"
              value={`${fmt(s.totalGapValue, 0)}`}
              color={s.totalGapValue > 0 ? 'amber' : 'green'}
              sub="إجمالي المطلوب شراؤه"
            />
            <SummaryCard
              label="قيمة مبيعات/شهر"
              value={`${fmt(s.totalMonthlyValue, 0)}`}
              color="brand"
              sub={s.unmatchedSoftech > 0 ? `${fmt(s.unmatchedSoftech, 0)} صنف غير مربوط` : 'ج.م شبكة كاملة'}
            />
          </div>
        )}

        {/* Main card */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">

          {/* View tabs */}
          <div className="flex items-center border-b border-gray-100 px-4 pt-3 gap-1">
            {VIEW_TABS.map(t => (
              <button
                key={t.value}
                onClick={() => handleViewTab(t.value)}
                className={`px-4 py-2 text-sm font-semibold rounded-t-lg transition-colors ${
                  viewTab === t.value
                    ? 'bg-brand-600 text-white'
                    : 'text-gray-500 hover:text-gray-800 hover:bg-gray-50'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* ABC filter + search bar — hidden on Transfer and Lost Sales tabs */}
          {viewTab !== 'transfer' && viewTab !== 'lostsales' && (
            <>
              <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-gray-100">
                {ABC_TABS.map(t => (
                  <button
                    key={t.value}
                    onClick={() => setAbcFilter(t.value)}
                    className={`px-3 py-1 text-xs font-bold rounded-full border transition-colors ${
                      abcFilter === t.value
                        ? 'bg-brand-600 text-white border-brand-600'
                        : 'border-gray-200 text-gray-500 hover:border-gray-400'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}

                {/* Advanced filters toggle */}
                <button
                  onClick={() => setShowAdvFilters(v => !v)}
                  className={`px-3 py-1 text-xs font-semibold rounded-full border transition-colors ${
                    showAdvFilters
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'border-gray-200 text-gray-500 hover:border-indigo-400 hover:text-indigo-600'
                  }`}
                >
                  🔍 {showAdvFilters ? 'إخفاء الفلاتر' : 'فلاتر متقدمة'}
                </button>

                <div className="mr-auto">
                  <input
                    type="text"
                    placeholder="ابحث عن صنف..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-48 focus:outline-none focus:border-brand-400"
                  />
                </div>
              </div>

              {/* Advanced filter panel (collapsible) */}
              {showAdvFilters && (
                <AdvancedFiltersBar
                  opts={filterOpts}
                  filters={itemFilters}
                  onChange={setItemFilters}
                />
              )}
            </>
          )}

          {/* Table content */}
          {viewTab === 'agg' ? (
            <AggregatedTab
              abcFilter={abcFilter}
              search={search}
              ordering={ordering}
              onSort={setOrdering}
              runId={runId}
              itemFilters={itemFilters}
            />
          ) : viewTab === 'branch' ? (
            <BranchTab
              abcFilter={abcFilter}
              search={search}
              ordering={ordering}
              onSort={setOrdering}
              branches={branches}
              runId={runId}
              itemFilters={itemFilters}
            />
          ) : viewTab === 'transfer' ? (
            <TransferRecsTab isAdmin={isAdmin} />
          ) : (
            <LostSalesTab />
          )}
        </div>

        {/* Engine info footer */}
        <div className="text-xs text-gray-400 text-center pb-4 space-y-0.5">
          <div>البيانات من SOFTECH ERP (آخر 365 يوم) · الرصيد الحالي من stkbal مباشرةً · تُحدَّث يدوياً</div>
          {params && (
            <div className="font-mono">
              المعادلة الحالية: موزون = معدل30×{((params.weight_30d||0)*100).toFixed(0)}%
              {' + '}معدل90×{((params.weight_90d||0)*100).toFixed(0)}%
              {' + '}معدل365×{((params.weight_365d||0)*100).toFixed(0)}%
              &nbsp;·&nbsp; ABC: A≤{params.abc_a_threshold}% / B≤{params.abc_b_threshold}%
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
