/**
 * MobileDemandDetailPage.jsx — demand record detail (route: /m/demand/:id).
 *
 * Read-focused: customer (call), items, status, and a notes thread (demand logs)
 * with a composer. Heavy lifecycle transitions stay on the desktop demand screens.
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { demandApi } from '../../api/client'
import { demandBadgeClass } from './demandStatus'
import MobileChatter from '../../components/MobileChatter'
import { MobileLoading, MobileError } from '../../components/mobileUi'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}
function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <span className="text-xs text-gray-400 shrink-0">{label}</span>
      <span className="text-sm text-gray-800 text-left">{children}</span>
    </div>
  )
}

export default function MobileDemandDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()

  const { data: d, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-demand-detail', id],
    queryFn: () => demandApi.get(id).then(r => r.data),
  })

  async function sendNote(text) {
    await demandApi.addLog(id, { log_type: 'note', message: text })
    await qc.invalidateQueries({ queryKey: ['m-demand-detail', id] })
  }

  if (isLoading) return <MobileLoading />
  if (isError || !d) return <MobileError text="تعذّر تحميل الطلب" onRetry={refetch} />

  const notes = (d.logs || [])
    .filter(l => l.message)
    .map(l => ({ id: l.id, text: l.message, who: l.created_by_name, when: l.created_at }))

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/demand')} className="text-sm text-gray-500">→ الرجوع للقائمة</button>

      {/* Header */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <h1 className="font-bold text-base text-gray-900">{d.demand_number}</h1>
          <div className="flex items-center gap-1.5">
            {d.sla_breached && <span className="text-[11px] text-red-600 font-medium">SLA</span>}
            <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${demandBadgeClass(d.status)}`}>
              {d.status_label}
            </span>
          </div>
        </div>
        {d.phone && (
          <a href={`tel:${d.phone}`} className="inline-block text-sm bg-brand-50 text-brand-700 border border-brand-200 rounded-xl px-4 py-1.5 font-medium" dir="ltr">📞 {d.phone}</a>
        )}
      </div>

      {/* Info */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 divide-y divide-gray-50">
        <Row label="العميل">{d.customer_name || '—'}</Row>
        <Row label="الفرع">{d.branch_name || '—'}</Row>
        <Row label="الأولوية">{d.priority_label}</Row>
        <Row label="المصدر">{d.source_label}</Row>
        {d.potential_value != null && <Row label="القيمة المتوقعة">{toLatin(d.potential_value)} ج.م</Row>}
        {d.notes && <Row label="ملاحظات">{d.notes}</Row>}
      </div>

      {/* Items */}
      {Array.isArray(d.items) && d.items.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">الأصناف ({toLatin(d.items.length)})</h2>
          <div className="space-y-1.5">
            {d.items.map(it => (
              <div key={it.id} className="flex items-center justify-between text-sm border-b border-gray-50 last:border-0 pb-1.5 last:pb-0">
                <span className="text-gray-700 break-words flex-1 min-w-0">{it.display_name || it.item_name || it.item_name_free || '—'}</span>
                <span className="text-gray-500 shrink-0">× {toLatin(it.quantity)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Notes / logs */}
      <MobileChatter messages={notes} onSend={sendNote} title="💬 الملاحظات" />
    </div>
  )
}
