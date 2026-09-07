/**
 * ItemOperationalFiltersBar.jsx
 *
 * Reusable collapsible filter panel for item operational / classification fields.
 * Used by InventoryDashboard and SalesDashboard.
 *
 * Props:
 *   filters  — state from emptyItemFilters()
 *   onChange — (newFilters) => void
 *   options  — response from itemsApi.filterOptions()
 *              { insurance_types, item_level_options, trans_options,
 *                nosale_classif_options, store_classif_options }
 */
import { useState, useRef, useEffect } from 'react'

const SEL     = 'border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs bg-white focus:ring-2 focus:ring-brand-400 focus:outline-none'
const CHK_LBL = 'flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none'

/* ── helpers ─────────────────────────────────────────────────────────────── */

export function emptyItemFilters() {
  return {
    insurance_types: [],
    item_level:      '',
    nosale_classifs: [],
    store_classifs:  [],
    is_fast_moving:  false,
    has_points:      false,
    branch_trans:    '',
    supplier_trans:  '',
    customer_trans:  '',
  }
}

export function buildItemParams(f) {
  const p = {}
  if ((f.insurance_types || []).length) p.insurance_types = f.insurance_types.join(',')
  if (f.item_level)                     p.item_level      = f.item_level
  if ((f.nosale_classifs || []).length) p.nosale_classifs = f.nosale_classifs.join(',')
  if ((f.store_classifs  || []).length) p.store_classifs  = f.store_classifs.join(',')
  if (f.is_fast_moving)                 p.is_fast_moving  = '1'
  if (f.has_points)                     p.has_points      = '1'
  if (f.branch_trans)                   p.branch_trans    = f.branch_trans
  if (f.supplier_trans)                 p.supplier_trans  = f.supplier_trans
  if (f.customer_trans)                 p.customer_trans  = f.customer_trans
  return p
}

export function countActiveItemFilters(f) {
  return [
    (f.insurance_types || []).length > 0 ? 1 : 0,
    f.item_level        ? 1 : 0,
    (f.nosale_classifs  || []).length > 0 ? 1 : 0,
    (f.store_classifs   || []).length > 0 ? 1 : 0,
    f.is_fast_moving    ? 1 : 0,
    f.has_points        ? 1 : 0,
    f.branch_trans      ? 1 : 0,
    f.supplier_trans    ? 1 : 0,
    f.customer_trans    ? 1 : 0,
  ].reduce((a, b) => a + b, 0)
}

function toggleCode(arr, code) {
  const s = String(code)
  return arr.includes(s) ? arr.filter(x => x !== s) : [...arr, s]
}

/* ── PillMultiSelect — for small lists (≤ 10 items) ─────────────────────── */
function PillMultiSelect({ options = [], selected = [], onChange }) {
  if (!options.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {options.map(opt => {
        const val = String(opt.code)
        const on  = selected.includes(val)
        return (
          <button key={val} type="button"
            onClick={() => onChange(toggleCode(selected, val))}
            className={`px-2.5 py-1 text-xs rounded-lg border transition-colors
              ${on
                ? 'border-brand-500 bg-brand-50 text-brand-700 font-semibold'
                : 'border-gray-300 text-gray-600 hover:border-brand-400'}`}>
            {opt.name_ar || opt.name || val}
          </button>
        )
      })}
    </div>
  )
}

/* ── SearchSelect — searchable multi-select for larger lists ─────────────── */
function SearchSelect({ options = [], selected = [], onChange, placeholder = 'الكل' }) {
  const [open, setOpen] = useState(false)
  const [q,    setQ]    = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const filtered = q.trim()
    ? options.filter(o => (o.name || o.code).toLowerCase().includes(q.trim().toLowerCase()))
    : options

  const count = selected.length

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border transition-colors
          ${count > 0
            ? 'border-brand-400 bg-brand-50 text-brand-700'
            : 'border-gray-300 bg-white text-gray-600 hover:border-brand-400'}`}>
        {placeholder}
        {count > 0 && (
          <span className="bg-brand-600 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center font-bold">
            {count}
          </span>
        )}
        <span className="text-gray-400 text-[10px]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full mt-1 right-0 z-20 bg-white border border-gray-200 rounded-xl shadow-lg w-56">
            <div className="p-2 border-b border-gray-100">
              <input autoFocus type="text" value={q} placeholder="بحث…"
                className="w-full border border-gray-300 rounded-lg px-2 py-1 text-xs focus:ring-2 focus:ring-brand-400 focus:outline-none"
                onChange={e => setQ(e.target.value)}
                onClick={e => e.stopPropagation()} />
            </div>
            <div className="max-h-48 overflow-y-auto">
              {!q.trim() && (
                <button type="button" onClick={() => onChange([])}
                  className={`w-full text-right px-3 py-2 text-xs hover:bg-gray-50 border-b border-gray-100
                    ${selected.length === 0 ? 'text-brand-600 font-semibold' : 'text-gray-500'}`}>
                  الكل
                </button>
              )}
              {filtered.length === 0 && (
                <p className="text-xs text-gray-400 text-center py-3">لا نتائج</p>
              )}
              {filtered.map(opt => {
                const val = String(opt.code)
                const on  = selected.includes(val)
                return (
                  <button key={val} type="button"
                    onClick={() => onChange(toggleCode(selected, val))}
                    className="w-full text-right px-3 py-2 text-xs hover:bg-brand-50 flex items-center gap-2 border-b border-gray-50 last:border-0">
                    <span className={`w-3 h-3 rounded border flex-shrink-0 flex items-center justify-center
                      ${on ? 'bg-brand-500 border-brand-500' : 'border-gray-300'}`}>
                      {on && <span className="text-white text-[8px]">✓</span>}
                    </span>
                    <span className="text-gray-700 flex-1 truncate">{opt.name || opt.code}</span>
                  </button>
                )
              })}
            </div>
            {count > 0 && (
              <div className="p-2 border-t border-gray-100">
                <button type="button" onClick={() => onChange([])}
                  className="text-xs text-red-500 hover:text-red-700 underline">
                  مسح ({count})
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/* ── main component ──────────────────────────────────────────────────────── */
export default function ItemOperationalFiltersBar({ filters, onChange, options = {} }) {
  const [expanded, setExpanded] = useState(false)
  const active = countActiveItemFilters(filters)
  const set    = patch => onChange({ ...filters, ...patch })

  const insuranceOpts = options.insurance_types        || []
  const levelOpts     = options.item_level_options     || []
  const nosaleOpts    = options.nosale_classif_options || []
  const storeOpts     = options.store_classif_options  || []
  const transOpts     = options.trans_options          || []

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-3 space-y-3">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-600">⚙️ فلاتر الصنف التفصيلية</span>
        <button type="button" onClick={() => setExpanded(e => !e)}
          className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg border transition-colors
            ${active > 0
              ? 'border-brand-400 bg-brand-50 text-brand-700'
              : 'border-gray-300 text-gray-500 hover:border-brand-400'}`}>
          {active > 0 ? `${active} فلاتر نشطة` : 'تصفية حسب الصنف'}
          {active > 0 && (
            <span className="bg-brand-600 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center font-bold">
              {active}
            </span>
          )}
          <span className="text-gray-400 text-[10px]">{expanded ? '▲' : '▼'}</span>
        </button>
        {active > 0 && (
          <button type="button" onClick={() => onChange(emptyItemFilters())}
            className="text-xs text-red-500 hover:text-red-700 underline">
            مسح الكل
          </button>
        )}
      </div>

      {expanded && (
        <div className="space-y-3 pt-2 border-t border-gray-100">

          {/* Row 1 — تصنيفات التأمين وقيود المبيعات */}
          {insuranceOpts.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-gray-500 w-24 flex-shrink-0 font-medium">التأمين:</span>
              <PillMultiSelect
                options={insuranceOpts}
                selected={filters.insurance_types || []}
                onChange={v => set({ insurance_types: v })}
              />
              {(filters.insurance_types || []).length > 0 && (
                <button type="button" onClick={() => set({ insurance_types: [] })}
                  className="text-xs text-red-400 hover:text-red-600 underline">
                  مسح
                </button>
              )}
            </div>
          )}

          {nosaleOpts.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-gray-500 w-24 flex-shrink-0 font-medium">قيد المبيعات:</span>
              <PillMultiSelect
                options={nosaleOpts}
                selected={filters.nosale_classifs || []}
                onChange={v => set({ nosale_classifs: v })}
              />
              {(filters.nosale_classifs || []).length > 0 && (
                <button type="button" onClick={() => set({ nosale_classifs: [] })}
                  className="text-xs text-red-400 hover:text-red-600 underline">
                  مسح
                </button>
              )}
            </div>
          )}

          {/* Row 2 — Dropdowns + checkboxes */}
          <div className="flex flex-wrap items-center gap-3">

            {levelOpts.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-gray-500">مستوى الصنف:</span>
                <select value={filters.item_level || ''} onChange={e => set({ item_level: e.target.value })}
                  className={SEL}>
                  <option value="">الكل</option>
                  {levelOpts.map(o => (
                    <option key={o.code} value={o.code}>{o.name_ar || o.name}</option>
                  ))}
                </select>
              </div>
            )}

            {storeOpts.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-gray-500">تصنيف التعاقد:</span>
                <SearchSelect
                  options={storeOpts.map(o => ({ code: o.code, name: o.name }))}
                  selected={filters.store_classifs || []}
                  onChange={v => set({ store_classifs: v })}
                  placeholder="تصنيف التعاقد"
                />
              </div>
            )}

            {transOpts.length > 0 && (
              <>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-500">حركة الفرع:</span>
                  <select value={filters.branch_trans || ''} onChange={e => set({ branch_trans: e.target.value })}
                    className={SEL}>
                    <option value="">الكل</option>
                    {transOpts.map(o => (
                      <option key={o.code} value={o.code}>{o.name_ar || o.name}</option>
                    ))}
                  </select>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-500">حركة المورد:</span>
                  <select value={filters.supplier_trans || ''} onChange={e => set({ supplier_trans: e.target.value })}
                    className={SEL}>
                    <option value="">الكل</option>
                    {transOpts.map(o => (
                      <option key={o.code} value={o.code}>{o.name_ar || o.name}</option>
                    ))}
                  </select>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-500">حركة العميل:</span>
                  <select value={filters.customer_trans || ''} onChange={e => set({ customer_trans: e.target.value })}
                    className={SEL}>
                    <option value="">الكل</option>
                    {transOpts.map(o => (
                      <option key={o.code} value={o.code}>{o.name_ar || o.name}</option>
                    ))}
                  </select>
                </div>
              </>
            )}

            <label className={CHK_LBL}>
              <input type="checkbox" checked={!!filters.is_fast_moving}
                onChange={e => set({ is_fast_moving: e.target.checked })}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-400" />
              سريع الحركة فقط
            </label>

            <label className={CHK_LBL}>
              <input type="checkbox" checked={!!filters.has_points}
                onChange={e => set({ has_points: e.target.checked })}
                className="rounded border-gray-300 text-brand-600 focus:ring-brand-400" />
              له نقاط فقط
            </label>

          </div>
        </div>
      )}
    </div>
  )
}
