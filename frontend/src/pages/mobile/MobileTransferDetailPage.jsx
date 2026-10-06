/**
 * MobileTransferDetailPage.jsx — phone transfer detail + workflow actions
 * (route: /m/transfers/:id).
 *
 * Renders branches, items, status timeline (chatter), and the contextual
 * state-machine actions the server permits — driven by the can_* flags on the
 * detail serializer (which already encode the requesting/supplying-side gating),
 * so the UI never offers an action the API would reject.
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { transfersApi } from '../../api/client'
import { transferBadgeClass } from './transferStatus'
import MobileChatter from '../../components/MobileChatter'
import { MobileLoading, MobileError } from '../../components/mobileUi'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

// action key → { label, color, needs: null | {field, label, required} }
const ACTIONS = {
  submit:   { label: 'تقديم للموافقة', color: 'bg-orange-500', needs: null },
  approve:  { label: 'اعتماد',          color: 'bg-green-600',  needs: null },
  reject:   { label: 'رفض',             color: 'bg-red-500',    needs: { field: 'rejection_reason', label: 'سبب الرفض', required: true } },
  revision: { label: 'طلب تعديل',       color: 'bg-yellow-500', needs: { field: 'revision_notes',   label: 'ملاحظات التعديل', required: true } },
  sendToERP:{ label: 'إرسال للـ ERP',   color: 'bg-purple-600', needs: { field: 'erp_reference',    label: 'مرجع ERP (اختياري)', required: false } },
  dispatch: { label: 'تسجيل الإرسال',   color: 'bg-blue-500',   needs: { field: 'delivery_person_name', label: 'اسم المندوب', required: true } },
  complete: { label: 'إغلاق الطلب',      color: 'bg-green-700',  needs: null },
  cancel:   { label: 'إلغاء الطلب',      color: 'bg-gray-500',   needs: null },
}

export default function MobileTransferDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()

  const { data: t, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-transfer', id],
    queryFn: () => transfersApi.get(id).then(r => r.data),
  })

  async function sendMessage(text) {
    await transfersApi.sendMessage(id, { message: text })
    await qc.invalidateQueries({ queryKey: ['m-transfer', id] })
  }

  const [action, setAction] = useState(null)   // key in ACTIONS, awaiting confirm
  const [input, setInput]   = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  async function run() {
    const spec = ACTIONS[action]
    if (spec.needs?.required && !input.trim()) { setError('هذا الحقل مطلوب'); return }
    setSaving(true); setError('')
    try {
      const body = spec.needs ? { [spec.needs.field]: input } : undefined
      if (action === 'submit')        await transfersApi.submit(id)
      else if (action === 'approve')  await transfersApi.approve(id)
      else if (action === 'reject')   await transfersApi.reject(id, body)
      else if (action === 'revision') await transfersApi.revision(id, body)
      else if (action === 'sendToERP')await transfersApi.sendToERP(id, body)
      else if (action === 'dispatch') await transfersApi.dispatch(id, body)
      else if (action === 'complete') await transfersApi.complete(id)
      else if (action === 'cancel')   await transfersApi.cancel(id)
      await qc.invalidateQueries({ queryKey: ['m-transfer', id] })
      qc.invalidateQueries({ queryKey: ['m-transfers'] })
      setAction(null); setInput('')
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر تنفيذ الإجراء')
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) return <MobileLoading />
  if (isError || !t) return <MobileError text="تعذّر تحميل الطلب" onRetry={refetch} />

  const chatterMsgs = (t.messages || [])
    .filter(m => !m.is_deleted)
    .map(m => ({ id: m.id, text: m.message, who: m.created_by_name, when: m.created_at }))

  // Build the available action list from the can_* flags the API returned.
  const available = []
  if (t.can_submit)           available.push('submit')
  if (t.can_approve)          available.push('approve')
  if (t.can_reject)           available.push('reject')
  if (t.can_request_revision) available.push('revision')
  if (t.can_send_to_erp)      available.push('sendToERP')
  if (t.can_dispatch)         available.push('dispatch')
  if (t.can_complete)         available.push('complete')
  if (t.can_cancel)           available.push('cancel')

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/transfers')} className="text-sm text-gray-500">→ الرجوع للقائمة</button>

      {/* Header */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h1 className="font-bold text-base text-gray-900">{t.request_number}</h1>
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${transferBadgeClass(t.status_color)}`}>
            {t.status_label}
          </span>
        </div>
        <div className="text-sm text-gray-700">
          {t.requesting_branch_name} <span className="text-gray-400">←</span> {t.supplying_branch_name || '—'}
        </div>
        {t.rejection_reason && <p className="text-xs text-red-600 mt-2">سبب الرفض: {t.rejection_reason}</p>}
        {t.revision_notes &&   <p className="text-xs text-yellow-700 mt-2">التعديل المطلوب: {t.revision_notes}</p>}
        {t.erp_reference &&    <p className="text-xs text-gray-500 mt-2 font-mono" dir="ltr">ERP: {t.erp_reference}</p>}
      </div>

      {/* Items */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 text-sm mb-2.5">الأصناف ({toLatin((t.items || []).length)})</h2>
        <div className="space-y-1.5">
          {(t.items || []).map(it => (
            <div key={it.id} className="flex items-center justify-between text-sm border-b border-gray-50 last:border-0 pb-1.5 last:pb-0">
              <span className="text-gray-700 break-words flex-1 min-w-0">{it.item_name || it.item?.name || '—'}</span>
              <span className="text-gray-500 shrink-0">
                {toLatin(it.quantity)}{it.approved_quantity != null ? ` → ${toLatin(it.approved_quantity)}` : ''}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Chatter (log + composer) */}
      <MobileChatter messages={chatterMsgs} onSend={sendMessage} title="💬 المحادثة" />

      {/* Actions */}
      {available.length > 0 ? (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">الإجراءات</h2>
          <div className="grid grid-cols-2 gap-2">
            {available.map(k => (
              <button
                key={k}
                onClick={() => { setAction(k); setInput(''); setError('') }}
                className={`py-3 rounded-xl text-white text-sm font-semibold active:opacity-90 ${ACTIONS[k].color}`}
              >
                {ACTIONS[k].label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center text-xs text-gray-400 py-2">لا توجد إجراءات متاحة لك في هذه الحالة</div>
      )}

      {/* Confirm sheet */}
      {action && (
        <div className="fixed inset-0 bg-black/40 flex items-end justify-center z-50" onClick={() => !saving && setAction(null)}>
          <div className="bg-white rounded-t-2xl shadow-2xl w-full p-5 pb-safe-bottom" dir="rtl" onClick={e => e.stopPropagation()}>
            <h3 className="font-bold text-gray-800 text-base mb-1 text-center">{ACTIONS[action].label}؟</h3>
            {ACTIONS[action].needs && (
              <textarea
                rows={2}
                className="input-field w-full resize-none mt-3"
                placeholder={ACTIONS[action].needs.label}
                value={input}
                onChange={e => setInput(e.target.value)}
                autoFocus
              />
            )}
            {error && <div className="text-sm text-red-600 mt-2 text-center">{error}</div>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => setAction(null)} disabled={saving} className="btn-secondary flex-1 text-sm">إلغاء</button>
              <button onClick={run} disabled={saving} className="btn-primary flex-1 text-sm disabled:opacity-50">
                {saving ? 'جارٍ التنفيذ...' : 'تأكيد'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
