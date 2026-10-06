/**
 * MultiItemPicker.jsx
 *
 * Multi-item selection component with quantity per row.
 * Wraps ItemSearchWidget for each new addition.
 *
 * Used by: ShortagePage (shortage items), InvoicesPage (line items),
 *          ProcurementPage (purchase items).
 *
 * Props:
 *   items      — array of { item: ItemObject, qty: number }
 *   onChange   — (items) => void  — called whenever the list changes
 *   branchId   — number | null  — if set, shows stock at that branch
 *   disabled   — bool
 *   className  — extra wrapper classes
 *   minQty     — number (default 1)
 *   maxQty     — number | null (default null = unlimited)
 */
import { useCallback } from 'react'
import ItemSearchWidget from './ItemSearchWidget'

function fmtPrice(v) {
  const n = parseFloat(v)
  return n ? n.toFixed(2) : null
}

// ── Single row ────────────────────────────────────────────────────────────────

function ItemRow({ entry, index, onChange, onRemove, disabled, branchId }) {
  const { item, qty } = entry
  const price  = fmtPrice(item.pack_price)
  const stock  = item.total_stock !== undefined ? Number(item.total_stock) : null
  const stockColor = stock === null ? 'gray' : stock > 10 ? 'green' : stock > 0 ? 'amber' : 'red'

  return (
    <div className="flex items-start gap-3 bg-white border border-gray-200 rounded-xl px-3 py-2.5 group">
      {/* Row number */}
      <div className="shrink-0 w-5 h-5 bg-brand-100 text-brand-700 rounded-full text-[10px] font-bold flex items-center justify-center mt-0.5">
        {index + 1}
      </div>

      {/* Item info */}
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-sm text-gray-900 leading-snug">{item.name}</div>
        {item.name_scientific && (
          <div className="text-[10px] text-gray-400 italic">{item.name_scientific}</div>
        )}
        <div className="flex flex-wrap items-center gap-1.5 mt-1">
          <span className="text-[11px] font-mono font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">
            {item.softech_id}
          </span>
          {price && (
            <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
              💰 {price} ج.م
            </span>
          )}
          {stock !== null && (
            <span className={`text-[11px] font-bold px-2 py-0.5 rounded border ${
              stockColor === 'green' ? 'text-green-700 bg-green-50 border-green-200' :
              stockColor === 'amber' ? 'text-amber-700 bg-amber-50 border-amber-200' :
                                      'text-red-700 bg-red-50 border-red-200'
            }`}>
              📦 {stock > 0 ? `${stock} وحدة` : 'نفد'}
            </span>
          )}
        </div>
      </div>

      {/* Quantity */}
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          type="button"
          disabled={disabled || qty <= 1}
          onClick={() => onChange(index, { ...entry, qty: qty - 1 })}
          className="w-6 h-6 rounded-lg border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 text-sm font-bold"
        >−</button>
        <input
          type="number"
          min="1"
          value={qty}
          onChange={e => {
            const v = Math.max(1, parseInt(e.target.value) || 1)
            onChange(index, { ...entry, qty: v })
          }}
          disabled={disabled}
          className="w-14 text-center border border-gray-300 rounded-lg py-1 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:bg-gray-50"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange(index, { ...entry, qty: qty + 1 })}
          className="w-6 h-6 rounded-lg border border-gray-300 text-gray-500 hover:bg-gray-100 disabled:opacity-40 text-sm font-bold"
        >+</button>
      </div>

      {/* Remove */}
      {!disabled && (
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="shrink-0 w-6 h-6 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors mt-0.5"
          title="إزالة"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5 mx-auto">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function MultiItemPicker({
  items     = [],
  onChange,
  branchId  = null,
  disabled  = false,
  className = '',
}) {
  const handleAdd = useCallback((item) => {
    // Prevent duplicate: just increment qty if already in list
    const idx = items.findIndex(e => e.item.id === item.id || e.item.softech_id === item.softech_id)
    if (idx !== -1) {
      const updated = items.map((e, i) => i === idx ? { ...e, qty: e.qty + 1 } : e)
      onChange(updated)
    } else {
      onChange([...items, { item, qty: 1 }])
    }
  }, [items, onChange])

  const handleChange = useCallback((index, updated) => {
    onChange(items.map((e, i) => i === index ? updated : e))
  }, [items, onChange])

  const handleRemove = useCallback((index) => {
    onChange(items.filter((_, i) => i !== index))
  }, [items, onChange])

  return (
    <div className={`space-y-3 ${className}`}>
      {/* Items list */}
      {items.length > 0 && (
        <div className="space-y-2">
          {items.map((entry, i) => (
            <ItemRow
              key={`${entry.item.softech_id || entry.item.id}-${i}`}
              entry={entry}
              index={i}
              onChange={handleChange}
              onRemove={handleRemove}
              disabled={disabled}
              branchId={branchId}
            />
          ))}
          <div className="flex items-center justify-between text-xs text-gray-500 px-1">
            <span>{items.length} صنف محدد</span>
            <span className="font-semibold">
              إجمالي الكميات: {items.reduce((s, e) => s + e.qty, 0)}
            </span>
          </div>
        </div>
      )}

      {/* Add item widget */}
      {!disabled && (
        <div className="bg-gray-50 border border-dashed border-gray-300 rounded-xl p-3">
          <div className="text-xs text-gray-500 mb-2 font-medium">
            {items.length === 0 ? '+ أضف أصناف' : '+ أضف صنفاً آخر'}
          </div>
          <ItemSearchWidget
            selected={null}
            onSelect={handleAdd}
            onClear={() => {}}
            placeholder="ابحث باسم الصنف أو الكود أو الباركود..."
            showStockBadge={true}
          />
        </div>
      )}

      {/* Empty state */}
      {items.length === 0 && disabled && (
        <div className="border-2 border-dashed border-gray-200 rounded-xl py-6 text-center text-sm text-gray-400">
          لا توجد أصناف
        </div>
      )}
    </div>
  )
}
