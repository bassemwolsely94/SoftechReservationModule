/**
 * SalesDashboard.jsx — Module 7: Sales Intelligence
 * Full filter set: branch, doc_code, person, channel, medicine_type,
 * date/hour/weekday + profit, margin, discount, piccodes metrics.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi, itemsApi } from '../api/client'
import AnalyticsFilterPanel, { filtersToParams, defaultFilters } from '../components/AnalyticsFilterPanel'
import ItemOperationalFiltersBar, { emptyItemFilters, buildItemParams } from '../components/ItemOperationalFiltersBar'
import DataTable from '../components/DataTable'
import RefreshButton from '../components/RefreshButton'

const fmt    = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const fmtPct = n => `${fmt(n, 1)}%`

function KpiCard({ label, value, sub, icon, color = 'brand' }) {
  const cls = {
    brand: 'bg-brand-50 border-brand-200 text-brand-700',
    green: 'bg-green-50 border-green-200 text-green-700',
    blue:  'bg-blue-50 border-blue-200 text-blue-700',
    amber: 'bg-amber-50 border-amber-200 text-amber-700',
    red:   'bg-red-50 border-red-200 text-red-700',
    gray:  'bg-gray-50 border-gray-200 text-gray-600',
  }
  return (
    <div className={`rounded-xl border p-4 ${cls[color] || cls.brand}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-gray-500 mb-1 truncate">{label}</p>
          <p className="text-xl font-bold font-mono leading-tight">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </div>
        {icon && <span className="text-xl opacity-60 flex-shrink-0">{icon}</span>}
      </div>
    </div>
  )
}

function BarChart({ rows = [], valueKey, labelKey, color = 'bg-brand-500', maxRows = 10 }) {
  const sliced = rows.slice(0, maxRows)
  const max    = Math.max(...sliced.map(r => Number(r[valueKey]) || 0), 1)
  return (
    <div className="space-y-2">
      {sliced.map((row, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <div className="w-32 text-right text-gray-600 truncate flex-shrink-0">{row[labelKey]}</div>
          <div className="flex-1 bg-gray-100 rounded h-4 overflow-hidden">
            <div className={`h-full ${color} rounded`} style={{ width: `${(Number(row[valueKey]) / max) * 100}%` }} />
          </div>
          <div className="w-20 font-mono text-gray-600 text-right flex-shrink-0">{fmt(row[valueKey])} جم</div>
        </div>
      ))}
    </div>
  )
}

function HourHeatmap({ byHour = [] }) {
  const map = {}
  byHour.forEach(r => { map[r.hour] = r.transactions })
  const maxV = Math.max(...Object.values(map), 1)
  return (
    <div className="grid grid-cols-12 gap-1">
      {Array.from({ length: 24 }, (_, h) => {
        const v   = map[h] || 0
        const pct = v / maxV
        const bg  = pct > 0.7 ? 'bg-brand-600 text-white' :
                    pct > 0.4 ? 'bg-brand-300 text-brand-900' :
                    pct > 0.1 ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-400'
        return (
          <div key={h} className={`rounded p-1 text-center ${bg}`} title={`${h}:00 — ${v} فاتورة`}>
            <div className="text-[9px] font-mono leading-none">{h}</div>
            <div className="text-[10px] font-bold leading-none mt-0.5">{v || ''}</div>
          </div>
        )
      })}
    </div>
  )
}

function WeekdayBar({ byWeekday = [] }) {
  const max = Math.max(...byWeekday.map(r => r.revenue || 0), 1)
  return (
    <div className="flex gap-2 items-end h-24">
      {byWeekday.map((row, i) => (
        <div key={i} className="flex-1 flex flex-col items-center gap-1">
          <div className="w-full bg-brand-400 rounded-t"
            style={{ height: `${Math.max(4, (row.revenue / max) * 72)}px` }}
            title={`${row.day_label}: ${fmt(row.revenue)} جم`} />
          <span className="text-[9px] text-gray-500">{row.day_label?.slice(0, 3)}</span>
        </div>
      ))}
    </div>
  )
}

// ── Column definitions ─────────────────────────────────────────────────────────

const BRANCH_COLS = [
  { key: 'branch_name',         label: 'الفرع',      type: 'text',    width: 180 },
  { key: 'revenue',             label: 'الإيراد',    type: 'number',  width: 140, render: v => <span className="font-mono text-brand-700">{fmt(v)} جم</span> },
  { key: 'profit',              label: 'الربح',      type: 'number',  width: 130, render: v => <span className="font-mono text-green-700">{fmt(v)} جم</span> },
  { key: 'margin_pct',          label: 'الهامش%',    type: 'number',  width: 90,  render: v => <span className="font-mono text-green-600">{fmtPct(v)}</span> },
  { key: 'discount',            label: 'الخصم',      type: 'number',  width: 120, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
  { key: 'transactions',        label: 'الفواتير',   type: 'integer', width: 90,  render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
  { key: 'distinct_customers',  label: 'عملاء',      type: 'integer', width: 80,  render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
  { key: 'distinct_items',      label: 'أصناف',      type: 'integer', width: 80,  render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
  { key: 'total_qty',           label: 'الكمية',     type: 'number',  width: 90,  render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
]

const USER_COLS = [
  { key: '_rank',            label: '#',           type: 'integer', width: 45,  sortable: false, render: (_, __, i) => <span className="text-gray-400 text-xs">{i + 1}</span> },
  { key: 'user_code',        label: 'كود',         type: 'text',    width: 80,  render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
  { key: 'user_name',        label: 'الاسم',       type: 'text',    width: 200 },
  { key: 'revenue',          label: 'الإيراد',     type: 'number',  width: 140, render: v => <span className="font-mono text-brand-700">{fmt(v)} جم</span> },
  { key: 'profit',           label: 'الربح',       type: 'number',  width: 130, render: v => <span className="font-mono text-green-700">{fmt(v)} جم</span> },
  { key: 'margin_pct',       label: 'الهامش%',     type: 'number',  width: 90,  render: v => <span className="font-mono text-green-600">{fmtPct(v)}</span> },
  { key: 'discount',         label: 'الخصم',       type: 'number',  width: 120, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
  { key: 'transactions',     label: 'الفواتير',    type: 'integer', width: 90,  render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
  { key: 'avg_basket',       label: 'متوسط',       type: 'number',  width: 110, render: v => <span className="font-mono text-gray-500">{fmt(v, 1)} جم</span> },
  { key: 'distinct_piccodes',label: 'PIC',         type: 'integer', width: 80,  render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
  { key: 'items_per_trx',    label: 'صنف/فات',     type: 'number',  width: 90,  render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
]

const MEDICINE_COLS = [
  { key: 'type_label',  label: 'نوع الدواء', type: 'text',    width: 200 },
  { key: 'revenue',     label: 'الإيراد',    type: 'number',  width: 140, render: v => <span className="font-mono text-brand-700">{fmt(v)} جم</span> },
  { key: 'profit',      label: 'الربح',      type: 'number',  width: 130, render: v => <span className="font-mono text-green-700">{fmt(v)} جم</span> },
  { key: 'margin_pct',  label: 'الهامش%',    type: 'number',  width: 90,  render: v => <span className="font-mono text-green-600">{fmtPct(v)}</span> },
  { key: 'discount',    label: 'الخصم',      type: 'number',  width: 120, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
  { key: 'qty',         label: 'الكمية',     type: 'number',  width: 90,  render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
  { key: 'trx_count',   label: 'الفواتير',   type: 'integer', width: 90,  render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
  { key: 'item_count',  label: 'الأصناف',    type: 'integer', width: 80,  render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
]

const ITEM_COLS = [
  { key: '_rank',       label: '#',          type: 'integer', width: 45,  sortable: false, render: (_, __, i) => <span className="text-gray-400 text-xs">{i + 1}</span> },
  { key: 'item_name',   label: 'الصنف',      type: 'text',    width: 260 },
  { key: 'item_code',   label: 'الكود',      type: 'text',    width: 80,  render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
  { key: 'medicine_type',label:'نوع الدواء', type: 'text',    width: 170 },
  { key: 'supplier',    label: 'المورد',     type: 'text',    width: 200 },
  { key: 'producer',    label: 'المنتج',     type: 'text',    width: 200 },
  { key: 'family',      label: 'العائلة',    type: 'text',    width: 150 },
  { key: 'revenue',     label: 'الإيراد',    type: 'number',  width: 140, render: v => <span className="font-mono text-brand-700">{fmt(v)} جم</span> },
  { key: 'profit',      label: 'الربح',      type: 'number',  width: 130, render: v => <span className="font-mono text-green-700">{fmt(v)} جم</span> },
  { key: 'margin_pct',  label: 'الهامش%',    type: 'number',  width: 90,  render: v => <span className="font-mono text-green-600">{fmtPct(v)}</span> },
  { key: 'discount',    label: 'الخصم',      type: 'number',  width: 120, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
  { key: 'qty',         label: 'الكمية',     type: 'number',  width: 90,  render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
  { key: 'trx_count',   label: 'الفواتير',   type: 'integer', width: 90,  render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
]

// ── Tab config ─────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'overview',      label: 'نظرة عامة',       icon: '📊' },
  { key: 'branches',      label: 'الفروع',           icon: '🏪' },
  { key: 'users',         label: 'الكاشيرون',        icon: '👤' },
  { key: 'channels',      label: 'قنوات البيع',      icon: '🛒' },
  { key: 'medicine',      label: 'أنواع الأدوية',    icon: '💊' },
  { key: 'items',         label: 'أفضل الأصناف',     icon: '📦' },
  { key: 'time',          label: 'التوزيع الزمني',   icon: '🕐' },
  { key: 'contribution',  label: 'مساهمة الفروع',    icon: '🏦' },
  { key: 'churn',         label: 'العملاء الغائبون', icon: '👻' },
]

const CHURN_TIER_COLORS = [
  { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-700', badge: 'bg-yellow-100 text-yellow-800' },
  { bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-700', badge: 'bg-orange-100 text-orange-800' },
  { bg: 'bg-red-50',    border: 'border-red-200',    text: 'text-red-700',    badge: 'bg-red-100 text-red-800' },
  { bg: 'bg-red-100',   border: 'border-red-300',    text: 'text-red-800',    badge: 'bg-red-200 text-red-900' },
  { bg: 'bg-gray-100',  border: 'border-gray-300',   text: 'text-gray-700',   badge: 'bg-gray-200 text-gray-800' },
]

const TABLE_HEIGHT = 'calc(100vh - 420px)'

// ── Page ───────────────────────────────────────────────────────────────────────

export default function SalesDashboard() {
  const [filters,     setFilters]     = useState(defaultFilters())
  const [itemFilters, setItemFilters] = useState(emptyItemFilters())
  const [activeTab,   setActiveTab]   = useState('overview')

  const { data: opts } = useQuery({
    queryKey: ['analytics-filter-options'],
    queryFn:  () => analyticsApi.filterOptions().then(r => r.data),
    staleTime: 300_000,
  })

  const { data: itemFilterOpts } = useQuery({
    queryKey: ['items-filter-options'],
    queryFn:  () => itemsApi.filterOptions().then(r => r.data),
    staleTime: 600_000,
  })

  // Merge temporal/transactional filters with item operational filters
  const params = { ...filtersToParams(filters), ...buildItemParams(itemFilters) }

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['analytics-sales', params],
    queryFn:  () => analyticsApi.sales(params).then(r => r.data),
    staleTime: 60_000,
    retry: 1,
  })

  // Customer Churn — lazy-loaded; no date param (recency is relative to today)
  const { data: churnData, isLoading: churnLoading } = useQuery({
    queryKey: ['analytics-churn'],
    queryFn:  () => analyticsApi.churn().then(r => r.data),
    staleTime: 600_000,
    enabled:  activeTab === 'churn',
    retry: 1,
  })

  // Branch Contribution — lazy-loaded; respects date_from / date_to from shared filters
  const contribParams = (() => {
    const fp = filtersToParams(filters)
    const p  = {}
    if (fp.date_from) p.date_from = fp.date_from
    if (fp.date_to)   p.date_to   = fp.date_to
    return p
  })()
  const { data: contribData, isLoading: contribLoading } = useQuery({
    queryKey: ['analytics-branch-contribution', contribParams],
    queryFn:  () => analyticsApi.branchContribution(contribParams).then(r => r.data),
    staleTime: 120_000,
    enabled:  activeTab === 'contribution',
    retry: 1,
  })

  const s = data?.summary || {}

  return (
    <div className="p-6 space-y-4 max-w-screen-xl mx-auto" dir="rtl">

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">لوحة المبيعات</h1>
          <p className="text-sm text-gray-500 mt-0.5">إيرادات · ربح · خصم · قنوات · أصناف · توزيع زمني</p>
        </div>
        <RefreshButton loading={isFetching} onClick={() => refetch()} variant="primary">
          تحديث
        </RefreshButton>
      </div>

      <AnalyticsFilterPanel
        filters={filters} onChange={setFilters} options={opts || {}}
        config={{ showDocCodes: true, showPersons: true, showChannels: true,
                  showMedicineTypes: true, showDaysOfWeek: true, showHours: true,
                  showPersonsMain: true }}
      />

      {/* Item operational filters — insurance, level, store_classif, nosale, trans, FMI, points */}
      <ItemOperationalFiltersBar
        filters={itemFilters}
        onChange={setItemFilters}
        options={itemFilterOpts || {}}
      />

      {isLoading && <div className="flex justify-center h-40 items-center"><div className="text-brand-600 animate-pulse">جارٍ التحميل…</div></div>}
      {isError   && <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-center text-red-600">تعذّر تحميل البيانات</div>}

      {data && (
        <>
          {/* KPIs row 1 */}
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
            <KpiCard label="صافي الإيرادات"      value={`${fmt(s.total_revenue)} جم`}    color="brand" icon="💰"
              sub={`مبيعات ${fmt(s.sales_revenue)} − مردودات ${fmt(s.returns_revenue)}`} />
            <KpiCard label="صافي الربح"           value={`${fmt(s.total_profit)} جم`}     color="green" icon="📈"
              sub={`هامش ${fmtPct(s.profit_margin_pct)}`} />
            <KpiCard label="تكلفة البضاعة (COGS)" value={`${fmt(s.total_cogs)} جم`}      color="red"   icon="🏭"
              sub={`${fmtPct(s.total_revenue ? (s.total_cogs / s.total_revenue) * 100 : 0)} من الإيراد`} />
            <KpiCard label="إجمالي الخصومات"      value={`${fmt(s.total_discount)} جم`}  color="amber" icon="🏷️" />
            <KpiCard label="عدد الفواتير"         value={fmt(s.total_transactions)}        color="blue"  icon="🧾"
              sub={`متوسط ${fmt(s.avg_basket, 1)} جم`} />
            <KpiCard label="عملاء PIC فريدون"     value={fmt(s.distinct_piccodes)}         color="brand" icon="👥"
              sub={`${fmt(s.distinct_customers)} حساب`} />
            <KpiCard label="صنف/فاتورة"           value={fmt(s.items_per_trx, 2)}          color="gray"  icon="🔢"
              sub={`${fmt(s.distinct_items)} صنف فريد`} />
          </div>

          {/* KPIs row 2 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="فواتير مبيعات"  value={fmt(s.sales_count)}   sub={`${fmt(s.sales_revenue)} جم`}   color="green" icon="✅" />
            <KpiCard label="مردودات"         value={fmt(s.returns_count)} sub={`${fmt(s.returns_revenue)} جم`} color="red"   icon="↩️" />
            <KpiCard label="معدل الإرجاع"   value={fmtPct(s.return_rate_pct)}
              sub="(قيمة المردودات ÷ المبيعات)"              color={s.return_rate_pct > 5 ? 'red' : 'gray'} icon="%" />
            <KpiCard label="إجمالي الكمية"  value={fmt(s.total_qty, 1)}  sub="وحدة / عبوة"                    color="gray"  icon="📦" />
          </div>

          {/* Tab bar */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="flex border-b border-gray-100 overflow-x-auto">
              {TABS.map(tab => (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px
                    ${activeTab === tab.key ? 'border-brand-500 text-brand-600 bg-brand-50/40' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                  <span>{tab.icon}</span>{tab.label}
                </button>
              ))}
            </div>

            <div className="p-5">

              {activeTab === 'overview' && (
                <div className="space-y-6">
                  {(data.by_day || []).length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-gray-700 mb-3">التوجه اليومي للإيرادات</h3>
                      <div className="flex items-end gap-0.5 h-24 bg-gray-50 rounded-xl p-2">
                        {(() => {
                          const days = data.by_day
                          const maxR = Math.max(...days.map(d => d.revenue), 1)
                          return days.map((d, i) => (
                            <div key={i} style={{ flex: 1, minWidth: '3px' }}
                              className="flex items-end h-full"
                              title={`${d.date}: ${fmt(d.revenue)} جم — ربح ${fmt(d.profit)} جم`}>
                              <div className="w-full bg-brand-400 hover:bg-brand-600 rounded-t transition-colors cursor-pointer"
                                style={{ height: `${Math.max(2, (d.revenue / maxR) * 100)}%` }} />
                            </div>
                          ))
                        })()}
                      </div>
                      <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
                        <span>{data.by_day[0]?.date}</span>
                        <span>{data.by_day[data.by_day.length - 1]?.date}</span>
                      </div>
                    </div>
                  )}
                  {(data.by_category || []).length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-gray-700 mb-3">إيرادات حسب التصنيف العلاجي</h3>
                      <BarChart rows={data.by_category} valueKey="revenue" labelKey="category_name" />
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'branches' && (
                <DataTable
                  columns={BRANCH_COLS}
                  rows={data.by_branch || []}
                  defaultSort={{ key: 'revenue', dir: 'desc' }}
                  maxHeight={TABLE_HEIGHT}
                  emptyLabel="لا توجد بيانات للفروع"
                />
              )}

              {activeTab === 'users' && (
                <DataTable
                  columns={USER_COLS}
                  rows={data.by_user || []}
                  defaultSort={{ key: 'revenue', dir: 'desc' }}
                  maxHeight={TABLE_HEIGHT}
                  rowClassName={(_, i) => i < 3 ? 'bg-yellow-50/40' : ''}
                  emptyLabel="لا توجد بيانات للكاشيرين"
                />
              )}

              {activeTab === 'channels' && (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {(data.by_channel || []).map((ch, i) => (
                    <div key={i} className="rounded-xl border border-gray-100 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-gray-700">{ch.channel_label}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 font-mono">{ch.channel_code || '—'}</span>
                      </div>
                      <p className="text-xl font-bold font-mono text-brand-700">{fmt(ch.revenue)} جم</p>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600">
                        <div>ربح: <span className="text-green-600 font-mono font-semibold">{fmt(ch.profit)} جم</span></div>
                        <div>هامش: <span className="text-green-600 font-mono">{fmtPct(ch.margin_pct)}</span></div>
                        <div>خصم: <span className="text-amber-600 font-mono">{fmt(ch.discount)} جم</span></div>
                        <div>فواتير: <span className="font-mono">{fmt(ch.transactions)}</span></div>
                        <div>حسابات: <span className="font-mono">{fmt(ch.distinct_customers)}</span></div>
                        <div>PIC فريد: <span className="font-mono font-semibold text-brand-600">{fmt(ch.distinct_piccodes)}</span></div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === 'medicine' && (
                <DataTable
                  columns={MEDICINE_COLS}
                  rows={data.by_medicine_type || []}
                  defaultSort={{ key: 'revenue', dir: 'desc' }}
                  maxHeight={TABLE_HEIGHT}
                  theadClass="bg-purple-50 text-xs text-purple-700"
                  emptyLabel="لا توجد بيانات لأنواع الأدوية"
                />
              )}

              {activeTab === 'items' && (
                <DataTable
                  columns={ITEM_COLS}
                  rows={data.top_items || []}
                  defaultSort={{ key: 'revenue', dir: 'desc' }}
                  maxHeight={TABLE_HEIGHT}
                  theadClass="bg-green-50 text-xs text-green-700"
                  emptyLabel="لا توجد بيانات للأصناف"
                />
              )}

              {activeTab === 'contribution' && (
                <div className="space-y-5">
                  {contribLoading && (
                    <div className="flex justify-center h-32 items-center">
                      <div className="text-brand-600 animate-pulse">جارٍ احتساب هامش المساهمة…</div>
                    </div>
                  )}
                  {contribData && (
                    <>
                      {/* Network totals */}
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <KpiCard label="صافي الإيرادات"    value={`${fmt(contribData.totals?.net_revenue)} جم`}            color="brand" icon="💰" />
                        <KpiCard label="إجمالي الربح"      value={`${fmt(contribData.totals?.gross_margin)} جم`}           color="green" icon="📈" />
                        <KpiCard label="مصروفات الفروع"    value={`${fmt(contribData.totals?.branch_expenses)} جم`}        color="amber" icon="💸" />
                        <KpiCard label="هامش المساهمة"     value={`${fmt(contribData.totals?.contribution_margin)} جم`}
                          sub={`${contribData.date_from} — ${contribData.date_to}`}                                        color="blue"  icon="🏦" />
                      </div>

                      {/* Branch-level table */}
                      <DataTable
                        theadClass="bg-blue-50 text-xs text-blue-700"
                        defaultSort={{ key: 'net_revenue', dir: 'desc' }}
                        maxHeight="calc(100vh - 460px)"
                        rows={contribData.branches || []}
                        emptyLabel="لا توجد بيانات"
                        columns={[
                          { key: 'branch_name',         label: 'الفرع',              type: 'text',   width: 200 },
                          { key: 'gross_revenue',       label: 'الإيراد الإجمالي',   type: 'number', width: 150, render: v => <span className="font-mono text-brand-700">{fmt(v)} جم</span> },
                          { key: 'returns_value',       label: 'المردودات',          type: 'number', width: 120, render: v => <span className="font-mono text-red-500">{fmt(v)} جم</span> },
                          { key: 'net_revenue',         label: 'صافي الإيراد',       type: 'number', width: 140, render: v => <span className="font-mono text-brand-700 font-semibold">{fmt(v)} جم</span> },
                          { key: 'cogs',                label: 'التكلفة (COGS)',     type: 'number', width: 140, render: v => <span className="font-mono text-gray-600">{fmt(v)} جم</span> },
                          { key: 'gross_margin',        label: 'إجمالي الربح',       type: 'number', width: 130, render: v => <span className="font-mono text-green-600">{fmt(v)} جم</span> },
                          { key: 'gross_margin_pct',    label: 'هامش %',             type: 'number', width: 85,  render: v => <span className="font-mono text-green-600">{fmt(v, 1)}%</span> },
                          { key: 'branch_expenses',     label: 'المصروفات',          type: 'number', width: 120, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
                          { key: 'contribution_margin', label: 'هامش المساهمة',      type: 'number', width: 140,
                            render: v => <span className={`font-mono font-semibold ${v >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(v)} جم</span> },
                          { key: 'contribution_pct',    label: 'مساهمة %',           type: 'number', width: 95,
                            render: v => <span className={`font-mono ${v >= 0 ? 'text-green-600' : 'text-red-500'}`}>{fmt(v, 1)}%</span> },
                          { key: 'transactions',        label: 'الفواتير',           type: 'integer', width: 90, render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
                        ]}
                      />
                    </>
                  )}
                </div>
              )}

              {activeTab === 'churn' && (
                <div className="space-y-5">
                  {churnLoading && (
                    <div className="flex justify-center h-32 items-center">
                      <div className="text-brand-600 animate-pulse">جارٍ تحليل بيانات العملاء الغائبين…</div>
                    </div>
                  )}
                  {churnData && (
                    <>
                      {/* KPIs */}
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <KpiCard label="عملاء في خطر"       value={fmt(churnData.total_at_risk)}
                          sub={`حتى ${churnData.as_of_date}`}                                        color="red"   icon="⚠️" />
                        <KpiCard label="خسارة سنوية متوقعة" value={`${fmt(churnData.revenue_at_risk)} جم`}
                          sub="متوسط الإنفاق × 12"                                                   color="amber" icon="💸" />
                        <KpiCard label="في نطاق 30-89 يوم"
                          value={fmt((churnData.by_tier?.[0]?.count || 0) + (churnData.by_tier?.[1]?.count || 0))}
                          sub="قابل للاسترداد بسهولة"                                                color="brand" icon="🔔" />
                        <KpiCard label="غائبون 365+ يوم"    value={fmt(churnData.by_tier?.[4]?.count || 0)}
                          sub="صعبو الاسترداد"                                                        color="gray"  icon="❌" />
                      </div>

                      {/* Tier buckets */}
                      <div>
                        <h3 className="text-sm font-semibold text-gray-700 mb-3">توزيع العملاء الغائبين حسب مدة الغياب</h3>
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                          {(churnData.by_tier || []).map((tier, i) => {
                            const c = CHURN_TIER_COLORS[i] || CHURN_TIER_COLORS[4]
                            return (
                              <div key={tier.label} className={`rounded-xl border p-4 ${c.bg} ${c.border}`}>
                                <p className={`text-xs font-medium mb-2 ${c.text}`}>{tier.label}</p>
                                <p className={`text-2xl font-bold font-mono ${c.text}`}>{fmt(tier.count)}</p>
                                <p className="text-xs text-gray-500 mt-1">خسارة: <span className={`font-mono font-semibold ${c.text}`}>{fmt(tier.annual_loss)} جم</span></p>
                              </div>
                            )
                          })}
                        </div>
                      </div>

                      {/* Top churned customers */}
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <h3 className="text-sm font-semibold text-gray-700">أعلى 20 عميلاً بالخسارة المتوقعة</h3>
                          <span className="text-xs text-gray-400">مرتبة تنازلياً حسب الخسارة السنوية</span>
                        </div>
                        <DataTable
                          theadClass="bg-red-50 text-xs text-red-700"
                          defaultSort={{ key: 'estimated_annual_loss', dir: 'desc' }}
                          maxHeight="calc(100vh - 560px)"
                          rows={churnData.top_churned || []}
                          emptyLabel="لا توجد بيانات"
                          columns={[
                            { key: 'name',                  label: 'الاسم',              type: 'text',    width: 220 },
                            { key: 'phone',                 label: 'الهاتف',             type: 'text',    width: 130, render: v => <span className="font-mono text-xs text-gray-500" dir="ltr">{v || '—'}</span> },
                            { key: 'softech_pic',           label: 'PIC',                type: 'text',    width: 90,  render: v => <span className="font-mono text-xs text-gray-400">{v || '—'}</span> },
                            { key: 'channel',               label: 'القناة',             type: 'text',    width: 120 },
                            { key: 'last_purchase',         label: 'آخر شراء',           type: 'text',    width: 110, render: v => <span className="font-mono text-xs text-gray-600">{v}</span> },
                            { key: 'days_silent',           label: 'أيام الغياب',        type: 'integer', width: 100, render: v => <span className={`font-mono font-semibold ${v >= 180 ? 'text-red-600' : v >= 90 ? 'text-orange-500' : 'text-amber-500'}`}>{v}</span> },
                            { key: 'purchase_count',        label: 'عدد الزيارات',       type: 'integer', width: 100, render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
                            { key: 'avg_monthly_spend',     label: 'متوسط/شهر',          type: 'number',  width: 120, render: v => <span className="font-mono text-gray-600">{fmt(v)} جم</span> },
                            { key: 'estimated_annual_loss', label: 'خسارة سنوية',        type: 'number',  width: 130, render: v => <span className="font-mono text-red-600 font-semibold">{fmt(v)} جم</span> },
                          ]}
                        />
                      </div>
                    </>
                  )}
                </div>
              )}

              {activeTab === 'time' && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-700 mb-3">خريطة الساعات — عدد الفواتير</h3>
                    <HourHeatmap byHour={data.by_hour || []} />
                  </div>
                  {(data.by_weekday || []).length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-gray-700 mb-3">توزيع أيام الأسبوع</h3>
                      <WeekdayBar byWeekday={data.by_weekday || []} />
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <h3 className="text-xs font-semibold text-gray-600 mb-2">الإيراد بالساعة</h3>
                      <div className="overflow-y-auto max-h-64">
                        <table className="w-full text-xs">
                          <thead className="bg-gray-50 sticky top-0">
                            <tr>
                              <th className="px-2 py-1.5 text-right text-gray-500">الساعة</th>
                              <th className="px-2 py-1.5 text-right text-gray-500">الإيراد</th>
                              <th className="px-2 py-1.5 text-right text-gray-500">الفواتير</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-50">
                            {(data.by_hour || []).map((row, i) => (
                              <tr key={i} className="hover:bg-gray-50">
                                <td className="px-2 py-1 font-mono text-gray-600">{row.hour}:00</td>
                                <td className="px-2 py-1 font-mono text-brand-700">{fmt(row.revenue)} جم</td>
                                <td className="px-2 py-1 font-mono text-blue-600">{row.transactions}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                    <div>
                      <h3 className="text-xs font-semibold text-gray-600 mb-2">الإيراد بيوم الأسبوع</h3>
                      <div className="space-y-1.5">
                        {(data.by_weekday || []).map((row, i) => {
                          const maxR = Math.max(...(data.by_weekday || []).map(r => r.revenue), 1)
                          return (
                            <div key={i} className="flex items-center gap-2 text-xs">
                              <span className="w-16 text-right text-gray-600">{row.day_label}</span>
                              <div className="flex-1 bg-gray-100 rounded h-3">
                                <div className="h-full bg-brand-400 rounded" style={{ width: `${(row.revenue / maxR) * 100}%` }} />
                              </div>
                              <span className="w-20 font-mono text-gray-500 text-right">{fmt(row.revenue)} جم</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              )}

            </div>
          </div>
        </>
      )}
    </div>
  )
}
