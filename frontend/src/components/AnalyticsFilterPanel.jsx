/**
 * AnalyticsFilterPanel.jsx
 *
 * Reusable, RTL-ready filter panel for all analytics dashboards.
 *
 * Props:
 *   filters    — current filter state object
 *   onChange   — (newFilters) => void
 *   options    — { branches, users, doc_types, channels, medicine_types,
 *                  suppliers, producers, persons, days_of_week }
 *   config     — { showDocCodes, showPersons, showChannels,
 *                  showMedicineTypes, showSuppliers, showProducers,
 *                  showPersonsMain, showDaysOfWeek, showHours, showBranches }
 *                all default true unless set to false
 *   loading    — bool  (show skeleton while options load)
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { analyticsApi } from '../api/client'

const today   = () => new Date().toISOString().slice(0, 10)
const daysAgo = d => { const dt = new Date(); dt.setDate(dt.getDate() - d); return dt.toISOString().slice(0, 10) }

const QUICK_RANGES = [
  { label: 'اليوم',   from: today(),    to: today()   },
  { label: '7 أيام', from: daysAgo(7), to: today()   },
  { label: '30 يوم', from: daysAgo(30),to: today()   },
  { label: '90 يوم', from: daysAgo(90),to: today()   },
]

/* ── SearchableMultiSelect ────────────────────────────────────────────────── */
/**
 * Multi-select dropdown with a built-in text search box.
 * options  — array of {code, label}
 * selected — array of code strings (the stored values)
 */
function SearchableMultiSelect({ label, options = [], selected = [], onChange, colorClass = 'brand' }) {
  const [open,  setOpen]  = useState(false)
  const [query, setQuery] = useState('')
  const boxRef = useRef(null)

  useEffect(() => {
    const handler = e => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = query.trim()
    ? options.filter(o => (o.label || '').toLowerCase().includes(query.trim().toLowerCase()))
    : options

  const toggle = code => {
    const s = String(code)
    onChange(selected.includes(s) ? selected.filter(x => x !== s) : [...selected, s])
  }

  const count = selected.length
  const allOn = count === 0

  const bgMap = { brand: 'bg-brand-600', blue: 'bg-blue-500', green: 'bg-green-500', amber: 'bg-amber-500' }
  const bg = bgMap[colorClass] || bgMap.brand

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg border transition-colors
          ${count > 0 ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-gray-300 bg-white text-gray-600 hover:border-brand-400'}`}
      >
        <span>{label}</span>
        {count > 0 && (
          <span className={`${bg} text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center font-bold`}>
            {count}
          </span>
        )}
        <span className="text-gray-400 text-[10px]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full mt-1 right-0 z-20 bg-white border border-gray-200 rounded-xl shadow-lg w-64">
            {/* Search input */}
            <div className="p-2 border-b border-gray-100">
              <input
                autoFocus
                type="text"
                value={query}
                placeholder="بحث…"
                className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none"
                onChange={e => setQuery(e.target.value)}
                onClick={e => e.stopPropagation()}
              />
            </div>

            <div className="max-h-56 overflow-y-auto">
              {/* Select-all row — only when no search */}
              {!query.trim() && (
                <button
                  type="button"
                  onClick={() => onChange([])}
                  className={`w-full text-right px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 border-b border-gray-100
                    ${allOn ? 'text-brand-600 font-semibold' : 'text-gray-500'}`}
                >
                  <span className={`w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center
                    ${allOn ? 'bg-brand-500 border-brand-500' : 'border-gray-300'}`}>
                    {allOn && <span className="text-white text-[8px]">✓</span>}
                  </span>
                  الكل
                </button>
              )}

              {filtered.length === 0 && (
                <p className="text-xs text-gray-400 text-center py-3">لا نتائج</p>
              )}

              {filtered.map(opt => {
                const val     = String(opt.code ?? opt.id ?? opt.value)
                const checked = selected.includes(val)
                return (
                  <button
                    key={val}
                    type="button"
                    onClick={() => toggle(val)}
                    className="w-full text-right px-3 py-2 text-xs hover:bg-brand-50 flex items-center gap-2 border-b border-gray-50 last:border-0"
                  >
                    <span className={`w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center
                      ${checked ? 'bg-brand-500 border-brand-500' : 'border-gray-300'}`}>
                      {checked && <span className="text-white text-[8px]">✓</span>}
                    </span>
                    <span className="text-gray-700 flex-1 text-right truncate">{opt.label || opt.name}</span>
                  </button>
                )
              })}
            </div>

            {count > 0 && (
              <div className="p-2 border-t border-gray-100">
                <button type="button" onClick={() => onChange([])} className="text-xs text-red-500 hover:text-red-700 underline">
                  مسح الكل ({count})
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/* ── CustomerSearch (typeahead) ───────────────────────────────────────────── */
function CustomerSearch({ selected = [], onChange }) {
  const [query,   setQuery]   = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [open,    setOpen]    = useState(false)
  const timer  = useRef(null)
  const boxRef = useRef(null)

  useEffect(() => {
    const handler = e => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const search = useCallback(q => {
    if (q.length < 2) { setResults([]); return }
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setLoading(true)
      try {
        const { data } = await analyticsApi.customerSearch(q, 15)
        setResults(data || [])
        setOpen(true)
      } catch { setResults([]) }
      finally { setLoading(false) }
    }, 280)
  }, [])

  const add    = c => { if (!selected.find(s => s.id === c.id)) onChange([...selected, c]); setQuery(''); setResults([]); setOpen(false) }
  const remove = id => onChange(selected.filter(s => s.id !== id))
  const count  = selected.length

  return (
    <div className="relative" ref={boxRef}>
      <button type="button"
        className={`flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg border transition-colors
          ${count > 0 ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-gray-300 bg-white text-gray-600 hover:border-brand-400'}`}
        onClick={() => setOpen(o => !o)}
      >
        <span>بحث عميل</span>
        {count > 0 && <span className="bg-brand-600 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center font-bold">{count}</span>}
        <span className="text-gray-400 text-[10px]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full mt-1 right-0 z-20 bg-white border border-gray-200 rounded-xl shadow-lg w-72">
            <div className="p-2 border-b border-gray-100">
              <input autoFocus type="text" value={query}
                placeholder="اسم / هاتف / PIC…"
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none"
                onChange={e => { setQuery(e.target.value); search(e.target.value) }}
                onClick={e => e.stopPropagation()}
              />
            </div>
            {selected.length > 0 && (
              <div className="px-2 py-1.5 flex flex-wrap gap-1 border-b border-gray-100">
                {selected.map(c => (
                  <span key={c.id} className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] bg-brand-100 text-brand-700 rounded-full">
                    {c.name}
                    <button type="button" onClick={() => remove(c.id)} className="hover:text-red-600">✕</button>
                  </span>
                ))}
              </div>
            )}
            <div className="max-h-52 overflow-y-auto">
              {loading && <p className="text-xs text-gray-400 text-center py-3">جارٍ البحث…</p>}
              {!loading && results.length === 0 && query.length >= 2 && (
                <p className="text-xs text-gray-400 text-center py-3">لا نتائج</p>
              )}
              {!loading && results.map(c => (
                <button key={c.id} type="button" onClick={() => add(c)}
                  className="w-full text-right px-3 py-2 text-xs hover:bg-brand-50 flex flex-col gap-0.5 border-b border-gray-50 last:border-0">
                  <span className="font-medium text-gray-800">{c.name}</span>
                  <span className="text-gray-400 font-mono">{c.softech_pic || c.phone} · {c.channel_label}</span>
                </button>
              ))}
            </div>
            {selected.length > 0 && (
              <div className="p-2 border-t border-gray-100">
                <button type="button" onClick={() => onChange([])} className="text-xs text-red-500 hover:text-red-700 underline">
                  مسح الكل ({count})
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/* ── HourRange ────────────────────────────────────────────────────────────── */
function HourRange({ hourFrom, hourTo, onChange }) {
  const hrs = Array.from({ length: 24 }, (_, i) => i)
  return (
    <div className="flex items-center gap-2">
      <select value={hourFrom ?? ''} onChange={e => onChange({ hourFrom: e.target.value || null, hourTo })}
        className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none">
        <option value="">من ساعة</option>
        {hrs.map(h => <option key={h} value={h}>{h}:00</option>)}
      </select>
      <span className="text-gray-400 text-xs">—</span>
      <select value={hourTo ?? ''} onChange={e => onChange({ hourFrom, hourTo: e.target.value || null })}
        className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none">
        <option value="">إلى ساعة</option>
        {hrs.map(h => <option key={h} value={h}>{h}:59</option>)}
      </select>
    </div>
  )
}

/* ── main component ──────────────────────────────────────────────────────── */
export default function AnalyticsFilterPanel({ filters = {}, onChange, options = {}, config = {}, loading = false }) {
  const [expanded, setExpanded] = useState(false)

  const cfg = {
    showBranches:      true,
    showDocCodes:      true,
    showPersons:       true,   // cashier/salesperson filter
    showChannels:      true,
    showCustomers:     true,   // typeahead customer search
    showPersonsMain:   true,   // العميل — persons from personsdata (searchable multi-select)
    showMedicineTypes: true,
    showSuppliers:     true,
    showProducers:     true,
    showStoreCodes:    true,
    showDaysOfWeek:    true,
    showHours:         true,
    ...config,
  }

  const set = patch => onChange({ ...filters, ...patch })

  const activeCount = [
    (filters.branches         || []).length,
    (filters.doc_codes        || []).length,
    (filters.person_codes     || []).length,
    (filters.channels         || []).length,
    (filters.customers        || []).length,
    (filters.person_main_codes|| []).length,
    (filters.medicine_types   || []).length,
    (filters.supplier_codes   || []).length,
    (filters.producer_codes   || []).length,
    (filters.store_codes      || []).length,
    (filters.days_of_week     || []).length,
    filters.hour_from != null ? 1 : 0,
    filters.hour_to   != null ? 1 : 0,
    filters.date_exact ? 1 : 0,
  ].reduce((a, b) => a + b, 0)

  const clearAll = () => onChange({
    date_from: filters.date_from,
    date_to:   filters.date_to,
    date_exact: '',
    hour_from: null, hour_to: null,
    branches: [], doc_codes: [], person_codes: [],
    channels: [], customers: [], person_main_codes: [],
    medicine_types: [], supplier_codes: [], producer_codes: [],
    store_codes: [], days_of_week: [],
  })

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      {/* ── Row 1: Date range + quick presets ── */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1.5">
          {QUICK_RANGES.map(r => (
            <button key={r.label} type="button"
              onClick={() => set({ date_from: r.from, date_to: r.to, date_exact: '' })}
              className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors
                ${filters.date_from === r.from && filters.date_to === r.to && !filters.date_exact
                  ? 'bg-brand-600 text-white border-brand-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'}`}>
              {r.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input type="date" value={filters.date_from || ''}
            onChange={e => set({ date_from: e.target.value, date_exact: '' })}
            className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          <span className="text-gray-400 text-xs">—</span>
          <input type="date" value={filters.date_to || ''}
            onChange={e => set({ date_to: e.target.value, date_exact: '' })}
            className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none" />
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-400">يوم بعينه:</span>
          <input type="date" value={filters.date_exact || ''}
            onChange={e => set({ date_exact: e.target.value })}
            className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          {filters.date_exact && (
            <button type="button" onClick={() => set({ date_exact: '' })} className="text-gray-400 hover:text-red-500 text-xs">✕</button>
          )}
        </div>

        <button type="button" onClick={() => setExpanded(e => !e)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors mr-auto
            ${activeCount > 0 ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-gray-300 text-gray-600 hover:border-brand-400'}`}>
          فلاتر متقدمة
          {activeCount > 0 && (
            <span className="bg-brand-600 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center font-bold">{activeCount}</span>
          )}
          <span className="text-gray-400 text-[10px]">{expanded ? '▲' : '▼'}</span>
        </button>

        {activeCount > 0 && (
          <button type="button" onClick={clearAll} className="text-xs text-red-500 hover:text-red-700 underline">
            مسح الفلاتر
          </button>
        )}
      </div>

      {/* ── Row 2: Advanced filters (collapsible) ── */}
      {expanded && (
        <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-100">

          {cfg.showBranches && (options.branches || []).length > 0 && (
            <SearchableMultiSelect
              label="الفروع"
              options={(options.branches || []).map(b => ({ code: String(b.id), label: b.name }))}
              selected={filters.branches || []}
              onChange={v => set({ branches: v })}
            />
          )}

          {cfg.showDocCodes && (
            <SearchableMultiSelect
              label="نوع الحركة"
              options={options.doc_types || [{ code: '115', label: 'مبيعات' }, { code: '30', label: 'مردودات' }]}
              selected={filters.doc_codes || []}
              onChange={v => set({ doc_codes: v })}
              colorClass="blue"
            />
          )}

          {cfg.showChannels && (
            <SearchableMultiSelect
              label="قناة البيع"
              options={options.channels || []}
              selected={filters.channels || []}
              onChange={v => set({ channels: v })}
              colorClass="green"
            />
          )}

          {/* نوع الشخص removed — not shown in any dashboard */}

          {cfg.showPersonsMain && (options.persons || []).length > 0 && (
            <SearchableMultiSelect
              label="العميل"
              options={options.persons || []}
              selected={filters.person_main_codes || []}
              onChange={v => set({ person_main_codes: v })}
              colorClass="green"
            />
          )}

          {cfg.showCustomers && (
            <CustomerSearch
              selected={filters.customers || []}
              onChange={v => set({ customers: v })}
            />
          )}

          {cfg.showPersons && (options.users || []).length > 0 && (
            <SearchableMultiSelect
              label="الكاشير / البائع"
              options={(options.users || []).map(u => ({
                code:  u.code,
                label: u.user_id
                  ? `${u.user_id} — ${u.code}${u.name && u.name !== u.code ? ` (${u.name})` : ''}`
                  : `${u.code}${u.name && u.name !== u.code ? ` — ${u.name}` : ''}`,
              }))}
              selected={filters.person_codes || []}
              onChange={v => set({ person_codes: v })}
            />
          )}

          {cfg.showMedicineTypes && (options.medicine_types || []).length > 0 && (
            <SearchableMultiSelect
              label="نوع الدواء"
              options={options.medicine_types || []}
              selected={filters.medicine_types || []}
              onChange={v => set({ medicine_types: v })}
              colorClass="blue"
            />
          )}

          {cfg.showSuppliers && (options.suppliers || []).length > 0 && (
            <SearchableMultiSelect
              label="المورد"
              options={options.suppliers || []}
              selected={filters.supplier_codes || []}
              onChange={v => set({ supplier_codes: v })}
              colorClass="blue"
            />
          )}

          {cfg.showProducers && (options.producers || []).length > 0 && (
            <SearchableMultiSelect
              label="المنتج"
              options={options.producers || []}
              selected={filters.producer_codes || []}
              onChange={v => set({ producer_codes: v })}
              colorClass="blue"
            />
          )}

          {cfg.showStoreCodes && (options.store_codes || []).length > 0 && (
            <SearchableMultiSelect
              label="المخزن"
              options={options.store_codes || []}
              selected={filters.store_codes || []}
              onChange={v => set({ store_codes: v })}
              colorClass="blue"
            />
          )}

          {cfg.showDaysOfWeek && (
            <SearchableMultiSelect
              label="أيام الأسبوع"
              options={(options.days_of_week || []).map(d => ({ code: String(d.code), label: d.label }))}
              selected={filters.days_of_week || []}
              onChange={v => set({ days_of_week: v })}
              colorClass="blue"
            />
          )}

          {cfg.showHours && (
            <HourRange
              hourFrom={filters.hour_from}
              hourTo={filters.hour_to}
              onChange={({ hourFrom, hourTo }) => set({ hour_from: hourFrom, hour_to: hourTo })}
            />
          )}

        </div>
      )}
    </div>
  )
}

/**
 * Converts the filter state object to query params for API calls.
 */
export function filtersToParams(f = {}) {
  const p = {}
  if (f.date_exact)                         p.date_exact         = f.date_exact
  else {
    if (f.date_from)                        p.date_from          = f.date_from
    if (f.date_to)                          p.date_to            = f.date_to
  }
  if (f.hour_from != null)                  p.hour_from          = f.hour_from
  if (f.hour_to   != null)                  p.hour_to            = f.hour_to
  if ((f.days_of_week     || []).length)    p.days_of_week       = f.days_of_week.join(',')
  if ((f.branches         || []).length)    p.branches           = f.branches.join(',')
  if ((f.doc_codes        || []).length)    p.doc_codes          = f.doc_codes.join(',')
  if ((f.person_codes     || []).length)    p.person_codes       = f.person_codes.join(',')
  if ((f.channels         || []).length)    p.channels           = f.channels.join(',')
  // customers = array of {id, name, ...} objects — extract IDs
  if ((f.customers        || []).length)    p.customer_ids       = f.customers.map(c => c.id).join(',')
  // person_main_codes = softech_ids from العميل dropdown
  if ((f.person_main_codes|| []).length)    p.person_main_codes  = f.person_main_codes.join(',')
  if ((f.medicine_types   || []).length)    p.medicine_types     = f.medicine_types.join(',')
  if ((f.supplier_codes   || []).length)    p.supplier_codes     = f.supplier_codes.join(',')
  if ((f.producer_codes   || []).length)    p.producer_codes     = f.producer_codes.join(',')
  if ((f.store_codes      || []).length)    p.store_codes        = f.store_codes.join(',')
  return p
}

/** Default filter state — pre-filled with last 30 days */
export function defaultFilters(overrides = {}) {
  return {
    date_from:        daysAgo(30),
    date_to:          today(),
    date_exact:       '',
    hour_from:        null,
    hour_to:          null,
    days_of_week:     [],
    branches:         [],
    doc_codes:        [],
    person_codes:     [],
    channels:         [],
    customers:        [],   // array of {id, name, phone, softech_pic, channel_label}
    person_main_codes:[],   // array of softech_id strings (العميل dropdown)
    medicine_types:   [],
    supplier_codes:   [],
    producer_codes:   [],
    store_codes:      [],
    ...overrides,
  }
}
