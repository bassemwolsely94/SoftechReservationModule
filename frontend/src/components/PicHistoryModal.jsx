/**
 * PicHistoryModal — the selected customer/PIC's full transaction history (past invoices
 * with line items), so the cashier can check earlier purchases and re-add any item.
 * Read-only; reuses /customers/{id}/purchases. Adding an item goes through the normal
 * (safety-checked) add path.
 */
import { useEffect, useState } from 'react'
import { customersApi } from '../api/client'
import { money } from '../hooks/usePosOrder'

export default function PicHistoryModal({ customerId, name, onAdd, onClose }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState({})
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!customerId) return
    customersApi.purchases(customerId)
      .then(({ data }) => setRows(Array.isArray(data) ? data : (data.results || [])))
      .catch(() => setErr('تعذّر تحميل السجل.'))
  }, [customerId])

  const toggle = (id) => setOpen(o => ({ ...o, [id]: !o[id] }))

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-auto" onClick={onClose}>
      <div dir="rtl" className="bg-white rounded-xl shadow-xl w-full max-w-2xl mt-8" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="font-bold text-gray-800 text-sm">📜 سجل معاملات {name || 'العميل'}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-lg">✕</button>
        </div>

        <div className="p-3 space-y-2 max-h-[70vh] overflow-auto">
          {err && <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">{err}</div>}
          {rows === null && !err && <div className="text-center text-gray-400 py-6 text-sm">… جارٍ التحميل</div>}
          {rows && rows.length === 0 && <div className="text-center text-gray-400 py-6 text-sm">لا معاملات سابقة.</div>}

          {(rows || []).map(inv => {
            const ret = inv.is_return || inv.doc_code === '30'
            const isOpen = open[inv.id]
            return (
              <div key={inv.id} className="rounded-lg border border-gray-200">
                <button onClick={() => toggle(inv.id)}
                        className="w-full flex items-center gap-2 px-3 py-2 text-right hover:bg-gray-50 rounded-lg">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${ret ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-700'}`}>
                    {ret ? 'مرتجع' : 'بيع'}
                  </span>
                  <span className="text-xs font-semibold text-gray-700">
                    {inv.invoice_date ? String(inv.invoice_date).slice(0, 10) : '—'}
                  </span>
                  <span className="text-[11px] text-gray-400">{inv.branch_name}</span>
                  <span className="text-xs tabnum font-bold text-brand-600 ms-auto">{money(inv.total_amount)}</span>
                  <span className="text-gray-400 text-xs">{isOpen ? '▾' : '◂'}</span>
                </button>
                {isOpen && (
                  <div className="border-t border-gray-100 divide-y divide-gray-50">
                    {(inv.lines || []).map(l => (
                      <div key={l.id} className="flex items-center gap-2 px-3 py-1.5 text-[11px]">
                        <span className="flex-1 truncate text-gray-700">{l.item_name || l.item_softech_id}</span>
                        <span className="text-gray-400">×{Number(l.quantity)}</span>
                        <span className="tabnum text-gray-500">{money(l.line_total)}</span>
                        {onAdd && l.item_softech_id && !ret && (
                          <button onClick={() => onAdd(l.item_softech_id)}
                                  title="إضافة للسلة" className="text-brand-600 hover:text-brand-800 font-bold">+ إضافة</button>
                        )}
                      </div>
                    ))}
                    {!(inv.lines || []).length && <div className="px-3 py-1.5 text-[11px] text-gray-400">لا تفاصيل أصناف.</div>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
