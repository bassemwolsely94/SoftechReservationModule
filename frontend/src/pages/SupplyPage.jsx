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
import AvailabilityInboxTab from './supply/AvailabilityInboxTab'
import SupplyCasesTab from './supply/SupplyCasesTab'
import IsrFulfilmentTab from './supply/IsrFulfilmentTab'
import BranchRequestsTab from './supply/BranchRequestsTab'
import { wildcardMatch } from '../utils/wildcard'
import useBranchLabels from '../hooks/useBranchLabels'

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
  ['inbox', 'صندوق الإتاحة'], ['cases', 'متابعة النواقص'],
  ['rates', 'معدلات البيع'], ['isr', 'طلبات التوريد / ISR'], ['isrfill', 'تلبية طلبات الفروع'],
  ['wa', 'طلبات واتساب'], ['dist', 'التوزيعة'],
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

      <div className="flex gap-1 border-b border-line overflow-x-auto">
        {SUPPLY_TABS.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 transition whitespace-nowrap ${
              tab === k ? 'border-primary text-primary' : 'border-transparent text-content/60 hover:text-content'}`}>
            {l}
          </button>
        ))}
      </div>

      {tab === 'inbox' ? <AvailabilityInboxTab />
        : tab === 'cases' ? <SupplyCasesTab />
        : tab === 'rates' ? <RatesTab />
        : tab === 'isr' ? <IsrTab />
        : tab === 'isrfill' ? <IsrFulfilmentTab />
        : tab === 'wa' ? <BranchRequestsTab /> : <DistributionTab />}
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
        <button onClick={() => proposeM.mutate()} disabled={proposeM.isPending}
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
          {push.status === 'proposed' && (
            <button onClick={onApprove} disabled={!canWrite || approving}
              className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm disabled:opacity-50"
              title={canWrite ? '' : 'يتطلب صلاحية اعتماد'}>
              {approving ? '…' : 'اعتماد'}
            </button>
          )}
          {push.status === 'approved' && (
            <button onClick={onExecute} disabled={!canWrite || gated || executing}
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
              <th className="text-right px-3 py-2">الكود</th>
              <th className="text-right px-3 py-2">الصنف</th>
              <th className="text-center px-3 py-2">الفرع/المخزن</th>
              <th className="text-center px-3 py-2">
                {push.target === 'hq' ? 'الحالي (الرئيسي)' : 'الحالي (الفرع)'}
              </th>
              {push.target === 'both' && <th className="text-center px-3 py-2">الحالي (الرئيسي)</th>}
              <th className="text-center px-3 py-2">المعدل الجديد</th>
              {push.status === 'executed' && <th className="text-center px-3 py-2">مؤكّد</th>}
            </tr>
          </thead>
          <tbody>
            {eligible.map(l => (
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
  const [covVal, setCovVal] = useState('')       // '' = engine default gap
  const [covUnit, setCovUnit] = useState('months')
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
    mutationFn: () => supplyApi.isrPropose({
      branch: branch.trim(), from_hq: fromHq, max_lines: maxLines.trim() || undefined,
      coverage_months: coverageMonths,
    }).then(r => r.data),
    onSuccess: (d) => { setSelected(d.id); invalidate() },
  })
  const xferM = useMutation({
    mutationFn: (pair) => supplyApi.isrTransfer(pair).then(r => r.data),
    onSuccess: invalidate,
  })
  const approveM = useMutation({ mutationFn: (id) => supplyApi.isrApprove(id).then(r => r.data), onSuccess: invalidate })
  const pushM = useMutation({ mutationFn: (id) => supplyApi.isrPush(id).then(r => r.data), onSuccess: invalidate })

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
        </div>
        <label className="flex items-center gap-1.5 text-xs text-content/70 mb-1.5 cursor-pointer">
          <input type="checkbox" checked={fromHq} onChange={e => setFromHq(e.target.checked)} />
          من الرئيسي إلى الفرع
        </label>
        <button onClick={() => proposeM.mutate()} disabled={proposeM.isPending || !branch.trim()}
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
          </span>
        )}
      </div>

      {showXfer && (
        <div className="rounded-lg border border-line bg-surface p-3 space-y-2">
          <div className="text-sm font-medium text-content flex items-center gap-2">
            توزيعة بين الفروع (فائض ← الرئيسي ← عجز)
            {previewQ.data?.run_id && <span className="text-xs text-content/50">تشغيل #{previewQ.data.run_id}</span>}
          </div>
          {previewQ.isLoading && <div className="text-sm text-content/50">جارٍ تحميل التوصيات…</div>}
          {previewQ.data?.pairs?.length === 0 && (
            <div className="text-sm text-content/50">لا توجد توصيات تحويل — شغّل محرك الطلب أولاً.</div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {previewQ.data?.pairs?.slice(0, 40).map((p, i) => (
              <div key={i} className="flex items-center justify-between gap-2 rounded border border-line px-3 py-1.5 text-sm">
                <span className="text-content">
                  {p.from} ({p.from_name?.split(',')[0]}) <span className="text-content/40">⟶ الرئيسي ⟶</span> {p.to} ({p.to_name?.split(',')[0]})
                </span>
                <span className="flex items-center gap-2 text-xs text-content/60">
                  {p.items} صنف · {Number(p.value).toLocaleString('ar-EG')} ج
                  <button onClick={() => xferM.mutate({ from: p.from, to: p.to })} disabled={xferM.isPending}
                    className="px-2 py-0.5 rounded bg-primary text-white disabled:opacity-50">توليد</button>
                </span>
              </div>
            ))}
          </div>
          {xferM.isSuccess && (
            <div className="text-xs text-emerald-600">تم إنشاء {xferM.data?.count} توزيعة (رجلين لكل منها) كمقترحات.</div>
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
                  {p.kind === 'self' ? `فرع ${bl(p.branchcode)}` : `${bl(p.branchcode)} ⟶ ${bl(p.dest_branchcode)}`} · #{p.id}
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
            <IsrDetail push={detailQ.data} gated={gated} canWrite={canWrite}
              onApprove={() => approveM.mutate(detailQ.data.id)}
              onPush={() => pushM.mutate(detailQ.data.id)}
              approving={approveM.isPending} pushing={pushM.isPending}
              actionError={approveM.error || pushM.error} />
          )}
        </div>
      </div>
    </div>
  )
}

function IsrDetail({ push, gated, canWrite, onApprove, onPush, approving, pushing, actionError }) {
  const bl = useBranchLabels()
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
  return (
    <div className="rounded-lg border border-line bg-surface">
      <div className="p-3 border-b border-line flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-content">
            طلب توريد #{push.id} · {push.kind === 'self' ? `فرع ${bl(push.branchcode)}` : `${bl(push.branchcode)} ⟶ ${bl(push.dest_branchcode)}`}
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
            <button onClick={onApprove} disabled={!canWrite || approving}
              className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm disabled:opacity-50"
              title={canWrite ? '' : 'يتطلب صلاحية اعتماد'}>
              {approving ? '…' : 'اعتماد'}
            </button>
          )}
          {push.status === 'approved' && (
            <button onClick={onPush} disabled={!canWrite || gated || pushing}
              className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm disabled:opacity-50"
              title={gated ? 'الترحيل معطّل (البوابة مغلقة)' : (canWrite ? '' : 'يتطلب صلاحية ترحيل')}>
              {pushing ? '…' : 'ترحيل إلى SOFTECH'}
            </button>
          )}
        </div>
      </div>

      {(actionError || push.error) && (
        <div className="px-3 py-2 text-xs text-rose-600 border-b border-line">
          {actionError?.response?.data?.detail || push.error || 'خطأ'}
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
              <th className="text-right px-3 py-2">الكود</th>
              <th className="text-right px-3 py-2">الصنف</th>
              <th className="text-center px-3 py-2">المطلوب</th>
              <th className="text-center px-3 py-2">رصيد الفرع</th>
              <th className="text-center px-3 py-2">المورد</th>
            </tr>
          </thead>
          <tbody>
            {lines.slice(0, 500).map((l, i) => (
              <tr key={i} className="border-b border-line/60">
                <td className="px-3 py-1.5 text-content/80">{l.itemcode}</td>
                <td className="px-3 py-1.5 text-content">{l.item_name}</td>
                <td className="px-3 py-1.5 text-center font-medium text-primary">{l.itemqty}</td>
                <td className="px-3 py-1.5 text-center text-content/60">{n(l.nowqty, 0)}</td>
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

  const q = useQuery({
    queryKey: ['dist-preview', cats],
    queryFn: () => supplyApi.distPreview({ category: cats, limit: 200 }).then(r => r.data),
  })
  const genM = useMutation({
    mutationFn: () => supplyApi.distGenerate({ categories: cats }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['isr-pushes'] }),
  })
  const canWrite = !!q.data?.can_write
  const toggle = (c) => setCats(cs => cs.includes(c) ? cs.filter(x => x !== c) : [...cs, c])

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
          <button onClick={() => genM.mutate()} disabled={genM.isPending || !cats.length}
            className="px-4 py-1.5 rounded bg-primary text-white text-sm font-medium disabled:opacity-50 mr-auto"
            title={canWrite ? '' : 'يتطلب صلاحية'}>
            {genM.isPending ? 'جارٍ التوليد…' : '＋ توليد مقترحات التوزيعة'}
          </button>
        </div>
        {q.data?.summary && (
          <div className="text-xs text-content/60">
            إجمالي {q.data.summary.total} اقتراح — تُنشأ كطلبات توريد (تظهر في تبويب «طلبات التوريد» للاعتماد والترحيل).
          </div>
        )}
        {genM.isSuccess && (
          <div className="text-xs text-emerald-600">تم إنشاء {genM.data?.count} مسار توزيعة كمقترحات.</div>
        )}
        {genM.isError && (
          <div className="text-xs text-rose-600">{genM.error?.response?.data?.detail || 'تعذّر التوليد'}</div>
        )}
      </div>

      <div className="rounded-lg border border-line bg-surface overflow-x-auto max-h-[70vh]">
        {q.isLoading && <div className="p-4 text-sm text-content/50">جارٍ التحميل…</div>}
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-xs text-content/60 border-b border-line">
              <th className="text-right px-3 py-2">النوع</th>
              <th className="text-right px-3 py-2">الكود</th>
              <th className="text-right px-3 py-2">الصنف</th>
              <th className="text-center px-3 py-2">يُباع بـ</th>
              <th className="text-center px-3 py-2">العمر</th>
              <th className="text-center px-3 py-2">من ⟶ إلى</th>
              <th className="text-center px-3 py-2">لكل فرع</th>
              <th className="text-center px-3 py-2">المعدل</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.suggestions?.slice(0, 200).map((s, i) => (
              <tr key={i} className="border-b border-line/60">
                <td className="px-3 py-1.5 text-content/70">{DIST_CATS.find(c => c[0] === s.category)?.[1] || s.category}</td>
                <td className="px-3 py-1.5 text-content/80">{s.itemcode}</td>
                <td className="px-3 py-1.5 text-content">
                  {s.is_new_code && <span className="text-[10px] bg-emerald-100 text-emerald-700 rounded px-1 mr-1">جديد</span>}
                  {s.item_name}
                </td>
                <td className="px-3 py-1.5 text-center text-content/70">{s.sells_at}/{s.of_branches}</td>
                <td className="px-3 py-1.5 text-center text-content/60">
                  {s.age_days != null ? (s.age_days < 540 ? `${s.age_days}ي` : `${Math.round(s.age_days / 365)}س`) : '—'}
                </td>
                <td className="px-3 py-1.5 text-center text-content/70">
                  {bl(s.from_branch)} ⟶ [{s.to_branches.map(t =>
                    s.category === 'over_piled' ? `${bl(t.code)} × ${t.qty}` : bl(t.code)).join('، ')}]
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
        {q.data?.suggestions?.length === 0 && (
          <div className="p-4 text-sm text-content/50">لا توجد اقتراحات توزيعة للفئات المختارة.</div>
        )}
      </div>
    </div>
  )
}
