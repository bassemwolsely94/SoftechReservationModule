import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { transfersApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

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
  try { return format(new Date(d), 'd MMM yyyy — HH:mm', { locale: ar }) } catch { return d }
}

function timeAgo(d) {
  if (!d) return ''
  try { return formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true }) } catch { return '' }
}

function initials(name) {
  return (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('')
}

// ── Tab component ─────────────────────────────────────────────────────────────

function Tab({ label, icon, active, onClick, count }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
        active
          ? 'border-brand-600 text-brand-700'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-200'
      }`}
    >
      <span>{icon}</span>
      {label}
      {count !== undefined && (
        <span className={`badge text-xs ${active ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-400'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

// ── Action buttons ────────────────────────────────────────────────────────────

function ActionButtons({ tr, onAction, loading }) {
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [showRevisionForm, setShowRevisionForm] = useState(false)
  const [showErpForm, setShowErpForm] = useState(false)
  const [rejectionReason, setRejectionReason] = useState('')
  const [revisionNotes, setRevisionNotes] = useState('')
  const [erpRef, setErpRef] = useState('')

  if (!tr) return null

  return (
    <div className="flex items-center gap-2 flex-wrap">

      {/* Submit */}
      {tr.can_submit && (
        <button
          onClick={() => onAction('submit')}
          disabled={loading}
          className="btn-primary text-sm disabled:opacity-50"
        >
          📤 تقديم الطلب
        </button>
      )}

      {/* Approve */}
      {tr.can_approve && (
        <button
          onClick={() => onAction('approve')}
          disabled={loading}
          className="text-sm px-4 py-2 rounded-lg font-semibold bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50"
        >
          ✅ اعتماد
        </button>
      )}

      {/* Reject */}
      {tr.can_reject && !showRejectForm && (
        <button
          onClick={() => setShowRejectForm(true)}
          className="btn-danger text-sm"
        >
          ❌ رفض
        </button>
      )}

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

      {/* Complete */}
      {tr.status === 'sent_to_erp' && (
        <button onClick={() => onAction('complete')}
          className="text-sm px-4 py-2 rounded-lg font-semibold bg-green-600 hover:bg-green-700 text-white transition-colors">
          🏁 إغلاق كمكتمل
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
          <div className="text-lg font-black text-brand-800">{tr.source_branch_name}</div>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div className="text-xs text-gray-500 font-semibold mb-1">الفرع المصدر</div>
          <div className="text-lg font-black text-gray-800">{tr.destination_branch_name}</div>
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
                    {format(new Date(step.date), 'd/M HH:mm', { locale: ar })}
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

  async function addItem() {
    if (!selectedItem || !newQty || Number(newQty) <= 0) {
      setError('اختر صنفاً وأدخل كمية صحيحة'); return
    }
    setError('')
    try {
      await transfersApi.addItem(tr.id, {
        item: selectedItem.id,
        quantity: newQty,
        notes: newNotes || '',
      })
      setAdding(false); setSelectedItem(null); setNewQty(''); setNewNotes('')
      onRefresh()
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' ') : 'حدث خطأ')
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
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الكمية المطلوبة</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">المتاح بالفرع المصدر</th>
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
                    <div className="text-xs text-gray-400 font-mono">{line.item_softech_id}</div>
                    {line.item_scientific && (
                      <div className="text-xs text-gray-400 italic">{line.item_scientific}</div>
                    )}
                  </td>
                  <td className="py-3 px-2 font-bold tabular-nums text-gray-800">
                    {line.quantity} وحدة
                  </td>
                  <td className="py-3 px-2">
                    {avail !== null ? (
                      <span className={`font-bold tabular-nums ${
                        avail > 10 ? 'text-green-700' : avail > 0 ? 'text-orange-600' : 'text-red-500'
                      }`}>
                        {avail > 0 ? `${avail} وحدة` : 'نفد'}
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
                <ItemSearch onSelect={item => setSelectedItem(item)} />
                {selectedItem && (
                  <div className="text-xs text-brand-600 bg-white border border-brand-200 rounded-lg px-2 py-1">
                    ✓ {selectedItem.name} ({selectedItem.softech_id})
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
                <button onClick={addItem} className="btn-primary text-xs px-3">إضافة</button>
                <button onClick={() => { setAdding(false); setSelectedItem(null); setError('') }}
                  className="btn-secondary text-xs px-3">إلغاء</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Tab 3: Communication ──────────────────────────────────────────────────────

function CommunicationTab({ tr, onRefresh }) {
  const [message, setMessage] = useState('')
  const [msgType, setMsgType] = useState('message')
  const [sending, setSending] = useState(false)
  const chatEndRef = useRef()
  const { user } = useAuthStore()

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [tr.messages?.length])

  async function sendMessage() {
    if (!message.trim()) return
    setSending(true)
    try {
      await transfersApi.sendMessage(tr.id, { message_type: msgType, message })
      setMessage('')
      onRefresh()
    } catch { } finally { setSending(false) }
  }

  const messages = tr.messages || []

  return (
    <div className="flex flex-col gap-4">
      {/* Messages feed */}
      <div className="max-h-96 overflow-y-auto space-y-0 divide-y divide-gray-50">
        {messages.length === 0 && (
          <div className="text-center py-10 text-gray-400">
            <div className="text-3xl mb-2">💬</div>
            <div className="text-sm">لا توجد رسائل بعد</div>
          </div>
        )}
        {messages.map(msg => {
          const isSystem = msg.message_type === 'system'
          if (isSystem) return (
            <div key={msg.id} className="flex items-start gap-2 py-2.5">
              <div className="w-7 h-7 rounded-full bg-gray-100 flex items-center justify-center text-sm flex-shrink-0">
                ⚙️
              </div>
              <div className="flex-1">
                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2 leading-relaxed">
                  {msg.message}
                </div>
                <div className="text-xs text-gray-300 mt-0.5">{timeAgo(msg.created_at)}</div>
              </div>
            </div>
          )

          return (
            <div key={msg.id} className="flex items-start gap-3 py-3">
              <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                {initials(msg.created_by_name || '؟')}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-semibold text-gray-800">{msg.created_by_name}</span>
                  {msg.created_by_branch && (
                    <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                      {msg.created_by_branch}
                    </span>
                  )}
                  {msg.message_type === 'note' && (
                    <span className="text-xs text-yellow-600 bg-yellow-50 px-1.5 py-0.5 rounded">
                      ملاحظة داخلية
                    </span>
                  )}
                  <span className="text-xs text-gray-400 mr-auto">{timeAgo(msg.created_at)}</span>
                </div>
                <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-4 py-2.5 shadow-sm">
                  <p className="text-sm text-gray-700 leading-relaxed">{msg.message}</p>
                </div>
              </div>
            </div>
          )
        })}
        <div ref={chatEndRef} />
      </div>

      {/* Compose */}
      <div className="border border-gray-200 rounded-xl p-3">
        <div className="flex gap-1 mb-2">
          {[
            { v: 'message', label: '💬 رسالة' },
            { v: 'note',    label: '📝 ملاحظة داخلية' },
          ].map(t => (
            <button key={t.v} onClick={() => setMsgType(t.v)}
              className={`text-xs px-2.5 py-1 rounded-full font-medium transition-colors ${
                msgType === t.v ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
        <textarea rows={2} value={message} onChange={e => setMessage(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) sendMessage() }}
          placeholder="اكتب رسالة أو ملاحظة... (Ctrl+Enter للإرسال)"
          className="w-full text-sm resize-none focus:outline-none placeholder-gray-300 leading-relaxed" />
        <div className="flex justify-end mt-2 pt-2 border-t border-gray-100">
          <button onClick={sendMessage} disabled={!message.trim() || sending}
            className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50">
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
    { label: 'إنشاء الطلب',     at: tr.created_at,    icon: '➕', color: '#1B6B3A', by: tr.created_by_name },
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
            style={{ background: ev.color + '18' }}>
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

function ItemSearch({ onSelect }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef()

  const { data: results } = useQuery({
    queryKey: ['item-search-detail', q],
    queryFn: () => itemsApi.list({ search: q, page_size: 10 }).then(r => r.data.results || r.data),
    enabled: q.length >= 2,
    staleTime: 10_000,
  })

  useEffect(() => {
    function h(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  return (
    <div ref={ref} className="relative">
      <input className="input-field text-sm" placeholder="ابحث بالاسم أو الكود..."
        value={q} onChange={e => { setQ(e.target.value); setOpen(true) }} autoComplete="off" />
      {open && q.length >= 2 && results?.length > 0 && (
        <div className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-52 overflow-y-auto">
          {results.map(item => (
            <button key={item.id} type="button"
              className="w-full text-right px-4 py-2.5 hover:bg-brand-50 transition-colors border-b border-gray-50 last:border-0"
              onClick={() => { onSelect(item); setQ(''); setOpen(false) }}>
              <div className="font-semibold text-gray-800 text-sm">{item.name}</div>
              <div className="text-xs text-blue-500 font-mono">كود: {item.softech_id}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function TransferDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [tab, setTab] = useState('details')
  const [actionLoading, setActionLoading] = useState(false)

  const { data: tr, isLoading, isError } = useQuery({
    queryKey: ['transfer', id],
    queryFn: () => transfersApi.get(id).then(r => r.data),
    refetchInterval: 60_000,
  })

  const invalidate = () => qc.invalidateQueries(['transfer', id])

  async function handleAction(actionName, payload = {}) {
    setActionLoading(true)
    try {
      const actionMap = {
        'submit':       () => transfersApi.submit(id),
        'approve':      () => transfersApi.approve(id),
        'reject':       () => transfersApi.reject(id, payload),
        'revision':     () => transfersApi.revision(id, payload),
        'send-to-erp':  () => transfersApi.sendToERP(id, payload),
        'complete':     () => transfersApi.complete(id),
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
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-5xl mx-auto">
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
              </div>
              <div className="text-xs text-gray-400 mt-0.5">
                {tr.source_branch_name} → {tr.destination_branch_name}
                · {tr.created_by_name}
                · {timeAgo(tr.created_at)}
              </div>
            </div>

            <ActionButtons tr={tr} onAction={handleAction} loading={actionLoading} />
          </div>

          {/* Tabs */}
          <div className="flex gap-0 mt-3 border-b border-gray-200 overflow-x-auto no-scrollbar -mb-px">
            <Tab icon="📋" label="التفاصيل"     active={tab === 'details'}       onClick={() => setTab('details')} />
            <Tab icon="💊" label="الأصناف"      active={tab === 'items'}         onClick={() => setTab('items')}   count={tr.items?.length} />
            <Tab icon="💬" label="التواصل"      active={tab === 'communication'} onClick={() => setTab('communication')} count={(tr.messages || []).filter(m => m.message_type !== 'system').length} />
            <Tab icon="📜" label="سجل الأنشطة" active={tab === 'activity'}      onClick={() => setTab('activity')} />
          </div>
        </div>
      </div>

      {/* Tab content */}
      <div className="max-w-5xl mx-auto px-6 py-6">
        <div className="card animate-fade-in">
          {tab === 'details'       && <DetailsTab       tr={tr} />}
          {tab === 'items'         && <ItemsTab         tr={tr} onRefresh={invalidate} />}
          {tab === 'communication' && <CommunicationTab tr={tr} onRefresh={invalidate} />}
          {tab === 'activity'      && <ActivityTab      tr={tr} />}
        </div>
      </div>
    </div>
  )
}
