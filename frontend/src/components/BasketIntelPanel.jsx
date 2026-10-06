/**
 * BasketIntelPanel — contextual, NON-modal sales opportunities for the live cart.
 *
 * Reads the current basket item codes and shows the backend's ranked, safety-
 * filtered suggestions (recommendationsApi.basketIntel). Calm UI (rule 11): a thin
 * inline strip, one-click add, no popups. Backend owns ranking + the safety filter
 * (blocked items never appear here); this only renders and dispatches an add.
 */
import { useEffect, useRef, useState } from 'react'
import { recommendationsApi } from '../api/client'

const REASON = {
  fbt:      { label: 'يُشترى معه', cls: 'bg-sky-50 text-sky-700 border-sky-200' },
  personal: { label: 'مقترح للعميل', cls: 'bg-violet-50 text-violet-700 border-violet-200' },
  refill:   { label: 'تجديد مزمن', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  bundle:   { label: 'إكمال الباقة', cls: 'bg-amber-50 text-amber-800 border-amber-200' },
}

export default function BasketIntelPanel({ itemCodes = [], customerId, branchId, onAdd }) {
  const [rows, setRows] = useState([])
  const codesKey = itemCodes.join(',')
  const seq = useRef(0)

  useEffect(() => {
    if (itemCodes.length === 0) { setRows([]); return }
    const my = ++seq.current
    const id = setTimeout(async () => {
      try {
        const { data } = await recommendationsApi.basketIntel({
          items: itemCodes, customer: customerId, branch: branchId, limit: 6,
        })
        if (my === seq.current) setRows(data.results || [])
      } catch { if (my === seq.current) setRows([]) }
    }, 200)
    return () => clearTimeout(id)
  }, [codesKey, customerId, branchId])   // eslint-disable-line react-hooks/exhaustive-deps

  if (rows.length === 0) return null

  return (
    <div className="mt-2 rounded-xl border border-line bg-surface-2 p-2">
      <div className="text-[11px] font-bold text-muted mb-1.5">💡 فرص بيع مقترحة</div>
      <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
        {rows.map((r) => {
          const reason = REASON[r.reasons?.[0]] || REASON.fbt
          const oos = typeof r.qty_at_branch === 'number' && r.qty_at_branch <= 0
          return (
            <button
              key={r.item_id}
              onClick={() => onAdd && onAdd({ softech_id: r.softech_id, id: r.item_id, name: r.name, pack_price: r.pack_price })}
              title={oos ? 'غير متوفر بالفرع' : 'إضافة للسلة'}
              className="shrink-0 w-40 text-right rounded-lg border border-line bg-surface hover:shadow-sm p-2 transition-all"
            >
              <div className="text-[11px] font-semibold text-content line-clamp-2 leading-tight">{r.name}</div>
              <div className="flex items-center justify-between mt-1">
                <span className="text-[11px] tabnum font-bold text-brand-600">{Number(r.pack_price || 0).toFixed(2)}</span>
                {oos && <span className="text-[9px] text-faint">لا رصيد</span>}
              </div>
              <div className="flex items-center gap-1 mt-1 flex-wrap">
                <span className={`inline-block text-[9px] border rounded px-1 ${reason.cls}`}>{reason.label}</span>
                {r.boost === 'premium' && <span title="مقترح لكبار العملاء" className="text-[9px] border rounded px-1 bg-violet-50 text-violet-700 border-violet-200">⭐ مميّز</span>}
                {r.boost === 'retention' && <span title="لإعادة تنشيط العميل" className="text-[9px] border rounded px-1 bg-amber-50 text-amber-800 border-amber-200">♥ احتفاظ</span>}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
