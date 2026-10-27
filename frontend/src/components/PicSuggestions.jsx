/* PIC history + suggestions — the selected individual's (or account's) most recent SALE,
 * revalidated against today's price/stock/safety. Read-only; one-tap add + reorder-all
 * (retention: bring a due/at-risk customer back fast). Shared web + mobile. */
export default function PicSuggestions({ P }) {
  const h = P.picHistory
  const who = P.picCustomer || P.customer
  if (!who || !h || !(h.lines || []).length) return null
  const src = h.source_invoice || {}
  const sellable = (h.lines || []).filter(l => l.softech_id && !l.blocked && l.status !== 'missing')
  const reorderAll = () => sellable.forEach(l => P.addByBarcode(l.softech_id))
  return (
    <div className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50/60 p-2">
      <div className="flex items-center justify-between mb-1 gap-2 flex-wrap">
        <span className="text-xs font-bold text-indigo-800">🧾 مشتريات {who.name} السابقة — اقتراحات</span>
        <div className="flex items-center gap-2">
          {src.date && <span className="text-[11px] text-indigo-600">آخر فاتورة: {src.date}</span>}
          {sellable.length > 1 && (
            <button onClick={reorderAll} title="إضافة كل الأصناف المتاحة من آخر فاتورة"
                    className="text-[11px] bg-indigo-600 text-white rounded px-2 py-0.5 font-semibold hover:bg-indigo-700">
              ↻ إعادة الطلب كامل ({sellable.length})
            </button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(h.lines || []).map((l, i) => {
          const disabled = l.blocked || l.status === 'missing'
          const oos = l.status === 'out_of_stock'
          return (
            <button key={i} disabled={disabled}
              onClick={() => l.softech_id && P.addByBarcode(l.softech_id)}
              title={disabled ? 'محظور/غير متاح' : (oos ? 'غير متوفر بالمخزن — يُضاف كحجز' : 'إضافة للسلة')}
              className={`text-[11px] rounded px-2 py-1 border flex items-center gap-1 ${
                disabled ? 'bg-gray-100 border-gray-200 text-gray-400 cursor-not-allowed'
                : oos ? 'bg-white border-amber-300 text-amber-700 hover:bg-amber-50'
                : 'bg-white border-indigo-200 text-indigo-700 hover:bg-indigo-50'}`}>
              <span className="truncate max-w-[180px]">{l.name || l.softech_id}</span>
              {l.qty ? <span className="text-gray-400">×{l.qty}</span> : null}
              {l.price_changed && <span title="تغيّر السعر" className="text-orange-500">₤!</span>}
              {oos && <span>⛔</span>}
              {l.blocked && <span>🚫</span>}
              {!disabled && <span className="font-bold">+</span>}
            </button>
          )
        })}
      </div>
      <div className="text-[10px] text-gray-400 mt-1">اقتراحات من آخر فاتورة — مُتحقَّق منها (سعر/رصيد/سلامة). التطبيق باختيارك.</div>
    </div>
  )
}
