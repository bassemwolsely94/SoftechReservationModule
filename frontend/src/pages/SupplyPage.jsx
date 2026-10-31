/**
 * SupplyPage.jsx — /supply workspace «التوريد والمعدلات» (under المشتريات).
 *
 * Doc 24 orchestration (supply/*.jsx): صندوق الإتاحة (supplier offers → need → order list)
 * and متابعة النواقص (daily case follow-up → draft transfers / orders). No SOFTECH writes.
 *
 * Two governed areas over our engine's SOFTECH writebacks:
 *   1. معدلات البيع (Feature 1) — push engine monthly_avg → SOFTECH stkbal.monthlyqty,
 *      as a proposed → approved → executed lifecycle (SalesRatePush). Live writes stay
 *      gated behind SALES_RATE_WRITER_ENABLED (server-enforced); the banner reflects it.
 *   2. طلبات التوريد / ISR (Feature 2) — read-only preview for now; writer pending.
 *
 * Backend owns every rule; this screen only displays decisions and triggers the
 * gated approve/execute actions.
 */
import { useState, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { supplyApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import AvailabilityInboxTab from './supply/AvailabilityInboxTab'
import SupplyCasesTab from './supply/SupplyCasesTab'
import IsrFulfilmentTab from './supply/IsrFulfilmentTab'
import BranchRequestsTab from './supply/BranchRequestsTab'
import SupplierComparisonTab from './supply/SupplierComparisonTab'
import PurchasePricesTab from './supply/PurchasePricesTab'
import ReceiptCheckTab from './supply/ReceiptCheckTab'
import { wildcardMatch } from '../utils/wildcard'
import useBranchLabels from '../hooks/useBranchLabels'
import useHelpTab from '../help/useHelpTab'
import { SortTh, useSort, downloadBlob } from './supply/supplyUi'
import { IsrRulePanel, IsrParamsSummary, useIsrRuleSettings } from './supply/IsrRuleControls'
import { fa } from '../utils/flowArrow'

const STATUS = {
  proposed:  ['مقترح',  'bg-amber-100 text-amber-800 border-amber-200'],
  approved:  ['معتمد',  'bg-blue-100 text-blue-800 border-blue-200'],
  executed:  ['مُنفّذ',  'bg-emerald-100 text-emerald-800 border-emerald-200'],
  failed:    ['فشل',    'bg-rose-100 text-rose-700 border-rose-200'],
  cancelled: ['ملغى',   'bg-gray-100 text-gray-600 border-gray-200'],
}

function Badge({ s }) {
  const [label, cls] = STATUS[s] || [s, 'bg-gray-100 text-gray-600 border-gray-200']
  return <span className={`text-xs px-2 py-0.5 rounded-full border ${cls}`}>{label}</span>
}

function fmtDate(d) {
  if (!d) return '—'
  try { return new Date(d).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' }) }
  catch { return String(d).slice(0, 16) }
}

const n = (v, d = 1) => (v === null || v === undefined || v === '' ? '—' : Number(v).toFixed(d))

const SUPPLY_TABS = [
  ['inbox', 'صندوق الإتاحة'], ['compare', 'مقارنة الموردين'], ['prices', 'مقارنة أسعار الشراء'], ['cases', 'متابعة النواقص'],
  ['rates', 'معدلات البيع'], ['isr', 'طلبات التوريد / ISR'], ['isrfill', 'تلبية طلبات الفروع'],
  ['wa', 'طلبات واتساب'], ['dist', 'التوزيعة'], ['receipts', 'استلام بدون طلب'],
]
const TAB_KEY = 'supply_last_tab'

function readLastTab() {
  try { return localStorage.getItem(TAB_KEY) } catch { return null }
}

export default function SupplyPage() {
  // ?tab= deep link wins, else this user's last tab (per-viewer convenience), else the inbox.
  const [params, setParams] = useSearchParams()
  const valid = SUPPLY_TABS.map(([k]) => k)
  const fromUrl = params.get('tab')
  const tab = valid.includes(fromUrl) ? fromUrl
    : (valid.includes(readLastTab()) ? readLastTab() : 'inbox')
  useHelpTab(tab)
  const setTab = (k) => {
    try { localStorage.setItem(TAB_KEY, k) } catch { /* storage blocked — URL still works */ }
    setParams(p => { const n = new URLSearchParams(p); n.set('tab', k); return n }, { replace: true })
  }

  return (
    <div className="p-4 space-y-4" dir="rtl">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold text-content">التوريد والمعدلات</h1>
        <span className="text-xs text-content/50">الإتاحة والنواقص والتحويلات ومعدلات الإستهلاك وطلبات التوريد</span>
      </div>

      {/* Supply decisions span stock availability, consumption (sales) + incoming (purchases) */}
      <DataFreshnessBar domains={['stock', 'sales', 'purchases']} />

      <div className="flex gap-1 border-b border-line overflow-x-auto" data-tour="purchasing-supply-tabs">
        {SUPPLY_TABS.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 transition whitespace-nowrap ${
              tab === k ? 'border-primary text-primary' : 'border-transparent text-content/60 hover:text-content'}`}>
            {l}
          </button>
        ))}
      </div>

      {tab === 'inbox' ? <AvailabilityInboxTab />
        : tab === 'compare' ? <SupplierComparisonTab />
        : tab === 'prices' ? <PurchasePricesTab />
        : tab === 'cases' ? <SupplyCasesTab />
        : tab === 'rates' ? <RatesTab />
        : tab === 'isr' ? <IsrTab />
        : tab === 'isrfill' ? <IsrFulfilmentTab />
        : tab === 'wa' ? <BranchRequestsTab />
        : tab === 'receipts' ? <ReceiptCheckTab /> : <DistributionTab />}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Feature 1 — Sales-rate writeback
// ══════════════════════════════════════════════════════════════════════════════

// Advanced (Croston) knobs the معدلات البيع screen can override. Keys must match
// rate_writer._ADV_PARAM_WHITELIST; empty string = use the engine default.
const ADV_FIELDS = [
  { key: 'history_months',            label: 'شهور التاريخ',   step: 1,    hint: 'نافذة الإحصاء (شهور)' },
  { key: 'trend_months',             label: 'شهور الاتجاه',   step: 1,    hint: 'شهور حساب ميل الاتجاه' },
  { key: 'trend_clamp',              label: 'حدّ الاتجاه',    step: 0.05, hint: 'أقصى تعديل للاتجاه (±)' },
  { key: 'bulk_cap_factor',          label: 'حدّ الجملة',     step: 0.5,  hint: 'شهر أعلى من الوسيط×هذا يُهذَّب' },
  { key: 'base_rate_halflife_months', label: 'نصف عمر الحداثة', step: 0.5, hint: 'ترجيح حداثة المعدل الأساسي' },
]
const ADV_DEFAULTS = ADV_FIELDS.reduce((o, f) => { o[f.key] = ''; return o }, {})

// Only send numeric, non-empty knobs (the backend whitelists them anyway).
function cleanAdvParams(adv) {
  const out = {}
  for (const f of ADV_FIELDS) {
    const v = adv[f.key]
    if (v !== '' && v != null && !Number.isNaN(Number(v))) out[f.key] = Number(v)
  }
  return out
}

function RatesTab() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState(null)
  const [branch, setBranch] = useState('')
  const [item, setItem] = useState('')
  const [method, setMethod] = useState('pivot')
  const [target, setTarget] = useState('both')
  const [showAdv, setShowAdv] = useState(false)
  const [adv, setAdv] = useState({ ...ADV_DEFAULTS })

  const listQ = useQuery({ queryKey: ['rate-pushes'], queryFn: () => supplyApi.ratePushes().then(r => r.data) })
  const gated = listQ.data && !listQ.data.writer_enabled
  const canWrite = !!listQ.data?.can_write

  const detailQ = useQuery({
    queryKey: ['rate-push', selected],
    queryFn: () => supplyApi.ratePush(selected).then(r => r.data),
    enabled: !!selected,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['rate-pushes'] })
    if (selected) qc.invalidateQueries({ queryKey: ['rate-push', selected] })
  }

  const proposeM = useMutation({
    mutationFn: () => supplyApi.proposeRate({
      branch: branch.trim() || undefined, item: item.trim() || undefined,
      method, target,
      method_params: method === 'advanced' ? cleanAdvParams(adv) : undefined,
    }).then(r => r.data),
    onSuccess: (d) => { setSelected(d.id); invalidate() },
  })
  const approveM = useMutation({
    mutationFn: (id) => supplyApi.approveRate(id).then(r => r.data),
    onSuccess: invalidate,
  })
  const executeM = useMutation({
    mutationFn: (id) => supplyApi.executeRate(id).then(r => r.data),
    onSuccess: invalidate,
  })

  return (
    <div className="space-y-4">
      {gated && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2">
          🔒 وضع المعاينة فقط — الكتابة الفعلية إلى SOFTECH معطّلة
          (<code>SALES_RATE_WRITER_ENABLED = OFF</code>). يمكن الاعتماد، لكن التنفيذ محجوب حتى تفعيل البوابة.
        </div>
      )}

      {/* Propose bar */}
      <div className="rounded-lg border border-line bg-surface p-3 flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">فروع (اختياري، مفصولة بفاصلة)</label>
          <input value={branch} onChange={e => setBranch(e.target.value)} placeholder="130,160"
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-40" />
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">أصناف (اختياري)</label>
          <input value={item} onChange={e => setItem(e.target.value)} placeholder="87602"
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-40" />
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">طريقة المعدّل</label>
          <select value={method} onChange={e => setMethod(e.target.value)}
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-44">
            <option value="pivot">المحورية (Pivot)</option>
            <option value="advanced">المتقدمة (Croston)</option>
          </select>
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">وجهة الكتابة</label>
          <select value={target} onChange={e => setTarget(e.target.value)}
            title="سيرفر الفرع = سيرفر الفرع نفسه · نسخة الرئيسي = نسخة المخزن على سيرفر الرئيسي · الاثنان معاً"
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-40">
            <option value="both">الاثنان معاً (افتراضي)</option>
            <option value="node">سيرفر الفرع فقط</option>
            <option value="hq">نسخة الرئيسي فقط</option>
          </select>
        </div>
        {method === 'advanced' && (
          <button type="button" onClick={() => setShowAdv(v => !v)}
            className="text-xs text-primary underline underline-offset-2 pb-1.5">
            {showAdv ? 'إخفاء الإعدادات' : 'إعدادات متقدمة ⚙'}
          </button>
        )}
        <button data-tour="purchasing-supply-rates-propose" onClick={() => proposeM.mutate()} disabled={proposeM.isPending}
          className="px-4 py-1.5 rounded bg-primary text-white text-sm font-medium disabled:opacity-50">
          {proposeM.isPending ? 'جارٍ التحضير…' : '＋ مقترح جديد (معاينة)'}
        </button>
        {proposeM.isError && (
          <span className="text-xs text-rose-600">
            {proposeM.error?.response?.data?.detail || 'تعذّر إنشاء المقترح'}
          </span>
        )}
      </div>

      {/* Advanced (Croston) settings — only affects the 'advanced' method */}
      {method === 'advanced' && showAdv && (
        <div className="rounded-lg border border-line bg-surface p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-content/80">إعدادات المحرك المتقدم (Croston / التنبؤ)</span>
            <button type="button" onClick={() => setAdv({ ...ADV_DEFAULTS })}
              className="text-xs text-content/50 hover:text-primary">إعادة الافتراضي</button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {ADV_FIELDS.map(f => (
              <div key={f.key} className="flex flex-col">
                <label className="text-[11px] text-content/60 mb-1" title={f.hint}>{f.label}</label>
                <input type="number" step={f.step} value={adv[f.key]}
                  onChange={e => setAdv(a => ({ ...a, [f.key]: e.target.value }))}
                  className="border border-line rounded px-2 py-1 text-sm bg-surface text-content" />
              </div>
            ))}
          </div>
          <p className="text-[11px] text-content/50 mt-2">
            تُطبَّق فقط على الطريقة المتقدمة؛ الحقول الفارغة تستخدم القيمة الافتراضية للمحرك. تُحفظ مع كل مقترح للمراجعة.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,22rem)_1fr] gap-4">
        {/* List */}
        <div className="space-y-2">
          {listQ.isLoading && <div className="text-sm text-content/50">جارٍ التحميل…</div>}
          {listQ.data?.results?.length === 0 && (
            <div className="text-sm text-content/50">لا توجد دفعات بعد — ابدأ بمقترح جديد.</div>
          )}
          {listQ.data?.results?.map(p => (
            <button key={p.id} onClick={() => setSelected(p.id)}
              className={`w-full text-right rounded-lg border p-3 transition ${
                selected === p.id ? 'border-primary bg-primary/5' : 'border-line bg-surface hover:border-primary/40'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-content text-sm">دفعة #{p.id}</span>
                <Badge s={p.status} />
              </div>
              <div className="mt-1 text-xs text-content/60 flex flex-wrap gap-x-3 gap-y-0.5">
                <span>مؤهّل: {p.eligible}</span>
                <span>متخطّى: {p.skipped}</span>
                {p.status === 'executed' && <span className="text-emerald-600">مؤكّد: {p.verified}/{p.written}</span>}
                <span>{fmtDate(p.created_at)}</span>
              </div>
            </button>
          ))}
        </div>

        {/* Detail */}
        <div>
          {!selected && <div className="text-sm text-content/50 p-4">اختر دفعة لعرض تفاصيلها.</div>}
          {selected && detailQ.isLoading && <div className="text-sm text-content/50 p-4">جارٍ التحميل…</div>}
          {selected && detailQ.data && (
            <PushDetail push={detailQ.data} gated={gated} canWrite={canWrite}
              onApprove={() => approveM.mutate(detailQ.data.id)}
              onExecute={() => executeM.mutate(detailQ.data.id)}
              approving={approveM.isPending} executing={executeM.isPending}
              actionError={approveM.error || executeM.error} />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Shared grid-filter primitives (SOFTECH-screen parity: search / slice / sort) ──
function GridToolbar({ search, setSearch, count, total, children, placeholder }) {
  return (
    <div className="p-2 border-b border-line flex flex-wrap items-center gap-2">
      <input value={search} onChange={e => setSearch(e.target.value)}
        placeholder={placeholder || 'بحث بالكود أو الاسم…'}
        className="border border-line rounded px-2 py-1 text-xs bg-surface text-content w-48" />
      {children}
      {search && (
        <button type="button" onClick={() => setSearch('')}
          className="text-[11px] text-content/50 hover:text-primary">مسح</button>
      )}
      <span className="text-[11px] text-content/50 mr-auto">عرض {count} من {total}</span>
    </div>
  )
}

function MiniSelect({ value, onChange, options, title }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} title={title}
      className="border border-line rounded px-2 py-1 text-xs bg-surface text-content">
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

// case/space-insensitive match on itemcode + item_name
function matchesText(l, q) {
  if (!q) return true
  const t = q.trim().toLowerCase()
  return String(l.itemcode || '').toLowerCase().includes(t) || wildcardMatch(l.item_name, t)
}

function PushDetail({ push, gated, canWrite, onApprove, onExecute, approving, executing, actionError }) {
  const bl = useBranchLabels()
  const lines = push.lines || []
  const xlsM = useMutation({ mutationFn: () => supplyApi.ratePushExcel(push.id),
    onSuccess: (res) => downloadBlob(res.data, `sales_rates_${push.id}.xlsx`) })
  const [search, setSearch] = useState('')
  const [dir, setDir] = useState('all')      // all | up | down | new
  const [sort, setSort] = useState('delta')  // delta | code | name
  const dirOf = (l) => {
    const o = Number(l.old || 0), nw = Number(l.new || 0)
    if (o === 0 && nw > 0) return 'new'
    if (nw > o) return 'up'
    if (nw < o) return 'down'
    return 'flat'
  }
  const allEligible = lines.filter(l => l.eligible)
  const eligible = useMemo(() => {
    let r = allEligible.filter(l => matchesText(l, search))
    if (dir !== 'all') r = r.filter(l => dirOf(l) === dir)
    const cmp = {
      delta: (a, b) => Math.abs(Number(b.new || 0) - Number(b.old || 0)) - Math.abs(Number(a.new || 0) - Number(a.old || 0)),
      code:  (a, b) => String(a.itemcode).localeCompare(String(b.itemcode), 'ar'),
      name:  (a, b) => String(a.item_name || '').localeCompare(String(b.item_name || ''), 'ar'),
    }[sort]
    return [...r].sort(cmp)
  }, [allEligible, search, dir, sort])
  const skipped = useMemo(
    () => lines.filter(l => !l.eligible && matchesText(l, search)),
    [lines, search])
  const grid = useSort(eligible, {
    itemcode: l => l.itemcode, item_name: l => l.item_name, branch: l => `${l.branchcode}/${l.storecode}`,
    old: l => Number(l.old ?? NaN), old_hq: l => Number(l.old_hq ?? NaN), new: l => Number(l.new ?? NaN),
    verified: l => (l.verified ? 2 : l.error ? 1 : 0),
  })
  return (
    <div className="rounded-lg border border-line bg-surface">
      <div className="p-3 border-b border-line flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-content">دفعة #{push.id}</span>
          <Badge s={push.status} />
          {push.method_label && (
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">{push.method_label}</span>
          )}
          {push.target_label && (
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-sky-100 text-sky-700"
              title="وجهة الكتابة إلى SOFTECH">⇢ {push.target_label}</span>
          )}
          <span className="text-xs text-content/50">
            تشغيل المحرك #{push.run_id ?? '—'} · أنشأها {push.created_by || '—'} · {fmtDate(push.created_at)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => xlsM.mutate()} disabled={xlsM.isPending}
            className="px-3 py-1.5 rounded border border-line text-sm hover:bg-primary/5 disabled:opacity-50"
            title="كل أسطر الدفعة مع «بيانات الصنف» (التصنيف، المورد الرئيسي، الشركة المنتجة، الأسعار)">
            {xlsM.isPending ? '…' : '⬇ Excel'}
          </button>
          {push.status === 'proposed' && (
            <button data-tour="purchasing-supply-rates-approve" onClick={onApprove} disabled={!canWrite || approving}
              className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm disabled:opacity-50"
              title={canWrite ? '' : 'يتطلب صلاحية اعتماد'}>
              {approving ? '…' : 'اعتماد'}
            </button>
          )}
          {push.status === 'approved' && (
            <button data-tour="purchasing-supply-rates-softech-execute" onClick={onExecute} disabled={!canWrite || gated || executing}
              className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm disabled:opacity-50"
              title={gated ? 'الكتابة معطّلة (البوابة مغلقة)' : (canWrite ? '' : 'يتطلب صلاحية تنفيذ')}>
              {executing ? '…' : 'تنفيذ إلى SOFTECH'}
            </button>
          )}
        </div>
      </div>

      {actionError && (
        <div className="px-3 py-2 text-xs text-rose-600 border-b border-line">
          {actionError?.response?.data?.detail || 'تعذّر تنفيذ الإجراء'}
        </div>
      )}

      <div className="p-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-content/70 border-b border-line">
        <span>فروع: {push.branches}</span>
        <span>مؤهّل: {push.eligible}</span>
        <span>متخطّى: {push.skipped}</span>
        {push.unreachable > 0 && <span className="text-rose-600">غير متاح: {push.unreachable}</span>}
        {push.status === 'executed' && (
          <span className="text-emerald-600">كُتب: {push.written} · مؤكّد: {push.verified} · غير مؤكَّد: {push.reverted}</span>
        )}
      </div>

      <GridToolbar search={search} setSearch={setSearch} count={eligible.length} total={allEligible.length}>
        <MiniSelect value={dir} onChange={setDir} title="اتجاه التغيّر" options={[
          ['all', 'كل الاتجاهات'], ['up', 'ارتفاع ▲'], ['down', 'انخفاض ▼'], ['new', 'جديد من صفر']]} />
        <MiniSelect value={sort} onChange={setSort} title="ترتيب" options={[
          ['delta', 'الأكبر تغيّراً'], ['code', 'الكود'], ['name', 'الاسم']]} />
      </GridToolbar>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-content/60 border-b border-line">
              <SortTh k="itemcode" {...grid} className="text-right px-3 py-2">الكود</SortTh>
              <SortTh k="item_name" {...grid} className="text-right px-3 py-2">الصنف</SortTh>
              <SortTh k="branch" {...grid} className="text-center px-3 py-2">الفرع/المخزن</SortTh>
              <SortTh k="old" {...grid} className="text-center px-3 py-2">
                {push.target === 'hq' ? 'الحالي (الرئيسي)' : 'الحالي (الفرع)'}
              </SortTh>
              {push.target === 'both' && <SortTh k="old_hq" {...grid} className="text-center px-3 py-2">الحالي (الرئيسي)</SortTh>}
              <SortTh k="new" {...grid} className="text-center px-3 py-2">المعدل الجديد</SortTh>
              {push.status === 'executed' && <SortTh k="verified" {...grid} className="text-center px-3 py-2">مؤكّد</SortTh>}
            </tr>
          </thead>
          <tbody>
            {grid.sorted.map(l => (
              <tr key={l.id} className="border-b border-line/60">
                <td className="px-3 py-1.5 text-content/80">{l.itemcode}</td>
                <td className="px-3 py-1.5 text-content">{l.item_name}</td>
                <td className="px-3 py-1.5 text-center text-content/70">{bl(l.branchcode)} / {l.storecode}</td>
                <td className="px-3 py-1.5 text-center text-content/60">{n(l.old)}</td>
                {push.target === 'both' && (
                  <td className="px-3 py-1.5 text-center text-content/60">{n(l.old_hq)}</td>
                )}
                <td className="px-3 py-1.5 text-center font-medium text-primary">{n(l.new)}</td>
                {push.status === 'executed' && (
                  <td className="px-3 py-1.5 text-center">{l.verified ? '✓' : (l.error ? '⚠️' : '—')}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {eligible.length === 0 && <div className="p-3 text-sm text-content/50">لا توجد أسطر مؤهّلة.</div>}
      </div>

      {skipped.length > 0 && (
        <details className="p-3 border-t border-line">
          <summary className="text-xs text-content/60 cursor-pointer">أسطر متخطّاة ({skipped.length})</summary>
          <div className="mt-2 space-y-1">
            {skipped.slice(0, 50).map(l => (
              <div key={l.id} className="text-xs text-content/60 flex gap-2">
                <span className="text-content/80">{l.itemcode}</span>
                <span>{l.item_name}</span>
                <span className="text-amber-600">{l.reason}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Feature 2 — ISR / طلبات التوريد (preview shell; writer pending)
// ══════════════════════════════════════════════════════════════════════════════

function IsrTab() {
  const bl = useBranchLabels()
  const qc = useQueryClient()
  const [selected, setSelected] = useState(null)
  const [branch, setBranch] = useState('')
  const [maxLines, setMaxLines] = useState('')
  const [fromHq, setFromHq] = useState(false)
  const [showXfer, setShowXfer] = useState(false)
  const [covVal, setCovVal] = useState('')       // '' = engine default gap (old rule only)
  const [covUnit, setCovUnit] = useState('months')
  // owner 2026-10-24: SOFTECH's rule by default; the engine gap stays selectable
  const [rule, setRule] = useState('softech')
  const ruleCfg = useIsrRuleSettings()
  // months for the API; days ÷ 30 (≈ 30d = 1 month per owner)
  const coverageMonths = covVal.trim() === '' ? undefined
    : (covUnit === 'days' ? Number(covVal) / 30 : Number(covVal))

  const listQ = useQuery({ queryKey: ['isr-pushes'], queryFn: () => supplyApi.isrList().then(r => r.data) })
  const gated = listQ.data && !listQ.data.writer_enabled
  const canWrite = !!listQ.data?.can_write

  const previewQ = useQuery({
    queryKey: ['isr-transfer-preview'], enabled: showXfer,
    queryFn: () => supplyApi.isrTransferPreview().then(r => r.data),
  })

  const detailQ = useQuery({
    queryKey: ['isr-push', selected],
    queryFn: () => supplyApi.isrGet(selected).then(r => r.data),
    enabled: !!selected,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['isr-pushes'] })
    if (selected) qc.invalidateQueries({ queryKey: ['isr-push', selected] })
  }
  const proposeM = useMutation({
    mutationFn: () => supplyApi.isrPropose(rule === 'softech'
      ? { ...(ruleCfg.st || {}), rule, branch: branch.trim(), from_hq: fromHq, max_lines: maxLines.trim() || undefined }
      : { rule, branch: branch.trim(), from_hq: fromHq, max_lines: maxLines.trim() || undefined,
          coverage_months: coverageMonths }).then(r => r.data),
    onSuccess: (d) => { setSelected(d.id); invalidate() },
  })
  // Excel of one pair (from → to) or of every pair — review before «توليد»
  const xferXlsM = useMutation({
    mutationFn: (pair) => supplyApi.isrTransferExcel(pair || {}),
    onSuccess: (res, pair) => downloadBlob(res.data, pair?.from ? `transfer_${pair.from}_to_${pair.to}.xlsx` : 'transfers_all.xlsx'),
  })
  const xferM = useMutation({
    mutationFn: (pair) => supplyApi.isrTransfer(pair).then(r => r.data),
    onSuccess: invalidate,
  })
  const approveM = useMutation({ mutationFn: (id) => supplyApi.isrApprove(id).then(r => r.data), onSuccess: invalidate })
  const pushM = useMutation({
    mutationFn: ({ id, force_reason }) => supplyApi.isrPush(id, force_reason ? { force_reason } : {}).then(r => r.data),
    onSuccess: invalidate,
  })
  const cancelM = useMutation({ mutationFn: ({ id, reason }) => supplyApi.isrCancel(id, reason).then(r => r.data), onSuccess: invalidate })

  return (
    <div className="space-y-4">
      {gated && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2">
          🔒 وضع المعاينة فقط — الترحيل إلى SOFTECH معطّل (<code>ISR_WRITER_ENABLED = OFF</code>).
          يمكن الاقتراح والاعتماد، لكن الترحيل محجوب.
        </div>
      )}

      <div className="rounded-lg border border-line bg-surface p-3 flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">الفرع الطالب</label>
          <input value={branch} onChange={e => setBranch(e.target.value)} placeholder="150"
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-28" />
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">حد الأسطر (اختياري)</label>
          <input value={maxLines} onChange={e => setMaxLines(e.target.value)} placeholder="الكل"
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-28" />
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">قاعدة الحساب</label>
          <select value={rule} onChange={e => setRule(e.target.value)}
            className="border border-line rounded px-1 py-1 text-sm bg-surface text-content">
            <option value="softech">مثل SOFTECH (حد الطلب − الرصيد − بالطريق)</option>
            <option value="engine">فجوة المحرك (القديمة)</option>
          </select>
        </div>
        {rule === 'engine' && <div className="flex flex-col">
          <label className="text-xs text-content/60 mb-1">التغطية (اختياري)</label>
          <div className="flex items-center gap-1">
            <input value={covVal} onChange={e => setCovVal(e.target.value)} type="number" min="0" step="0.25"
              placeholder="افتراضي" title="عدد أشهر/أيام التغطية — فارغ = فجوة المحرك الافتراضية"
              className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-24" />
            <select value={covUnit} onChange={e => setCovUnit(e.target.value)}
              className="border border-line rounded px-1 py-1 text-sm bg-surface text-content">
              <option value="months">شهور</option>
              <option value="days">أيام</option>
            </select>
          </div>
        </div>}
        <label className="flex items-center gap-1.5 text-xs text-content/70 mb-1.5 cursor-pointer">
          <input type="checkbox" checked={fromHq} onChange={e => setFromHq(e.target.checked)} />
          من الرئيسي إلى الفرع
        </label>
        <button data-tour="purchasing-supply-isr-new" onClick={() => proposeM.mutate()}
          disabled={proposeM.isPending || !branch.trim() || (rule === 'softech' && !ruleCfg.st)}
          className="px-4 py-1.5 rounded bg-primary text-white text-sm font-medium disabled:opacity-50">
          {proposeM.isPending ? 'جارٍ التحضير…' : '＋ طلب توريد جديد (معاينة)'}
        </button>
        <button onClick={() => setShowXfer(v => !v)}
          className="px-3 py-1.5 rounded border border-line text-sm text-content/80 hover:border-primary/40">
          {showXfer ? '▲ إخفاء التوزيعة' : '⇄ توزيعة بين الفروع'}
        </button>
        {proposeM.isError && (
          <span className="text-xs text-rose-600">
            {proposeM.error?.response?.data?.detail || 'تعذّر إنشاء الطلب'}
            {proposeM.error?.response?.data?.stats && (
              <span className="text-content/60"> — {Object.entries(proposeM.error.response.data.stats)
                .filter(([k, v]) => v && k !== 'lines')
                .map(([k, v]) => `${proposeM.error.response.data.stat_labels?.[k] || k}: ${v}`).join('، ')}</span>
            )}
          </span>
        )}
        {rule === 'softech' && <IsrRulePanel {...ruleCfg} />}
      </div>

      {showXfer && (
        <div className="rounded-lg border border-line bg-surface p-3 space-y-2">
          <div className="text-sm font-medium text-content flex items-center gap-2">
            توزيعة بين الفروع (فائض ← الرئيسي ← عجز)
            {previewQ.data?.run_id && <span className="text-xs text-content/50">تشغيل #{previewQ.data.run_id}</span>}
            {previewQ.data?.pairs?.length > 0 && (
              <button onClick={() => xferXlsM.mutate(null)} disabled={xferXlsM.isPending}
                className="ms-auto px-2 py-0.5 rounded border border-line text-xs text-content/80 hover:border-primary/40 disabled:opacity-50">
                {xferXlsM.isPending ? '…' : '⬇ Excel (كل المسارات)'}</button>)}
          </div>
          {previewQ.isLoading && <div className="text-sm text-content/50">جارٍ تحميل التوصيات…</div>}
          {previewQ.data?.pairs?.length === 0 && (
            <div className="text-sm text-content/50">لا توجد توصيات تحويل — شغّل محرك الطلب أولاً.</div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {previewQ.data?.pairs?.slice(0, 40).map((p, i) => (
              <div key={i} className="flex items-center justify-between gap-2 rounded border border-line px-3 py-1.5 text-sm">
                <span className="text-content">
                  {p.from} ({p.from_name?.split(',')[0]}) <span className="text-content/40">{fa()} الرئيسي {fa()}</span> {p.to} ({p.to_name?.split(',')[0]})
                </span>
                <span className="flex items-center gap-2 text-xs text-content/60">
                  {p.items} صنف · {Number(p.value).toLocaleString('ar-EG')} ج
                  <button onClick={() => xferXlsM.mutate({ from: p.from, to: p.to })} disabled={xferXlsM.isPending}
                    className="px-2 py-0.5 rounded border border-line text-content/80 hover:border-primary/40 disabled:opacity-50"
                    title="أصناف هذا المسار مع الأرصدة ومعدلات البيع — للمراجعة قبل التوليد">Excel</button>
                  <button onClick={() => xferM.mutate({ from: p.from, to: p.to })} disabled={xferM.isPending}
                    className="px-2 py-0.5 rounded bg-primary text-white disabled:opacity-50">توليد</button>
                </span>
              </div>
            ))}
          </div>
          {xferM.isSuccess && (
            <div className="text-xs text-emerald-600">
              تم إنشاء {xferM.data?.count} توزيعة كمقترحات.
              {xferM.data?.skipped?.length > 0 && (
                <div className="text-amber-700">لم يُنشأ: {xferM.data.skipped.map(s => `${s.path ? s.path.map(bl).join(` ${fa()} `) : s.route} — ${s.reason}`).join(' · ')}</div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,22rem)_1fr] gap-4">
        <div className="space-y-2">
          {listQ.isLoading && <div className="text-sm text-content/50">جارٍ التحميل…</div>}
          {listQ.data?.results?.length === 0 && (
            <div className="text-sm text-content/50">لا توجد طلبات — ابدأ بطلب توريد جديد.</div>
          )}
          {listQ.data?.results?.map(p => (
            <button key={p.id} onClick={() => setSelected(p.id)}
              className={`w-full text-right rounded-lg border p-3 transition ${
                selected === p.id ? 'border-primary bg-primary/5' : 'border-line bg-surface hover:border-primary/40'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-content text-sm">
                  {p.kind === 'self' ? `فرع ${bl(p.branchcode)}` : `${bl(p.branchcode)} ${fa()} ${bl(p.dest_branchcode)}`} · #{p.id}
                </span>
                <Badge s={p.status} />
              </div>
              {p.kind !== 'self' && (
                <div className="text-[11px] text-content/50">{p.kind_label}{p.linked_push_id ? ` · مرتبط #${p.linked_push_id}` : ''}{p.origin_isr ? ` · لطلب ${p.origin_isr}` : ''}{p.origin_request_id ? ` · واتساب WA-${p.origin_request_id}` : ''}</div>
              )}
              <div className="mt-1 text-xs text-content/60 flex flex-wrap gap-x-3 gap-y-0.5">
                <span>{p.line_count} صنف</span>
                <span>{Number(p.docvalue).toLocaleString('ar-EG', { maximumFractionDigits: 0 })} ج</span>
                {p.isrdocnumber && <span className="text-emerald-600">ISR {p.isrdocnumber}</span>}
                <span>{fmtDate(p.created_at)}</span>
              </div>
            </button>
          ))}
        </div>

        <div>
          {!selected && <div className="text-sm text-content/50 p-4">اختر طلباً لعرض تفاصيله.</div>}
          {selected && detailQ.isLoading && <div className="text-sm text-content/50 p-4">جارٍ التحميل…</div>}
          {selected && detailQ.data && (
            <IsrDetail key={detailQ.data.id} push={detailQ.data} gated={gated} canWrite={canWrite}
              onApprove={() => approveM.mutate(detailQ.data.id)}
              onPush={(force_reason) => pushM.mutate({ id: detailQ.data.id, force_reason })}
              onCancel={(reason) => cancelM.mutate({ id: detailQ.data.id, reason })}
              approving={approveM.isPending} pushing={pushM.isPending} cancelling={cancelM.isPending}
              approveWarning={approveM.data?.id === detailQ.data.id ? approveM.data?.warning : null}
              actionError={approveM.error || pushM.error || cancelM.error} />
          )}
        </div>
      </div>
    </div>
  )
}

function IsrDetail({ push, gated, canWrite, onApprove, onPush, onCancel, approving, pushing, cancelling,
                     approveWarning, actionError }) {
  const bl = useBranchLabels()
  // cancel / a deliberate re-send both need a written reason — inline, no popup
  const [cancelling_, setCancelOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [forceReason, setForceReason] = useState('')
  const errCode = actionError?.response?.data?.code
  const cancelled = push.params?.cancelled
  const allLines = push.lines || []
  const [search, setSearch] = useState('')
  const [supp, setSupp] = useState('all')
  const [neededOnly, setNeededOnly] = useState(false)
  const [sort, setSort] = useState('qty')   // qty | code | name
  const suppliers = useMemo(() => {
    const s = [...new Set(allLines.map(l => String(l.suppcode || '').trim()).filter(Boolean))]
    return s.sort((a, b) => a.localeCompare(b, 'ar'))
  }, [allLines])
  const lines = useMemo(() => {
    let r = allLines.filter(l => matchesText(l, search))
    if (supp !== 'all') r = r.filter(l => String(l.suppcode || '').trim() === supp)
    if (neededOnly) r = r.filter(l => Number(l.itemqty || 0) > 0)
    const cmp = {
      qty:  (a, b) => Number(b.itemqty || 0) - Number(a.itemqty || 0),
      code: (a, b) => String(a.itemcode).localeCompare(String(b.itemcode), 'ar'),
      name: (a, b) => String(a.item_name || '').localeCompare(String(b.item_name || ''), 'ar'),
    }[sort]
    return [...r].sort(cmp)
  }, [allLines, search, supp, neededOnly, sort])
  const grid = useSort(lines, {
    itemcode: l => l.itemcode, item_name: l => l.item_name, itemqty: l => Number(l.itemqty ?? NaN),
    nowqty: l => Number(l.nowqty ?? NaN), suppcode: l => l.suppcode,
    rate: l => Number(l.rate ?? NaN), target: l => Number(l.target ?? NaN), transit: l => Number(l.transit ?? NaN),
    hq: l => Number(l.hq_stock ?? NaN), need: l => Number(l.need ?? NaN),
  })
  const rich = push.params?.rule === 'softech'      // SOFTECH-rule lines carry the why
  return (
    <div className="rounded-lg border border-line bg-surface">
      <div className="p-3 border-b border-line flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-content">
            طلب توريد #{push.id} · {push.kind === 'self' ? `فرع ${bl(push.branchcode)}` : `${bl(push.branchcode)} ${fa()} ${bl(push.dest_branchcode)}`}
          </span>
          {push.kind !== 'self' && <span className="text-xs text-content/50">{push.kind_label}{push.linked_push_id ? ` · مرتبط #${push.linked_push_id}` : ''}</span>}
          <Badge s={push.status} />
          {push.coverage_months != null && (
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-primary/10 text-primary"
              title="أُعيد حساب الكمية على هذه التغطية بدل فجوة المحرك">تغطية {push.coverage_months} شهر</span>
          )}
          {push.isrdocnumber && <span className="text-xs text-emerald-600">SOFTECH ISR {push.isrdocnumber}</span>}
          {push.origin_isr && (
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800" title={push.notes || ''}>
              لتلبية طلب الفرع {push.origin_isr}
            </span>
          )}
          {push.origin_request_id && (
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-teal-100 text-teal-800" title={push.notes || ''}>
              طلب واتساب WA-{push.origin_request_id} · فائض فرع {bl(push.origin_donor)}
            </span>
          )}
          <span className="text-xs text-content/50">
            {push.line_count} صنف · {Number(push.docvalue).toLocaleString('ar-EG', { maximumFractionDigits: 0 })} ج · {push.created_by || '—'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {push.status === 'proposed' && (
            <button data-tour="purchasing-supply-isr-approve" onClick={onApprove} disabled={!canWrite || approving}
              className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm disabled:opacity-50"
              title={canWrite ? '' : 'يتطلب صلاحية اعتماد'}>
              {approving ? '…' : 'اعتماد'}
            </button>
          )}
          {push.status === 'approved' && (
            <button data-tour="purchasing-supply-isr-push" onClick={() => onPush()} disabled={!canWrite || gated || pushing}
              className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm disabled:opacity-50"
              title={gated ? 'الترحيل معطّل (البوابة مغلقة)' : (canWrite ? '' : 'يتطلب صلاحية ترحيل')}>
              {pushing ? '…' : 'ترحيل إلى SOFTECH'}
            </button>
          )}
          {['proposed', 'approved', 'failed'].includes(push.status) && canWrite && !cancelling_ && (
            <button data-tour="purchasing-supply-isr-cancel" onClick={() => setCancelOpen(true)}
              className="px-3 py-1.5 rounded border border-line text-sm text-content/70 hover:border-rose-300">إلغاء</button>
          )}
        </div>
      </div>

      {cancelling_ && (
        <div className="px-3 py-2 border-b border-line flex flex-wrap items-center gap-2 text-sm">
          <input value={reason} onChange={e => setReason(e.target.value)} placeholder="سبب الإلغاء (مطلوب)" autoFocus
            className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-72" />
          <button onClick={() => onCancel(reason)} disabled={cancelling || reason.trim().length < 5}
            className="px-3 py-1 rounded bg-rose-600 text-white text-sm disabled:opacity-50">{cancelling ? '…' : 'تأكيد الإلغاء'}</button>
          <button onClick={() => setCancelOpen(false)} className="text-xs text-content/60 underline">تراجع</button>
        </div>
      )}
      {cancelled && (
        <div className="px-3 py-2 border-b border-line text-xs text-content/70">
          ملغى{cancelled.by ? ` بواسطة ${cancelled.by}` : ''} — {cancelled.reason}
          {cancelled.superseded_by && <span className="text-primary"> (الطلب الأحدث #{cancelled.superseded_by})</span>}
        </div>
      )}
      {approveWarning && <div className="px-3 py-2 border-b border-line text-xs text-amber-800 bg-amber-50">{approveWarning}</div>}
      {push.params?.forced_push && (
        <div className="px-3 py-2 border-b border-line text-xs text-amber-800 bg-amber-50">
          رُحِّل رغم تطابقه مع الطلب #{push.params.forced_push.duplicate_of} — السبب: {push.params.forced_push.reason}
        </div>
      )}
      <IsrParamsSummary push={push} />

      {(actionError || push.error) && (
        <div className="px-3 py-2 text-xs text-rose-600 border-b border-line space-y-1.5">
          <div>{actionError?.response?.data?.detail || push.error || 'خطأ'}</div>
          {errCode === 'duplicate_push' && push.status === 'approved' && (
            // the guard refused an identical re-send — only a written reason lets it through
            <div className="flex flex-wrap items-center gap-2 text-content">
              <input value={forceReason} onChange={e => setForceReason(e.target.value)}
                placeholder="سبب إعادة الإرسال عن قصد (مطلوب)"
                className="border border-line rounded px-2 py-1 text-sm bg-surface text-content w-72" />
              <button onClick={() => onPush(forceReason)} disabled={pushing || forceReason.trim().length < 5}
                className="px-3 py-1 rounded border border-rose-300 text-rose-700 text-sm disabled:opacity-50">
                ترحيل رغم التطابق</button>
            </div>
          )}
        </div>
      )}

      <GridToolbar search={search} setSearch={setSearch} count={lines.length} total={allLines.length}>
        <MiniSelect value={supp} onChange={setSupp} title="المورد" options={[
          ['all', 'كل الموردين'], ...suppliers.map(s => [s, `مورد ${s}`])]} />
        <MiniSelect value={sort} onChange={setSort} title="ترتيب" options={[
          ['qty', 'الأكثر طلباً'], ['code', 'الكود'], ['name', 'الاسم']]} />
        <label className="flex items-center gap-1 text-[11px] text-content/70 cursor-pointer">
          <input type="checkbox" checked={neededOnly} onChange={e => setNeededOnly(e.target.checked)} />
          المطلوب فقط
        </label>
      </GridToolbar>

      <div className="overflow-x-auto max-h-[70vh]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-xs text-content/60 border-b border-line">
              <SortTh k="itemcode" {...grid} className="text-right px-3 py-2">الكود</SortTh>
              <SortTh k="item_name" {...grid} className="text-right px-3 py-2">الصنف</SortTh>
              <SortTh k="itemqty" {...grid} className="text-center px-3 py-2">المطلوب</SortTh>
              <SortTh k="nowqty" {...grid} className="text-center px-3 py-2">رصيد الفرع</SortTh>
              {rich && <>
                <SortTh k="transit" {...grid} className="text-center px-3 py-2">بالطريق</SortTh>
                <SortTh k="rate" {...grid} className="text-center px-3 py-2">المعدل/شهر</SortTh>
                <SortTh k="target" {...grid} className="text-center px-3 py-2">الهدف</SortTh>
                <SortTh k="need" {...grid} className="text-center px-3 py-2">الاحتياج</SortTh>
                <SortTh k="hq" {...grid} className="text-center px-3 py-2">رصيد الرئيسي</SortTh>
              </>}
              <SortTh k="suppcode" {...grid} className="text-center px-3 py-2">المورد</SortTh>
            </tr>
          </thead>
          <tbody>
            {grid.sorted.slice(0, 500).map((l, i) => (
              <tr key={i} className="border-b border-line/60">
                <td className="px-3 py-1.5 text-content/80">{l.itemcode}</td>
                <td className="px-3 py-1.5 text-content">{l.item_name}</td>
                <td className="px-3 py-1.5 text-center font-medium text-primary">
                  {l.itemqty}
                  {l.capped && <span className="ms-1 text-[10px] px-1 rounded bg-amber-100 text-amber-800"
                    title={`الاحتياج ${l.need} لكن رصيد الرئيسي ${l.hq_stock} — خُفِّض`}>رصيد الرئيسي</span>}
                </td>
                <td className="px-3 py-1.5 text-center text-content/60">{n(l.nowqty, 0)}</td>
                {rich && <>
                  <td className="px-3 py-1.5 text-center text-content/60">{l.transit ? n(l.transit, 0) : '—'}</td>
                  <td className="px-3 py-1.5 text-center text-content/60">{n(l.rate, 1)}</td>
                  <td className="px-3 py-1.5 text-center text-content/60">{n(l.target, 1)}</td>
                  <td className="px-3 py-1.5 text-center text-content/60">{l.need}</td>
                  <td className="px-3 py-1.5 text-center text-content/60">{n(l.hq_stock, 0)}</td>
                </>}
                <td className="px-3 py-1.5 text-center text-content/60">{l.suppcode}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {lines.length > 500 && (
          <div className="p-2 text-xs text-content/50">… {lines.length - 500} صنف إضافي (يُرحّل بالكامل)</div>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// L3 — التوزيعة (proactive distribution)
// ══════════════════════════════════════════════════════════════════════════════

const DIST_CATS = [
  ['new_no_rate',   'جديد بلا معدل'],
  ['never_stocked', 'غير مُدرج بفرع'],
  ['over_piled',    'متكدس بفرع'],
  ['hq_dormant',    'راكد بالرئيسي'],
]

function DistributionTab() {
  const bl = useBranchLabels()
  const qc = useQueryClient()
  const [cats, setCats] = useState(DIST_CATS.map(c => c[0]))
  const [search, setSearch] = useState('')

  // ONE read of every suggestion; the category boxes filter it here (instant, and the
  // list always agrees with the counts beside each box)
  const q = useQuery({
    queryKey: ['dist-preview'],
    queryFn: () => supplyApi.distPreview({ limit: 20000 }).then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })
  const genM = useMutation({
    mutationFn: () => supplyApi.distGenerate({ categories: cats }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['isr-pushes'] }),
  })
  // the filters on screen (categories + search) go with the export
  const xlsM = useMutation({
    mutationFn: () => supplyApi.distExcel({ category: cats, q: search.trim() }),
    onSuccess: (res) => downloadBlob(res.data, 'distribution.xlsx'),
  })
  const canWrite = !!q.data?.can_write
  const toggle = (c) => setCats(cs => cs.includes(c) ? cs.filter(x => x !== c) : [...cs, c])
  const catLabel = (k) => DIST_CATS.find(c => c[0] === k)?.[1] || k
  const rows = useMemo(() => (q.data?.suggestions || []).filter(s => cats.includes(s.category)
    && (!search.trim() || wildcardMatch(`${s.itemcode} ${s.item_name}`, search))), [q.data, cats, search])
  const { sorted, sort, onSort } = useSort(rows, {
    category: s => catLabel(s.category), itemcode: s => s.itemcode, item_name: s => s.item_name,
    sells: s => s.sells_at, age: s => s.age_days, route: s => bl(s.from_branch),
    qty: s => (s.category === 'over_piled' ? s.total_qty : s.qty_each), rate: s => s.network_avg,
    to_stock: s => Math.min(...s.to_branches.map(t => t.stock ?? Infinity)),
  })
  // a branch's stock + monthly sales (+ its SOFTECH maximum when read live)
  const pos = (p) => p && p.stock != null ? (
    <span className="text-[11px] text-content/60 whitespace-nowrap"
      title={p.live ? 'الرصيد لحظي من سيرفر الفرع' : 'الرصيد من آخر تشغيل للمحرك'}>
      رصيد {p.stock}{p.live ? '' : '*'} · بيع {p.rate}/ش{p.max != null ? ` · حد ${p.max}` : ''}
    </span>) : null
  const SHOW = 500
  const th = 'px-3 py-2'

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-line bg-surface p-3 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-content">التوزيعة الاستباقية</span>
          {DIST_CATS.map(([k, l]) => (
            <label key={k} className="flex items-center gap-1.5 text-xs text-content/70 cursor-pointer">
              <input type="checkbox" checked={cats.includes(k)} onChange={() => toggle(k)} />
              {l}
              {q.data?.summary?.by_category?.[k] && (
                <span className="text-content/40">({q.data.summary.by_category[k].count})</span>
              )}
            </label>
          ))}
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="بحث بالصنف أو الكود… (* أو %)"
            className="border border-line rounded px-2 py-1 text-xs bg-surface text-content w-52" />
          <button onClick={() => xlsM.mutate()} disabled={xlsM.isPending || !cats.length || !q.data}
            className="px-3 py-1.5 rounded border border-line text-sm text-content/80 hover:border-primary/40 disabled:opacity-50 ms-auto"
            title="الصفوف الظاهرة بنفس الفلاتر، مع رصيد ومعدل بيع الفرع الحائز والمستهدف">
            {xlsM.isPending ? '…' : '⬇ Excel'}</button>
          <button data-tour="purchasing-supply-dist-generate" onClick={() => genM.mutate()} disabled={genM.isPending || !cats.length}
            className="px-4 py-1.5 rounded bg-primary text-white text-sm font-medium disabled:opacity-50"
            title={canWrite ? '' : 'يتطلب صلاحية'}>
            {genM.isPending ? 'جارٍ التوليد…' : '＋ توليد مقترحات التوزيعة'}
          </button>
        </div>
        {q.data?.summary && (
          <div className="text-xs text-content/60">
            المعروض {rows.length} من إجمالي {q.data.summary.total} اقتراح — تُنشأ كطلبات توريد (تظهر في تبويب «طلبات التوريد» للاعتماد والترحيل).
            {' '}الرصيد لحظي من سيرفر الفرع (* = من تشغيل المحرك #{q.data.positions_source?.run_id}){' '}
            ومعدل البيع من نفس التشغيل.
          </div>
        )}
        {genM.isSuccess && (
          <div className="text-xs text-emerald-600">
            تم إنشاء {genM.data?.count} مسار توزيعة كمقترحات (المقترح الأقدم لنفس المسار يُستبدل تلقائياً).
            {genM.data?.skipped?.length > 0 && (
              <div className="text-amber-700">لم يُنشأ {genM.data.skipped.length} مسار: {genM.data.skipped.map(s => `${s.path ? s.path.map(bl).join(` ${fa()} `) : s.route} — ${s.reason}`).join(' · ')}</div>
            )}
          </div>
        )}
        {genM.isError && (
          <div className="text-xs text-rose-600">{genM.error?.response?.data?.detail || 'تعذّر التوليد'}</div>
        )}
      </div>

      <div className="rounded-lg border border-line bg-surface overflow-x-auto max-h-[70vh]">
        {q.isLoading && <div className="p-4 text-sm text-content/50">جارٍ تحليل التوزيعة…</div>}
        {q.isError && <div className="p-4 text-sm text-rose-600">{q.error?.response?.data?.detail || 'تعذّر تحميل التوزيعة'}</div>}
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-xs text-content/60 border-b border-line">
              <SortTh k="category" sort={sort} onSort={onSort} className={`text-right ${th}`}>النوع</SortTh>
              <SortTh k="itemcode" sort={sort} onSort={onSort} className={`text-right ${th}`}>الكود</SortTh>
              <SortTh k="item_name" sort={sort} onSort={onSort} className={`text-right ${th}`}>الصنف</SortTh>
              <SortTh k="sells" sort={sort} onSort={onSort} className={`text-center ${th}`}>يُباع بـ</SortTh>
              <SortTh k="age" sort={sort} onSort={onSort} className={`text-center ${th}`}>العمر</SortTh>
              <SortTh k="route" sort={sort} onSort={onSort} className={`text-right ${th}`}
                title="الفرع الحائز: رصيده الآن ومعدل بيعه الشهري">من (الفرع الحائز)</SortTh>
              <SortTh k="to_stock" sort={sort} onSort={onSort} className={`text-right ${th}`}
                title="الفرع المستهدف: الكمية المقترحة، رصيده الآن ومعدل بيعه الشهري">إلى (الفرع المستهدف)</SortTh>
              <SortTh k="qty" sort={sort} onSort={onSort} className={`text-center ${th}`}>لكل فرع</SortTh>
              <SortTh k="rate" sort={sort} onSort={onSort} className={`text-center ${th}`}
                title="مجموع البيع الشهري في كل الفروع">بيع الشبكة/شهر</SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, SHOW).map((s, i) => (
              <tr key={`${s.itemcode}-${i}`} className="border-b border-line/60">
                <td className="px-3 py-1.5 text-content/70">{catLabel(s.category)}</td>
                <td className="px-3 py-1.5 text-content/80">{s.itemcode}</td>
                <td className="px-3 py-1.5 text-content">
                  {s.is_new_code && <span className="text-[10px] bg-emerald-100 text-emerald-700 rounded px-1 mr-1">جديد</span>}
                  {s.item_name}
                </td>
                <td className="px-3 py-1.5 text-center text-content/70">{s.sells_at}/{s.of_branches}</td>
                <td className="px-3 py-1.5 text-center text-content/60">
                  {s.age_days != null ? (s.age_days < 540 ? `${s.age_days}ي` : `${Math.round(s.age_days / 365)}س`) : '—'}
                </td>
                <td className="px-3 py-1.5 text-content/70 align-top">
                  <div>{bl(s.from_branch)}</div>
                  {pos(s.from_position)}
                </td>
                <td className="px-3 py-1.5 text-content/70 align-top">
                  {s.to_branches.map(t => (
                    <div key={t.code}>
                      {bl(t.code)} <span className="text-primary font-medium">× {t.qty}</span> {pos(t)}
                    </div>
                  ))}
                </td>
                <td className="px-3 py-1.5 text-center font-medium text-primary"
                  title={s.category === 'over_piled' ? 'الزيادة فوق الحد الأقصى — لكل فرع حسب المساحة تحت حده' : ''}>
                  {s.category === 'over_piled' ? `${s.total_qty} (إجمالي)` : s.qty_each}
                </td>
                <td className="px-3 py-1.5 text-center text-content/60">{s.network_avg}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length > SHOW && (
          <div className="p-2 text-xs text-content/50">يُعرض أول {SHOW} من {sorted.length} — رتّب أو ابحث لتضييق القائمة.</div>
        )}
        {q.data && rows.length === 0 && (
          <div className="p-4 text-sm text-content/50">لا توجد اقتراحات توزيعة للفئات المختارة.</div>
        )}
      </div>
    </div>
  )
}
