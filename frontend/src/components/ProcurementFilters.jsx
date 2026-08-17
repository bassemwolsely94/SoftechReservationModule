/**
 * ProcurementFilters.jsx
 *
 * Shared, module-wide filter state for the procurement hub: a period selector
 * (narrative-reports style), branch multi-select (personal-module style), and
 * all supplier-category + item-attribute dimensions.  One bar at the hub top
 * drives every tab so you can slice/vector the same way across pages.
 *
 * Usage:
 *   <ProcurementFilterProvider> ... <ProcurementFilterBar/> <Outlet/> ... </ProcurementFilterProvider>
 *   const { params, options } = useProcurementFilters()   // inside any tab
 */
import { createContext, useContext, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { procurementIntelApi } from '../api/client'
import MultiSelectFilter from './MultiSelectFilter'

const PERIODS = [
  { key: 'today',   label: 'اليوم' },
  { key: 'week',    label: 'الأسبوع' },
  { key: 'month',   label: 'الشهر' },
  { key: 'quarter', label: 'الربع' },
  { key: 'year',    label: 'السنة' },
  { key: 'all',     label: 'الكل' },
  { key: 'custom',  label: 'مخصص' },
]

const EMPTY = {
  period: 'quarter', date_from: '', date_to: '',
  branch: [], supplier_category: [],
  medicine_type: [], family_code: [], producer_code: [], origin_code: [], shape_code: [], effect_code: [],
}

const ARRAY_KEYS = ['branch', 'supplier_category', 'medicine_type', 'family_code', 'producer_code', 'origin_code', 'shape_code', 'effect_code']

const Ctx = createContext(null)
export const useProcurementFilters = () => useContext(Ctx)

export function ProcurementFilterProvider({ children }) {
  const [filters, setFilters] = useState(EMPTY)

  const optsQ = useQuery({
    queryKey: ['proc-filter-options'],
    queryFn: () => procurementIntelApi.filterOptions().then(r => r.data),
    staleTime: 5 * 60_000,
  })
  const options = optsQ.data ?? {}

  // Build API params from the shared filters (arrays → csv, drop empties)
  const params = useMemo(() => {
    const out = {}
    if (filters.period === 'custom') {
      if (filters.date_from) out.date_from = filters.date_from
      if (filters.date_to)   out.date_to   = filters.date_to
    } else if (filters.period) {
      out.period = filters.period
    }
    for (const k of ARRAY_KEYS) {
      if (filters[k]?.length) out[k] = filters[k].join(',')
    }
    return out
  }, [filters])

  const value = { filters, setFilters, params, options, EMPTY }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function ProcurementFilterBar() {
  const { filters, setFilters, options } = useProcurementFilters()
  const [showAdv, setShowAdv] = useState(false)

  const set = (name, value) => setFilters(f => ({ ...f, [name]: value }))
  const advCount = ['medicine_type', 'family_code', 'producer_code', 'origin_code', 'shape_code', 'effect_code']
    .reduce((n, k) => n + (filters[k]?.length ? 1 : 0), 0)
  const activeCount = ARRAY_KEYS.reduce((n, k) => n + (filters[k]?.length ? 1 : 0), 0)

  return (
    <div className="bg-white border-b border-gray-200 px-6 py-3 space-y-2" dir="rtl">
      <div className="flex flex-wrap items-center gap-2">
        {/* Period presets */}
        <div className="flex bg-gray-100 rounded-lg p-0.5">
          {PERIODS.map(p => (
            <button key={p.key} onClick={() => set('period', p.key)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                filters.period === p.key ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              {p.label}
            </button>
          ))}
        </div>

        {filters.period === 'custom' && (
          <div className="flex items-center gap-1">
            <input type="date" value={filters.date_from} onChange={e => set('date_from', e.target.value)}
              className="input-field !py-1 text-xs !w-auto" />
            <span className="text-gray-400 text-xs">→</span>
            <input type="date" value={filters.date_to} onChange={e => set('date_to', e.target.value)}
              className="input-field !py-1 text-xs !w-auto" />
          </div>
        )}

        <div className="w-40"><MultiSelectFilter options={options.branches ?? []} selected={filters.branch}
          onChange={v => set('branch', v)} placeholder="كل الفروع" /></div>
        <div className="w-44"><MultiSelectFilter options={options.supplier_categories ?? []} selected={filters.supplier_category}
          onChange={v => set('supplier_category', v)} placeholder="كل فئات الموردين" /></div>

        <button onClick={() => setShowAdv(s => !s)}
          className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
            advCount ? 'border-brand-500 text-brand-700 bg-brand-50' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
          فلاتر الأصناف {advCount ? `(${advCount})` : ''} {showAdv ? '▲' : '▾'}
        </button>

        <div className="flex-1" />
        {activeCount > 0 && (
          <>
            <span className="text-xs text-gray-400">{activeCount} بُعد نشط</span>
            <button onClick={() => setFilters(f => ({ ...EMPTY, period: f.period }))}
              className="px-3 py-1 rounded-lg text-xs text-gray-500 border border-gray-300 hover:bg-gray-50">مسح الفلاتر</button>
          </>
        )}
      </div>

      {showAdv && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 pt-1">
          <MultiSelectFilter label="تصنيف عام" options={options.medicine_types ?? []} selected={filters.medicine_type} onChange={v => set('medicine_type', v)} />
          <MultiSelectFilter label="العائلة" options={options.families ?? []} selected={filters.family_code} onChange={v => set('family_code', v)} />
          <MultiSelectFilter label="الشركة المنتجة" options={options.producers ?? []} selected={filters.producer_code} onChange={v => set('producer_code', v)} />
          <MultiSelectFilter label="المنشأ" options={options.origins ?? []} selected={filters.origin_code} onChange={v => set('origin_code', v)} />
          <MultiSelectFilter label="الشكل الدوائي" options={options.shapes ?? []} selected={filters.shape_code} onChange={v => set('shape_code', v)} />
          <MultiSelectFilter label="الاستخدام" options={options.effects ?? []} selected={filters.effect_code} onChange={v => set('effect_code', v)} />
        </div>
      )}
    </div>
  )
}
