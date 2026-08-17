/**
 * pages/RecommendationsPage.jsx
 *
 * Recommendations Intelligence Dashboard
 *
 * Tabs:
 *   🔗 اقترانات الأصناف  — FBT pairs explorer (sortable, filterable, confidence/lift bars)
 *   👤 توصيات العملاء    — Customer recs preview (search customer → personalised list)
 *   🕓 سجل التشغيل       — Engine run history timeline
 *
 * Features:
 *   • Engine status card with trigger button
 *   • KPI row: pairs generated, invoices scanned, customers scored
 *   • FBT pairs: search, confidence bar, lift badge, sort by score/confidence/lift
 *   • Customer recs: freetext customer search + inline rec chips
 *   • Run history: timeline with status badge + stats
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { recommendationsApi, customersApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt  = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: d })
const fmtP = (n)        => (Number(n || 0) * 100).toFixed(1) + '%'
const fmtF = (n, d = 2) => Number(n || 0).toFixed(d)

function timeAgo(dt) {
  if (!dt) return '—'
  try {
    return formatDistanceToNow(new Date(dt), { addSuffix: true, locale: ar })
  } catch { return dt }
}

function fmtDate(dt) {
  if (!dt) return '—'
  try { return format(new Date(dt), 'dd/MM/yyyy HH:mm') } catch { return dt }
}

const RUN_STATUS = {
  running: { label: 'جارٍ',  cls: 'bg-blue-100  text-blue-700  ring-1 ring-blue-300',  dot: 'bg-blue-500  animate-pulse' },
  success: { label: 'ناجح',  cls: 'bg-green-100 text-green-700 ring-1 ring-green-300', dot: 'bg-green-500' },
  failed:  { label: 'فاشل',  cls: 'bg-red-100   text-red-700   ring-1 ring-red-300',   dot: 'bg-red-500' },
}

// ── Shared small components ───────────────────────────────────────────────────

function KpiCard({ icon, label, value, sub, color = 'indigo' }) {
  const colors = {
    indigo:  'border-indigo-100 bg-indigo-50  text-indigo-700  ring-indigo-200',
    emerald: 'border-emerald-100 bg-emerald-50 text-emerald-700 ring-emerald-200',
    sky:     'border-sky-100   bg-sky-50     text-sky-700     ring-sky-200',
    amber:   'border-amber-100  bg-amber-50   text-amber-700   ring-amber-200',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="text-xl mb-1">{icon}</div>
      <div className="text-xs font-medium opacity-70">{label}</div>
      <div className="text-2xl font-black mt-0.5">{value}</div>
      {sub && <div className="text-xs opacity-60 mt-0.5">{sub}</div>}
    </div>
  )
}

function ConfBar({ value, max = 1, color = 'bg-indigo-400' }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="h-2 rounded-full bg-gray-100 flex-1 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums w-10 text-right text-gray-500">{fmtP(value)}</span>
    </div>
  )
}

function LiftBadge({ value }) {
  const v = Number(value || 0)
  const cls = v >= 3
    ? 'bg-emerald-100 text-emerald-700'
    : v >= 1.5
    ? 'bg-blue-100 text-blue-700'
    : 'bg-gray-100 text-gray-500'
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-semibold ${cls}`}>
      ×{fmtF(v, 1)}
    </span>
  )
}

// ── Engine Status Strip ───────────────────────────────────────────────────────

function EngineStatusStrip({ onTriggerSuccess }) {
  const { user } = useAuthStore()
  const isAdmin  = ['admin', 'supervisor'].includes(user?.role)
  const qc       = useQueryClient()

  const { data: run, isLoading } = useQuery({
    queryKey: ['rec-latest-run'],
    queryFn:  () => recommendationsApi.latestRun().then(r => r.data),
    staleTime: 30_000,
    retry: false,
  })

  const [params, setParams] = useState({ lookback_days: 365, min_support: 0.001, min_confidence: 0.05 })
  const [showConfig, setShowConfig] = useState(false)

  const triggerMutation = useMutation({
    mutationFn: () => recommendationsApi.trigger(params),
    onSuccess: () => {
      qc.invalidateQueries(['rec-latest-run'])
      qc.invalidateQueries(['rec-runs-history'])
      onTriggerSuccess?.()
    },
  })

  // Poll while running
  useEffect(() => {
    if (run?.status !== 'running') return
    const t = setInterval(() => {
      qc.invalidateQueries(['rec-latest-run'])
    }, 4000)
    return () => clearInterval(t)
  }, [run?.status, qc])

  const st = run ? RUN_STATUS[run.status] : null

  return (
    <div className="border-b border-gray-100 bg-white px-6 py-4">
      <div className="flex flex-wrap items-center gap-4">
        {/* Status badge */}
        <div className="flex items-center gap-2">
          {isLoading ? (
            <div className="h-4 w-28 bg-gray-100 animate-pulse rounded" />
          ) : run ? (
            <>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${st?.cls}`}>
                <span className={`inline-block w-2 h-2 rounded-full ${st?.dot}`} />
                {st?.label}
              </span>
              <span className="text-xs text-gray-400">{timeAgo(run.started_at)}</span>
            </>
          ) : (
            <span className="text-xs text-gray-400">لم يتم التشغيل بعد</span>
          )}
        </div>

        {/* KPIs inline */}
        {run?.status === 'success' && (
          <div className="flex items-center gap-4 text-sm text-gray-600">
            <span><strong className="text-gray-800">{fmt(run.pairs_generated)}</strong> اقتران</span>
            <span><strong className="text-gray-800">{fmt(run.invoices_scanned)}</strong> فاتورة</span>
            <span><strong className="text-gray-800">{fmt(run.customers_scored)}</strong> عميل</span>
          </div>
        )}

        {run?.status === 'failed' && run.error_message && (
          <span className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded">
            {run.error_message.slice(0, 120)}
          </span>
        )}

        {/* Trigger controls (admin only) */}
        {isAdmin && (
          <div className="flex items-center gap-2 mr-auto">
            <button
              onClick={() => setShowConfig(v => !v)}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 transition-colors"
            >
              ⚙️ إعدادات
            </button>
            <button
              onClick={() => triggerMutation.mutate()}
              disabled={triggerMutation.isLoading || run?.status === 'running'}
              className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white font-medium
                         hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50
                         transition-colors flex items-center gap-1.5"
            >
              {triggerMutation.isLoading || run?.status === 'running'
                ? <><span className="animate-spin">⟳</span> جارٍ…</>
                : '▶ تشغيل المحرك'
              }
            </button>
          </div>
        )}
      </div>

      {/* Config panel */}
      {showConfig && isAdmin && (
        <div className="mt-3 flex flex-wrap gap-4 p-3 bg-gray-50 rounded-xl border border-gray-100 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-gray-500 font-medium">فترة الرصد (أيام)</span>
            <input type="number" min={30} max={1825} value={params.lookback_days}
              onChange={e => setParams(p => ({ ...p, lookback_days: +e.target.value }))}
              className="border border-gray-200 rounded px-2 py-1 w-24 focus:outline-none focus:border-indigo-400" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-gray-500 font-medium">الحد الأدنى للدعم</span>
            <input type="number" min={0.0001} max={0.1} step={0.001} value={params.min_support}
              onChange={e => setParams(p => ({ ...p, min_support: +e.target.value }))}
              className="border border-gray-200 rounded px-2 py-1 w-24 focus:outline-none focus:border-indigo-400" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-gray-500 font-medium">الحد الأدنى للثقة</span>
            <input type="number" min={0.01} max={1} step={0.01} value={params.min_confidence}
              onChange={e => setParams(p => ({ ...p, min_confidence: +e.target.value }))}
              className="border border-gray-200 rounded px-2 py-1 w-24 focus:outline-none focus:border-indigo-400" />
          </label>
        </div>
      )}
    </div>
  )
}

// ── Tab: FBT Pairs ────────────────────────────────────────────────────────────

const SORT_OPTS = [
  { value: '-score',          label: 'الدرجة ↓' },
  { value: '-confidence',     label: 'الثقة ↓' },
  { value: '-lift',           label: 'الرفع ↓' },
  { value: '-co_occurrences', label: 'التكرار ↓' },
  { value: 'score',           label: 'الدرجة ↑' },
]

function FBTPairsTab() {
  const [search,   setSearch]   = useState('')
  const [ordering, setOrdering] = useState('-score')
  const [page,     setPage]     = useState(1)
  const PAGE_SIZE = 50

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['rec-fbt-list', search, ordering, page],
    queryFn: () => recommendationsApi.fbtList({
      search:    search   || undefined,
      ordering,
      page,
      page_size: PAGE_SIZE,
    }).then(r => r.data),
    staleTime: 60_000,
    keepPreviousData: true,
  })

  const rows  = data?.results || data || []
  const count = data?.count   || rows.length
  const pages = Math.ceil(count / PAGE_SIZE)

  const handleSearch = useCallback(e => {
    setSearch(e.target.value)
    setPage(1)
  }, [])

  return (
    <div dir="rtl">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 p-4 border-b border-gray-100">
        <div className="relative flex-1 min-w-48">
          <span className="absolute inset-y-0 right-3 flex items-center text-gray-400 pointer-events-none text-sm">🔍</span>
          <input
            value={search}
            onChange={handleSearch}
            placeholder="ابحث باسم الصنف أو كوده…"
            className="w-full border border-gray-200 rounded-xl pr-9 pl-3 py-2 text-sm focus:outline-none focus:border-indigo-400"
          />
        </div>
        <select value={ordering} onChange={e => setOrdering(e.target.value)}
          className="border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-indigo-400">
          {SORT_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span className="text-xs text-gray-400">{fmt(count)} اقتران</span>
        {isFetching && <span className="text-xs text-indigo-500 animate-pulse">تحميل…</span>}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="p-12 text-center text-gray-400">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center text-gray-400">لا توجد اقترانات</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100 text-gray-500 text-xs">
                <th className="text-right px-4 py-3 font-medium">الصنف الأساسي</th>
                <th className="text-right px-4 py-3 font-medium">الصنف المقترن</th>
                <th className="text-right px-4 py-3 font-medium w-32">الثقة</th>
                <th className="text-right px-4 py-3 font-medium w-24">الرفع</th>
                <th className="text-right px-4 py-3 font-medium w-20">الدعم</th>
                <th className="text-right px-4 py-3 font-medium w-20">التكرار</th>
                <th className="text-right px-4 py-3 font-medium w-24">الدرجة</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.id}
                  className={`border-b border-gray-50 hover:bg-indigo-50/30 transition-colors
                              ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/40'}`}>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-800 leading-tight">{r.item_a_name}</div>
                    <div className="text-xs text-gray-400">{r.item_a_code}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-indigo-700 leading-tight">{r.item_b_name}</div>
                    <div className="text-xs text-gray-400">{r.item_b_code}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <ConfBar value={r.confidence} />
                  </td>
                  <td className="px-4 py-2.5">
                    <LiftBadge value={r.lift} />
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-500 tabular-nums">
                    {fmtP(r.support)}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-700 tabular-nums font-medium">
                    {fmt(r.co_occurrences)}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-700 tabular-nums font-semibold">
                    {fmtF(r.score, 3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-2 py-4 border-t border-gray-100">
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs hover:bg-gray-50 disabled:opacity-40">
            ‹ السابق
          </button>
          <span className="text-xs text-gray-500">{page} / {pages}</span>
          <button onClick={() => setPage(p => Math.min(pages, p + 1))} disabled={page === pages}
            className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs hover:bg-gray-50 disabled:opacity-40">
            التالي ›
          </button>
        </div>
      )}
    </div>
  )
}

// ── Tab: Customer Recommendations ─────────────────────────────────────────────

function CustomerRecsTab() {
  const [query,        setQuery]        = useState('')
  const [debouncedQ,   setDebouncedQ]   = useState('')
  const [selectedCust, setSelectedCust] = useState(null)
  const timer = useRef(null)

  const handleQueryChange = e => {
    setQuery(e.target.value)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setDebouncedQ(e.target.value), 350)
  }

  // Customer search
  const { data: custResults = [] } = useQuery({
    queryKey: ['customer-search-recs', debouncedQ],
    queryFn: () => customersApi.list({ search: debouncedQ, page_size: 10 })
      .then(r => r.data.results || r.data),
    enabled: debouncedQ.length >= 2,
    staleTime: 30_000,
  })

  const [clinicalFilter, setClinicalFilter] = useState(true)

  // Recs for selected customer — uses the new API endpoint with clinical filter
  const { data: recsData, isLoading: recsLoading } = useQuery({
    queryKey: ['rec-customer-preview', selectedCust?.id, clinicalFilter],
    queryFn: () => customersApi.recommendations(selectedCust.id, {
      limit: 20,
      clinical_filter: clinicalFilter,
    }).then(r => r.data),
    enabled: !!selectedCust,
    staleTime: 60_000,
  })
  const recs = recsData?.recommendations || []

  return (
    <div dir="rtl" className="p-4">
      <p className="text-sm text-gray-500 mb-4">
        ابحث عن عميل لعرض التوصيات الشخصية المبنية على سلوك الشراء واقترانات الأصناف.
      </p>

      {/* Customer search */}
      <div className="relative max-w-md mb-6">
        <span className="absolute inset-y-0 right-3 flex items-center text-gray-400 pointer-events-none">👤</span>
        <input
          value={query}
          onChange={handleQueryChange}
          placeholder="اسم العميل أو رقم الهاتف…"
          className="w-full border border-gray-200 rounded-xl pr-9 pl-3 py-2.5 text-sm focus:outline-none focus:border-indigo-400"
        />
        {/* Dropdown suggestions */}
        {debouncedQ.length >= 2 && custResults.length > 0 && !selectedCust && (
          <ul className="absolute top-full right-0 left-0 mt-1 bg-white border border-gray-200
                         rounded-xl shadow-lg z-30 overflow-hidden">
            {custResults.map(c => (
              <li key={c.id}>
                <button
                  className="w-full text-right px-4 py-2.5 text-sm hover:bg-indigo-50 transition-colors
                             flex items-center justify-between"
                  onClick={() => { setSelectedCust(c); setQuery(c.name); setDebouncedQ('') }}
                >
                  <span className="font-medium">{c.name}</span>
                  <span className="text-xs text-gray-400">{c.phone || c.mobile_phone}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {selectedCust && (
        <>
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div>
              <h3 className="font-semibold text-gray-800">
                توصيات لـ <span className="text-indigo-700">{selectedCust.name}</span>
              </h3>
              {selectedCust.detected_conditions?.length > 0 && (
                <div className="flex gap-1 mt-1 flex-wrap">
                  {selectedCust.detected_conditions.slice(0, 4).map(c => (
                    <span key={c} className="text-[10px] bg-orange-50 text-orange-700 border border-orange-200 px-2 py-0.5 rounded-full">
                      💊 {c}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              {/* Clinical safety toggle */}
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <input
                  type="checkbox"
                  checked={clinicalFilter}
                  onChange={e => setClinicalFilter(e.target.checked)}
                  className="accent-indigo-600"
                />
                <span className={clinicalFilter ? 'text-green-700 font-semibold' : 'text-gray-400'}>
                  {clinicalFilter ? '🛡️ فلتر السلامة السريرية مفعَّل' : '⚠️ فلتر السلامة معطَّل'}
                </span>
              </label>
              <button onClick={() => { setSelectedCust(null); setQuery('') }}
                className="text-xs text-gray-400 hover:text-gray-600 transition-colors">
                ✕ مسح
              </button>
            </div>
          </div>
          {clinicalFilter && selectedCust.detected_conditions?.length > 0 && (
            <div className="mb-3 text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
              يتم تصفية الأصناف التي تتعارض مع أدوية هذا العميل المزمنة تلقائياً.
            </div>
          )}

          {recsLoading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-20 rounded-xl bg-gray-100 animate-pulse" />
              ))}
            </div>
          ) : recs.length === 0 ? (
            <div className="py-8 text-center text-gray-400 text-sm">
              لا توجد توصيات لهذا العميل بعد
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {recs.map(rec => (
                <div key={rec.item_id || rec.id}
                  className="rounded-xl border border-gray-100 bg-white p-3 hover:border-indigo-200
                             hover:shadow-sm transition-all group">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm text-gray-800 leading-tight break-words">
                        {rec.item_name}
                      </div>
                      <div className="text-xs text-gray-400 font-mono mt-0.5">{rec.softech_id}</div>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      {rec.is_chronic && (
                        <span className="text-[10px] bg-orange-50 text-orange-600 px-1.5 py-0.5 rounded border border-orange-200">💊 مزمن</span>
                      )}
                      {rec.clinical_safe === true && clinicalFilter && (
                        <span className="text-[10px] bg-green-50 text-green-600 px-1.5 py-0.5 rounded border border-green-200">🛡️ آمن</span>
                      )}
                    </div>
                  </div>
                  {rec.reason && (
                    <div className="mt-1.5 text-xs text-indigo-600 bg-indigo-50 rounded px-2 py-1">
                      {rec.reason}
                    </div>
                  )}
                  <div className="mt-1.5">
                    <ConfBar value={Math.min(rec.score, 1)} color="bg-indigo-400" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {!selectedCust && (
        <div className="py-12 text-center text-gray-300 text-4xl select-none">
          <div>👤</div>
          <div className="text-sm text-gray-400 mt-2">ابدأ بالبحث عن عميل</div>
        </div>
      )}
    </div>
  )
}

// ── Tab: Run History ──────────────────────────────────────────────────────────

function RunHistoryTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['rec-runs-history'],
    queryFn: () => recommendationsApi.runsHistory({ page_size: 30 }).then(r => r.data),
    staleTime: 30_000,
  })

  const runs = data?.results || data || []

  if (isLoading) return (
    <div className="p-12 text-center text-gray-400">جارٍ التحميل…</div>
  )

  if (runs.length === 0) return (
    <div className="p-12 text-center text-gray-400">لا يوجد سجل تشغيل بعد</div>
  )

  return (
    <div dir="rtl" className="p-4 space-y-3">
      {runs.map((run, i) => {
        const st = RUN_STATUS[run.status] || RUN_STATUS.failed
        const duration = run.finished_at
          ? Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)
          : null
        return (
          <div key={run.id}
            className="rounded-xl border border-gray-100 bg-white p-4 hover:border-indigo-100 transition-colors">
            <div className="flex flex-wrap items-center gap-3">
              {/* Run number + status */}
              <span className="text-xs text-gray-400 font-mono w-8">#{run.id}</span>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${st.cls}`}>
                <span className={`inline-block w-1.5 h-1.5 rounded-full ${st.dot}`} />
                {st.label}
              </span>

              {/* Date */}
              <span className="text-xs text-gray-500">{fmtDate(run.started_at)}</span>
              {duration !== null && (
                <span className="text-xs text-gray-400">{duration}ث</span>
              )}

              {/* Stats (success only) */}
              {run.status === 'success' && (
                <div className="flex items-center gap-3 mr-auto text-xs text-gray-600">
                  <span><strong className="text-gray-800">{fmt(run.pairs_generated)}</strong> اقتران</span>
                  <span><strong className="text-gray-800">{fmt(run.invoices_scanned)}</strong> فاتورة</span>
                  <span><strong className="text-gray-800">{fmt(run.customers_scored)}</strong> عميل</span>
                </div>
              )}
            </div>

            {/* Config used */}
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-400">
              <span>فترة: <strong>{run.lookback_days}</strong> يوم</span>
              <span>دعم ≥ <strong>{run.min_support}</strong></span>
              <span>ثقة ≥ <strong>{run.min_confidence}</strong></span>
            </div>

            {/* Error message */}
            {run.status === 'failed' && run.error_message && (
              <div className="mt-2 text-xs text-red-600 bg-red-50 rounded px-2 py-1.5">
                {run.error_message}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Root Page ─────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'fbt',     label: '🔗 اقترانات الأصناف' },
  { id: 'customer', label: '👤 توصيات العملاء' },
  { id: 'history',  label: '🕓 سجل التشغيل' },
]

export default function RecommendationsPage() {
  const [activeTab, setActiveTab] = useState('fbt')
  const qc = useQueryClient()

  return (
    <div dir="rtl" className="flex flex-col h-full bg-gray-50 min-h-screen">

      {/* Page header */}
      <div className="bg-white border-b border-gray-100 px-6 py-5">
        <h1 className="text-xl font-black text-gray-900">محرك التوصيات الذكية</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          اقترانات الأصناف FBT · التوصيات الشخصية للعملاء
        </p>
      </div>

      {/* Engine status strip */}
      <EngineStatusStrip onTriggerSuccess={() => qc.invalidateQueries(['rec-runs-history'])} />

      {/* KPI row — latest run */}
      <LatestRunKpis />

      {/* Tab bar */}
      <div className="bg-white border-b border-gray-100 px-6">
        <div className="flex gap-1 -mb-px">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors
                ${activeTab === t.id
                  ? 'border-indigo-500 text-indigo-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-200'}`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto bg-white">
        {activeTab === 'fbt'      && <FBTPairsTab />}
        {activeTab === 'customer' && <CustomerRecsTab />}
        {activeTab === 'history'  && <RunHistoryTab />}
      </div>
    </div>
  )
}

// ── KPI row from latest successful run ───────────────────────────────────────

function LatestRunKpis() {
  const { data: run } = useQuery({
    queryKey: ['rec-latest-run'],
    queryFn:  () => recommendationsApi.latestRun().then(r => r.data),
    staleTime: 30_000,
    retry: false,
  })

  if (!run || run.status !== 'success') return null

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-6 py-4 bg-white border-b border-gray-100">
      <KpiCard icon="🔗" label="إجمالي الاقترانات" value={fmt(run.pairs_generated)} color="indigo" />
      <KpiCard icon="🧾" label="الفواتير المحللة"   value={fmt(run.invoices_scanned)} color="sky" />
      <KpiCard icon="👥" label="العملاء المُوصَّى لهم" value={fmt(run.customers_scored)} color="emerald" />
      <KpiCard
        icon="⏱️"
        label="آخر تشغيل"
        value={timeAgo(run.started_at)}
        sub={`ثقة ≥ ${(run.min_confidence * 100).toFixed(0)}% · فترة ${run.lookback_days} يوم`}
        color="amber"
      />
    </div>
  )
}
