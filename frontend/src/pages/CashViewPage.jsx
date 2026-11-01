/**
 * CashViewPage — /finance/cash «النقدية ١٣ أسبوع» (P-40).
 *
 * Money expected in and out each week for 13 weeks (Saturday–Friday) and the projected balance in three cases
 * (low / base / high). Lines come from the SOFTECH mirror (supplier cheques and payables, contract collections), from
 * estimates (cash sales run rate, new purchases) and from finance inputs (opening balance, fixed outflows, planned
 * cheques). Memo lines never change the balance. A cell click lists the rows behind it in the side panel. The server
 * builds every number; the "what if" weekly purchase budget is sent with the request and never saved.
 * Company-level finance — the server checks the grant and all-branch scope; nothing writes to SOFTECH.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { financeApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import useBranchLabels from '../hooks/useBranchLabels'
import useHelpTab from '../help/useHelpTab'

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 }))
const errOf = (e, d) => e?.response?.data?.detail || d
const GROUPS = [['in', 'داخل'], ['out', 'خارج'], ['memo', 'للعلم — خارج الرصيد']]
const SOURCE_TONE = { softech_mirror: 'bg-indigo-50 text-indigo-700', finance_input: 'bg-emerald-50 text-emerald-700', estimate: 'bg-amber-50 text-amber-700' }
const ddmm = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`

function Kpi({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function Bars({ weeks, closing }) {
  if (!closing?.base) return null
  const all = [...closing.low, ...closing.high, 0].map(Number)
  const max = Math.max(...all), min = Math.min(...all)
  const span = max - min || 1
  const y = (v) => ((max - Number(v)) / span) * 100
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-3">
      <div className="flex items-stretch gap-1 h-28 relative">
        <div className="absolute inset-x-0 border-t border-dashed border-gray-300" style={{ top: `${y(0)}%` }} />
        {weeks.map((w, i) => (
          <div key={w.start} className="flex-1 relative" title={`${ddmm(w.start)} · متشائم ${fmt(closing.low[i])} · أساسي ${fmt(closing.base[i])} · متفائل ${fmt(closing.high[i])}`}>
            <div className="absolute inset-x-1 rounded bg-gray-200" style={{ top: `${y(closing.high[i])}%`, bottom: `${100 - y(closing.low[i])}%` }} />
            <div className={`absolute inset-x-0 h-0.5 ${Number(closing.base[i]) < 0 ? 'bg-orange-600' : 'bg-brand-600'}`} style={{ top: `${y(closing.base[i])}%` }} />
          </div>
        ))}
      </div>
      <div className="flex gap-1 text-[10px] text-gray-400 mt-1">{weeks.map(w => <div key={w.start} className="flex-1 text-center">{ddmm(w.start)}</div>)}</div>
    </div>
  )
}

function Drill({ cell, budget, onClose }) {
  const bl = useBranchLabels()
  const { data, isLoading } = useQuery({
    queryKey: ['cash-view', 'line', cell.key, cell.week, budget],
    queryFn: () => financeApi.cashViewLine(cell.key, { week: cell.week, purchase_budget_weekly: budget || undefined }).then(r => r.data),
  })
  const rows = data?.rows || []
  return (
    <aside className="bg-white rounded-xl border border-gray-200 p-3 text-xs space-y-2 self-start sticky top-4">
      <div className="flex items-center gap-2">
        <span className="font-semibold">{cell.label} · أسبوع {ddmm(cell.start)}</span>
        <span className="flex-1" />
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label="إغلاق">✕</button>
      </div>
      {isLoading ? <div className="text-gray-400">جارٍ التحميل…</div> : !rows.length ? <div className="text-gray-400">لا تفاصيل.</div> : (
        <div className="max-h-[60vh] overflow-y-auto">
          {rows.map((r, k) => (
            <div key={k} className="border-t py-1 flex justify-between gap-2">
              <span className="text-gray-700">
                {r.supplier || r.name || r.label || r.plan || ''}
                {r.personcode ? <span className="text-gray-400"> · {r.personcode}</span> : null}
                {r.docnumber ? <span className="text-gray-400"> · {r.branchcode ? `${bl(r.branchcode)} ` : ''}#{r.docnumber}</span> : null}
                {r.cheqsno ? <span className="text-gray-400"> · شيك {r.cheqsno}</span> : null}
                {r.week_start ? <span className="text-gray-400">أسبوع {ddmm(r.week_start)}</span> : null}
                {r.date ? <span className="text-gray-400"> · {r.date}</span> : null}
              </span>
              <span className="font-medium">{fmt(r.amount)}</span>
            </div>
          ))}
          {cell.key !== 'cash_sales' && (
            <div className="border-t pt-1 flex justify-between font-semibold"><span>الإجمالي</span><span>{fmt(rows.reduce((s, r) => s + Number(r.amount || 0), 0))}</span></div>
          )}
          {cell.key === 'cash_sales' && <div className="text-gray-400 pt-1">آخر 8 أسابيع — الأساسي متوسطها، المتشائم أقلها، المتفائل أعلاها.</div>}
        </div>
      )}
    </aside>
  )
}

function ViewTab({ budget, setBudget }) {
  const [cell, setCell] = useState(null)
  const [draft, setDraft] = useState(budget ?? '')
  const { data, isLoading, error } = useQuery({
    queryKey: ['cash-view', 'view', budget],
    queryFn: () => financeApi.cashView({ purchase_budget_weekly: budget || undefined }).then(r => r.data),
  })
  if (error) return <div className="p-6 text-sm text-red-600">{errOf(error, 'تعذّر تحميل النقدية')}</div>
  if (isLoading) return <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div>
  const weeks = data.weeks
  const c = data.closing
  const lowest = (arr) => (arr ? arr.reduce((m, v, i) => (Number(v) < Number(arr[m]) ? i : m), 0) : null)
  const lb = lowest(c.base), ll = lowest(c.low)
  const below = c.base ? c.base.filter(v => Number(v) < 0).length : null
  const cov = data.coverage
  const pick = (ln, i) => setCell({ key: ln.key, label: ln.label_ar, week: i, start: weeks[i].start })
  return (
    <div className="space-y-3">
      <div data-tour="finance-cash-kpis" className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="أقل رصيد — أساسي" value={c.base ? fmt(c.base[lb]) : '—'} tone={c.base && Number(c.base[lb]) < 0 ? 'text-orange-600' : 'text-gray-900'}
             sub={c.base ? `أسبوع ${ddmm(weeks[lb].start)}` : 'أدخل الرصيد الافتتاحي'} />
        <Kpi label="أقل رصيد — متشائم" value={c.low ? fmt(c.low[ll]) : '—'} tone={c.low && Number(c.low[ll]) < 0 ? 'text-orange-600' : 'text-gray-900'}
             sub={c.low ? `أسبوع ${ddmm(weeks[ll].start)}` : ''} />
        <Kpi label="أسابيع تحت الصفر" value={below ?? '—'} tone={below ? 'text-orange-600' : 'text-gray-900'} sub="الحالة الأساسية" />
        <Kpi label="تغطية المدخلات" value={data.opening ? `رصيد ${data.opening.as_of}` : 'بلا رصيد'}
             sub={`شروط الموردين ${cov.supplier_terms.coverage_pct ?? 0}% · تعاقدات بأيام ${cov.contracts_with_agreed_days}/${cov.contracts_tracked}`} />
      </div>
      <Bars weeks={weeks} closing={c} />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-1">لو اشترينا أسبوعيًا
          <input type="number" min="0" step="10000" value={draft} placeholder="معدل آخر 13 أسبوع"
                 onChange={e => setDraft(e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter') setBudget(draft === '' ? null : draft) }}
                 onBlur={() => setBudget(draft === '' ? null : draft)}
                 className="w-36 border rounded px-2 py-1 text-xs" /> ج
        </label>
        {budget != null && <button onClick={() => { setDraft(''); setBudget(null) }} className="text-xs text-gray-500 underline">رجوع للمعدل</button>}
        <span className="text-xs text-gray-400">تجربة فقط — لا تُحفظ. تغيّر بند «مشتريات جديدة» بس.</span>
      </div>
      <div className={`grid gap-3 ${cell ? 'lg:grid-cols-[1fr_320px]' : ''}`}>
        <div data-tour="finance-cash-table" className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-xs whitespace-nowrap">
            <thead className="bg-gray-50 text-gray-600"><tr>
              <th className="text-right px-2 py-2">البند</th>
              {weeks.map(w => <th key={w.start} className="text-right px-2 py-2" title={`${w.start} → ${w.end}`}>{ddmm(w.start)}</th>)}
            </tr></thead>
            <tbody>
              {data.opening && (
                <tr className="border-t text-gray-500"><td className="px-2 py-1.5">رصيد افتتاحي {data.opening.as_of}</td>
                  <td className="px-2 py-1.5 font-semibold" colSpan={weeks.length}>{fmt(data.opening.amount)}</td></tr>
              )}
              {GROUPS.map(([g, title]) => (
                [<tr key={g} className="bg-gray-50/70"><td className="px-2 py-1.5 font-semibold" colSpan={weeks.length + 1}>{title}</td></tr>,
                ...data.lines.filter(ln => ln.group === g).map(ln => (
                  <tr key={ln.key} className={`border-t ${g === 'memo' ? 'text-gray-500' : ''}`}>
                    <td className="px-2 py-1.5" title={ln.notes.join(' · ')}>
                      {ln.label_ar} <span className={`text-[10px] px-1 rounded ${SOURCE_TONE[ln.source]}`}>{ln.source_label}</span>
                      {!!ln.notes.length && <span className="text-[10px] text-amber-700"> ⓘ</span>}
                    </td>
                    {ln.base.map((v, i) => (
                      <td key={i} className={`px-2 py-1.5 ${Number(v) ? 'cursor-pointer hover:bg-brand-50' : 'text-gray-300'} ${cell?.key === ln.key && cell?.week === i ? 'bg-brand-50' : ''}`}
                          onClick={() => Number(v) && pick(ln, i)}
                          title={ln.low[i] !== ln.base[i] || ln.high[i] !== ln.base[i] ? `متشائم ${fmt(ln.low[i])} · متفائل ${fmt(ln.high[i])}` : undefined}>
                        {Number(v) ? fmt(v) : '·'}
                      </td>
                    ))}
                  </tr>
                ))]
              ))}
              <tr className="border-t-2 font-semibold"><td className="px-2 py-1.5">صافي الأسبوع</td>
                {data.net.base.map((v, i) => <td key={i} className={`px-2 py-1.5 ${Number(v) < 0 ? 'text-orange-600' : ''}`}>{fmt(v)}</td>)}</tr>
              {[['low', 'الرصيد — متشائم'], ['base', 'الرصيد — أساسي'], ['high', 'الرصيد — متفائل']].map(([k, l]) => (
                <tr key={k} className={`border-t ${k === 'base' ? 'font-bold' : 'text-gray-600'}`}><td className="px-2 py-1.5">{l}</td>
                  {c[k] ? c[k].map((v, i) => <td key={i} className={`px-2 py-1.5 ${Number(v) < 0 ? 'text-orange-600' : ''}`}>{fmt(v)}</td>)
                        : <td className="px-2 py-1.5 text-gray-400" colSpan={weeks.length}>أدخل الرصيد الافتتاحي في «المدخلات»</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cell && <Drill cell={cell} budget={budget} onClose={() => setCell(null)} />}
      </div>
    </div>
  )
}

function InputsTab() {
  const qc = useQueryClient()
  const reload = () => qc.invalidateQueries({ queryKey: ['cash-view'] })
  const today = new Date().toISOString().slice(0, 10)
  const [ob, setOb] = useState({ as_of: today, amount: '', note: '' })
  const [nf, setNf] = useState({ label: '', category: 'salaries', amount: '', frequency: 'monthly', day_of_month: '', date: '', start: today })
  const [msg, setMsg] = useState('')
  const opening = useQuery({ queryKey: ['cash-view', 'opening'], queryFn: () => financeApi.cashOpening().then(r => r.data) })
  const fixed = useQuery({ queryKey: ['cash-view', 'fixed'], queryFn: () => financeApi.cashFixed().then(r => r.data) })
  const addOb = useMutation({
    mutationFn: () => financeApi.cashOpeningAdd(ob),
    onSuccess: () => { setMsg('حُفظ الرصيد.'); setOb(o => ({ ...o, amount: '', note: '' })); reload() },
    onError: (e) => setMsg(errOf(e, 'تعذّر الحفظ')),
  })
  const addF = useMutation({
    mutationFn: () => financeApi.cashFixedAdd(nf),
    onSuccess: () => { setMsg('أُضيف البند.'); setNf(f => ({ ...f, label: '', amount: '' })); reload() },
    onError: (e) => setMsg(errOf(e, 'تعذّر الحفظ')),
  })
  const upd = useMutation({
    mutationFn: (body) => financeApi.cashFixedUpdate(body),
    onSuccess: reload,
    onError: (e) => setMsg(errOf(e, 'تعذّر الحفظ')),
  })
  const set = (setter, k) => (e) => setter(x => ({ ...x, [k]: e.target.value }))
  const cats = fixed.data?.categories || []
  const freqs = fixed.data?.frequencies || []
  return (
    <div className="grid lg:grid-cols-2 gap-4 text-sm">
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="font-semibold">رصيد النقدية الافتتاحي</div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs">التاريخ<input type="date" value={ob.as_of} onChange={set(setOb, 'as_of')} className="border rounded px-1 py-1" /></label>
          <label className="flex flex-col text-xs">الرصيد<input type="number" step="1000" value={ob.amount} onChange={set(setOb, 'amount')} className="w-32 border rounded px-1 py-1" /></label>
          <label className="flex flex-col text-xs flex-1">الخزائن والبنوك<input value={ob.note} onChange={set(setOb, 'note')} className="border rounded px-1 py-1" /></label>
          <button disabled={!ob.amount} onClick={() => addOb.mutate()} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white disabled:opacity-40">حفظ</button>
        </div>
        <table className="w-full text-xs">
          <thead className="text-gray-500"><tr><th className="text-right p-1">التاريخ</th><th className="text-right p-1">الرصيد</th><th className="text-right p-1">بيان</th><th className="text-right p-1">أدخله</th></tr></thead>
          <tbody>{(opening.data?.rows || []).map(r => (
            <tr key={r.id} className="border-t"><td className="p-1">{r.as_of}</td><td className="p-1">{fmt(r.amount)}</td><td className="p-1 text-gray-500">{r.note}</td><td className="p-1 text-gray-400">{r.entered_by}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="font-semibold">مصروفات ثابتة</div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs">البيان<input value={nf.label} onChange={set(setNf, 'label')} className="w-32 border rounded px-1 py-1" /></label>
          <label className="flex flex-col text-xs">الفئة<select value={nf.category} onChange={set(setNf, 'category')} className="border rounded px-1 py-1">{cats.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className="flex flex-col text-xs">المبلغ<input type="number" step="1000" value={nf.amount} onChange={set(setNf, 'amount')} className="w-28 border rounded px-1 py-1" /></label>
          <label className="flex flex-col text-xs">التكرار<select value={nf.frequency} onChange={set(setNf, 'frequency')} className="border rounded px-1 py-1">{freqs.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          {nf.frequency === 'monthly' && <label className="flex flex-col text-xs">يوم الشهر<input type="number" min="1" max="31" step="1" value={nf.day_of_month} onChange={set(setNf, 'day_of_month')} className="w-16 border rounded px-1 py-1" /></label>}
          {nf.frequency === 'one_off' && <label className="flex flex-col text-xs">التاريخ<input type="date" value={nf.date} onChange={set(setNf, 'date')} className="border rounded px-1 py-1" /></label>}
          <button disabled={!nf.label || !nf.amount} onClick={() => addF.mutate()} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white disabled:opacity-40">إضافة</button>
        </div>
        <table className="w-full text-xs">
          <thead className="text-gray-500"><tr><th className="text-right p-1">البيان</th><th className="text-right p-1">الفئة</th><th className="text-right p-1">المبلغ</th><th className="text-right p-1">التكرار</th><th className="text-right p-1">فعّال</th></tr></thead>
          <tbody>{(fixed.data?.rows || []).map(f => (
            <tr key={f.id} className={`border-t ${f.is_active ? '' : 'text-gray-400'}`}>
              <td className="p-1">{f.label}</td><td className="p-1">{f.category_label}</td>
              <td className="p-1">
                <input type="number" step="1000" defaultValue={f.amount} className="w-24 border rounded px-1 py-0.5"
                       onBlur={e => e.target.value && Number(e.target.value) !== Number(f.amount) && upd.mutate({ id: f.id, amount: e.target.value })} />
              </td>
              <td className="p-1">{f.frequency_label}{f.day_of_month ? ` · يوم ${f.day_of_month}` : ''}{f.date ? ` · ${f.date}` : ''}</td>
              <td className="p-1"><input type="checkbox" checked={f.is_active} onChange={e => upd.mutate({ id: f.id, is_active: e.target.checked })} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {msg && <div className="lg:col-span-2 text-xs text-gray-600">{msg}</div>}
    </div>
  )
}

export default function CashViewPage() {
  const [tab, setTab] = useState('view')
  const [budget, setBudget] = useState(null)
  useHelpTab(tab)
  const exportX = () => financeApi.cashViewExport({ purchase_budget_weekly: budget || undefined }).then(res => {
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a'); a.href = url; a.download = 'cash_view.xlsx'
    document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
  })
  return (
    <div className="p-6 space-y-4" dir="rtl">
      <div data-tour="finance-cash-freshness">
        <DataFreshnessBar domains={['ap_reconciliation', 'ar_contracts', 'sales', 'purchases']} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {[['view', 'العرض'], ['inputs', 'المدخلات']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
                  className={`px-3 py-1.5 rounded-lg text-sm border ${tab === k ? 'bg-brand-600 text-white border-brand-600' : 'bg-white hover:bg-gray-50'}`}>{l}</button>
        ))}
        <span className="flex-1" />
        <button data-tour="finance-cash-export" onClick={exportX} className="px-3 py-1.5 border rounded-lg bg-white hover:bg-gray-50 text-sm">⬇️ تصدير Excel</button>
      </div>
      {tab === 'view' ? <ViewTab budget={budget} setBudget={setBudget} /> : <InputsTab />}
    </div>
  )
}
