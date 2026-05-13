/**
 * DemandDetailPage.jsx  —  /demand/:id
 * Odoo-style 4-tab layout:
 *   📋 Details | 💊 Items | 🔔 Follow-ups | 💬 Logs
 */
import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { demandApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Tokens ────────────────────────────────────────────────────────────────────
const BRAND  = '#1B6B3A'
const GREEN  = '#10b981'
const BLUE   = '#3b82f6'
const ORANGE = '#f59e0b'
const RED    = '#ef4444'
const PURPLE = '#8b5cf6'
const GRAY   = '#9ca3af'

const STATUS_CFG = {
  new:       { label: 'جديد',           dot: ORANGE, bg: '#fffbeb', text: '#92400e', border: '#fde68a' },
  assigned:  { label: 'مُعيَّن',        dot: BLUE,   bg: '#eff6ff', text: '#1e40af', border: '#bfdbfe' },
  follow_up: { label: 'متابعة',         dot: PURPLE, bg: '#f5f3ff', text: '#5b21b6', border: '#ddd6fe' },
  contacted: { label: 'تم التواصل',     dot: BRAND,  bg: '#f0f9f4', text: '#1B6B3A', border: '#bbf7d0' },
  waiting:   { label: 'ينتظر المخزون', dot: GRAY,   bg: '#f9fafb', text: '#6b7280', border: '#e5e7eb' },
  fulfilled: { label: 'تم التوريد',     dot: GREEN,  bg: '#f0fdf4', text: '#166534', border: '#bbf7d0' },
  lost:      { label: 'بيع ضائع',      dot: RED,    bg: '#fef2f2', text: '#991b1b', border: '#fecaca' },
  cancelled: { label: 'ملغي',          dot: GRAY,   bg: '#f9fafb', text: '#9ca3af', border: '#e5e7eb' },
}

const PRIORITY_CFG = {
  low:     { label: 'منخفض',    cls: 'bg-gray-100 text-gray-500' },
  normal:  { label: 'عادي',     cls: 'bg-blue-100 text-blue-700' },
  high:    { label: 'عالٍ',     cls: 'bg-orange-100 text-orange-700' },
  urgent:  { label: 'عاجل 🔴', cls: 'bg-red-100 text-red-700' },
  chronic: { label: 'مزمن 💊', cls: 'bg-purple-100 text-purple-700' },
}

const LOST_REASONS = [
  { value: 'no_stock',     label: 'لا يوجد مخزون' },
  { value: 'delayed',      label: 'تأخر — اشترى من مكان آخر' },
  { value: 'discontinued', label: 'متوقف — غير متاح' },
  { value: 'no_response',  label: 'لا يوجد رد من العميل' },
  { value: 'price',        label: 'رفض السعر' },
  { value: 'other',        label: 'أخرى' },
]

const LOG_TYPE_OPTIONS = [
  { value: 'note',      label: '📝 ملاحظة' },
  { value: 'call',      label: '📞 سجل اتصال' },
  { value: 'whatsapp',  label: '💬 واتساب' },
]

const FOLLOW_UP_TYPES = [
  { value: 'call',        label: '📞 اتصال هاتفي' },
  { value: 'whatsapp',    label: '💬 واتساب' },
  { value: 'visit',       label: '🏥 زيارة للفرع' },
  { value: 'stock_check', label: '📦 مراجعة المخزون' },
  { value: 'other',       label: '📝 أخرى' },
]

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

// ── SLA Timer (live countdown) ────────────────────────────────────────────────

function SlaTimer({ demand }) {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(t)
  }, [])

  const deadline =
    demand.status === 'new'      ? demand.sla_assigned_due :
    demand.status === 'assigned' ? demand.sla_contacted_due :
    demand.is_active             ? demand.sla_resolved_due : null

  if (!deadline) return null

  const diffMs = new Date(deadline) - now
  const breached = diffMs < 0
  const mins = Math.abs(Math.floor(diffMs / 60000))
  const hrs  = Math.floor(mins / 60)
  const m    = mins % 60
  const label = hrs > 0 ? `${hrs}س ${m}د` : `${m}د`

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold"
      style={{
        background: breached ? '#fef2f2' : mins < 10 ? '#fffbeb' : '#f0fdf4',
        color:      breached ? RED       : mins < 10 ? ORANGE   : GREEN,
        border: `1px solid ${breached ? '#fecaca' : mins < 10 ? '#fde68a' : '#bbf7d0'}`,
      }}
    >
      {breached ? '⚠ SLA تجاوز' : '⏱ SLA'}&nbsp;
      {breached ? `منذ ${label}` : `متبقي ${label}`}
    </div>
  )
}

// ── Tab ───────────────────────────────────────────────────────────────────────

function Tab({ icon, label, active, onClick, count }) {
  return (
    <button onClick={onClick}
      className={`flex items-center gap-2 px-4 py-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
        active ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500 hover:text-gray-700'
      }`}>
      <span>{icon}</span>{label}
      {count !== undefined && (
        <span className={`badge text-xs ${active ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-400'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

// ── Action Buttons ────────────────────────────────────────────────────────────

function ActionBar({ demand, onAction, loading }) {
  const [lostForm, setLostForm]     = useState(false)
  const [lostReason, setLostReason] = useState('')
  const [lostNotes, setLostNotes]   = useState('')
  const [noteInput, setNoteInput]   = useState('')
  const [showNote, setShowNote]     = useState(false)
  const [erpInput, setErpInput]     = useState('')
  const [showERP, setShowERP]       = useState(false)

  const btn = (label, action, payload, color, icon) => (
    <button
      disabled={loading}
      onClick={() => onAction(action, payload)}
      className={`text-sm px-4 py-2 rounded-lg font-semibold text-white transition-colors disabled:opacity-50 flex items-center gap-1.5`}
      style={{ background: color }}>
      {icon} {label}
    </button>
  )

  return (
    <div className="flex items-center gap-2 flex-wrap">

      {/* Assign — new only, admin/CC */}
      {demand.can_assign && btn('تعيين', 'assign', {}, BLUE, '👤')}

      {/* Contact */}
      {demand.can_contact && !showNote && (
        <button disabled={loading} onClick={() => setShowNote(true)}
          className="text-sm px-4 py-2 rounded-lg font-semibold text-white transition-colors"
          style={{ background: BRAND }}>
          📞 تواصلت مع العميل
        </button>
      )}
      {showNote && (
        <div className="flex items-center gap-2 bg-brand-50 border border-brand-200 rounded-xl px-3 py-2">
          <input className="border border-brand-300 rounded-lg px-2 py-1 text-xs w-48 focus:outline-none"
            placeholder="ملاحظة التواصل..."
            value={noteInput} onChange={e => setNoteInput(e.target.value)} autoFocus />
          <button onClick={() => { onAction('contact', { note: noteInput }); setShowNote(false) }}
            className="text-xs text-white px-2 py-1 rounded-lg" style={{ background: BRAND }}>
            تأكيد
          </button>
          <button onClick={() => setShowNote(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* Wait for stock */}
      {['new', 'assigned', 'contacted'].includes(demand.status) &&
        btn('ينتظر المخزون', 'wait', {}, GRAY, '⏳')}

      {/* Fulfill */}
      {demand.can_fulfill && !showERP && (
        <button disabled={loading} onClick={() => setShowERP(true)}
          className="text-sm px-4 py-2 rounded-lg font-semibold text-white"
          style={{ background: GREEN }}>
          ✅ تم التوريد
        </button>
      )}
      {showERP && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-xl px-3 py-2">
          <input className="border border-green-300 rounded-lg px-2 py-1 text-xs w-36 focus:outline-none font-mono"
            placeholder="رقم الفاتورة (اختياري)" dir="ltr"
            value={erpInput} onChange={e => setErpInput(e.target.value)} />
          <button onClick={() => { onAction('fulfill', { erp_invoice_id: erpInput }); setShowERP(false) }}
            className="text-xs text-white px-2 py-1 rounded-lg" style={{ background: GREEN }}>
            تأكيد
          </button>
          <button onClick={() => setShowERP(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* Lost */}
      {demand.can_mark_lost && !lostForm && (
        <button onClick={() => setLostForm(true)}
          className="text-sm px-4 py-2 rounded-lg font-semibold text-white" style={{ background: RED }}>
          ❌ بيع ضائع
        </button>
      )}
      {lostForm && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2 flex-wrap">
          <select className="border border-red-300 rounded-lg px-2 py-1 text-xs focus:outline-none"
            value={lostReason} onChange={e => setLostReason(e.target.value)}>
            <option value="">اختر السبب *</option>
            {LOST_REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <input className="border border-red-300 rounded-lg px-2 py-1 text-xs w-36 focus:outline-none"
            placeholder="تفاصيل إضافية..."
            value={lostNotes} onChange={e => setLostNotes(e.target.value)} />
          <button
            disabled={!lostReason}
            onClick={() => {
              onAction('markLost', { lost_reason: lostReason, lost_notes: lostNotes })
              setLostForm(false)
            }}
            className="text-xs text-white px-2 py-1 rounded-lg disabled:opacity-50" style={{ background: RED }}>
            تأكيد
          </button>
          <button onClick={() => setLostForm(false)} className="text-xs text-gray-400">إلغاء</button>
        </div>
      )}

      {/* ERP lookup */}
      {!demand.erp_lookup_done && (
        <button onClick={() => onAction('erpLookup', {})}
          className="btn-secondary text-xs">
          🔗 بحث في ERP
        </button>
      )}

      {/* Cancel */}
      {demand.can_cancel && (
        <button onClick={() => { if (window.confirm('إلغاء الطلب؟')) onAction('cancel', {}) }}
          className="btn-ghost text-xs text-gray-400 hover:text-red-500">
          إلغاء الطلب
        </button>
      )}
    </div>
  )
}

// ── Tab 1: Details ────────────────────────────────────────────────────────────

function DetailsTab({ demand }) {
  const s = STATUS_CFG[demand.status] || STATUS_CFG.new
  const p = PRIORITY_CFG[demand.priority] || PRIORITY_CFG.normal

  return (
    <div className="grid sm:grid-cols-2 gap-6">
      {/* Customer */}
      <div>
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">بيانات العميل</div>
        <div className="space-y-2 bg-blue-50 border border-blue-100 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-blue-600">الهاتف</span>
            <span className="font-mono font-bold text-gray-800" dir="ltr">{demand.contact_phone}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-blue-600">الاسم</span>
            <span className="font-semibold text-gray-800">{demand.contact_name || '—'}</span>
          </div>
          {demand.phcode && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-blue-600">كود PIC</span>
              <span className="font-mono text-sm text-blue-700 bg-blue-100 px-2 py-0.5 rounded">
                {demand.phcode}
              </span>
            </div>
          )}
          {demand.erp_branch_code && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-blue-600">فرع ERP</span>
              <span className="font-mono text-xs text-gray-600">{demand.erp_branch_code}</span>
            </div>
          )}
          <div className="flex items-center justify-between pt-1 border-t border-blue-200">
            <span className="text-xs text-blue-600">ربط ERP</span>
            <span className={`text-xs font-semibold ${demand.erp_lookup_done ? 'text-green-600' : 'text-orange-600'}`}>
              {demand.erp_lookup_done ? '✓ تم البحث' : '⏳ لم يتم البحث بعد'}
            </span>
          </div>
          {demand.customer_name && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-blue-600">العميل المرتبط</span>
              <span className="text-xs font-semibold text-brand-700">{demand.customer_name}</span>
            </div>
          )}
        </div>
      </div>

      {/* Request info */}
      <div>
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">تفاصيل الطلب</div>
        <div className="space-y-2">
          <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span className="text-xs text-gray-400">الفرع</span>
            <span className="font-semibold text-gray-700 text-sm">{demand.branch_name}</span>
          </div>
          <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span className="text-xs text-gray-400">الحالة</span>
            <span className="badge text-xs px-2.5 py-1"
              style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
              {s.label}
            </span>
          </div>
          <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span className="text-xs text-gray-400">الأولوية</span>
            <span className={`badge text-xs ${p.cls}`}>{p.label}</span>
          </div>
          <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span className="text-xs text-gray-400">مصدر الطلب</span>
            <span className="text-xs text-gray-600">{demand.source_channel}</span>
          </div>
          <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span className="text-xs text-gray-400">أنشئ بواسطة</span>
            <span className="text-xs text-gray-700">{demand.created_by_name}</span>
          </div>
          {demand.assigned_name && (
            <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
              <span className="text-xs text-gray-400">مُعيَّن لـ</span>
              <span className="text-xs font-semibold text-brand-700">{demand.assigned_name}</span>
            </div>
          )}
          <div className="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span className="text-xs text-gray-400">تاريخ الطلب</span>
            <span className="text-xs text-gray-600">{fmtDate(demand.created_at)}</span>
          </div>
        </div>
      </div>

      {/* Notes */}
      {demand.notes && (
        <div className="sm:col-span-2">
          <div className="bg-yellow-50 border border-yellow-100 rounded-xl p-3">
            <div className="text-xs text-yellow-700 font-bold mb-1">ملاحظات</div>
            <p className="text-sm text-gray-700 leading-relaxed">{demand.notes}</p>
          </div>
        </div>
      )}

      {/* Lost sale info */}
      {demand.status === 'lost' && (
        <div className="sm:col-span-2">
          <div className="bg-red-50 border border-red-200 rounded-xl p-4">
            <div className="text-xs text-red-700 font-black mb-3 flex items-center gap-2">
              ❌ تفاصيل البيع الضائع
              {demand.lost_value_egp && (
                <span className="font-mono text-sm text-red-800">
                  — قيمة مقدرة: {parseFloat(demand.lost_value_egp).toLocaleString('ar-EG')} ج.م
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-xs text-red-500 mb-1">السبب</div>
                <div className="font-semibold text-red-800 text-sm">
                  {LOST_REASONS.find(r => r.value === demand.lost_reason)?.label || demand.lost_reason}
                </div>
              </div>
              {demand.lost_notes && (
                <div>
                  <div className="text-xs text-red-500 mb-1">تفاصيل</div>
                  <div className="text-sm text-red-700">{demand.lost_notes}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SLA deadlines */}
      <div className="sm:col-span-2 border-t border-gray-100 pt-4">
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">مسار SLA</div>
        <div className="flex items-center gap-0 overflow-x-auto">
          {[
            { label: 'إنشاء',      at: demand.created_at,   done: true },
            { label: 'تعيين',      at: demand.assigned_at,  done: !!demand.assigned_at,  deadline: demand.sla_assigned_due },
            { label: 'تواصل',      at: demand.contacted_at, done: !!demand.contacted_at, deadline: demand.sla_contacted_due },
            { label: 'حل',         at: demand.fulfilled_at, done: !!demand.fulfilled_at, deadline: demand.sla_resolved_due },
          ].map((step, i, arr) => (
            <div key={i} className="flex items-center">
              <div className="flex flex-col items-center min-w-20 text-center">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                  step.done ? 'text-white' : 'bg-gray-100 text-gray-400'
                }`} style={step.done ? { background: BRAND } : {}}>
                  {step.done ? '✓' : i + 1}
                </div>
                <div className={`text-xs mt-1 font-medium ${step.done ? 'text-brand-700' : 'text-gray-400'}`}>
                  {step.label}
                </div>
                {step.at && (
                  <div className="text-xs text-gray-400 mt-0.5">
                    {format(new Date(step.at), 'HH:mm', { locale: ar })}
                  </div>
                )}
                {!step.done && step.deadline && (
                  <div className="text-xs text-orange-500 mt-0.5">
                    حد: {format(new Date(step.deadline), 'HH:mm', { locale: ar })}
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

function ItemSearch({ onSelect }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)


  const [debouncedQ, setDebouncedQ] = useState('')

useEffect(() => {
  const delay = setTimeout(() => {
    setDebouncedQ(q)
  }, 300)

  return () => clearTimeout(delay)
}, [q])


  const ref = useRef()

  const { data: results } = useQuery({
    queryKey: ['item-search-detail', debouncedQ],
queryFn: () => itemsApi.list({ search: debouncedQ, page_size: 10 }).then(r => r.data.results || r.data),
enabled: debouncedQ.length >= 2, staleTime: 10_000,
  })

  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
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

function ItemsTab({ demand, onRefresh }) {
  const [adding, setAdding] = useState(false)
  const [selItem, setSelItem] = useState(null)
  const [qty, setQty] = useState('1')
  const [itemNotes, setItemNotes] = useState('')
  const [err, setErr] = useState('')

  async function addItem() {
    if (!selItem || !qty || Number(qty) <= 0) { setErr('اختر صنفاً وأدخل كمية صحيحة'); return }
    setErr('')
    try {
      await demandApi.addItem(demand.id, { item: selItem.id, quantity: qty, notes: itemNotes })
      setAdding(false); setSelItem(null); setQty('1'); setItemNotes('')
      onRefresh()
    } catch (e) {
      const d = e.response?.data
      setErr(typeof d === 'object' ? Object.values(d).flat().join(' ') : 'حدث خطأ')
    }
  }

  const isEditable = ['new', 'assigned', 'follow_up'].includes(demand.status)

  return (
    <div>
      {demand.items.length === 0 ? (
        <div className="text-center py-10 text-gray-400">
          <div className="text-4xl mb-2">💊</div>
          <div className="text-sm">لا توجد أصناف مسجلة</div>
        </div>
      ) : (
        <table className="w-full text-sm mb-5">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الصنف</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الكمية</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">التصنيف</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">المخزون الحالي</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">وقت التسجيل</th>
              <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الحالة</th>
              {isEditable && <th className="pb-2 px-2" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {demand.items.map(line => {
              const typeColors = {
                out_of_stock: { bg: '#fef2f2', text: RED,    label: 'نفد' },
                low_stock:    { bg: '#fffbeb', text: ORANGE, label: 'منخفض' },
                new_item:     { bg: '#f0f9f4', text: BRAND,  label: 'جديد' },
                unknown:      { bg: '#f9fafb', text: GRAY,   label: 'غير محدد' },
              }[line.item_type] || { bg: '#f9fafb', text: GRAY, label: '—' }

              return (
                <tr key={line.id} className="hover:bg-gray-50">
                  <td className="py-3 px-2">
                    <div className="font-semibold text-gray-800 text-sm">{line.item_name}</div>
                    <div className="text-xs text-gray-400 font-mono">{line.item_softech_id}</div>
                    {line.item_scientific && (
                      <div className="text-xs text-gray-400 italic">{line.item_scientific}</div>
                    )}
                    {line.is_long_shortage && (
                      <span className="text-xs bg-orange-100 text-orange-600 px-1 rounded mt-0.5 inline-block">
                        نقص طويل الأمد
                      </span>
                    )}
                    {line.is_discontinued && (
                      <span className="text-xs bg-red-100 text-red-600 px-1 rounded mt-0.5 inline-block">
                        متوقف
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-2 font-bold tabular-nums">{line.quantity}</td>
                  <td className="py-3 px-2">
                    <span className="badge text-xs px-2 py-0.5"
                      style={{ background: typeColors.bg, color: typeColors.text }}>
                      {typeColors.label}
                    </span>
                  </td>
                  <td className="py-3 px-2">
                    <span className={`font-bold tabular-nums text-sm ${
                      line.current_stock > 10 ? 'text-green-700'
                      : line.current_stock > 0 ? 'text-orange-600'
                      : 'text-red-500'
                    }`}>
                      {line.current_stock > 0 ? `${line.current_stock} وحدة` : 'نفد'}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-xs text-gray-500 tabular-nums">
                    {line.stock_at_capture != null ? `${line.stock_at_capture} وحدة` : '—'}
                  </td>
                  <td className="py-3 px-2">
                    {line.is_fulfilled ? (
                      <span className="badge bg-green-100 text-green-700">✓ وُرِّد</span>
                    ) : (
                      <span className="badge bg-gray-100 text-gray-500">لم يُورَّد</span>
                    )}
                  </td>
                  {isEditable && (
                    <td className="py-3 px-2">
                      <button onClick={async () => {
                        await demandApi.removeItem(demand.id, line.id)
                        onRefresh()
                      }} className="text-gray-300 hover:text-red-400 text-lg leading-none">✕</button>
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {isEditable && !adding && (
        <button onClick={() => setAdding(true)} className="btn-secondary text-sm">
          + إضافة صنف
        </button>
      )}

      {adding && (
        <div className="bg-brand-50 border border-brand-200 rounded-xl p-4 space-y-3 mt-2">
          <div className="text-xs font-bold text-brand-700">إضافة صنف</div>
          <ItemSearch onSelect={setSelItem} />
          {selItem && (
            <div className="text-xs text-brand-600 bg-white border border-brand-200 rounded-lg px-2 py-1">
              ✓ {selItem.name} ({selItem.softech_id})
            </div>
          )}
          <div className="flex gap-2">
            <input type="number" min="0.001" placeholder="الكمية"
              value={qty} onChange={e => setQty(e.target.value)}
              className="input-field w-24 text-sm" />
            <input placeholder="ملاحظة" value={itemNotes} onChange={e => setItemNotes(e.target.value)}
              className="input-field flex-1 text-sm" />
          </div>
          {err && <div className="text-xs text-red-600">{err}</div>}
          <div className="flex gap-2">
            <button onClick={addItem} className="btn-primary text-xs px-3">إضافة</button>
            <button onClick={() => { setAdding(false); setSelItem(null); setErr('') }}
              className="btn-secondary text-xs px-3">إلغاء</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tab 3: Follow-ups ─────────────────────────────────────────────────────────

function FollowUpsTab({ demand, onRefresh }) {
  const [showAdd, setShowAdd] = useState(false)
  const [fuType, setFuType]   = useState('call')
  const [fuDate, setFuDate]   = useState('')
  const [fuNotes, setFuNotes] = useState('')

  async function addFollowUp() {
    if (!fuDate) return
    try {
      await demandApi.addFollowUp(demand.id, {
        follow_up_type: fuType,
        due_date: fuDate,
        notes: fuNotes,
      })
      setShowAdd(false); setFuDate(''); setFuNotes(''); setFuType('call')
      onRefresh()
    } catch { }
  }

  async function complete(fuId) {
    const notes = prompt('ملاحظات إتمام المتابعة:')
    if (notes === null) return
    try {
      await demandApi.completeFollowUp(demand.id, fuId, notes || 'تم')
      onRefresh()
    } catch { }
  }

  const followUps = demand.follow_ups || []
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div>
      {followUps.length === 0 ? (
        <div className="text-center py-8 text-gray-400">
          <div className="text-3xl mb-2">🔔</div>
          <div className="text-sm">لا توجد مهام متابعة</div>
        </div>
      ) : (
        <div className="space-y-2 mb-4">
          {followUps.map(fu => {
            const isOverdue = fu.is_overdue
            const isDone    = fu.status === 'done'
            return (
              <div key={fu.id}
                className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
                  isDone    ? 'bg-green-50 border-green-100 opacity-70' :
                  isOverdue ? 'bg-red-50 border-red-200' :
                  'bg-white border-gray-200'
                }`}>
                <div className="text-xl shrink-0">
                  {fu.follow_up_type === 'call'        ? '📞'
                   : fu.follow_up_type === 'whatsapp'  ? '💬'
                   : fu.follow_up_type === 'visit'     ? '🏥'
                   : fu.follow_up_type === 'stock_check' ? '📦' : '📝'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-gray-800 text-sm">
                      {fu.follow_up_type_label}
                    </span>
                    {isOverdue && !isDone && (
                      <span className="badge bg-red-100 text-red-700 text-xs">⚠ فائت</span>
                    )}
                    {isDone && (
                      <span className="badge bg-green-100 text-green-700 text-xs">✓ تم</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    تاريخ الاستحقاق: {fu.due_date}
                    {fu.assigned_to_name && <span className="mr-2">· مُعيَّن لـ {fu.assigned_to_name}</span>}
                  </div>
                  {fu.notes && (
                    <div className="text-xs text-gray-600 mt-1 bg-gray-50 rounded px-2 py-1">
                      {fu.notes}
                    </div>
                  )}
                  {isDone && fu.completed_at && (
                    <div className="text-xs text-green-600 mt-1">
                      أُكملت {timeAgo(fu.completed_at)}
                    </div>
                  )}
                </div>
                {!isDone && (
                  <button onClick={() => complete(fu.id)}
                    className="text-xs bg-green-600 text-white px-2 py-1 rounded-lg hover:bg-green-700 shrink-0">
                    ✓ أكملت
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {!showAdd ? (
        <button onClick={() => setShowAdd(true)} className="btn-secondary text-sm">
          + إضافة متابعة
        </button>
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
          <div className="text-xs font-bold text-gray-600">جدولة متابعة جديدة</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label text-xs">نوع المتابعة</label>
              <select className="input-field" value={fuType} onChange={e => setFuType(e.target.value)}>
                {FOLLOW_UP_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label text-xs">تاريخ الاستحقاق</label>
              <input type="date" className="input-field" min={today}
                value={fuDate} onChange={e => setFuDate(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="label text-xs">ملاحظات</label>
            <input className="input-field text-sm" placeholder="تفاصيل المتابعة..."
              value={fuNotes} onChange={e => setFuNotes(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <button onClick={addFollowUp} disabled={!fuDate}
              className="btn-primary text-xs px-3 disabled:opacity-50">جدولة</button>
            <button onClick={() => setShowAdd(false)} className="btn-secondary text-xs px-3">إلغاء</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tab 4: Logs / Chatter ─────────────────────────────────────────────────────

function LogsTab({ demand, onRefresh }) {
  const [logType, setLogType] = useState('note')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const chatEndRef = useRef()

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [demand.logs?.length])

  async function send() {
    if (!message.trim()) return
    setSending(true)
    try {
      await demandApi.addLog(demand.id, { log_type: logType, message })
      setMessage('')
      onRefresh()
    } catch { } finally { setSending(false) }
  }

  const logs = demand.logs || []

  const LOG_ICONS = {
    note:          '📝',
    call:          '📞',
    whatsapp:      '💬',
    system:        '⚙️',
    status_change: '🔄',
    assignment:    '👤',
    erp_match:     '🔗',
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="max-h-96 overflow-y-auto space-y-0 divide-y divide-gray-50">
        {logs.length === 0 && (
          <div className="text-center py-10 text-gray-400">
            <div className="text-3xl mb-2">💬</div>
            <div className="text-sm">لا توجد سجلات بعد</div>
          </div>
        )}
        {logs.map(log => {
          const isSystem = ['system', 'status_change', 'assignment', 'erp_match'].includes(log.log_type)
          if (isSystem) return (
            <div key={log.id} className="flex items-start gap-2 py-2">
              <div className="w-7 h-7 rounded-full bg-gray-100 flex items-center justify-center text-sm shrink-0">
                {LOG_ICONS[log.log_type] || '⚙️'}
              </div>
              <div className="flex-1">
                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2 leading-relaxed">
                  {log.message}
                </div>
                <div className="text-xs text-gray-300 mt-0.5">{timeAgo(log.created_at)}</div>
              </div>
            </div>
          )

          return (
            <div key={log.id} className="flex items-start gap-3 py-3">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0"
                style={{ background: BRAND }}>
                {initials(log.created_by_name || '؟')}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="font-semibold text-gray-800 text-sm">{log.created_by_name}</span>
                  {log.created_by_branch && (
                    <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                      {log.created_by_branch}
                    </span>
                  )}
                  <span className="badge text-xs bg-gray-100 text-gray-500">
                    {LOG_ICONS[log.log_type]} {log.log_type_label}
                  </span>
                  <span className="text-xs text-gray-400 mr-auto">{timeAgo(log.created_at)}</span>
                </div>
                <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-4 py-2.5 shadow-sm">
                  <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{log.message}</p>
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
          {LOG_TYPE_OPTIONS.map(t => (
            <button key={t.value} onClick={() => setLogType(t.value)}
              className={`text-xs px-2.5 py-1 rounded-full font-medium transition-colors ${
                logType === t.value ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
              style={logType === t.value ? { background: BRAND } : {}}>
              {t.label}
            </button>
          ))}
        </div>
        <textarea rows={2} value={message}
          onChange={e => setMessage(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send() }}
          placeholder="اكتب ملاحظة، سجل اتصال، أو رسالة واتساب... (Ctrl+Enter للإرسال)"
          className="w-full text-sm resize-none focus:outline-none placeholder-gray-300 leading-relaxed" />
        <div className="flex justify-end mt-2 pt-2 border-t border-gray-100">
          <button onClick={send} disabled={!message.trim() || sending}
            className="btn-primary text-xs px-3 py-1.5 disabled:opacity-50">
            {sending ? 'جارٍ...' : 'إرسال'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Detail Page ──────────────────────────────────────────────────────────

export default function DemandDetailPage() {
  const { id }     = useParams()
  const navigate   = useNavigate()
  const qc         = useQueryClient()
  const { user }   = useAuthStore()
  const [tab, setTab]          = useState('details')
  const [actionLoading, setActionLoading] = useState(false)

  const { data: demand, isLoading, isError } = useQuery({
    queryKey: ['demand', String(id)],
    queryFn: () => demandApi.get(id).then(r => r.data),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['demand', String(id)] })
    qc.invalidateQueries({ queryKey: ['demands'] })
  }

  async function handleAction(action, payload = {}) {
  if (actionLoading) return   // ✅ prevent double click

  setActionLoading(true)
    try {
      const map = {
        assign:    () => demandApi.assign(id, payload.assigned_to),
        contact:   () => demandApi.contact(id, payload.note),
        wait:      () => demandApi.wait(id, payload.note),
        fulfill:   () => demandApi.fulfill(id, payload.erp_invoice_id),
        markLost:  () => demandApi.markLost(id, payload),
        cancel:    () => demandApi.cancel(id, payload.reason),
        erpLookup: () => demandApi.erpLookup(id),
      }
      if (!map[action]) return
await map[action]()
      invalidate()
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

  if (isError || !demand) return (
    <div className="p-8 text-center" dir="rtl">
      <div className="text-5xl mb-3">😕</div>
      <div className="text-gray-600">لم يتم العثور على الطلب</div>
      <button onClick={() => navigate('/demand')} className="btn-secondary mt-4">← العودة</button>
    </div>
  )

  const s = STATUS_CFG[demand.status] || STATUS_CFG.new
  const p = PRIORITY_CFG[demand.priority] || PRIORITY_CFG.normal

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center gap-3 flex-wrap">
            <button onClick={() => navigate('/demand')}
              className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100 shrink-0">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-black text-gray-900 font-mono">
                  {demand.demand_number}
                </h1>
                <span className="badge text-sm px-3 py-1 font-semibold"
                  style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
                  {s.label}
                </span>
                <span className={`badge text-xs ${p.cls}`}>{p.label}</span>
                {demand.sla_breached && (
                  <span className="badge bg-red-100 text-red-700 text-xs">⚠ SLA تجاوز</span>
                )}
              </div>
              <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-2 flex-wrap">
                <span>{demand.contact_name || demand.contact_phone}</span>
                {demand.phcode && <span className="font-mono text-blue-400">({demand.phcode})</span>}
                <span>·</span>
                <span>{demand.branch_name}</span>
                <span>·</span>
                <span>{timeAgo(demand.created_at)}</span>
              </div>
            </div>

            <SlaTimer demand={demand} />

            <ActionBar demand={demand} onAction={handleAction} loading={actionLoading} />
          </div>

          {/* Tabs */}
          <div className="flex gap-0 mt-3 border-b border-gray-200 overflow-x-auto -mb-px">
            <Tab icon="📋" label="التفاصيل"   active={tab === 'details'}   onClick={() => setTab('details')} />
            <Tab icon="💊" label="الأصناف"    active={tab === 'items'}     onClick={() => setTab('items')}
              count={demand.items?.length} />
            <Tab icon="🔔" label="المتابعات"  active={tab === 'followups'} onClick={() => setTab('followups')}
              count={demand.follow_ups?.filter(f => f.status === 'pending').length} />
            <Tab icon="💬" label="السجلات"    active={tab === 'logs'}      onClick={() => setTab('logs')}
              count={demand.logs?.filter(l => l.log_type !== 'system').length} />
          </div>
        </div>
      </div>

      {/* Tab content */}
      <div className="max-w-5xl mx-auto px-6 py-6">
        <div className="card animate-fade-in">
          {tab === 'details'   && <DetailsTab   demand={demand} />}
          {tab === 'items'     && <ItemsTab     demand={demand} onRefresh={invalidate} />}
          {tab === 'followups' && <FollowUpsTab demand={demand} onRefresh={invalidate} />}
          {tab === 'logs'      && <LogsTab      demand={demand} onRefresh={invalidate} />}
        </div>
      </div>
    </div>
  )
}
