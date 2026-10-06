import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { transfersApi, itemsApi } from '../api/client'
import { tint } from '../theme/theme'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
import PrintReceiptModal from '../components/PrintReceiptModal'
import CanDo from '../components/CanDo'
import WhatsAppShareButton from '../components/WhatsAppShareButton'
import VoiceNoteRecorder from '../components/VoiceNoteRecorder'
import ItemSearchWidget from '../components/ItemSearchWidget'

// ── Status config ─────────────────────────────────────────────────────────────

const STATUS = {
  draft:          { label: 'مسودة',              dot: '#9ca3af', bg: '#f9fafb', text: '#6b7280',  border: '#e5e7eb'  },
  pending:        { label: 'بانتظار الموافقة',   dot: '#f59e0b', bg: '#fffbeb', text: '#92400e',  border: '#fde68a'  },
  approved:       { label: 'معتمد',              dot: '#3b82f6', bg: '#eff6ff', text: '#1e40af',  border: '#bfdbfe'  },
  rejected:       { label: 'مرفوض',              dot: '#ef4444', bg: '#fef2f2', text: '#991b1b',  border: '#fecaca'  },
  needs_revision: { label: 'يحتاج تعديل',        dot: '#f59e0b', bg: '#fefce8', text: '#713f12',  border: '#fef08a'  },
  sent_to_erp:    { label: 'أُرسل للـ ERP',      dot: '#8b5cf6', bg: '#f5f3ff', text: '#5b21b6',  border: '#ddd6fe'  },
  completed:      { label: 'مكتمل',              dot: '#10b981', bg: '#f0fdf4', text: '#166534',  border: '#bbf7d0'  },
  cancelled:      { label: 'ملغي',               dot: '#d1d5db', bg: '#f9fafb', text: '#9ca3af',  border: '#e5e7eb'  },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(d) {
  if (!d) return '—'
  try { return toLatinDigits(format(new Date(d), 'd MMM yyyy — HH:mm', { locale: ar })) } catch { return d }
}

function timeAgo(d) {
  if (!d) return ''
  try { return toLatinDigits(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) } catch { return '' }
}

function initials(name) {
  return (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('')
}

// ── Section heading ───────────────────────────────────────────────────────────

function SectionHeading({ icon, label, count }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <span className="text-base">{icon}</span>
      <span className="text-sm font-bold text-gray-700">{label}</span>
      {count !== undefined && (
        <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-full font-semibold">
          {count}
        </span>
      )}
    </div>
  )
}

// ── Action buttons ────────────────────────────────────────────────────────────

function ActionButtons({ tr, onAction, loading }) {
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [showRevisionForm, setShowRevisionForm] = useState(false)
  const [showErpForm, setShowErpForm] = useState(false)
  const [showDispatchForm, setShowDispatchForm] = useState(false)
  const [showApproveForm, setShowApproveForm] = useState(false)
  const [showCompleteForm, setShowCompleteForm] = useState(false)
  const [rejectionReason, setRejectionReason] = useState('')
  const [revisionNotes, setRevisionNotes] = useState('')
  const [erpRef, setErpRef] = useState('')
  const [deliveryPerson, setDeliveryPerson] = useState('')
  const [approveQtys, setApproveQtys] = useState({})
  const [completeQtys, setCompleteQtys] = useState({})

  if (!tr) return null

  function openApproveForm() {
    const init = {}
    ;(tr.items || []).forEach(l => { init[l.id] = String(l.quantity) })
    setApproveQtys(init)
    setShowApproveForm(true)
  }

  function submitApprove() {
    const items = (tr.items || []).map(l => ({
      item_id: l.item,
      approved_quantity: Number(approveQtys[l.id] ?? l.quantity),
    }))
    onAction('approve', { items })
    setShowApproveForm(false)
  }

  function openCompleteForm() {
    const init = {}
    ;(tr.items || []).forEach(l => {
      init[l.id] = String(l.approved_quantity ?? l.quantity)
    })
    setCompleteQtys(init)
    setShowCompleteForm(true)
  }

  function submitComplete() {
    const items = (tr.items || []).map(l => ({
      item_id: l.item,
      received_quantity: Number(completeQtys[l.id] ?? l.approved_quantity ?? l.quantity),
    }))
    onAction('complete', { items })
    setShowCompleteForm(false)
  }

  return (
    <>
    {/* ── Partial-approval modal ─────────────────────────────────────────── */}
    {showApproveForm && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        onClick={e => { if (e.target === e.currentTarget) setShowApproveForm(false) }}>
        <div className="bg-white rounded-2xl shadow-2xl p-5 w-[420px] max-w-full mx-4" dir="rtl">
          <div className="font-bold text-blue-800 mb-1 text-sm">✅ اعتماد الطلب</div>
          <div className="text-xs text-gray-500 mb-4">أدخل الكمية المعتمدة لكل صنف (يمكن اعتماد كمية جزئية)</div>
          <div className="space-y-2 mb-5 max-h-64 overflow-y-auto">
            {(tr.items || []).map(line => (
              <div key={line.id} className="flex items-center gap-3 bg-blue-50 rounded-xl px-3 py-2.5">
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-gray-800 break-words">{line.item_name}</div>
                  <div className="text-xs text-gray-400 mt-0.5">مطلوب: <span className="font-bold text-gray-600">{line.quantity}</span></div>
                </div>
                <div className="flex flex-col items-end gap-0.5">
                  <span className="text-[10px] text-gray-400">معتمد</span>
                  <input type="number" min="0" step="0.001"
                    value={approveQtys[line.id] ?? line.quantity}
                    onChange={e => setApproveQtys(prev => ({ ...prev, [line.id]: e.target.value }))}
                    className="w-24 text-sm border border-blue-300 rounded-lg px-2 py-1 text-center focus:outline-none focus:border-blue-500 font-bold"
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={submitApprove} disabled={loading}
              className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-bold py-2.5 rounded-xl disabled:opacity-50">
              تأكيد الاعتماد
            </button>
            <button onClick={() => setShowApproveForm(false)}
              className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 rounded-xl hover:bg-gray-100">
              إلغاء
            </button>
          </div>
        </div>
      </div>
    )}

    {/* ── Received-quantity modal ────────────────────────────────────────── */}
    {showCompleteForm && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        onClick={e => { if (e.target === e.currentTarget) setShowCompleteForm(false) }}>
        <div className="bg-white rounded-2xl shadow-2xl p-5 w-[420px] max-w-full mx-4" dir="rtl">
          <div className="font-bold text-green-800 mb-1 text-sm">🏁 تأكيد الاستلام</div>
          <div className="text-xs text-gray-500 mb-4">أدخل الكمية المستلمة فعلياً لكل صنف</div>
          <div className="space-y-2 mb-5 max-h-64 overflow-y-auto">
            {(tr.items || []).map(line => {
              const expected = line.approved_quantity ?? line.quantity
              return (
                <div key={line.id} className="flex items-center gap-3 bg-green-50 rounded-xl px-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold text-gray-800 break-words">{line.item_name}</div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      معتمد: <span className="font-bold text-gray-600">{expected}</span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-0.5">
                    <span className="text-[10px] text-gray-400">مستلم</span>
                    <input type="number" min="0" step="0.001"
                      value={completeQtys[line.id] ?? expected}
                      onChange={e => setCompleteQtys(prev => ({ ...prev, [line.id]: e.target.value }))}
                      className="w-24 text-sm border border-green-300 rounded-lg px-2 py-1 text-center focus:outline-none focus:border-green-500 font-bold"
                    />
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex gap-2">
            <button onClick={submitComplete} disabled={loading}
              className="flex-1 bg-green-600 hover:bg-green-700 text-white text-sm font-bold py-2.5 rounded-xl disabled:opacity-50">
              تأكيد الاستلام وإغلاق الطلب
            </button>
            <button onClick={() => setShowCompleteForm(false)}
              className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 rounded-xl hover:bg-gray-100">
              إلغاء
            </button>
          </div>
        </div>
      </div>
    )}

    <div className="flex items-center gap-2 flex-wrap">

      {/* Submit */}
      <CanDo module="transfers" action="edit">
        {tr.can_submit && (
          <button
            onClick={() => onAction('submit')}
            disabled={loading}
            className="btn-primary text-sm disabled:opacity-50"
          >
            تقديم الطلب
          </button>
        )}
      </CanDo>

      {/* Approve — opens partial-quantity form */}
      <CanDo module="transfers" action="approve">
        {tr.can_approve && (
          <button
            onClick={openApproveForm}
            disabled={loading}
            className="text-sm px-4 py-2 rounded-lg font-semibold bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50"
          >
            اعتماد
          </button>
        )}
      </CanDo>

      {/* Reject */}
      <CanDo module="transfers" action="approve">
        {tr.can_reject && !showRejectForm && (
          <button
            onClick={() => setShowRejectForm(true)}
            className="btn-danger text-sm"
          >
            رفض
          </button>
        )}
      </CanDo>

      {/* Reject inline form */}
      {showRejectForm && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2">
          <input
            className="border border-red-300 rounded-lg px-2 py-1 text-xs w-48 focus:outline-none focus:border-red-400"
            placeholder="سبب الرفض (مطلوب)..."
            value={rejectionReason}
            onChange={e => setRejectionReason(e.target.value)}
            autoFocus
          />
          <button
            onClick={() => { if (rejectionReason.trim()) { onAction('reject', { rejection_reason: rejectionReason }); setShowRejectForm(false) } }}
            disabled={!rejectionReason.trim()}
            className="text-xs bg-red-600 text-white px-2 py-1 rounded-lg disabled:opacity-50"
          >
            تأكيد الرفض
          </button>
          <button onClick={() => setShowRejectForm(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* Revision */}
      {tr.can_request_revision && !showRevisionForm && (
        <button onClick={() => setShowRevisionForm(true)}
          className="btn-secondary text-sm">
          ✏️ طلب تعديل
        </button>
      )}

      {showRevisionForm && (
        <div className="flex items-center gap-2 bg-yellow-50 border border-yellow-200 rounded-xl px-3 py-2">
          <input
            className="border border-yellow-300 rounded-lg px-2 py-1 text-xs w-48 focus:outline-none"
            placeholder="ملاحظات التعديل المطلوب..."
            value={revisionNotes}
            onChange={e => setRevisionNotes(e.target.value)}
            autoFocus
          />
          <button
            onClick={() => { if (revisionNotes.trim()) { onAction('revision', { revision_notes: revisionNotes }); setShowRevisionForm(false) } }}
            disabled={!revisionNotes.trim()}
            className="text-xs bg-yellow-600 text-white px-2 py-1 rounded-lg disabled:opacity-50"
          >
            إرسال
          </button>
          <button onClick={() => setShowRevisionForm(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* Send to ERP */}
      {tr.can_send_to_erp && !showErpForm && (
        <button onClick={() => setShowErpForm(true)}
          className="text-sm px-4 py-2 rounded-lg font-semibold bg-purple-600 hover:bg-purple-700 text-white transition-colors">
          🚀 إرسال للـ ERP
        </button>
      )}

      {showErpForm && (
        <div className="flex items-center gap-2 bg-purple-50 border border-purple-200 rounded-xl px-3 py-2">
          <input
            className="border border-purple-300 rounded-lg px-2 py-1 text-xs w-40 focus:outline-none"
            placeholder="مرجع ERP (اختياري)..."
            value={erpRef}
            onChange={e => setErpRef(e.target.value)}
          />
          <button
            onClick={() => { onAction('send-to-erp', { erp_reference: erpRef }); setShowErpForm(false) }}
            className="text-xs bg-purple-600 text-white px-2 py-1 rounded-lg"
          >
            تأكيد الإرسال
          </button>
          <button onClick={() => setShowErpForm(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* Dispatch — record delivery person name */}
      {tr.can_dispatch && !showDispatchForm && (
        <button onClick={() => setShowDispatchForm(true)}
          className="text-sm px-4 py-2 rounded-lg font-semibold bg-indigo-600 hover:bg-indigo-700 text-white transition-colors disabled:opacity-50"
          disabled={loading}>
          🚚 تسجيل الإرسال
        </button>
      )}

      {showDispatchForm && (
        <div className="flex items-center gap-2 bg-indigo-50 border border-indigo-200 rounded-xl px-3 py-2">
          <input
            className="border border-indigo-300 rounded-lg px-2 py-1 text-xs w-48 focus:outline-none focus:border-indigo-400"
            placeholder="اسم مندوب التوصيل *"
            value={deliveryPerson}
            onChange={e => setDeliveryPerson(e.target.value)}
            autoFocus
          />
          <button
            onClick={() => {
              if (deliveryPerson.trim()) {
                onAction('dispatch', { delivery_person_name: deliveryPerson.trim() })
                setShowDispatchForm(false)
              }
            }}
            disabled={!deliveryPerson.trim()}
            className="text-xs bg-indigo-600 text-white px-2 py-1 rounded-lg disabled:opacity-50"
          >
            تأكيد الإرسال
          </button>
          <button onClick={() => setShowDispatchForm(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* Complete — opens received-quantity form */}
      {tr.can_complete && (
        <button onClick={openCompleteForm}
          className="text-sm px-4 py-2 rounded-lg font-semibold bg-green-600 hover:bg-green-700 text-white transition-colors">
          🏁 تأكيد الاستلام
        </button>
      )}

      {/* Cancel */}
      {tr.can_cancel && (
        <button onClick={() => { if (window.confirm('هل تريد إلغاء هذا الطلب؟')) onAction('cancel') }}
          className="btn-ghost text-sm text-gray-400 hover:text-red-500">
          إلغاء الطلب
        </button>
      )}
    </div>
    </>
  )
}

// ── ERP Match Panel ───────────────────────────────────────────────────────────

const ERP_MATCH_CFG = {
  pending:   { icon: '🔍', label: 'قيد التحقق',      bg: '#f5f3ff', text: '#5b21b6', border: '#ddd6fe' },
  matched:   { icon: '✅', label: 'تم التأكيد',       bg: '#f0fdf4', text: '#166534', border: '#bbf7d0' },
  partial:   { icon: '⚠️', label: 'تأكيد جزئي',      bg: '#fffbeb', text: '#92400e', border: '#fde68a' },
  not_found: { icon: '❌', label: 'غير موجود في ERP', bg: '#fef2f2', text: '#991b1b', border: '#fecaca' },
  timeout:   { icon: '⏱️', label: 'انتهت المهلة',    bg: '#f9fafb', text: '#6b7280', border: '#e5e7eb' },
}

const MATCH_LEVEL_CFG = {
  full:      { icon: '✅', text: '#166534', label: 'مطابق'       },
  partial:   { icon: '⚠️', text: '#92400e', label: 'جزئي'        },
  not_found: { icon: '❌', text: '#991b1b', label: 'غير موجود'   },
}

// SOFTECH doccode → Arabic document type name
const SOFTECH_DOCTYPE = {
  '11':  'موظفين',
  '15':  'تأمين صحي',
  '30':  'حجز',
  '99':  'VIP',
  '110': 'مبيعات نقدية',
  '111': 'مبيعات آجلة',
  '115': 'مبيعات لعميل',
  '116': 'مرتجع مبيعات آجلة',
  '120': 'مشتريات',
  '121': 'مرتجع مشتريات',
  '125': 'صرف تبادل بين الفروع',
  '126': 'استلام تبادل بين الفروع',
  '130': 'تحويل مخزن داخلي',
  '200': 'صرف مخزن',
  '501': 'جرد إضافة',
  '502': 'جرد خصم',
  '600': 'تسوية مخزون',
}

function ERPMatchPanel({ tr, onRefresh }) {
  const [checking, setChecking] = useState(false)
  const [cooldown, setCooldown]  = useState(0)   // seconds remaining before button re-enables
  const cooldownRef              = useRef(null)
  const status = tr.erp_match_status

  // Clean up cooldown timer on unmount
  useEffect(() => () => { if (cooldownRef.current) clearInterval(cooldownRef.current) }, [])

  // Auto-refresh every 2 min while pending
  useEffect(() => {
    if (status !== 'pending') return
    const t = setInterval(onRefresh, 120_000)
    return () => clearInterval(t)
  }, [status, onRefresh])

  if (!['sent_to_erp', 'completed'].includes(tr.status)) return null
  // Show panel if: erp_reference is set, OR there is already a match status, OR admin can trigger auto-search
  if (!tr.erp_reference && !status && !tr.can_check_erp_match) return null

  const cfg = ERP_MATCH_CFG[status] || ERP_MATCH_CFG.pending
  const items = tr.erp_matched_items || []
  const hasDocs = status !== 'pending' && status !== 'not_found'

  function startCooldown(seconds = 60) {
    setCooldown(seconds)
    if (cooldownRef.current) clearInterval(cooldownRef.current)
    cooldownRef.current = setInterval(() => {
      setCooldown(prev => {
        if (prev <= 1) { clearInterval(cooldownRef.current); cooldownRef.current = null; return 0 }
        return prev - 1
      })
    }, 1000)
  }

  async function runCheck() {
    setChecking(true)
    try {
      await transfersApi.checkErpMatch(tr.id)
      onRefresh()
      startCooldown(60)
    } catch (e) {
      const msg = e.response?.data?.detail || 'حدث خطأ أثناء التحقق'
      // 429 = rate limited by backend — show remaining time and start cooldown
      if (e.response?.status === 429) {
        const match = msg.match(/(\d+)/)
        startCooldown(match ? parseInt(match[1], 10) : 20)
      }
      alert(msg)
    } finally { setChecking(false) }
  }

  return (
    <div className="card border-2 animate-fade-in"
      style={{ borderColor: cfg.border }}>
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="text-xl">{cfg.icon}</div>
        <div className="flex-1">
          <div className="font-bold text-sm text-gray-800">مطابقة مستند ERP</div>
          {tr.erp_reference ? (
            <div className="text-xs text-gray-400 mt-0.5">
              رقم المستند:{' '}
              <span className="font-mono text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded text-xs">
                {tr.erp_reference}
              </span>
            </div>
          ) : (
            <div className="text-xs text-amber-600 mt-0.5">
              🔎 لم يُدخَل رقم المستند — سيتم البحث تلقائياً عبر الأصناف والتاريخ
            </div>
          )}
        </div>
        {status && (
          <span className="px-2.5 py-1 rounded-full text-xs font-bold"
            style={{ background: cfg.bg, color: cfg.text, border: `1px solid ${cfg.border}` }}>
            {cfg.label}
          </span>
        )}
      </div>

      {/* Detail text */}
      {tr.erp_match_detail && (
        <div className="text-sm text-gray-700 bg-gray-50 border border-gray-100 rounded-xl px-3 py-2.5 mb-4 leading-relaxed">
          {tr.erp_match_detail}
        </div>
      )}

      {/* Matched doc info */}
      {hasDocs && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
          {tr.erp_match_doc_date && (
            <div className="bg-gray-50 rounded-xl px-3 py-2">
              <div className="text-xs text-gray-400">تاريخ المستند</div>
              <div className="text-sm font-semibold text-gray-800 font-mono">{tr.erp_match_doc_date}</div>
            </div>
          )}
          {tr.erp_match_doc_value != null && (
            <div className="bg-gray-50 rounded-xl px-3 py-2">
              <div className="text-xs text-gray-400">قيمة المستند</div>
              <div className="text-sm font-bold text-emerald-700">
                {Number(tr.erp_match_doc_value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م
              </div>
            </div>
          )}
          {(tr.erp_match_user_id || tr.erp_match_user_code) && (
            <div className="bg-gray-50 rounded-xl px-3 py-2">
              <div className="text-xs text-gray-400">المستخدم (ERP)</div>
              {tr.erp_match_user_id && (
                <div className="text-sm font-semibold text-gray-800">{tr.erp_match_user_id}</div>
              )}
              {tr.erp_match_user_name && tr.erp_match_user_name !== tr.erp_match_user_id && (
                <div className="text-xs text-gray-500">{tr.erp_match_user_name}</div>
              )}
              {tr.erp_match_user_code && (
                <div className="text-[10px] font-mono text-gray-400 mt-0.5">
                  كود: {tr.erp_match_user_code}
                </div>
              )}
            </div>
          )}
          {tr.erp_match_trans_time && (
            <div className="bg-gray-50 rounded-xl px-3 py-2">
              <div className="text-xs text-gray-400">وقت التنفيذ (ERP)</div>
              <div className="text-sm font-semibold text-gray-800 font-mono">
                {new Date(tr.erp_match_trans_time).toLocaleTimeString('en-GB', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
                })}
              </div>
              <div className="text-[10px] text-gray-400 mt-0.5">
                {new Date(tr.erp_match_trans_time).toLocaleDateString('en-GB')}
              </div>
            </div>
          )}
          {tr.erp_match_doc_code && (
            <div className="bg-gray-50 rounded-xl px-3 py-2">
              <div className="text-xs text-gray-400">نوع المستند</div>
              <div className="text-sm font-semibold text-gray-800">
                {SOFTECH_DOCTYPE[tr.erp_match_doc_code] || tr.erp_match_doc_code}
              </div>
              <div className="text-[10px] font-mono text-gray-400 mt-0.5">كود: {tr.erp_match_doc_code}</div>
            </div>
          )}
        </div>
      )}

      {/* Matched items table */}
      {items.length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-bold text-gray-500 mb-2">تفاصيل الأصناف</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-right pb-1.5 text-gray-400 font-semibold">الصنف</th>
                <th className="text-right pb-1.5 text-gray-400 font-semibold">الكمية المطلوبة</th>
                <th className="text-right pb-1.5 text-gray-400 font-semibold">كمية ERP</th>
                <th className="text-right pb-1.5 text-gray-400 font-semibold">الحالة</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((it, i) => {
                const lv = MATCH_LEVEL_CFG[it.match_level] || MATCH_LEVEL_CFG.not_found
                return (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="py-2 pr-0 font-semibold text-gray-800">
                      {it.itemname || it.itemcode}
                      {it.itemcode && <span className="font-mono text-gray-400 mr-1 text-[10px]">({it.itemcode})</span>}
                    </td>
                    <td className="py-2 tabular-nums text-gray-700">{it.requested_qty}</td>
                    <td className="py-2 tabular-nums text-gray-700">
                      {it.erp_qty != null ? it.erp_qty : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="py-2">
                      <span className="inline-flex items-center gap-1 font-medium" style={{ color: lv.text }}>
                        {lv.icon} {lv.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer: meta + action button */}
      <div className="flex items-center justify-between flex-wrap gap-2 border-t border-gray-100 pt-3">
        <div className="text-xs text-gray-400 space-y-0.5">
          {tr.erp_check_attempts > 0 && (
            <div>عدد المحاولات: <span className="font-semibold">{tr.erp_check_attempts}</span></div>
          )}
          {tr.erp_last_checked && (
            <div>آخر فحص: <span className="font-semibold">{timeAgo(tr.erp_last_checked)}</span></div>
          )}
          {status === 'pending' && (
            <div className="text-purple-500">🔄 يُفحص تلقائياً كل 30 دقيقة</div>
          )}
        </div>
        {tr.can_check_erp_match && (
          <div className="flex flex-col items-end gap-1">
            <button
              onClick={runCheck}
              disabled={checking || cooldown > 0}
              title={cooldown > 0 ? `يمكن إعادة الفحص بعد ${cooldown} ثانية` : ''}
              className="text-xs px-3 py-1.5 rounded-lg font-semibold bg-purple-600 hover:bg-purple-700 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {checking ? (
                <>
                  <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  جارٍ الفحص...
                </>
              ) : cooldown > 0 ? (
                `⏳ ${cooldown}ث`
              ) : tr.erp_match_status ? (
                tr.erp_reference ? '🔍 إعادة الفحص' : '🔎 إعادة البحث'
              ) : (
                tr.erp_reference ? '🔍 فحص الآن' : '🔎 بحث تلقائي'
              )}
            </button>
            {cooldown > 0 && (
              <span className="text-[10px] text-gray-400">
                إعادة الفحص متاحة بعد {cooldown}ث
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Tab 1: Details ────────────────────────────────────────────────────────────

function DetailsTab({ tr }) {
  const s = STATUS[tr.status] || STATUS.draft
  return (
    <div className="grid sm:grid-cols-2 gap-6">
      <div className="space-y-4">
        <div className="bg-brand-50 border border-brand-100 rounded-xl p-4">
          <div className="text-xs text-brand-500 font-semibold mb-1">الفرع الطالب</div>
          <div className="text-lg font-black text-brand-800">{tr.requesting_branch_name}</div>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div className="text-xs text-gray-500 font-semibold mb-1">الفرع المصدر</div>
          <div className="text-lg font-black text-gray-800">{tr.supplying_branch_name}</div>
        </div>
      </div>

      <div className="space-y-3">
        <div>
          <div className="text-xs text-gray-400 mb-1">الحالة</div>
          <span className="badge text-sm px-3 py-1"
            style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
            {s.label}
          </span>
        </div>
        <div>
          <div className="text-xs text-gray-400 mb-0.5">أنشئ بواسطة</div>
          <div className="text-sm font-semibold text-gray-700">{tr.created_by_name}</div>
          <div className="text-xs text-gray-400">{tr.created_by_branch}</div>
        </div>
        {tr.reviewed_by_name && (
          <div>
            <div className="text-xs text-gray-400 mb-0.5">راجع بواسطة</div>
            <div className="text-sm font-semibold text-gray-700">{tr.reviewed_by_name}</div>
          </div>
        )}
        {tr.erp_reference && (
          <div>
            <div className="text-xs text-gray-400 mb-0.5">مرجع ERP</div>
            <div className="text-sm font-mono text-purple-700 bg-purple-50 px-2 py-1 rounded">
              {tr.erp_reference}
            </div>
          </div>
        )}
        {tr.notes && (
          <div>
            <div className="text-xs text-gray-400 mb-0.5">ملاحظات</div>
            <div className="text-sm text-gray-700 bg-yellow-50 border border-yellow-100 rounded-lg px-3 py-2">
              {tr.notes}
            </div>
          </div>
        )}
        {tr.rejection_reason && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3">
            <div className="text-xs text-red-600 font-bold mb-1">سبب الرفض</div>
            <div className="text-sm text-red-800">{tr.rejection_reason}</div>
          </div>
        )}
        {tr.revision_notes && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3">
            <div className="text-xs text-yellow-700 font-bold mb-1">ملاحظات التعديل المطلوب</div>
            <div className="text-sm text-yellow-900">{tr.revision_notes}</div>
          </div>
        )}
      </div>

      {/* Timeline summary */}
      <div className="sm:col-span-2 border-t border-gray-100 pt-4">
        <div className="text-xs text-gray-400 font-semibold mb-3">مسار الطلب</div>
        <div className="flex items-center gap-0 overflow-x-auto no-scrollbar">
          {[
            { label: 'الإنشاء',     date: tr.created_at,    done: true },
            { label: 'التقديم',     date: tr.submitted_at,  done: !!tr.submitted_at },
            { label: 'المراجعة',    date: tr.reviewed_at,   done: !!tr.reviewed_at },
            { label: 'إرسال ERP',   date: tr.sent_to_erp_at, done: !!tr.sent_to_erp_at },
            { label: 'الاكتمال',    date: tr.completed_at,  done: !!tr.completed_at },
          ].map((step, i, arr) => (
            <div key={i} className="flex items-center">
              <div className={`flex flex-col items-center min-w-20 text-center`}>
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                  step.done ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-400'
                }`}>
                  {step.done ? '✓' : i + 1}
                </div>
                <div className={`text-xs mt-1 font-medium ${step.done ? 'text-brand-700' : 'text-gray-400'}`}>
                  {step.label}
                </div>
                {step.date && (
                  <div className="text-xs text-gray-400 mt-0.5 whitespace-nowrap">
                    {toLatinDigits(format(new Date(step.date), 'd/M HH:mm', { locale: ar }))}
                  </div>
                )}
              </div>
              {i < arr.length - 1 && (
                <div className={`h-0.5 w-8 mx-1 flex-shrink-0 ${
                  arr[i + 1].done ? 'bg-brand-600' : 'bg-gray-200'
                }`} />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Tab 2: Items ──────────────────────────────────────────────────────────────

function ItemsTab({ tr, onRefresh }) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [newQty, setNewQty] = useState('')
  const [newNotes, setNewNotes] = useState('')
  const [selectedItem, setSelectedItem] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // C2 — Smart source: fetch stock at all branches for the selected item
  const { data: itemStockData } = useQuery({
    queryKey: ['item-stock-all', selectedItem?.item_id],
    queryFn: () => transfersApi.itemStock(selectedItem.item_id).then(r => r.data),
    enabled: !!(adding && selectedItem?.item_id),
    staleTime: 60_000,
  })

  async function addItem() {
    if (!selectedItem || !newQty || Number(newQty) <= 0) {
      setError('اختر صنفاً وأدخل كمية صحيحة'); return
    }
    if (!selectedItem.item_id) {
      setError('هذا الصنف غير موجود في قاعدة البيانات المحلية — قد يحتاج إلى مزامنة')
      return
    }
    if (saving) return
    setError('')
    setSaving(true)
    try {
      await transfersApi.addItem(tr.id, {
        item: selectedItem.item_id,
        quantity: Number(newQty),
        notes: newNotes || '',
      })
      setAdding(false); setSelectedItem(null); setNewQty(''); setNewNotes('')
      onRefresh()
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' ') : 'حدث خطأ')
    } finally {
      setSaving(false)
    }
  }

  async function removeItem(itemId) {
    try {
      await transfersApi.removeItem(tr.id, itemId)
      onRefresh()
    } catch { }
  }

  const destStock = tr.destination_stock || {}

  return (
    <div>
      {/* Items table */}
      {tr.items.length === 0 ? (
        <div className="text-center py-10 text-gray-400">
          <div className="text-4xl mb-2">💊</div>
          <div className="text-sm">لا توجد أصناف في هذا الطلب</div>
        </div>
      ) : (
        <table className="w-full text-sm mb-4">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الصنف</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">مطلوب</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">معتمد</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">مستلم</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">متاح بالمصدر</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">ملاحظة</th>
              {tr.is_editable && <th className="pb-2 px-2" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {tr.items.map(line => {
              const avail = destStock[String(line.item)] ?? line.available_stock ?? null
              return (
                <tr key={line.id} className="hover:bg-gray-50">
                  <td className="py-3 px-2">
                    <div className="font-semibold text-gray-800">{line.item_name}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-xs text-gray-400 font-mono">{line.item_softech_id}</span>
                      {line.item_sale_price > 0 && (
                        <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                          {Number(line.item_sale_price).toFixed(2)} ج.م
                        </span>
                      )}
                    </div>
                    {line.item_scientific && (
                      <div className="text-xs text-gray-400 italic mt-0.5">{line.item_scientific}</div>
                    )}
                  </td>
                  <td className="py-3 px-2 font-bold tabular-nums text-gray-800">
                    {line.quantity}
                  </td>
                  <td className="py-3 px-2 tabular-nums">
                    {line.approved_quantity != null ? (
                      <span className={`font-bold ${Number(line.approved_quantity) < Number(line.quantity) ? 'text-orange-600' : 'text-blue-700'}`}>
                        {line.approved_quantity}
                        {Number(line.approved_quantity) < Number(line.quantity) && (
                          <span className="text-[10px] text-orange-400 mr-1">جزئي</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </td>
                  <td className="py-3 px-2 tabular-nums">
                    {line.received_quantity != null ? (
                      <span className={`font-bold ${Number(line.received_quantity) < Number(line.approved_quantity ?? line.quantity) ? 'text-red-600' : 'text-green-700'}`}>
                        {line.received_quantity}
                        {Number(line.received_quantity) < Number(line.approved_quantity ?? line.quantity) && (
                          <span className="text-[10px] text-red-400 mr-1">نقص</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </td>
                  <td className="py-3 px-2">
                    {avail !== null ? (
                      <span className={`font-bold tabular-nums ${
                        avail > 10 ? 'text-green-700' : avail > 0 ? 'text-orange-600' : 'text-red-500'
                      }`}>
                        {avail > 0 ? `${avail}` : 'نفد'}
                      </span>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </td>
                  <td className="py-3 px-2 text-xs text-gray-500">{line.notes || '—'}</td>
                  {tr.is_editable && (
                    <td className="py-3 px-2">
                      <button onClick={() => removeItem(line.id)}
                        className="text-gray-300 hover:text-red-400 text-lg leading-none transition-colors">
                        ✕
                      </button>
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {/* Add item form (only in editable state) */}
      {tr.is_editable && (
        <div className="border-t border-gray-100 pt-4">
          {!adding ? (
            <button onClick={() => setAdding(true)}
              className="btn-secondary text-sm">
              + إضافة صنف
            </button>
          ) : (
            <div className="bg-brand-50 border border-brand-200 rounded-xl p-4 space-y-3">
              <div className="text-xs font-bold text-brand-700">إضافة صنف جديد</div>
              <div className="flex flex-col gap-2">
                <ItemSearchWidget
                  selected={selectedItem}
                  onSelect={item => setSelectedItem(item)}
                  onClear={() => setSelectedItem(null)}
                  placeholder="ابحث باسم الصنف أو الكود أو الباركود (قارئ ضوئي متوافق)..."
                />

                {/* C2 — Smart source: stock at all branches for selected item */}
                {selectedItem && itemStockData?.stock_by_branch?.length > 0 && (
                  <div className="bg-amber-50 border border-amber-200 rounded-xl p-3">
                    <div className="text-xs font-bold text-amber-800 mb-2">مخزون الأصناف بالفروع</div>
                    <div className="space-y-1">
                      {[...itemStockData.stock_by_branch]
                        .sort((a, b) => b.quantity_on_hand - a.quantity_on_hand)
                        .slice(0, 5)
                        .map(b => (
                          <div key={b.branch_id} className="flex items-center justify-between text-xs">
                            <span className={`font-medium ${b.branch_id === tr.supplying_branch ? 'text-green-700' : 'text-gray-700'}`}>
                              {b.branch_id === tr.supplying_branch ? '✓ ' : ''}{b.branch_name}
                            </span>
                            <span className={`font-bold tabular-nums ${
                              b.quantity_on_hand > 10 ? 'text-green-700'
                              : b.quantity_on_hand > 0 ? 'text-orange-600'
                              : 'text-red-400'
                            }`}>
                              {b.quantity_on_hand > 0 ? b.quantity_on_hand : 'نفد'}
                            </span>
                          </div>
                        ))}
                    </div>
                    {tr.supplying_branch && (() => {
                      const sup = itemStockData.stock_by_branch.find(b => b.branch_id === tr.supplying_branch)
                      if (sup && sup.quantity_on_hand === 0) {
                        const best = [...itemStockData.stock_by_branch].sort((a,b) => b.quantity_on_hand - a.quantity_on_hand)[0]
                        if (best && best.quantity_on_hand > 0 && best.branch_id !== tr.supplying_branch) {
                          return (
                            <div className="mt-2 text-xs text-orange-700 bg-orange-50 rounded-lg px-2 py-1 border border-orange-200">
                              ⚠️ الفرع المصدر نفد — الفرع الأوفر: <span className="font-bold">{best.branch_name}</span> ({best.quantity_on_hand} وحدة)
                            </div>
                          )
                        }
                      }
                      return null
                    })()}
                  </div>
                )}
                <div className="flex gap-2">
                  <input type="number" min="0.001" step="0.001" placeholder="الكمية *"
                    value={newQty} onChange={e => setNewQty(e.target.value)}
                    className="input-field w-28 text-sm" />
                  <input placeholder="ملاحظة (اختياري)"
                    value={newNotes} onChange={e => setNewNotes(e.target.value)}
                    className="input-field flex-1 text-sm" />
                </div>
              </div>
              {error && <div className="text-xs text-red-600">{error}</div>}
              <div className="flex gap-2">
                <button onClick={addItem} disabled={saving}
                  className="btn-primary text-xs px-3 disabled:opacity-50">
                  {saving ? 'جارٍ الإضافة...' : 'إضافة'}
                </button>
                <button onClick={() => { setAdding(false); setSelectedItem(null); setItemSearchText(''); setError('') }}
                  disabled={saving}
                  className="btn-secondary text-xs px-3 disabled:opacity-50">إلغاء</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Chatter / Communication Panel ────────────────────────────────────────────

function CommunicationTab({ tr, onRefresh, onDeleteMessage }) {
  const [message, setMessage] = useState('')
  const [msgType, setMsgType] = useState('message')
  const [attachFile, setAttachFile] = useState(null)
  const [voiceFile, setVoiceFile] = useState(null)
  const [sending, setSending] = useState(false)
  const chatEndRef = useRef()
  const attachRef = useRef()

  const messages = tr.messages || []
  const humanCount = messages.filter(m => m.message_type !== 'system').length

  useEffect(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 80)
  }, [messages.length])

  async function sendMessage() {
    if (!message.trim() && !attachFile && !voiceFile) return
    setSending(true)
    try {
      const fd = new FormData()
      fd.append('message_type', msgType)
      fd.append('message', message)
      if (attachFile) fd.append('attachment', attachFile)
      if (voiceFile) fd.append('voice_note', voiceFile)
      await transfersApi.sendMessage(tr.id, fd)
      setMessage('')
      setAttachFile(null)
      setVoiceFile(null)
      onRefresh()
    } catch { } finally { setSending(false) }
  }

  return (
    <div className="flex flex-col h-full">

      {/* Panel header */}
      <div className="px-4 py-3 border-b border-gray-100 flex-shrink-0">
        <div className="text-sm font-bold text-gray-700 flex items-center gap-2">
          💬 المحادثة
          {humanCount > 0 && (
            <span className="text-xs bg-brand-100 text-brand-700 px-1.5 py-0.5 rounded-full font-semibold">
              {humanCount}
            </span>
          )}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">{messages.length} إجمالي الأنشطة</div>
      </div>

      {/* Messages feed */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2.5">
        {messages.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            <div className="text-3xl mb-2">💬</div>
            <div className="text-xs">لا توجد رسائل بعد</div>
          </div>
        )}

        {messages.map(msg => {
          const isSystem = msg.message_type === 'system'

          if (isSystem) return (
            <div key={msg.id} className="flex items-start gap-2">
              <div className="w-6 h-6 rounded-full bg-gray-100 flex items-center justify-center text-xs flex-shrink-0 mt-0.5">
                ⚙️
              </div>
              <div className="flex-1">
                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg px-2.5 py-1.5 leading-relaxed">
                  {msg.message}
                </div>
                <div className="text-xs text-gray-300 mt-0.5">{timeAgo(msg.created_at)}</div>
              </div>
            </div>
          )

          return (
            <div key={msg.id} className="flex items-start gap-2">
              <div className="w-7 h-7 rounded-full bg-brand-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5">
                {initials(msg.created_by_name || '؟')}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                  <span className="text-xs font-semibold text-gray-800">{msg.created_by_name}</span>
                  {msg.created_by_branch && (
                    <span className="text-xs text-gray-400 bg-gray-100 px-1 py-0.5 rounded">
                      {msg.created_by_branch}
                    </span>
                  )}
                  {!msg.is_deleted && msg.message_type === 'note' && (
                    <span className="text-xs text-yellow-600 bg-yellow-50 px-1 py-0.5 rounded">📝 داخلي</span>
                  )}
                  <span className="text-xs text-gray-300 mr-auto">{timeAgo(msg.created_at)}</span>
                  {/* Delete button */}
                  {msg.can_delete && onDeleteMessage && (
                    <button
                      onClick={() => onDeleteMessage(msg.id)}
                      className="text-gray-300 hover:text-red-400 transition-colors p-0.5 rounded"
                      title="حذف الرسالة"
                    >
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>

                {/* Tombstone */}
                {msg.is_deleted ? (
                  <div className="flex items-center gap-1.5 text-xs text-gray-400 italic bg-gray-50 border border-dashed border-gray-200 rounded-lg px-2.5 py-1.5">
                    <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                    <span>
                      تم حذف هذه الرسالة
                      {msg.deleted_by_name && ` بواسطة ${msg.deleted_by_name}`}
                      {msg.deleted_at && ` · ${timeAgo(msg.deleted_at)}`}
                    </span>
                  </div>
                ) : (
                  <>
                    {msg.message && (
                      <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-3 py-2 shadow-sm">
                        <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">{msg.message}</p>
                      </div>
                    )}
                    {msg.attachment_url && (
                      <div className="mt-1.5">
                        <img
                          src={msg.attachment_url}
                          alt="مرفق"
                          className="rounded-lg max-h-40 border border-gray-200 object-contain cursor-pointer hover:opacity-90"
                          onClick={() => window.open(msg.attachment_url, '_blank')}
                        />
                      </div>
                    )}
                    {msg.voice_note_url && (
                      <div className="mt-1.5">
                        <div className="flex items-center gap-1 text-xs text-gray-400 mb-1">
                          <span>🎙️</span><span>ملاحظة صوتية</span>
                        </div>
                        <audio
                          src={msg.voice_note_url}
                          controls
                          className="w-full h-8"
                          style={{ direction: 'ltr' }}
                        />
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )
        })}
        <div ref={chatEndRef} />
      </div>

      {/* Compose */}
      <div className="px-3 pb-3 pt-2 border-t border-gray-100 flex-shrink-0 space-y-2">
        <div className="flex gap-1">
          {[
            { v: 'message', label: '💬 رسالة' },
            { v: 'note',    label: '📝 ملاحظة داخلية' },
          ].map(t => (
            <button key={t.v} onClick={() => setMsgType(t.v)}
              className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors ${
                msgType === t.v ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
        <textarea rows={2} value={message} onChange={e => setMessage(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) sendMessage() }}
          placeholder="اكتب رسالة أو ملاحظة... (Ctrl+Enter)"
          className="w-full text-xs border border-gray-200 rounded-lg p-2 resize-none focus:outline-none focus:border-brand-300 bg-white placeholder-gray-300" />

        {/* Voice recorder */}
        <VoiceNoteRecorder
          onRecorded={(f) => setVoiceFile(f)}
          onClear={() => setVoiceFile(null)}
          disabled={sending}
          maxSeconds={120}
        />

        {/* Image attach row */}
        <div className="flex items-center gap-2">
          <input type="file" accept="image/*" ref={attachRef} className="hidden"
            onChange={e => setAttachFile(e.target.files[0] || null)} />
          <button
            onClick={() => attachRef.current?.click()}
            className="text-gray-400 hover:text-brand-600 transition-colors p-1 rounded"
            title="إرفاق صورة"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>
          {attachFile && (
            <span className="text-xs text-brand-600 bg-brand-50 px-2 py-0.5 rounded truncate max-w-28">
              📎 {attachFile.name}
              <button onClick={() => setAttachFile(null)} className="mr-1 text-gray-400 hover:text-red-500">✕</button>
            </span>
          )}
          <div className="flex-1" />
          <button onClick={sendMessage} disabled={(!message.trim() && !attachFile && !voiceFile) || sending}
            className="text-xs bg-brand-600 text-white px-3 py-1 rounded-lg disabled:opacity-40 hover:bg-brand-700 transition-colors font-medium">
            {sending ? 'جارٍ...' : 'إرسال'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tab 4: Activity Log ───────────────────────────────────────────────────────

function ActivityTab({ tr }) {
  const systemMsgs = (tr.messages || []).filter(m => m.message_type === 'system')
  const events = [
    { label: 'إنشاء الطلب',     at: tr.created_at,    icon: '➕', color: 'rgb(var(--c-brand-600))', by: tr.created_by_name },
    tr.submitted_at  && { label: 'تقديم الطلب',    at: tr.submitted_at,  icon: '📤', color: '#f59e0b', by: tr.created_by_name },
    tr.reviewed_at   && { label: 'مراجعة الطلب',   at: tr.reviewed_at,   icon: tr.status === 'rejected' ? '❌' : '✅', color: tr.status === 'rejected' ? '#ef4444' : '#3b82f6', by: tr.reviewed_by_name },
    tr.sent_to_erp_at && { label: 'إرسال للـ ERP',  at: tr.sent_to_erp_at, icon: '🚀', color: '#8b5cf6', by: tr.sent_to_erp_by_name },
    tr.completed_at  && { label: 'اكتمال الطلب',   at: tr.completed_at,  icon: '🏁', color: '#10b981' },
  ].filter(Boolean).sort((a, b) => new Date(a.at) - new Date(b.at))

  return (
    <div className="space-y-3">
      {events.map((ev, i) => (
        <div key={i} className="flex gap-3 items-start">
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0"
            style={{ background: tint(ev.color, 0.094) }}>
            {ev.icon}
          </div>
          <div className="flex-1 border-b border-gray-50 pb-3">
            <div className="font-semibold text-gray-800 text-sm">{ev.label}</div>
            {ev.by && <div className="text-xs text-gray-500 mt-0.5">بواسطة: {ev.by}</div>}
            <div className="text-xs text-gray-400 mt-0.5">{fmtDate(ev.at)}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TransferDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [actionLoading, setActionLoading] = useState(false)
  const [showPrintModal, setShowPrintModal] = useState(false)

  const { data: tr, isLoading, isError } = useQuery({
    queryKey: ['transfer', id],
    queryFn: () => transfersApi.get(id).then(r => r.data),
    refetchInterval: 60_000,
  })

  const invalidate = () => qc.invalidateQueries(['transfer', id])

  const handleDeleteMessage = async (messageId) => {
    if (!window.confirm('هل تريد حذف هذه الرسالة؟ ستبقى علامة الحذف مرئية للجميع.')) return
    try {
      await transfersApi.deleteMessage(id, messageId)
      invalidate()
    } catch (e) {
      alert(e.response?.data?.detail || 'تعذّر حذف الرسالة')
    }
  }

  async function handleAction(actionName, payload = {}) {
    setActionLoading(true)
    try {
      const actionMap = {
        'submit':       () => transfersApi.submit(id),
        'approve':      () => transfersApi.approve(id, payload),
        'reject':       () => transfersApi.reject(id, payload),
        'revision':     () => transfersApi.revision(id, payload),
        'send-to-erp':  () => transfersApi.sendToERP(id, payload),
        'dispatch':     () => transfersApi.dispatch(id, payload),
        'complete':     () => transfersApi.complete(id, payload),
        'cancel':       () => transfersApi.cancel(id),
      }
      await actionMap[actionName]?.()
      invalidate()
      qc.invalidateQueries(['transfers'])
    } catch (e) {
      alert(e.response?.data?.detail || 'حدث خطأ')
    } finally { setActionLoading(false) }
  }

  if (isLoading) return (
    <div className="p-8 animate-pulse" dir="rtl">
      <div className="h-10 bg-gray-200 rounded-xl w-64 mb-6" />
      <div className="h-64 bg-gray-100 rounded-2xl" />
    </div>
  )

  if (isError || !tr) return (
    <div className="p-8 text-center" dir="rtl">
      <div className="text-5xl mb-3">😕</div>
      <div className="text-gray-600">لم يتم العثور على الطلب</div>
      <button onClick={() => navigate('/transfers')} className="btn-secondary mt-4">← العودة</button>
    </div>
  )

  const s = STATUS[tr.status] || STATUS.draft

  return (
    <div className="flex flex-col bg-gray-50" style={{ minHeight: '100vh' }} dir="rtl">
      {showPrintModal && (
        <PrintReceiptModal
          type="transfer"
          docId={tr.id}
          onClose={() => setShowPrintModal(false)}
        />
      )}

      {/* ── Sticky header ── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20 flex-shrink-0">
        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={() => navigate('/transfers')}
            className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-black text-gray-900 font-mono">{tr.request_number}</h1>
              <span className="badge text-sm px-3 py-1 font-semibold"
                style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
                {s.label}
              </span>
              {/* Deep-link to the fulfillment side once issued as a 125 */}
              {(tr.in_transit_docs || []).map(d => (
                <button
                  key={d.id}
                  onClick={() => navigate(`/transits?id=${d.id}`)}
                  title={`تتبع الشحنة قيد النقل — ${d.transit_status_display}`}
                  className="text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
                >
                  🚛 قيد النقل ← {d.erp_doc_number}
                </button>
              ))}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              {tr.requesting_branch_name} → {tr.supplying_branch_name}
              · {tr.created_by_name}
              · {timeAgo(tr.created_at)}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Print & WhatsApp */}
            <button
              onClick={() => setShowPrintModal(true)}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
              title="طباعة الإيصال"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
              </svg>
              طباعة
            </button>
            <WhatsAppShareButton type="transfer" docId={tr.id} size="sm" />
            <ActionButtons tr={tr} onAction={handleAction} loading={actionLoading} />
          </div>
        </div>
      </div>

      {/* ── 2-column body ── */}
      <div className="flex flex-1 gap-0 overflow-hidden" style={{ height: 'calc(100vh - 105px)' }}>

        {/* Left: single-scroll — Details → Items → Activity */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">

          {/* ── Details ── */}
          <div className="card animate-fade-in">
            <SectionHeading icon="📋" label="التفاصيل" />
            <DetailsTab tr={tr} />
          </div>

          {/* ── ERP Match Verification ── */}
          <ERPMatchPanel tr={tr} onRefresh={invalidate} />

          {/* ── Items ── */}
          <div className="card">
            <SectionHeading icon="💊" label="الأصناف" count={tr.items?.length} />
            <ItemsTab tr={tr} onRefresh={invalidate} />
          </div>

          {/* ── Activity log ── */}
          <div className="card">
            <SectionHeading icon="📜" label="سجل الأنشطة" />
            <ActivityTab tr={tr} />
          </div>

        </div>

        {/* Right: always-visible chatter panel */}
        <div className="w-80 flex-shrink-0 flex flex-col bg-white border-r border-gray-200 shadow-inner">
          <CommunicationTab tr={tr} onRefresh={invalidate} onDeleteMessage={handleDeleteMessage} />
        </div>
      </div>
    </div>
  )
}
