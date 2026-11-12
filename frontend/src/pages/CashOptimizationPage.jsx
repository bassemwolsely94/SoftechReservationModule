/**
 * CashOptimizationPage — تحسين الكاش والمخزون (docs/architecture/22)
 *
 * The cash & inventory action layer. Tab 1 (built): 📈 ذروة الطلب — demand-spike
 * over-purchase (the Jutoxib pattern). A STRONG spike is auto-flagged; a human
 * confirms "unsustained burst" to make it eligible for the review-gated order cap
 * (which only cuts المطلوب when activated for the run). WATCH spikes are monitor-only.
 * Tab 2: 🧊 مخزون راكد (P-27 part A, read-only — cash/DeadStockTab.jsx). Tab 3 (فائض) is still to come.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { purchasingApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import DeadStockTab from './cash/DeadStockTab'   // P-27 part A
import useSortableRows from '../hooks/useSortableRows'
import SortTh from '../components/SortTh'
import MultiSelectFilter from '../components/MultiSelectFilter'

const egp = (n) => (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const invalidate = (qc) => ['spike-candidates', 'spike-summary'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))
const onErr = (e) => window.alert(e?.response?.data?.detail || e?.message || 'تعذّر تنفيذ الإجراء.')

const spikeValue = (r, k) => (k === 'order' ? r.order_qty : k === 'tierRank' ? (r.tier === 'strong' ? 1 : 0) : r[k])
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
  // med is a multi-select ([] = all, sent as one comma list); tier stays a one-of switch
  const [tier, setTier] = useState(''); const [med, setMed] = useState([]); const [q, setQ] = useState('')
  const params = { ...(tier ? { tier } : {}), ...(med.length ? { med: med.join(',') } : {}), ...(q.trim() ? { q: q.trim() } : {}) }
  const { data: summary } = useQuery({ queryKey: ['spike-summary'], queryFn: () => purchasingApi.spikeSummary().then(r => r.data) })
  const { data: medTypes } = useQuery({ queryKey: ['spike-medtypes'], queryFn: () => purchasingApi.spikeMedTypes().then(r => r.data.med_types) })
  const { data, isLoading } = useQuery({ queryKey: ['spike-candidates', params], queryFn: () => purchasingApi.spikeCandidates(params).then(r => r.data) })
  const confirm = useMutation({ mutationFn: (id) => purchasingApi.spikeConfirm(id), onSuccess: () => invalidate(qc), onError: onErr })
  const unconfirm = useMutation({ mutationFn: (id) => purchasingApi.spikeUnconfirm(id), onSuccess: () => invalidate(qc), onError: onErr })
  const { sorted: rows, headerProps } = useSortableRows(data?.items, {
    defaultSort: { key: 'ratio', dir: 'desc', type: 'number' }, getValue: spikeValue,
  })
  return (
    <div>
      <p className="text-sm text-gray-500 mb-3">
        قفزة طلب حديثة قد لا تدوم (نُشتري بكثرة لملاحقتها ثم يركد المخزون). التقليل <b>مراجَع بشريًا</b>: أكِّد الذروة القوية فقط لتصبح قابلة للتقليل،
        ويُطبَّق التقليل على شيت النواقص فقط عند تفعيله في تشغيل المحرك.
        {summary && <span data-tour="purchasing-cash-cap-status" className={`mr-2 px-2 py-0.5 rounded-full text-xs ${summary.cap_active ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>
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
        <MultiSelectFilter className="w-48" options={(medTypes || []).map(([v, l]) => ({ code: v, name: l }))}
                           selected={med} onChange={setMed} allLabel="كل التصنيفات" showCode={false} />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالكود/الاسم…" className="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]" />
      </div>
      {isLoading ? <p className="text-gray-400 py-10 text-center">جارٍ التحميل…</p>
        : !rows.length ? <p className="text-gray-400 py-10 text-center">لا توجد ذروات</p>
          : (
            <div className="overflow-x-auto bg-white rounded-xl border border-gray-200" data-tour="purchasing-cash-table">
              <table className="w-full text-sm text-right">
                <thead className="bg-gray-50 text-gray-600 border-b">
                  <tr>
                    <SortTh {...headerProps('tierRank', 'number')} className="px-3 py-2 font-semibold">الدرجة</SortTh>
                    <SortTh {...headerProps('code')} className="px-3 py-2 font-semibold">الكود</SortTh>
                    <SortTh {...headerProps('name')} className="px-3 py-2 font-semibold">الصنف</SortTh>
                    <SortTh {...headerProps('ratio', 'number')} className="px-3 py-2 font-semibold">المضاعف</SortTh>
                    <SortTh {...headerProps('recent', 'number')} className="px-3 py-2 font-semibold">المعدل الحديث/شهر</SortTh>
                    <SortTh {...headerProps('prior', 'number')} className="px-3 py-2 font-semibold">السابق/شهر</SortTh>
                    <SortTh {...headerProps('stock', 'number')} className="px-3 py-2 font-semibold">الرصيد</SortTh>
                    <SortTh {...headerProps('order', 'number')} className="px-3 py-2 font-semibold">المطلوب</SortTh>
                    <SortTh {...headerProps('capped_qty', 'number')} className="px-3 py-2 font-semibold">بعد التقليل</SortTh>
                    <SortTh {...headerProps('avoided_value', 'number')} className="px-3 py-2 font-semibold">توفير محتمل</SortTh>
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
                            ? <button data-tour="purchasing-cash-unconfirm" onClick={() => unconfirm.mutate(r.item_id)} className="px-2 py-1 text-xs text-gray-600 border border-gray-300 rounded hover:bg-gray-100">إلغاء التأكيد</button>
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
          <button key={k} onClick={() => k !== 'overstock' && setTab(k)} disabled={k === 'overstock'}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 ${tab === k ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-400'} ${k === 'overstock' ? 'cursor-not-allowed' : ''}`}>
            {l}{k === 'overstock' && <span className="text-xs"> (قريبًا)</span>}
          </button>
        ))}
      </div>
      {tab === 'spike' && <SpikeTab />}
      {tab === 'dead' && <DeadStockTab />}
    </div>
  )
}
