/**
 * DataFreshnessBar — top-of-screen data freshness + sync.
 *
 * Two modes:
 *  • domains mode (NEW): pass domains={['stock']} to show PER-DOMAIN freshness
 *    (last successful sync of exactly the data this module relies on) with an
 *    optional fast-lane refresh button. Source: /api/sync/freshness/.
 *  • KPI mode (legacy): pass dataThrough/daysElapsed/… to show the KPI board's
 *    MTD completeness + a rollup-rebuild button. Unchanged.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { syncApi, kpiApi } from '../api/client'

// Domains served by the fast lane (stock+sales+branches, ~15s to refresh).
const FAST_DOMAINS = new Set(['stock', 'sales', 'branches'])
// Domains the SOFTECH sync trigger can refresh at all (fast or slow lane).
// Custom-source domains (purchases, expiry) are synced by their own engines, so
// the sync-trigger refresh button must NOT appear for them.
const SYNC_REFRESHABLE = new Set(['stock', 'sales', 'branches', 'catalog', 'customers', 'users'])

function fmtAge(seconds) {
  if (seconds == null) return 'لم تتم مزامنة'
  const m = Math.round(seconds / 60)
  if (m < 1) return 'الآن'
  if (m < 60) return `منذ ${m} د`
  const h = Math.floor(m / 60)
  if (h < 24) return `منذ ${h} س${m % 60 ? ` ${m % 60} د` : ''}`
  return `منذ ${Math.floor(h / 24)} يوم`
}

function DomainFreshness({ domains, canEdit, compact }) {
  const qc = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const { data } = useQuery({
    queryKey: ['data-freshness', domains.join(',')],
    queryFn: () => syncApi.freshness(domains).then(r => r.data),
    refetchInterval: refreshing ? 4000 : 60000,
  })

  const doms = data?.domains || {}
  const list = domains.map(k => ({ key: k, ...(doms[k] || {}) })).filter(d => d.label_ar)
  const anyStale = list.some(d => d.stale)
  const lane = domains.every(d => FAST_DOMAINS.has(d)) ? 'fast' : 'full'
  // Only offer the sync-trigger button when EVERY domain is refreshable by it.
  const canRefresh = canEdit && domains.every(d => SYNC_REFRESHABLE.has(d))

  // Compact inline chip for dense screens (POS header): one dot + hover detail,
  // no block, no button — keeps the cashier surface calm.
  if (compact) {
    if (!list.length) return null
    const title = list.map(d => `${d.label_ar}: ${fmtAge(d.age_seconds)}`).join('  ·  ')
    return (
      <span className="inline-flex items-center gap-1 text-[11px] shrink-0" title={title} dir="rtl">
        <span className={`w-1.5 h-1.5 rounded-full ${anyStale ? 'bg-amber-500' : 'bg-emerald-500'}`} />
        <span className={anyStale ? 'text-amber-700 font-semibold' : 'text-gray-400'}>
          {anyStale ? 'بيانات قد تكون قديمة' : 'البيانات محدّثة'}
        </span>
      </span>
    )
  }

  async function refresh() {
    setRefreshing(true)
    try { await syncApi.triggerLane(lane) } catch { /* surfaced by staleness */ }
    let n = 0
    const t = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['data-freshness', domains.join(',')] })
      if (++n >= 8) { clearInterval(t); setRefreshing(false) }
    }, 4000)
  }

  const cls = anyStale
    ? 'bg-amber-50 text-amber-800 border-amber-200'
    : 'bg-emerald-50 text-emerald-700 border-emerald-100'

  return (
    <div className={`mb-3 text-xs rounded-lg px-3 py-2 border flex flex-wrap items-center gap-x-3 gap-y-1 ${cls}`} dir="rtl">
      {list.map(d => {
        const sales = d.key === 'sales'
        const behind = sales && d.behind_days > 0
        const warn = d.stale || behind || (sales && d.complete === false)
        return (
          <span key={d.key} className={`inline-flex items-center gap-1 ${warn ? 'font-bold' : ''}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${warn ? 'bg-amber-500' : 'bg-emerald-500'}`} />
            {d.label_ar}: {fmtAge(d.age_seconds)}
            {sales && d.data_through && <span className="opacity-75"> · حتى {d.data_through}</span>}
            {behind && <span> · متأخّرة ~{d.behind_days} يوم</span>}
            {sales && d.complete === false && !behind && <span> · بيانات ناقصة</span>}
          </span>
        )
      })}
      {list.some(d => d.last_run_failed) && (
        <span className="text-red-600 font-bold">· آخر مزامنة فشلت</span>
      )}
      {canRefresh && (
        <button onClick={refresh} disabled={refreshing}
          className={`ml-auto px-2.5 py-1 rounded-md text-white text-[11px] font-bold disabled:opacity-50 ${anyStale ? 'bg-amber-600' : 'bg-emerald-600'}`}>
          {refreshing ? '⏳ جارٍ التحديث…' : '🔄 تحديث الآن'}
        </button>
      )}
    </div>
  )
}

function daysBehind(dateStr) {
  if (!dateStr) return null
  const d = new Date(dateStr + 'T00:00:00')
  const today = new Date(); today.setHours(0, 0, 0, 0)
  // "complete through yesterday" is on-time (today is still in progress)
  return Math.max(0, Math.round((today - d) / 86400000) - 1)
}

export default function DataFreshnessBar({ domains, compact, dataThrough, daysElapsed, daysTotal, canEdit, invalidateKeys = [] }) {
  // NEW per-domain freshness mode (modules pass `domains`); falls through to the
  // legacy KPI/MTD mode when `domains` is absent. `compact` renders a tiny inline
  // chip for dense screens (e.g. POS header).
  if (domains && domains.length) return <DomainFreshness domains={domains} canEdit={canEdit} compact={compact} />

  const qc = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const { data: sync } = useQuery({
    queryKey: ['sync-status-bar'],
    queryFn: () => syncApi.status().then(r => r.data),
    refetchInterval: refreshing ? 5000 : false,
  })
  const lastSync = sync?.completed_at || sync?.started_at
  const behind = daysBehind(dataThrough)
  const stale = behind != null && behind >= 1

  async function refresh() {
    setRefreshing(true)
    try { await kpiApi.refresh() } catch { /* surfaced below */ }
    // rollups rebuild in the background — refetch a few times, then stop
    let n = 0
    const t = setInterval(() => {
      invalidateKeys.forEach(k => qc.invalidateQueries({ queryKey: k }))
      if (++n >= 6) { clearInterval(t); setRefreshing(false) }
    }, 5000)
  }

  const cls = stale
    ? 'bg-amber-50 text-amber-800 border-amber-200'
    : 'bg-emerald-50 text-emerald-700 border-emerald-100'
  return (
    <div className={`mb-3 text-xs rounded-lg px-3 py-2 border flex flex-wrap items-center gap-x-3 gap-y-1 ${cls}`}>
      <span>
        {dataThrough
          ? <>🕒 البيانات محسوبة بنظام الشهر حتى تاريخه (MTD) — مكتملة حتى <b>{dataThrough}</b>{daysTotal ? <> · يوم <b>{daysElapsed}</b> من <b>{daysTotal}</b></> : null}</>
          : <>🕒 بيانات التنبؤ مبنية على المجاميع الشهرية (KpiActualRollup)</>}
      </span>
      {lastSync && <span className="opacity-80">· آخر مزامنة {new Date(lastSync).toLocaleString('ar-EG')}</span>}
      {stale && <span className="font-bold">· متأخّرة ~{behind} يوم عن أمس</span>}
      {canEdit && (
        <button onClick={refresh} disabled={refreshing}
          className={`ml-auto px-2.5 py-1 rounded-md text-white text-[11px] font-bold disabled:opacity-50 ${stale ? 'bg-amber-600' : 'bg-emerald-600'}`}>
          {refreshing ? '⏳ جارٍ التحديث…' : '🔄 تحديث البيانات'}
        </button>
      )}
      {refreshing && <span className="text-[11px] opacity-70">يُعاد بناء المجاميع — قد يستغرق دقيقة</span>}
    </div>
  )
}
