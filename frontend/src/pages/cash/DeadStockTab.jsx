/**
 * DeadStockTab — /cash-optimization «🧊 مخزون راكد» (P-27 part A, read-only).
 *
 * The server builds the list from the latest demand-engine run: no local sale for 6 months AND the oldest unit on
 * hand arrived 6+ months ago (HQ: only when no branch sells the item). Three lanes — move to a branch that sells it,
 * return to the supplier (advisory), stop (موقوف). Buyers tick lines and exclude them (with a reason) or set a
 * strategic hold; both are audited server-side. Nothing here creates a transfer or writes to SOFTECH.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { purchasingApi } from '../../api/client'
import DataFreshnessBar from '../../components/DataFreshnessBar'
import ProgressBar from '../../components/ProgressBar'
import useGridKeyboard, { ACTIVE_ROW } from '../../hooks/useGridKeyboard'
import useServerSort from '../../hooks/useServerSort'
import SortTh from '../../components/SortTh'
import MultiSelectFilter from '../../components/MultiSelectFilter'
import BranchMultiSelect from '../../components/BranchMultiSelect'

const egp = (n) => (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const errOf = (e, d) => e?.response?.data?.detail || d
const LANES = [['', 'الكل'], ['move', 'يُباع بفرع آخر'], ['return', 'مرتجع للمورد'], ['stop', 'إيقاف (موقوف)']]
const LOC_OPTIONS = [{ code: 'hq_only', name: 'الرئيسي فقط' }, { code: 'branches_only', name: 'فروع فقط' },
                     { code: 'both', name: 'الرئيسي والفروع' }]
const SORT_KEYS = ['name', 'branch_name', 'qty', 'value', 'last_sale_date', 'oldest_arrival_date', 'network_rate', 'lane_label', 'cause_label']
const LANE_TONE = { move: 'bg-emerald-50 text-emerald-700', return: 'bg-indigo-50 text-indigo-700', stop: 'bg-gray-100 text-gray-700' }

export default function DeadStockTab() {
  const qc = useQueryClient()
  const [lane, setLane] = useState('')
  const [location, setLocation] = useState([])   // multi-select ([] = all)
  const [branch, setBranch] = useState([])       // SOFTECH codes, multi-select ([] = all)
  const [q, setQ] = useState('')
  const [showDecided, setShowDecided] = useState(false)
  const [ticked, setTicked] = useState(new Set())
  const [open, setOpen] = useState(null)
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState('')
  const [since, setSince] = useState(null)
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('')   // server-side sort of ALL lines (rank order until a header is clicked)
  const filters = { lane: lane || undefined, location: location.join(',') || undefined, branch: branch.join(',') || undefined,
                    q: q || undefined, show_decided: showDecided ? 1 : undefined }
  const params = { ...filters, ...(ordering ? { ordering } : {}), page }
  useEffect(() => { setPage(1); setTicked(new Set()) }, [lane, location, branch, q, showDecided])
  const reload = () => qc.invalidateQueries({ queryKey: ['dead-stock'] })
  const summary = useQuery({ queryKey: ['dead-stock', 'summary'], queryFn: () => purchasingApi.deadStockSummary().then(r => r.data) })
  const lines = useQuery({ queryKey: ['dead-stock', 'lines', params], placeholderData: prev => prev,
                           queryFn: () => purchasingApi.deadStockLines(params).then(r => r.data) })
  const status = useQuery({
    queryKey: ['dead-stock-recompute'], enabled: since != null, refetchInterval: 3000,
    queryFn: () => purchasingApi.deadStockRecomputeStatus().then(r => r.data),
  })
  useEffect(() => {
    if (since != null && status.data && !status.data.running) { setSince(null); setMsg('اكتملت إعادة الحساب.'); reload() }
  }, [status.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: SORT_KEYS })
  const rows = lines.data?.lines || []
  const toggle = (id) => setTicked(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const kb = useGridKeyboard({
    rows, getKey: r => r.id, onToggle: r => toggle(r.id), onOpen: r => setOpen(o => (o === r.id ? null : r.id)),
    onConfirm: r => setOpen(o => (o === r.id ? null : r.id)), onSelectAll: () => setTicked(new Set(rows.map(r => r.id))),
  })

  const decide = useMutation({
    mutationFn: async () => {
      for (const r of rows.filter(x => ticked.has(x.id))) {
        await purchasingApi.deadStockDecide({ item_id: r.item_id, branch_code: r.branch_code, decision: 'exclude', reason })
      }
    },
    onSuccess: () => { setMsg(`استُبعد ${ticked.size} سطر.`); setTicked(new Set()); reload() },
    onError: (e) => setMsg(errOf(e, 'تعذّر الحفظ')),
  })
  const hold = useMutation({
    mutationFn: async () => {
      const ids = [...new Set(rows.filter(x => ticked.has(x.id)).map(x => x.item_id))]
      for (const id of ids) await purchasingApi.deadStockHold({ item_id: id, hold: true })
      return ids.length
    },
    onSuccess: (n) => { setMsg(`احتفاظ استراتيجي لـ ${n} صنف — يُستبعد من الحساب القادم.`); setTicked(new Set()); reload() },
    onError: (e) => setMsg(errOf(e, 'تعذّر الحفظ')),
  })
  const recompute = () => purchasingApi.deadStockRecompute()
    .then(r => { setMsg(r.data.detail); setSince(Date.now()) })
    .catch(e => setMsg(errOf(e, 'تعذّر بدء إعادة الحساب')))
  const exportX = () => purchasingApi.deadStockExport(filters).then(res => {
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a'); a.href = url; a.download = 'dead_stock.xlsx'
    document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
  })

  const s = summary.data
  return (
    <div className="space-y-3">
      <DataFreshnessBar domains={['stock', 'sales', 'stock_audit', 'purchases']} />
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        {s?.snapshot ? <span>تشغيل المحرك #{s.snapshot.run_id} · حُسبت {String(s.snapshot.computed_at).slice(0, 16).replace('T', ' ')}
          · راكد = بلا بيع {s.snapshot.settings?.months} أشهر وأقدم وارد ≥ {s.snapshot.settings?.months} أشهر</span>
          : <span>{s?.detail}</span>}
        <span className="flex-1" />
        <button onClick={recompute} disabled={since != null} className="px-3 py-1 border rounded-lg bg-white hover:bg-gray-50 disabled:opacity-50">⟳ إعادة الحساب</button>
        <button data-tour="purchasing-cash-dead-export" onClick={exportX} className="px-3 py-1 border rounded-lg bg-white hover:bg-gray-50">⬇️ تصدير Excel</button>
      </div>
      {since != null && <ProgressBar label="إعادة حساب المخزون الراكد" since={since} />}
      {msg && since == null && <div className="text-sm bg-white border rounded-lg px-3 py-2">{msg}</div>}

      <div data-tour="purchasing-cash-dead-lanes" className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {LANES.map(([k, l]) => {
          const v = k ? s?.lanes?.[k] : s?.total
          return (
            <button key={k} onClick={() => setLane(k)}
                    className={`text-right rounded-xl border p-3 ${lane === k ? 'border-brand-600 ring-1 ring-brand-600' : 'border-gray-200 bg-white'}`}>
              <div className="text-xs text-gray-500">{l}</div>
              <div className="text-lg font-bold">{egp(v?.value)} ج</div>
              <div className="text-xs text-gray-400">{v?.count ?? 0} سطر</div>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <MultiSelectFilter className="w-40 text-xs" options={LOC_OPTIONS} selected={location} onChange={setLocation}
                           allLabel="كل المواقع" showCode={false} />
        <BranchMultiSelect className="w-44 text-xs" valueKey="code" selected={branch} onChange={setBranch}
                           branches={(summary.data?.branches || []).map(b => ({ id: b.code, softech_branch_id: b.code, name_ar: b.name }))} />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالصنف أو الكود" className="border rounded px-2 py-1" />
        <label className="flex items-center gap-1 text-xs text-gray-600"><input type="checkbox" checked={showDecided} onChange={e => setShowDecided(e.target.checked)} /> إظهار المستبعد</label>
        <span className="flex-1" />
        <div data-tour="purchasing-cash-dead-actions" className="flex items-center gap-2">
          <span className="text-xs text-gray-500">{ticked.size} محدد</span>
          <select value={reason} onChange={e => setReason(e.target.value)} className="border rounded px-2 py-1 text-xs">
            <option value="">سبب الاستبعاد…</option>
            {(s?.reasons || []).map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <button disabled={!ticked.size || !reason || decide.isPending} onClick={() => decide.mutate()}
                  className="px-2 py-1 text-xs border rounded disabled:opacity-40">استبعاد</button>
          <button disabled={!ticked.size || hold.isPending} onClick={() => hold.mutate()}
                  className="px-2 py-1 text-xs border rounded disabled:opacity-40">احتفاظ استراتيجي</button>
        </div>
      </div>

      <div data-tour="purchasing-cash-dead-grid" {...kb.containerProps} className="bg-white rounded-xl border border-gray-200 overflow-x-auto outline-none">
        {lines.isLoading ? <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div> : (
          <table className="w-full text-xs whitespace-nowrap">
            <thead className="bg-gray-50 text-gray-600"><tr>
              <th className="px-2 py-2" />
              <SortTh {...headerProps('name')} className="text-right px-2 py-2">الصنف</SortTh>
              <SortTh {...headerProps('branch_name')} className="text-right px-2 py-2">الفرع</SortTh>
              <SortTh {...headerProps('qty', 'number')} className="text-right px-2 py-2">الكمية</SortTh>
              <SortTh {...headerProps('value', 'number')} className="text-right px-2 py-2">القيمة</SortTh>
              <SortTh {...headerProps('last_sale_date', 'date')} className="text-right px-2 py-2">آخر بيع</SortTh>
              <SortTh {...headerProps('oldest_arrival_date', 'date')} className="text-right px-2 py-2">أقدم وارد</SortTh>
              <SortTh {...headerProps('network_rate', 'number')} className="text-right px-2 py-2">معدل الشبكة</SortTh>
              <SortTh {...headerProps('lane_label')} className="text-right px-2 py-2">المسار</SortTh>
              <SortTh {...headerProps('cause_label')} className="text-right px-2 py-2">السبب</SortTh>
              <th className="text-right px-2 py-2">التفاصيل</th>
            </tr></thead>
            <tbody>
              {rows.map(r => {
                const rp = kb.rowProps(r)
                return [
                  <tr key={r.id} {...rp} className={`border-t ${rp.className || ''} ${kb.active === r.id ? ACTIVE_ROW : ''} ${r.decision ? 'text-gray-400' : ''}`}>
                    <td className="px-2 py-1.5"><input type="checkbox" checked={ticked.has(r.id)} onChange={() => toggle(r.id)} /></td>
                    <td className="px-2 py-1.5">{r.itemcode} · {r.name}{r.strategic_hold && <span className="text-[10px] text-indigo-600"> احتفاظ</span>}</td>
                    <td className="px-2 py-1.5">{r.branch_name}</td>
                    <td className="px-2 py-1.5">{r.qty}</td>
                    <td className="px-2 py-1.5">{egp(r.value)}</td>
                    <td className="px-2 py-1.5">{r.last_sale_date || 'لا بيع في سنة'}</td>
                    <td className="px-2 py-1.5">{r.oldest_arrival_date || 'أقدم من سنة'}</td>
                    <td className="px-2 py-1.5">{r.network_rate ? r.network_rate.toFixed(1) : '—'}</td>
                    <td className="px-2 py-1.5"><span className={`px-1.5 py-0.5 rounded ${LANE_TONE[r.lane]}`}>{r.lane_label}</span>
                      <span className="text-[10px] text-gray-400"> {r.location_label}</span></td>
                    <td className="px-2 py-1.5">{r.cause_label}</td>
                    <td className="px-2 py-1.5">
                      {r.lane === 'move' && r.targets.map(t => `${t.branch_name}: ${t.qty}`).join('، ')}
                      {r.lane === 'return' && <span>{r.supplier_code} ({r.supplier_class}){r.window_label ? ` · ${r.window_label}` : ''}</span>}
                      {r.flags?.fridge && <span className="mr-1 text-sky-700">ثلاجة — لا يُنقل</span>}
                      {r.flags?.below_threshold && <span className="mr-1 text-amber-700">أقل من حد القيمة</span>}
                      {r.flags?.conflict && <span className="mr-1 text-rose-700">متعارض ({r.flags.conflict})</span>}
                      {r.soonest_expiry && <span className="mr-1 text-orange-700">ينتهي {r.soonest_expiry}</span>}
                      {r.decision && <span className="mr-1">مستبعد: {r.decision.reason} حتى {r.decision.until}</span>}
                    </td>
                  </tr>,
                  open === r.id && (
                    <tr key={`${r.id}-o`} className="bg-gray-50"><td colSpan={11} className="px-6 py-2 text-xs text-gray-600">
                      {r.targets.length ? r.targets.map(t => <div key={t.branch}>{t.branch_name}: {t.qty} عبوة · مساحة {t.room} · يبيع {t.rate.toFixed(1)}/شهر</div>)
                        : 'لا فروع مستهدفة.'}
                      {r.lane === 'move' && <div>قيمة النقل: {egp(r.move_value)} ج</div>}
                    </td></tr>
                  ),
                ]
              })}
            </tbody>
          </table>
        )}
        {!lines.isLoading && !rows.length && <div className="text-center py-10 text-gray-400 text-sm">لا سطور.</div>}
      </div>
      {(lines.data?.pages || 1) > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1 border rounded disabled:opacity-40">السابق</button>
          <span className="text-gray-600">صفحة {lines.data.page} من {lines.data.pages} · {lines.data.count} سطر</span>
          <button disabled={page >= lines.data.pages} onClick={() => setPage(p => p + 1)} className="px-3 py-1 border rounded disabled:opacity-40">التالي</button>
        </div>
      )}
      <p className="text-xs text-gray-400">للاسترشاد فقط — لا يُنشأ تحويل أو مرتجع من هنا. النقل يدخل «التوزيعة» لاحقًا بعد مراجعة أول قائمة.</p>
    </div>
  )
}
