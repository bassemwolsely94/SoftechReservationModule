/**
 * AdvancedItemSearchModal.jsx
 *
 * Comprehensive multi-criteria item search modal — mirrors SOFTECH ERP item search.
 * Triggered by Ctrl+F1 shortcut or the magnifier button inside ItemSearchWidget.
 *
 * Keyboard shortcuts:
 *   Esc    — Close modal
 *   F7     — Reset all criteria
 *   F8     — Execute search
 *   ↑ / ↓  — Navigate result rows
 *   Enter  — Select highlighted row
 *
 * Props:
 *   onSelect(item) — called when the user picks an item; modal stays open control stays
 *   onClose()      — called when modal should be dismissed
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const PAGE_SIZE = 30

// Static insurance-type options (same as backend INSURANCE_TYPE_OPTIONS)
const INSURANCE_OPTS = [
  { code: '0', label: 'غير خاضع للتأمين' },
  { code: '1', label: 'طلبية' },
  { code: '2', label: 'TPA' },
  { code: '3', label: 'تكافل' },
  { code: '4', label: 'أخرى' },
]

const EMPTY_CRITERIA = {
  search:         '',   // name / scientific-name / code / barcode (wildcard * supported)
  category:       '',
  supplier_code:  '',
  producer_code:  '',
  medicine_type:  '',
  family_code:    '',
  pack_price_min: '',
  pack_price_max: '',
  unit_price_min: '',
  unit_price_max: '',
  insurance_type: '',
  item_level:     '',
  is_fast_moving: false,
  requires_fridge: false,
  has_points:     false,
}

// Columns that can be sorted and their backend ordering field names
const SORTABLE_COLS = {
  softech_id:      'softech_id',
  name:            'name',
  name_scientific: 'name_scientific',
  pack_price:      'pack_price',
  unit_price:      'unit_price',
  total_stock:     'total_stock',
  category_name:   'category__name',
}

/**
 * Convert the criteria object into API query params (omit blank/false values).
 */
function buildParams(criteria) {
  const p = {}

  const q = (criteria.search || '').trim()
  if (q) {
    if (q.includes('*')) {
      p.name = q
    } else {
      p.search = q
    }
  }

  if (criteria.category)       p.category        = criteria.category
  if (criteria.supplier_code)  p.supplier_code   = criteria.supplier_code
  if (criteria.producer_code)  p.producer_code   = criteria.producer_code
  if (criteria.medicine_type)  p.medicine_type   = criteria.medicine_type
  if (criteria.family_code)    p.family_code     = criteria.family_code
  if (criteria.pack_price_min) p.pack_price_min  = criteria.pack_price_min
  if (criteria.pack_price_max) p.pack_price_max  = criteria.pack_price_max
  if (criteria.unit_price_min) p.unit_price_min  = criteria.unit_price_min
  if (criteria.unit_price_max) p.unit_price_max  = criteria.unit_price_max
  if (criteria.insurance_type) p.insurance_type  = criteria.insurance_type
  if (criteria.item_level !== '') p.item_level   = criteria.item_level
  if (criteria.is_fast_moving) p.is_fast_moving  = 'true'
  if (criteria.requires_fridge) p.requires_fridge = 'true'
  if (criteria.has_points)     p.has_points      = 'true'
  return p
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SelectField({ label, value, onChange, children }) {
  return (
    <div>
      <label className="block text-[11px] font-semibold text-gray-500 mb-1">{label}</label>
      <select
        className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-400 bg-white"
        value={value}
        onChange={e => onChange(e.target.value)}
      >
        {children}
      </select>
    </div>
  )
}

function NumberField({ label, value, onChange, placeholder }) {
  return (
    <div>
      <label className="block text-[11px] font-semibold text-gray-500 mb-1">{label}</label>
      <input
        type="number"
        min="0"
        step="0.01"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-400"
      />
    </div>
  )
}

function StockBadge({ stock }) {
  if (stock === null || stock === undefined) return <span className="text-gray-400">—</span>
  const n = Number(stock)
  if (n > 10) return <span className="font-bold text-green-600">{n}</span>
  if (n > 0)  return <span className="font-bold text-amber-600">{n}</span>
  return <span className="font-bold text-red-500">0</span>
}

/** Sortable column header — shows sort indicator and handles click */
function SortTh({ colKey, sortField, sortDir, onSort, children, className = '' }) {
  const active = sortField === colKey
  return (
    <th
      className={`px-3 py-2.5 text-right select-none cursor-pointer group ${className}`}
      onClick={() => onSort(colKey)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        <span className={`text-[10px] leading-none transition-colors ${
          active ? 'text-brand-600' : 'text-gray-300 group-hover:text-gray-400'
        }`}>
          {active ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
        </span>
      </span>
    </th>
  )
}

// ── Main modal ─────────────────────────────────────────────────────────────────

export default function AdvancedItemSearchModal({ onSelect, onClose }) {
  const [criteria,     setCriteria]     = useState({ ...EMPTY_CRITERIA })
  const [activeParams, setActiveParams] = useState(null)   // null = not searched yet
  const [page,         setPage]         = useState(1)
  const [highlighted,  setHighlighted]  = useState(-1)

  // Sort state — field key + direction
  const [sortField, setSortField] = useState('name')
  const [sortDir,   setSortDir]   = useState('asc')

  const firstInputRef  = useRef(null)
  const resultsBodyRef = useRef(null)

  // ── Filter options ──────────────────────────────────────────────────────────
  const { data: opts = {} } = useQuery({
    queryKey: ['item-filter-options'],
    queryFn: () => api.get('/items/filter-options/').then(r => r.data),
    staleTime: 5 * 60_000,
  })

  // Build ordering string for API
  const orderingParam = sortDir === 'asc'
    ? (SORTABLE_COLS[sortField] || sortField)
    : `-${SORTABLE_COLS[sortField] || sortField}`

  // ── Search results ──────────────────────────────────────────────────────────
  const { data: searchData, isFetching } = useQuery({
    queryKey: ['adv-item-search', activeParams, page, orderingParam],
    queryFn: () =>
      api.get('/items/', {
        params: { ...activeParams, page, page_size: PAGE_SIZE, ordering: orderingParam },
      }).then(r => r.data),
    enabled: activeParams !== null,
    staleTime: 10_000,
    keepPreviousData: true,
  })

  const results    = searchData?.results || []
  const totalCount = searchData?.count   || 0
  const totalPages = Math.ceil(totalCount / PAGE_SIZE)

  // ── Auto-focus first input ──────────────────────────────────────────────────
  useEffect(() => { setTimeout(() => firstInputRef.current?.focus(), 80) }, [])

  // ── Reset highlight when results change ─────────────────────────────────────
  useEffect(() => { setHighlighted(-1) }, [results])

  // ── Scroll highlighted row into view ───────────────────────────────────────
  useEffect(() => {
    if (highlighted >= 0 && resultsBodyRef.current) {
      resultsBodyRef.current
        .querySelector(`[data-row="${highlighted}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    }
  }, [highlighted])

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleSearch = useCallback(() => {
    setPage(1)
    setHighlighted(-1)
    setActiveParams(buildParams(criteria))
  }, [criteria])

  const handleReset = useCallback(() => {
    setCriteria({ ...EMPTY_CRITERIA })
    setActiveParams(null)
    setHighlighted(-1)
    setSortField('name')
    setSortDir('asc')
    setTimeout(() => firstInputRef.current?.focus(), 50)
  }, [])

  const handleSelect = useCallback((item) => {
    onSelect(item)
    onClose()
  }, [onSelect, onClose])

  function set(field, value) {
    setCriteria(prev => ({ ...prev, [field]: value }))
  }

  /** Toggle sort: same column → flip direction; new column → asc */
  function handleSort(colKey) {
    if (!SORTABLE_COLS[colKey]) return
    if (sortField === colKey) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(colKey)
      setSortDir('asc')
    }
    setPage(1)
    setHighlighted(-1)
  }

  // ── Global keyboard shortcuts ────────────────────────────────────────────────
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'F7') { e.preventDefault(); handleReset(); return }
      if (e.key === 'F8') { e.preventDefault(); handleSearch(); return }
      if (e.key === 'ArrowDown' && results.length > 0) {
        e.preventDefault()
        setHighlighted(i => Math.min(i + 1, results.length - 1))
        return
      }
      if (e.key === 'ArrowUp' && results.length > 0) {
        e.preventDefault()
        setHighlighted(i => Math.max(i - 1, -1))
        return
      }
      if (e.key === 'Enter' && highlighted >= 0 && results[highlighted]) {
        e.preventDefault()
        handleSelect(results[highlighted])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [results, highlighted, handleReset, handleSearch, handleSelect, onClose])

  // ── Render ───────────────────────────────────────────────────────────────────
  const inputCls = 'w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-400'
  const labelCls = 'block text-[11px] font-semibold text-gray-500 mb-1'

  const sortProps = { sortField, sortDir, onSort: handleSort }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-3"
      dir="rtl"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-2xl shadow-2xl flex flex-col w-full max-w-7xl"
        style={{ height: '90vh' }}>

        {/* ── Header ──────────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-gray-50 rounded-t-2xl flex-shrink-0">
          <div>
            <h2 className="text-sm font-black text-gray-900">
              🔍 البحث المتقدم عن الأصناف
            </h2>
            <p className="text-[10px] text-gray-400 mt-0.5 font-mono">
              F7: إعادة تعيين · F8: بحث · ↑↓: تنقل في النتائج · Enter: اختيار · Esc: إغلاق
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none font-light w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100"
          >✕</button>
        </div>

        {/* ── Criteria ────────────────────────────────────────────────────────── */}
        <div className="px-5 pt-4 pb-3 border-b border-gray-100 flex-shrink-0">

          {/* Row 1: main text search + category + medicine type + family */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <div className="md:col-span-2">
              <label className={labelCls}>
                اسم الصنف / اسم علمي / كود / باركود
              </label>
              <input
                ref={firstInputRef}
                type="text"
                className={inputCls}
                placeholder="مثال: urosolv* أو par* أو *cillin أو 6221077... أو كود 404"
                value={criteria.search}
                onChange={e => set('search', e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
              />
              <p className="text-[10px] text-gray-400 mt-0.5">
                بدون *: بحث في الاسم والكود والباركود ·
                مع *: بحث بالاسم فقط مع بدل
                (<span className="font-mono text-brand-500">urosolv*</span> = كل ما يبدأ بـ urosolv ·
                <span className="font-mono text-brand-500">*cillin</span> = كل ما ينتهي بـ cillin ·
                <span className="font-mono text-brand-500">amox*500</span> = بدل في المنتصف)
              </p>
            </div>

            <SelectField label="الفئة" value={criteria.category} onChange={v => set('category', v)}>
              <option value=''>-- الكل --</option>
              {(opts.categories || []).map(c => (
                <option key={c.id} value={c.id}>{c.name_ar || c.name}</option>
              ))}
            </SelectField>

            <SelectField label="نوع الدواء" value={criteria.medicine_type} onChange={v => set('medicine_type', v)}>
              <option value=''>-- الكل --</option>
              {(opts.medicine_types || []).map(m => (
                <option key={m.code} value={m.code}>{m.name_ar || m.name}</option>
              ))}
            </SelectField>
          </div>

          {/* Row 2: supplier, producer, family/form, insurance */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <SelectField label="المورد" value={criteria.supplier_code} onChange={v => set('supplier_code', v)}>
              <option value=''>-- الكل --</option>
              {(opts.suppliers || []).map(s => (
                <option key={s.code} value={s.code}>{s.name}</option>
              ))}
            </SelectField>

            <SelectField label="الشركة المنتجة" value={criteria.producer_code} onChange={v => set('producer_code', v)}>
              <option value=''>-- الكل --</option>
              {(opts.producers || []).map(p => (
                <option key={p.code} value={p.code}>{p.name}</option>
              ))}
            </SelectField>

            <SelectField label="الشكل الدوائي" value={criteria.family_code} onChange={v => set('family_code', v)}>
              <option value=''>-- الكل --</option>
              {(opts.families || []).map(f => (
                <option key={f.code} value={f.code}>{f.name_ar || f.name}</option>
              ))}
            </SelectField>

            <SelectField label="نوع التأمين" value={criteria.insurance_type} onChange={v => set('insurance_type', v)}>
              <option value=''>-- الكل --</option>
              {INSURANCE_OPTS.map(o => (
                <option key={o.code} value={o.code}>{o.label}</option>
              ))}
            </SelectField>
          </div>

          {/* Row 3: price ranges + item level */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">
            <NumberField label="سعر العبوة من" value={criteria.pack_price_min}
              onChange={v => set('pack_price_min', v)} placeholder="0.00" />
            <NumberField label="سعر العبوة إلى" value={criteria.pack_price_max}
              onChange={v => set('pack_price_max', v)} placeholder="9999.00" />
            <NumberField label="سعر الوحدة من" value={criteria.unit_price_min}
              onChange={v => set('unit_price_min', v)} placeholder="0.00" />
            <NumberField label="سعر الوحدة إلى" value={criteria.unit_price_max}
              onChange={v => set('unit_price_max', v)} placeholder="9999.00" />

            <SelectField label="مستوى الصنف" value={criteria.item_level} onChange={v => set('item_level', v)}>
              <option value=''>-- الكل --</option>
              <option value="0">قياسي</option>
              <option value="1">خاص</option>
            </SelectField>
          </div>

          {/* Row 4: checkboxes + action bar */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Checkboxes */}
            <div className="flex flex-wrap gap-4">
              {[
                ['is_fast_moving',  'سريع الحركة'],
                ['requires_fridge', 'يحتاج تبريد ❄️'],
                ['has_points',      'له نقاط'],
              ].map(([field, label]) => (
                <label key={field}
                  className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer select-none">
                  <input type="checkbox" className="rounded"
                    checked={criteria[field]}
                    onChange={e => set(field, e.target.checked)} />
                  {label}
                </label>
              ))}
            </div>

            {/* Count + buttons */}
            <div className="flex items-center gap-3">
              <div className="text-xs text-gray-400 min-w-[100px] text-left">
                {activeParams !== null && !isFetching && (
                  <span>{totalCount.toLocaleString('en-US')} نتيجة</span>
                )}
                {isFetching && (
                  <span className="text-brand-500 flex items-center gap-1">
                    <span className="w-3 h-3 border-2 border-brand-200 border-t-brand-500 rounded-full animate-spin inline-block" />
                    جارٍ البحث...
                  </span>
                )}
              </div>
              <button onClick={handleReset}
                className="px-4 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 text-gray-600 flex items-center gap-1">
                <span className="text-[10px] font-mono bg-gray-100 px-1 rounded text-gray-400">F7</span>
                إعادة تعيين
              </button>
              <button onClick={handleSearch}
                className="px-5 py-1.5 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-semibold flex items-center gap-1">
                <span className="text-[10px] font-mono bg-brand-500/50 px-1 rounded">F8</span>
                بحث
              </button>
            </div>
          </div>
        </div>

        {/* ── Results table ────────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto min-h-0" ref={resultsBodyRef}>
          {activeParams === null ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-300 gap-2">
              <div className="text-5xl">🔍</div>
              <div className="text-sm font-medium">حدد معايير البحث واضغط F8 أو زر "بحث"</div>
              <div className="text-xs opacity-70">يمكنك البحث بالاسم أو الكود أو الباركود أو بمجموعة معايير متقدمة</div>
            </div>
          ) : results.length === 0 && !isFetching ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-300 gap-2">
              <div className="text-5xl">📭</div>
              <div className="text-sm font-medium">لا توجد نتائج للمعايير المحددة</div>
              <div className="text-xs opacity-70">جرب تغيير أو تقليل معايير البحث</div>
            </div>
          ) : (
            <table className="w-full text-xs border-collapse">
              <thead className="sticky top-0 z-10 bg-gray-50 border-b-2 border-gray-200">
                <tr className="text-[11px] text-gray-500 font-semibold">
                  <th className="px-2 py-2.5 text-center w-8 font-mono">#</th>
                  <SortTh colKey="softech_id" {...sortProps} className="w-16">الكود</SortTh>
                  <SortTh colKey="name" {...sortProps} className="min-w-[220px]">الاسم</SortTh>
                  <SortTh colKey="name_scientific" {...sortProps} className="min-w-[160px]">الاسم العلمي</SortTh>
                  <th className="px-3 py-2.5 text-right w-28">الباركود</th>
                  <SortTh colKey="category_name" {...sortProps} className="w-28">الفئة</SortTh>
                  <SortTh colKey="pack_price" {...sortProps} className="w-24">سعر العبوة</SortTh>
                  <SortTh colKey="unit_price" {...sortProps} className="w-24">سعر الوحدة</SortTh>
                  <SortTh colKey="total_stock" {...sortProps} className="w-20 text-center">المخزون</SortTh>
                  <th className="px-2 py-2.5 text-center w-10" title="سريع الحركة">FMI</th>
                  <th className="px-2 py-2.5 text-center w-10" title="يحتاج تبريد">❄️</th>
                  <th className="px-3 py-2.5 text-right min-w-[100px]">المورد</th>
                  <th className="px-3 py-2.5 text-right min-w-[100px]">المنتج</th>
                  <th className="px-2 py-2.5 text-center w-16"></th>
                </tr>
              </thead>
              <tbody>
                {results.map((item, idx) => {
                  const isHL          = idx === highlighted
                  const primaryBarcode = item.all_barcodes?.[0] || item.barcode || ''

                  return (
                    <tr
                      key={item.id}
                      data-row={idx}
                      className={`border-b border-gray-50 cursor-pointer transition-colors
                        ${isHL ? 'bg-brand-50 outline outline-1 outline-brand-300' : 'hover:bg-gray-50'}`}
                      onMouseEnter={() => setHighlighted(idx)}
                      onClick={() => handleSelect(item)}
                    >
                      {/* # */}
                      <td className="px-2 py-2 text-center text-gray-400 font-mono">
                        {(page - 1) * PAGE_SIZE + idx + 1}
                      </td>

                      {/* Code */}
                      <td className="px-3 py-2 font-mono font-bold text-blue-700">
                        {item.softech_id}
                      </td>

                      {/* Name — full wrap, no truncation */}
                      <td className="px-3 py-2 font-semibold text-gray-900 min-w-[220px]">
                        <div className="whitespace-normal leading-snug">{item.name}</div>
                      </td>

                      {/* Scientific name — full wrap, no truncation */}
                      <td className="px-3 py-2 text-gray-500 italic min-w-[160px]">
                        <div className="whitespace-normal leading-snug">
                          {item.name_scientific || '—'}
                        </div>
                      </td>

                      {/* Barcode */}
                      <td className="px-3 py-2 font-mono text-gray-500">
                        {primaryBarcode || '—'}
                      </td>

                      {/* Category */}
                      <td className="px-3 py-2 text-gray-600 max-w-[110px]">
                        <div className="whitespace-normal leading-snug">{item.category_name || '—'}</div>
                      </td>

                      {/* Pack price */}
                      <td className="px-3 py-2 text-emerald-700 font-bold text-right">
                        {item.pack_price > 0 ? Number(item.pack_price).toFixed(2) : '—'}
                      </td>

                      {/* Unit price */}
                      <td className="px-3 py-2 text-teal-700 text-right">
                        {item.unit_price > 0 ? Number(item.unit_price).toFixed(2) : '—'}
                      </td>

                      {/* Stock */}
                      <td className="px-3 py-2 text-center">
                        <StockBadge stock={item.total_stock} />
                      </td>

                      {/* FMI */}
                      <td className="px-2 py-2 text-center text-green-600">
                        {item.is_fast_moving ? '✓' : ''}
                      </td>

                      {/* Fridge */}
                      <td className="px-2 py-2 text-center">
                        {item.requires_fridge ? '❄️' : ''}
                      </td>

                      {/* Supplier */}
                      <td className="px-3 py-2 text-gray-500 max-w-[110px]">
                        <div className="whitespace-normal leading-snug" title={item.supplier_name}>
                          {item.supplier_name || '—'}
                        </div>
                      </td>

                      {/* Producer */}
                      <td className="px-3 py-2 text-gray-500 max-w-[110px]">
                        <div className="whitespace-normal leading-snug" title={item.producer_name}>
                          {item.producer_name || '—'}
                        </div>
                      </td>

                      {/* Select button */}
                      <td className="px-2 py-2 text-center">
                        <button
                          onClick={e => { e.stopPropagation(); handleSelect(item) }}
                          className={`text-[10px] px-2 py-1 rounded font-semibold transition-colors
                            ${isHL
                              ? 'bg-brand-600 text-white'
                              : 'bg-gray-100 text-gray-600 hover:bg-brand-100 hover:text-brand-700'}`}
                        >
                          اختر
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Pagination footer ────────────────────────────────────────────────── */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-5 py-2 border-t border-gray-100 bg-gray-50 rounded-b-2xl flex-shrink-0">
            <div className="text-xs text-gray-500">
              {totalCount.toLocaleString('en-US')} نتيجة — صفحة {page} من {totalPages}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setPage(1); setHighlighted(-1) }}
                disabled={page <= 1}
                className="px-2 py-1 text-xs border rounded hover:bg-gray-100 disabled:opacity-40"
              >
                «
              </button>
              <button
                onClick={() => { setPage(p => Math.max(1, p - 1)); setHighlighted(-1) }}
                disabled={page <= 1}
                className="px-3 py-1 text-xs border rounded hover:bg-gray-100 disabled:opacity-40"
              >
                السابق
              </button>
              {/* Page number chips */}
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const start = Math.max(1, Math.min(page - 2, totalPages - 4))
                const p     = start + i
                return (
                  <button
                    key={p}
                    onClick={() => { setPage(p); setHighlighted(-1) }}
                    className={`w-7 h-7 text-xs rounded border transition-colors
                      ${p === page
                        ? 'bg-brand-600 text-white border-brand-600'
                        : 'hover:bg-gray-100 border-gray-200'}`}
                  >
                    {p}
                  </button>
                )
              })}
              <button
                onClick={() => { setPage(p => Math.min(totalPages, p + 1)); setHighlighted(-1) }}
                disabled={page >= totalPages}
                className="px-3 py-1 text-xs border rounded hover:bg-gray-100 disabled:opacity-40"
              >
                التالي
              </button>
              <button
                onClick={() => { setPage(totalPages); setHighlighted(-1) }}
                disabled={page >= totalPages}
                className="px-2 py-1 text-xs border rounded hover:bg-gray-100 disabled:opacity-40"
              >
                »
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
