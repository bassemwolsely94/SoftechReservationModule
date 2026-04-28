import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reservationsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Status config ─────────────────────────────────────────────────────────────
const COLUMNS = [
  { key: 'pending',   label: 'قيد الانتظار',     color: '#6b7280', bg: '#f9fafb', dot: '#9ca3af' },
  { key: 'available', label: 'المخزون متاح',       color: '#d97706', bg: '#fffbeb', dot: '#f59e0b' },
  { key: 'contacted', label: 'تم التواصل',          color: '#2563eb', bg: '#eff6ff', dot: '#3b82f6' },
  { key: 'confirmed', label: 'مؤكد — قادم',        color: '#7c3aed', bg: '#f5f3ff', dot: '#8b5cf6' },
  { key: 'fulfilled', label: 'تم التسليم',          color: '#059669', bg: '#ecfdf5', dot: '#10b981' },
  { key: 'cancelled', label: 'ملغي / منتهي',       color: '#dc2626', bg: '#fef2f2', dot: '#ef4444' },
]

const PRIORITY_BADGE = {
  normal:  { label: 'عادي',        cls: 'bg-gray-100 text-gray-600' },
  urgent:  { label: 'عاجل 🔴',     cls: 'bg-red-100 text-red-700' },
  chronic: { label: 'مزمن 💊',     cls: 'bg-purple-100 text-purple-700' },
}

const STATUS_TRANSITIONS = {
  pending:   ['available', 'cancelled'],
  available: ['contacted', 'cancelled'],
  contacted: ['confirmed', 'cancelled', 'expired'],
  confirmed: ['fulfilled', 'cancelled'],
  fulfilled: [],
  cancelled: [],
  expired:   [],
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function timeAgo(dt) {
  try { return formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }) }
  catch { return '' }
}

function formatDate(d) {
  if (!d) return '—'
  try { return format(new Date(d), 'dd/MM/yyyy') } catch { return d }
}

// ── Card component ────────────────────────────────────────────────────────────
function ReservationCard({ reservation, onStatusChange, onOpen, isCCOrAdmin }) {
  const col = COLUMNS.find(c => c.key === reservation.status) || COLUMNS[0]
  const pri = PRIORITY_BADGE[reservation.priority] || PRIORITY_BADGE.normal
  const transitions = STATUS_TRANSITIONS[reservation.status] || []

  return (
    <div
      className="bg-white rounded-xl shadow-sm border border-gray-100 p-3 cursor-pointer hover:shadow-md hover:border-gray-200 transition-all duration-150 select-none"
      onClick={() => onOpen(reservation)}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-gray-900 text-sm leading-tight truncate">
            {reservation.item_name}
          </div>
          {reservation.item_softech_id && (
            <div className="text-xs text-gray-400 font-mono mt-0.5">
              كود: {reservation.item_softech_id}
            </div>
          )}
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap flex-shrink-0 ${pri.cls}`}>
          {pri.label}
        </span>
      </div>

      {/* Customer */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-gray-400 text-xs">👤</span>
        <span className="text-xs text-gray-700 truncate">{reservation.customer_name}</span>
      </div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-gray-400 text-xs">📞</span>
        <span className="text-xs text-gray-600 font-mono" dir="ltr">{reservation.contact_phone}</span>
      </div>

      {/* Branch badge — shown for CC/admin */}
      {isCCOrAdmin && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="text-gray-400 text-xs">🏥</span>
          <span className="text-xs bg-brand-50 text-brand-700 px-1.5 py-0.5 rounded font-medium truncate">
            {reservation.branch_name}
          </span>
        </div>
      )}

      {/* Qty + image indicator */}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-50">
        <span className="text-xs text-gray-500">الكمية: <strong>{reservation.quantity_requested}</strong></span>
        <div className="flex items-center gap-2">
          {reservation.image_url && (
            <span className="text-gray-400 text-xs" title="يحتوي صورة">🖼️</span>
          )}
          <span className="text-xs text-gray-400">{timeAgo(reservation.created_at)}</span>
        </div>
      </div>

      {/* Quick status buttons */}
      {transitions.length > 0 && (
        <div className="flex gap-1 mt-2 flex-wrap" onClick={e => e.stopPropagation()}>
          {transitions.map(s => {
            const tc = COLUMNS.find(c => c.key === s)
            return (
              <button
                key={s}
                onClick={() => onStatusChange(reservation.id, s)}
                style={{ borderColor: tc?.dot, color: tc?.color }}
                className="text-xs border rounded px-2 py-0.5 hover:opacity-80 transition-opacity bg-white"
              >
                → {tc?.label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Column component ──────────────────────────────────────────────────────────
function KanbanColumn({ col, cards, onStatusChange, onOpen, isCCOrAdmin }) {
  return (
    <div className="flex flex-col" style={{ minWidth: 280, maxWidth: 320, flex: '0 0 290px' }}>
      {/* Column header */}
      <div
        className="flex items-center justify-between px-3 py-2.5 rounded-t-xl font-semibold text-sm sticky top-0 z-10"
        style={{ background: col.bg, color: col.color, borderBottom: `2px solid ${col.dot}` }}
      >
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: col.dot }} />
          {col.label}
        </div>
        <span
          className="text-xs font-bold px-2 py-0.5 rounded-full"
          style={{ background: col.dot + '22', color: col.color }}
        >
          {cards.length}
        </span>
      </div>

      {/* Cards */}
      <div
        className="flex flex-col gap-2 p-2 rounded-b-xl overflow-y-auto"
        style={{ background: col.bg + 'cc', minHeight: 100, maxHeight: 'calc(100vh - 220px)' }}
      >
        {cards.length === 0 && (
          <div className="text-center py-8 text-gray-300 text-xs select-none">لا توجد حجوزات</div>
        )}
        {cards.map(r => (
          <ReservationCard
            key={r.id}
            reservation={r}
            onStatusChange={onStatusChange}
            onOpen={onOpen}
            isCCOrAdmin={isCCOrAdmin}
          />
        ))}
      </div>
    </div>
  )
}

// ── Detail Modal ──────────────────────────────────────────────────────────────
function ReservationModal({ reservation, onClose, onStatusChange, onImageUpload }) {
  const [note, setNote] = useState('')
  const fileRef = useRef()
  if (!reservation) return null

  const transitions = STATUS_TRANSITIONS[reservation.status] || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">

        {/* Modal header */}
        <div className="flex items-center justify-between p-5 border-b">
          <div>
            <h2 className="text-lg font-bold text-gray-900">حجز #{reservation.id}</h2>
            <div className="text-xs text-gray-400 mt-0.5">
              أنشأه: {reservation.created_by_name} — {timeAgo(reservation.created_at)}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">✕</button>
        </div>

        <div className="p-5 space-y-5">

          {/* Item + Customer grid */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-gray-50 rounded-xl p-3">
              <div className="text-xs text-gray-400 mb-1">الصنف</div>
              <div className="font-semibold text-gray-900 text-sm">{reservation.item_name}</div>
              {reservation.item_scientific && (
                <div className="text-xs text-gray-500 italic">{reservation.item_scientific}</div>
              )}
              <div className="text-xs text-blue-500 font-mono mt-1">
                كود سوفتك: {reservation.item_softech_id || '—'}
              </div>
              <div className="text-xs text-gray-500 mt-1">الكمية: <strong>{reservation.quantity_requested}</strong></div>
            </div>
            <div className="bg-gray-50 rounded-xl p-3">
              <div className="text-xs text-gray-400 mb-1">العميل</div>
              <div className="font-semibold text-gray-900 text-sm">{reservation.customer_name}</div>
              <div className="text-xs text-gray-600 font-mono" dir="ltr">{reservation.contact_phone}</div>
              <div className="text-xs text-gray-500 mt-1">الفرع: <strong>{reservation.branch_name}</strong></div>
            </div>
          </div>

          {/* Status + Priority */}
          <div className="flex items-center gap-3 flex-wrap">
            {(() => {
              const col = COLUMNS.find(c => c.key === reservation.status)
              return (
                <span
                  className="text-sm font-semibold px-3 py-1 rounded-full"
                  style={{ background: col?.bg, color: col?.color, border: `1px solid ${col?.dot}` }}
                >
                  {col?.label}
                </span>
              )
            })()}
            <span className={`text-xs px-2 py-1 rounded-full font-medium ${PRIORITY_BADGE[reservation.priority]?.cls}`}>
              {PRIORITY_BADGE[reservation.priority]?.label}
            </span>
            {reservation.follow_up_date && (
              <span className="text-xs text-orange-600 bg-orange-50 px-2 py-1 rounded-full">
                متابعة: {formatDate(reservation.follow_up_date)}
              </span>
            )}
          </div>

          {/* Notes */}
          {reservation.notes && (
            <div className="bg-yellow-50 border border-yellow-100 rounded-xl p-3">
              <div className="text-xs text-yellow-700 font-medium mb-1">ملاحظات</div>
              <div className="text-sm text-gray-700">{reservation.notes}</div>
            </div>
          )}

          {/* Image */}
          {reservation.image_url && (
            <div>
              <div className="text-xs text-gray-400 mb-2">المرفقات</div>
              <img
                src={reservation.image_url}
                alt="مرفق الحجز"
                className="rounded-xl max-h-48 border object-contain w-full cursor-pointer"
                onClick={() => window.open(reservation.image_url, '_blank')}
              />
            </div>
          )}

          {/* Upload image */}
          <div>
            <input type="file" accept="image/*" ref={fileRef} className="hidden"
              onChange={e => onImageUpload(reservation.id, e.target.files[0])} />
            <button
              onClick={() => fileRef.current?.click()}
              className="text-xs text-blue-600 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-50 transition-colors"
            >
              📎 {reservation.image_url ? 'استبدال الصورة' : 'إرفاق صورة / روشتة'}
            </button>
          </div>

          {/* Status change */}
          {transitions.length > 0 && (
            <div>
              <div className="text-xs text-gray-400 mb-2">تغيير الحالة</div>
              <textarea
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="ملاحظة (اختياري)..."
                rows={2}
                className="w-full text-sm border border-gray-200 rounded-lg p-2 mb-2 resize-none focus:outline-none focus:border-blue-300"
              />
              <div className="flex gap-2 flex-wrap">
                {transitions.map(s => {
                  const tc = COLUMNS.find(c => c.key === s)
                  return (
                    <button
                      key={s}
                      onClick={() => { onStatusChange(reservation.id, s, note); onClose() }}
                      style={{ background: tc?.dot, color: 'white' }}
                      className="text-sm px-4 py-1.5 rounded-lg font-medium hover:opacity-90 transition-opacity"
                    >
                      {tc?.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* Status history */}
          {reservation.status_logs?.length > 0 && (
            <div>
              <div className="text-xs text-gray-400 mb-2">سجل التحديثات</div>
              <div className="space-y-2">
                {reservation.status_logs.map(log => {
                  const nc = COLUMNS.find(c => c.key === log.new_status)
                  return (
                    <div key={log.id} className="flex items-start gap-2 text-xs">
                      <span
                        className="mt-1 w-2 h-2 rounded-full flex-shrink-0"
                        style={{ background: nc?.dot || '#9ca3af' }}
                      />
                      <div>
                        <span className="font-medium text-gray-700">{log.new_status_label}</span>
                        <span className="text-gray-400 mx-1">—</span>
                        <span className="text-gray-500">{log.changed_by_name}</span>
                        {log.changed_by_username && (
                          <span className="text-gray-400 ml-1">({log.changed_by_username})</span>
                        )}
                        <span className="text-gray-400 mx-1">·</span>
                        <span className="text-gray-400">
                          {format(new Date(log.changed_at), 'dd/MM HH:mm')}
                        </span>
                        {log.note && <div className="text-gray-500 mt-0.5">"{log.note}"</div>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── New Reservation Modal ─────────────────────────────────────────────────────
function NewReservationModal({ onClose, onCreated, branches, userBranchId, isCCOrAdmin }) {
  const [form, setForm] = useState({
    customer_search: '', customer: '',
    item_search: '', item: '',
    branch: userBranchId || '',
    priority: 'normal', quantity_requested: 1,
    contact_phone: '', contact_name: '', notes: '',
    follow_up_date: '', expected_arrival_date: '',
  })
  const [customerResults, setCustomerResults] = useState([])
  const [itemResults, setItemResults] = useState([])
  const [image, setImage] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef()

  // Customer search
  useEffect(() => {
    if (form.customer_search.length < 2) { setCustomerResults([]); return }
    const t = setTimeout(async () => {
      try {
        const { default: api } = await import('../api/client')
        const res = await api.get('/customers/', { params: { search: form.customer_search, limit: 8 } })
        setCustomerResults(res.data.results || res.data)
      } catch { setCustomerResults([]) }
    }, 300)
    return () => clearTimeout(t)
  }, [form.customer_search])

  // Item search
  useEffect(() => {
    if (form.item_search.length < 2) { setItemResults([]); return }
    const t = setTimeout(async () => {
      try {
        const { default: api } = await import('../api/client')
        const res = await api.get('/items/', { params: { search: form.item_search, limit: 8 } })
        setItemResults(res.data.results || res.data)
      } catch { setItemResults([]) }
    }, 300)
    return () => clearTimeout(t)
  }, [form.item_search])

  const handleSubmit = async () => {
    if (!form.customer || !form.item || !form.branch || !form.contact_phone) {
      setError('يرجى تعبئة جميع الحقول المطلوبة'); return
    }
    setSubmitting(true); setError('')
    try {
      const fd = new FormData()
      Object.entries(form).forEach(([k, v]) => {
        if (!['customer_search','item_search'].includes(k) && v !== '') fd.append(k, v)
      })
      if (image) fd.append('image', image)
      const { default: api } = await import('../api/client')
      await api.post('/reservations/', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      onCreated()
      onClose()
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ، يرجى المحاولة مجدداً')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-bold text-gray-900">حجز جديد</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">✕</button>
        </div>
        <div className="p-5 space-y-4">

          {/* Customer search */}
          <div className="relative">
            <label className="text-xs text-gray-500 mb-1 block">العميل *</label>
            <input
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
              placeholder="ابحث باسم العميل أو الهاتف..."
              value={form.customer_search}
              onChange={e => setForm(f => ({ ...f, customer_search: e.target.value, customer: '' }))}
            />
            {form.customer && <div className="text-xs text-green-600 mt-1">✓ تم الاختيار</div>}
            {customerResults.length > 0 && !form.customer && (
              <div className="absolute z-20 w-full bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto">
                {customerResults.map(c => (
                  <div
                    key={c.id}
                    className="px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                    onClick={() => {
                      setForm(f => ({ ...f, customer: c.id, customer_search: c.name, contact_phone: c.phone || f.contact_phone, contact_name: c.name }))
                      setCustomerResults([])
                    }}
                  >
                    <div className="font-medium">{c.name}</div>
                    <div className="text-xs text-gray-400" dir="ltr">{c.phone}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Item search */}
          <div className="relative">
            <label className="text-xs text-gray-500 mb-1 block">الصنف *</label>
            <input
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
              placeholder="ابحث باسم الدواء أو الكود..."
              value={form.item_search}
              onChange={e => setForm(f => ({ ...f, item_search: e.target.value, item: '' }))}
            />
            {form.item && <div className="text-xs text-green-600 mt-1">✓ تم الاختيار</div>}
            {itemResults.length > 0 && !form.item && (
              <div className="absolute z-20 w-full bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto">
                {itemResults.map(it => (
                  <div
                    key={it.id}
                    className="px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                    onClick={() => {
                      setForm(f => ({ ...f, item: it.id, item_search: it.name }))
                      setItemResults([])
                    }}
                  >
                    <div className="font-medium">{it.name}</div>
                    <div className="text-xs text-gray-400 font-mono">كود: {it.softech_id}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Branch (CC/admin only can choose) */}
          {isCCOrAdmin && (
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الفرع *</label>
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.branch}
                onChange={e => setForm(f => ({ ...f, branch: e.target.value }))}
              >
                <option value="">اختر الفرع</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
              </select>
            </div>
          )}

          {/* Contact fields */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">اسم التواصل *</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.contact_name} onChange={e => setForm(f => ({ ...f, contact_name: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">هاتف التواصل *</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                dir="ltr" value={form.contact_phone} onChange={e => setForm(f => ({ ...f, contact_phone: e.target.value }))} />
            </div>
          </div>

          {/* Priority + Qty */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الأولوية</label>
              <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
                <option value="normal">عادي</option>
                <option value="urgent">عاجل</option>
                <option value="chronic">مريض مزمن</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الكمية</label>
              <input type="number" min="1" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.quantity_requested} onChange={e => setForm(f => ({ ...f, quantity_requested: e.target.value }))} />
            </div>
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">تاريخ المتابعة</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.follow_up_date} onChange={e => setForm(f => ({ ...f, follow_up_date: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">موعد الوصول المتوقع</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.expected_arrival_date} onChange={e => setForm(f => ({ ...f, expected_arrival_date: e.target.value }))} />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="text-xs text-gray-500 mb-1 block">ملاحظات</label>
            <textarea rows={2} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300 resize-none"
              value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
          </div>

          {/* Image */}
          <div>
            <input type="file" accept="image/*" ref={fileRef} className="hidden" onChange={e => setImage(e.target.files[0])} />
            <button onClick={() => fileRef.current?.click()}
              className="text-xs text-blue-600 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-50 transition-colors">
              📎 {image ? `✓ ${image.name}` : 'إرفاق صورة / روشتة (اختياري)'}
            </button>
          </div>

          {error && <div className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</div>}

          <div className="flex gap-2 pt-1">
            <button onClick={handleSubmit} disabled={submitting}
              className="flex-1 bg-brand-600 text-white rounded-lg py-2.5 text-sm font-semibold hover:bg-brand-700 disabled:opacity-50 transition-colors">
              {submitting ? 'جاري الحفظ...' : 'إنشاء الحجز'}
            </button>
            <button onClick={onClose} className="px-4 py-2.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors">
              إلغاء
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Kanban Page ──────────────────────────────────────────────────────────
export default function ReservationsKanban() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const isCCOrAdmin = user?.role === 'admin' || user?.role === 'call_center'

  const [filterBranch, setFilterBranch] = useState('')
  const [filterPriority, setFilterPriority] = useState('')
  const [search, setSearch] = useState('')
  const [openModal, setOpenModal] = useState(null)   // reservation object
  const [showNew, setShowNew] = useState(false)
  const [detailData, setDetailData] = useState(null)

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data),
  })

  const { data: rawList = [], isLoading } = useQuery({
    queryKey: ['reservations-kanban', filterBranch, filterPriority, search],
    queryFn: () => reservationsApi.list({
      branch: filterBranch || undefined,
      priority: filterPriority || undefined,
      search: search || undefined,
      page_size: 200,
    }).then(r => r.data.results || r.data),
    refetchInterval: 30_000,
  })

  // Status change mutation
  const changeMutation = useMutation({
    mutationFn: ({ id, status, note }) => reservationsApi.changeStatus(id, status, note || ''),
    onSuccess: () => {
      qc.invalidateQueries(['reservations-kanban'])
      if (detailData) {
        reservationsApi.get(detailData.id).then(r => setDetailData(r.data))
      }
    },
  })

  // Image upload mutation
  const imageMutation = useMutation({
    mutationFn: async ({ id, file }) => {
      const fd = new FormData(); fd.append('image', file)
      const { default: api } = await import('../api/client')
      return api.patch(`/reservations/${id}/`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    },
    onSuccess: () => qc.invalidateQueries(['reservations-kanban']),
  })

  // Open detail: fetch full data
  const openDetail = async (r) => {
    try {
      const res = await reservationsApi.get(r.id)
      setDetailData(res.data)
      setOpenModal(r)
    } catch { setOpenModal(r); setDetailData(r) }
  }

  // Group by status, applying filters
  const grouped = COLUMNS.reduce((acc, col) => {
    acc[col.key] = rawList.filter(r => {
      if (r.status !== col.key) return false
      if (!isCCOrAdmin && r.branch_id !== user?.branch_id) return false
      return true
    })
    return acc
  }, {})

  // Merged cancelled + expired
  grouped.cancelled = [
    ...(rawList.filter(r => r.status === 'cancelled')),
    ...(rawList.filter(r => r.status === 'expired')),
  ]

  const totalActive = rawList.filter(r => !['fulfilled','cancelled','expired'].includes(r.status)).length

  return (
    <div className="flex flex-col h-full" dir="rtl">

      {/* Top bar */}
      <div className="flex items-center gap-3 px-5 py-3 bg-white border-b flex-wrap">
        <div>
          <h1 className="text-lg font-bold text-gray-900">لوحة الحجوزات</h1>
          <p className="text-xs text-gray-400">{totalActive} حجز نشط</p>
        </div>

        <div className="flex-1" />

        {/* Search */}
        <input
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-48 focus:outline-none focus:border-blue-300"
          placeholder="بحث..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />

        {/* Branch filter (CC/admin only) */}
        {isCCOrAdmin && (
          <select
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
            value={filterBranch}
            onChange={e => setFilterBranch(e.target.value)}
          >
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
        )}

        {/* Priority filter */}
        <select
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
          value={filterPriority}
          onChange={e => setFilterPriority(e.target.value)}
        >
          <option value="">كل الأولويات</option>
          <option value="urgent">عاجل</option>
          <option value="chronic">مزمن</option>
          <option value="normal">عادي</option>
        </select>

        <button
          onClick={() => setShowNew(true)}
          className="bg-brand-600 text-white px-4 py-1.5 rounded-lg text-sm font-semibold hover:bg-brand-700 transition-colors whitespace-nowrap"
        >
          + حجز جديد
        </button>
      </div>

      {/* Kanban board */}
      <div className="flex-1 overflow-x-auto">
        <div className="flex gap-3 p-4 h-full" style={{ width: 'max-content', minWidth: '100%' }}>
          {isLoading ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
              جاري التحميل...
            </div>
          ) : (
            COLUMNS.map(col => (
              <KanbanColumn
                key={col.key}
                col={col}
                cards={grouped[col.key] || []}
                onStatusChange={(id, status, note) => changeMutation.mutate({ id, status, note })}
                onOpen={openDetail}
                isCCOrAdmin={isCCOrAdmin}
              />
            ))
          )}
        </div>
      </div>

      {/* Detail modal */}
      {openModal && (
        <ReservationModal
          reservation={detailData || openModal}
          onClose={() => { setOpenModal(null); setDetailData(null) }}
          onStatusChange={(id, status, note) => changeMutation.mutate({ id, status, note })}
          onImageUpload={(id, file) => imageMutation.mutate({ id, file })}
        />
      )}

      {/* New reservation modal */}
      {showNew && (
        <NewReservationModal
          onClose={() => setShowNew(false)}
          onCreated={() => qc.invalidateQueries(['reservations-kanban'])}
          branches={branches}
          userBranchId={user?.branch_id}
          isCCOrAdmin={isCCOrAdmin}
        />
      )}
    </div>
  )
}
