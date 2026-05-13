/**
 * DemandPage.jsx  —  /demand
 * Demand & Lost Sales Engine — list view + create modal
 */
import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { demandApi, branchesApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Design tokens ─────────────────────────────────────────────────────────────
const BRAND  = '#1B6B3A'
const GREEN  = '#10b981'
const BLUE   = '#3b82f6'
const ORANGE = '#f59e0b'
const RED    = '#ef4444'
const PURPLE = '#8b5cf6'
const GRAY   = '#9ca3af'

const STATUS_CFG = {
  new:       { label: 'جديد',              dot: ORANGE, bg: '#fffbeb', text: '#92400e' },
  assigned:  { label: 'مُعيَّن',           dot: BLUE,   bg: '#eff6ff', text: '#1e40af' },
  follow_up: { label: 'متابعة',            dot: PURPLE, bg: '#f5f3ff', text: '#5b21b6' },
  contacted: { label: 'تم التواصل',        dot: BRAND,  bg: '#f0f9f4', text: '#1B6B3A' },
  waiting:   { label: 'ينتظر المخزون',    dot: GRAY,   bg: '#f9fafb', text: '#6b7280' },
  fulfilled: { label: 'تم التوريد',        dot: GREEN,  bg: '#f0fdf4', text: '#166534' },
  lost:      { label: 'بيع ضائع',          dot: RED,    bg: '#fef2f2', text: '#991b1b' },
  cancelled: { label: 'ملغي',              dot: GRAY,   bg: '#f9fafb', text: '#9ca3af' },
}

const PRIORITY_CFG = {
  low:     { label: 'منخفض',           cls: 'bg-gray-100 text-gray-500'   },
  normal:  { label: 'عادي',            cls: 'bg-blue-100 text-blue-700'   },
  high:    { label: 'عالٍ',            cls: 'bg-orange-100 text-orange-700' },
  urgent:  { label: 'عاجل 🔴',        cls: 'bg-red-100 text-red-700'     },
  chronic: { label: 'مزمن 💊',        cls: 'bg-purple-100 text-purple-700' },
}

const SOURCE_OPTIONS = [
  { value: 'walk_in',      label: '🚶 حضر للفرع' },
  { value: 'phone',        label: '📞 اتصال' },
  { value: 'whatsapp',     label: '💬 واتساب' },
  { value: 'delivery_app', label: '📱 تطبيق توصيل' },
  { value: 'online',       label: '🌐 موقع' },
  { value: 'internal',     label: '⚙️ داخلي' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(d) {
  if (!d) return '—'
  try { return formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true }) } catch { return '' }
}

function StatusBadge({ status }) {
  const s = STATUS_CFG[status] || STATUS_CFG.new
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.text }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  )
}

function PriorityBadge({ priority }) {
  const p = PRIORITY_CFG[priority] || PRIORITY_CFG.normal
  return <span className={`badge text-xs ${p.cls}`}>{p.label}</span>
}

function SlaChip({ slaStatus, minsRemaining }) {
  if (!slaStatus || slaStatus === 'ok') return null
  const isBreached = slaStatus === 'breached'
  return (
    <span className={`badge text-xs ${isBreached ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'}`}>
      {isBreached ? '⚠ SLA تجاوز' : `⏱ ${minsRemaining}د`}
    </span>
  )
}

// ── Item search input ─────────────────────────────────────────────────────────

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
    queryKey: ['item-search-demand', debouncedQ],
queryFn: () => itemsApi.list({ search: debouncedQ, page_size: 10 }).then(r => r.data.results || r.data),
enabled: debouncedQ.length >= 2,
    staleTime: 10_000,
  })

  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  return (
    <div ref={ref} className="relative">
      <input className="input-field text-sm" placeholder="ابحث بالاسم أو كود SOFTECH..."
        value={q} onChange={e => { setQ(e.target.value); setOpen(true) }} autoComplete="off" />
      {open && q.length >= 2 && results?.length > 0 && (
        <div className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-52 overflow-y-auto">
          {results.map(item => (
            <button key={item.id} type="button"
              className="w-full text-right px-4 py-2.5 hover:bg-brand-50 transition-colors border-b border-gray-50 last:border-0"
              onClick={() => { onSelect(item); setQ(''); setOpen(false) }}>
              <div className="font-semibold text-gray-800 text-sm">{item.name}</div>
              <div className="flex gap-3 mt-0.5">
                <span className="text-xs text-blue-500 font-mono">كود: {item.softech_id}</span>
                {item.name_scientific && <span className="text-xs text-gray-400 italic truncate">{item.name_scientific}</span>}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Create Demand Modal ───────────────────────────────────────────────────────

function CreateDemandModal({ branches, userBranchId, onClose, onCreated }) {
  const [form, setForm] = useState({
    branch: String(userBranchId || ''),
    contact_phone: '',
    contact_name: '',
    phcode: '',
    source_channel: 'walk_in',
    priority: 'normal',
    notes: '',
  })
  const [items, setItems] = useState([])   // [{item, qty, notes}]
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  function f(field) { return e => setForm(prev => ({ ...prev, [field]: e.target.value })) }

  function addItem(item) {
    if (items.find(i => i.item.id === item.id)) return
    setItems(p => [...p, { item, qty: '1', notes: '' }])
  }

  function removeItem(idx) { setItems(p => p.filter((_, i) => i !== idx)) }

  function updateItem(idx, field, val) {
    setItems(p => p.map((row, i) => i === idx ? { ...row, [field]: val } : row))
  }

  async function handleSubmit() {
    if (!form.contact_phone.trim()) { setError('رقم الهاتف مطلوب'); return }
    if (!form.branch)               { setError('اختر الفرع'); return }
    if (items.length === 0)         { setError('أضف صنفاً واحداً على الأقل'); return }
    const bad = items.find(i => !i.qty || Number(i.qty) <= 0)
    if (bad) { setError(`أدخل الكمية لـ: ${bad.item.name}`); return }

    setSubmitting(true); setError('')
    try {
      const res = await demandApi.create({
        ...form,
        branch: Number(form.branch),
        items: items.map(i => ({ item: i.item.id, quantity: i.qty, notes: i.notes || '' })),
      })
      onCreated(res.data.id)
      onClose()
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' — ') : 'حدث خطأ')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <div>
            <h2 className="font-black text-gray-900 text-base">تسجيل طلب عميل جديد</h2>
            <p className="text-xs text-gray-400 mt-0.5">صنف غير متوفر · طلب غير مُستوفى · بيع ضائع محتمل</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl p-1">✕</button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">

          {/* Customer identity */}
          <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 space-y-3">
            <div className="text-xs font-bold text-blue-700">هوية العميل</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label text-xs">رقم الهاتف *</label>
                <input className="input-field" placeholder="010xxxxxxxx" dir="ltr"
                  value={form.contact_phone} onChange={f('contact_phone')} autoFocus />
              </div>
              <div>
                <label className="label text-xs">الاسم</label>
                <input className="input-field" placeholder="اسم العميل"
                  value={form.contact_name} onChange={f('contact_name')} />
              </div>
            </div>
            <div>
              <label className="label text-xs">كود العميل PIC (اختياري)</label>
              <input className="input-field font-mono text-sm" placeholder="مثال: 140HD515"
                dir="ltr" value={form.phcode} onChange={f('phcode')} />
              <p className="text-xs text-blue-500 mt-1">
                إذا كان العميل معروفاً في الـ ERP — سيتم البحث تلقائياً بالهاتف إذا تُرك فارغاً
              </p>
            </div>
          </div>

          {/* Branch + source + priority */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label text-xs">الفرع *</label>
              <select className="input-field" value={form.branch} onChange={f('branch')}>
                <option value="">اختر...</option>
                {(branches || []).map(b => (
                  <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label text-xs">مصدر الطلب</label>
              <select className="input-field" value={form.source_channel} onChange={f('source_channel')}>
                {SOURCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label text-xs">الأولوية</label>
              <select className="input-field" value={form.priority} onChange={f('priority')}>
                {Object.entries(PRIORITY_CFG).map(([v, c]) => (
                  <option key={v} value={v}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Items */}
          <div>
            <label className="label text-xs mb-2">الأصناف المطلوبة *</label>
            <ItemSearch onSelect={addItem} />
            <p className="text-xs text-gray-400 mt-1">اكتب حرفين للبحث — بالاسم أو كود SOFTECH</p>
          </div>

          {items.length === 0 ? (
            <div className="border-2 border-dashed border-gray-200 rounded-xl py-6 text-center">
              <div className="text-3xl mb-1">💊</div>
              <div className="text-sm text-gray-400">ابحث عن صنف أعلاه لإضافته</div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs font-bold text-gray-500">الأصناف المضافة ({items.length})</div>
              {items.map((row, idx) => (
                <div key={row.item.id}
                  className="flex items-center gap-3 bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-gray-800 text-sm truncate">{row.item.name}</div>
                    <div className="text-xs text-blue-500 font-mono">كود: {row.item.softech_id}</div>
                  </div>
                  <input type="number" min="0.001" step="0.001" placeholder="كمية"
                    value={row.qty} onChange={e => updateItem(idx, 'qty', e.target.value)}
                    className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:border-brand-400" />
                  <input placeholder="ملاحظة" value={row.notes}
                    onChange={e => updateItem(idx, 'notes', e.target.value)}
                    className="w-28 border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand-400" />
                  <button onClick={() => removeItem(idx)}
                    className="text-gray-300 hover:text-red-400 text-xl leading-none">✕</button>
                </div>
              ))}
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="label text-xs">ملاحظات</label>
            <textarea rows={2} className="input-field resize-none text-sm"
              placeholder="أي تفاصيل إضافية..."
              value={form.notes} onChange={f('notes')} />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t flex-shrink-0 flex items-center justify-between gap-3">
          <div className="text-xs text-gray-400">
            {items.length > 0
              ? `${items.length} صنف · سيتم البحث عن العميل في الـ ERP تلقائياً`
              : 'أضف أصناف للمتابعة'}
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
            <button onClick={handleSubmit}
              disabled={submitting || items.length === 0}
              className="btn-primary text-sm disabled:opacity-50">
              {submitting ? 'جارٍ...' : '📋 تسجيل الطلب'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Demand Row ────────────────────────────────────────────────────────────────

function DemandRow({ demand, onClick }) {
  const s = STATUS_CFG[demand.status] || STATUS_CFG.new
  const p = PRIORITY_CFG[demand.priority] || PRIORITY_CFG.normal
  return (
    <tr onClick={onClick}
      className="cursor-pointer hover:bg-brand-50 transition-colors border-b border-gray-50 last:border-0">
      <td className="px-4 py-3">
        <div className="font-bold text-brand-700 font-mono text-sm">{demand.demand_number}</div>
        <div className="text-xs text-gray-400 mt-0.5">{timeAgo(demand.created_at)}</div>
      </td>
      <td className="px-4 py-3">
        <div className="font-semibold text-gray-800 text-sm">{demand.contact_name || '—'}</div>
        <div className="text-xs text-gray-500 font-mono" dir="ltr">{demand.contact_phone}</div>
        {demand.phcode && (
          <div className="text-xs text-blue-400 font-mono mt-0.5">{demand.phcode}</div>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-gray-600">{demand.branch_name}</td>
      <td className="px-4 py-3 text-xs text-gray-500 tabular-nums">{demand.total_items} صنف</td>
      <td className="px-4 py-3">
        <StatusBadge status={demand.status} />
      </td>
      <td className="px-4 py-3">
        <span className={`badge text-xs ${p.cls}`}>{p.label}</span>
      </td>
      <td className="px-4 py-3">
        <SlaChip slaStatus={demand.sla_status} minsRemaining={demand.sla_minutes_remaining} />
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">{demand.assigned_name || '—'}</td>
    </tr>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DemandPage() {
  const navigate      = useNavigate()
  const qc            = useQueryClient()
  const { user }      = useAuthStore()

  const [showCreate, setShowCreate] = useState(false)
  const [filters, setFilters] = useState({
    status: '', priority: '', branch: '', search: '', sla_breached: '',
  })

  const [searchInput, setSearchInput] = useState('')

// Debounce search
useEffect(() => {
  const delay = setTimeout(() => {
    setFilters(f => ({ ...f, search: searchInput }))
  }, 400)

  return () => clearTimeout(delay)
}, [searchInput])

  const isCCOrAdmin   = ['admin', 'call_center', 'purchasing'].includes(user?.role)
  const userBranchId  = user?.branch_id

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const { data: demands = [], isLoading } = useQuery({
    queryKey: [
  'demands',
  filters.status,
  filters.priority,
  filters.branch,
  filters.search,
  filters.sla_breached,
],
    queryFn: () => demandApi.list({
      status:       filters.status       || undefined,
      priority:     filters.priority     || undefined,
      branch:       filters.branch       || undefined,
      search:       filters.search       || undefined,
      sla_breached: filters.sla_breached || undefined,
    }).then(r => r.data.results || r.data),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })

  const activeCount  = demands.filter(d => !['fulfilled', 'lost', 'cancelled'].includes(d.status)).length
  const lostCount    = demands.filter(d => d.status === 'lost').length
  const breachCount  = demands.filter(d => d.sla_breached).length

  const TAB_FILTERS = [
    { label: 'الكل',              value: '' },
    { label: 'جديد',             value: 'new' },
    { label: 'مُعيَّن',          value: 'assigned' },
    { label: 'متابعة',           value: 'follow_up' },
    { label: 'تم التواصل',        value: 'contacted' },
    { label: 'ينتظر المخزون',    value: 'waiting' },
    { label: 'بيع ضائع',         value: 'lost' },
    { label: 'تم التوريد',        value: 'fulfilled' },
  ]

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center gap-4 flex-wrap">
            <div>
              <h1 className="text-lg font-black text-gray-900">طلبات العملاء والطلب الضائع</h1>
              <p className="text-xs text-gray-400 mt-0.5">
                {demands.length} طلب إجمالي
                {activeCount  > 0 && <span className="text-brand-600 mr-2">· {activeCount} نشط</span>}
                {lostCount    > 0 && <span className="text-red-600 mr-2">· {lostCount} بيع ضائع</span>}
                {breachCount  > 0 && <span className="text-red-600 font-bold mr-2">· {breachCount} ⚠ SLA تجاوز</span>}
              </p>
            </div>
            <div className="flex-1" />
            <button
              onClick={() => navigate('/demand/dashboard')}
              className="btn-secondary text-sm">
              📊 لوحة الطلب الضائع
            </button>
            <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
              + تسجيل طلب جديد
            </button>
          </div>

          {/* Status tab strip */}
          <div className="flex gap-1 mt-3 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
            {TAB_FILTERS.map(t => (
              <button key={t.value}
                onClick={() => setFilters(p => ({ ...p, status: t.value }))}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                  filters.status === t.value
                    ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
                style={filters.status === t.value ? { background: BRAND } : {}}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Search + filters row */}
          <div className="flex gap-2 mt-2 flex-wrap">
            <input className="input-field w-52 text-xs"
  placeholder="🔍 بحث بالهاتف، اسم العميل، PIC، الصنف..."
  value={searchInput}
  onChange={e => setSearchInput(e.target.value)}
/>
            <select className="input-field w-36 text-xs" value={filters.priority}
              onChange={e => setFilters(p => ({ ...p, priority: e.target.value }))}>
              <option value="">كل الأولويات</option>
              {Object.entries(PRIORITY_CFG).map(([v, c]) => (
                <option key={v} value={v}>{c.label}</option>
              ))}
            </select>
            {isCCOrAdmin && (
              <select className="input-field w-44 text-xs" value={filters.branch}
                onChange={e => setFilters(p => ({ ...p, branch: e.target.value }))}>
                <option value="">كل الفروع</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
              </select>
            )}
            <select className="input-field w-40 text-xs" value={filters.sla_breached}
              onChange={e => setFilters(p => ({ ...p, sla_breached: e.target.value }))}>
              <option value="">كل الطلبات</option>
              <option value="true">⚠ SLA تجاوز فقط</option>
            </select>
            <button className="btn-secondary text-xs px-3"
  onClick={() => {
    setFilters({ status: '', priority: '', branch: '', search: '', sla_breached: '' })
    setSearchInput('')
  }}>
              مسح
            </button>
          </div>
        </div>
      </div>

      {/* List */}
      <div className="max-w-7xl mx-auto px-6 py-5">
        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1,2,3,4,5].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl" />)}
          </div>
        ) : demands.length === 0 ? (
          <div className="card text-center py-16">
            <div className="text-5xl mb-3">📋</div>
            <div className="text-gray-600 font-semibold">
              {filters.status || filters.search ? 'لا توجد نتائج' : 'لا توجد طلبات بعد'}
            </div>
            <div className="text-gray-400 text-xs mt-1 mb-5">
              {!filters.status && !filters.search && 'اضغط "+ تسجيل طلب جديد" لبدء تتبع الطلب الضائع'}
            </div>
            {!filters.status && !filters.search && (
              <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
                + تسجيل طلب جديد
              </button>
            )}
          </div>
        ) : (
          <div className="card p-0 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">رقم الطلب</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">العميل</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الفرع</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الأصناف</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الحالة</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الأولوية</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">SLA</th>
                    <th className="text-right px-4 py-3 text-xs font-semibond text-gray-500">مُعيَّن لـ</th>
                  </tr>
                </thead>
                <tbody>
                  {demands.map(d => (
                    <DemandRow key={d.id} demand={d}
                      onClick={() => navigate(`/demand/${d.id}`)} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {showCreate && (
        <CreateDemandModal
          branches={branches}
          userBranchId={userBranchId}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            qc.invalidateQueries(['demands'])
            navigate(`/demand/${id}`)
          }}
        />
      )}
    </div>
  )
}
