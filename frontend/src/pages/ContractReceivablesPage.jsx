/**
 * ContractReceivablesPage — /finance/receivables «مستحقات التعاقدات» (P-41).
 *
 * Who owes us on contract, since when: open sales invoices of the tracked contract accounts (customer side of the
 * A/P–A/R mirror), aged, with the expected date = end of the invoice month + agreed days. Where SOFTECH links under
 * 70 % of a contract's sales to receipts, collection days are an estimate paying the oldest invoices first. Insurance
 * co-pay accounts are grouped by company. Company-level finance — the server checks the grant and all-branch scope;
 * nothing here writes to SOFTECH.
 */
import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { financeApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import useBranchLabels from '../hooks/useBranchLabels'

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 }))
const BUCKETS = ['0-30', '31-60', '61-90', '91-180', '>180']
const errOf = (e, d) => e?.response?.data?.detail || d

function Kpi({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function DaysInput({ contract, onSaved }) {
  const [v, setV] = useState(contract.agreed_days ?? '')
  const [err, setErr] = useState('')
  const save = useMutation({
    mutationFn: () => financeApi.receivablesTerms({ personcode: contract.personcode, agreed_days: v === '' ? null : Number(v) }),
    onSuccess: () => { setErr(''); onSaved() },
    onError: (e) => setErr(errOf(e, 'تعذّر الحفظ')),
  })
  const dirty = String(v) !== String(contract.agreed_days ?? '')
  return (
    <span className="inline-flex items-center gap-1">
      <input type="number" min="0" max="365" step="1" value={v} placeholder="—"
             onChange={e => setV(e.target.value)}
             onKeyDown={e => { if (e.key === 'Enter' && dirty) save.mutate() }}
             onBlur={() => dirty && save.mutate()}
             className="w-16 border rounded px-1 py-0.5 text-xs" title="أيام السداد المتفق عليها — تُحسب من نهاية شهر الفاتورة" />
      {save.isPending && <span className="text-xs text-gray-400">…</span>}
      {err && <span className="text-xs text-red-600">{err}</span>}
    </span>
  )
}

function Invoices({ personcode }) {
  const bl = useBranchLabels()
  const { data, isLoading } = useQuery({
    queryKey: ['receivables', 'invoices', personcode],
    queryFn: () => financeApi.receivablesInvoices(personcode).then(r => r.data),
  })
  if (isLoading) return <div className="p-3 text-xs text-gray-400">جارٍ التحميل…</div>
  return (
    <div className="grid md:grid-cols-3 gap-3 p-3 bg-gray-50">
      <div className="md:col-span-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-gray-500"><tr>
            <th className="text-right p-1">الفاتورة</th><th className="text-right p-1">التاريخ</th>
            <th className="text-right p-1">المفتوح</th><th className="text-right p-1">العمر</th>
            <th className="text-right p-1">الاستحقاق المتوقع</th><th className="text-right p-1">الأساس</th>
          </tr></thead>
          <tbody>
            {(data?.invoices || []).map(i => (
              <tr key={i.id} className={`border-t ${i.overdue ? 'text-red-700' : ''}`}>
                <td className="p-1">{bl(i.branchcode)} · #{i.docnumber}</td><td className="p-1">{i.docdate}</td>
                <td className="p-1">{fmt(i.open)}</td><td className="p-1">{i.age} يوم</td>
                <td className="p-1">{i.expected_date || '—'}{i.overdue ? ' ⚠' : ''}</td>
                <td className="p-1 text-gray-500">{i.expected_basis_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.invoices?.length && <div className="text-xs text-gray-400 p-2">لا فواتير مفتوحة.</div>}
      </div>
      <div>
        <div className="text-xs font-semibold text-gray-600 mb-1">آخر المقبوضات</div>
        {(data?.receipts || []).map((r, k) => (
          <div key={k} className="text-xs flex justify-between border-t py-1">
            <span>{r.date}{r.cheqtype === '20' ? ' · رد' : ''}</span><span>{fmt(r.amount)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ContractReceivablesPage() {
  const qc = useQueryClient()
  const [open, setOpen] = useState({})
  const [msg, setMsg] = useState('')
  const { data, isLoading, error } = useQuery({
    queryKey: ['receivables', 'summary'],
    queryFn: () => financeApi.receivablesSummary().then(r => r.data),
  })
  const reload = () => qc.invalidateQueries({ queryKey: ['receivables'] })
  const refresh = () => financeApi.receivablesRefresh()
    .then(r => setMsg(r.data.detail))
    .catch(e => setMsg(errOf(e, 'تعذّر بدء التحديث')))
  const exportX = () => financeApi.receivablesExport().then(res => {
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a'); a.href = url; a.download = 'contract_receivables.xlsx'
    document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
  })

  if (error) return <div className="p-6 text-sm text-red-600">{errOf(error, 'تعذّر تحميل المستحقات')}</div>
  const t = data?.totals || {}
  const toggle = (k) => setOpen(o => ({ ...o, [k]: !o[k] }))

  return (
    <div className="p-6 space-y-4" dir="rtl">
      <div data-tour="finance-receivables-freshness">
        <DataFreshnessBar domains={['ar_contracts']} onRefresh={refresh} />
      </div>
      {msg && <div className="text-sm bg-white border rounded-lg px-3 py-2">{msg}</div>}
      <div data-tour="finance-receivables-kpis" className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="صافي المستحق" value={`${fmt(t.net_receivable)} ج`} sub={`مفتوح ${fmt(t.open)} − على الحساب ${fmt(t.on_account)} − مرتجعات ${fmt(t.open_returns)}`} />
        <Kpi label="متأخر عن الاستحقاق" value={`${fmt(t.overdue)} ج`} tone="text-red-700" sub="حسب الأيام المتفق عليها من نهاية شهر الفاتورة" />
        <Kpi label="متوسط أيام التحصيل" value={t.measured_days ?? '—'} sub="مرجّح بالمبلغ المفتوح" />
        <Kpi label="مقبوضات على الحساب" value={`${fmt(t.on_account)} ج`} sub="غير مربوطة بفواتير في SOFTECH" />
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span className="text-gray-500">«أيام مقاسة»: من ربط SOFTECH لو يغطي {data?.reliable_coverage_pct ?? 70}% من المبيعات، وإلا «تقدير — أقدم فاتورة أولاً».</span>
        <span className="flex-1" />
        <button data-tour="finance-receivables-export" onClick={exportX} className="px-3 py-1.5 border rounded-lg bg-white hover:bg-gray-50">⬇️ تصدير Excel</button>
      </div>

      {isLoading ? <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div> : (
        <div data-tour="finance-receivables-table" className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <th className="text-right px-2 py-2">الجهة / الحساب</th>
                <th className="text-right px-2 py-2">صافي المستحق</th>
                {BUCKETS.map(b => <th key={b} className="text-right px-2 py-2">{b}</th>)}
                <th className="text-right px-2 py-2">المتأخر</th>
                <th className="text-right px-2 py-2">أيام متفق عليها</th>
                <th className="text-right px-2 py-2">أيام مقاسة</th>
                <th className="text-right px-2 py-2">رصيد SOFTECH</th>
                <th className="text-right px-2 py-2">الفرق</th>
              </tr>
            </thead>
            <tbody>
              {(data?.groups || []).map(g => (
                <Fragment key={g.group_name}>
                  <tr className="border-t bg-gray-50/60 cursor-pointer" onClick={() => toggle(`g:${g.group_name}`)}>
                    <td className="px-2 py-2 font-semibold">{open[`g:${g.group_name}`] ? '▾' : '▸'} {g.group_name} <span className="text-xs text-gray-400">({g.contracts.length})</span></td>
                    <td className="px-2 py-2 font-semibold">{fmt(g.net_receivable)}</td>
                    {BUCKETS.map(b => <td key={b} className="px-2 py-2">{fmt(g.contracts.reduce((s, c) => s + (c.buckets?.[b] || 0), 0))}</td>)}
                    <td className="px-2 py-2 text-red-700">{fmt(g.overdue)}</td>
                    <td className="px-2 py-2" /><td className="px-2 py-2">{g.measured_days ?? '—'}</td>
                    <td className="px-2 py-2" /><td className="px-2 py-2" />
                  </tr>
                  {open[`g:${g.group_name}`] && g.contracts.map(c => (
                    <Fragment key={c.personcode}>
                      <tr className="border-t">
                        <td className="px-2 py-1.5 pr-6 cursor-pointer" onClick={() => toggle(c.personcode)}>
                          {open[c.personcode] ? '▾' : '▸'} {c.personcode} · {c.name}
                        </td>
                        <td className="px-2 py-1.5">{fmt(c.net_receivable)}</td>
                        {BUCKETS.map(b => <td key={b} className="px-2 py-1.5">{fmt(c.buckets?.[b])}</td>)}
                        <td className="px-2 py-1.5 text-red-700">{fmt(c.overdue)}</td>
                        <td className="px-2 py-1.5"><DaysInput contract={c} onSaved={reload} /></td>
                        <td className="px-2 py-1.5" title={`${c.measured_method_label} · تغطية الربط ${c.link_coverage_pct ?? 0}%`}>
                          {c.measured_days ?? '—'}{c.measured_method === 'fifo' && <span className="text-xs text-amber-700"> تقدير</span>}
                        </td>
                        <td className="px-2 py-1.5">{fmt(c.softech_receivable)}</td>
                        <td className={`px-2 py-1.5 ${Math.abs(c.difference || 0) >= 1 ? 'text-amber-700' : 'text-gray-400'}`}>{fmt(c.difference)}</td>
                      </tr>
                      {open[c.personcode] && <tr><td colSpan={11}><Invoices personcode={c.personcode} /></td></tr>}
                    </Fragment>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
          {!data?.groups?.length && (
            <div className="text-center py-10 text-gray-400 text-sm">لا حسابات تعاقد متابَعة بعد — شغّل <code>seed_contract_terms</code> ثم حدّث.</div>
          )}
        </div>
      )}
    </div>
  )
}
