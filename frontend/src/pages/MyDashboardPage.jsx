/**
 * MyDashboardPage — /me
 *
 * A per-user "who am I in SOFTECH" 360° dashboard:
 *   • claim SOFTECH identities (supplier / customer) → admin approves
 *   • arrange configurable widgets that read your data across every role you
 *     play: as a supplier, as an employee-customer, as a salesperson/author,
 *     and your allocated operational tasks (reused from apps/tasks).
 *
 * All widget data flows through /api/personal/widgets/:id/data/, which is
 * hard-scoped server-side to an APPROVED identity claim you own.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { personalApi } from '../api/client'
import useAuthStore from '../store/authStore'
import {
  PageHeader, Modal, EmptyState, Spinner, SectionTitle, useToast,
} from '../components/ui'

const KIND_LABEL = { supplier: 'مورد', customer: 'عميل / موظف', salesperson: 'مسؤول بيع', self: 'شخصي' }
const STATUS_BADGE = {
  pending:  { t: 'قيد المراجعة', c: 'bg-amber-100 text-amber-700' },
  approved: { t: 'معتمد',       c: 'bg-green-100 text-green-700' },
  rejected: { t: 'مرفوض',       c: 'bg-red-100 text-red-700' },
}
const money = (v) => `${Number(v || 0).toLocaleString('en-EG', { maximumFractionDigits: 2 })} ج.م`
const SIZE_SPAN = { sm: 'lg:col-span-1', md: 'lg:col-span-1', lg: 'lg:col-span-2', xl: 'lg:col-span-3' }
// Default look-back per widget type — must match apps/personal/providers.py.
const DEFAULT_PERIOD = {
  supplier_transactions: 90,
  supplier_payments: 180,
  customer_transactions: 180,
  customer_payments: 180,
}
const PERIOD_WIDGETS = Object.keys(DEFAULT_PERIOD)

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Page
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function MyDashboardPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const qc = useQueryClient()
  const toast = useToast()

  const [showAdd, setShowAdd]       = useState(false)
  const [showClaim, setShowClaim]   = useState(false)
  const [showManage, setShowManage] = useState(false)

  const widgetsQ = useQuery({ queryKey: ['personal-widgets'], queryFn: () => personalApi.widgets().then(r => r.data.results) })
  const identsQ  = useQuery({ queryKey: ['personal-identities'], queryFn: () => personalApi.identities().then(r => r.data.results) })

  const widgets    = widgetsQ.data || []
  const identities = identsQ.data || []
  const approved   = identities.filter(i => i.status === 'approved')

  // ── Drag-and-drop reorder ───────────────────────────────────────────────────
  // Keep a local ordered copy so dragging feels instant; re-sync whenever the
  // server list actually changes (add/remove), then persist the new order.
  const [order, setOrder] = useState([])
  useEffect(() => { setOrder(widgetsQ.data || []) }, [widgetsQ.dataUpdatedAt])
  const dragFrom = useRef(null)

  const persistOrder = (list) => {
    personalApi.layout(list.map((w, idx) => ({ id: w.id, position: idx, column: 0 })))
      .then(() => qc.invalidateQueries({ queryKey: ['personal-widgets'] }))
      .catch(() => {})
  }
  const onDragStart = (i) => { dragFrom.current = i }
  const onDragEnter = (i) => {
    const from = dragFrom.current
    if (from === null || from === i) return
    setOrder(prev => {
      const next = [...prev]
      const [moved] = next.splice(from, 1)
      next.splice(i, 0, moved)
      dragFrom.current = i
      return next
    })
  }
  const onDragEnd = () => {
    dragFrom.current = null
    setOrder(prev => { persistOrder(prev); return prev })
  }

  return (
    <div className="pb-20">
      <PageHeader
        title="لوحتي الشخصية"
        subtitle="بياناتك في SOFTECH كمورد وكعميل وكمسؤول بيع + مهامك"
        actions={
          <>
            <button className="btn-secondary" onClick={() => setShowManage(true)}>🪪 هوياتي</button>
            <button className="btn-primary" onClick={() => setShowAdd(true)}>➕ إضافة لوحة</button>
          </>
        }
      />

      <div className="max-w-7xl mx-auto px-4">
        {isAdmin && <AdminApprovalQueue />}

        {widgetsQ.isLoading ? (
          <div className="flex justify-center py-16"><Spinner size="lg" /></div>
        ) : widgets.length === 0 ? (
          <EmptyState
            preset="search"
            title="لوحتك فارغة"
            sub="ابدأ بإضافة لوحة — قد تحتاج أولاً إلى المطالبة بهويتك في SOFTECH واعتمادها"
            action={<button className="btn-primary" onClick={() => setShowAdd(true)}>➕ إضافة لوحة</button>}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
            {order.map((w, i) => (
              <WidgetCard
                key={w.id} widget={w} index={i}
                onDragStart={onDragStart} onDragEnter={onDragEnter} onDragEnd={onDragEnd}
              />
            ))}
          </div>
        )}
      </div>

      {showAdd && (
        <AddWidgetModal
          onClose={() => setShowAdd(false)}
          approvedIdentities={approved}
          onNeedIdentity={() => { setShowAdd(false); setShowClaim(true) }}
          onAdded={() => { setShowAdd(false); qc.invalidateQueries({ queryKey: ['personal-widgets'] }) }}
        />
      )}
      {showManage && (
        <ManageIdentitiesModal
          identities={identities}
          onClose={() => setShowManage(false)}
          onClaimNew={() => { setShowManage(false); setShowClaim(true) }}
          onChanged={() => qc.invalidateQueries({ queryKey: ['personal-identities'] })}
        />
      )}
      {showClaim && (
        <ClaimIdentityModal
          onClose={() => setShowClaim(false)}
          onClaimed={() => {
            setShowClaim(false)
            qc.invalidateQueries({ queryKey: ['personal-identities'] })
            qc.invalidateQueries({ queryKey: ['personal-pending'] })
            toast.success('تم إرسال الطلب', 'بانتظار اعتماد المدير')
          }}
        />
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Widget card
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function WidgetCard({ widget, index, onDragStart, onDragEnter, onDragEnd }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [refreshTick, setRefreshTick] = useState(0)
  const [dragging, setDragging] = useState(false)

  const dataQ = useQuery({
    queryKey: ['personal-widget-data', widget.id, refreshTick],
    queryFn: () => personalApi.widgetData(widget.id, refreshTick > 0).then(r => r.data),
    retry: false,
  })

  const removeM = useMutation({
    mutationFn: () => personalApi.deleteWidget(widget.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['personal-widgets'] }); toast.success('تم الحذف') },
  })

  // Period is optimistic local state so the highlight flips instantly on click,
  // then we persist and refetch. Re-sync if the server value changes elsewhere.
  const [period, setPeriodState] = useState(
    widget.config?.period_days ?? DEFAULT_PERIOD[widget.widget_type] ?? 180
  )
  useEffect(() => {
    if (widget.config?.period_days) setPeriodState(widget.config.period_days)
  }, [widget.config?.period_days])

  const setPeriod = async (days) => {
    if (days === period) return
    setPeriodState(days)                 // instant highlight
    try {
      await personalApi.updateWidget(widget.id, { config: { ...(widget.config || {}), period_days: days } })
    } catch { /* keep optimistic value; next load reconciles */ }
    setRefreshTick(t => t + 1)           // refetch with the persisted period
  }

  const err = dataQ.data?.detail
  const payload = dataQ.data?.data

  return (
    <div
      className={`card ${SIZE_SPAN[widget.size] || ''} flex flex-col transition-opacity ${dragging ? 'opacity-40' : ''}`}
      draggable
      onDragStart={(e) => { setDragging(true); onDragStart?.(index); e.dataTransfer.effectAllowed = 'move' }}
      onDragEnter={() => onDragEnter?.(index)}
      onDragOver={(e) => e.preventDefault()}
      onDragEnd={() => { setDragging(false); onDragEnd?.() }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-gray-300 cursor-move shrink-0 select-none" title="اسحب لإعادة الترتيب">⠿</span>
          <span className="text-lg shrink-0">{widget.catalog_icon}</span>
          <div className="min-w-0">
            <h3 className="font-bold text-sm text-gray-800 truncate">{widget.title || widget.catalog_label}</h3>
            {widget.identity_label && (
              <p className="text-[11px] text-gray-400 truncate">{widget.identity_label}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button title="تحديث" className="text-gray-400 hover:text-brand-600 p-1" onClick={() => setRefreshTick(t => t + 1)}>↻</button>
          <button title="حذف" className="text-gray-400 hover:text-red-600 p-1" onClick={() => removeM.mutate()}>✕</button>
        </div>
      </div>

      {PERIOD_WIDGETS.includes(widget.widget_type) && (
        <div className="flex gap-1 mb-2 flex-wrap">
          {[30, 90, 180, 365].map(d => (
            <button key={d}
              className={`text-[11px] px-2 py-0.5 rounded-full border transition-colors ${period === d ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-200 text-gray-500 hover:border-gray-300'}`}
              onClick={() => setPeriod(d)}>{d}ي</button>
          ))}
        </div>
      )}

      <div className="flex-1 min-h-[80px]">
        {dataQ.isLoading ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : err ? (
          <div className="text-xs text-amber-600 bg-amber-50 rounded-lg p-3">{err}</div>
        ) : payload?.error ? (
          <div className="text-xs text-amber-600 bg-amber-50 rounded-lg p-3">تعذّر جلب البيانات: {payload.error}</div>
        ) : (
          <WidgetBody type={widget.widget_type} payload={payload} />
        )}
      </div>

      {dataQ.data?._cached && (
        <p className="text-[10px] text-gray-300 mt-2">مخزّن مؤقتاً</p>
      )}
    </div>
  )
}

// ── type-specific body renderers ──────────────────────────────────────────────

function WidgetBody({ type, payload }) {
  if (!payload) return <EmptyMini />
  switch (type) {
    case 'supplier_transactions':
    case 'customer_transactions': return <TxnBody payload={payload} />
    case 'supplier_payments':
    case 'customer_payments':     return <PaymentsBody payload={payload} />
    case 'my_sales':              return <MySalesBody payload={payload} />
    case 'my_analytics':          return <MyAnalyticsBody payload={payload} />
    case 'my_narrative_reports':  return <NarrativeBody payload={payload} />
    case 'my_tasks':              return <TasksBody payload={payload} />
    default:                      return <pre className="text-[10px] overflow-auto">{JSON.stringify(payload, null, 1)}</pre>
  }
}

const EmptyMini = () => <p className="text-xs text-gray-400 text-center py-4">لا توجد بيانات</p>

function Kpi({ label, value, tone = 'text-gray-800' }) {
  return (
    <div className="bg-gray-50 rounded-lg px-3 py-2">
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className={`text-sm font-bold ${tone}`}>{value}</div>
    </div>
  )
}

function TxnBody({ payload }) {
  const s = payload.summary || {}
  const lines = payload.lines || []
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="صافي القيمة" value={money(s.net_value)} tone={Number(s.net_value) < 0 ? 'text-red-600' : 'text-green-700'} />
        <Kpi label="عدد المستندات" value={s.doc_count || 0} />
      </div>
      {lines.length === 0 ? <EmptyMini /> : (
        <div className="max-h-56 overflow-auto -mx-1">
          <table className="w-full text-[11px]">
            <thead className="text-gray-400 sticky top-0 bg-white">
              <tr><th className="text-right px-1 py-1">التاريخ</th><th className="text-right px-1">الصنف</th><th className="text-left px-1">كمية</th><th className="text-left px-1">القيمة</th></tr>
            </thead>
            <tbody>
              {lines.slice(0, 60).map((l, i) => (
                <tr key={i} className="border-t border-gray-50">
                  <td className="px-1 py-1 text-gray-500 whitespace-nowrap">{(l.docdate || '').slice(0, 10)}</td>
                  <td className="px-1 text-gray-700">{l.itemcode}</td>
                  <td className="px-1 text-left">{Number(l.qty || 0)}</td>
                  <td className="px-1 text-left text-gray-700">{Number(l.line_value || 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function PaymentsBody({ payload }) {
  const cheques = (payload.cheques || []).filter(x => !x._error)
  const pays    = (payload.payments || payload.custpayments || []).filter(x => !x._error)
  const rows = [
    ...cheques.map(c => ({ date: c.pay_date, amount: c.amount, kind: 'شيك' })),
    ...pays.map(p => ({ date: p.pay_date, amount: p.amount, kind: 'دفعة' })),
  ].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  const total = rows.reduce((s, r) => s + Number(r.amount || 0), 0)
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="الإجمالي" value={money(total)} />
        <Kpi label="عدد الحركات" value={rows.length} />
      </div>
      {rows.length === 0 ? <EmptyMini /> : (
        <div className="max-h-56 overflow-auto">
          <table className="w-full text-[11px]">
            <tbody>
              {rows.slice(0, 60).map((r, i) => (
                <tr key={i} className="border-t border-gray-50">
                  <td className="px-1 py-1 text-gray-500">{(r.date || '').slice(0, 10)}</td>
                  <td className="px-1"><span className="text-[10px] bg-gray-100 rounded px-1.5 py-0.5">{r.kind}</span></td>
                  <td className="px-1 text-left text-gray-700">{Number(r.amount || 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function MySalesBody({ payload }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Kpi label="إجمالي المبيعات" value={money(payload.revenue)} tone="text-green-700" />
      <Kpi label="عدد الفواتير" value={payload.invoices || 0} />
      <Kpi label="المرتجعات" value={money(payload.returns_value)} tone="text-red-600" />
      <Kpi label="عدد المرتجعات" value={payload.returns_count || 0} />
    </div>
  )
}

function MyAnalyticsBody({ payload }) {
  const items = payload.top_items || []
  const channels = payload.channels || []
  return (
    <div className="space-y-2">
      {channels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {channels.map((c, i) => (
            <span key={i} className="text-[10px] bg-brand-50 text-brand-700 rounded-full px-2 py-0.5">
              {c.channel}: {money(c.value)}
            </span>
          ))}
        </div>
      )}
      {items.length === 0 ? <EmptyMini /> : (
        <div className="max-h-52 overflow-auto">
          <table className="w-full text-[11px]">
            <tbody>
              {items.map((t, i) => (
                <tr key={i} className="border-t border-gray-50">
                  <td className="px-1 py-1 text-gray-700 truncate max-w-[140px]">{t.name}</td>
                  <td className="px-1 text-left">{Number(t.qty || 0)}</td>
                  <td className="px-1 text-left text-gray-600">{Number(t.value || 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const SEV = {
  critical: 'bg-red-100 text-red-700', warning: 'bg-amber-100 text-amber-700', info: 'bg-sky-100 text-sky-700',
}
function NarrativeBody({ payload }) {
  const f = payload.findings || []
  if (f.length === 0) return <EmptyMini />
  return (
    <div className="max-h-60 overflow-auto space-y-1.5">
      {f.map((x, i) => (
        <div key={i} className="flex items-start gap-2 text-[11px]">
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${SEV[x.severity] || 'bg-gray-100'}`}>{x.severity}</span>
          <span className="text-gray-600 leading-snug">{x.message_ar}</span>
        </div>
      ))}
    </div>
  )
}

const PRIO = { urgent: 'text-red-600', high: 'text-orange-600', normal: 'text-gray-500', low: 'text-gray-400' }
function TasksBody({ payload }) {
  const tasks = payload.tasks || []
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="مهام مفتوحة" value={payload.open || 0} />
        <Kpi label="متأخرة" value={payload.overdue || 0} tone={payload.overdue ? 'text-red-600' : 'text-gray-800'} />
      </div>
      {tasks.length === 0 ? <EmptyMini /> : (
        <div className="max-h-56 overflow-auto space-y-1">
          {tasks.map(t => (
            <div key={t.id} className="flex items-center justify-between gap-2 text-[11px] border-t border-gray-50 py-1">
              <span className="text-gray-700 truncate">{t.title}</span>
              <div className="flex items-center gap-2 shrink-0">
                {t.due_date && <span className="text-gray-400">{(t.due_date || '').slice(0, 10)}</span>}
                <span className={PRIO[t.priority] || 'text-gray-400'}>●</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Add-widget modal
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function AddWidgetModal({ onClose, approvedIdentities, onNeedIdentity, onAdded }) {
  const toast = useToast()
  const [picked, setPicked]     = useState(null)
  const [identityId, setIdentityId] = useState('')
  const [title, setTitle]       = useState('')

  const catQ = useQuery({ queryKey: ['personal-catalog'], queryFn: () => personalApi.catalog().then(r => r.data.results) })
  const catalog = catQ.data || []

  const needsIdentity = picked && (picked.kind === 'supplier' || picked.kind === 'customer')
  const options = approvedIdentities.filter(i => i.kind === picked?.kind)

  const addM = useMutation({
    mutationFn: () => personalApi.addWidget({
      widget_type: picked.widget_type,
      identity: needsIdentity ? Number(identityId) : undefined,
      title: title || undefined,
    }),
    onSuccess: onAdded,
    onError: (e) => toast.error('تعذّرت الإضافة', e?.response?.data?.detail || ''),
  })

  const canAdd = picked && (!needsIdentity || identityId)

  return (
    <Modal open onClose={onClose} title="إضافة لوحة" maxWidth="max-w-2xl"
      footer={
        <div className="flex gap-2">
          <button className="btn-secondary flex-1" onClick={onClose}>إلغاء</button>
          <button className="btn-primary flex-1 disabled:opacity-40" disabled={!canAdd || addM.isPending} onClick={() => addM.mutate()}>
            {addM.isPending ? <Spinner size="sm" color="white" /> : 'إضافة'}
          </button>
        </div>
      }>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {catalog.map(c => (
          <button key={c.widget_type}
            onClick={() => { setPicked(c); setIdentityId('') }}
            className={`text-right p-3 rounded-xl border transition ${picked?.widget_type === c.widget_type ? 'border-brand-500 bg-brand-50' : 'border-gray-200 hover:border-gray-300'}`}>
            <div className="flex items-center gap-2">
              <span className="text-lg">{c.icon}</span>
              <span className="font-bold text-sm text-gray-800">{c.label}</span>
            </div>
            <p className="text-[11px] text-gray-400 mt-1">{c.desc}</p>
            <span className="inline-block mt-1 text-[10px] bg-gray-100 rounded px-1.5 py-0.5 text-gray-500">{KIND_LABEL[c.kind]}</span>
          </button>
        ))}
      </div>

      {picked && (
        <div className="mt-4 space-y-3 border-t border-gray-100 pt-3">
          <input className="input w-full" placeholder="عنوان مخصص (اختياري)" value={title} onChange={e => setTitle(e.target.value)} />
          {needsIdentity && (
            options.length === 0 ? (
              <div className="text-xs bg-amber-50 text-amber-700 rounded-lg p-3">
                لا توجد هوية {KIND_LABEL[picked.kind]} معتمدة.
                <button className="underline mr-1" onClick={onNeedIdentity}>اطلب هوية الآن</button>
              </div>
            ) : (
              <select className="input w-full" value={identityId} onChange={e => setIdentityId(e.target.value)}>
                <option value="">— اختر هويتك ({KIND_LABEL[picked.kind]}) —</option>
                {options.map(o => <option key={o.id} value={o.id}>{o.label || o.person_code} ({o.person_code})</option>)}
              </select>
            )
          )}
        </div>
      )}
    </Modal>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Claim-identity modal
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ClaimIdentityModal({ onClose, onClaimed }) {
  const toast = useToast()
  const [kind, setKind] = useState('supplier')
  const [q, setQ]       = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)

  const doSearch = async () => {
    if (q.trim().length < 2) return
    setSearching(true)
    try {
      const { data } = await personalApi.searchPersons(q.trim(), kind)
      setResults(data.results || [])
    } catch (e) {
      toast.error('تعذّر البحث', e?.response?.data?.detail || '')
    } finally { setSearching(false) }
  }

  const claimM = useMutation({
    mutationFn: (p) => personalApi.claimIdentity({ kind, person_code: p.person_code, label: p.name }),
    onSuccess: onClaimed,
    onError: (e) => toast.error('تعذّر الطلب', e?.response?.data?.detail || ''),
  })

  return (
    <Modal open onClose={onClose} title="المطالبة بهوية SOFTECH" subtitle="ابحث عن كودك في سجلّ الأشخاص ثم اطلب اعتماده"
      maxWidth="max-w-xl">
      <div className="flex gap-2 mb-3">
        {['supplier', 'customer'].map(k => (
          <button key={k} onClick={() => { setKind(k); setResults([]) }}
            className={`flex-1 py-2 rounded-lg text-sm border ${kind === k ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-200 text-gray-600'}`}>
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>
      <div className="flex gap-2 mb-3">
        <input className="input flex-1" placeholder="ابحث بالاسم أو الكود…" value={q}
          onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()} />
        <button className="btn-primary" onClick={doSearch} disabled={searching}>{searching ? <Spinner size="sm" color="white" /> : 'بحث'}</button>
      </div>
      <div className="max-h-72 overflow-auto space-y-1">
        {results.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-6">اكتب كلمة بحث ثم اضغط بحث</p>
        ) : results.map(r => (
          <div key={r.person_code} className="flex items-center justify-between gap-2 p-2 rounded-lg hover:bg-gray-50">
            <div className="min-w-0">
              <div className="text-sm text-gray-800 truncate">{r.name}</div>
              <div className="text-[11px] text-gray-400">كود: {r.person_code} {r.ptcode ? `· نوع ${r.ptcode}` : ''}</div>
            </div>
            <button className="btn-secondary text-xs shrink-0" disabled={claimM.isPending} onClick={() => claimM.mutate(r)}>
              اطلب اعتماد
            </button>
          </div>
        ))}
      </div>
    </Modal>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Manage-identities modal
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ManageIdentitiesModal({ identities, onClose, onClaimNew, onChanged }) {
  const toast = useToast()
  const delM = useMutation({
    mutationFn: (id) => personalApi.deleteIdentity(id),
    onSuccess: () => { onChanged(); toast.success('تم الحذف') },
  })
  return (
    <Modal open onClose={onClose} title="هوياتي في SOFTECH" maxWidth="max-w-xl"
      footer={<button className="btn-primary w-full" onClick={onClaimNew}>➕ المطالبة بهوية جديدة</button>}>
      {identities.length === 0 ? (
        <EmptyState title="لا توجد هويات" sub="اطلب هويتك كمورد أو كعميل ليعتمدها المدير" />
      ) : (
        <div className="space-y-2">
          {identities.map(i => {
            const b = STATUS_BADGE[i.status] || {}
            return (
              <div key={i.id} className="flex items-center justify-between gap-2 p-3 rounded-xl border border-gray-100">
                <div className="min-w-0">
                  <div className="text-sm font-bold text-gray-800 truncate">{i.label || i.person_code}</div>
                  <div className="text-[11px] text-gray-400">{KIND_LABEL[i.kind]} · كود {i.person_code}</div>
                  {i.review_note && <div className="text-[11px] text-gray-400 mt-0.5">ملاحظة: {i.review_note}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`text-[10px] rounded-full px-2 py-0.5 ${b.c}`}>{b.t}</span>
                  <button className="text-gray-300 hover:text-red-600" onClick={() => delM.mutate(i.id)}>✕</button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Modal>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Admin approval queue
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function AdminApprovalQueue() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['personal-pending'], queryFn: () => personalApi.pendingIdentities().then(r => r.data.results) })
  const pending = q.data || []

  const reviewM = useMutation({
    mutationFn: ({ id, action }) => personalApi.reviewIdentity(id, action),
    onSuccess: () => {
      // refresh BOTH the queue and the identities list — an approval makes the
      // identity immediately bindable in the "add widget" picker.
      qc.invalidateQueries({ queryKey: ['personal-pending'] })
      qc.invalidateQueries({ queryKey: ['personal-identities'] })
      toast.success('تم')
    },
  })

  if (pending.length === 0) return null
  return (
    <div className="mt-4 card border-amber-200 bg-amber-50/40">
      <SectionTitle icon="🪪">طلبات اعتماد الهويات ({pending.length})</SectionTitle>
      <div className="space-y-2">
        {pending.map(p => (
          <div key={p.id} className="flex items-center justify-between gap-2 bg-white rounded-xl p-3 border border-gray-100">
            <div className="min-w-0">
              <div className="text-sm font-bold text-gray-800 truncate">{p.staff_name} → {p.label || p.person_code}</div>
              <div className="text-[11px] text-gray-400">{KIND_LABEL[p.kind]} · كود {p.person_code}{p.note ? ` · ${p.note}` : ''}</div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button className="btn-primary text-xs" onClick={() => reviewM.mutate({ id: p.id, action: 'approve' })}>اعتماد</button>
              <button className="btn-secondary text-xs" onClick={() => reviewM.mutate({ id: p.id, action: 'reject' })}>رفض</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
