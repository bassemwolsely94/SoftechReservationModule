/**
 * CashOptimizationPage — تحسين الكاش والمخزون (docs/architecture/22)
 *
 * The cash & inventory action layer. Tab 1 (built): 📈 ذروة الطلب — demand-spike
 * over-purchase (the Jutoxib pattern). A STRONG spike is auto-flagged; a human
 * confirms "unsustained burst" to make it eligible for the review-gated order cap
 * (which only cuts المطلوب when activated for the run). WATCH spikes are monitor-only.
 * Tabs 2–3 (راكد / فائض) land with the dead-stock & overstock detectors.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { purchasingApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'

const egp = (n) => (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const invalidate = (qc) => ['spike-candidates', 'spike-summary'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))
const onErr = (e) => window.alert(e?.response?.data?.detail || e?.message || 'تعذّر تنفيذ الإجراء.')

function useSort(initKey = 'ratio', initDir = 'desc') {
  const [key, setKey] = useState(initKey); const [dir, setDir] = useState(initDir)
  const toggle = (k) => { if (k === key) setDir(d => d === 'asc' ? 'desc' : 'asc'); else { setKey(k); setDir('desc') } }
  return { key, dir, toggle }
}
const applySort = (rows, sort, acc) => {
  if (!sort.key || !acc[sort.key]) return rows
  const f = acc[sort.key]
  const out = [...rows].sort((a, b) => {
    const x = f(a), y = f(b)
    if (typeof x === 'number' && typeof y === 'number') return x - y
    return String(x ?? '').localeCompare(String(y ?? ''), 'ar')
  })
  return sort.dir === 'asc' ? out : out.reverse()
}
function Th({ label, k, sort }) {
  const on = sort.key === k
  return (
    <th onClick={() => sort.toggle(k)} className="px-3 py-2 font-semibold cursor-pointer select-none whitespace-nowrap hover:text-brand-600">
      {label}<span className={on ? 'text-brand-600' : 'text-gray-300'}>{on ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅'}</span>
    </th>
  )
}
function Stat({ label, value, tone = 'text-gray-800' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

function SpikeTab() {
  const qc = useQueryClient()
  const [tier, setTier] = useState(''); const [med, setMed] = useState(''); const [q, setQ] = useState('')
  const sort = useSort('ratio', 'desc')
  const params = { ...(tier ? { tier } : {}), ...(med ? { med } : {}), ...(q.trim() ? { q: q.trim() } : {}) }
  const { data: summary } = useQuery({ queryKey: ['spike-summary'], queryFn: () => purchasingApi.spikeSummary().then(r => r.data) })
  const { data: medTypes } = useQuery({ queryKey: ['spike-medtypes'], queryFn: () => purchasingApi.spikeMedTypes().then(r => r.data.med_types) })
  const { data, isLoading } = useQuery({ queryKey: ['spike-candidates', params], queryFn: () => purchasingApi.spikeCandidates(params).then(r => r.data) })
  const confirm = useMutation({ mutationFn: (id) => purchasingApi.spikeConfirm(id), onSuccess: () => invalidate(qc), onError: onErr })
  const unconfirm = useMutation({ mutationFn: (id) => purchasingApi.spikeUnconfirm(id), onSuccess: () => invalidate(qc), onError: onErr })
  const acc = {
    code: r => r.code, name: r => r.name, ratio: r => r.ratio, recent: r => r.recent,
    stock: r => r.stock, order: r => r.order_qty, avoided: r => r.avoided_value,
  }
  const rows = applySort(data?.items || [], sort, acc)
  return (
    <div>
      <p className="text-sm text-gray-500 mb-3">
        قفزة طلب حديثة قد لا تدوم (نُشتري بكثرة لملاحقتها ثم يركد المخزون). التقليل <b>مراجَع بشريًا</b>: أكِّد الذروة القوية فقط لتصبح قابلة للتقليل،
        ويُطبَّق التقليل على شيت النواقص فقط عند تفعيله في تشغيل المحرك.
        {summary && <span className={`mr-2 px-2 py-0.5 rounded-full text-xs ${summary.cap_active ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>
          {summary.cap_active ? 'التقليل مُفعَّل' : 'التقليل غير مُفعَّل (رصد فقط)'}</span>}
      </p>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4" data-tour="purchasing-cash-kpis">
        <Stat label="📈 مكتشفة" value={summary?.flagged ?? '—'} tone="text-orange-600" />
        <Stat label="قوية (قابلة للتقليل)" value={summary?.strong ?? '—'} tone="text-red-600" />
        <Stat label="للمراقبة" value={summary?.watch ?? '—'} tone="text-amber-600" />
        <Stat label="✓ مؤكَّدة" value={summary?.confirmed ?? '—'} tone="text-emerald-700" />
        <Stat label="توفير الطلب المؤكَّد" value={`${egp(data?.confirmed_avoided_value)} ج`} tone="text-emerald-700" />
      </div>
      <div className="flex flex-wrap items-center gap-2 mb-3" data-tour="purchasing-cash-filters">
        {[['', 'الكل'], ['strong', 'قوية'], ['watch', 'مراقبة']].map(([v, l]) => (
          <button key={v} onClick={() => setTier(v)} className={`px-3 py-1.5 text-sm rounded-lg border ${tier === v ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>{l}</button>
        ))}
        <select value={med} onChange={e => setMed(e.target.value)} className="border rounded-lg px-3 py-2 text-sm">
          <option value="">كل التصنيفات</option>
          {(medTypes || []).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالكود/الاسم…" className="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]" />
      </div>
      {isLoading ? <p className="text-gray-400 py-10 text-center">جارٍ التحميل…</p>
        : !rows.length ? <p className="text-gray-400 py-10 text-center">لا توجد ذروات</p>
          : (
            <div className="overflow-x-auto bg-white rounded-xl border border-gray-200" data-tour="purchasing-cash-table">
              <table className="w-full text-sm text-right">
                <thead className="bg-gray-50 text-gray-600 border-b">
                  <tr>
                    <th className="px-3 py-2 font-semibold">الدرجة</th>
                    <Th label="الكود" k="code" sort={sort} /><Th label="الصنف" k="name" sort={sort} />
                    <Th label="المضاعف" k="ratio" sort={sort} /><Th label="المعدل الحديث/شهر" k="recent" sort={sort} />
                    <th className="px-3 py-2 font-semibold">السابق/شهر</th>
                    <Th label="الرصيد" k="stock" sort={sort} /><Th label="المطلوب" k="order" sort={sort} />
                    <th className="px-3 py-2 font-semibold">بعد التقليل</th>
                    <Th label="توفير محتمل" k="avoided" sort={sort} />
                    <th className="px-3 py-2 font-semibold">إجراء</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {rows.map(r => (
                    <tr key={r.item_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 whitespace-nowrap">
                        {r.tier === 'strong'
                          ? <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700">قوية</span>
                          : <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">مراقبة</span>}
                        {r.confirmed && <span className="mr-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">مؤكَّد</span>}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-gray-500">{r.code}</td>
                      <td className="px-3 py-2">{r.name}{r.abc && <span className="mr-1 text-xs text-gray-400">[{r.abc}]</span>}</td>
                      <td className="px-3 py-2 tabular-nums font-semibold text-orange-700">{r.ratio >= 999 ? 'جديد' : `${r.ratio}×`}</td>
                      <td className="px-3 py-2 tabular-nums">{egp(r.recent)}</td>
                      <td className="px-3 py-2 tabular-nums text-gray-500">{r.prior}</td>
                      <td className="px-3 py-2 tabular-nums">{egp(r.stock)}</td>
                      <td className="px-3 py-2 tabular-nums">{egp(r.order_qty)}</td>
                      <td className="px-3 py-2 tabular-nums text-emerald-700">{r.confirmed ? egp(r.capped_qty) : '—'}</td>
                      <td className="px-3 py-2 tabular-nums text-gray-500">{r.confirmed ? `${egp(r.avoided_value)} ج` : '—'}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {r.tier !== 'strong'
                          ? <span className="text-xs text-gray-400">مراقبة فقط</span>
                          : r.confirmed
                            ? <button onClick={() => unconfirm.mutate(r.item_id)} className="px-2 py-1 text-xs text-gray-600 border border-gray-300 rounded hover:bg-gray-100">إلغاء التأكيد</button>
                            : <button onClick={() => confirm.mutate(r.item_id)} data-tour="purchasing-cash-confirm" className="px-2 py-1 text-xs text-red-700 border border-red-200 rounded hover:bg-red-50">تأكيد (طبّق التقليل)</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
    </div>
  )
}

export default function CashOptimizationPage() {
  const [tab, setTab] = useState('spike')
  useHelpTab(tab)
  return (
    <div dir="rtl" className="p-4 max-w-[1400px] mx-auto">
      <h1 className="text-xl font-bold text-gray-800 mb-1">💰 تحسين الكاش والمخزون</h1>
      <p className="text-sm text-gray-500 mb-4">رصد وتحرير الكاش المجمّد ومنع الشراء الزائد — تُظهر النتائج على شيت النواقص كتنبيهات.</p>
      <div className="flex gap-4 border-b mb-4" data-tour="purchasing-cash-tabs">
        {[['spike', '📈 ذروة الطلب'], ['dead', '🧊 مخزون راكد'], ['overstock', '📦 فائض']].map(([k, l]) => (
          <button key={k} onClick={() => k === 'spike' && setTab(k)} disabled={k !== 'spike'}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 ${tab === k ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-400'} ${k !== 'spike' ? 'cursor-not-allowed' : ''}`}>
            {l}{k !== 'spike' && <span className="text-xs"> (قريبًا)</span>}
          </button>
        ))}
      </div>
      {tab === 'spike' && <SpikeTab />}
    </div>
  )
}
