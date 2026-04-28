import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reservationsApi } from '../api/client'
import { StatusBadge, PriorityBadge, STATUS_OPTIONS } from '../components/StatusBadge'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Constants ─────────────────────────────────────────────────────────────────

const NEXT_STATUSES = {
  pending:   ['available', 'cancelled'],
  available: ['contacted', 'cancelled'],
  contacted: ['confirmed', 'expired', 'cancelled'],
  confirmed: ['fulfilled', 'cancelled'],
  fulfilled: [],
  cancelled: [],
  expired:   [],
}

const ACTIVITY_TYPE_OPTIONS = [
  { value: 'note',               label: '📝 ملاحظة' },
  { value: 'call_made',          label: '📞 مكالمة أُجريت' },
  { value: 'customer_replied',   label: '💬 رد العميل' },
  { value: 'stock_checked',      label: '🔍 تم فحص المخزون' },
  { value: 'transfer_requested', label: '🔀 طلب تحويل مخزون' },
]

const STATUS_COLOR_MAP = {
  pending:   { bg: 'bg-gray-100',   text: 'text-gray-700',   dot: '#9ca3af' },
  available: { bg: 'bg-orange-100', text: 'text-orange-700', dot: '#f59e0b' },
  contacted: { bg: 'bg-blue-100',   text: 'text-blue-700',   dot: '#3b82f6' },
  confirmed: { bg: 'bg-indigo-100', text: 'text-indigo-700', dot: '#6366f1' },
  fulfilled: { bg: 'bg-green-100',  text: 'text-green-700',  dot: '#10b981' },
  cancelled: { bg: 'bg-red-100',    text: 'text-red-700',    dot: '#ef4444' },
  expired:   { bg: 'bg-red-100',    text: 'text-red-700',    dot: '#ef4444' },
}

const ROLE_ACTIONS = {
  call_center: [
    { status: 'available', label: 'المخزون متاح 📦' },
    { status: 'contacted', label: 'تم التواصل 📞' },
    { status: 'cancelled', label: 'إلغاء الحجز ✕' },
  ],
  pharmacist: [
    { status: 'confirmed', label: 'العميل قادم ✅' },
    { status: 'fulfilled', label: 'تم الصرف 💊' },
    { status: 'cancelled', label: 'إلغاء ✕' },
  ],
  salesperson: [
    { status: 'available', label: 'المخزون متاح 📦' },
    { status: 'contacted', label: 'تم التواصل 📞' },
    { status: 'cancelled', label: 'إلغاء ✕' },
  ],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(dt) {
  try { return formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }) } catch { return '' }
}

function formatDate(d) {
  if (!d) return '—'
  try { return format(new Date(d), 'd MMMM yyyy', { locale: ar }) } catch { return d }
}

function formatDateTime(d) {
  if (!d) return '—'
  try { return format(new Date(d), 'd MMM yyyy — HH:mm', { locale: ar }) } catch { return d }
}

function InitialsAvatar({ name, role }) {
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('')
  const colors = {
    admin: 'bg-red-500',
    call_center: 'bg-blue-500',
    pharmacist: 'bg-green-600',
    salesperson: 'bg-indigo-500',
    purchasing: 'bg-yellow-600',
  }
  const bg = colors[role] || 'bg-gray-500'
  return (
    <div className={`w-8 h-8 rounded-full ${bg} flex items-center justify-center text-white text-xs font-bold flex-shrink-0`}>
      {initials}
    </div>
  )
}

// ── Stock Widget ──────────────────────────────────────────────────────────────

function StockWidget({ stockByBranch, currentBranchId }) {
  if (!stockByBranch || stockByBranch.length === 0) {
    return (
      <div className="text-xs text-gray-400 text-center py-3">
        لا توجد بيانات مخزون متاحة
      </div>
    )
  }

  const total = stockByBranch.reduce((sum, s) => sum + s.quantity, 0)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
        <span>الفرع</span>
        <span>الكمية المتاحة</span>
      </div>
      {stockByBranch.map(s => {
        const isCurrent = s.branch_id === currentBranchId
        const pct = total > 0 ? Math.round((s.quantity / total) * 100) : 0
        const barColor = s.quantity > 10
          ? 'bg-green-400'
          : s.quantity > 0
          ? 'bg-orange-400'
          : 'bg-red-300'

        return (
          <div key={s.branch_id} className={`rounded-lg p-2 ${isCurrent ? 'bg-brand-50 border border-brand-200' : 'bg-gray-50'}`}>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                {isCurrent && (
                  <span className="w-1.5 h-1.5 rounded-full bg-brand-500 inline-block" />
                )}
                <span className={`text-xs font-medium ${isCurrent ? 'text-brand-700' : 'text-gray-600'}`}>
                  {s.branch_name}
                </span>
              </div>
              <span className={`text-xs font-bold tabular-nums ${
                s.quantity > 0 ? 'text-green-700' : 'text-red-500'
              }`}>
                {s.quantity > 0 ? s.quantity : 'نفد'}
              </span>
            </div>
            {total > 0 && (
              <div className="h-1 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            )}
          </div>
        )
      })}
      <div className="text-xs text-gray-400 text-left pt-1 tabular-nums">
        الإجمالي: {total} وحدة
      </div>
    </div>
  )
}

// ── Chatter Entry ─────────────────────────────────────────────────────────────

function ActivityEntry({ activity }) {
  const isSystem = activity.activity_type === 'status_changed'
  const isDispensed = activity.activity_type === 'item_dispensed'

  // System auto-logs rendered differently (like Odoo gray banners)
  if (isSystem || isDispensed) {
    return (
      <div className="flex items-start gap-3 py-2">
        <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0 text-sm">
          {activity.activity_icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="bg-gray-50 rounded-lg px-3 py-2 border border-gray-100">
            <p className="text-xs text-gray-600 leading-relaxed whitespace-pre-line">
              {activity.message}
            </p>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-gray-400">{activity.created_by_name}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-400" title={formatDateTime(activity.created_at)}>
              {timeAgo(activity.created_at)}
            </span>
          </div>
        </div>
      </div>
    )
  }

  // Human-posted activity (note, call, etc.)
  return (
    <div className="flex items-start gap-3 py-2">
      <InitialsAvatar name={activity.created_by_name} role={activity.created_by_role} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="text-sm font-semibold text-gray-800">{activity.created_by_name}</span>
          {activity.created_by_branch && (
            <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
              {activity.created_by_branch}
            </span>
          )}
          <span className="text-xs text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded border">
            {activity.activity_icon} {activity.activity_label}
          </span>
          <span
            className="text-xs text-gray-400 mr-auto"
            title={formatDateTime(activity.created_at)}
          >
            {timeAgo(activity.created_at)}
          </span>
        </div>

        {/* Message bubble */}
        {activity.message && (
          <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-4 py-3 shadow-sm">
            <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
              {activity.message}
            </p>
          </div>
        )}

        {/* Attachment */}
        {activity.attachment_url && (
          <div className="mt-2">
            <img
              src={activity.attachment_url}
              alt="مرفق"
              className="rounded-lg max-h-48 border border-gray-200 object-contain cursor-pointer hover:opacity-90"
              onClick={() => window.open(activity.attachment_url, '_blank')}
            />
          </div>
        )}

        {/* Mentions */}
        {activity.mentioned_users_names?.length > 0 && (
          <div className="flex gap-1 mt-1 flex-wrap">
            {activity.mentioned_users_names.map(u => (
              <span key={u.id} className="text-xs text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">
                @{u.name}
              </span>
            ))}
          </div>
        )}

        {/* Transfer reference */}
        {activity.transfer_request_id_ref && (
          <div className="mt-1 text-xs text-blue-600">
            🔀 طلب تحويل #{activity.transfer_request_id_ref}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Chatter Input ─────────────────────────────────────────────────────────────

function ChatterInput({ reservationId, onPosted }) {
  const [type, setType] = useState('note')
  const [message, setMessage] = useState('')
  const [file, setFile] = useState(null)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef()
  const textRef = useRef()

  const handlePost = async () => {
    if (!message.trim() && !file) {
      setError('اكتب رسالة أو أرفق صورة')
      return
    }
    setPosting(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('activity_type', type)
      fd.append('message', message)
      if (file) fd.append('attachment', file)
      await reservationsApi.logActivity(reservationId, fd)
      setMessage('')
      setFile(null)
      onPosted()
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setPosting(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      handlePost()
    }
  }

  return (
    <div className="border-t border-gray-100 pt-4 mt-2">
      {/* Type selector */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {ACTIVITY_TYPE_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => setType(opt.value)}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              type === opt.value
                ? 'bg-brand-600 text-white border-brand-600'
                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Text area */}
      <textarea
        ref={textRef}
        rows={3}
        value={message}
        onChange={e => setMessage(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="اكتب ملاحظة، نتيجة مكالمة، أو تحديثاً... (Ctrl+Enter للإرسال)"
        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200 placeholder-gray-400"
      />

      {/* Footer row */}
      <div className="flex items-center gap-2 mt-2">
        {/* File attach */}
        <input type="file" accept="image/*" ref={fileRef} className="hidden"
          onChange={e => setFile(e.target.files[0])} />
        <button
          onClick={() => fileRef.current?.click()}
          className="text-gray-400 hover:text-brand-600 transition-colors p-1 rounded"
          title="إرفاق صورة"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>

        {file && (
          <span className="text-xs text-brand-600 bg-brand-50 px-2 py-0.5 rounded truncate max-w-32">
            📎 {file.name}
            <button onClick={() => setFile(null)} className="mr-1 text-gray-400 hover:text-red-500">✕</button>
          </span>
        )}

        {error && <span className="text-xs text-red-500 flex-1">{error}</span>}

        <div className="flex-1" />

        <span className="text-xs text-gray-300">Ctrl+Enter</span>
        <button
          onClick={handlePost}
          disabled={posting}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-semibold px-4 py-1.5 rounded-lg transition-colors"
        >
          {posting ? 'جارٍ...' : 'إرسال'}
        </button>
      </div>
    </div>
  )
}

// ── Status Change Modal ───────────────────────────────────────────────────────

function ChangeStatusModal({ reservation, onClose, onSuccess }) {
  const qc = useQueryClient()
  const [newStatus, setNewStatus] = useState('')
  const [note, setNote] = useState('')

  const allowed = NEXT_STATUSES[reservation.status] || []
  const allowedOptions = STATUS_OPTIONS.filter(o => allowed.includes(o.value))

  const mutation = useMutation({
    mutationFn: () => reservationsApi.changeStatus(reservation.id, newStatus, note),
    onSuccess: () => {
      qc.invalidateQueries(['reservation', String(reservation.id)])
      qc.invalidateQueries(['reservations-kanban'])
      onSuccess?.()
      onClose()
    },
  })

  if (allowed.length === 0) return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="card max-w-sm w-full mx-4" onClick={e => e.stopPropagation()}>
        <p className="text-gray-500 text-center py-4 text-sm">لا يمكن تغيير حالة هذا الحجز</p>
        <button onClick={onClose} className="btn-secondary w-full">إغلاق</button>
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full mx-4 p-6" onClick={e => e.stopPropagation()} dir="rtl">
        <h3 className="font-bold text-gray-800 mb-4 text-base">تغيير حالة الحجز</h3>
        <div className="mb-3">
          <label className="label">الحالة الجديدة *</label>
          <div className="flex flex-col gap-2">
            {allowedOptions.map(o => {
              const sc = STATUS_COLOR_MAP[o.value] || {}
              return (
                <label key={o.value} className={`flex items-center gap-3 p-3 rounded-xl border-2 cursor-pointer transition-all ${
                  newStatus === o.value ? 'border-brand-400 bg-brand-50' : 'border-gray-200 hover:border-gray-300'
                }`}>
                  <input type="radio" name="status" value={o.value}
                    checked={newStatus === o.value}
                    onChange={() => setNewStatus(o.value)}
                    className="sr-only" />
                  <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0`}
                    style={{ background: sc.dot || '#9ca3af' }} />
                  <span className="text-sm font-medium text-gray-700">{o.label}</span>
                </label>
              )
            })}
          </div>
        </div>
        <div className="mb-4">
          <label className="label">ملاحظة (اختياري)</label>
          <textarea rows={2} className="input-field" value={note}
            onChange={e => setNote(e.target.value)} placeholder="سبب التغيير..." />
        </div>
        {mutation.isError && (
          <div className="text-red-600 text-xs mb-3 bg-red-50 rounded-lg px-3 py-2">
            {mutation.error?.response?.data?.detail || 'حدث خطأ'}
          </div>
        )}
        <div className="flex gap-2">
          <button onClick={onClose} className="btn-secondary flex-1">إلغاء</button>
          <button
            disabled={!newStatus || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="btn-primary flex-1 disabled:opacity-50"
          >
            {mutation.isPending ? 'جارٍ...' : 'تأكيد'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReservationDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [showStatusModal, setShowStatusModal] = useState(false)
  const chatEndRef = useRef()

  const { data: r, isLoading, isError } = useQuery({
    queryKey: ['reservation', id],
    queryFn: () => reservationsApi.get(id).then(res => res.data),
    refetchInterval: 60_000,
  })

  // Scroll chatter to bottom on load
  useEffect(() => {
    if (r?.activities?.length) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [r?.activities?.length])

  const invalidate = () => {
    qc.invalidateQueries(['reservation', id])
    qc.invalidateQueries(['reservations-kanban'])
  }

  if (isLoading) return (
    <div className="p-8 flex flex-col gap-4 animate-pulse" dir="rtl">
      <div className="h-8 w-48 bg-gray-200 rounded-xl" />
      <div className="grid md:grid-cols-3 gap-5">
        <div className="md:col-span-2 space-y-4">
          {[1,2,3].map(i => <div key={i} className="h-32 bg-gray-100 rounded-xl" />)}
        </div>
        <div className="h-96 bg-gray-100 rounded-xl" />
      </div>
    </div>
  )

  if (isError || !r) return (
    <div className="p-8 text-center" dir="rtl">
      <div className="text-5xl mb-3">😕</div>
      <div className="text-gray-600">لم يتم العثور على الحجز</div>
      <button onClick={() => navigate('/reservations')} className="btn-secondary mt-4">
        ← العودة للحجوزات
      </button>
    </div>
  )

  const canChange = !['fulfilled', 'cancelled', 'expired'].includes(r.status)
  const userRole = user?.role || 'viewer'
  const roleActions = (ROLE_ACTIONS[userRole] || []).filter(a =>
    (NEXT_STATUSES[r.status] || []).includes(a.status)
  )

  const sc = STATUS_COLOR_MAP[r.status] || STATUS_COLOR_MAP.pending

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {showStatusModal && (
        <ChangeStatusModal
          reservation={r}
          onClose={() => setShowStatusModal(false)}
          onSuccess={invalidate}
        />
      )}

      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4 flex-wrap">
          <button
            onClick={() => navigate('/reservations')}
            className="text-gray-400 hover:text-gray-700 transition-colors p-1 rounded-lg hover:bg-gray-100"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-black text-gray-900">حجز #{r.id}</h1>
              <span className={`badge ${sc.bg} ${sc.text}`}>{r.status_label}</span>
              <PriorityBadge priority={r.priority} />
              {r.item_softech_id && (
                <span className="text-xs font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                  {r.item_softech_id}
                </span>
              )}
            </div>
            <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-2">
              <span>{formatDateTime(r.created_at)}</span>
              {r.created_by_name && <><span>·</span><span>{r.created_by_name}</span></>}
              {r.branch_name && <><span>·</span><span>🏥 {r.branch_name}</span></>}
            </div>
          </div>

          {/* Role-based quick action buttons */}
          <div className="flex gap-2 flex-wrap">
            {roleActions.map(a => {
              const asc = STATUS_COLOR_MAP[a.status] || {}
              return (
                <button
                  key={a.status}
                  onClick={() => {
                    reservationsApi.changeStatus(r.id, a.status, '').then(invalidate)
                  }}
                  className="text-sm px-3 py-1.5 rounded-lg font-medium border transition-colors hover:opacity-90"
                  style={{
                    borderColor: asc.dot || '#d1d5db',
                    color: asc.dot || '#6b7280',
                  }}
                >
                  {a.label}
                </button>
              )
            })}
            {canChange && (
              <button onClick={() => setShowStatusModal(true)} className="btn-primary text-sm">
                تغيير الحالة
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-6 py-6 grid lg:grid-cols-3 gap-6">

        {/* ── Left / Main: Chatter ──────────────────────────────────────── */}
        <div className="lg:col-span-2 flex flex-col gap-5">

          {/* Chatter card */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-gray-800 text-sm">
                سجل الأنشطة
                {r.activities?.length > 0 && (
                  <span className="mr-2 text-xs font-normal text-gray-400">
                    ({r.activities.length} إدخال)
                  </span>
                )}
              </h3>
            </div>

            {/* Activities feed */}
            <div className="space-y-0 divide-y divide-gray-50 max-h-96 overflow-y-auto pr-1">
              {(!r.activities || r.activities.length === 0) && (
                <div className="text-center py-8">
                  <div className="text-3xl mb-2">💬</div>
                  <div className="text-sm text-gray-400">لا توجد أنشطة بعد</div>
                  <div className="text-xs text-gray-300 mt-1">سيظهر هنا كل تحديث وتواصل</div>
                </div>
              )}
              {r.activities?.map(activity => (
                <ActivityEntry key={activity.id} activity={activity} />
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Compose box */}
            <ChatterInput
              reservationId={r.id}
              onPosted={invalidate}
            />
          </div>

          {/* Notes */}
          {r.notes && (
            <div className="card">
              <h3 className="font-bold text-gray-700 mb-2 text-sm">ملاحظات الحجز</h3>
              <p className="text-gray-600 text-sm leading-relaxed">{r.notes}</p>
            </div>
          )}

          {/* Attached image */}
          {r.image_url && (
            <div className="card">
              <h3 className="font-bold text-gray-700 mb-3 text-sm">المرفقات</h3>
              <img
                src={r.image_url}
                alt="مرفق الحجز"
                className="rounded-xl max-h-64 border border-gray-200 object-contain w-full cursor-pointer hover:opacity-90"
                onClick={() => window.open(r.image_url, '_blank')}
              />
            </div>
          )}
        </div>

        {/* ── Right sidebar ─────────────────────────────────────────────── */}
        <div className="flex flex-col gap-4">

          {/* Customer */}
          <div className="card">
            <h3 className="font-bold text-gray-700 mb-3 text-xs uppercase tracking-wide text-gray-400">العميل</h3>
            <div className="text-base font-bold text-gray-900">{r.contact_name}</div>
            <div className="text-brand-600 font-mono text-sm mt-0.5" dir="ltr">{r.contact_phone}</div>
            {r.customer_name !== r.contact_name && (
              <div className="text-xs text-gray-400 mt-1">في النظام: {r.customer_name}</div>
            )}
            <button
              onClick={() => navigate(`/customers/${r.customer_id || r.customer}`)}
              className="text-brand-600 text-xs hover:underline mt-2 inline-flex items-center gap-1"
            >
              سجل العميل الكامل ←
            </button>
          </div>

          {/* Item */}
          <div className="card">
            <h3 className="font-bold text-gray-400 mb-3 text-xs uppercase tracking-wide">الصنف</h3>
            <div className="text-base font-bold text-gray-900 leading-tight">{r.item_name}</div>
            {r.item_scientific && (
              <div className="text-xs text-gray-400 italic mt-0.5">{r.item_scientific}</div>
            )}
            <div className="flex items-center gap-3 mt-2 text-sm">
              <span className="text-gray-600">الكمية: <strong className="text-gray-900">{r.quantity_requested}</strong></span>
            </div>
            {r.item_softech_id && (
              <div className="text-xs text-blue-500 font-mono mt-1">كود: {r.item_softech_id}</div>
            )}
          </div>

          {/* Stock by branch */}
          <div className="card">
            <h3 className="font-bold text-gray-400 mb-3 text-xs uppercase tracking-wide">المخزون بالفروع</h3>
            <StockWidget
              stockByBranch={r.stock_by_branch}
              currentBranchId={r.branch_id || r.branch}
            />
          </div>

          {/* Dates */}
          <div className="card">
            <h3 className="font-bold text-gray-400 mb-3 text-xs uppercase tracking-wide">التواريخ</h3>
            <div className="space-y-2.5">
              <div>
                <div className="text-xs text-gray-400">موعد الوصول المتوقع</div>
                <div className="text-sm font-medium text-gray-700">{formatDate(r.expected_arrival_date)}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">تاريخ المتابعة</div>
                <div className={`text-sm font-medium ${r.follow_up_date ? 'text-orange-600' : 'text-gray-700'}`}>
                  {formatDate(r.follow_up_date)}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-400">آخر تحديث</div>
                <div className="text-sm text-gray-500">{timeAgo(r.updated_at)}</div>
              </div>
            </div>
          </div>

          {/* Assignment */}
          {r.assigned_to_name && (
            <div className="card">
              <h3 className="font-bold text-gray-400 mb-2 text-xs uppercase tracking-wide">مسند إلى</h3>
              <div className="flex items-center gap-2">
                <InitialsAvatar name={r.assigned_to_name} />
                <span className="text-sm font-medium text-gray-700">{r.assigned_to_name}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
