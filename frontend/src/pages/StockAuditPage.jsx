/**
 * StockAuditPage — تدقيق حركات المخزون (doc 32). Route /stock-audit.
 *
 * Findings from the deterministic checks over the SOFTECH stock-movement mirror. The server
 * decides everything (who sees which branch, who may review, thresholds); this page only
 * shows the result and sends the user's choices. Review happens inline — no modals.
 *
 * Tabs: summary · sales (checks 1–3) · adjustments (check 5 + per-user ranking) · settings.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { stockAuditApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import DataTable, { SortIcon } from '../components/DataTable'
import useGridKeyboard from '../hooks/useGridKeyboard'
import useHelpTab from '../help/useHelpTab'

const TABS = [
  { key: 'summary',     label: '📊 ملخص' },
  { key: 'sales',       label: '🧾 المبيعات والأسعار' },
  { key: 'adjustments', label: '⚖️ تسويات المخزون' },
  { key: 'availability', label: '📦 توافر المخزون' },
  { key: 'returns',     label: '↩️ المرتجعات' },
  { key: 'timing',      label: '🕘 مواعيد الإدخال' },
  { key: 'settings',    label: '⚙️ الإعدادات' },
]
const STATUS = {
  open:      { label: 'مفتوح',        cls: 'bg-amber-50 text-amber-800 border-amber-200' },
  escalated: { label: 'تم التصعيد',   cls: 'bg-red-50 text-red-700 border-red-200' },
  reviewed:  { label: 'تمت المراجعة', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  dismissed: { label: 'تم التجاهل',   cls: 'bg-gray-100 text-gray-600 border-gray-200' },
}
const SEVERITY = {
  critical: { label: 'حرج',    dot: 'bg-red-500' },
  warning:  { label: 'تنبيه',  dot: 'bg-amber-500' },
  info:     { label: 'معلومة', dot: 'bg-sky-500' },
}
const STATUS_FILTERS = [
  { key: 'open,escalated', label: 'المفتوحة' },
  { key: 'reviewed', label: 'تمت مراجعتها' },
  { key: 'dismissed', label: 'المتجاهلة' },
  { key: '', label: 'الكل' },
]
const MOVE_LABEL = { reviewed: '✔ تمت المراجعة', dismissed: 'تجاهل', escalated: '⬆ تصعيد', open: '↺ إعادة فتح' }
const DOC = { '115': 'بيع', '30': 'مرتجع', '10': 'شراء', '50': 'فائض جرد', '150': 'عجز جرد', '160': 'هالك',
              '125': 'صرف لفرع', '25': 'استلام من فرع', '80': 'حجز', '180': 'تسليم حجز' }
const PARAM_LABEL = {
  min_loss_pct: 'أقل نسبة خسارة %', min_loss_egp: 'أقل خسارة (ج.م)',
  critical_loss_pct: 'حرج من نسبة %', critical_loss_egp: 'حرج من قيمة (ج.م)',
  excluded_personcodes: 'عملاء مستبعدون (أكواد)', excluded_channel_buckets: 'قنوات مستبعدة',
  window_min: 'خلال (دقيقة)', cross_doc_min_lines: 'أقل عدد سطور للمستند',
  include_same_document: 'تكرار السطر داخل نفس المستند', doccodes: 'أنواع المستندات',
  ratio: 'نسبة الأعلى للأقل أكبر من', warning_ratio: 'تنبيه من نسبة', min_price_egp: 'تجاهل سعر أقل من (ج.م)',
  count: 'عدد المرات', days: 'خلال (يوم)', single_egp: 'تسوية واحدة من (ج.م)', critical_egp: 'حرج من (ج.م)',
  change_pct: 'تغيّر أكبر من %', warning_pct: 'تنبيه من تغيّر %', lookback_days: 'مقارنة بشراء خلال (يوم)',
  same_supplier_only: 'نفس المورد فقط', excluded_suppliers: 'موردون مستبعدون (أكواد)',
  min_monthly_qty: 'أقل معدل بيع شهري', qty_tolerance: 'سماحية الكمية', hours: 'خلال (ساعة) من الجرد',
  grace_min: 'سماح (دقيقة)', warning_after_min: 'تنبيه بعد (دقيقة) خارج المواعيد',
  excluded_users: 'مستخدمو SOFTECH مستبعدون',
}

const CODES_HINT = { doccodes: 'فارغ = كل أنواع المستندات', excluded_personcodes: 'مثال: 4785, 4283',
                     excluded_channel_buckets: 'مثال: credit', excluded_suppliers: 'مثال: 4469, 4470',
                     excluded_users: 'مثال: 1509' }

const fmt = (v, d = 2) => (v == null || v === '' ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }))
const fmtInt = v => Number(v || 0).toLocaleString('en-US')
const fmtTime = v => (v ? new Date(v).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—')
const isoDay = d => d.toISOString().slice(0, 10)
const daysAgo = n => { const d = new Date(); d.setDate(d.getDate() - n); return isoDay(d) }

function errText(e) {
  return e?.response?.data?.detail || 'حدث خطأ — حاول مرة أخرى'
}

// ── Header: freshness + refresh ───────────────────────────────────────────────

function RefreshButton() {
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const runs = useQuery({ queryKey: ['stock-audit-runs'], queryFn: () => stockAuditApi.runs().then(r => r.data),
                          refetchInterval: q => (q.state.data?.refreshing ? 4000 : false) })
  const busy = runs.data?.refreshing
  const start = useMutation({
    mutationFn: () => stockAuditApi.refresh(),
    onSuccess: () => { setMsg(''); qc.invalidateQueries({ queryKey: ['stock-audit-runs'] }) },
    onError: e => setMsg(errText(e)),
  })
  // when a refresh finishes, reload every stock-audit query (findings, summary, freshness)
  const wasBusy = useRef(false)
  useEffect(() => {
    if (wasBusy.current && !busy) {
      qc.invalidateQueries({ queryKey: ['stock-audit'] })
      qc.invalidateQueries({ queryKey: ['data-freshness'] })
    }
    wasBusy.current = !!busy
  }, [busy, qc])
  return (
    <div className="flex items-center gap-2">
      <button data-tour="stock-audit-main-refresh" onClick={() => start.mutate()} disabled={busy || start.isPending}
        className="px-3 py-1.5 rounded-md bg-primary text-white text-xs font-bold disabled:opacity-50">
        {busy ? '⏳ جارٍ التحديث من SOFTECH…' : '🔄 تحديث الآن'}
      </button>
      {msg && <span className="text-xs text-red-600">{msg}</span>}
    </div>
  )
}

// ── Filters ───────────────────────────────────────────────────────────────────

function Filters({ f, setF, branches, channels = [], showStatus = true }) {
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  return (
    <div className="flex flex-wrap items-end gap-2 mb-3 text-sm" data-tour="stock-audit-main-filters">
      <label className="flex flex-col text-xs text-gray-500">من
        <input type="date" value={f.from} onChange={e => set('from', e.target.value)}
          className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
      </label>
      <label className="flex flex-col text-xs text-gray-500">إلى
        <input type="date" value={f.to} onChange={e => set('to', e.target.value)}
          className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
      </label>
      {branches.length > 1 && (
        <label className="flex flex-col text-xs text-gray-500">الفرع
          <select value={f.branch} onChange={e => set('branch', e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.branchcode} value={b.branchcode}>{b.branch_name?.ar || b.branchcode}</option>)}
          </select>
        </label>
      )}
      {showStatus && (
        <>
          <label className="flex flex-col text-xs text-gray-500">الحالة
            <select value={f.status} onChange={e => set('status', e.target.value)}
              className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
              {STATUS_FILTERS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col text-xs text-gray-500">الخطورة
            <select value={f.severity} onChange={e => set('severity', e.target.value)}
              className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
              <option value="">الكل</option>
              {Object.entries(SEVERITY).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
            </select>
          </label>
          {channels.length > 0 && (
            <label className="flex flex-col text-xs text-gray-500" data-tour="stock-audit-main-channel">قناة البيع
              <select value={f.channel} onChange={e => set('channel', e.target.value)}
                className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
                <option value="">كل القنوات</option>
                {channels.map(c => <option key={c.code} value={c.code}>{c.label}</option>)}
              </select>
            </label>
          )}
          <label className="flex flex-col text-xs text-gray-500 grow min-w-[180px]">بحث
            <input value={f.q} onChange={e => set('q', e.target.value)} placeholder="كود صنف، اسم، رقم مستند…"
              className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
          </label>
        </>
      )}
    </div>
  )
}

// ── Summary tab ───────────────────────────────────────────────────────────────

function SummaryTab({ f, onOpenRule }) {
  const params = { from: f.from, to: f.to, branch: f.branch || undefined }
  const { data, isLoading, error } = useQuery({
    queryKey: ['stock-audit', 'summary', params], queryFn: () => stockAuditApi.summary(params).then(r => r.data) })
  if (isLoading) return <div className="py-12 text-center text-gray-400">جاري التحميل…</div>
  if (error) return <div className="py-12 text-center text-red-600">{errText(error)}</div>
  const rules = data.rules
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-tour="stock-audit-main-cards">
        {rules.map(r => {
          const delta = r.total - r.previous_total
          return (
            <button key={r.code} onClick={() => onOpenRule(r.code)}
              className="text-right bg-white border border-gray-200 rounded-xl p-4 hover:border-primary/50 transition">
              <div className="text-xs text-gray-500">فحص {r.number}</div>
              <div className="font-bold text-gray-900">{r.name_ar}</div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl font-bold text-gray-900">{fmtInt(r.open)}</span>
                <span className="text-xs text-gray-500">مفتوحة</span>
                {r.critical_open > 0 && <span className="text-xs font-bold text-red-600">· {fmtInt(r.critical_open)} حرجة</span>}
              </div>
              <div className="text-xs text-gray-500 mt-1">{fmt(r.value_open)} ج.م · إجمالي الفترة {fmtInt(r.total)}
                <span className={delta > 0 ? 'text-red-600' : 'text-emerald-600'}> ({delta > 0 ? '+' : ''}{fmtInt(delta)} عن الفترة السابقة)</span>
              </div>
            </button>
          )
        })}
      </div>
      <div className="bg-white rounded-xl border border-gray-200" data-tour="stock-audit-main-matrix">
        <MatrixGrid rules={rules} branches={data.branches} onOpenRule={onOpenRule} />
      </div>
    </div>
  )
}

function MatrixGrid({ rules, branches, onOpenRule }) {
  const rows = useMemo(() => branches.map(b => ({
    ...b, name: b.branch_name?.ar || b.branchcode,
    ...Object.fromEntries(rules.map(r => [`r_${r.code}`, b.per_rule[r.code] || 0])),
  })), [branches, rules])
  const columns = useMemo(() => [
    { key: 'name', label: 'الفرع', width: 150, cellClass: 'font-medium text-gray-900' },
    ...rules.map(r => ({
      key: `r_${r.code}`, label: r.name_ar, type: 'integer', width: 120, align: 'center',
      render: (v, b) => (v
        ? <button className="text-primary font-bold hover:underline" onClick={() => onOpenRule(r.code, b.branchcode)}>{fmtInt(v)}</button>
        : <span className="text-gray-300">—</span>),
    })),
    { key: 'open', label: 'المفتوحة', type: 'integer', width: 100, align: 'center', cellClass: 'font-bold', render: v => fmtInt(v) },
    { key: 'value_open', label: 'القيمة (ج.م)', type: 'currency', width: 130, align: 'center', render: v => fmt(v) },
  ], [rules, onOpenRule])
  return (
    <DataTable columns={columns} rows={rows} rowKey={b => b.branchcode} stickyHeader={false}
      defaultSort={{ key: 'value_open', dir: 'desc' }}
      emptyLabel="✅ لا توجد ملاحظات مفتوحة في هذه الفترة" />
  )
}

// ── Findings grid (sales + adjustments tabs) ──────────────────────────────────

const EVIDENCE_COLUMNS = [
  { key: 'docnumber', label: 'المستند', type: 'integer', width: 150, render: (v, l) => `${DOC[l.doccode] || l.doccode} ${v}` },
  { key: 'trans_time', label: 'الوقت', width: 130, render: v => fmtTime(v) },
  { key: 'itemcode', label: 'الصنف', width: 90 },
  { key: 'qty', label: 'الكمية', type: 'number', width: 80, render: v => fmt(v, 2) },
  { key: 'price', label: 'السعر', type: 'number', width: 90, render: v => fmt(v) },
  { key: 'cost', label: 'التكلفة', type: 'number', width: 90, render: v => fmt(v) },
  { key: 'newqty', label: 'الرصيد بعده', type: 'number', width: 100, render: v => fmt(v, 2) },
  { key: 'usercode', label: 'المستخدم', width: 90 },
]

function EvidenceLines({ ev }) {
  const lines = ev?.lines || (ev?.line ? [ev.line] : [])
  if (!lines.length) return null
  return (
    <div className="mt-2 bg-white rounded-lg border border-gray-100">
      <DataTable columns={EVIDENCE_COLUMNS} rows={lines} stickyHeader={false} />
    </div>
  )
}

function ReviewBar({ statuses, onMove, pending, compact }) {
  const [note, setNote] = useState('')
  if (!statuses?.length) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="ملاحظة (مطلوبة للتجاهل والتصعيد)"
        className="border border-gray-200 rounded-md px-2 py-1 text-xs bg-white min-w-[220px] grow" />
      {statuses.map(s => (
        <button key={s} disabled={pending} onClick={() => onMove(s, note, () => setNote(''))}
          className={`px-2.5 py-1 rounded-md text-xs font-bold border disabled:opacity-50 ${
            s === 'reviewed' ? 'bg-emerald-600 text-white border-emerald-600'
              : s === 'escalated' ? 'bg-white text-red-700 border-red-300'
                : 'bg-white text-gray-700 border-gray-300'}`}>
          {MOVE_LABEL[s]}
        </button>
      ))}
    </div>
  )
}

// Server-side sort keys (stock_audit/views.py SORTS). Numbers/dates open descending, text ascending.
const FINDING_COLUMNS = [
  { key: 'rule', label: 'الفحص' },
  { key: 'branch', label: 'الفرع' },
  { key: 'item', label: 'الصنف' },
  { key: 'account', label: 'القناة / الحساب' },
  { key: 'pic', label: 'العميل (PIC)', sortable: false },
  { key: 'value', label: 'القيمة (ج.م)', align: 'text-left', firstDesc: true },
  { key: 'status', label: 'الحالة' },
  { key: 'doc', label: 'المستند' },
  { key: 'date', label: 'الوقت', firstDesc: true },
  { key: 'user', label: 'المستخدم' },
]

function SortTh({ col, label, align = 'text-right', firstDesc, sortable = true, sort, onSort }) {
  if (!sortable) return <th className={`px-2 py-2 font-semibold whitespace-nowrap ${align}`}>{label}</th>
  const active = sort === col || sort === `-${col}`
  const dir = sort === `-${col}` ? 'desc' : 'asc'
  const next = active ? (dir === 'desc' ? col : `-${col}`) : (firstDesc ? `-${col}` : col)
  return (
    <th onClick={() => onSort(next)}
      className={`px-2 py-2 font-semibold whitespace-nowrap cursor-pointer select-none hover:bg-gray-100 ${align}`}>
      {label}<SortIcon active={active} dir={dir} />
    </th>
  )
}

function FindingsGrid({ f, rules, access }) {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [picked, setPicked] = useState(new Set())
  const [open, setOpen] = useState(null)
  const [msg, setMsg] = useState('')
  const params = { from: f.from, to: f.to, branch: f.branch || undefined, status: f.status || undefined,
                   severity: f.severity || undefined, channel: f.channel || undefined,
                   q: f.q || undefined, rule: rules.join(','),
                   sort: f.sort, page }
  const filterKey = [f.from, f.to, f.branch, f.status, f.severity, f.channel, f.q, f.sort, rules.join(',')].join('|')
  useEffect(() => { setPage(1); setPicked(new Set()) }, [filterKey])
  const { data, isLoading, error } = useQuery({
    queryKey: ['stock-audit', 'findings', params], queryFn: () => stockAuditApi.findings(params).then(r => r.data),
    placeholderData: prev => prev })
  const rows = data?.results || []
  const refresh = () => qc.invalidateQueries({ queryKey: ['stock-audit'] })

  const one = useMutation({
    mutationFn: ({ id, status, note }) => stockAuditApi.review(id, { status, note }),
    onSuccess: () => { setMsg(''); refresh() }, onError: e => setMsg(errText(e)) })
  const bulk = useMutation({
    mutationFn: d => stockAuditApi.bulkReview(d),
    onSuccess: r => {
      const s = r.data.skipped.length
      setMsg(s ? `تم ${r.data.done} — وتُرك ${s}: ${r.data.skipped[0].reason}` : '')
      setPicked(new Set()); refresh()
    },
    onError: e => setMsg(errText(e)) })

  const toggle = r => setPicked(p => { const n = new Set(p); n.has(r.id) ? n.delete(r.id) : n.add(r.id); return n })
  const kb = useGridKeyboard({
    rows, getKey: r => r.id, onToggle: toggle,
    onConfirm: r => setOpen(o => (o === r.id ? null : r.id)),
    onSelectAll: () => setPicked(p => (p.size === rows.length ? new Set() : new Set(rows.map(r => r.id)))),
  })
  const pickedRows = rows.filter(r => picked.has(r.id))
  const bulkMoves = pickedRows.length
    ? [...pickedRows.map(r => new Set(r.next_statuses)).reduce((a, b) => new Set([...a].filter(x => b.has(x))))]
    : []

  async function download() {
    setMsg('')
    try {
      const { page: _p, ...q } = params
      const r = await stockAuditApi.exportFindings(q)
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a'); a.href = url; a.download = `stock-audit-${f.from}-${f.to}.xlsx`; a.click()
      URL.revokeObjectURL(url)
    } catch { setMsg('ليس لديك صلاحية التصدير.') }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-2 text-xs text-gray-500">
        <span>{fmtInt(data?.count)} ملاحظة · {fmt(data?.totals?.value)} ج.م</span>
        <span className="text-gray-400">· اضغط عنوان أي عمود للترتيب</span>
        {access.can_export && (
          <button data-tour="stock-audit-main-export" onClick={download}
            className="ms-auto px-2.5 py-1 rounded-md border border-gray-300 bg-white text-gray-700 font-bold">⬇️ تصدير Excel</button>
        )}
      </div>
      {pickedRows.length > 0 && access.can_review && (
        <div className="mb-2 p-2 rounded-lg bg-primary/5 border border-primary/20 flex flex-wrap items-center gap-2" data-tour="stock-audit-main-bulk">
          <span className="text-xs font-bold text-gray-700">{pickedRows.length} محددة</span>
          <div className="grow"><ReviewBar compact statuses={bulkMoves} pending={bulk.isPending}
            onMove={(s, note, done) => bulk.mutate({ ids: pickedRows.map(r => r.id), status: s, note }, { onSuccess: done })} /></div>
        </div>
      )}
      {msg && <div className="mb-2 text-xs text-red-600">{msg}</div>}
      <div {...kb.containerProps} data-tour="stock-audit-main-grid"
        className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <th className="px-2 py-2 w-8"></th>
              {FINDING_COLUMNS.map(c => <SortTh key={c.key} col={c.key} label={c.label} align={c.align}
                firstDesc={c.firstDesc} sortable={c.sortable} sort={f.sort} onSort={f.setSort} />)}
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={11} className="py-10 text-center text-gray-400">جاري التحميل…</td></tr>}
            {error && <tr><td colSpan={11} className="py-10 text-center text-red-600">{errText(error)}</td></tr>}
            {!isLoading && !error && rows.length === 0 && (
              <tr><td colSpan={11} className="py-10 text-center text-gray-400">✅ لا توجد ملاحظات بهذه الفلاتر</td></tr>
            )}
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return [
                <tr key={r.id} {...rp} onClick={() => setOpen(o => (o === r.id ? null : r.id))}
                  className={`border-b border-gray-100 cursor-pointer hover:bg-gray-50 ${rp.className}`}>
                  <td className="px-2 py-2" onClick={e => e.stopPropagation()}>
                    {access.can_review && <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r)} />}
                  </td>
                  <td className="px-2 py-2 whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${SEVERITY[r.severity]?.dot}`} title={SEVERITY[r.severity]?.label} />
                      {r.rule.name_ar}
                    </span>
                  </td>
                  <td className="px-2 py-2 whitespace-nowrap">{r.branch_name?.ar}</td>
                  <td className="px-2 py-2"><div dir="auto" className="font-medium text-gray-900 truncate max-w-[260px] text-right">{r.item_name || r.itemcode}</div>
                    <div className="text-[11px] text-gray-400">{r.itemcode}</div></td>
                  <td className="px-2 py-2">{r.sales
                    ? <><div className="font-medium text-gray-900 whitespace-nowrap">{r.sales.channel_label || '—'}</div>
                        <div dir="auto" className="text-[11px] text-gray-500 truncate max-w-[220px] text-right" title={r.sales.account_name}>
                          {r.sales.account_name || r.sales.account_code}</div></>
                    : <span className="text-gray-300">—</span>}</td>
                  <td className="px-2 py-2">{r.sales?.pic
                    ? <><div dir="auto" className="text-gray-900 truncate max-w-[200px] text-right">{r.sales.pic_name || '—'}</div>
                        <div className="text-[11px] text-gray-400">{r.sales.pic}</div></>
                    : <span className="text-gray-300">{r.sales ? 'بدون PIC' : '—'}</span>}</td>
                  <td className="px-2 py-2 text-left font-bold whitespace-nowrap">{fmt(r.value_egp)}</td>
                  <td className="px-2 py-2 whitespace-nowrap"><span className={`px-2 py-0.5 rounded-full border text-[11px] ${STATUS[r.status]?.cls}`}>{STATUS[r.status]?.label}</span></td>
                  <td className="px-2 py-2 whitespace-nowrap">{DOC[r.doccode] || r.doccode} {r.docnumber}</td>
                  <td className="px-2 py-2 whitespace-nowrap">{fmtTime(r.occurred_at)}</td>
                  <td className="px-2 py-2 whitespace-nowrap">{r.user_name || r.softech_user || '—'}</td>
                </tr>,
                open === r.id && (
                  <tr key={`${r.id}-d`} className="bg-gray-50/60 border-b border-gray-100">
                    <td></td>
                    <td colSpan={10} className="px-2 py-3">
                      <div className="text-sm text-gray-800">{r.message_ar}</div>
                      <EvidenceLines ev={r.evidence} />
                      {r.review_note && <pre className="mt-2 text-xs text-gray-600 whitespace-pre-wrap font-sans">{r.review_note}</pre>}
                      {access.can_review && (
                        <div className="mt-2" data-tour="stock-audit-main-review"><ReviewBar statuses={r.next_statuses} pending={one.isPending}
                          onMove={(s, note, done) => one.mutate({ id: r.id, status: s, note }, { onSuccess: done })} /></div>
                      )}
                    </td>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </table>
      </div>
      {data && (data.next || data.previous) && (
        <div className="flex justify-center gap-2 mt-3 text-xs">
          <button disabled={!data.previous} onClick={() => setPage(p => p - 1)} className="px-3 py-1 border rounded-md disabled:opacity-40">السابق</button>
          <span className="py-1 text-gray-500">صفحة {page}</span>
          <button disabled={!data.next} onClick={() => setPage(p => p + 1)} className="px-3 py-1 border rounded-md disabled:opacity-40">التالي</button>
        </div>
      )}
    </div>
  )
}

function RuleChips({ codes, value, onChange, meta }) {
  if (codes.length < 2) return null
  return (
    <div className="flex flex-wrap gap-1 mb-3" data-tour="stock-audit-main-rules">
      {[{ code: '', name_ar: 'كل الفحوص' }, ...codes.map(c => meta[c])].map(r => (
        <button key={r.code} onClick={() => onChange(r.code)}
          className={`px-3 py-1 rounded-full text-xs border ${value === r.code ? 'bg-primary text-white border-primary' : 'bg-white text-gray-600 border-gray-200'}`}>
          {r.number ? `${r.number}. ` : ''}{r.name_ar}
        </button>
      ))}
    </div>
  )
}

function UserRanking({ f }) {
  const params = { from: f.from, to: f.to, branch: f.branch || undefined }
  const { data } = useQuery({ queryKey: ['stock-audit', 'by-user', params], queryFn: () => stockAuditApi.byUser(params).then(r => r.data) })
  const rows = useMemo(() => (data?.rows || []).map(r => ({
    ...r, user: r.user_name || r.usercode || '', branch: r.branch_name?.ar || r.branchcode,
    surplus: r.by_doccode['50'] || 0, shortage: r.by_doccode['150'] || 0, damaged: r.by_doccode['160'] || 0,
  })), [data])
  return (
    <div className="mt-6" data-tour="stock-audit-main-ranking">
      <h3 className="font-bold text-gray-900 mb-2">التسويات حسب المستخدم <span className="text-xs font-normal text-gray-500">(كل التسويات في الفترة، بدون حد)</span></h3>
      <div className="bg-white rounded-xl border border-gray-200">
        <DataTable columns={RANKING_COLUMNS} rows={rows} rowKey={r => `${r.branchcode}-${r.usercode}`}
          stickyHeader={false} defaultSort={{ key: 'value_egp', dir: 'desc' }} emptyLabel="لا توجد تسويات في الفترة" />
      </div>
    </div>
  )
}

const RANKING_COLUMNS = [
  { key: 'user', label: 'المستخدم', width: 200,
    render: (v, r) => <>{v || '—'} <span className="text-[11px] text-gray-400">{r.usercode}</span></> },
  { key: 'branch', label: 'الفرع', width: 150 },
  { key: 'count', label: 'عدد التسويات', type: 'integer', width: 110, align: 'center', render: v => fmtInt(v) },
  { key: 'surplus', label: 'فائض', type: 'integer', width: 80, align: 'center', render: v => fmtInt(v) },
  { key: 'shortage', label: 'عجز', type: 'integer', width: 80, align: 'center', render: v => fmtInt(v) },
  { key: 'damaged', label: 'هالك', type: 'integer', width: 80, align: 'center', render: v => fmtInt(v) },
  { key: 'value_egp', label: 'القيمة بالتكلفة (ج.م)', type: 'currency', width: 160, align: 'left', cellClass: 'font-bold', render: v => fmt(v) },
  { key: 'open_findings', label: 'ملاحظات مفتوحة', type: 'integer', width: 120, align: 'center', render: v => (v ? fmtInt(v) : '—') },
]

// ── Settings tab ──────────────────────────────────────────────────────────────

function ParamInput({ name, spec, value, onChange, disabled, placeholder }) {
  if (spec.type === 'bool') {
    return (
      <select disabled={disabled} value={value === undefined ? '' : String(value)}
        onChange={e => onChange(e.target.value === '' ? undefined : e.target.value === 'true')}
        className="border border-gray-200 rounded-md px-2 py-1 text-sm bg-white w-full">
        {placeholder !== undefined && <option value="">كالعام ({placeholder ? 'مفعّل' : 'متوقف'})</option>}
        <option value="false">متوقف</option><option value="true">مفعّل</option>
      </select>
    )
  }
  if (spec.type === 'codes') {
    return (
      <input disabled={disabled} value={value === undefined ? '' : (value || []).join(', ')}
        placeholder={placeholder !== undefined ? `كالعام: ${(placeholder || []).join(', ') || (name === 'doccodes' ? 'كل الأنواع' : 'لا شيء')}`
          : (CODES_HINT[name] || '')}
        onChange={e => onChange(e.target.value.trim() === '' && placeholder !== undefined ? undefined
          : e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
        className="border border-gray-200 rounded-md px-2 py-1 text-sm bg-white w-full" />
    )
  }
  return (
    <input type="number" disabled={disabled} min={spec.min} max={spec.max}
      step={name.includes('ratio') ? 0.05 : name.includes('pct') ? 1 : name.includes('egp') ? 50 : 1}
      value={value === undefined ? '' : value} placeholder={placeholder !== undefined ? `كالعام: ${placeholder}` : ''}
      onChange={e => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      className="border border-gray-200 rounded-md px-2 py-1 text-sm bg-white w-full" />
  )
}

function RuleCard({ rule, branches, canEdit }) {
  const qc = useQueryClient()
  const [params, setParams] = useState(rule.params)
  const [enabled, setEnabled] = useState(rule.enabled)
  const [branch, setBranch] = useState('')
  const [ov, setOv] = useState({})
  const [msg, setMsg] = useState('')
  const saved = () => { setMsg('✔ تم الحفظ'); qc.invalidateQueries({ queryKey: ['stock-audit'] }) }
  const save = useMutation({ mutationFn: () => stockAuditApi.updateRule(rule.code, { enabled, params }),
                             onSuccess: saved, onError: e => setMsg(errText(e)) })
  const existing = rule.overrides.find(o => o.branchcode === branch)
  const saveOv = useMutation({
    mutationFn: () => {
      const clean = Object.fromEntries(Object.entries(ov.params || {}).filter(([, v]) => v !== undefined))
      return stockAuditApi.setOverride(rule.code, branch, { params: clean, enabled: ov.enabled ?? null })
    }, onSuccess: saved, onError: e => setMsg(errText(e)) })
  const pickBranch = code => {
    setBranch(code)
    const o = rule.overrides.find(x => x.branchcode === code)
    setOv({ params: { ...(o?.params || {}) }, enabled: o?.enabled ?? null })
  }
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="font-bold text-gray-900">{rule.number}. {rule.name_ar}</span>
        <label className="ms-auto flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" disabled={!canEdit} checked={enabled} onChange={e => setEnabled(e.target.checked)} /> مفعّل
        </label>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(rule.schema).map(([k, spec]) => (
          <label key={k} className="text-xs text-gray-500">{PARAM_LABEL[k] || k}
            <ParamInput name={k} spec={spec} value={params[k]} disabled={!canEdit}
              onChange={v => setParams(p => ({ ...p, [k]: v ?? rule.defaults[k] }))} />
          </label>
        ))}
      </div>
      {canEdit && (
        <div className="mt-3 flex items-center gap-2">
          <button data-tour="stock-audit-main-save" onClick={() => save.mutate()} disabled={save.isPending}
            className="px-3 py-1.5 rounded-md bg-primary text-white text-xs font-bold disabled:opacity-50">حفظ الحدود العامة</button>
          {msg && <span className="text-xs text-gray-600">{msg}</span>}
        </div>
      )}
      <div className="mt-4 pt-3 border-t border-gray-100">
        <div className="text-xs font-bold text-gray-700 mb-2">حدود خاصة بفرع
          {rule.overrides.length > 0 && <span className="font-normal text-gray-500"> — مضبوطة لـ: {rule.overrides.map(o => o.branch_name?.ar || o.branchcode).join('، ')}</span>}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <select value={branch} onChange={e => pickBranch(e.target.value)}
            className="border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
            <option value="">اختر فرعاً…</option>
            {branches.map(b => <option key={b.branchcode} value={b.branchcode}>{b.branch_name?.ar || b.branchcode}</option>)}
          </select>
          {branch && (
            <label className="text-xs text-gray-500">الفحص في هذا الفرع
              <select disabled={!canEdit} value={ov.enabled === null || ov.enabled === undefined ? '' : String(ov.enabled)}
                onChange={e => setOv(o => ({ ...o, enabled: e.target.value === '' ? null : e.target.value === 'true' }))}
                className="block border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
                <option value="">كالعام</option><option value="true">مفعّل</option><option value="false">متوقف</option>
              </select>
            </label>
          )}
        </div>
        {branch && (
          <>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 mt-2">
              {Object.entries(rule.schema).map(([k, spec]) => (
                <label key={k} className="text-xs text-gray-500">{PARAM_LABEL[k] || k}
                  <ParamInput name={k} spec={spec} value={ov.params?.[k]} disabled={!canEdit} placeholder={rule.params[k]}
                    onChange={v => setOv(o => ({ ...o, params: { ...o.params, [k]: v } }))} />
                </label>
              ))}
            </div>
            {canEdit && (
              <div className="mt-2 flex gap-2">
                <button onClick={() => saveOv.mutate()} disabled={saveOv.isPending}
                  className="px-3 py-1.5 rounded-md border border-primary text-primary text-xs font-bold disabled:opacity-50">حفظ حدود الفرع</button>
                {existing && (
                  <button onClick={() => stockAuditApi.clearOverride(rule.code, branch).then(() => { pickBranch(''); saved() })}
                    className="px-3 py-1.5 rounded-md border border-gray-300 text-gray-600 text-xs">رجوع للحدود العامة</button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function AccessPanel() {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [msg, setMsg] = useState('')
  const grants = useQuery({ queryKey: ['stock-audit', 'access'], queryFn: () => stockAuditApi.access().then(r => r.data.rows) })
  const cands = useQuery({ queryKey: ['stock-audit', 'cands', q], enabled: q.trim().length >= 2,
                           queryFn: () => stockAuditApi.candidates(q.trim()).then(r => r.data.rows) })
  const done = () => { setMsg(''); qc.invalidateQueries({ queryKey: ['stock-audit'] }) }
  const grant = useMutation({ mutationFn: id => stockAuditApi.grant({ staff_id: id }), onSuccess: done, onError: e => setMsg(errText(e)) })
  const revoke = useMutation({ mutationFn: id => stockAuditApi.revoke(id), onSuccess: done, onError: e => setMsg(errText(e)) })
  const active = (grants.data || []).filter(g => !g.revoked_at)
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4" data-tour="stock-audit-main-access">
      <div className="font-bold text-gray-900">مديرو الفروع المسموح لهم</div>
      <p className="text-xs text-gray-500 mb-3">يرى مدير الفرع ملاحظات فرعه فقط ويراجعها ويصدّرها، ولا يغيّر الحدود. الإدارة والمشرفون والجودة يرون كل الفروع بصلاحية دورهم.</p>
      <div className="mb-3 rounded-lg border border-gray-100">
        <DataTable rows={active} rowKey={g => g.id} stickyHeader={false}
          defaultSort={{ key: 'staff_name', dir: 'asc' }} emptyLabel="لا يوجد مديرو فروع بعد."
          columns={[
            { key: 'staff_name', label: 'الموظف', width: 200, cellClass: 'font-medium' },
            { key: 'branch', label: 'الفرع', width: 150 },
            { key: 'granted_at', label: 'منذ', width: 140, render: v => fmtTime(v) },
            { key: 'granted_by', label: 'بواسطة', width: 150 },
            { key: 'id', label: '', width: 120, sortable: false, render: (id) => (
              <button data-tour="stock-audit-main-access-revoke" onClick={() => revoke.mutate(id)}
                className="px-2 py-0.5 rounded-md border border-gray-300 text-xs text-gray-600">سحب الصلاحية</button>) },
          ]} />
      </div>
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="ابحث عن موظف بالاسم أو الكود…"
        className="border border-gray-200 rounded-md px-2 py-1 text-sm bg-white w-full max-w-sm" />
      <div className="mt-2 space-y-1">
        {(cands.data || []).map(c => (
          <div key={c.id} className="flex items-center gap-2 text-sm">
            <span>{c.name}</span><span className="text-xs text-gray-500">{c.branch}</span>
            {c.granted ? <span className="ms-auto text-xs text-emerald-700">✔ لديه الصلاحية</span>
              : <button onClick={() => grant.mutate(c.id)} className="ms-auto px-2 py-0.5 rounded-md bg-primary text-white text-xs font-bold">منح الصلاحية</button>}
          </div>
        ))}
      </div>
      {msg && <div className="mt-2 text-xs text-red-600">{msg}</div>}
    </div>
  )
}

function SettingsTab({ access }) {
  const { data, isLoading, error } = useQuery({ queryKey: ['stock-audit', 'rules'], queryFn: () => stockAuditApi.rules().then(r => r.data) })
  if (isLoading) return <div className="py-12 text-center text-gray-400">جاري التحميل…</div>
  if (error) return <div className="py-12 text-center text-red-600">{errText(error)}</div>
  return (
    <div className="space-y-3" data-tour="stock-audit-main-thresholds">
      {!data.can_edit && <div className="text-xs text-gray-500">عرض فقط — تعديل الحدود للمدير والجودة.</div>}
      {data.rules.map(r => <RuleCard key={`${r.code}-${r.updated_at}`} rule={r} branches={data.branches} canEdit={data.can_edit} />)}
      {access.can_manage_access && <AccessPanel />}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function StockAuditPage() {
  const [tab, setTab] = useState('summary')
  useHelpTab(tab)
  const [rule, setRule] = useState({})
  const [filters, setFilters] = useState({ from: daysAgo(29), to: isoDay(new Date()), branch: '',
                                           status: 'open,escalated', severity: '', channel: '', q: '', sort: '-date' })
  const me = useQuery({ queryKey: ['stock-audit', 'me'], queryFn: () => stockAuditApi.me().then(r => r.data) })
  const rulesMeta = useMemo(() => Object.fromEntries((me.data?.rules || []).map(r => [r.code, r])), [me.data])
  const summaryBranches = useQuery({
    queryKey: ['stock-audit', 'branches'], enabled: !!me.data?.can_view,
    queryFn: () => stockAuditApi.rules().then(r => r.data.branches) })
  const branches = (summaryBranches.data || []).filter(b => !me.data?.branches || me.data.branches.includes(b.branchcode))

  if (me.isLoading) return <div className="p-6 text-gray-400" dir="rtl">جاري التحميل…</div>
  if (!me.data?.can_view) {
    return (
      <div className="p-6 max-w-3xl mx-auto text-center" dir="rtl">
        <div className="text-4xl mb-2">🔒</div>
        <p className="text-gray-600">هذه الشاشة للإدارة والجودة ومديري الفروع المسموح لهم فقط.</p>
      </div>
    )
  }
  const access = me.data
  const f = { ...filters, setSort: s => setFilters(p => ({ ...p, sort: s })) }
  const openRule = (code, branchcode) => {
    const group = Object.entries(access.groups).find(([, codes]) => codes.includes(code))?.[0] || 'sales'
    setRule(r => ({ ...r, [group]: code }))
    if (branchcode) setFilters(p => ({ ...p, branch: branchcode }))
    setTab(group)
  }
  const groupRules = g => (rule[g] ? [rule[g]] : access.groups[g])

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" dir="rtl">
      <div className="flex flex-wrap items-start gap-3 mb-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">تدقيق حركات المخزون</h1>
          <p className="text-sm text-gray-500 mt-1">فحوص ثابتة على حركات SOFTECH: الأسعار والتكلفة، المستندات المكررة، التسويات، النفاد المتكرر، المرتجعات، ومواعيد الإدخال.
            {access.branch_manager && <span className="text-primary"> · فروعك فقط</span>}</p>
        </div>
        {access.can_refresh && <div className="ms-auto"><RefreshButton /></div>}
      </div>
      <DataFreshnessBar domains={['stock_audit']} />
      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-4" data-tour="stock-audit-main-tabs">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab !== 'settings' && <Filters f={filters} setF={setFilters} branches={branches} channels={me.data?.channels}
                                                showStatus={tab !== 'summary'} />}
      {tab === 'summary' && <SummaryTab f={filters} onOpenRule={openRule} />}
      {access.groups[tab] && (
        <>
          {tab === 'timing' && (
            <div className="mb-3 text-xs text-gray-600 bg-white border border-gray-200 rounded-lg px-3 py-2" data-tour="stock-audit-main-hours">
              مواعيد عمل كل فرع تُضبط من <Link to="/settings" className="text-primary font-bold hover:underline">الإعدادات ← الفروع</Link>. الفروع التي تعمل 24 ساعة أو بلا مواعيد لا تُفحص.
            </div>
          )}
          {tab === 'availability' && (
            <div className="mb-3 text-xs text-gray-600 bg-white border border-gray-200 rounded-lg px-3 py-2" data-tour="stock-audit-main-overstock">
              الفائض والتغطية الزائدة (الفحص 7) في <Link to="/inventory" className="text-primary font-bold hover:underline">لوحة المخزون ← تبويب «📦 الفائض»</Link>.
            </div>
          )}
          <RuleChips codes={access.groups[tab]} value={rule[tab] || ''} meta={rulesMeta}
            onChange={c => setRule(r => ({ ...r, [tab]: c }))} />
          <FindingsGrid key={tab} f={f} rules={groupRules(tab)} access={access} />
          {tab === 'adjustments' && <UserRanking f={filters} />}
        </>
      )}
      {tab === 'settings' && <SettingsTab access={access} />}
    </div>
  )
}
