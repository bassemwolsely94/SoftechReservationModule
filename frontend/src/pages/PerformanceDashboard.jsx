/**
 * PerformanceDashboard.jsx — Module 8: Staff Performance Analytics
 * Full filters: branch, doc_code, person_codes, channels, medicine_types,
 * date/hour/weekday + profit, margin, discount, piccodes per employee.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '../api/client'
import AnalyticsFilterPanel, { filtersToParams, defaultFilters } from '../components/AnalyticsFilterPanel'
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
    gray:  'bg-gray-50 border-gray-200 text-gray-600',
  }
  return (
    <div className={`rounded-xl border p-4 ${cls[color] || cls.brand}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs text-gray-500 mb-1">{label}</p>
          <p className="text-xl font-bold font-mono">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </div>
        {icon && <span className="text-xl opacity-60 flex-shrink-0">{icon}</span>}
      </div>
    </div>
  )
}

function MiniBar({ value, max, color = 'bg-brand-500' }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="h-1.5 bg-gray-100 rounded w-20">
      <div className={`h-full rounded ${color} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function MedalBadge({ rank }) {
  if (rank === 1) return <span className="text-lg">🥇</span>
  if (rank === 2) return <span className="text-lg">🥈</span>
  if (rank === 3) return <span className="text-lg">🥉</span>
  return <span className="w-5 h-5 rounded-full bg-gray-100 text-gray-500 text-xs font-bold flex items-center justify-center">{rank}</span>
}

const TABS = [
  { key: 'employees', label: 'الموظفون',       icon: '👤' },
  { key: 'branches',  label: 'الفروع',          icon: '🏪' },
  { key: 'time',      label: 'التوزيع الزمني',  icon: '🕐' },
]

const TABLE_HEIGHT = 'calc(100vh - 460px)'

// ── Column definitions ─────────────────────────────────────────────────────────

const buildEmpCols = (maxRev, maxTrx) => [
  { key: '_rank',            label: '#',           type: 'integer', width: 50,  sortable: false,
    render: (_, __, i) => <MedalBadge rank={i + 1} /> },
  { key: 'user_code',        label: 'كود',         type: 'text',    width: 80,
    render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
  { key: 'user_name',        label: 'الاسم',       type: 'text',    width: 200 },
  { key: 'revenue',          label: 'الإيراد',     type: 'number',  width: 160,
    render: (v, row) => (
      <div>
        <div className="font-mono text-brand-700 font-semibold">{fmt(v)} جم</div>
        <MiniBar value={v} max={maxRev} color="bg-brand-400" />
      </div>
    ) },
  { key: 'profit',           label: 'الربح',       type: 'number',  width: 130,
    render: v => <span className="font-mono text-green-700">{fmt(v)} جم</span> },
  { key: 'margin_pct',       label: 'الهامش%',     type: 'number',  width: 90,
    render: v => <span className="font-mono text-green-600">{fmtPct(v)}</span> },
  { key: 'discount',         label: 'الخصم',       type: 'number',  width: 120,
    render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
  { key: 'transactions',     label: 'الفواتير',    type: 'integer', width: 120,
    render: (v, row) => (
      <div>
        <div className="font-mono text-blue-700">{fmt(v)}</div>
        <MiniBar value={v} max={maxTrx} color="bg-blue-400" />
      </div>
    ) },
  { key: 'avg_basket',       label: 'متوسط',       type: 'number',  width: 110,
    render: v => <span className="font-mono text-gray-600">{fmt(v, 1)} جم</span> },
  { key: 'items_sold',       label: 'أصناف',       type: 'number',  width: 90,
    render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
  { key: 'items_per_trx',    label: 'صنف/فات',     type: 'number',  width: 90,
    render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
  { key: 'distinct_customers',label:'عملاء',        type: 'integer', width: 80,
    render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
  { key: 'distinct_piccodes', label: 'PIC',         type: 'integer', width: 80,
    render: v => <span className="font-mono font-semibold text-brand-600">{fmt(v)}</span> },
]

const BRANCH_COLS = [
  { key: 'branch_name',     label: 'الفرع',    type: 'text',    width: 200 },
  { key: 'revenue',         label: 'الإيراد',  type: 'number',  width: 140,
    render: v => <span className="font-mono text-brand-700">{fmt(v)} جم</span> },
  { key: 'profit',          label: 'الربح',    type: 'number',  width: 130,
    render: v => <span className="font-mono text-green-700">{fmt(v)} جم</span> },
  { key: 'margin_pct',      label: 'الهامش%',  type: 'number',  width: 90,
    render: v => <span className="font-mono text-green-600">{fmtPct(v)}</span> },
  { key: 'transactions',    label: 'الفواتير', type: 'integer', width: 90,
    render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
  { key: 'distinct_users',  label: 'موظفون',   type: 'integer', width: 90,
    render: v => <span className="font-mono text-gray-500">{fmt(v)}</span> },
  { key: '_share',          label: 'توزيع%',   type: 'number',  width: 90, sortable: false,
    cellClass: 'text-gray-500 font-mono' },
]

// ── Page ───────────────────────────────────────────────────────────────────────

export default function PerformanceDashboard() {
  const [filters,   setFilters]   = useState(defaultFilters())
  const [activeTab, setActiveTab] = useState('employees')

  const { data: opts } = useQuery({
    queryKey: ['analytics-filter-options'],
    queryFn:  () => analyticsApi.filterOptions().then(r => r.data),
    staleTime: 300_000,
  })

  const params = filtersToParams(filters)

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['analytics-performance', params],
    queryFn:  () => analyticsApi.performance(params).then(r => r.data),
    staleTime: 60_000,
    retry: 1,
  })

  const empRows = data?.by_employee || []
  const maxRev  = Math.max(...empRows.map(e => e.revenue || 0), 1)
  const maxTrx  = Math.max(...empRows.map(e => e.transactions || 0), 1)
  const s = data?.summary || {}

  // Add computed share% to branch rows
  const branchRows = (data?.by_branch || []).map(r => ({
    ...r,
    _share: fmtPct(s.total_revenue ? (r.revenue / s.total_revenue) * 100 : 0),
  }))

  return (
    <div className="p-6 space-y-4 max-w-screen-xl mx-auto" dir="rtl">

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">لوحة الأداء</h1>
          <p className="text-sm text-gray-500 mt-0.5">أداء الموظفين — إيراد · ربح · خصم · كود المستخدم واسمه</p>
        </div>
        <RefreshButton loading={isFetching} onClick={() => refetch()} variant="primary">
          تحديث
        </RefreshButton>
      </div>

      <AnalyticsFilterPanel
        filters={filters} onChange={setFilters} options={opts || {}}
        config={{ showDocCodes: true, showPersons: true, showChannels: true,
                  showMedicineTypes: true, showDaysOfWeek: true, showHours: true }}
      />

      {isLoading && <div className="flex justify-center h-40 items-center"><div className="text-brand-600 animate-pulse">جارٍ التحميل…</div></div>}
      {isError   && <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-center text-red-600">تعذّر تحميل بيانات الأداء</div>}

      {data && (
        <>
          {/* Summary KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            <KpiCard label="إجمالي الإيرادات"   value={`${fmt(s.total_revenue)} جم`}    color="brand" icon="💰" />
            <KpiCard label="صافي الربح"          value={`${fmt(s.total_profit)} جم`}     color="green" icon="📈" sub={`هامش ${fmtPct(s.profit_margin_pct)}`} />
            <KpiCard label="إجمالي الخصومات"    value={`${fmt(s.total_discount)} جم`}   color="amber" icon="🏷️" />
            <KpiCard label="الفواتير"            value={fmt(s.total_transactions)}        color="blue"  icon="🧾" />
            <KpiCard label="عملاء فريدون (PIC)" value={fmt(s.distinct_piccodes)}          color="brand" icon="👥" sub={`${fmt(s.distinct_customers)} حساب`} />
            <KpiCard label="الأفضل أداءً"
              value={data.best_performer?.user_code || '—'}
              sub={data.best_performer?.user_name || ''}
              color="amber" icon="🏆" />
          </div>

          {/* Podium — top 3 */}
          {empRows.length >= 3 && (
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">المتصدرون</h2>
              <div className="flex justify-center items-end gap-4">
                <div className="text-center">
                  <div className="w-16 h-20 bg-gray-100 rounded-t-xl flex items-center justify-center"><span className="text-2xl">🥈</span></div>
                  <div className="bg-gray-200 rounded-b-xl px-2 py-2 text-xs">
                    <div className="font-mono text-gray-600 text-[10px]">{empRows[1]?.user_code}</div>
                    <div className="font-semibold text-gray-700 truncate max-w-16">{empRows[1]?.user_name}</div>
                    <div className="text-gray-500">{fmt(empRows[1]?.revenue)} جم</div>
                  </div>
                </div>
                <div className="text-center -mt-4">
                  <div className="w-20 h-28 bg-yellow-100 rounded-t-xl flex items-center justify-center border-2 border-yellow-300"><span className="text-3xl">🥇</span></div>
                  <div className="bg-yellow-200 rounded-b-xl px-2 py-2 text-xs border-2 border-yellow-300">
                    <div className="font-mono text-yellow-600 text-[10px]">{empRows[0]?.user_code}</div>
                    <div className="font-bold text-yellow-800 truncate max-w-20">{empRows[0]?.user_name}</div>
                    <div className="text-yellow-700 font-semibold">{fmt(empRows[0]?.revenue)} جم</div>
                  </div>
                </div>
                <div className="text-center">
                  <div className="w-16 h-16 bg-amber-50 rounded-t-xl flex items-center justify-center"><span className="text-2xl">🥉</span></div>
                  <div className="bg-amber-100 rounded-b-xl px-2 py-2 text-xs">
                    <div className="font-mono text-amber-600 text-[10px]">{empRows[2]?.user_code}</div>
                    <div className="font-semibold text-amber-800 truncate max-w-16">{empRows[2]?.user_name}</div>
                    <div className="text-amber-700">{fmt(empRows[2]?.revenue)} جم</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="flex border-b border-gray-100 overflow-x-auto">
              {TABS.map(tab => (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-1.5 px-5 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px
                    ${activeTab === tab.key ? 'border-brand-500 text-brand-600 bg-brand-50/40' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                  <span>{tab.icon}</span>{tab.label}
                </button>
              ))}
            </div>

            <div>

              {activeTab === 'employees' && (
                <DataTable
                  columns={buildEmpCols(maxRev, maxTrx)}
                  rows={empRows}
                  defaultSort={{ key: 'revenue', dir: 'desc' }}
                  maxHeight={TABLE_HEIGHT}
                  rowClassName={(_, i) => i < 3 ? 'bg-yellow-50/30' : ''}
                  emptyLabel="لا توجد بيانات للموظفين"
                />
              )}

              {activeTab === 'branches' && (
                <div className="p-5">
                  <DataTable
                    columns={BRANCH_COLS}
                    rows={branchRows}
                    defaultSort={{ key: 'revenue', dir: 'desc' }}
                    maxHeight={TABLE_HEIGHT}
                    emptyLabel="لا توجد بيانات للفروع"
                  />
                </div>
              )}

              {activeTab === 'time' && (
                <div className="p-5 space-y-6">
                  {(data.by_hour || []).length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-gray-700 mb-3">الإيراد بالساعة</h3>
                      <div className="flex items-end gap-1 h-20">
                        {Array.from({ length: 24 }, (_, h) => {
                          const row = (data.by_hour || []).find(r => r.hour === h)
                          const rev = row?.revenue || 0
                          const maxH = Math.max(...(data.by_hour || []).map(r => r.revenue), 1)
                          return (
                            <div key={h} className="flex-1 flex flex-col items-center gap-0.5" title={`${h}:00 — ${fmt(rev)} جم`}>
                              <div className="w-full bg-brand-400 rounded-t" style={{ height: `${Math.max(2, (rev / maxH) * 64)}px` }} />
                              <span className="text-[8px] text-gray-400">{h}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                  {(data.by_weekday || []).length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-gray-700 mb-3">الإيراد بيوم الأسبوع</h3>
                      <div className="space-y-2">
                        {(data.by_weekday || []).map((row, i) => {
                          const maxR = Math.max(...(data.by_weekday || []).map(r => r.revenue), 1)
                          return (
                            <div key={i} className="flex items-center gap-3 text-xs">
                              <span className="w-16 text-right text-gray-600">{row.day_label}</span>
                              <div className="flex-1 bg-gray-100 rounded h-4">
                                <div className="h-full bg-brand-400 rounded" style={{ width: `${(row.revenue / maxR) * 100}%` }} />
                              </div>
                              <span className="w-24 font-mono text-gray-600 text-right">{fmt(row.revenue)} جم</span>
                              <span className="w-12 font-mono text-blue-600">{fmt(row.transactions)}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

            </div>
          </div>
        </>
      )}
    </div>
  )
}
