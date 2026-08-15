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
import { useState, useEffect, useRef, useMemo } from 'react'
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
  my_sales: 30,
  my_analytics: 90,
}
const PERIOD_WIDGETS = Object.keys(DEFAULT_PERIOD)
// Width cycle: 1 col → 2 cols → full width. Maps to PersonalWidget.size.
const SIZE_ORDER = ['md', 'lg', 'xl']
const SIZE_HINT = { md: 'عرض ١', lg: 'عرض ٢', xl: 'عرض كامل' }
// Widgets whose documents carry an editable SOFTECH remarks field.
const WIDGET_KIND_EDITABLE = ['supplier_transactions', 'customer_transactions', 'supplier_payments', 'customer_payments']
// Widgets whose branch filter is applied SERVER-SIDE (aggregates) → refetch on change.
// Transaction/payment widgets filter client-side (rows already loaded), so no refetch.
const SERVER_BRANCH_FILTER = ['my_sales', 'my_analytics']

// Multi-select branch chips (client-side filter, persisted in widget config).
function BranchFilter({ options, selected, onChange }) {
  if (!options || options.length <= 1) return null
  const toggle = (b) => {
    const set = new Set(selected)
    set.has(b) ? set.delete(b) : set.add(b)
    onChange([...set])
  }
  return (
    <div className="flex gap-1 mb-2 flex-wrap items-center">
      <span className="text-[13px] text-gray-400 ml-1">الفروع:</span>
      {options.map(b => (
        <button key={b} onClick={() => toggle(b)}
          className={`text-[13px] px-2 py-0.5 rounded-full border transition-colors ${selected.includes(b) ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-200 text-gray-500 hover:border-gray-300'}`}>
          فرع {b}
        </button>
      ))}
      {selected.length > 0 && (
        <button onClick={() => onChange([])} className="text-[13px] text-gray-400 underline">مسح</button>
      )}
    </div>
  )
}

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
  const capsQ    = useQuery({ queryKey: ['personal-caps'], queryFn: () => personalApi.capabilities().then(r => r.data) })
  const canEditComments = capsQ.data?.can_edit_erp_comments || false

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
                key={w.id} widget={w} index={i} canEdit={canEditComments}
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

function WidgetCard({ widget, index, canEdit, onDragStart, onDragEnter, onDragEnd }) {
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

  const cycleSize = async () => {
    const cur = SIZE_ORDER.includes(widget.size) ? widget.size : 'md'
    const next = SIZE_ORDER[(SIZE_ORDER.indexOf(cur) + 1) % SIZE_ORDER.length]
    try {
      await personalApi.updateWidget(widget.id, { size: next })
      qc.invalidateQueries({ queryKey: ['personal-widgets'] })
    } catch { /* no-op */ }
  }
  const wide = widget.size === 'lg' || widget.size === 'xl'

  const cfg = widget.config || {}
  const saveBranches = async (arr) => {
    try {
      await personalApi.updateWidget(widget.id, { config: { ...cfg, branches: arr } })
      qc.invalidateQueries({ queryKey: ['personal-widgets'] })
      // aggregate widgets recompute server-side → refetch; row widgets filter locally
      if (SERVER_BRANCH_FILTER.includes(widget.widget_type)) setRefreshTick(t => t + 1)
    } catch { /* no-op */ }
  }

  const err = dataQ.data?.detail
  const payload = dataQ.data?.data
  const branchOptions = useMemo(() => {
    if (Array.isArray(payload?.branches)) return payload.branches   // server facet
    const src = payload?.documents || payload?.cheques || []
    return [...new Set(src.map(x => x && x.branchcode).filter(Boolean))].sort()
  }, [payload])

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
          <span className="text-xl shrink-0">{widget.catalog_icon}</span>
          <div className="min-w-0">
            <h3 className="font-bold text-base text-gray-800 truncate">{widget.title || widget.catalog_label}</h3>
            {widget.identity_label && (
              <p className="text-sm text-gray-400 truncate">{widget.identity_label}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button title={`العرض: ${SIZE_HINT[widget.size] || SIZE_HINT.md} — اضغط للتوسيع`} className="text-gray-400 hover:text-brand-600 p-1" onClick={cycleSize}>⤢</button>
          <button title="تحديث" className="text-gray-400 hover:text-brand-600 p-1" onClick={() => setRefreshTick(t => t + 1)}>↻</button>
          <button title="حذف" className="text-gray-400 hover:text-red-600 p-1" onClick={() => removeM.mutate()}>✕</button>
        </div>
      </div>

      {PERIOD_WIDGETS.includes(widget.widget_type) && (
        <div className="flex gap-1 mb-2 flex-wrap">
          {[30, 90, 180, 365].map(d => (
            <button key={d}
              className={`text-sm px-2 py-0.5 rounded-full border transition-colors ${period === d ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-200 text-gray-500 hover:border-gray-300'}`}
              onClick={() => setPeriod(d)}>{d}ي</button>
          ))}
        </div>
      )}
      {PERIOD_WIDGETS.includes(widget.widget_type) && (
        <BranchFilter options={branchOptions} selected={cfg.branches || []} onChange={saveBranches} />
      )}

      <div className="flex-1 min-h-[80px]">
        {dataQ.isLoading ? (
          <div className="flex justify-center py-6"><Spinner /></div>
        ) : err ? (
          <div className="text-xs text-amber-600 bg-amber-50 rounded-lg p-3">{err}</div>
        ) : payload?.error ? (
          <div className="text-xs text-amber-600 bg-amber-50 rounded-lg p-3">تعذّر جلب البيانات: {payload.error}</div>
        ) : (
          <WidgetBody
            type={widget.widget_type} payload={payload} wide={wide}
            widgetId={widget.id} branches={cfg.branches || []}
            canEdit={canEdit && (WIDGET_KIND_EDITABLE.includes(widget.widget_type))}
            onSaved={() => setRefreshTick(t => t + 1)}
          />
        )}
      </div>

      {dataQ.data?._cached && (
        <p className="text-[13px] text-gray-300 mt-2">مخزّن مؤقتاً</p>
      )}
    </div>
  )
}

// ── type-specific body renderers ──────────────────────────────────────────────

function WidgetBody({ type, payload, wide, widgetId, canEdit, onSaved, branches }) {
  if (!payload) return <EmptyMini />
  switch (type) {
    case 'supplier_transactions':
    case 'customer_transactions': return <TxnBody payload={payload} wide={wide} widgetId={widgetId} canEdit={canEdit} onSaved={onSaved} branches={branches} />
    case 'supplier_payments':
    case 'customer_payments':     return <PaymentsBody payload={payload} widgetId={widgetId} canEdit={canEdit} onSaved={onSaved} branches={branches} />
    case 'my_sales':              return <MySalesBody payload={payload} />
    case 'my_analytics':          return <MyAnalyticsBody payload={payload} />
    case 'my_narrative_reports':  return <NarrativeBody payload={payload} />
    case 'my_tasks':              return <TasksBody payload={payload} />
    default:                      return <pre className="text-[13px] overflow-auto">{JSON.stringify(payload, null, 1)}</pre>
  }
}

const EmptyMini = () => <p className="text-xs text-gray-400 text-center py-4">لا توجد بيانات</p>

function Kpi({ label, value, tone = 'text-gray-800' }) {
  return (
    <div className="bg-gray-50 rounded-lg px-3 py-2">
      <div className="text-[13px] text-gray-400">{label}</div>
      <div className={`text-xl font-bold ${tone}`}>{value}</div>
    </div>
  )
}

const DOCCODE_LABEL = { '10': 'شراء', '120': 'مرتجع شراء', '115': 'بيع', '30': 'مرتجع بيع' }

// Revision toggle + drift-fix. Marks a document/cheque revised in our ledger AND
// stamps the SOFTECH remark; if the stamp was removed in native SOFTECH (drift),
// offers a one-click re-stamp. `kind` = 'document' | 'cheque'.
function RevisionControl({ item, kind, widgetId, canEdit, onSaved }) {
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  const revised = !!item.revised
  const drift = revised && item.stamp_drift

  const setRev = async (val) => {
    setSaving(true)
    try {
      const body = kind === 'cheque'
        ? { widget_id: widgetId, kind: 'cheque', branchcode: item.branchcode,
            doccode: item.financialdoccode, docnumber: item.cheqsno, revised: val }
        : { widget_id: widgetId, kind: 'document', branchcode: item.branchcode,
            doccode: item.doccode, docnumber: item.docnumber, revised: val }
      const { data } = await personalApi.setRevision(body)
      const ok = data.ok
      toast[ok ? 'success' : 'error'](
        ok ? (val ? 'تمت المراجعة' : 'أُلغيت المراجعة') : 'لم يكتمل — أحد الخوادم غير متصل',
        ok ? 'المركز والفرع: تم' : (data.warning || `المركز: ${data.hq_result} · الفرع: ${data.branch_result}`))
      onSaved?.()
    } catch (e) {
      toast.error('تعذّر', e?.response?.data?.detail || '')
    } finally { setSaving(false) }
  }

  return (
    <div className="flex items-center justify-between gap-2 mt-1.5 pt-1.5 border-t border-gray-200 text-sm">
      <div className="flex items-center gap-2 min-w-0">
        {revised
          ? <span className="text-green-700 font-medium whitespace-nowrap">✔ تمت المراجعة{item.revision_code ? ` #${item.revision_code}` : ''}</span>
          : <span className="text-gray-400 whitespace-nowrap">لم تُراجع</span>}
        {drift && <span className="text-amber-600 whitespace-nowrap" title="الختم مفقود من ملاحظات SOFTECH">⚠ الختم مفقود</span>}
      </div>
      {canEdit && (
        <div className="flex gap-1.5 shrink-0">
          {drift && (
            <button disabled={saving} onClick={() => setRev(true)} className="btn-secondary text-[13px] px-2 py-0.5">إعادة الختم</button>
          )}
          <button disabled={saving} onClick={() => setRev(!revised)}
            className={`text-[13px] px-2 py-0.5 rounded ${revised ? 'btn-secondary' : 'btn-primary'} disabled:opacity-50`}>
            {saving ? '...' : (revised ? 'إلغاء المراجعة' : '✔ تمييز كمُراجَع')}
          </button>
        </div>
      )}
    </div>
  )
}
const DOCCODE_TONE = {
  '10': 'bg-green-100 text-green-700', '115': 'bg-green-100 text-green-700',
  '120': 'bg-red-100 text-red-700',    '30': 'bg-red-100 text-red-700',
}
// Money always shows 2 decimals (matches SOFTECH's currency rounding); SOFTECH
// line values carry sub-cent float artifacts (e.g. 13044.9964 → 13,045.00).
const money2 = (v) => (v == null ? '—' : Number(v).toLocaleString('en-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
// Quantities keep their real precision (e.g. 0.333), never forced to 2 dp.
const qtyFmt = (v) => (v == null ? '—' : Number(v).toLocaleString('en-EG', { maximumFractionDigits: 3 }))
const fmtDoc = (v) => String(v ?? '').replace(/\.0+$/, '')   // 10791.0 → 10791

// One row per DOCUMENT (transaction); click to expand its item lines with full
// names. `wide` (widget size lg/xl) lays the items out in two columns.
function TxnBody({ payload, wide, widgetId, canEdit, onSaved, branches }) {
  const s = payload.summary || {}
  const docs = (payload.documents || []).filter(d => !branches?.length || branches.includes(d.branchcode))
  const [sel, setSel] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  const toggle = (i, open) => { setSel(open ? null : i); setEditing(false) }

  const saveComment = async (d) => {
    setSaving(true)
    try {
      const { data } = await personalApi.setComment({
        widget_id: widgetId, branchcode: d.branchcode, doccode: d.doccode,
        docnumber: d.docnumber, comment: draft,
      })
      const ok = data.ok
      toast[ok ? 'success' : 'error'](
        ok ? 'تم الحفظ في SOFTECH' : 'لم يكتمل الحفظ — أحد الخوادم غير متصل',
        ok ? 'المركز والفرع: تم' : (data.warning || `المركز: ${data.hq_result} · الفرع: ${data.branch_result}`),
      )
      setEditing(false)
      onSaved?.()
    } catch (e) {
      toast.error('تعذّر الحفظ', e?.response?.data?.detail || '')
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="صافي القيمة" value={money(s.net_value)} tone={Number(s.net_value) < 0 ? 'text-red-600' : 'text-green-700'} />
        <Kpi label="عدد المستندات" value={s.doc_count || docs.length} />
      </div>
      {docs.length === 0 ? <EmptyMini /> : (
        <div className="max-h-[32rem] overflow-auto -mx-1 divide-y divide-gray-100">
          {docs.slice(0, 80).map((d, i) => {
            const open = sel === i
            return (
              <div key={i}>
                <button
                  onClick={() => toggle(i, open)}
                  className={`w-full text-right px-2 py-1.5 ${open ? 'bg-brand-50' : 'hover:bg-gray-50'}`}
                >
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-gray-300 shrink-0">{open ? '▾' : '▸'}</span>
                    <span className="text-gray-500 whitespace-nowrap shrink-0">{(d.docdate || '').slice(0, 10)}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[13px] shrink-0 ${DOCCODE_TONE[d.doccode] || 'bg-gray-100 text-gray-500'}`}>
                      {DOCCODE_LABEL[d.doccode] || d.doccode}
                    </span>
                    <span className="mr-auto font-bold text-gray-800 whitespace-nowrap">{money2(d.line_total)}</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-[13px] text-gray-400 pr-4 mt-0.5 flex-wrap">
                    <span className="whitespace-nowrap">مستند #{fmtDoc(d.docnumber)}</span>
                    <span className="text-gray-300">·</span>
                    <span className="whitespace-nowrap">فرع {d.branchcode}</span>
                    <span className="text-gray-300">·</span>
                    <span className="whitespace-nowrap">{d.items.length} صنف</span>
                    {d.user && (
                      <>
                        <span className="text-gray-300">·</span>
                        <span className="whitespace-nowrap" title="أدخلها">👤 {d.user}</span>
                      </>
                    )}
                    {d.revised && (
                      <>
                        <span className="text-gray-300">·</span>
                        <span className="text-green-600 whitespace-nowrap" title={`تمت المراجعة${d.revision_code ? ' #' + d.revision_code : ''}`}>✔{d.stamp_drift ? ' ⚠' : ''}</span>
                      </>
                    )}
                    {d.comments && (
                      <>
                        <span className="text-gray-300">·</span>
                        <span className="text-amber-600 truncate max-w-[240px]" title={d.comments}>📝 {d.comments}</span>
                      </>
                    )}
                  </div>
                </button>
                {open && (
                  <div className="px-2 pb-2 pt-1 bg-brand-50/30">
                    <div className={`grid gap-1 ${wide ? 'grid-cols-2' : 'grid-cols-1'}`}>
                      {d.items.map((it, j) => (
                        <div key={j} className="bg-white rounded-lg px-2 py-1.5 border border-gray-100">
                          <div className="text-gray-800 text-sm font-medium leading-snug">{it.item_name || it.itemcode}</div>
                          <div className="flex items-center justify-between text-[13px] text-gray-400 mt-1">
                            <span>كود {it.itemcode}</span>
                            <span className="text-gray-600">
                              {qtyFmt(it.qty)} × {money2(it.unit_price)} = <span className="text-gray-800 font-semibold">{money2(it.line_value)}</span>
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="flex justify-between text-sm pt-1.5 mt-1.5 border-t border-gray-200">
                      <span className="text-gray-400">إجمالي المستند</span>
                      <span className="font-bold text-gray-800">{money2(d.docvalue)} ج.م</span>
                    </div>
                    <div className="mt-1">
                      {editing ? (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-gray-400">📝 ملاحظات</span>
                            <span className="text-[12px] text-gray-400">{draft.length}/100</span>
                          </div>
                          <textarea
                            value={draft} maxLength={100} rows={2} autoFocus
                            onChange={(e) => setDraft(e.target.value)}
                            className="w-full text-sm border border-gray-200 rounded-lg p-1.5 focus:outline-none focus:border-brand-500"
                            placeholder="اكتب ملاحظة (تُكتب في SOFTECH — المركز والفرع)"
                          />
                          <div className="flex gap-1.5">
                            <button disabled={saving} onClick={() => saveComment(d)}
                              className="btn-primary text-sm px-3 py-1 disabled:opacity-50">
                              {saving ? '...' : 'حفظ في SOFTECH'}
                            </button>
                            <button disabled={saving} onClick={() => setEditing(false)}
                              className="btn-secondary text-sm px-3 py-1">إلغاء</button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-gray-400">📝 ملاحظات</span>
                            {canEdit && (
                              <button onClick={() => { setDraft(d.comments || ''); setEditing(true) }}
                                className="text-gray-400 hover:text-brand-600" title="تعديل الملاحظة">✏️ تعديل</button>
                            )}
                          </div>
                          <div className="text-sm text-gray-800 leading-relaxed break-words whitespace-pre-wrap mt-1">{d.comments || '—'}</div>
                        </div>
                      )}
                    </div>
                    <RevisionControl item={d} kind="document" widgetId={widgetId} canEdit={canEdit} onSaved={onSaved} />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// Real payment method comes from the bank type (0 = خزينة/cash, 1 = bank),
// NOT cheqtype (which mislabels cash-box entries as "شيك").
const payMethod = (c) => {
  const bt = String(c?.banktype ?? '')
  if (bt === '0') return 'نقدى'
  if (bt === '1') return 'بنكي'
  return ''
}

function Detail({ k, v }) {
  return (
    <div className="flex justify-between gap-2 min-w-0">
      <span className="text-gray-400 shrink-0">{k}</span>
      <span className="text-gray-800 font-medium text-left truncate" title={String(v ?? '—')}>{v ?? '—'}</span>
    </div>
  )
}

// One row per cheque; click to expand its details, with an editable remarks
// field (cheques.chequenote) written to HQ + branch like document comments.
function PaymentsBody({ payload, widgetId, canEdit, onSaved, branches }) {
  const cheques = (payload.cheques || [])
    .filter(x => !x._error)
    .filter(c => !branches?.length || branches.includes(c.branchcode))
  const total = cheques.reduce((s, c) => s + Number(c.amount || 0), 0)
  const [sel, setSel] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()
  const toggle = (i, open) => { setSel(open ? null : i); setEditing(false) }

  const saveNote = async (c) => {
    setSaving(true)
    try {
      const { data } = await personalApi.setChequeNote({
        widget_id: widgetId, branchcode: c.branchcode,
        financialdoccode: c.financialdoccode, cheqsno: c.cheqsno, note: draft,
      })
      const ok = data.ok
      toast[ok ? 'success' : 'error'](
        ok ? 'تم الحفظ في SOFTECH' : 'لم يكتمل الحفظ — أحد الخوادم غير متصل',
        ok ? 'المركز والفرع: تم' : (data.warning || `المركز: ${data.hq_result} · الفرع: ${data.branch_result}`),
      )
      setEditing(false)
      onSaved?.()
    } catch (e) {
      toast.error('تعذّر الحفظ', e?.response?.data?.detail || '')
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="الإجمالي" value={money(total)} />
        <Kpi label="عدد الحركات" value={cheques.length} />
      </div>
      {cheques.length === 0 ? <EmptyMini /> : (
        <div className="max-h-[32rem] overflow-auto -mx-1 divide-y divide-gray-100">
          {cheques.slice(0, 80).map((c, i) => {
            const open = sel === i
            return (
              <div key={i}>
                <button onClick={() => toggle(i, open)}
                  className={`w-full text-right px-2 py-1.5 ${open ? 'bg-brand-50' : 'hover:bg-gray-50'}`}>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-gray-300 shrink-0">{open ? '▾' : '▸'}</span>
                    <span className="text-gray-500 whitespace-nowrap shrink-0">{(c.pay_date || '').slice(0, 10)}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[13px] shrink-0 ${DOCCODE_TONE[c.financialdoccode] || 'bg-gray-100 text-gray-500'}`}>
                      {DOCCODE_LABEL[c.financialdoccode] || 'شيك'}
                    </span>
                    <span className="mr-auto font-bold text-gray-800 whitespace-nowrap">{money2(c.amount)}</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-[13px] text-gray-400 pr-4 mt-0.5 flex-wrap">
                    <span className="whitespace-nowrap">رقم #{c.cheqno || fmtDoc(c.cheqsno)}</span>
                    <span className="text-gray-300">·</span>
                    <span className="whitespace-nowrap">فرع {c.branchcode}</span>
                    {payMethod(c) && (<><span className="text-gray-300">·</span><span className="whitespace-nowrap font-medium">{payMethod(c)}</span></>)}
                    {c.bankname && (<><span className="text-gray-300">·</span><span className="whitespace-nowrap truncate max-w-[200px]" title={c.bankname}>{c.bankname}</span></>)}
                    {c.user && (<><span className="text-gray-300">·</span><span className="whitespace-nowrap">👤 {c.user}</span></>)}
                    {c.revised && (<><span className="text-gray-300">·</span><span className="text-green-600 whitespace-nowrap" title={`تمت المراجعة${c.revision_code ? ' #' + c.revision_code : ''}`}>✔{c.stamp_drift ? ' ⚠' : ''}</span></>)}
                    {c.note && (<><span className="text-gray-300">·</span><span className="text-amber-600 truncate max-w-[240px]" title={c.note}>📝 {c.note}</span></>)}
                  </div>
                </button>
                {open && (
                  <div className="px-2 pb-2 pt-1 bg-brand-50/30 text-sm">
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                      <Detail k="رقم المرجع" v={c.cheqno || '—'} />
                      <Detail k="طريقة الدفع" v={payMethod(c) || '—'} />
                      <Detail k="الخزينة / البنك" v={c.bankname || '—'} />
                      <Detail k="نوع المستند" v={DOCCODE_LABEL[c.financialdoccode] || c.financialdoccode} />
                      <Detail k="الفرع" v={c.branchcode} />
                      <Detail k="المبلغ" v={money2(c.amount)} />
                      <Detail k="الرصيد بعد" v={money2(c.balance)} />
                      <Detail k="سُلّم إلى" v={c.handedto || '—'} />
                      <Detail k="أدخلها" v={c.user || '—'} />
                    </div>
                    <div className="mt-1.5 pt-1.5 border-t border-gray-200">
                      {editing ? (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-gray-400">📝 ملاحظات الشيك</span>
                            <span className="text-[12px] text-gray-400">{draft.length}/250</span>
                          </div>
                          <textarea value={draft} maxLength={250} rows={2} autoFocus
                            onChange={(e) => setDraft(e.target.value)}
                            className="w-full text-sm border border-gray-200 rounded-lg p-1.5 focus:outline-none focus:border-brand-500"
                            placeholder="اكتب ملاحظة (تُكتب في SOFTECH — المركز والفرع)" />
                          <div className="flex gap-1.5">
                            <button disabled={saving} onClick={() => saveNote(c)}
                              className="btn-primary text-sm px-3 py-1 disabled:opacity-50">
                              {saving ? '...' : 'حفظ في SOFTECH'}
                            </button>
                            <button disabled={saving} onClick={() => setEditing(false)}
                              className="btn-secondary text-sm px-3 py-1">إلغاء</button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-gray-400">📝 ملاحظات</span>
                            {canEdit && (
                              <button onClick={() => { setDraft(c.note || ''); setEditing(true) }}
                                className="text-gray-400 hover:text-brand-600" title="تعديل ملاحظة الشيك">✏️ تعديل</button>
                            )}
                          </div>
                          <div className="text-sm text-gray-800 leading-relaxed break-words whitespace-pre-wrap mt-1">{c.note || '—'}</div>
                        </div>
                      )}
                    </div>
                    <RevisionControl item={c} kind="cheque" widgetId={widgetId} canEdit={canEdit} onSaved={onSaved} />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function MySalesBody({ payload }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
      <Kpi label="إجمالي المبيعات" value={money(payload.revenue)} tone="text-green-700" />
      <Kpi label="عدد الفواتير" value={qtyFmt(payload.invoices)} />
      <Kpi label="متوسط الفاتورة" value={money(payload.avg_invoice)} />
      <Kpi label="عدد العملاء" value={qtyFmt(payload.customers)} />
      <Kpi label="عدد الوحدات" value={qtyFmt(payload.units)} />
      <Kpi label="صافي الربح" value={money(payload.gross_profit)}
           tone={Number(payload.gross_profit) < 0 ? 'text-red-600' : 'text-green-700'} />
      <Kpi label="هامش الربح" value={`${qtyFmt(payload.margin)}%`} />
      <Kpi label="المرتجعات" value={money(payload.returns_value)} tone="text-red-600" />
      <Kpi label="عدد المرتجعات" value={qtyFmt(payload.returns_count)} />
    </div>
  )
}

function MyAnalyticsBody({ payload }) {
  const items = payload.top_items || []
  const channels = payload.channels || []
  return (
    <div className="space-y-4">
      {channels.length > 0 && (
        <div>
          <div className="text-[13px] text-gray-400 mb-1.5">المبيعات حسب القناة</div>
          <div className="flex flex-wrap gap-1.5">
            {channels.map((c, i) => (
              <span key={i} className="text-[13px] bg-brand-50 text-brand-700 rounded-lg px-2.5 py-1">
                <span className="font-semibold">{c.channel_label || `قناة ${c.channel}`}</span>
                {' — '}{money(c.value)}
                {c.invoices ? <span className="text-brand-400"> · {c.invoices} فاتورة</span> : null}
              </span>
            ))}
          </div>
        </div>
      )}
      <div>
        <div className="text-[13px] text-gray-400 mb-1.5">أعلى الأصناف مبيعاً</div>
        {items.length === 0 ? <EmptyMini /> : (
          <div className="max-h-[26rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="text-gray-400 sticky top-0 bg-white z-10">
                <tr>
                  <th className="text-right px-1 py-1 font-medium">الصنف</th>
                  <th className="text-left px-1 font-medium whitespace-nowrap">الكمية</th>
                  <th className="text-left px-1 font-medium whitespace-nowrap">القيمة (ج.م)</th>
                </tr>
              </thead>
              <tbody>
                {items.map((t, i) => (
                  <tr key={i} className="border-t border-gray-50">
                    <td className="px-1 py-1.5 text-gray-700">
                      <div className="truncate max-w-[300px]" title={t.name}>{t.name}</div>
                      <div className="text-[12px] text-gray-400">كود {t.softech_id || '—'}</div>
                    </td>
                    <td className="px-1 text-left align-top">{qtyFmt(t.qty)}</td>
                    <td className="px-1 text-left align-top text-gray-600">{money2(t.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
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
        <div key={i} className="flex items-start gap-2 text-sm">
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[13px] ${SEV[x.severity] || 'bg-gray-100'}`}>{x.severity}</span>
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
            <div key={t.id} className="flex items-center justify-between gap-2 text-sm border-t border-gray-50 py-1">
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
            <p className="text-sm text-gray-400 mt-1">{c.desc}</p>
            <span className="inline-block mt-1 text-[13px] bg-gray-100 rounded px-1.5 py-0.5 text-gray-500">{KIND_LABEL[c.kind]}</span>
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
              <div className="text-sm text-gray-400">كود: {r.person_code} {r.ptcode ? `· نوع ${r.ptcode}` : ''}</div>
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
                  <div className="text-sm text-gray-400">{KIND_LABEL[i.kind]} · كود {i.person_code}</div>
                  {i.review_note && <div className="text-sm text-gray-400 mt-0.5">ملاحظة: {i.review_note}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`text-[13px] rounded-full px-2 py-0.5 ${b.c}`}>{b.t}</span>
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
              <div className="text-sm text-gray-400">{KIND_LABEL[p.kind]} · كود {p.person_code}{p.note ? ` · ${p.note}` : ''}</div>
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
