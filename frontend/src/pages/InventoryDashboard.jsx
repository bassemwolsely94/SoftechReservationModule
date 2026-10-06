/**
 * InventoryDashboard.jsx — Module 9: Inventory Intelligence
 * Filters: branch (multi), medicine_type (multi), abc_class (multi)
 * Metrics: shortage, overstock, dead stock, by medicine type, coverage months
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi, itemsApi } from '../api/client'
import AnalyticsFilterPanel, { filtersToParams, defaultFilters } from '../components/AnalyticsFilterPanel'
import ItemOperationalFiltersBar, { emptyItemFilters, buildItemParams } from '../components/ItemOperationalFiltersBar'
import DataTable from '../components/DataTable'
import RefreshButton from '../components/RefreshButton'

const fmt = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })

/* ── KPI card ─────────────────────────────────────────────────────────── */
function KpiCard({ label, value, sub, color = 'brand', icon }) {
  const s = {
    brand: 'bg-brand-50 border-brand-200 text-brand-700',
    red:   'bg-red-50 border-red-200 text-red-700',
    blue:  'bg-blue-50 border-blue-200 text-blue-700',
    gray:  'bg-gray-50 border-gray-200 text-gray-600',
    amber: 'bg-amber-50 border-amber-200 text-amber-700',
  }
  return (
    <div className={`rounded-xl border p-5 ${s[color] || s.brand}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-500 mb-1">{label}</p>
          <p className="text-2xl font-bold font-mono">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
        </div>
        {icon && <span className="text-2xl opacity-60">{icon}</span>}
      </div>
    </div>
  )
}

/* ── Priority dot ─────────────────────────────────────────────────────── */
function PriorityDot({ priority }) {
  if (priority >= 3)   return <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
  if (priority >= 1.5) return <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
  return <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
}

const ABC_COLORS = { A: 'text-red-600 bg-red-50', B: 'text-amber-600 bg-amber-50', C: 'text-blue-600 bg-blue-50', X: 'text-gray-500 bg-gray-50' }

const TAB_CONFIG = [
  { key: 'shortages',    label: 'النواقص',      icon: '⚠️' },
  { key: 'overstock',    label: 'الفائض',       icon: '📦' },
  { key: 'dead_stock',   label: 'الراكد',       icon: '💤' },
  { key: 'by_branch',    label: 'بالفرع',       icon: '🏪' },
  { key: 'by_medicine',  label: 'بنوع الدواء',  icon: '💊' },
  { key: 'investment',   label: 'رأس المال',     icon: '💰' },
]

const ABC_INV_COLORS = {
  A: { bg: 'bg-red-50',   border: 'border-red-200',   text: 'text-red-700',   badge: 'bg-red-100 text-red-700' },
  B: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-700' },
  C: { bg: 'bg-blue-50',  border: 'border-blue-200',  text: 'text-blue-700',  badge: 'bg-blue-100 text-blue-700' },
  X: { bg: 'bg-gray-50',  border: 'border-gray-200',  text: 'text-gray-600',  badge: 'bg-gray-100 text-gray-600' },
}

export default function InventoryDashboard() {
  const [activeTab,   setActiveTab]   = useState('shortages')
  const [filters,     setFilters]     = useState(defaultFilters())
  const [itemFilters, setItemFilters] = useState(emptyItemFilters())

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

  // Build combined params: branch/medicine/abc + item operational filters
  const params = {
    ...(((filters.branches       || []).length) ? { branches:       filters.branches.join(',')       } : {}),
    ...(((filters.medicine_types || []).length) ? { medicine_types: filters.medicine_types.join(',') } : {}),
    ...(((filters.abc_class      || []).length) ? { abc_class:      filters.abc_class.join(',')      } : {}),
    ...buildItemParams(itemFilters),
  }

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['analytics-inventory', params],
    queryFn:  () => analyticsApi.inventory(params).then(r => r.data),
    staleTime: 120_000,
    retry: 1,
  })

  // Inventory Investment — lazy-loaded only when the tab is active
  const { data: investData, isLoading: investLoading } = useQuery({
    queryKey: ['analytics-inventory-investment'],
    queryFn:  () => analyticsApi.inventoryInvestment().then(r => r.data),
    staleTime: 300_000,
    enabled:  activeTab === 'investment',
    retry: 1,
  })

  return (
    <div className="p-6 space-y-5 max-w-screen-xl mx-auto" dir="rtl">

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">لوحة المخزون</h1>
          <p className="text-sm text-gray-500 mt-0.5">نواقص · فائض · راكد · نوع الدواء · توزيع الفروع</p>
          {data?.run_date && <p className="text-xs text-gray-400 mt-0.5">آخر تشغيل: {data.run_date}</p>}
        </div>
        <RefreshButton loading={isFetching} onClick={() => refetch()} variant="primary">
          تحديث
        </RefreshButton>
      </div>

      {/* Shared filter panel — show only inventory-relevant filters */}
      <AnalyticsFilterPanel
        filters={filters}
        onChange={setFilters}
        options={opts || {}}
        config={{
          showDocCodes:        false,
          showPersons:         false,
          showChannels:        false,
          showPersonTypes:     false,
          showSuppliers:       false,
          showProducers:       false,
          showStoreCodes:      false,
          showCustBranchCodes: false,
          showDaysOfWeek:      false,
          showHours:           false,
          // abc_class is handled inline below since AnalyticsFilterPanel
          // doesn't carry an abc_class key natively — keep branches & medicine_types
          showBranches:        true,
          showMedicineTypes:   true,
        }}
      />

      {/* ABC class filter — inventory-specific, added inline */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-500 font-medium">فئة ABC:</span>
        {(opts?.abc_classes || [
          { code: 'A', label: 'فئة A' }, { code: 'B', label: 'فئة B' },
          { code: 'C', label: 'فئة C' }, { code: 'X', label: 'فئة X' },
        ]).map(cls => {
          const selected = (filters.abc_class || []).includes(cls.code)
          return (
            <button key={cls.code} type="button"
              onClick={() => {
                const cur = filters.abc_class || []
                setFilters({ ...filters, abc_class: selected ? cur.filter(x => x !== cls.code) : [...cur, cls.code] })
              }}
              className={`px-3 py-1 text-xs rounded-lg border transition-colors
                ${selected ? 'border-brand-500 bg-brand-50 text-brand-700 font-semibold' : 'border-gray-300 text-gray-600 hover:border-brand-400'}`}
            >
              {cls.label}
            </button>
          )
        })}
        {(filters.abc_class || []).length > 0 && (
          <button type="button" onClick={() => setFilters({ ...filters, abc_class: [] })}
            className="text-xs text-red-500 hover:text-red-700 underline mr-2">
            مسح
          </button>
        )}
      </div>

      {/* Item operational filters — insurance, level, store_classif, nosale, trans, FMI, points */}
      <ItemOperationalFiltersBar
        filters={itemFilters}
        onChange={setItemFilters}
        options={itemFilterOpts || {}}
      />

      {isLoading && <div className="flex justify-center h-40 items-center"><div className="text-brand-600 animate-pulse">جارٍ التحميل…</div></div>}
      {isError   && <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-red-600">تعذّر تحميل بيانات المخزون</div>}

      {data && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard label="إجمالي الأصناف"       value={fmt(data.total_items)}       color="brand" icon="📦" />
            <KpiCard label="أصناف ناقصة"           value={fmt(data.shortage_items)}
              sub={`قيمة الفجوة: ${fmt(data.shortage_value)} جم`}                    color="red"   icon="⚠️" />
            <KpiCard label="أصناف فائضة"           value={fmt(data.overstock_items)}
              sub={`قيمة الفائض: ${fmt(data.overstock_value)} جم`}                   color="blue"  icon="📈" />
            <KpiCard label="راكد صفري المبيعات"    value={fmt(data.dead_stock_items)} color="gray"  icon="💤" />
          </div>

          {data.shortage_items > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-center gap-3">
              <span className="text-red-500 text-xl">🚨</span>
              <p className="text-red-700 font-semibold text-sm">
                {fmt(data.shortage_items)} صنف يحتاج إعادة توريد — قيمة الفجوة: {fmt(data.shortage_value)} جم
              </p>
            </div>
          )}

          {/* Tab bar */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="flex border-b border-gray-100 overflow-x-auto">
              {TAB_CONFIG.map(tab => (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-1.5 px-5 py-3.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px
                    ${activeTab === tab.key ? 'border-brand-500 text-brand-600 bg-brand-50/50' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                  <span>{tab.icon}</span>{tab.label}
                  {tab.key === 'shortages' && data.shortage_items > 0 && (
                    <span className="bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                      {data.shortage_items > 99 ? '99+' : data.shortage_items}
                    </span>
                  )}
                </button>
              ))}
            </div>

            <div className="p-0">

              {activeTab === 'shortages' && (
                <div>
                  <div className="px-5 py-3 border-b border-gray-50 flex items-center justify-between">
                    <p className="text-sm text-gray-500">{data.top_shortages?.length || 0} أعلى الأصناف احتياجاً</p>
                    <span className="text-xs text-gray-400">مرتبة حسب الأولوية تنازلياً</span>
                  </div>
                  <DataTable
                    theadClass="bg-red-50 text-xs text-red-600"
                    defaultSort={{ key: 'priority', dir: 'desc' }}
                    maxHeight="calc(100vh - 460px)"
                    rows={data.top_shortages || []}
                    emptyLabel="لا توجد نواقص"
                    columns={[
                      { key: 'item_name',      label: 'الصنف',        type: 'text',    width: 260 },
                      { key: 'item_code',      label: 'الكود',        type: 'text',    width: 80,  render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
                      { key: 'medicine_type',  label: 'نوع الدواء',   type: 'text',    width: 180 },
                      { key: 'supplier',       label: 'المورد',       type: 'text',    width: 200 },
                      { key: 'producer',       label: 'المنتج',       type: 'text',    width: 200 },
                      { key: 'family',         label: 'العائلة',      type: 'text',    width: 150 },
                      { key: 'branch',         label: 'الفرع',        type: 'text',    width: 150 },
                      { key: 'gap',            label: 'الفجوة',       type: 'number',  width: 90,  render: v => <span className="font-mono text-red-600 font-semibold">{fmt(v, 1)}</span> },
                      { key: 'current_stock',  label: 'المخزون',      type: 'number',  width: 100, render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
                      { key: 'safety_stock',   label: 'الأمان',       type: 'number',  width: 90,  render: v => <span className="font-mono text-gray-500">{fmt(v, 1)}</span> },
                      { key: 'monthly_avg',    label: 'متوسط/شهر',    type: 'number',  width: 110, render: v => <span className="font-mono text-gray-500">{fmt(v, 2)}</span> },
                      { key: 'coverage_months',label: 'التغطية',      type: 'number',  width: 100, render: v => <span className="font-mono text-amber-600">{fmt(v, 1)} شهر</span> },
                      { key: 'priority',       label: 'الأولوية',     type: 'number',  width: 100,
                        render: v => (
                          <div className="flex items-center gap-1.5">
                            <PriorityDot priority={v} />
                            <span className="font-mono text-xs text-gray-500">{Number(v).toFixed(2)}</span>
                          </div>
                        ) },
                      { key: 'abc_class',      label: 'ABC',          type: 'text',    width: 70,
                        render: v => <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${ABC_COLORS[v] || ''}`}>{v}</span> },
                    ]}
                  />
                </div>
              )}

              {activeTab === 'overstock' && (
                <div>
                  <div className="px-5 py-3 border-b border-gray-50 flex items-center justify-between">
                    <p className="text-sm text-gray-500">{data.top_overstock?.length || 0} أعلى الأصناف فائضاً</p>
                    <span className="text-xs text-gray-400">مرتبة حسب قيمة الفائض</span>
                  </div>
                  <DataTable
                    theadClass="bg-blue-50 text-xs text-blue-600"
                    defaultSort={{ key: 'value', dir: 'desc' }}
                    maxHeight="calc(100vh - 460px)"
                    rows={data.top_overstock || []}
                    emptyLabel="لا يوجد فائض"
                    columns={[
                      { key: 'item_name',     label: 'الصنف',      type: 'text',   width: 260 },
                      { key: 'item_code',     label: 'الكود',      type: 'text',   width: 80,  render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
                      { key: 'medicine_type', label: 'نوع الدواء', type: 'text',   width: 180 },
                      { key: 'supplier',      label: 'المورد',     type: 'text',   width: 200 },
                      { key: 'producer',      label: 'المنتج',     type: 'text',   width: 200 },
                      { key: 'family',        label: 'العائلة',    type: 'text',   width: 150 },
                      { key: 'branch',        label: 'الفرع',      type: 'text',   width: 150 },
                      { key: 'surplus',       label: 'الفائض',     type: 'number', width: 90,  render: v => <span className="font-mono text-blue-600 font-semibold">{fmt(v, 1)}</span> },
                      { key: 'value',         label: 'القيمة',     type: 'number', width: 130, render: v => <span className="font-mono text-blue-700">{fmt(v)} جم</span> },
                      { key: 'monthly_avg',   label: 'متوسط/شهر',  type: 'number', width: 110, render: v => <span className="font-mono text-gray-500">{fmt(v, 2)}</span> },
                      { key: 'abc_class',     label: 'ABC',        type: 'text',   width: 70,
                        render: v => <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${ABC_COLORS[v] || ''}`}>{v}</span> },
                    ]}
                  />
                </div>
              )}

              {activeTab === 'dead_stock' && (
                <div className="p-5 text-center">
                  <span className="text-4xl">💤</span>
                  <p className="text-3xl font-bold text-gray-700 mt-3">{fmt(data.dead_stock_items)} صنف</p>
                  <p className="text-sm text-gray-500 mt-1">أصناف ذات مبيعات صفرية ومخزون موجود</p>
                  <p className="text-xs text-gray-400 mt-3 max-w-sm mx-auto">
                    هذه الأصناف تُعتبر رأس مال راكد. يُنصح بمراجعتها للتحويل أو التخفيض أو الإيقاف.
                  </p>
                </div>
              )}

              {activeTab === 'by_branch' && (
                <div className="p-5 space-y-3">
                  {(data.by_branch || []).map((row, i) => (
                    <div key={i} className="rounded-xl border border-gray-100 p-4 hover:border-brand-200">
                      <div className="flex items-center justify-between mb-2">
                        <h3 className="font-semibold text-gray-700">{row.branch}</h3>
                        <div className="flex gap-1.5">
                          {row.shortage_count > 0  && <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700">{row.shortage_count} ناقص</span>}
                          {row.overstock_count > 0 && <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">{row.overstock_count} فائض</span>}
                          {row.dead_count > 0      && <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{row.dead_count} راكد</span>}
                        </div>
                      </div>
                      <div className="grid grid-cols-4 gap-2 text-center text-xs">
                        <div>
                          <div className="text-sm font-mono text-red-600 font-bold">{row.shortage_count}</div>
                          <div className="text-gray-400">نقص</div>
                        </div>
                        <div>
                          <div className="text-sm font-mono text-blue-600 font-bold">{row.overstock_count}</div>
                          <div className="text-gray-400">فائض</div>
                        </div>
                        <div>
                          <div className="text-sm font-mono text-gray-500 font-bold">{row.dead_count}</div>
                          <div className="text-gray-400">راكد</div>
                        </div>
                        <div>
                          <div className="text-sm font-mono text-amber-600 font-bold">{fmt(row.shortage_value)} جم</div>
                          <div className="text-gray-400">قيمة نقص</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === 'by_medicine' && (
                <div className="p-5">
                  <DataTable
                    theadClass="bg-purple-50 text-xs text-purple-700"
                    defaultSort={{ key: 'shortage_count', dir: 'desc' }}
                    maxHeight="calc(100vh - 460px)"
                    rows={data.by_medicine_type || []}
                    emptyLabel="لا توجد بيانات"
                    columns={[
                      { key: 'type_label',      label: 'نوع الدواء',  type: 'text',    width: 250 },
                      { key: 'type_code',       label: 'الكود',       type: 'text',    width: 80,  render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
                      { key: 'item_count',      label: 'أصناف',       type: 'integer', width: 90,  render: v => <span className="font-mono text-gray-600">{fmt(v)}</span> },
                      { key: 'shortage_count',  label: 'ناقص',        type: 'integer', width: 90,  render: v => <span className="font-mono text-red-600 font-semibold">{fmt(v)}</span> },
                      { key: 'overstock_count', label: 'فائض',        type: 'integer', width: 90,  render: v => <span className="font-mono text-blue-600">{fmt(v)}</span> },
                      { key: 'shortage_value',  label: 'قيمة النقص',  type: 'number',  width: 140, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
                    ]}
                  />
                </div>
              )}

              {activeTab === 'investment' && (
                <div className="p-5 space-y-5">
                  {investLoading && (
                    <div className="flex justify-center h-32 items-center">
                      <div className="text-brand-600 animate-pulse">جارٍ تحليل رأس المال…</div>
                    </div>
                  )}
                  {investData?.error === 'no_run' && (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
                      <span className="text-3xl">⏳</span>
                      <p className="text-amber-700 font-semibold mt-2">لم يتم تشغيل محرك الطلب بعد</p>
                      <p className="text-xs text-amber-600 mt-1">يرجى تشغيل محرك الطلب من لوحة المشتريات أولاً</p>
                    </div>
                  )}
                  {investData && !investData.error && (
                    <>
                      {/* KPIs */}
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <KpiCard label="إجمالي رأس المال"    value={`${fmt(investData.total_capital)} جم`}
                          sub={`آخر تشغيل: ${investData.run_date || '—'}`}               color="brand" icon="💰" />
                        <KpiCard label="رأس المال الراكد"    value={`${fmt(investData.surplus_capital)} جم`}
                          sub={`${fmt(investData.surplus_pct, 1)}% من الإجمالي`}         color="amber" icon="📦" />
                        <KpiCard label="مرشحون للتصفية"      value={fmt(investData.liquidation?.length || 0)}
                          sub={`تغطية > ${investData.coverage_threshold} أشهر`}          color="red"   icon="⚠️" />
                        <KpiCard label="قيمة التصفية المحتملة"
                          value={`${fmt(investData.liquidation?.reduce((s, r) => s + r.surplus_value, 0))} جم`}
                          sub="فائض تكلفة الأصناف الراكدة"                               color="gray"  icon="📉" />
                      </div>

                      {/* ABC breakdown cards */}
                      <div>
                        <h3 className="text-sm font-semibold text-gray-700 mb-3">توزيع رأس المال حسب فئة ABC</h3>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                          {(investData.by_abc || []).map(row => {
                            const c = ABC_INV_COLORS[row.abc_class] || ABC_INV_COLORS.X
                            const surplusPct = row.stock_value > 0 ? (row.surplus_value / row.stock_value * 100).toFixed(1) : 0
                            return (
                              <div key={row.abc_class} className={`rounded-xl border p-4 ${c.bg} ${c.border}`}>
                                <div className="flex items-center justify-between mb-2">
                                  <span className={`text-lg font-black ${c.text}`}>{row.abc_class}</span>
                                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${c.badge}`}>{fmt(row.item_count)} صنف</span>
                                </div>
                                <p className={`text-xl font-bold font-mono ${c.text}`}>{fmt(row.stock_value)} جم</p>
                                <div className="mt-2 space-y-0.5 text-xs text-gray-500">
                                  <div>راكد: <span className="font-mono text-amber-600 font-semibold">{fmt(row.surplus_value)} جم</span>
                                    <span className="text-gray-400 mr-1">({surplusPct}%)</span>
                                  </div>
                                  {row.gap_value > 0 && (
                                    <div>فجوة: <span className="font-mono text-red-600">{fmt(row.gap_value)} جم</span></div>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>

                      {/* Per-branch table */}
                      <div>
                        <h3 className="text-sm font-semibold text-gray-700 mb-3">توزيع رأس المال بالفروع</h3>
                        <DataTable
                          theadClass="bg-brand-50 text-xs text-brand-700"
                          defaultSort={{ key: 'stock_value', dir: 'desc' }}
                          maxHeight="280px"
                          rows={investData.by_branch || []}
                          emptyLabel="لا توجد بيانات"
                          columns={[
                            { key: 'branch_name',    label: 'الفرع',          type: 'text',    width: 200 },
                            { key: 'item_count',     label: 'أصناف',          type: 'integer', width: 80,  render: v => <span className="font-mono text-gray-600">{fmt(v)}</span> },
                            { key: 'shortage_count', label: 'ناقص',           type: 'integer', width: 80,  render: v => <span className="font-mono text-red-600">{fmt(v)}</span> },
                            { key: 'stock_value',    label: 'رأس المال',       type: 'number',  width: 150, render: v => <span className="font-mono text-brand-700 font-semibold">{fmt(v)} جم</span> },
                            { key: 'surplus_value',  label: 'الراكد',          type: 'number',  width: 140, render: v => <span className="font-mono text-amber-600">{fmt(v)} جم</span> },
                          ]}
                        />
                      </div>

                      {/* Liquidation candidates */}
                      {(investData.liquidation || []).length > 0 && (
                        <div>
                          <div className="flex items-center justify-between mb-3">
                            <h3 className="text-sm font-semibold text-gray-700">
                              🔴 مرشحون للتصفية — تغطية &gt; {investData.coverage_threshold} أشهر
                            </h3>
                            <span className="text-xs text-gray-400">{investData.liquidation.length} صنف</span>
                          </div>
                          <DataTable
                            theadClass="bg-red-50 text-xs text-red-700"
                            defaultSort={{ key: 'coverage_months', dir: 'desc' }}
                            maxHeight="calc(100vh - 560px)"
                            rows={investData.liquidation || []}
                            emptyLabel="لا توجد مرشحين"
                            columns={[
                              { key: 'item_name',       label: 'الصنف',          type: 'text',   width: 260 },
                              { key: 'item_code',       label: 'الكود',          type: 'text',   width: 80,  render: v => <span className="font-mono text-xs text-gray-400">{v}</span> },
                              { key: 'branch',          label: 'الفرع',          type: 'text',   width: 150 },
                              { key: 'abc_class',       label: 'ABC',            type: 'text',   width: 60,  render: v => <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${ABC_COLORS[v] || ''}`}>{v}</span> },
                              { key: 'current_stock',   label: 'المخزون',        type: 'number', width: 100, render: v => <span className="font-mono text-gray-600">{fmt(v, 1)}</span> },
                              { key: 'safety_stock',    label: 'الأمان',         type: 'number', width: 90,  render: v => <span className="font-mono text-gray-400">{fmt(v, 1)}</span> },
                              { key: 'surplus_stock',   label: 'الفائض',         type: 'number', width: 90,  render: v => <span className="font-mono text-amber-600 font-semibold">{fmt(v, 1)}</span> },
                              { key: 'surplus_value',   label: 'قيمة الفائض',    type: 'number', width: 130, render: v => <span className="font-mono text-red-600 font-semibold">{fmt(v)} جم</span> },
                              { key: 'coverage_months', label: 'التغطية (شهر)',  type: 'number', width: 110, render: v => <span className="font-mono text-red-500">{fmt(v, 1)} شهر</span> },
                              { key: 'pack_price',      label: 'سعر العبوة',     type: 'number', width: 110, render: v => <span className="font-mono text-gray-500">{fmt(v, 2)} جم</span> },
                            ]}
                          />
                        </div>
                      )}
                    </>
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
