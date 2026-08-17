/**
 * MobileItemsPage.jsx — item / stock lookup on the floor (route: /m/items).
 *
 * Pharmacist/sales scan or search an item → see price + live stock across all
 * branches. Read-only; reuses ItemSearchWidget + /items/{id}/stock/.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { itemsApi } from '../../api/client'
import ItemSearchWidget from '../../components/ItemSearchWidget'
import { MobileLoading, MobileError } from '../../components/mobileUi'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}
function fmt(v) { const n = parseFloat(v); return Number.isFinite(n) ? n.toFixed(2) : null }

const STOCK_CLASS = {
  in_stock:     'text-green-600',
  low_stock:    'text-amber-600',
  out_of_stock: 'text-red-500',
}

export default function MobileItemsPage() {
  const [item, setItem] = useState(null)

  const { data: stock, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-item-stock', item?.id],
    queryFn: () => itemsApi.stock(item.id).then(r => r.data),
    enabled: !!item?.id,
  })

  const rows = Array.isArray(stock) ? stock : []
  const total = rows.reduce((s, r) => s + (Number(r.quantity_on_hand) || 0), 0)

  return (
    <div className="p-3 space-y-3">
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 text-sm mb-2.5">🔎 بحث عن صنف</h2>
        <ItemSearchWidget selected={item} onSelect={setItem} onClear={() => setItem(null)} autoFocus />
      </div>

      {item && (
        <>
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <div className="font-bold text-sm text-gray-900">{item.name}</div>
            {item.name_scientific && <div className="text-xs text-gray-500 italic mt-0.5">{item.name_scientific}</div>}
            <div className="flex flex-wrap items-center gap-1.5 mt-2">
              <span className="text-[11px] font-mono font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">كود: {item.softech_id}</span>
              {fmt(item.pack_price) && <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">💰 {fmt(item.pack_price)} ج.م</span>}
              <span className="text-[11px] text-gray-600 bg-gray-100 px-2 py-0.5 rounded">إجمالي الشبكة: {toLatin(total)}</span>
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <h2 className="font-semibold text-gray-700 text-sm mb-2.5">📦 المخزون حسب الفرع</h2>
            {isLoading ? (
              <MobileLoading />
            ) : isError ? (
              <MobileError text="تعذّر تحميل المخزون" onRetry={refetch} />
            ) : rows.length === 0 ? (
              <div className="text-sm text-gray-400 text-center py-4">لا توجد بيانات مخزون</div>
            ) : (
              <div className="space-y-1.5">
                {rows.filter(r => (r.quantity_on_hand || 0) !== 0 || true).sort((a,b)=>(b.quantity_on_hand||0)-(a.quantity_on_hand||0)).map((r, i) => (
                  <div key={r.branch || i} className="flex items-center justify-between text-sm border-b border-gray-50 last:border-0 pb-1.5 last:pb-0">
                    <span className="text-gray-600 truncate flex-1">{r.branch_name_ar || r.branch_name || `فرع ${r.branch}`}</span>
                    <span className={`font-bold shrink-0 ${STOCK_CLASS[r.stock_status] || 'text-gray-700'}`}>
                      {toLatin(r.quantity_on_hand)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
