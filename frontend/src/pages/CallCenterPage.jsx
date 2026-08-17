/**
 * CallCenterPage.jsx  —  /callcenter
 * Call center operator screen v2:
 *   - Phone lookup → Customer 360 profile (segment, LTV, open cases, demands)
 *   - Log a call with notes
 *   - Case creation modal
 *   - Follow-up scheduling
 *   - AI summarize button (post-save)
 *   - Manager tab: KPIs dashboard
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { callCenterApi, branchesApi, followupsApi, itemsApi, recommendationsApi } from '../api/client'
import CustomerSearchWidget from '../components/CustomerSearchWidget'
import useAuthStore from '../store/authStore'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s =>
  s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

const SEGMENT_META = {
  vip:      { label: 'VIP 👑',         cls: 'bg-yellow-100 text-yellow-800 border-yellow-200' },
  loyal:    { label: 'مخلص 💚',        cls: 'bg-green-100 text-green-800 border-green-200'  },
  regular:  { label: 'عادي',           cls: 'bg-gray-100 text-gray-700 border-gray-200'     },
  at_risk:  { label: 'في خطر ⚠️',      cls: 'bg-orange-100 text-orange-800 border-orange-200' },
  dormant:  { label: 'نائم 💤',        cls: 'bg-slate-100 text-slate-700 border-slate-200' },
  new:      { label: 'جديد 🌱',        cls: 'bg-teal-100 text-teal-800 border-teal-200'   },
  churned:  { label: 'مفقود ❌',       cls: 'bg-red-100 text-red-800 border-red-200'      },
}

const PURPOSE_OPTIONS = [
  { value: 'reservation',  label: '📋 استفسار حجز' },
  { value: 'delivery',     label: '🚚 متابعة توصيل' },
  { value: 'refill',       label: '💊 إعادة صرف' },
  { value: 'complaint',    label: '⚠️ شكوى' },
  { value: 'new_order',    label: '🛒 طلب جديد' },
  { value: 'address',      label: '📍 تحديث عنوان' },
  { value: 'followup',     label: '🔔 متابعة مزمن' },
  { value: 'demand',       label: '🔍 صنف غير متوفر' },
  { value: 'general',      label: '💬 استفسار عام' },
]

const CASE_CATEGORY_OPTIONS = [
  { value: 'complaint',  label: '⚠️ شكوى' },
  { value: 'inquiry',    label: '❓ استفسار' },
  { value: 'request',    label: '📋 طلب' },
  { value: 'lost_sale',  label: '❌ بيعة مفقودة' },
  { value: 'delivery',   label: '🚚 توصيل' },
  { value: 'support',    label: '🛠️ دعم' },
  { value: 'refund',     label: '↩️ إرجاع/استبدال' },
  { value: 'other',      label: '💬 أخرى' },
]

// ─── Sub-components ───────────────────────────────────────────────────────────

function SegmentBadge({ segment }) {
  if (!segment) return null
  const m = SEGMENT_META[segment] || { label: segment, cls: 'bg-gray-100 text-gray-700 border-gray-200' }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border ${m.cls}`}>
      {m.label}
    </span>
  )
}

function RiskBar({ score }) {
  if (score == null) return null
  const color = score >= 60 ? 'bg-red-500' : score >= 30 ? 'bg-orange-400' : 'bg-green-400'
  return (
    <div className="flex items-center gap-2 mt-1">
      <span className="text-xs text-gray-400">مخاطر الشكوى</span>
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-bold text-gray-600">{score}</span>
    </div>
  )
}

// ─── Case Creation Modal ──────────────────────────────────────────────────────

function CaseModal({ callId, customerId, onClose, onCreated }) {
  const [form, setForm] = useState({
    category: 'inquiry', priority: 'normal', title: '', description: '',
  })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function submit() {
    if (!form.title.trim()) { setErr('العنوان مطلوب'); return }
    setLoading(true)
    setErr('')
    try {
      const { data } = callId
        ? await callCenterApi.createCase(callId, { ...form, customer: customerId })
        : await callCenterApi.cases.create({ ...form, customer: customerId })
      onCreated(data)
    } catch (e) {
      setErr(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-black text-gray-900">🗂️ فتح حالة جديدة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="label text-xs">التصنيف</label>
            <select className="input-field text-sm" value={form.category}
              onChange={e => setForm(p => ({ ...p, category: e.target.value }))}>
              {CASE_CATEGORY_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label text-xs">الأولوية</label>
            <select className="input-field text-sm" value={form.priority}
              onChange={e => setForm(p => ({ ...p, priority: e.target.value }))}>
              <option value="low">منخفضة</option>
              <option value="normal">عادية</option>
              <option value="high">مرتفعة</option>
              <option value="urgent">عاجلة 🔴</option>
            </select>
          </div>
          <div>
            <label className="label text-xs">عنوان الحالة *</label>
            <input className="input-field text-sm" placeholder="اكتب عنواناً موجزاً..."
              value={form.title}
              onChange={e => setForm(p => ({ ...p, title: e.target.value }))} />
          </div>
          <div>
            <label className="label text-xs">الوصف التفصيلي</label>
            <textarea rows={3} className="input-field resize-none text-sm"
              value={form.description}
              onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
          </div>
          {err && <p className="text-red-600 text-xs">{err}</p>}
        </div>
        <div className="p-5 border-t border-gray-100 flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">إلغاء</button>
          <button onClick={submit} disabled={loading} className="btn-primary text-sm disabled:opacity-50">
            {loading ? '...' : '🗂️ فتح الحالة'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Follow-up Modal ──────────────────────────────────────────────────────────

function FollowupModal({ callId, customerId, onClose, onCreated }) {
  const [form, setForm] = useState({
    due_date: '',
    notes: '',
    task_type: 'custom',
    reminder_at: '',
  })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function submit() {
    if (!form.due_date) { setErr('الموعد مطلوب'); return }
    setLoading(true); setErr('')
    try {
      const payload = {
        due_date:  form.due_date,
        notes:     form.notes,
        task_type: form.task_type,
        customer:  customerId || undefined,
        ...(form.reminder_at ? { reminder_at: new Date(form.reminder_at).toISOString() } : {}),
      }
      // If a call has been saved, link the follow-up to it; otherwise create standalone
      const { data } = callId
        ? await callCenterApi.createFollowup(callId, payload)
        : await followupsApi.create(payload)
      onCreated(data)
    } catch (e) {
      setErr(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-black text-gray-900">🔔 جدولة متابعة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="label text-xs">نوع المهمة</label>
            <select className="input-field text-sm" value={form.task_type}
              onChange={e => setForm(p => ({ ...p, task_type: e.target.value }))}>
              <option value="custom">📝 مهمة مخصصة</option>
              <option value="refill">💊 تذكير إعادة صرف</option>
              <option value="chronic">🏥 متابعة مريض مزمن</option>
              <option value="demand">📋 متابعة طلب عميل</option>
            </select>
          </div>
          <div>
            <label className="label text-xs">تاريخ الاستحقاق *</label>
            <input type="date" className="input-field text-sm" value={form.due_date}
              onChange={e => setForm(p => ({ ...p, due_date: e.target.value }))} />
          </div>
          <div>
            <label className="label text-xs">
              ⏰ موعد التذكير
              <span className="text-gray-400 mr-1">(اختياري — يُرسَل إشعار في هذا الوقت)</span>
            </label>
            <input type="datetime-local" className="input-field text-sm" value={form.reminder_at}
              onChange={e => setForm(p => ({ ...p, reminder_at: e.target.value }))} />
          </div>
          <div>
            <label className="label text-xs">ملاحظات</label>
            <textarea rows={2} className="input-field resize-none text-sm"
              value={form.notes}
              onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
          </div>
          {err && <p className="text-red-600 text-xs">{err}</p>}
        </div>
        <div className="p-5 border-t border-gray-100 flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">إلغاء</button>
          <button onClick={submit} disabled={loading} className="btn-primary text-sm disabled:opacity-50">
            {loading ? '...' : '🔔 جدولة'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Manager Dashboard Tab ────────────────────────────────────────────────────

function ManagerDashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ['cc-dashboard'],
    queryFn: () => callCenterApi.dashboard().then(r => r.data),
    staleTime: 60_000,
  })
  const { data: caseDash, isLoading: caseLoading } = useQuery({
    queryKey: ['cc-case-dashboard'],
    queryFn: () => callCenterApi.cases.dashboard().then(r => r.data),
    staleTime: 60_000,
  })

  if (isLoading || caseLoading) return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-pulse">
      {[...Array(8)].map((_, i) => <div key={i} className="h-24 bg-gray-100 rounded-2xl" />)}
    </div>
  )

  const d = data || {}
  const c = caseDash || {}

  const kpiCards = [
    { label: 'مكالمات (30 يوم)', value: d.total_calls, icon: '📞', color: 'blue' },
    { label: 'اليوم', value: d.today, icon: '📅', color: 'indigo' },
    { label: 'انتظار معاودة', value: d.pending_callbacks, icon: '🔄', color: 'orange' },
    { label: 'متوسط مدة (ث)', value: Math.round(d.avg_duration_seconds || 0), icon: '⏱️', color: 'teal' },
    { label: 'حالات مفتوحة', value: c.open, icon: '🗂️', color: 'purple' },
    { label: 'مُصعَّدة', value: c.escalated, icon: '🔴', color: 'red' },
    { label: 'محلولة اليوم', value: c.resolved_today, icon: '✅', color: 'green' },
    { label: 'متوسط CSAT', value: c.avg_csat ? (+c.avg_csat).toFixed(1) + ' ⭐' : '—', icon: '⭐', color: 'yellow' },
  ]

  const colorMap = {
    blue: 'bg-blue-50 text-blue-700', indigo: 'bg-indigo-50 text-indigo-700',
    orange: 'bg-orange-50 text-orange-700', teal: 'bg-teal-50 text-teal-700',
    purple: 'bg-purple-50 text-purple-700', red: 'bg-red-50 text-red-700',
    green: 'bg-green-50 text-green-700', yellow: 'bg-yellow-50 text-yellow-700',
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {kpiCards.map(k => (
          <div key={k.label} className={`rounded-2xl p-4 ${colorMap[k.color]}`}>
            <div className="text-2xl mb-1">{k.icon}</div>
            <div className="text-2xl font-black">{k.value ?? '—'}</div>
            <div className="text-xs font-semibold opacity-70 mt-0.5">{k.label}</div>
          </div>
        ))}
      </div>

      {/* Sentiment breakdown */}
      {d.sentiment && (
        <div className="card">
          <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
            💬 تحليل المشاعر (AI)
          </div>
          <div className="flex gap-4">
            <div className="flex-1 text-center bg-green-50 rounded-xl p-3">
              <div className="text-xl font-black text-green-700">{d.sentiment.positive || 0}</div>
              <div className="text-xs text-green-600">إيجابي 😊</div>
            </div>
            <div className="flex-1 text-center bg-gray-50 rounded-xl p-3">
              <div className="text-xl font-black text-gray-700">{d.sentiment.neutral || 0}</div>
              <div className="text-xs text-gray-600">محايد 😐</div>
            </div>
            <div className="flex-1 text-center bg-red-50 rounded-xl p-3">
              <div className="text-xl font-black text-red-700">{d.sentiment.negative || 0}</div>
              <div className="text-xs text-red-600">سلبي 😟</div>
            </div>
          </div>
        </div>
      )}

      {/* Purpose breakdown */}
      {d.by_purpose?.length > 0 && (
        <div className="card">
          <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
            📊 توزيع الغرض
          </div>
          <div className="space-y-2">
            {d.by_purpose.slice(0, 6).map(r => {
              const total = d.total_calls || 1
              const pct = Math.round((r.count / total) * 100)
              const opt = PURPOSE_OPTIONS.find(o => o.value === r.purpose)
              return (
                <div key={r.purpose} className="flex items-center gap-3">
                  <div className="w-32 text-xs text-gray-600 truncate">
                    {opt?.label || r.purpose}
                  </div>
                  <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full bg-brand-500 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="text-xs font-bold text-gray-700 w-8 text-left">{r.count}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Case category breakdown */}
      {c.by_category?.length > 0 && (
        <div className="card">
          <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
            🗂️ توزيع تصنيف الحالات
          </div>
          <div className="grid grid-cols-2 gap-2">
            {c.by_category.map(r => {
              const opt = CASE_CATEGORY_OPTIONS.find(o => o.value === r.category)
              return (
                <div key={r.category} className="flex justify-between items-center text-sm
                  bg-gray-50 rounded-lg px-3 py-1.5">
                  <span className="text-gray-600">{opt?.label || r.category}</span>
                  <span className="font-bold">{r.count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Customer Picker (shown when multiple customers match the same phone) ────────

function CustomerPicker({ customers, onSelect }) {
  return (
    <div className="card border-2 border-brand-200 bg-brand-50">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">👥</span>
        <div>
          <div className="font-black text-gray-900 text-sm">
            {customers.length} عملاء بنفس الرقم
          </div>
          <div className="text-xs text-gray-500">اختر العميل لعرض بياناته الكاملة</div>
        </div>
      </div>
      <div className="grid gap-2">
        {customers.map(c => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className="w-full text-right bg-white border border-gray-200 hover:border-brand-400
              hover:shadow-md rounded-xl px-4 py-3 transition-all group"
          >
            <div className="flex items-start gap-3">
              {/* Avatar */}
              <div className="w-9 h-9 rounded-full bg-brand-100 flex items-center justify-center
                text-brand-700 font-black text-base shrink-0 group-hover:bg-brand-200 transition-colors">
                {c.name?.[0] || '?'}
              </div>
              <div className="flex-1 min-w-0">
                {/* Name + segment */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-black text-gray-900 text-sm">{c.name}</span>
                  {c.segment && <SegmentBadge segment={c.segment} />}
                  {c.type_label && (
                    <span className="badge bg-gray-100 text-gray-600 text-xs">{c.type_label}</span>
                  )}
                </div>
                {/* PIC code + branch — always shown */}
                <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                  {c.softech_pic ? (
                    <span className="badge bg-purple-100 text-purple-800 font-mono font-bold text-xs">
                      📋 {c.softech_pic}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-400 italic">بدون PIC</span>
                  )}
                  {c.branch ? (
                    <span className="text-xs text-gray-500 font-semibold">🏥 {c.branch}</span>
                  ) : (
                    <span className="text-xs text-gray-400 italic">بدون فرع</span>
                  )}
                </div>
                {/* LTV */}
                {c.ltv != null && (
                  <div className="text-xs text-indigo-600 font-bold mt-0.5">
                    💰 LTV: {Number(c.ltv).toLocaleString('en-US')} ج.م
                  </div>
                )}
              </div>
              <span className="text-brand-400 text-sm font-bold shrink-0 self-center
                group-hover:text-brand-600">←</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Case Chat Panel (slide-in overlay for call center page) ─────────────────

const CC_STATUS_META = {
  open:      { label: '🆕 مفتوحة',       cls: 'bg-blue-100 text-blue-800'    },
  working:   { label: '⚙️ قيد المعالجة', cls: 'bg-indigo-100 text-indigo-800'},
  waiting:   { label: '⏳ انتظار',        cls: 'bg-yellow-100 text-yellow-800'},
  escalated: { label: '🔴 مُصعَّدة',      cls: 'bg-red-100 text-red-800'      },
  resolved:  { label: '✅ محلولة',        cls: 'bg-green-100 text-green-800'  },
  closed:    { label: '🔒 مغلقة',         cls: 'bg-gray-100 text-gray-700'    },
}

function CaseChatPanel({ caseId, onClose }) {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [noteText, setNoteText]       = useState('')
  const [attachFile, setAttachFile]   = useState(null)
  const [attachType, setAttachType]   = useState('image')
  const [recording, setRecording]     = useState(false)
  const [posting, setPosting]         = useState(false)
  const [showResolve, setShowResolve] = useState(false)
  const [resolveText, setResolveText] = useState('')
  const mediaRecRef  = useRef(null)
  const chunksRef    = useRef([])
  const fileInputRef = useRef(null)
  const noteRef      = useRef(null)

  const { data: cas, isLoading } = useQuery({
    queryKey: ['case-detail', caseId],
    queryFn:  () => callCenterApi.cases.get(caseId).then(r => r.data),
    staleTime: 10_000,
  })

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        setAttachFile(new File([blob], `voice_${Date.now()}.webm`, { type: 'audio/webm' }))
        setAttachType('voice')
        stream.getTracks().forEach(t => t.stop())
      }
      mediaRecRef.current = rec; rec.start(); setRecording(true)
    } catch { alert('لا يمكن الوصول للميكروفون') }
  }
  function stopRecording() { mediaRecRef.current?.stop(); setRecording(false) }

  async function addNote() {
    if (!noteText.trim() && !attachFile) return
    setPosting(true)
    try {
      const fd = new FormData()
      fd.append('message', noteText)
      if (attachFile) { fd.append('attachment', attachFile, attachFile.name); fd.append('attachment_type', attachType) }
      await callCenterApi.cases.addNote(caseId, fd)
      setNoteText(''); setAttachFile(null)
      qc.invalidateQueries({ queryKey: ['case-detail', caseId] })
      qc.invalidateQueries({ queryKey: ['cc-my-queue'] })
    } catch (e) { alert(e.response?.data?.detail || 'حدث خطأ') }
    finally { setPosting(false) }
  }

  async function doAction(actionFn, body = {}) {
    try {
      await actionFn(caseId, body)
      qc.invalidateQueries({ queryKey: ['case-detail', caseId] })
      qc.invalidateQueries({ queryKey: ['cc-my-queue'] })
    } catch (e) { alert(e.response?.data?.detail || 'حدث خطأ') }
  }

  const sm = cas ? (CC_STATUS_META[cas.status] || { label: cas.status, cls: 'bg-gray-100' }) : {}
  const canEdit = ['admin', 'supervisor', 'call_center', 'quality_manager'].includes(user?.role)

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-end" dir="rtl"
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-white w-full max-w-lg h-full flex flex-col shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-start gap-3 p-4 border-b border-gray-100 shrink-0">
          <div className="flex-1 min-w-0">
            {isLoading ? (
              <div className="h-4 bg-gray-100 rounded animate-pulse w-48" />
            ) : cas && (
              <>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs text-gray-400">{cas.case_number}</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${sm.cls}`}>{sm.label}</span>
                  {cas.is_sla_breached && <span className="text-xs text-red-600 font-bold">⏰ SLA!</span>}
                </div>
                <div className="font-black text-gray-900 mt-0.5 truncate">{cas.title}</div>
                <div className="text-sm text-gray-500">
                  {cas.customer_name}{cas.branch_name ? ` · ${cas.branch_name}` : ''}
                </div>
              </>
            )}
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl shrink-0">✕</button>
        </div>

        {/* Scrollable events body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isLoading ? (
            <div className="text-center text-gray-400 animate-pulse py-12">تحميل...</div>
          ) : (
            <>
              {cas?.description && (
                <div className="bg-gray-50 rounded-xl p-3 text-sm text-gray-700">{cas.description}</div>
              )}
              {cas?.resolution && (
                <div className="bg-green-50 rounded-xl p-3">
                  <div className="text-xs font-bold text-green-700 mb-1">✅ الحل</div>
                  <div className="text-sm text-green-800">{cas.resolution}</div>
                </div>
              )}
              <div className="text-xs font-bold text-gray-400 uppercase tracking-wide pt-1">سجل الأحداث</div>
              {!cas?.events?.length ? (
                <div className="text-center text-gray-400 py-8 text-sm">لا توجد ملاحظات بعد — ابدأ بكتابة ملاحظة أدناه</div>
              ) : (
                <div className="space-y-3">
                  {cas.events.map(ev => (
                    <div key={ev.id} className="flex gap-2 text-sm">
                      <div className="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center text-xs shrink-0 mt-0.5">
                        {ev.event_type === 'note' ? '📝' : ev.event_type === 'call' ? '📞'
                          : ev.event_type === 'status' ? '🔄' : '⚙️'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-gray-700">
                          {ev.message?.split(/(@\w+)/g).map((part, i) =>
                            part.startsWith('@')
                              ? <span key={i} className="text-brand-600 font-semibold">{part}</span>
                              : part
                          )}
                        </div>
                        {ev.attachment_url && ev.attachment_type === 'image' && (
                          <a href={ev.attachment_url} target="_blank" rel="noopener noreferrer">
                            <img src={ev.attachment_url} alt=""
                              className="max-h-28 rounded-lg mt-1.5 border border-gray-200 object-cover" />
                          </a>
                        )}
                        {ev.attachment_url && ev.attachment_type === 'voice' && (
                          <audio controls src={ev.attachment_url} className="h-8 w-full max-w-xs mt-1" />
                        )}
                        {ev.attachment_url && ev.attachment_type === 'document' && (
                          <a href={ev.attachment_url} target="_blank" rel="noopener noreferrer"
                            className="text-xs text-brand-600 hover:underline mt-1 block">📎 مرفق</a>
                        )}
                        <div className="text-xs text-gray-400 mt-0.5">
                          {ev.created_by_name} · {ev.created_at
                            ? toLatinDigits(format(new Date(ev.created_at), 'd MMM HH:mm', { locale: ar }))
                            : '—'}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer — note input + state buttons */}
        {cas && cas.status !== 'closed' && canEdit && (
          <div className="shrink-0 border-t border-gray-100 p-4 space-y-3">
            {attachFile && (
              <div className="flex items-center gap-2 text-xs bg-gray-50 border border-gray-200 rounded-lg px-2 py-1.5">
                <span>{attachType === 'voice' ? '🎙️' : '📎'} {attachFile.name}</span>
                <button onClick={() => setAttachFile(null)} className="text-red-400 hover:text-red-600 mr-auto">✕</button>
              </div>
            )}
            <div className="flex gap-2">
              <textarea
                ref={noteRef} rows={2}
                className="flex-1 input-field resize-none text-sm"
                placeholder="اكتب ملاحظة... (Ctrl+Enter للإرسال)"
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) addNote() }}
              />
              <div className="flex flex-col gap-1 shrink-0">
                <button onClick={addNote}
                  disabled={(!noteText.trim() && !attachFile) || posting}
                  className="btn-primary text-xs px-3 py-1.5 disabled:opacity-40">
                  {posting ? '⏳' : '➤'}
                </button>
                <button
                  onClick={recording ? stopRecording : startRecording}
                  className={`text-xs px-3 py-1.5 rounded-lg border font-bold transition-all
                    ${recording
                      ? 'bg-red-100 border-red-300 text-red-600 animate-pulse'
                      : 'border-gray-200 text-gray-400 hover:text-gray-600'}`}
                  title={recording ? 'إيقاف التسجيل' : 'تسجيل صوتي'}>🎙️
                </button>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-400 hover:text-gray-600"
                  title="إرفاق ملف">📎
                </button>
                <input ref={fileInputRef} type="file" className="hidden"
                  accept="image/*,application/pdf,.doc,.docx"
                  onChange={e => {
                    const f = e.target.files?.[0]
                    if (f) { setAttachFile(f); setAttachType(f.type.startsWith('image/') ? 'image' : 'document') }
                  }} />
              </div>
            </div>
            <div className="flex gap-2 flex-wrap">
              {cas.status === 'open' && (
                <button
                  onClick={() => doAction(callCenterApi.cases.assign, { staff_id: user?.staff_id || user?.id })}
                  className="btn-secondary text-xs py-1.5 px-2">⚙️ بدء المعالجة
                </button>
              )}
              {['open', 'working', 'waiting'].includes(cas.status) && !showResolve && (
                <button onClick={() => setShowResolve(true)}
                  className="btn-secondary text-xs py-1.5 px-2">✅ حل الحالة
                </button>
              )}
              {cas.status === 'resolved' && (
                <button onClick={() => doAction(callCenterApi.cases.close)}
                  className="btn-secondary text-xs py-1.5 px-2">🔒 إغلاق
                </button>
              )}
            </div>
            {showResolve && (
              <div className="space-y-2">
                <textarea rows={2} className="input-field resize-none text-sm w-full"
                  placeholder="اشرح طريقة الحل..."
                  value={resolveText}
                  onChange={e => setResolveText(e.target.value)} />
                <div className="flex gap-2">
                  <button onClick={() => setShowResolve(false)} className="btn-secondary text-xs">إلغاء</button>
                  <button
                    onClick={async () => {
                      if (!resolveText.trim()) return
                      await doAction(callCenterApi.cases.resolve, { resolution: resolveText })
                      setShowResolve(false); setResolveText('')
                    }}
                    disabled={!resolveText.trim()}
                    className="btn-primary text-xs disabled:opacity-40">✅ تأكيد الحل
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Call Items Panel ─────────────────────────────────────────────────────────

/**
 * Items discussed during a call.
 * Before call is saved (savedCallId = null): items held in local state (pendingItems).
 * After save: pending items auto-flushed to DB; new items saved immediately.
 * Convert buttons appear once savedCallId is set.
 */

// ── FBT Suggestions Row ────────────────────────────────────────────────────────
/**
 * Shows "يُشترى معه عادةً" chip row for the last added catalog item.
 * Chips that are already in the list are shown as disabled.
 */
function FBTSuggestionsRow({ itemId, onAdd, alreadyAdded = [], onDismiss }) {
  const { data, isLoading } = useQuery({
    queryKey: ['fbt-for-item', itemId],
    queryFn:  () => recommendationsApi.fbtForItem(itemId, 6).then(r => r.data),
    enabled:  !!itemId,
    staleTime: 300_000,
    retry: false,
  })

  const recs = Array.isArray(data) ? data : []
  if (isLoading) return (
    <div className="mt-2 py-1.5 text-xs text-gray-400 animate-pulse">يُحضِّر اقتراحات...</div>
  )
  if (!recs.length) return null

  return (
    <div className="mt-2 mb-1">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-gray-400 font-medium">🧩 يُشترى معه عادةً</span>
        <button onClick={onDismiss} className="text-gray-300 hover:text-gray-500 text-xs">✕</button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {recs.map(rec => {
          const alreadyIn = alreadyAdded.includes(rec.item_b_id)
          return (
            <button
              key={rec.item_b_id}
              onClick={() => !alreadyIn && onAdd({ id: rec.item_b_id, name: rec.item_b_name, softech_id: rec.item_b_code })}
              disabled={alreadyIn}
              title={`ثقة: ${Math.round((rec.confidence || 0) * 100)}%`}
              className={`px-2.5 py-1 rounded-full text-xs border transition-all
                ${alreadyIn
                  ? 'bg-gray-50 text-gray-300 border-gray-100 cursor-default'
                  : 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100 hover:border-green-400 cursor-pointer'
                }`}
            >
              {alreadyIn ? '✓ ' : '+ '}{rec.item_b_name}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Customer Recommendations Panel ────────────────────────────────────────────
/**
 * Shows personalized "مقترح لك" recommendations for the identified customer.
 * Shown as a card in the right column of the operator workspace.
 */
function CustomerRecsPanel({ customerId, onAdd }) {
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['customer-recs', customerId],
    queryFn:  () => recommendationsApi.customerRecs(customerId, 8).then(r => r.data),
    enabled:  !!customerId,
    staleTime: 300_000,
    retry: false,
  })

  const recs = Array.isArray(data) ? data : []
  if (isLoading || !recs.length) return null

  const visible = expanded ? recs : recs.slice(0, 4)

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide">
          💡 مقترح لهذا العميل
        </div>
        <span className="text-xs text-gray-400">{recs.length} صنف</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {visible.map(rec => (
          <button
            key={rec.item_id}
            onClick={() => onAdd && onAdd({ id: rec.item_id, name: rec.item_name, softech_id: rec.item_code })}
            title={`نقاط: ${rec.score?.toFixed ? rec.score.toFixed(2) : rec.score}`}
            className="px-2.5 py-1 rounded-full text-xs border bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 hover:border-blue-400 transition-all cursor-pointer"
          >
            + {rec.item_name}
          </button>
        ))}
      </div>
      {recs.length > 4 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="text-xs text-brand-600 hover:underline mt-2"
        >
          {expanded ? 'عرض أقل ↑' : `عرض الكل (${recs.length}) ↓`}
        </button>
      )}
      <p className="text-xs text-gray-300 mt-2">
        بناءً على تاريخ مشترياته — انقر لإضافة الصنف
      </p>
    </div>
  )
}

function CallItemsPanel({ savedCallId, customer, branchId }) {
  const qc = useQueryClient()
  const [pendingItems, setPendingItems]   = useState([])   // local-only, pre-save
  const [dbItems, setDbItems]             = useState([])   // persisted
  const [flushing, setFlushing]           = useState(false)
  const [searchQ, setSearchQ]             = useState('')
  const [searchRes, setSearchRes]         = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [showSearch, setShowSearch]       = useState(false)
  const [manualName, setManualName]       = useState('')
  const [showManual, setShowManual]       = useState(false)
  const [showConvert, setShowConvert]     = useState(null)  // 'reservation' | 'transfer'
  const [lastAddedItemId, setLastAddedItemId] = useState(null)  // for FBT suggestions
  const [convertForm, setConvertForm]     = useState({
    branch_id: branchId || '', requesting_branch_id: branchId || '', supplying_branch_id: '',
    notes: '', priority: 'normal', channel: 'pickup',
  })
  const [converting, setConverting]       = useState(false)
  const [convertResult, setConvertResult] = useState(null)
  const searchTimeoutRef = useRef(null)

  // Branches for conversion dropdowns
  const { data: branchList = [] } = useQuery({
    queryKey: ['branches-list'],
    queryFn:  () => branchesApi.list().then(r => r.data?.results || r.data || []),
    staleTime: 300_000,
  })

  // Reset when branchId changes
  useEffect(() => {
    setConvertForm(p => ({ ...p, branch_id: branchId || '', requesting_branch_id: branchId || '' }))
  }, [branchId])

  // ── Auto-flush pending items when call is saved ───────────────────────────
  useEffect(() => {
    if (!savedCallId || pendingItems.length === 0 || flushing) return
    ;(async () => {
      setFlushing(true)
      const saved = []
      for (const item of pendingItems) {
        try {
          const { data } = await callCenterApi.addItem(savedCallId, {
            item:             item.item?.id || null,
            manual_item_name: item.manual_item_name || '',
            manual_item_code: item.manual_item_code || '',
            quantity:         item.quantity,
            notes:            item.notes || '',
          })
          saved.push(data)
        } catch { /* silent — item already shown in UI */ }
      }
      setPendingItems([])
      setDbItems(prev => [...prev, ...saved])
      setFlushing(false)
    })()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedCallId])

  // Load db items if savedCallId arrives from outside (page reload)
  useEffect(() => {
    if (!savedCallId) return
    callCenterApi.getItems(savedCallId).then(r => setDbItems(r.data))
  }, [savedCallId])

  // Listen for rec-item add events from CustomerRecsPanel (sibling component)
  useEffect(() => {
    const handler = (e) => addCatalogItem(e.detail)
    window.addEventListener('cc-add-rec-item', handler)
    return () => window.removeEventListener('cc-add-rec-item', handler)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedCallId])

  // ── Item search ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!searchQ.trim() || searchQ.trim().length < 2) { setSearchRes([]); return }
    clearTimeout(searchTimeoutRef.current)
    searchTimeoutRef.current = setTimeout(async () => {
      setSearchLoading(true)
      try {
        const { data } = await itemsApi.wildcardSearch(searchQ.trim(), branchId || null)
        setSearchRes(Array.isArray(data) ? data : data?.results || [])
      } catch { setSearchRes([]) }
      finally { setSearchLoading(false) }
    }, 350)
    return () => clearTimeout(searchTimeoutRef.current)
  }, [searchQ, branchId])

  const allItems = [
    ...pendingItems.map(i => ({ ...i, _status: 'pending' })),
    ...dbItems.map(i => ({ ...i, _status: i.converted_to !== 'none' ? 'converted' : 'saved' })),
  ]

  async function addCatalogItem(catalogItem) {
    const payload = {
      item:             catalogItem.id,
      manual_item_name: '',
      manual_item_code: '',
      quantity:         1,
      notes:            '',
    }
    if (savedCallId) {
      try {
        const { data } = await callCenterApi.addItem(savedCallId, payload)
        setDbItems(p => [...p, data])
      } catch (e) { alert(e.response?.data?.detail || 'حدث خطأ') }
    } else {
      setPendingItems(p => [...p, { ...payload, item: catalogItem, _tempId: Date.now() }])
    }
    setLastAddedItemId(catalogItem.id)
    setSearchQ(''); setSearchRes([]); setShowSearch(false)
  }

  async function addManualItem() {
    if (!manualName.trim()) return
    const payload = { item: null, manual_item_name: manualName.trim(), manual_item_code: '', quantity: 1, notes: '' }
    if (savedCallId) {
      try {
        const { data } = await callCenterApi.addItem(savedCallId, payload)
        setDbItems(p => [...p, data])
      } catch (e) { alert(e.response?.data?.detail || 'حدث خطأ') }
    } else {
      setPendingItems(p => [...p, { ...payload, _tempId: Date.now() }])
    }
    setManualName(''); setShowManual(false)
  }

  async function removeItem(item) {
    if (item._status === 'saved' && savedCallId) {
      try {
        await callCenterApi.removeItem(savedCallId, item.id)
        setDbItems(p => p.filter(i => i.id !== item.id))
      } catch (e) { alert(e.response?.data?.detail || 'حدث خطأ') }
    } else if (item._status === 'pending') {
      setPendingItems(p => p.filter(i => i._tempId !== item._tempId))
    }
  }

  function updateQty(item, qty) {
    if (item._status === 'pending') {
      setPendingItems(p => p.map(i => i._tempId === item._tempId ? { ...i, quantity: qty } : i))
    } else if (item._status === 'saved') {
      setDbItems(p => p.map(i => i.id === item.id ? { ...i, quantity: qty } : i))
    }
  }

  async function handleConvert() {
    if (!savedCallId) return
    setConverting(true)
    setConvertResult(null)
    try {
      let res
      if (showConvert === 'reservation') {
        res = await callCenterApi.convertToReservation(savedCallId, {
          branch_id: convertForm.branch_id,
          notes:     convertForm.notes,
          priority:  convertForm.priority,
          channel:   convertForm.channel,
        })
      } else {
        res = await callCenterApi.convertToTransfer(savedCallId, {
          requesting_branch_id: convertForm.requesting_branch_id,
          supplying_branch_id:  convertForm.supplying_branch_id || undefined,
          notes:                convertForm.notes,
        })
      }
      setConvertResult(res.data)
      // Refresh db items to show converted status
      const { data } = await callCenterApi.getItems(savedCallId)
      setDbItems(data)
      qc.invalidateQueries({ queryKey: ['reservations'] })
      qc.invalidateQueries({ queryKey: ['transfers'] })
    } catch (e) {
      alert(e.response?.data?.detail || 'حدث خطأ في التحويل')
    } finally {
      setConverting(false)
    }
  }

  const unconvertedCount = dbItems.filter(i => i.converted_to === 'none').length

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide">
          📦 الأصناف ({allItems.length})
          {flushing && <span className="text-brand-500 mr-1">· حفظ...</span>}
          {pendingItems.length > 0 && !savedCallId && (
            <span className="text-orange-500 mr-1">· {pendingItems.length} في الانتظار</span>
          )}
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={() => { setShowManual(s => !s); setShowSearch(false) }}
            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-lg px-2 py-1 transition-all">
            ✏️ يدوي
          </button>
          <button
            onClick={() => { setShowSearch(s => !s); setShowManual(false) }}
            className="text-xs bg-brand-50 hover:bg-brand-100 text-brand-700 rounded-lg px-2 py-1 transition-all">
            🔍 بحث
          </button>
        </div>
      </div>

      {/* Catalog search */}
      {showSearch && (
        <div className="mb-3 relative">
          <input
            className="input-field text-sm w-full"
            placeholder="ابحث باسم الصنف أو الكود... (*نجمة للبحث الشامل)"
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            autoFocus
          />
          {searchLoading && (
            <div className="absolute left-2 top-2 text-xs text-gray-400 animate-pulse">بحث...</div>
          )}
          {searchRes.length > 0 && (
            <div className="absolute z-20 top-full right-0 left-0 bg-white border border-gray-200 rounded-xl shadow-lg max-h-48 overflow-y-auto mt-1">
              {searchRes.slice(0, 15).map(item => (
                <button
                  key={item.id}
                  onClick={() => addCatalogItem(item)}
                  className="w-full text-right px-3 py-2 hover:bg-brand-50 text-sm border-b border-gray-50 last:border-0 transition-colors">
                  <span className="font-semibold text-gray-800 block break-words">{item.name}</span>
                  <span className="text-xs text-gray-400 font-mono">{item.softech_id}</span>
                  {item.qty_at_branch != null && (
                    <span className="text-xs text-green-600 mr-2">مخزون: {item.qty_at_branch}</span>
                  )}
                </button>
              ))}
            </div>
          )}
          {searchQ.length >= 2 && !searchLoading && searchRes.length === 0 && (
            <div className="text-xs text-gray-400 text-center py-2">لا نتائج — جرب اسماً مختلفاً</div>
          )}
        </div>
      )}

      {/* Manual item entry */}
      {showManual && (
        <div className="mb-3 flex gap-2">
          <input
            className="input-field text-sm flex-1"
            placeholder="اسم الصنف اليدوي..."
            value={manualName}
            onChange={e => setManualName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addManualItem()}
            autoFocus
          />
          <button onClick={addManualItem} disabled={!manualName.trim()}
            className="btn-primary text-xs px-3 disabled:opacity-40">إضافة</button>
        </div>
      )}

      {/* Items list */}
      {allItems.length === 0 ? (
        <div className="text-center py-4 text-xs text-gray-400">
          لم يُضف أصناف بعد
        </div>
      ) : (
        <div className="space-y-1.5 mb-3">
          {allItems.map((item, idx) => {
            const name = item.item?.name || item.display_name || item.manual_item_name || '—'
            const code = item.item?.softech_id || item.display_code || item.manual_item_code || ''
            const isConverted = item._status === 'converted' || item.converted_to !== 'none'
            return (
              <div key={item.id || item._tempId || idx}
                className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-all
                  ${isConverted
                    ? 'bg-green-50 border border-green-100 opacity-70'
                    : item._status === 'pending'
                    ? 'bg-orange-50 border border-orange-100'
                    : 'bg-gray-50 border border-gray-100'
                  }`}>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-gray-800 text-xs truncate">{name}</div>
                  {code && <div className="font-mono text-xs text-gray-400">{code}</div>}
                  {isConverted && (
                    <div className="text-xs text-green-600 font-semibold">
                      ✅ {item.converted_to_label || item.converted_to}
                    </div>
                  )}
                </div>
                {!isConverted && (
                  <input type="number" min="0.5" step="0.5"
                    className="w-14 text-center border border-gray-200 rounded-md text-xs py-0.5 bg-white"
                    value={item.quantity}
                    onChange={e => updateQty(item, parseFloat(e.target.value) || 1)}
                  />
                )}
                {!isConverted && (
                  <button onClick={() => removeItem(item)}
                    className="text-gray-300 hover:text-red-400 text-xs shrink-0">✕</button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* FBT suggestions — shown when a catalog item was added */}
      {lastAddedItemId && (
        <FBTSuggestionsRow
          itemId={lastAddedItemId}
          onAdd={addCatalogItem}
          alreadyAdded={allItems.map(i => i.item?.id || i.item).filter(Boolean)}
          onDismiss={() => setLastAddedItemId(null)}
        />
      )}

      {/* Convert buttons — only after call is saved and items exist */}
      {savedCallId && unconvertedCount > 0 && !convertResult && (
        <div className="border-t border-gray-100 pt-3 space-y-1.5">
          <div className="text-xs text-gray-400 mb-1.5">تحويل ({unconvertedCount} صنف)</div>
          <button
            onClick={() => setShowConvert(showConvert === 'reservation' ? null : 'reservation')}
            className={`w-full text-xs px-3 py-2 rounded-lg transition-all text-right
              ${showConvert === 'reservation'
                ? 'bg-blue-100 text-blue-800 font-semibold'
                : 'bg-blue-50 hover:bg-blue-100 text-blue-700'}`}>
            📋 تحويل لحجوزات
          </button>
          <button
            onClick={() => setShowConvert(showConvert === 'transfer' ? null : 'transfer')}
            className={`w-full text-xs px-3 py-2 rounded-lg transition-all text-right
              ${showConvert === 'transfer'
                ? 'bg-purple-100 text-purple-800 font-semibold'
                : 'bg-purple-50 hover:bg-purple-100 text-purple-700'}`}>
            🔄 تحويل لطلب نقل
          </button>
        </div>
      )}

      {/* Convert form */}
      {showConvert === 'reservation' && savedCallId && !convertResult && (
        <div className="mt-3 space-y-2 border border-blue-100 rounded-xl p-3 bg-blue-50">
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">الفرع *</label>
            <select className="input-field text-xs w-full"
              value={convertForm.branch_id}
              onChange={e => setConvertForm(p => ({ ...p, branch_id: e.target.value }))}>
              <option value="">-- اختر فرع --</option>
              {branchList.map(b => (
                <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-gray-500 block mb-0.5">الأولوية</label>
              <select className="input-field text-xs"
                value={convertForm.priority}
                onChange={e => setConvertForm(p => ({ ...p, priority: e.target.value }))}>
                <option value="normal">عادي</option>
                <option value="urgent">عاجل</option>
                <option value="chronic">مزمن</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-0.5">القناة</label>
              <select className="input-field text-xs"
                value={convertForm.channel}
                onChange={e => setConvertForm(p => ({ ...p, channel: e.target.value }))}>
                <option value="pickup">استلام</option>
                <option value="home_delivery">توصيل</option>
              </select>
            </div>
          </div>
          <input className="input-field text-xs" placeholder="ملاحظات (اختياري)"
            value={convertForm.notes}
            onChange={e => setConvertForm(p => ({ ...p, notes: e.target.value }))} />
          <button onClick={handleConvert} disabled={!convertForm.branch_id || converting}
            className="btn-primary text-xs w-full disabled:opacity-40">
            {converting ? '⏳...' : '📋 إنشاء الحجوزات'}
          </button>
        </div>
      )}

      {showConvert === 'transfer' && savedCallId && !convertResult && (
        <div className="mt-3 space-y-2 border border-purple-100 rounded-xl p-3 bg-purple-50">
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">الفرع الطالب *</label>
            <select className="input-field text-xs w-full"
              value={convertForm.requesting_branch_id}
              onChange={e => setConvertForm(p => ({ ...p, requesting_branch_id: e.target.value }))}>
              <option value="">-- اختر فرع --</option>
              {branchList.map(b => (
                <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">الفرع المصدر (اختياري)</label>
            <select className="input-field text-xs w-full"
              value={convertForm.supplying_branch_id}
              onChange={e => setConvertForm(p => ({ ...p, supplying_branch_id: e.target.value }))}>
              <option value="">-- غير محدد --</option>
              {branchList.map(b => (
                <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
              ))}
            </select>
          </div>
          <input className="input-field text-xs" placeholder="ملاحظات (اختياري)"
            value={convertForm.notes}
            onChange={e => setConvertForm(p => ({ ...p, notes: e.target.value }))} />
          <button onClick={handleConvert} disabled={!convertForm.requesting_branch_id || converting}
            className="btn-primary text-xs w-full disabled:opacity-40">
            {converting ? '⏳...' : '🔄 إنشاء طلب النقل'}
          </button>
        </div>
      )}

      {/* Conversion result */}
      {convertResult && (
        <div className="mt-3 bg-green-50 border border-green-200 rounded-xl p-3 text-xs">
          {showConvert === 'reservation' ? (
            <>
              <div className="font-bold text-green-800">✅ تم إنشاء {convertResult.count} حجز بنجاح</div>
              <div className="text-green-600 mt-1">
                الحجوزات جاهزة — يمكن متابعتها من صفحة الحجوزات
              </div>
            </>
          ) : (
            <>
              <div className="font-bold text-green-800">✅ تم إنشاء طلب النقل #{convertResult.request_number}</div>
              {convertResult.items_skipped > 0 && (
                <div className="text-orange-600 mt-1">
                  ⚠️ {convertResult.items_skipped} صنف تخطّي (أصناف يدوية لا تدعم النقل)
                </div>
              )}
            </>
          )}
          <button onClick={() => { setConvertResult(null); setShowConvert(null) }}
            className="text-green-600 hover:underline mt-1 block">إخفاء ←</button>
        </div>
      )}
    </div>
  )
}


// ─── My Queue Panel (agent's assigned open cases) ─────────────────────────────

function MyQueuePanel({ onOpenCase }) {
  const { data, isLoading } = useQuery({
    queryKey: ['cc-my-queue'],
    queryFn:  () => callCenterApi.cases.myQueue().then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 120_000,
  })
  const cases = Array.isArray(data) ? data : []
  if (!isLoading && cases.length === 0) return null
  return (
    <div className="card mb-5 border-r-4 border-brand-400">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wide">
          📋 طابور انتظاري ({isLoading ? '...' : cases.length} حالة مسندة إليك)
        </div>
        <Link to="/callcenter/cases" className="text-xs text-brand-600 hover:underline">
          عرض الكل →
        </Link>
      </div>
      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {[...Array(2)].map((_, i) => <div key={i} className="h-12 bg-gray-100 rounded-lg" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {cases.slice(0, 6).map(c => (
            <button key={c.id} onClick={() => onOpenCase(c.id)}
              className="text-right flex items-center gap-3 bg-gray-50 hover:bg-brand-50
                border border-gray-200 hover:border-brand-300 rounded-xl px-3 py-2.5 transition-all group">
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm text-gray-800 truncate group-hover:text-brand-700">
                  {c.title}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {c.customer_name} · <span className="font-mono">{c.case_number}</span>
                  {c.age_hours != null && ` · ${c.age_hours}س`}
                </div>
              </div>
              <span className={`px-1.5 py-0.5 rounded-full text-xs font-bold shrink-0 ${
                c.status === 'escalated' ? 'bg-red-100 text-red-700' :
                c.status === 'waiting'   ? 'bg-yellow-100 text-yellow-700' :
                c.status === 'working'   ? 'bg-indigo-100 text-indigo-700' :
                'bg-blue-100 text-blue-700'
              }`}>{c.status_label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CallCenterPage() {
  const { user }   = useAuthStore()
  const qc         = useQueryClient()
  const [tab, setTab]           = useState('operator')  // 'operator' | 'manager'
  const [searchMode, setSearchMode] = useState('phone') // 'phone' | 'name'
  const [phone, setPhone]       = useState('')
  const [searchPhone, setSearchPhone]         = useState('')
  const [selectedCustomerId, setSelectedCustomerId] = useState(null)
  const [logForm, setLogForm]   = useState({
    purpose: 'general', direction: 'inbound',
    status: 'answered', duration_seconds: 0,
    notes: '', summary: '', payment_method: '',
  })
  const [savedCallId, setSavedCallId]   = useState(null)
  const [showCaseModal, setShowCaseModal]     = useState(false)
  const [showFollowupModal, setShowFollowupModal] = useState(false)
  const [aiLoading, setAiLoading]       = useState(false)
  const [aiDone, setAiDone]             = useState(false)
  const [flashCase, setFlashCase]       = useState(null)
  const [selectedCaseId, setSelectedCaseId] = useState(null)   // for CaseChatPanel overlay

  // Debounced auto-search
  useEffect(() => {
    const delay = setTimeout(() => {
      if (phone.trim().length >= 8) handleSearch()
    }, 400)
    return () => clearTimeout(delay)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone])

  const { data: lookupData, isLoading: lookupLoading, isFetching } = useQuery({
    queryKey: ['cc-lookup', searchPhone, selectedCustomerId],
    queryFn:  () => callCenterApi.lookup(searchPhone, selectedCustomerId).then(r => r.data),
    enabled:  !!searchPhone && searchPhone.trim().length >= 8,
    staleTime: 30_000,
  })

  function normalizePhone(raw) {
    let p = raw.trim().replace(/\s+/g, '')
    if (p.startsWith('+20'))  p = '0' + p.slice(3)
    if (p.startsWith('0020')) p = '0' + p.slice(4)
    return p
  }

  function handleSearch() {
    const clean = normalizePhone(phone)
    if (clean === searchPhone) return
    setSearchPhone(clean)
    setSelectedCustomerId(null)
    setSavedCallId(null)
    setAiDone(false)
    setFlashCase(null)
  }

  function handleSelectCustomer(id) {
    setSelectedCustomerId(id)
    setSavedCallId(null)
    setAiDone(false)
    setFlashCase(null)
  }

  async function handleSaveLog() {
    try {
      const customer = lookupData?.customer
      const { data } = await callCenterApi.create({
        ...logForm,
        phone_number: searchPhone,
        caller_name:  customer?.name || '',
        customer:     customer?.id || null,
      })
      qc.invalidateQueries({ queryKey: ['cc-calls'] })
      setSavedCallId(data.id)
    } catch (err) {
      alert('حدث خطأ أثناء حفظ المكالمة: ' + (err.response?.data?.detail || err.message))
    }
  }

  async function handleAiSummarize() {
    if (!savedCallId) return
    setAiLoading(true)
    try {
      await callCenterApi.summarize(savedCallId)
      setAiDone(true)
    } catch (e) {
      alert('فشل التلخيص: ' + (e.response?.data?.detail || e.message))
    } finally {
      setAiLoading(false)
    }
  }

  const data     = lookupData
  const customer = data?.customer

  // Show picker when multiple customers found and agent hasn't picked one yet.
  // '__unknown__' means agent explicitly chose to log without a customer — skip picker.
  const multipleCustomers = (data?.customers?.length ?? 0) > 1
  const needsPicker       = multipleCustomers && !customer && selectedCustomerId !== '__unknown__'

  const isManager  = ['admin', 'supervisor', 'quality_manager'].includes(user?.role)

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-lg font-black text-gray-900">📞 مركز الاتصال</h1>
            <p className="text-xs text-gray-400 mt-0.5">ادخل رقم الهاتف لعرض بيانات المتصل</p>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/callcenter/cases" className="btn-secondary text-xs py-1.5 px-3">
              🗂️ الحالات
            </Link>
            {isManager && (
              <div className="flex bg-gray-100 rounded-xl p-0.5 text-xs">
                {[{ id: 'operator', label: '📱 موظف' }, { id: 'manager', label: '📊 مدير' }].map(t => (
                  <button key={t.id}
                    onClick={() => setTab(t.id)}
                    className={`px-3 py-1.5 rounded-lg font-bold transition-all
                      ${tab === t.id ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
                    {t.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-5">

        {/* Manager tab */}
        {tab === 'manager' ? (
          <ManagerDashboard />
        ) : (

        <>
          {/* My Queue — always visible; collapses automatically when no cases */}
          <MyQueuePanel onOpenCase={setSelectedCaseId} />

          {/* Search card — phone mode or name/PIC mode */}
          <div className="card mb-5">
            {/* Mode toggle */}
            <div className="flex gap-1 mb-4 bg-gray-100 p-1 rounded-xl w-fit">
              <button
                onClick={() => setSearchMode('phone')}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  searchMode === 'phone'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                📞 بحث بالهاتف
              </button>
              <button
                onClick={() => setSearchMode('name')}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  searchMode === 'name'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                👤 بحث بالاسم / PIC
              </button>
            </div>

            {searchMode === 'phone' ? (
              <div className="flex gap-3 items-end flex-wrap">
                <div className="flex-1 min-w-52">
                  <label className="label text-sm">رقم الهاتف</label>
                  <input
                    className="input-field font-mono text-lg"
                    placeholder="010xxxxxxxx"
                    dir="ltr"
                    value={phone}
                    onChange={e => setPhone(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSearch()}
                    autoFocus
                  />
                </div>
                <button onClick={handleSearch} disabled={phone.length < 8}
                  className="btn-primary text-sm px-6 py-2.5 disabled:opacity-50">
                  🔍 بحث
                </button>
                <button onClick={() => { setPhone(''); setSearchPhone(''); setSavedCallId(null); setAiDone(false) }}
                  className="btn-secondary text-sm">
                  مسح
                </button>
              </div>
            ) : (
              <div>
                <label className="label text-sm">الاسم أو كود PIC</label>
                <CustomerSearchWidget
                  selected={null}
                  onSelect={c => {
                    if (c?.phone) {
                      // Bridge into the phone-lookup flow using the customer's phone
                      setSearchMode('phone')
                      setPhone(c.phone)
                      setSearchPhone(c.phone)
                    }
                    if (c?.id) setSelectedCustomerId(c.id)
                  }}
                  placeholder="ابحث بالاسم أو كود PIC..."
                />
                <p className="text-xs text-gray-400 mt-2">
                  عند اختيار عميل من نتائج البحث يتم تحميل ملفه تلقائياً
                </p>
              </div>
            )}
          </div>

          {lookupLoading || isFetching ? (
            <div className="space-y-3 animate-pulse">
              <div className="h-36 bg-gray-100 rounded-2xl" />
              <div className="h-24 bg-gray-100 rounded-2xl" />
            </div>
          ) : data ? (
            <div className="grid md:grid-cols-3 gap-5">

              {/* ── Left: Patient 360 profile ── */}
              <div className="md:col-span-2 space-y-4">

                {/* ── Customer picker (multiple matches, none selected yet) ── */}
                {needsPicker && (
                  <CustomerPicker
                    customers={data.customers}
                    onSelect={handleSelectCustomer}
                  />
                )}

                {/* ── Multi-customer breadcrumb (shown after selection or skip) ── */}
                {multipleCustomers && !needsPicker && (
                  <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50
                    border border-gray-200 rounded-xl px-3 py-2">
                    <span>👥 {data.customers.length} عملاء بنفس الرقم</span>
                    {customer && (
                      <span className="text-gray-600 font-semibold">· {customer.name}</span>
                    )}
                    <span className="text-gray-300">|</span>
                    <button
                      onClick={() => { setSelectedCustomerId(null); setSavedCallId(null); setFlashCase(null) }}
                      className="text-brand-600 hover:underline font-semibold"
                    >
                      تغيير العميل ←
                    </button>
                  </div>
                )}

                {/* Customer identity card */}
                {customer ? (
                  <div className="card">
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-full bg-brand-100 flex items-center
                        justify-center text-brand-700 font-black text-xl shrink-0">
                        {customer.name[0]}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-black text-gray-900 text-lg">{customer.name}</span>
                          <SegmentBadge segment={customer.segment} />
                          <span className={`badge ${
                            customer.type_label === 'توصيل'
                              ? 'bg-blue-100 text-blue-700'
                              : customer.type_label === 'تأمين صحي'
                              ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-700'
                          }`}>{customer.type_label}</span>
                        </div>

                        {/* Phone + PIC code (always displayed) */}
                        <div className="flex items-center gap-3 mt-1 flex-wrap">
                          <span className="font-mono text-gray-600 text-sm" dir="ltr">
                            {customer.phone}
                          </span>
                          {/* PIC code — always visible, prominent */}
                          <span className={`badge font-mono font-bold text-xs ${
                            customer.softech_pic
                              ? 'bg-purple-100 text-purple-800 border border-purple-200'
                              : 'bg-gray-100 text-gray-400 border border-gray-200'
                          }`}>
                            📋 {customer.softech_pic || 'بدون PIC'}
                          </span>
                          {customer.discount > 0 && (
                            <span className="text-green-600 text-xs font-bold">
                              خصم {customer.discount}%
                            </span>
                          )}
                        </div>

                        {/* Branch — always displayed */}
                        <div className="text-xs mt-0.5 font-semibold">
                          {customer.branch ? (
                            <span className="text-brand-700">🏥 {customer.branch}</span>
                          ) : (
                            <span className="text-gray-400 italic">بدون فرع افتراضي</span>
                          )}
                        </div>

                        {/* LTV + risk */}
                        <div className="mt-2 flex items-center gap-4 flex-wrap">
                          {customer.ltv != null && (
                            <span className="text-xs font-bold text-indigo-700">
                              💰 LTV: {Number(customer.ltv).toLocaleString('en-US')} ج.م
                            </span>
                          )}
                          {customer.days_since_last_visit != null && (
                            <span className="text-xs text-gray-500">
                              🗓️ آخر زيارة: منذ {customer.days_since_last_visit} يوم
                            </span>
                          )}
                        </div>
                        <RiskBar score={customer.complaint_risk_score} />

                        {customer.chronic_conditions && (
                          <div className="mt-2 text-xs bg-purple-50 text-purple-700
                            border border-purple-100 rounded-lg px-2 py-1">
                            💊 {customer.chronic_conditions}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Default delivery location */}
                    {customer.default_location && (
                      <div className="mt-3 bg-blue-50 border border-blue-100 rounded-xl p-3">
                        <div className="text-xs font-bold text-blue-700 mb-1">📍 عنوان التوصيل</div>
                        <div className="text-sm text-gray-700">{customer.default_location.address}</div>
                        <div className="flex gap-3 mt-2">
                          {customer.default_location.maps_url && (
                            <a href={customer.default_location.maps_url} target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-blue-600 hover:underline">🗺️ الخريطة</a>
                          )}
                          {customer.default_location.whatsapp_url && (
                            <a href={customer.default_location.whatsapp_url} target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-green-600 hover:underline">💬 واتساب</a>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ) : !needsPicker ? (
                  <div className="card text-center py-6">
                    <div className="text-3xl mb-2">👤</div>
                    <div className="text-gray-500 font-semibold">عميل جديد — لا توجد بيانات سابقة</div>
                    <div className="text-xs text-gray-400 mt-1 font-mono" dir="ltr">{searchPhone}</div>
                  </div>
                ) : null}

                {/* Open cases — clickable to open chatter */}
                {data.open_cases?.length > 0 && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                      🗂️ الحالات المفتوحة ({data.open_cases.length})
                      <span className="text-gray-300 font-normal mr-1">· اضغط لفتح الدردشة</span>
                    </div>
                    <div className="space-y-2">
                      {data.open_cases.map(c => (
                        <button key={c.id}
                          onClick={() => setSelectedCaseId(c.id)}
                          className="w-full text-right flex items-center gap-3 bg-purple-50 border border-purple-100
                            hover:bg-purple-100 hover:border-purple-200 rounded-xl px-3 py-2.5 transition-all group">
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-sm text-gray-800 truncate group-hover:text-purple-700">{c.title}</div>
                            <div className="text-xs text-gray-500 mt-0.5">{c.case_number} · {c.category}</div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="badge bg-purple-100 text-purple-700 text-xs">{c.status}</span>
                            <span className="text-purple-400 text-xs group-hover:text-purple-600">💬</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Purchase history — last 365 days */}
                {data.purchase_history && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                      🛒 تاريخ المشتريات (365 يوم)
                    </div>
                    {/* Summary row */}
                    <div className="grid grid-cols-3 gap-3 mb-3">
                      <div className="bg-indigo-50 rounded-xl p-2.5 text-center">
                        <div className="text-lg font-black text-indigo-700">
                          {data.purchase_history.visit_count}
                        </div>
                        <div className="text-xs text-indigo-500">فاتورة</div>
                      </div>
                      <div className="bg-green-50 rounded-xl p-2.5 text-center">
                        <div className="text-sm font-black text-green-700">
                          {Number(data.purchase_history.total_365d).toLocaleString('en-US')}
                        </div>
                        <div className="text-xs text-green-500">إجمالي ج.م</div>
                      </div>
                      <div className="bg-blue-50 rounded-xl p-2.5 text-center">
                        <div className="text-sm font-black text-blue-700">
                          {Number(data.purchase_history.avg_basket).toLocaleString('en-US')}
                        </div>
                        <div className="text-xs text-blue-500">متوسط الفاتورة</div>
                      </div>
                    </div>
                    {/* Monthly sparkline-style bars */}
                    {data.purchase_history.months?.length > 0 && (
                      <div className="mb-3">
                        <div className="text-xs text-gray-400 mb-1.5">الشهور الأخيرة</div>
                        <div className="flex items-end gap-1 h-12">
                          {data.purchase_history.months.slice(0, 12).reverse().map(m => {
                            const maxTotal = Math.max(...data.purchase_history.months.map(x => x.total), 1)
                            const pct = Math.round((m.total / maxTotal) * 100)
                            return (
                              <div key={m.month} className="flex-1 flex flex-col items-center gap-0.5"
                                title={`${m.month}: ${m.count} فاتورة`}>
                                <div
                                  className="w-full bg-brand-400 rounded-t"
                                  style={{ height: `${Math.max(pct, 4)}%` }}
                                />
                                <div className="text-gray-400 text-center"
                                  style={{ fontSize: '8px', lineHeight: 1 }}>
                                  {m.month.slice(5)}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    {/* Recent transactions */}
                    {data.purchase_history.recent?.length > 0 && (
                      <div className="space-y-1">
                        <div className="text-xs text-gray-400 mb-1">آخر الفواتير</div>
                        {data.purchase_history.recent.map((t, i) => (
                          <div key={i} className="flex items-center justify-between text-xs
                            border-b border-gray-50 pb-1 last:border-0">
                            <span className="text-gray-500">{t.date}</span>
                            <span className="text-gray-500">{t.branch}</span>
                            <span className="font-bold text-gray-800">
                              {Number(t.amount).toLocaleString('en-US')} ج.م
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Flash case created */}
                {flashCase && (
                  <div className="card border-2 border-green-200 bg-green-50">
                    <div className="font-bold text-green-800">✅ تم فتح الحالة</div>
                    <div className="text-sm text-green-700 mt-1">
                      {flashCase.case_number} — {flashCase.title}
                    </div>
                    <Link to="/callcenter/cases" className="text-xs text-green-600 underline mt-1 block">
                      عرض الحالات ←
                    </Link>
                  </div>
                )}

                {/* Open follow-ups */}
                {data.open_followups?.length > 0 && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                      💊 مهام المتابعة ({data.open_followups.length})
                    </div>
                    <div className="space-y-2">
                      {data.open_followups.map(f => (
                        <div key={f.id}
                          className="flex items-center gap-3 bg-orange-50 border border-orange-100 rounded-xl px-3 py-2">
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-gray-800">{f.item}</div>
                            <div className="text-xs text-gray-500">استحقاق: {f.due_date}</div>
                          </div>
                          <span className="badge bg-orange-100 text-orange-700 text-xs">{f.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Open reservations */}
                {data.open_reservations?.length > 0 && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                      📋 الحجوزات المفتوحة ({data.open_reservations.length})
                    </div>
                    <div className="space-y-2">
                      {data.open_reservations.map(r => (
                        <div key={r.id}
                          className="flex items-center gap-3 bg-blue-50 border border-blue-100 rounded-xl px-3 py-2">
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-gray-800">{r.item}</div>
                            <div className="text-xs text-gray-500">{r.branch}</div>
                          </div>
                          <span className="badge bg-blue-100 text-blue-700 text-xs">{r.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Active demands */}
                {data.active_demands?.length > 0 && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                      🔍 الطلبات المعلقة ({data.active_demands.length})
                    </div>
                    <div className="space-y-2">
                      {data.active_demands.map(d => (
                        <div key={d.id}
                          className="flex items-center gap-3 bg-yellow-50 border border-yellow-100 rounded-xl px-3 py-2">
                          <div className="flex-1">
                            <div className="text-xs text-gray-500">#{d.number} · {d.branch}</div>
                          </div>
                          <span className="badge bg-yellow-100 text-yellow-800 text-xs">{d.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recent calls */}
                {data.recent_calls?.length > 0 && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                      📞 آخر المكالمات
                    </div>
                    <div className="space-y-2">
                      {data.recent_calls.map(c => (
                        <div key={c.id}
                          className="flex items-center gap-3 text-sm border-b border-gray-50 pb-2 last:pb-0 last:border-0">
                          <span className="text-gray-400 tabular-nums text-xs shrink-0">
                            {c.called_at
                              ? toLatinDigits(format(new Date(c.called_at), 'd MMM HH:mm', { locale: ar }))
                              : '—'}
                          </span>
                          <span className="flex-1 text-gray-600 truncate">
                            {c.summary || c.purpose_label}
                          </span>
                          {c.ai_sentiment && (
                            <span className="text-xs shrink-0">
                              {c.ai_sentiment === 'positive' ? '😊' : c.ai_sentiment === 'negative' ? '😟' : '😐'}
                            </span>
                          )}
                          <span className="text-xs text-gray-400 shrink-0">{c.handled_by_name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* ── Right: Log call + actions ── */}
              <div className="space-y-4">
                <div className="card">
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                    📝 تسجيل المكالمة
                  </div>

                  {/* When picker is shown, prompt agent to pick a customer first */}
                  {needsPicker ? (
                    <div className="text-center py-6">
                      <div className="text-3xl mb-2">☝️</div>
                      <div className="text-sm text-gray-500 font-semibold">
                        اختر العميل أولاً من القائمة
                      </div>
                      <div className="text-xs text-gray-400 mt-1">
                        أو سجّل المكالمة بدون تحديد عميل:
                      </div>
                      <button
                        onClick={() => setSelectedCustomerId('__unknown__')}
                        className="mt-3 btn-secondary text-xs py-1.5 px-4"
                      >
                        👤 متصل غير محدد
                      </button>
                    </div>
                  ) : savedCallId ? (
                    <div className="space-y-3">
                      <div className="text-center py-4">
                        <div className="text-3xl mb-2">✅</div>
                        <div className="font-semibold text-green-700">تم التسجيل بنجاح</div>
                        <div className="text-xs text-gray-400 mt-1">رقم المكالمة: #{savedCallId}</div>
                      </div>

                      {/* Post-save actions */}
                      <div className="space-y-2">
                        {customer && (
                          <button
                            onClick={() => setShowCaseModal(true)}
                            className="w-full text-sm btn-secondary text-right px-3 py-2">
                            🗂️ فتح حالة
                          </button>
                        )}
                        {customer && (
                          <button
                            onClick={() => setShowFollowupModal(true)}
                            className="w-full text-sm btn-secondary text-right px-3 py-2">
                            🔔 جدولة متابعة
                          </button>
                        )}
                        <button
                          onClick={handleAiSummarize}
                          disabled={aiLoading || aiDone}
                          className="w-full text-sm btn-secondary text-right px-3 py-2 disabled:opacity-50">
                          {aiLoading ? '⏳ جارٍ التلخيص...' : aiDone ? '✅ تم التلخيص بـ AI' : '🤖 تلخيص AI'}
                        </button>
                      </div>

                      <button onClick={() => { setSavedCallId(null); setAiDone(false); setFlashCase(null) }}
                        className="btn-secondary text-sm w-full mt-1">
                        📞 تسجيل مكالمة أخرى
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div>
                        <label className="label text-xs">الغرض</label>
                        <select className="input-field text-sm" value={logForm.purpose}
                          onChange={e => setLogForm(p => ({ ...p, purpose: e.target.value }))}>
                          {PURPOSE_OPTIONS.map(o => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="label text-xs">الاتجاه</label>
                          <select className="input-field text-sm" value={logForm.direction}
                            onChange={e => setLogForm(p => ({ ...p, direction: e.target.value }))}>
                            <option value="inbound">📲 واردة</option>
                            <option value="outbound">📞 صادرة</option>
                            <option value="whatsapp">💬 واتساب</option>
                          </select>
                        </div>
                        <div>
                          <label className="label text-xs">الحالة</label>
                          <select className="input-field text-sm" value={logForm.status}
                            onChange={e => setLogForm(p => ({ ...p, status: e.target.value }))}>
                            <option value="answered">✅ أجاب</option>
                            <option value="no_answer">📵 لا رد</option>
                            <option value="busy">📶 مشغول</option>
                            <option value="callback">🔄 معاودة</option>
                          </select>
                        </div>
                      </div>
                      <div>
                        <label className="label text-xs">ملخص سريع</label>
                        <input className="input-field text-sm"
                          placeholder="موضوع المكالمة..."
                          value={logForm.summary}
                          onChange={e => setLogForm(p => ({ ...p, summary: e.target.value }))} />
                      </div>
                      <div>
                        <label className="label text-xs">ملاحظات تفصيلية</label>
                        <textarea rows={3} className="input-field resize-none text-sm"
                          value={logForm.notes}
                          onChange={e => setLogForm(p => ({ ...p, notes: e.target.value }))} />
                      </div>
                      <button onClick={handleSaveLog} disabled={!searchPhone}
                        className="btn-primary w-full text-sm disabled:opacity-50">
                        💾 حفظ المكالمة
                      </button>

                      {/* Quick case button before save if complaint purpose */}
                      {logForm.purpose === 'complaint' && customer && !savedCallId && (
                        <p className="text-xs text-orange-600 text-center">
                          ⚠️ تذكر فتح حالة بعد الحفظ
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* Quick actions — available as soon as we have a customer, even before saving */}
                {customer && !savedCallId && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">
                      إجراءات سريعة
                    </div>
                    <div className="space-y-1.5">
                      <button onClick={() => setShowCaseModal(true)}
                        className="w-full text-right text-xs text-purple-700 hover:text-purple-900
                          bg-purple-50 hover:bg-purple-100 rounded-lg px-3 py-2 transition-all">
                        🗂️ فتح حالة جديدة
                      </button>
                      <button onClick={() => setShowFollowupModal(true)}
                        className="w-full text-right text-xs text-orange-700 hover:text-orange-900
                          bg-orange-50 hover:bg-orange-100 rounded-lg px-3 py-2 transition-all">
                        🔔 جدولة متابعة
                      </button>
                    </div>
                  </div>
                )}

                {/* Call Items Panel — available as soon as phone is searched */}
                {searchPhone && (
                  <CallItemsPanel
                    savedCallId={savedCallId}
                    customer={customer}
                    branchId={customer?.branch_id || null}
                  />
                )}

                {/* Customer personalised recommendations */}
                {customer?.id && (
                  <CustomerRecsPanel
                    customerId={customer.id}
                    onAdd={(item) => {
                      // Forward add to CallItemsPanel by simulating catalog add
                      // We dispatch via a CustomEvent the panel listens to
                      window.dispatchEvent(new CustomEvent('cc-add-rec-item', { detail: item }))
                    }}
                  />
                )}

                {/* Quick customer nav */}
                {customer && (
                  <div className="card">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">
                      روابط سريعة
                    </div>
                    <div className="space-y-1">
                      <Link to={`/customers/${customer.id}`}
                        className="block text-xs text-brand-600 hover:underline py-1">
                        👤 بروفايل العميل الكامل →
                      </Link>
                      <Link to="/callcenter/cases"
                        className="block text-xs text-brand-600 hover:underline py-1">
                        🗂️ إدارة الحالات →
                      </Link>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : searchPhone.length >= 8 ? (
            <div className="card text-center py-10">
              <div className="text-3xl mb-2">🔍</div>
              <div className="text-gray-500">لم يتم العثور على بيانات للرقم</div>
              <div className="text-xs text-gray-400 font-mono mt-1" dir="ltr">{searchPhone}</div>
            </div>
          ) : null}
        </>
        )}
      </div>

      {/* Modals — case creation works with or without a saved call */}
      {showCaseModal && customer && (
        <CaseModal
          callId={savedCallId || null}
          customerId={customer.id}
          onClose={() => setShowCaseModal(false)}
          onCreated={c => { setShowCaseModal(false); setFlashCase(c) }}
        />
      )}
      {showFollowupModal && customer && (
        <FollowupModal
          callId={savedCallId || null}
          customerId={customer?.id}
          onClose={() => setShowFollowupModal(false)}
          onCreated={() => setShowFollowupModal(false)}
        />
      )}
      {/* Case chatter overlay */}
      {selectedCaseId && (
        <CaseChatPanel
          caseId={selectedCaseId}
          onClose={() => setSelectedCaseId(null)}
        />
      )}
    </div>
  )
}
