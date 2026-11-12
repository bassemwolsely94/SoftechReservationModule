/**
 * PhantomSalesPage — مبيعات وهمية (phantom substitution)
 *
 * Contract patients sell prescribed drugs back; the item is bought from internal
 * buy-back accounts + re-sold on the contract channel, never sourced from real
 * distributors. Auto-detected (phantom_ratio = buyback/sold ≥ 50%); this screen
 * lets a human confirm / exclude / reset the flag. The recommended order-% and
 * genuine need drive the demand sheet (engine reduction is separate/gated).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { purchasingApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import useSortableRows from '../hooks/useSortableRows'
import SortTh from '../components/SortTh'
import MultiSelectFilter from '../components/MultiSelectFilter'

const pct = (x) => `${Math.round((x ?? 0) * 100)}%`
const egp = (n) => (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const invalidate = (qc) => ['phantom-candidates', 'phantom-excluded', 'phantom-summary']
  .forEach(k => qc.invalidateQueries({ queryKey: [k] }))
const onErr = (e) => window.alert(e?.response?.data?.detail || e?.message || 'تعذّر تنفيذ الإجراء.')

// derived sort values (value = the reduction value); default = biggest reduction first
const phantomVal = (r, k) => (k === 'value' ? r.buyback_qty * r.cost : r[k])
const PHANTOM_DEFAULT = { key: 'value', dir: 'desc', type: 'number' }

function Stat({ label, value, tone = 'text-gray-800' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

function Toolbar({ med, setMed, q, setQ, medTypes }) {
  return (
    <div className="flex flex-wrap items-center gap-2 mb-3" data-tour="shortage-phantom-toolbar">
      <MultiSelectFilter className="w-[190px]" showCode={false} allLabel="كل التصنيفات" menuClassName="min-w-[240px]"
        options={medTypes.map(([code, name]) => ({ code, name }))} selected={med} onChange={setMed} />
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالكود/الاسم…"
        className="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]" />
    </div>
  )
}

function Table({ rows, tab, qc }) {
  const confirm = useMutation({ mutationFn: (id) => purchasingApi.phantomConfirm({ item_id: id }), onSuccess: () => invalidate(qc), onError: onErr })
  const exclude = useMutation({
    mutationFn: (id) => purchasingApi.phantomExclude({ item_id: id, note: window.prompt('سبب الاستبعاد (اختياري):') || '' }),
    onSuccess: () => invalidate(qc), onError: onErr,
  })
  const reset = useMutation({ mutationFn: (id) => purchasingApi.phantomReset(id), onSuccess: () => invalidate(qc), onError: onErr })
  const { sorted, headerProps: hp } = useSortableRows(rows, { defaultSort: PHANTOM_DEFAULT, getValue: phantomVal })
  if (!rows.length) return <p className="text-gray-400 py-10 text-center">لا توجد أصناف</p>
  return (
    <div className="overflow-x-auto bg-white rounded-xl border border-gray-200" data-tour="shortage-phantom-table">
      <table className="w-full text-sm text-right">
        <thead className="bg-gray-50 text-gray-600 border-b">
          <tr>
            <SortTh {...hp('code', 'text')} className="px-3 py-2 font-semibold whitespace-nowrap">الكود</SortTh><SortTh {...hp('name', 'text')} className="px-3 py-2 font-semibold whitespace-nowrap">الصنف</SortTh>
            <SortTh {...hp('phantom_ratio', 'number')} className="px-3 py-2 font-semibold whitespace-nowrap">نسبة الوهمية</SortTh><SortTh {...hp('order_pct', 'number')} className="px-3 py-2 font-semibold whitespace-nowrap">النسبة الموصى بطلبها</SortTh>
            <SortTh {...hp('sold_qty', 'number')} className="px-3 py-2 font-semibold whitespace-nowrap">المبيعات</SortTh><SortTh {...hp('buyback_qty', 'number')} className="px-3 py-2 font-semibold whitespace-nowrap">إعادة الشراء</SortTh>
            <SortTh {...hp('genuine_need', 'number')} className="px-3 py-2 font-semibold whitespace-nowrap">الطلب الحقيقي</SortTh><SortTh {...hp('value', 'number')} className="px-3 py-2 font-semibold whitespace-nowrap">قيمة التخفيض</SortTh>
            <th className="px-3 py-2 font-semibold">الحالة</th><th className="px-3 py-2 font-semibold">إجراء</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {sorted.map(r => (
            <tr key={r.item_id} className="hover:bg-gray-50">
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{r.code}</td>
              <td className="px-3 py-2">
                {r.tier === 'watch'
                  ? <span className="ml-1 text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 whitespace-nowrap">مراقبة</span>
                  : <span className="ml-1 text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 whitespace-nowrap">شديد</span>}
                {r.name}
                {r.in_shortage && <span className="mr-1 text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 whitespace-nowrap">📉 نقص سوق</span>}</td>
              <td className="px-3 py-2 tabular-nums font-semibold text-violet-700">{pct(r.phantom_ratio)}</td>
              <td className="px-3 py-2 tabular-nums font-semibold text-emerald-700">{pct(r.order_pct)}</td>
              <td className="px-3 py-2 tabular-nums">{egp(r.sold_qty)}</td>
              <td className="px-3 py-2 tabular-nums">{egp(r.buyback_qty)}</td>
              <td className="px-3 py-2 tabular-nums">{egp(r.genuine_need)}</td>
              <td className="px-3 py-2 tabular-nums text-gray-500">{egp(r.buyback_qty * r.cost)}</td>
              <td className="px-3 py-2 whitespace-nowrap">
                {r.override === 'confirmed' && <span className="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">مؤكَّد</span>}
                {r.override === 'excluded' && <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">مستبعد</span>}
                {!r.override && <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">تلقائي</span>}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {tab === 'flagged' ? (
                  <div data-tour="shortage-phantom-row-actions" className="flex gap-1">
                    {r.override !== 'confirmed' &&
                      <button data-tour="shortage-phantom-confirm" onClick={() => confirm.mutate(r.item_id)} className="px-2 py-1 text-xs text-violet-700 border border-violet-200 rounded hover:bg-violet-50">تأكيد</button>}
                    <button data-tour="shortage-phantom-exclude" onClick={() => exclude.mutate(r.item_id)} className="px-2 py-1 text-xs text-gray-600 border border-gray-300 rounded hover:bg-gray-100">ليست وهمية</button>
                  </div>
                ) : (
                  <button data-tour="shortage-phantom-reset" onClick={() => reset.mutate(r.item_id)} className="px-2 py-1 text-xs text-brand-600 border border-brand-200 rounded hover:bg-brand-50">إرجاع للتلقائي</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function PhantomSalesPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('flagged')
  useHelpTab(tab)
  const [med, setMed] = useState([]); const [q, setQ] = useState('')   // med: multi-select codes (none = all)
  const params = { ...(med.length ? { med: med.join(',') } : {}), ...(q.trim() ? { q: q.trim() } : {}) }
  const { data: summary } = useQuery({ queryKey: ['phantom-summary'], queryFn: () => purchasingApi.phantomSummary().then(r => r.data) })
  const { data: medTypes } = useQuery({ queryKey: ['phantom-medtypes'], queryFn: () => purchasingApi.phantomMedTypes().then(r => r.data.med_types) })
  const { data, isLoading } = useQuery({
    queryKey: [tab === 'flagged' ? 'phantom-candidates' : 'phantom-excluded', params],
    queryFn: () => (tab === 'flagged' ? purchasingApi.phantomCandidates(params) : purchasingApi.phantomExcluded(params)).then(r => r.data),
  })
  return (
    <div dir="rtl" className="p-4 max-w-[1400px] mx-auto">
      <div data-tour="shortage-phantom-header" className="mb-4">
        <h1 className="text-xl font-bold text-gray-800">🩹 مبيعات وهمية</h1>
        <p className="text-sm text-gray-500">أصناف يُعاد شراء معظم مبيعاتها من العميل/المريض (تعاقد) لا من الموردين — تُقلَّل كميتها في شيت النواقص.
          الحد: ≥ {pct(summary?.threshold)} من المبيعات خلال {summary?.window_months} شهر.</p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4" data-tour="shortage-phantom-stats">
        <Stat label="🩹 مُكتشفة" value={summary?.flagged ?? '—'} tone="text-violet-700" />
        <Stat label="⏳ بانتظار المراجعة" value={summary?.pending_review ?? '—'} tone="text-amber-600" />
        <Stat label="✓ مؤكَّدة" value={summary?.confirmed ?? '—'} tone="text-violet-700" />
        <Stat label="مستبعدة (ليست وهمية)" value={summary?.excluded ?? '—'} tone="text-gray-600" />
        <Stat label="تخفيض الطلب (تقديري)" value={`${egp(data?.total_order_reduction_value)} ج`} tone="text-emerald-700" />
      </div>
      <div className="flex gap-4 border-b mb-4" data-tour="shortage-phantom-tabs">
        {[['flagged', `المُكتشفة (${summary?.flagged ?? 0})`], ['excluded', `المستبعدة (${summary?.excluded ?? 0})`]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 ${tab === k ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>{l}</button>
        ))}
      </div>
      <Toolbar med={med} setMed={setMed} q={q} setQ={setQ} medTypes={medTypes || []} />
      {isLoading ? <p className="text-gray-400 py-10 text-center">جارٍ التحميل…</p>
        : <Table rows={data?.items || []} tab={tab} qc={qc} />}
    </div>
  )
}
