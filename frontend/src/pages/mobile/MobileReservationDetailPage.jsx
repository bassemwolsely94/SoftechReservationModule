/**
 * MobileReservationDetailPage.jsx — phone reservation detail + status progression
 * (route: /m/reservations/:id).
 *
 * Shows the core reservation info, branch stock availability, and a status
 * timeline. Status actions mirror the server-side transition graph
 * (ReservationViewSet._VALID_TRANSITIONS) so only valid next states are offered;
 * privileged roles (admin/call_center) also get a cancel escape hatch.
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { reservationsApi } from '../../api/client'
import useAuthStore from '../../store/authStore'
import { StatusBadge, PriorityBadge } from '../../components/StatusBadge'
import MobileChatter from '../../components/MobileChatter'
import { MobileLoading, MobileError } from '../../components/mobileUi'
import { format } from 'date-fns'

// Mirror of the backend transition graph. Keep in sync with views.py.
const TRANSITIONS = {
  pending:   ['available', 'cancelled', 'expired'],
  available: ['contacted', 'confirmed', 'cancelled', 'expired'],
  contacted: ['confirmed', 'available', 'cancelled', 'expired'],
  confirmed: ['fulfilled', 'cancelled', 'expired'],
  expired:   ['pending'],
  fulfilled: [],
  cancelled: [],
}
const PRIVILEGED = new Set(['admin', 'call_center', 'manager'])

const ACTION_STYLE = {
  available: 'bg-orange-500',
  contacted: 'bg-blue-500',
  confirmed: 'bg-indigo-500',
  fulfilled: 'bg-green-600',
  pending:   'bg-gray-500',
  expired:   'bg-gray-400',
  cancelled: 'bg-red-500',
}
const STATUS_LABELS = {
  pending: 'قيد الانتظار', available: 'المخزون متاح', contacted: 'تم التواصل',
  confirmed: 'مؤكد', fulfilled: 'تم التسليم', cancelled: 'إلغاء', expired: 'منتهي',
}

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

export default function MobileReservationDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const { user } = useAuthStore()

  const { data: r, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-reservation', id],
    queryFn: () => reservationsApi.get(id).then(res => res.data),
  })

  async function sendNote(text) {
    await reservationsApi.logActivity(id, { message: text })
    await qc.invalidateQueries({ queryKey: ['m-reservation', id] })
  }

  const [pendingStatus, setPendingStatus] = useState(null) // status awaiting confirm
  const [note, setNote]       = useState('')
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  async function confirmChange() {
    setSaving(true); setError('')
    try {
      await reservationsApi.changeStatus(id, pendingStatus, note)
      await qc.invalidateQueries({ queryKey: ['m-reservation', id] })
      qc.invalidateQueries({ queryKey: ['m-reservations'] })
      setPendingStatus(null); setNote('')
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر تغيير الحالة')
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) return <MobileLoading />
  if (isError || !r) return <MobileError text="تعذّر تحميل الحجز" onRetry={refetch} />

  const chatterMsgs = (r.activities || [])
    .filter(a => !a.is_deleted && a.message)
    .map(a => ({ id: a.id, text: a.message, who: a.created_by_name, when: a.created_at }))

  let allowed = [...(TRANSITIONS[r.status] || [])]
  if (PRIVILEGED.has(user?.role) && !['fulfilled', 'cancelled'].includes(r.status) && !allowed.includes('cancelled')) {
    allowed.push('cancelled')
  }

  return (
    <div className="p-3 space-y-3">

      {/* Back */}
      <button onClick={() => navigate('/m/reservations')} className="text-sm text-gray-500 flex items-center gap-1">
        → الرجوع للقائمة
      </button>

      {/* Header card */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <h1 className="font-bold text-base text-gray-900 leading-snug">{r.item_name}</h1>
          <span className="text-xs text-gray-400 shrink-0">#{r.id}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={r.status} />
          {r.priority && r.priority !== 'normal' && <PriorityBadge priority={r.priority} />}
          {r.is_manual_item && (
            <span className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">صنف غير مكوَّد</span>
          )}
        </div>
      </div>

      {/* Info card */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 divide-y divide-gray-50">
        <Row label="العميل">{r.customer_name || '—'}</Row>
        {r.contact_phone && (
          <Row label="الهاتف">
            <a href={`tel:${r.contact_phone}`} className="text-brand-600 font-medium" dir="ltr">📞 {r.contact_phone}</a>
          </Row>
        )}
        <Row label="الكمية">{toLatin(r.quantity_requested)}</Row>
        <Row label="الفرع">{r.branch_name || '—'}</Row>
        <Row label="القناة">{r.channel_display || r.channel_label || '—'}</Row>
        {r.notes && <Row label="ملاحظات">{r.notes}</Row>}
        {r.created_by_name && <Row label="أنشأه">{r.created_by_name}</Row>}
      </div>

      {/* Stock availability */}
      {Array.isArray(r.stock_by_branch) && r.stock_by_branch.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2">📦 توفر المخزون</h2>
          <div className="space-y-1.5">
            {r.stock_by_branch.slice(0, 6).map(s => (
              <div key={s.branch_id} className="flex items-center justify-between text-sm">
                <span className="text-gray-600">{s.branch_name}</span>
                <span className={`font-bold ${
                  s.status === 'in_stock' ? 'text-green-600' :
                  s.status === 'low_stock' ? 'text-amber-600' : 'text-red-500'
                }`}>{toLatin(s.quantity)} · {s.status_label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status timeline */}
      {Array.isArray(r.status_logs) && r.status_logs.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">📜 السجل</h2>
          <div className="space-y-2.5">
            {r.status_logs.slice().reverse().map(log => (
              <div key={log.id} className="flex gap-2.5 text-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-brand-400 mt-1.5 shrink-0" />
                <div className="min-w-0">
                  <div className="text-gray-700">
                    {log.old_status_label ? `${log.old_status_label} ← ` : ''}
                    <span className="font-semibold">{log.new_status_label}</span>
                  </div>
                  {log.note && <div className="text-gray-500 mt-0.5">{log.note}</div>}
                  <div className="text-gray-400 mt-0.5">
                    {log.changed_by_name || '—'} · {log.changed_at ? toLatin(format(new Date(log.changed_at), 'yyyy/MM/dd HH:mm')) : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chatter */}
      <MobileChatter messages={chatterMsgs} onSend={sendNote} title="💬 الملاحظات" />

      {/* Status actions */}
      {allowed.length > 0 ? (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">تغيير الحالة</h2>
          <div className="grid grid-cols-2 gap-2">
            {allowed.map(s => (
              <button
                key={s}
                onClick={() => { setPendingStatus(s); setNote(''); setError('') }}
                className={`py-3 rounded-xl text-white text-sm font-semibold active:opacity-90 ${ACTION_STYLE[s] || 'bg-gray-500'}`}
              >
                {STATUS_LABELS[s] || s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center text-xs text-gray-400 py-2">هذا الحجز في حالة نهائية</div>
      )}

      {/* Confirm sheet */}
      {pendingStatus && (
        <div className="fixed inset-0 bg-black/40 flex items-end justify-center z-50" onClick={() => !saving && setPendingStatus(null)}>
          <div className="bg-white rounded-t-2xl shadow-2xl w-full p-5 pb-safe-bottom" dir="rtl" onClick={e => e.stopPropagation()}>
            <h3 className="font-bold text-gray-800 text-base mb-1 text-center">
              تغيير الحالة إلى «{STATUS_LABELS[pendingStatus] || pendingStatus}»؟
            </h3>
            <textarea
              rows={2}
              className="input-field w-full resize-none mt-3"
              placeholder="ملاحظة (اختياري)..."
              value={note}
              onChange={e => setNote(e.target.value)}
            />
            {error && <div className="text-sm text-red-600 mt-2 text-center">{error}</div>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => setPendingStatus(null)} disabled={saving} className="btn-secondary flex-1 text-sm">إلغاء</button>
              <button onClick={confirmChange} disabled={saving} className="btn-primary flex-1 text-sm disabled:opacity-50">
                {saving ? 'جارٍ الحفظ...' : 'تأكيد'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
