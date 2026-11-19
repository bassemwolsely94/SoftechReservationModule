/**
 * CoverTiersTab — /cash-optimization «🎯 التغطية حسب الفئة» (C25 / P-34, read-only).
 *
 * The server (apps/purchasing/cover_tiers.py) splits each branch's items by sales value (A = top 80%, B = next 15%,
 * C = the rest), compares today's months of cover with each tier's target (SystemSettings, default 1.5 / 1 / 0.5)
 * and prices the gap at cost. It then shows how much of that cash fits at 75 / 100 / 125% of last month's purchases,
 * funding A first. Nothing is ordered or written anywhere: the buyer decides.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { purchasingApi } from '../../api/client'
import DataFreshnessBar from '../../components/DataFreshnessBar'
import useServerSort from '../../hooks/useServerSort'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import BranchMultiSelect from '../../components/BranchMultiSelect'

const egp = (n) => (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const mo = (n) => (n == null ? '—' : Number(n).toFixed(2))
const errOf = (e, d) => e?.response?.data?.detail || d
const TIERS = ['A', 'B', 'C']
const TIER_TONE = { A: 'bg-emerald-50 text-emerald-700', B: 'bg-sky-50 text-sky-700', C: 'bg-gray-100 text-gray-600' }
const LINE_SORT = ['itemcode', 'name', 'branch_name', 'tier', 'rate', 'sales_value', 'stock', 'transit', 'cover_months',
  'target_months', 'need_qty', 'cost', 'stock_value', 'need_value', 'excess_value']
const branchValue = (row, key) => (key === 'branch_name' ? row.branch_name : row.tiers?.[key]?.need_value ?? row.total?.[key])

export default function CoverTiersTab() {
  const [branch, setBranch] = useState([])
  const [tier, setTier] = useState('')
  const [needOnly, setNeedOnly] = useState(true)
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('')
  const scope = { branch: branch.join(',') || undefined }
  const filters = { ...scope, tier: tier || undefined, need: needOnly ? 1 : undefined, q: q.trim() || undefined }
  const params = { ...filters, ...(ordering ? { ordering } : {}), page }
  useEffect(() => { setPage(1) }, [branch, tier, needOnly, q])

  const summary = useQuery({ queryKey: ['cover-tiers', 'summary', scope],
                             queryFn: () => purchasingApi.coverTiersSummary(scope).then(r => r.data) })
  const lines = useQuery({ queryKey: ['cover-tiers', 'lines', params], placeholderData: prev => prev,
                           queryFn: () => purchasingApi.coverTiersLines(params).then(r => r.data) })
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: LINE_SORT })
  const s = summary.data
  const { sorted: branchRows, headerProps: branchHeader } = useSortableRows(s?.branches, {
    defaultSort: { key: 'A', dir: 'desc', type: 'number' }, getValue: branchValue,
  })
  const exportX = () => purchasingApi.coverTiersExport(filters).then(res => {
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a'); a.href = url; a.download = 'cover_tiers.xlsx'
    document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
  })

  if (summary.isError) return <p className="text-sm text-red-600 py-6">{errOf(summary.error, 'تعذّر تحميل التقرير')}</p>
  const rows = lines.data?.lines || []
  return (
    <div className="space-y-3">
      <DataFreshnessBar domains={['sales', 'stock', 'catalog', 'purchases']} />
      <p className="text-sm text-gray-500">
        كل فرع: الأصناف مقسّمة حسب قيمة البيع — <b>أ</b> = أعلى {s?.settings?.cut_a ?? 80}%،
        <b> ب</b> = حتى {s?.settings?.cut_b ?? 95}%، <b>ج</b> = الباقي. التغطية = الرصيد ÷ المعدل الشهري، والكاش المطلوب = ما ينقص
        للوصول للهدف بسعر التكلفة. <b>للاسترشاد فقط</b> — لا يُنشئ طلب شراء ولا يكتب في SOFTECH.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        {s?.run ? <span>تشغيل المحرك #{s.run.id} · بتاريخ {s.run.calc_date || String(s.run.finished_at || '').slice(0, 10)}</span>
          : <span>{s?.detail || 'جارٍ التحميل…'}</span>}
        <span className="flex-1" />
        <BranchMultiSelect className="w-48 text-xs" valueKey="code" selected={branch} onChange={setBranch} />
        <button data-tour="purchasing-cash-cover-export" onClick={exportX}
                className="px-3 py-1 border rounded-lg bg-white hover:bg-gray-50">⬇️ تصدير Excel</button>
      </div>

      <div data-tour="purchasing-cash-cover-tiers" className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {TIERS.map(t => {
          const a = s?.tiers?.[t]
          const short = a && a.cover_months != null && a.cover_months < a.target_months
          return (
            <button key={t} onClick={() => setTier(x => (x === t ? '' : t))}
                    className={`text-right rounded-xl border p-3 ${tier === t ? 'border-brand-600 ring-1 ring-brand-600' : 'border-gray-200 bg-white'}`}>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span className={`px-2 py-0.5 rounded-full font-bold ${TIER_TONE[t]}`}>{t}</span>{a?.label}
              </div>
              <div className="mt-1 text-sm">
                التغطية <b className={short ? 'text-red-600' : 'text-emerald-700'}>{mo(a?.cover_months)}</b> شهر
                <span className="text-gray-400"> / الهدف {mo(a?.target_months)}</span>
              </div>
              <div className="text-lg font-bold">{egp(a?.need_value)} ج <span className="text-xs font-normal text-gray-500">كاش مطلوب</span></div>
              <div className="text-xs text-gray-400">
                {a?.lines ?? 0} سطر · رصيد {egp(a?.stock_value)} ج · فوق الهدف {egp(a?.excess_value)} ج · رصيد صفر {a?.at_zero ?? 0}
                {a?.no_cost_needing ? ` · بلا تكلفة ${a.no_cost_needing}` : ''}
              </div>
            </button>
          )
        })}
      </div>

      <div data-tour="purchasing-cash-cover-budget" className="bg-white rounded-xl border border-gray-200 p-3">
        {s?.budget ? (
          <>
            <div className="text-sm font-semibold mb-2">
              كم يكفي من الكاش؟ — مشتريات {s.budget.purchases.month_label}: {egp(s.budget.purchases.value)} ج
              <span className="text-xs font-normal text-gray-500"> (فاتورة شراء ناقص المرتجع، موردين فعليين) · التمويل بالترتيب أ ثم ب ثم ج</span>
            </div>
            <table className="w-full text-sm text-right">
              <thead className="text-xs text-gray-500"><tr>
                <th className="px-2 py-1">الميزانية</th>
                {TIERS.map(t => <th key={t} className="px-2 py-1">يغطي {t} (من {egp(s.tiers[t].need_value)})</th>)}
                <th className="px-2 py-1">الإجمالي المموَّل</th><th className="px-2 py-1">ينقص</th><th className="px-2 py-1">يتبقى</th>
              </tr></thead>
              <tbody>
                {s.budget.levels.map(l => (
                  <tr key={l.pct} className="border-t">
                    <td className="px-2 py-1 tabular-nums"><b>{l.pct}%</b> = {egp(l.budget)} ج</td>
                    {TIERS.map(t => <td key={t} className="px-2 py-1 tabular-nums">{egp(l.funded[t])}</td>)}
                    <td className="px-2 py-1 tabular-nums font-semibold">{egp(l.funded_total)}</td>
                    <td className={`px-2 py-1 tabular-nums ${l.short > 0 ? 'text-red-600' : 'text-gray-400'}`}>{egp(l.short)}</td>
                    <td className="px-2 py-1 tabular-nums text-gray-500">{egp(l.left)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : <p className="text-xs text-gray-500">{s?.budget_note || 'مقارنة الميزانية غير متاحة.'}</p>}
      </div>

      {branchRows.length > 0 && (
        <div data-tour="purchasing-cash-cover-branches" className="overflow-x-auto bg-white rounded-xl border border-gray-200">
          <table className="w-full text-sm text-right">
            <thead className="bg-gray-50 text-xs text-gray-500"><tr>
              <SortTh {...branchHeader('branch_name')} className="px-3 py-2">الفرع</SortTh>
              {TIERS.map(t => <SortTh key={t} {...branchHeader(t, 'number')} className="px-3 py-2">كاش {t}</SortTh>)}
              {TIERS.map(t => <th key={`c${t}`} className="px-3 py-2">تغطية {t}</th>)}
              <SortTh {...branchHeader('excess_value', 'number')} className="px-3 py-2">فوق الهدف</SortTh>
            </tr></thead>
            <tbody>
              {branchRows.map(b => (
                <tr key={b.branch_code} className="border-t">
                  <td className="px-3 py-1.5">{b.branch_code} · {b.branch_name}</td>
                  {TIERS.map(t => <td key={t} className="px-3 py-1.5 tabular-nums">{egp(b.tiers[t].need_value)}</td>)}
                  {TIERS.map(t => <td key={`c${t}`} className="px-3 py-1.5 tabular-nums text-gray-500">{mo(b.tiers[t].cover_months)}</td>)}
                  <td className="px-3 py-1.5 tabular-nums text-gray-500">{egp(b.total.excess_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {[['', 'كل الفئات'], ...TIERS.map(t => [t, `فئة ${t}`])].map(([v, l]) => (
          <button key={v} onClick={() => setTier(v)}
                  className={`px-3 py-1 text-xs rounded-lg border ${tier === v ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>{l}</button>
        ))}
        <label className="flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" checked={needOnly} onChange={e => setNeedOnly(e.target.checked)} /> المطلوب فقط
        </label>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالصنف أو الكود" className="border rounded px-2 py-1" />
        <span className="flex-1" />
        <span className="text-xs text-gray-500">{lines.data?.count ?? 0} سطر</span>
      </div>

      <div data-tour="purchasing-cash-cover-lines" className="overflow-x-auto bg-white rounded-xl border border-gray-200">
        <table className="w-full text-sm text-right">
          <thead className="bg-gray-50 text-xs text-gray-500"><tr>
            <SortTh {...headerProps('itemcode')} className="px-2 py-2">الكود</SortTh>
            <SortTh {...headerProps('name')} className="px-2 py-2">الصنف</SortTh>
            <SortTh {...headerProps('branch_name')} className="px-2 py-2">الفرع</SortTh>
            <SortTh {...headerProps('tier')} className="px-2 py-2">الفئة</SortTh>
            <SortTh {...headerProps('rate', 'number')} className="px-2 py-2">المعدل/شهر</SortTh>
            <SortTh {...headerProps('stock', 'number')} className="px-2 py-2">الرصيد</SortTh>
            <SortTh {...headerProps('transit', 'number')} className="px-2 py-2">بالطريق</SortTh>
            <SortTh {...headerProps('cover_months', 'number')} className="px-2 py-2">التغطية</SortTh>
            <SortTh {...headerProps('target_months', 'number')} className="px-2 py-2">الهدف</SortTh>
            <SortTh {...headerProps('need_qty', 'number')} className="px-2 py-2">المطلوب</SortTh>
            <SortTh {...headerProps('cost', 'number')} className="px-2 py-2">التكلفة</SortTh>
            <SortTh {...headerProps('need_value', 'number')} className="px-2 py-2">الكاش</SortTh>
            <SortTh {...headerProps('excess_value', 'number')} className="px-2 py-2">فوق الهدف</SortTh>
          </tr></thead>
          <tbody>
            {lines.isLoading ? <tr><td colSpan={13} className="py-8 text-center text-gray-400">جارٍ التحميل…</td></tr>
              : !rows.length ? <tr><td colSpan={13} className="py-8 text-center text-gray-400">لا توجد أسطر</td></tr>
                : rows.map(l => (
                  <tr key={`${l.item_id}-${l.branch_code}`} className="border-t">
                    <td className="px-2 py-1 tabular-nums text-gray-500">{l.itemcode}</td>
                    <td className="px-2 py-1">{l.name}</td>
                    <td className="px-2 py-1 text-xs">{l.branch_code} · {l.branch_name}</td>
                    <td className="px-2 py-1"><span className={`px-2 py-0.5 rounded-full text-xs font-bold ${TIER_TONE[l.tier]}`}>{l.tier}</span></td>
                    <td className="px-2 py-1 tabular-nums">{l.rate.toFixed(2)}</td>
                    <td className={`px-2 py-1 tabular-nums ${l.at_zero ? 'text-red-600 font-semibold' : ''}`}>{l.stock}</td>
                    <td className="px-2 py-1 tabular-nums text-gray-500">{l.transit || ''}</td>
                    <td className="px-2 py-1 tabular-nums">{mo(l.cover_months)}</td>
                    <td className="px-2 py-1 tabular-nums text-gray-500">{mo(l.target_months)}</td>
                    <td className="px-2 py-1 tabular-nums font-semibold">{l.need_qty || ''}</td>
                    <td className="px-2 py-1 tabular-nums text-gray-500">{l.no_cost ? <span className="text-amber-600">بلا تكلفة</span> : egp(l.cost)}</td>
                    <td className="px-2 py-1 tabular-nums">{egp(l.need_value)}</td>
                    <td className="px-2 py-1 tabular-nums text-gray-500">{egp(l.excess_value)}</td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
      {(lines.data?.pages || 1) > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-2 py-1 border rounded disabled:opacity-40">السابق</button>
          <span>{lines.data.page} / {lines.data.pages}</span>
          <button disabled={page >= lines.data.pages} onClick={() => setPage(p => p + 1)} className="px-2 py-1 border rounded disabled:opacity-40">التالي</button>
        </div>
      )}
    </div>
  )
}
