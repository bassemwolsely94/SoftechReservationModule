/**
 * ExpenseAnalyticsPage.jsx
 * Route: /finance/expenses
 *
 * Expense breakdown with:
 *  - Date range (free date_from / date_to) OR month+year selector
 *  - Category filter dropdown
 *  - Sub-category filter dropdown (dynamic — loads subcategories for selected category)
 *  - Branch filter dropdown
 *  - Sub-category breakdown panel (visible when category is selected)
 *  - English digits throughout (toLocaleString uses 'en-US')
 */

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { financeApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import { fa } from '../utils/flowArrow'
import useServerSort from '../hooks/useServerSort'
import SortTh from '../components/SortTh'
import MultiSelectFilter from '../components/MultiSelectFilter'
import BranchMultiSelect from '../components/BranchMultiSelect'

const SORT_KEYS = ['expense_date', 'category', 'sub_category', 'description', 'cost_center', 'branch__name', 'amount']

// ── Number formatter: English digits + comma separators ──────────────────────
const fmt = (n, d = 0) =>
  parseFloat(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })

const fmtPct = n => `${parseFloat(n || 0).toFixed(1)}%`

// ── Localisation ──────────────────────────────────────────────────────────────
const MONTHS_AR = [
  'يناير','فبراير','مارس','أبريل','مايو','يونيو',
  'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر',
]

const toggleIn = (arr, v) => (arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v])

const CATEGORY_AR = {
  payroll:      'رواتب وأجور',
  rent:         'إيجارات',
  utilities:    'مرافق',
  fuel:         'وقود ومواصلات',
  maintenance:  'صيانة',
  delivery:     'توصيل وشحن',
  marketing:    'تسويق وإعلان',
  finance_cost: 'تكاليف تمويلية',
  bank_charges: 'رسوم بنكية',
  taxes:        'ضرائب ورسوم',
  shrinkage:    'فاقد وعجز',
  expiry:       'منتهي الصلاحية',
  returns:      'مرتجعات',
  admin:        'مصروفات إدارية',
  depreciation: 'استهلاك',
  insurance:    'تأمين',
  other:        'أخرى',
}
const CATEGORY_OPTIONS = Object.entries(CATEGORY_AR).map(([code, name]) => ({ code, name }))

const CATEGORY_COLORS = [
  '#10b981','#3b82f6','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#f97316','#ec4899','#84cc16','#6366f1',
  '#14b8a6','#d946ef','#0ea5e9','#a3e635','#fb923c',
]

// ── Tiny design atoms ─────────────────────────────────────────────────────────
function Card({ children, className = '' }) {
  return (
    <div className={`bg-white rounded-2xl shadow-sm border border-gray-100 p-5 ${className}`}>
      {children}
    </div>
  )
}

function Select({ value, onChange, children, className = '' }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className={`border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:ring-2 focus:ring-green-200 focus:border-green-400 outline-none ${className}`}
    >
      {children}
    </select>
  )
}

function DateInput({ value, onChange, placeholder }) {
  return (
    <input
      type="date"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:ring-2 focus:ring-green-200 focus:border-green-400 outline-none"
    />
  )
}

function Chip({ label, onRemove, color = 'green' }) {
  const styles = {
    green:  'bg-green-50 border-green-200 text-green-800',
    orange: 'bg-orange-50 border-orange-200 text-orange-800',
    blue:   'bg-blue-50 border-blue-200 text-blue-800',
  }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 border rounded-full text-xs ${styles[color] || styles.green}`}>
      {label}
      <button onClick={onRemove} className="hover:text-red-500 font-bold leading-none">×</button>
    </span>
  )
}

// ── Category breakdown bar ────────────────────────────────────────────────────
function CategoryRow({ label, amount, total, colorIdx, active, onClick }) {
  const pct   = total > 0 ? (amount / total) * 100 : 0
  const color = CATEGORY_COLORS[colorIdx % CATEGORY_COLORS.length]
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-3 cursor-pointer rounded-lg px-2 py-1.5 transition-colors ${active ? 'bg-green-50 ring-1 ring-green-200' : 'hover:bg-gray-50'}`}
    >
      <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <div className="flex-1 text-sm text-gray-700 truncate">{label}</div>
      <div className="w-36 bg-gray-100 rounded-full h-1.5 overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: color }} />
      </div>
      <div className="w-10 text-xs text-gray-400 text-right">{fmtPct(pct)}</div>
      <div className="w-28 text-sm font-semibold text-gray-800 text-right" dir="ltr">{fmt(amount)}</div>
    </div>
  )
}

// ── Sub-category breakdown bar (compact) ─────────────────────────────────────
function SubCategoryRow({ label, amount, count, total, active, onClick }) {
  const pct = total > 0 ? (amount / total) * 100 : 0
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-3 cursor-pointer rounded-lg px-2 py-1 transition-colors text-xs ${active ? 'bg-blue-50 ring-1 ring-blue-200' : 'hover:bg-gray-50'}`}
    >
      <div className="flex-1 text-gray-700 truncate">{label}</div>
      <div className="w-24 bg-gray-100 rounded-full h-1 overflow-hidden">
        <div className="h-full rounded-full bg-blue-400 transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div className="w-8 text-gray-400 text-right">{fmtPct(pct)}</div>
      <div className="text-gray-400 text-right" style={{ minWidth: '2rem' }}>{count}</div>
      <div className="w-24 font-semibold text-gray-700 text-right" dir="ltr">{fmt(amount)}</div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function ExpenseAnalyticsPage() {
  const today = new Date()

  // Filter mode: 'month' (year+month selectors) or 'range' (date_from / date_to)
  const [filterMode,   setFilterMode]   = useState('month')
  const [year,         setYear]         = useState(today.getFullYear())
  const [month,        setMonth]        = useState(today.getMonth() + 1)
  const [dateFrom,     setDateFrom]     = useState('')
  const [dateTo,       setDateTo]       = useState('')
  // category / sub-category / branch are multi-select arrays (none ticked = all)
  const [category,     setCategory]     = useState([])
  const [subCategory,  setSubCategory]  = useState([])
  const [branchId,     setBranchId]     = useState([])
  const [page,         setPage]         = useState(1)
  const [ordering,     setOrdering]     = useState('')   // server-side sort of the paged detail list
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: SORT_KEYS })

  const YEARS = Array.from({ length: 5 }, (_, i) => today.getFullYear() - i)

  // Reset page when any filter changes
  const handleFilterChange = fn => (...args) => { fn(...args); setPage(1) }

  // When the categories change, keep only the sub-categories that belong to them
  const handleCategoryChange = vals => {
    setCategory(vals)
    if (vals.length) {
      const keep = new Set((subcatData || []).filter(r => vals.includes(r.category)).map(r => r.sub_category))
      setSubCategory(subs => subs.filter(x => keep.has(x)))
    }
    setPage(1)
  }
  const toggleCategory = c => handleCategoryChange(toggleIn(category, c))
  const toggleSub = sc => { setSubCategory(subs => toggleIn(subs, sc)); setPage(1) }

  // Build API params — shared across breakdown + list + subcategory queries
  const baseParams = useMemo(() => {
    const p = {}
    if (filterMode === 'range') {
      if (dateFrom) p.date_from = dateFrom
      if (dateTo)   p.date_to   = dateTo
    } else {
      p.year  = year
      p.month = month
    }
    if (category.length)    p.category     = category.join(',')
    if (subCategory.length) p.sub_category = subCategory.join(',')
    if (branchId.length)    p.branch_id    = branchId.join(',')
    return p
  }, [filterMode, year, month, dateFrom, dateTo, category, subCategory, branchId])

  // Params without subcategory — for breakdown and subcategory list
  const periodParams = useMemo(() => {
    const p = { ...baseParams }
    delete p.sub_category
    return p
  }, [baseParams])

  // ── Queries ──────────────────────────────────────────────────────────────────

  const { data: breakdown, isLoading: bLoading } = useQuery({
    queryKey: ['finance-expense-breakdown', periodParams],
    queryFn:  () => financeApi.expenseBreakdown(periodParams).then(r => r.data),
    staleTime: 60_000,
  })

  // Subcategory list — fetched when a category is selected
  const { data: subcatData, isLoading: subcatLoading } = useQuery({
    queryKey: ['finance-expense-subcategories', periodParams],
    queryFn:  () => financeApi.expenseSubcategories(periodParams).then(r => r.data),
    staleTime: 60_000,
    enabled:  true,   // always load; dropdown shows all or filtered by category
  })
  const subcategories = useMemo(() => subcatData || [], [subcatData])
  // one option per sub-category name (a name can sit under several categories), narrowed to the ticked categories
  const subOptions = useMemo(() => {
    const totals = new Map()
    subcategories.filter(s => !category.length || category.includes(s.category)).forEach(s => {
      totals.set(s.sub_category, (totals.get(s.sub_category) || 0) + parseFloat(s.total || 0))
    })
    return [...totals].map(([code, t]) => ({ code, name: `${code} (${fmt(t)})` }))
  }, [subcategories, category])

  // Detail list query
  const { data: listData, isLoading: lLoading } = useQuery({
    queryKey: ['finance-expenses-list', baseParams, page, ordering],
    queryFn:  () => financeApi.expenses({ ...baseParams, ...(ordering ? { ordering } : {}), page, page_size: 40 }).then(r => r.data),
    staleTime: 60_000,
  })

  // Branches list
  const { data: branchesData } = useQuery({
    queryKey: ['branches-list'],
    queryFn:  () => import('../api/client').then(m => m.default.get('/branches/')).then(r => r.data),
    staleTime: 300_000,
  })
  const branches = branchesData?.results || branchesData || []

  // ── Derived data ─────────────────────────────────────────────────────────────

  const catRows    = breakdown?.by_category   || []
  const subRows    = breakdown?.by_sub_category || []
  const total      = parseFloat(breakdown?.total || 0)
  const expenses   = listData?.results || []
  const totalCount = listData?.count || 0

  // Sub-category rows to display: prefer breakdown's list (same period)
  // filtered to active category when one is selected
  const subRowsVisible = category.length
    ? subRows.filter(r => category.includes(r.category))
    : subRows.slice(0, 20)

  // Sub-category total (for bar width calculation)
  const subTotal = subRowsVisible.reduce((s, r) => s + parseFloat(r.total || 0), 0)

  // Active filter chips
  const activeFilters = []
  category.forEach(c => activeFilters.push({
    label: CATEGORY_AR[c] || c,
    color: 'orange',
    clear: () => toggleCategory(c),
  }))
  subCategory.forEach(sc => activeFilters.push({
    label: sc,
    color: 'blue',
    clear: () => toggleSub(sc),
  }))
  branchId.forEach(id => {
    const b = branches.find(b => String(b.id) === String(id))
    activeFilters.push({
      label: b?.name || b?.name_ar || `فرع ${id}`,
      color: 'green',
      clear: () => { setBranchId(ids => ids.filter(x => x !== id)); setPage(1) },
    })
  })
  if (filterMode === 'range' && (dateFrom || dateTo)) {
    activeFilters.push({
      label: `${dateFrom || '?'} — ${dateTo || '?'}`,
      color: 'green',
      clear: () => { setDateFrom(''); setDateTo(''); setPage(1) },
    })
  }

  return (
    <div className="space-y-5" dir="rtl">

      <DataFreshnessBar domains={['finance_expenses']} />

      {/* ── Filter Bar ─────────────────────────────────────────────────────── */}
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3" data-tour="finance-expenses-filters">
          <h2 className="text-base font-bold text-gray-700 ml-auto">تحليل المصروفات</h2>

          {/* Filter mode toggle */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden text-xs" data-tour="finance-expenses-mode">
            {['month','range'].map(m => (
              <button key={m}
                onClick={() => { setFilterMode(m); setPage(1) }}
                className={`px-3 py-1.5 transition-colors ${filterMode === m ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              >
                {m === 'month' ? 'شهر / سنة' : 'نطاق تاريخ'}
              </button>
            ))}
          </div>

          {/* Month / Year OR Date Range */}
          {filterMode === 'month' ? (
            <>
              <Select value={year} onChange={handleFilterChange(v => setYear(Number(v)))}>
                {YEARS.map(y => <option key={y} value={y}>{y}</option>)}
              </Select>
              <Select value={month} onChange={handleFilterChange(v => setMonth(Number(v)))}>
                {MONTHS_AR.map((m, i) => <option key={i+1} value={i+1}>{m}</option>)}
              </Select>
            </>
          ) : (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span>من</span>
              <DateInput value={dateFrom} onChange={handleFilterChange(setDateFrom)} />
              <span>إلى</span>
              <DateInput value={dateTo}   onChange={handleFilterChange(setDateTo)} />
            </div>
          )}

          {/* Category filter */}
          <MultiSelectFilter className="w-[170px]" showCode={false} allLabel="كل الفئات" menuClassName="min-w-[220px]"
            options={CATEGORY_OPTIONS} selected={category} onChange={handleCategoryChange} />

          {/* Sub-category filter — shows all subcategories, or those for selected category */}
          <MultiSelectFilter className="w-[200px]" showCode={false} allLabel="كل التصنيفات الفرعية" menuClassName="min-w-[300px]"
            options={subOptions} selected={subCategory} onChange={v => { setSubCategory(v); setPage(1) }} />

          {/* Branch filter */}
          <BranchMultiSelect className="w-[180px]" branches={branches}
            selected={branchId} onChange={handleFilterChange(setBranchId)} />
        </div>

        {/* Active filter chips */}
        {activeFilters.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-gray-100" data-tour="finance-expenses-chips">
            <span className="text-xs text-gray-400 self-center">مرشحات نشطة:</span>
            {activeFilters.map((f, i) => (
              <Chip key={i} label={f.label} color={f.color} onRemove={f.clear} />
            ))}
            {activeFilters.length > 1 && (
              <button
                onClick={() => { setCategory([]); setSubCategory([]); setBranchId([]); setDateFrom(''); setDateTo(''); setPage(1) }}
                className="text-xs text-red-500 hover:underline px-1"
              >
                مسح الكل
              </button>
            )}
          </div>
        )}
      </Card>

      {/* ── Summary KPIs ───────────────────────────────────────────────────── */}
      {bLoading ? (
        <div className="h-20 bg-gray-50 rounded-2xl animate-pulse" />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4" data-tour="finance-expenses-kpis">
          <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 col-span-2">
            <div className="text-xs text-gray-500 mb-1">إجمالي المصروفات</div>
            <div className="text-2xl font-bold text-orange-700" dir="ltr">{fmt(total)}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              {filterMode === 'month'
                ? `${MONTHS_AR[month - 1]} ${year}`
                : (dateFrom || dateTo) ? `${dateFrom || '?'} — ${dateTo || '?'}` : '—'}
            </div>
          </div>
          <div className="bg-white border border-gray-100 rounded-xl p-4">
            <div className="text-xs text-gray-500 mb-1">عدد الفئات</div>
            <div className="text-2xl font-bold text-gray-800" dir="ltr">{catRows.length}</div>
          </div>
          <div className="bg-white border border-gray-100 rounded-xl p-4">
            <div className="text-xs text-gray-500 mb-1">عدد السجلات</div>
            <div className="text-2xl font-bold text-gray-800" dir="ltr">{fmt(totalCount)}</div>
          </div>
        </div>
      )}

      {/* ── Category breakdown + Sub-category breakdown side by side ────────── */}
      {!bLoading && catRows.length > 0 && (
        <div data-tour="finance-expenses-breakdown" className={`grid gap-5 ${subRowsVisible.length > 0 ? 'grid-cols-1 lg:grid-cols-2' : 'grid-cols-1'}`}>

          {/* Category breakdown */}
          <Card>
            <h3 className="text-sm font-semibold text-gray-700 mb-4">
              التوزيع بالفئة الرئيسية
            </h3>
            <div className="space-y-1" data-tour="finance-expenses-categories">
              {catRows.map((r, i) => (
                <CategoryRow
                  key={r.category}
                  label={CATEGORY_AR[r.category] || r.category}
                  amount={parseFloat(r.total || 0)}
                  total={total}
                  colorIdx={i}
                  active={category.includes(r.category)}
                  onClick={() => toggleCategory(r.category)}
                />
              ))}
            </div>
            <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400 text-center">
              انقر على الفئة لتصفية السجلات والتصنيفات الفرعية
            </div>
          </Card>

          {/* Sub-category breakdown — visible when there are subcategories */}
          {subRowsVisible.length > 0 && (
            <Card>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-gray-700">
                  {category.length
                    ? `التصنيفات الفرعية — ${category.map(c => CATEGORY_AR[c] || c).join('، ')}`
                    : 'أعلى التصنيفات الفرعية'}
                </h3>
                <span className="text-xs text-gray-400">{subRowsVisible.length} تصنيف</span>
              </div>

              {/* Column headers */}
              <div className="flex items-center gap-3 px-2 mb-2 text-xs text-gray-400">
                <div className="flex-1">الاسم</div>
                <div className="w-24" />
                <div className="w-8 text-right">%</div>
                <div style={{ minWidth: '2rem' }} className="text-right">عدد</div>
                <div className="w-24 text-right">المبلغ</div>
              </div>

              <div className="space-y-0.5 max-h-80 overflow-y-auto" data-tour="finance-expenses-subcategories">
                {subRowsVisible.map(r => (
                  <SubCategoryRow
                    key={r.sub_category}
                    label={r.sub_category}
                    amount={parseFloat(r.total || 0)}
                    count={r.count || 0}
                    total={subTotal}
                    active={subCategory.includes(r.sub_category)}
                    onClick={() => toggleSub(r.sub_category)}
                  />
                ))}
              </div>

              <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400 text-center">
                انقر على التصنيف الفرعي لتصفية القائمة أدناه
              </div>
            </Card>
          )}
        </div>
      )}

      {!bLoading && catRows.length === 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-8 text-center">
          <div className="text-4xl mb-3">📭</div>
          <div className="text-amber-800 text-sm font-medium">لا توجد سجلات مصروفات لهذه الفترة</div>
          <div className="text-amber-600 text-xs mt-1">تحقق من تشغيل مزامنة المصروفات: sync_finance --months 1</div>
        </div>
      )}

      {/* ── Expense detail table ─────────────────────────────────────────────── */}
      {expenses.length > 0 && (
        <Card className="p-0">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-700">تفاصيل المصروفات</h3>
            <span className="text-xs text-gray-400" dir="ltr">{fmt(totalCount)} سجل</span>
          </div>

          <div className="overflow-x-auto" data-tour="finance-expenses-table">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-xs text-gray-500">
                  <SortTh {...headerProps('expense_date', 'date')} className="px-4 py-2.5 text-right font-medium">التاريخ</SortTh>
                  <SortTh {...headerProps('category')} className="px-4 py-2.5 text-right font-medium">الفئة</SortTh>
                  <SortTh {...headerProps('sub_category')} className="px-4 py-2.5 text-right font-medium">التصنيف الفرعي</SortTh>
                  <SortTh {...headerProps('description')} className="px-4 py-2.5 text-right font-medium">البيان</SortTh>
                  <SortTh {...headerProps('cost_center')} className="px-4 py-2.5 text-right font-medium">مركز التكلفة</SortTh>
                  <SortTh {...headerProps('branch__name')} className="px-4 py-2.5 text-right font-medium">الفرع</SortTh>
                  <SortTh {...headerProps('amount', 'number')} className="px-4 py-2.5 text-right font-medium" dir="ltr">المبلغ</SortTh>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {expenses.map(e => (
                  <tr key={e.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap" dir="ltr">
                      {e.expense_date}
                    </td>

                    {/* Category badge — clickable */}
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => toggleCategory(e.category)}
                        className={`px-2 py-0.5 rounded-full text-xs border transition-colors whitespace-nowrap ${
                          category.includes(e.category)
                            ? 'bg-orange-200 border-orange-300 text-orange-900'
                            : 'bg-orange-50 border-orange-100 text-orange-700 hover:bg-orange-100'
                        }`}
                      >
                        {e.category_label || CATEGORY_AR[e.category] || e.category}
                      </button>
                    </td>

                    {/* Sub-category badge — clickable */}
                    <td className="px-4 py-2.5">
                      {e.sub_category ? (
                        <button
                          onClick={() => toggleSub(e.sub_category)}
                          className={`px-2 py-0.5 rounded-full text-xs border transition-colors max-w-[160px] truncate block ${
                            subCategory.includes(e.sub_category)
                              ? 'bg-blue-200 border-blue-300 text-blue-900'
                              : 'bg-blue-50 border-blue-100 text-blue-700 hover:bg-blue-100'
                          }`}
                          title={e.sub_category}
                        >
                          {e.sub_category}
                        </button>
                      ) : (
                        <span className="text-gray-300 text-xs">—</span>
                      )}
                    </td>

                    <td className="px-4 py-2.5 text-gray-700 max-w-xs truncate">
                      {e.description || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs">
                      {e.cost_center || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs">
                      {e.branch_name || '—'}
                    </td>
                    <td className="px-4 py-2.5 font-semibold text-gray-800 whitespace-nowrap" dir="ltr">
                      {fmt(e.amount, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between" data-tour="finance-expenses-pagination">
            <button
              disabled={page === 1}
              onClick={() => setPage(p => Math.max(1, p - 1))}
              className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-40 hover:bg-gray-50 transition-colors"
            >
              ← السابق
            </button>
            <span className="text-sm text-gray-500" dir="ltr">
              صفحة {page}
              {listData?.count ? ` من ${Math.ceil(listData.count / 40)}` : ''}
            </span>
            <button
              disabled={!listData?.next}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-40 hover:bg-gray-50 transition-colors"
            >
              التالي {fa()}
            </button>
          </div>
        </Card>
      )}

      {lLoading && (
        <div className="h-48 bg-gray-50 rounded-2xl animate-pulse" />
      )}
    </div>
  )
}
