/** PriceHistoryModal (#8) — full change timeline for one item (system of record). */
import { useQuery } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../../api/client'

const FIELD_LABEL = {
  pack_price: 'سعر العبوة', unit_price: 'سعر الوحدة', pack_price_tax: 'شامل الضريبة',
  pharmacy_discp: 'خصم الصيدلية', additional_discp: 'خصم إضافي',
  special_discp: 'خصم خاص', pos_discp: 'خصم POS',
}
const STATUS = {
  executed: { t: 'منفذ', c: 'text-emerald-600' }, rejected: { t: 'مرفوض', c: 'text-red-600' },
  pending: { t: 'معلّق', c: 'text-amber-600' }, failed: { t: 'فشل', c: 'text-rose-600' },
  approved: { t: 'معتمد', c: 'text-blue-600' },
}
const fmt = s => s ? new Date(s).toLocaleString('ar-EG', { day: '2-digit', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'

export default function PriceHistoryModal({ softechId, itemName, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ['price-history', softechId],
    queryFn: () => pricingApprovalsApi.priceHistory(softechId).then(r => r.data),
  })
  const events = data?.events || []

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="p-5 border-b flex items-center justify-between sticky top-0 bg-white">
          <div>
            <h2 className="text-lg font-bold text-gray-900">سجل تغييرات السعر</h2>
            <p className="text-sm text-gray-500">{itemName} · <span className="font-mono">{softechId}</span></p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        <div className="p-5">
          {isLoading && <div className="text-center py-8 text-gray-400 text-sm">جاري التحميل…</div>}
          {!isLoading && !events.length && (
            <div className="text-center py-10 text-gray-400 text-sm">لا يوجد سجل تغييرات لهذا الصنف عبر الوحدة</div>
          )}
          <ol className="relative border-r-2 border-gray-100 pr-4 space-y-4">
            {events.map(ev => {
              const st = STATUS[ev.status] || { t: ev.status, c: 'text-gray-600' }
              const shown = Object.keys(ev.executed_values || {}).length ? ev.executed_values : ev.new_values
              return (
                <li key={ev.id} className="relative">
                  <span className="absolute -right-[22px] top-1 w-3 h-3 rounded-full bg-white border-2 border-blue-400" />
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-sm font-semibold ${st.c}`}>{st.t}</span>
                    {ev.source === 'rollback' && <span className="text-xs text-purple-600">↩ تراجع</span>}
                    {ev.source === 'import' && <span className="text-xs text-gray-500">📄 استيراد</span>}
                    <span className="text-xs text-gray-400">{fmt(ev.erp_executed_at || ev.reviewed_at || ev.requested_at)}</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {Object.entries(shown).map(([k, v]) => (
                      <span key={k} className="inline-flex items-center gap-1 bg-gray-50 border border-gray-200 rounded px-2 py-0.5 text-xs">
                        <span className="text-gray-500">{FIELD_LABEL[k] || k}:</span>
                        {ev.old_values?.[k] != null && <span className="text-red-400 line-through">{parseFloat(ev.old_values[k]).toFixed(2)}</span>}
                        <span className="text-gray-300">→</span>
                        <span className="font-semibold text-emerald-600">{parseFloat(v).toFixed(2)}</span>
                      </span>
                    ))}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    طلب: {ev.requested_by}
                    {ev.reviewed_by && ` · راجع: ${ev.reviewed_by}`}
                    {ev.erp_username && ` · Softech: ${ev.erp_username}`}
                  </div>
                  {ev.reason && <div className="text-xs text-gray-400 mt-0.5">السبب: {ev.reason}</div>}
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </div>
  )
}
