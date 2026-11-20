/**
 * RiderPayoutsTab.jsx — C22 / P-48 rider payout ledger (/delivery/analytics → 💵 أجور الطيارين).
 *
 * An internal record of what each rider is owed per ride: it pays nothing, writes nothing to SOFTECH
 * or payroll and never touches cash collection. The server owns every number (the rule, the totals,
 * the lock) and every permission; this tab only shows them and sends the user's choices.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi, deliveryApi, exportJobsApi, riderPayoutsApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import useExportJob from '../../hooks/useExportJob'
import ExportJobStatus from '../../components/ExportJobStatus'

const money = v => Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const errText = (e, fallback) => e?.response?.data?.detail || fallback
const thisMonth = () => new Date().toISOString().slice(0, 7)
const today = () => new Date().toISOString().slice(0, 10)
const newRef = () => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `${Date.now()}-${Math.random()}`)
const VEHICLE = { motorcycle: 'دراجة نارية', car: 'سيارة', bicycle: 'دراجة', on_foot: 'سير', van: 'ميكروباص' }

function RuleLine({ rule }) {
  if (!rule) return null
  const minimum = Number(rule.daily_minimum) > 0
    ? `حد أدنى يومي ${money(rule.daily_minimum)} ج.م (${(rule.minimum_vehicles || []).map(v => VEHICLE[v] || v).join('، ')})`
    : 'حد أدنى يومي: متوقف'
  return (
    <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2" data-tour="delivery-payouts-rule">
      <span className="font-semibold">القاعدة:</span> {money(rule.flat_fee)} ج.م لكل توصيلة
      {' · '}{Number(rule.per_km) > 0 ? `${money(rule.per_km)} ج.م لكل كم (لو المسافة معروفة)` : 'بدون أجر للمسافة'}
      {' · '}{minimum}
      <span className="text-gray-400"> — سجل داخلي، لا يصرف فلوس ولا يكتب في SOFTECH</span>
      {rule.fallbacks?.length > 0 && (
        <div className="text-amber-700 mt-1">⚠ بعض أرقام القاعدة غير مضبوطة في الإعدادات — مستخدم الافتراضي الآمن: {rule.fallbacks.join('، ')}</div>
      )}
    </div>
  )
}

function RecordRide({ branches, onDone }) {
  const blank = () => ({ branch: '', driver: '', ride_date: today(), deliveries: 1, distance_km: '', order_refs: '', note: '', client_ref: newRef() })
  const [f, setF] = useState(blank)
  const [msg, setMsg] = useState('')
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const { data: drivers = [] } = useQuery({
    queryKey: ['delivery-drivers', f.branch],
    queryFn: () => deliveryApi.listDrivers({ branch: f.branch || undefined }).then(r => r.data?.results || r.data || []),
    staleTime: 60_000,
  })
  const save = useMutation({
    mutationFn: () => riderPayoutsApi.recordRide({ ...f, distance_km: f.distance_km === '' ? null : f.distance_km }),
    onSuccess: r => { setMsg(`✓ سُجّلت الرحلة — ${money(r.data.amount)} ج.م`); setF(blank()); onDone() },
    onError: e => setMsg(errText(e, 'تعذّر تسجيل الرحلة')),
  })
  const input = 'border border-gray-300 rounded-lg px-2 py-1.5 text-xs'
  return (
    <form className="flex flex-wrap items-end gap-2 bg-white border border-gray-200 rounded-lg p-3" data-tour="delivery-payouts-record"
      onSubmit={e => { e.preventDefault(); save.mutate() }}>
      <label className="text-xs text-gray-500">الفرع
        <select className={`${input} block`} value={f.branch} onChange={e => set('branch', e.target.value)} required>
          <option value="">—</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.softech_branch_id} · {b.name_ar || b.name}</option>)}
        </select>
      </label>
      <label className="text-xs text-gray-500">الطيار
        <select className={`${input} block`} value={f.driver} onChange={e => set('driver', e.target.value)} required>
          <option value="">—</option>
          {drivers.map(d => <option key={d.id} value={d.id}>{d.full_name}</option>)}
        </select>
      </label>
      <label className="text-xs text-gray-500">التاريخ
        <input type="date" className={`${input} block`} value={f.ride_date} max={today()} onChange={e => set('ride_date', e.target.value)} required />
      </label>
      <label className="text-xs text-gray-500">التوصيلات
        <input type="number" min="1" max="50" step="1" className={`${input} block w-20`} value={f.deliveries} onChange={e => set('deliveries', e.target.value)} required />
      </label>
      <label className="text-xs text-gray-500">المسافة كم (اختياري)
        <input type="number" min="0" max="200" step="0.1" className={`${input} block w-24`} value={f.distance_km} onChange={e => set('distance_km', e.target.value)} />
      </label>
      <label className="text-xs text-gray-500 flex-1 min-w-40">أرقام الطلبات
        <input className={`${input} block w-full`} value={f.order_refs} onChange={e => set('order_refs', e.target.value)} placeholder="1201، 1202" />
      </label>
      <button type="submit" disabled={save.isPending} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-xs font-bold disabled:opacity-50">
        {save.isPending ? '…' : '＋ تسجيل رحلة'}</button>
      {msg && <span className="text-xs text-gray-600 w-full">{msg}</span>}
    </form>
  )
}

function ReasonAction({ label, placeholder, onRun, busy, tone = 'brand', dataTour }) {
  const [reason, setReason] = useState('')
  const cls = tone === 'red' ? 'bg-red-600' : tone === 'amber' ? 'bg-amber-600' : 'bg-brand-600'
  return (
    <form className="flex gap-2 items-center" data-tour={dataTour}
      onSubmit={e => { e.preventDefault(); onRun(reason, () => setReason('')) }}>
      <input className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs flex-1 min-w-48" value={reason}
        onChange={e => setReason(e.target.value)} placeholder={placeholder} />
      <button type="submit" disabled={busy || reason.trim().length < 5}
        className={`px-3 py-1.5 rounded-lg text-white text-xs font-bold disabled:opacity-40 ${cls}`}>{label}</button>
    </form>
  )
}

function PeriodDetail({ id, rule, onChanged }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const [adj, setAdj] = useState({ amount: '', reason: '', adj_date: today() })
  const { data: p, isLoading } = useQuery({ queryKey: ['rider-payout-period', id], queryFn: () => riderPayoutsApi.period(id).then(r => r.data) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['rider-payout-period', id] }); onChanged() }
  const act = useMutation({
    mutationFn: ({ fn }) => fn(),
    onSuccess: (_r, { done, ok }) => { setMsg(ok); done?.(); refresh() },
    onError: e => setMsg(errText(e, 'تعذّر تنفيذ العملية')),
  })
  if (isLoading || !p) return <div className="p-4 text-gray-400 text-sm">جاري التحميل…</div>
  const open = !p.is_finalized
  return (
    <div className="bg-gray-50 border-t border-gray-200 p-4 space-y-4 text-xs">
      {msg && <div className="text-gray-700">{msg}</div>}
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <div className="font-bold text-gray-700 mb-1">الأيام</div>
          <table className="w-full bg-white border border-gray-200 rounded">
            <thead className="bg-gray-100"><tr><th className="p-1.5 text-right">اليوم</th><th>رحلات</th><th>توصيلات</th><th>أجر</th><th>استكمال</th></tr></thead>
            <tbody>{p.days.map(d => (
              <tr key={d.date} className="border-t border-gray-100 text-center">
                <td className="p-1.5 text-right font-mono">{d.date}</td><td>{d.rides}</td><td>{d.deliveries}</td>
                <td>{money(d.amount)}</td><td>{Number(d.topup) > 0 ? money(d.topup) : '—'}</td></tr>))}
            </tbody>
          </table>
        </div>
        <div>
          <div className="font-bold text-gray-700 mb-1">إضافات وخصومات (بسبب)</div>
          {p.adjustments.length === 0 && <div className="text-gray-400">لا يوجد</div>}
          {p.adjustments.map(a => (
            <div key={a.id} className={`flex items-center gap-2 py-1 border-b border-gray-100 ${a.is_removed ? 'line-through text-gray-400' : ''}`}>
              <span className="font-mono">{a.adj_date}</span>
              <span className={`font-bold ${Number(a.amount) < 0 ? 'text-red-600' : 'text-green-700'}`}>{money(a.amount)}</span>
              <span className="flex-1">{a.reason}</span>
              {open && !a.is_removed && rule?.can_finalize && (
                <ReasonAction label="حذف" tone="red" placeholder="سبب الحذف" busy={act.isPending}
                  onRun={(reason, done) => act.mutate({ fn: () => riderPayoutsApi.removeAdjustment(a.id, reason), done, ok: '✓ حُذفت' })} />)}
            </div>))}
          {open && rule?.can_finalize && (
            <form className="flex flex-wrap gap-2 mt-2" data-tour="delivery-payouts-adjust"
              onSubmit={e => { e.preventDefault(); act.mutate({ fn: () => riderPayoutsApi.addAdjustment(id, adj), done: () => setAdj({ amount: '', reason: '', adj_date: today() }), ok: '✓ أُضيفت' }) }}>
              <input type="number" step="0.01" className="border border-gray-300 rounded-lg px-2 py-1.5 w-24" placeholder="+40 / -20"
                value={adj.amount} onChange={e => setAdj(x => ({ ...x, amount: e.target.value }))} required />
              <input type="date" className="border border-gray-300 rounded-lg px-2 py-1.5" value={adj.adj_date}
                onChange={e => setAdj(x => ({ ...x, adj_date: e.target.value }))} />
              <input className="border border-gray-300 rounded-lg px-2 py-1.5 flex-1 min-w-40" placeholder="السبب (مثلاً: تحويل لفرع 140)"
                value={adj.reason} onChange={e => setAdj(x => ({ ...x, reason: e.target.value }))} required />
              <button type="submit" disabled={act.isPending || adj.reason.trim().length < 5}
                className="px-3 py-1.5 rounded-lg bg-brand-600 text-white font-bold disabled:opacity-40">إضافة</button>
            </form>)}
        </div>
      </div>

      <div>
        <div className="font-bold text-gray-700 mb-1">الرحلات</div>
        <table className="w-full bg-white border border-gray-200 rounded">
          <thead className="bg-gray-100"><tr>
            <th className="p-1.5 text-right">التاريخ</th><th>المصدر</th><th>الطلبات</th><th>توصيلات</th><th>كم</th><th>ثابت</th><th>مسافة</th><th>الأجر</th><th></th></tr></thead>
          <tbody>{p.rides.map(r => (
            <tr key={r.id} className={`border-t border-gray-100 text-center ${r.is_void ? 'line-through text-gray-400' : ''}`}>
              <td className="p-1.5 text-right font-mono">{r.ride_date}</td><td>{r.source_label}</td>
              <td className="max-w-48 truncate" title={r.order_refs}>{r.order_refs || '—'}</td><td>{r.deliveries}</td>
              <td>{r.distance_km ?? '—'}</td><td>{money(r.flat_amount)}</td><td>{money(r.distance_amount)}</td>
              <td className="font-bold">{money(r.amount)}</td>
              <td>{open && !r.is_void && rule?.can_build && (
                <ReasonAction label="إلغاء" tone="red" placeholder="سبب الإلغاء" busy={act.isPending}
                  onRun={(reason, done) => act.mutate({ fn: () => riderPayoutsApi.voidRide(r.id, reason), done, ok: '✓ أُلغيت الرحلة' })} />)}</td>
            </tr>))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap gap-4 items-center">
        {open && rule?.can_finalize && (
          <ReasonAction label="✓ اعتماد الفترة" placeholder="ملاحظة الاعتماد (مثلاً: راجعت مع الكاشير)" busy={act.isPending}
            dataTour="delivery-payouts-finalize"
            onRun={(reason, done) => act.mutate({ fn: () => riderPayoutsApi.finalize(id, reason), done, ok: '✓ اعتُمدت الفترة وتقفلت' })} />)}
        {!open && (
          <span className="text-green-700 font-bold">🔒 مُعتمدة {p.finalized_by_name && `— ${p.finalized_by_name}`} {p.finalize_reason && `(${p.finalize_reason})`}</span>)}
        {!open && rule?.can_unlock && (
          <ReasonAction label="فتح الاعتماد" tone="amber" placeholder="سبب فتح الاعتماد" busy={act.isPending}
            onRun={(reason, done) => act.mutate({ fn: () => riderPayoutsApi.unlock(id, reason), done, ok: '✓ فُتح الاعتماد' })} />)}
      </div>

      {p.audit.length > 0 && (
        <details>
          <summary className="cursor-pointer font-bold text-gray-700">سجل التدقيق ({p.audit.length})</summary>
          <ul className="mt-1 space-y-0.5">{p.audit.map(ev => (
            <li key={ev.id} className="text-gray-600">
              <span className="font-mono">{ev.created_at.slice(0, 16).replace('T', ' ')}</span> · {ev.action_label} · {ev.actor_name}
              {ev.reason && ` — ${ev.reason}`}
              {ev.before?.total_payout !== undefined && ev.after?.total_payout !== undefined && ` (${money(ev.before.total_payout)} → ${money(ev.after.total_payout)})`}
            </li>))}
          </ul>
        </details>)}
    </div>
  )
}

export default function RiderPayoutsTab({ branchId }) {
  const qc = useQueryClient()
  const [month, setMonth] = useState(thisMonth())
  const [openId, setOpenId] = useState(null)
  const [msg, setMsg] = useState('')
  const params = useMemo(() => ({ month, branch: branchId || undefined }), [month, branchId])

  const { data: rule } = useQuery({ queryKey: ['rider-payout-rule'], queryFn: () => riderPayoutsApi.rule().then(r => r.data) })
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'], queryFn: () => branchesApi.list().then(r => r.data?.results || r.data || []), staleTime: 300_000,
  })
  const { data, isLoading } = useQuery({
    queryKey: ['rider-payout-periods', params], queryFn: () => riderPayoutsApi.periods(params).then(r => r.data),
  })
  const rows = data?.results || []
  const sort = useSortableRows(rows, { getValue: (r, k) => (['total_payout', 'rides_amount', 'minimum_topup', 'adjustments_total', 'distance_km'].includes(k) ? Number(r[k]) : r[k]) })
  const reload = () => qc.invalidateQueries({ queryKey: ['rider-payout-periods'] })

  const build = useMutation({
    mutationFn: () => {
      const [y, m] = month.split('-').map(Number)
      const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
      const to = last > today() ? today() : last
      return riderPayoutsApi.build({ date_from: `${month}-01`, date_to: to, branch: branchId || undefined })
    },
    onSuccess: r => {
      const d = r.data
      setMsg(`✓ أُضيفت ${d.created} رحلة من طلبات التوصيل${d.held_finalized ? ` · ${d.held_finalized} طلب في فترات مُعتمدة لم يُضف` : ''}`)
      reload()
    },
    onError: e => setMsg(errText(e, 'تعذّر بناء السجل')),
  })
  const exp = useExportJob({
    storageKey: 'export-job:rider-payouts',
    start: () => exportJobsApi.start('/delivery/payouts/periods/export/', params),
    fileName: () => `rider-payouts-${month}.xlsx`,
  })
  const totals = rows.reduce((t, r) => t + Number(r.total_payout || 0), 0)
  const th = 'px-3 py-2 font-semibold text-gray-600'

  return (
    <div className="space-y-3">
      <RuleLine rule={rule} />
      <div className="flex flex-wrap items-center gap-2">
        <input type="month" value={month} onChange={e => { setMonth(e.target.value); setOpenId(null) }}
          className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs" data-tour="delivery-payouts-month" />
        {rule?.can_build && (
          <button onClick={() => build.mutate()} disabled={build.isPending} data-tour="delivery-payouts-build"
            className="px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-xs font-bold disabled:opacity-50">
            {build.isPending ? '…' : '↻ بناء من طلبات التوصيل'}</button>)}
        {rule?.can_export && (
          <button onClick={() => exp.run()} disabled={exp.busy}
            className="px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-xs font-bold disabled:opacity-50">
            {exp.busy ? '… جارٍ تجهيز الملف' : '⬇️ تصدير Excel'}</button>)}
        <span className="ms-auto text-xs text-gray-500">{rows.length} فترة · الإجمالي {money(totals)} ج.م</span>
      </div>
      <ExportJobStatus exp={exp} />
      {msg && <div className="text-xs text-gray-700">{msg}</div>}
      {rule?.can_record && <RecordRide branches={branches} onDone={() => { reload(); qc.invalidateQueries({ queryKey: ['rider-payout-period'] }) }} />}

      {isLoading ? <div className="text-center py-10 text-gray-400 animate-pulse">جاري التحميل…</div>
        : rows.length === 0 ? <div className="text-center py-10 text-gray-400">لا توجد رحلات مسجّلة في هذا الشهر</div>
          : (
            <div className="overflow-x-auto rounded-xl border border-gray-200" data-tour="delivery-payouts-periods">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs"><tr>
                  <SortTh {...sort.headerProps('branch_label', 'text')} className={`${th} text-right`}>الفرع</SortTh>
                  <SortTh {...sort.headerProps('driver_name', 'text')} className={`${th} text-right`}>الطيار</SortTh>
                  <SortTh {...sort.headerProps('days_count', 'number')} className={th}>أيام</SortTh>
                  <SortTh {...sort.headerProps('rides_count', 'number')} className={th}>رحلات</SortTh>
                  <SortTh {...sort.headerProps('deliveries_count', 'number')} className={th}>توصيلات</SortTh>
                  <SortTh {...sort.headerProps('rides_amount', 'number')} className={th}>أجر الرحلات</SortTh>
                  <SortTh {...sort.headerProps('minimum_topup', 'number')} className={th}>استكمال</SortTh>
                  <SortTh {...sort.headerProps('adjustments_total', 'number')} className={th}>إضافات/خصومات</SortTh>
                  <SortTh {...sort.headerProps('total_payout', 'number')} className={th}>الإجمالي</SortTh>
                  <SortTh {...sort.headerProps('is_finalized', 'text')} className={th}>الحالة</SortTh>
                </tr></thead>
                <tbody className="divide-y divide-gray-100">
                  {sort.sorted.map(r => [
                    <tr key={r.id} onClick={() => setOpenId(openId === r.id ? null : r.id)}
                      className={`cursor-pointer hover:bg-gray-50 text-center ${openId === r.id ? 'bg-brand-50' : ''}`}>
                      <td className="px-3 py-2 text-right">{r.branch_label}</td>
                      <td className="px-3 py-2 text-right font-medium">{r.driver_name}</td>
                      <td>{r.days_count}</td><td>{r.rides_count}</td><td>{r.deliveries_count}</td>
                      <td>{money(r.rides_amount)}</td><td>{Number(r.minimum_topup) > 0 ? money(r.minimum_topup) : '—'}</td>
                      <td className={Number(r.adjustments_total) < 0 ? 'text-red-600' : ''}>{Number(r.adjustments_total) ? money(r.adjustments_total) : '—'}</td>
                      <td className="font-bold">{money(r.total_payout)}</td>
                      <td>{r.is_finalized ? '🔒 مُعتمدة' : 'مفتوحة'}</td>
                    </tr>,
                    openId === r.id && (
                      <tr key={`${r.id}-d`}><td colSpan={10} className="p-0">
                        <PeriodDetail id={r.id} rule={rule} onChanged={reload} />
                      </td></tr>),
                  ])}
                </tbody>
              </table>
            </div>)}
    </div>
  )
}
