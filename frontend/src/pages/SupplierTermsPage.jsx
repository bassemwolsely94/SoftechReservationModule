/**
 * SupplierTermsPage — /finance/supplier-terms «شروط الموردين» (P-42).
 *
 * Finance enters each supplier's credit days per item category (local / imported, or «كل الأصناف» as the supplier-wide
 * default) and any early-pay discount. The server splits every open supplier invoice by category from its purchase
 * lines and gives each part a due date; no term → no due date. Tabs: terms, payment calendar (weeks start Saturday),
 * early-pay opportunities ranked by annualised return, paid on time (always with its link coverage), and items open
 * more than a year. Internal / virtual accounts are shown apart. Company-level finance; nothing writes to SOFTECH.
 */
import { Fragment, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { financeApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import ProgressBar from '../components/ProgressBar'
import useBranchLabels from '../hooks/useBranchLabels'
import useHelpTab from '../help/useHelpTab'
import { wildcardMatch } from '../utils/wildcard'

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 }))
const fmt2 = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const errOf = (e, d) => e?.response?.data?.detail || d
const CATS = [['any', 'كل الأصناف'], ['local', 'محلي'], ['imported', 'مستورد']]
const CAT_LABEL = { any: 'كل الأصناف', local: 'محلي', imported: 'مستورد', unclassified: 'غير مصنف' }
const TABS = [
  ['terms', 'الشروط'], ['calendar', 'تقويم السداد'], ['early', 'فرص الدفع المبكر'],
  ['ontime', 'السداد في الموعد'], ['residue', 'البواقي القديمة'],
]
const SHEET = { terms: 'terms', calendar: 'calendar', early: 'early_pay', ontime: 'on_time', residue: 'residue' }

function Kpi({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function current(terms, today) {
  return terms.find(t => t.effective_from <= today && (!t.effective_to || t.effective_to >= today))
}

/** One category's credit days, edited in place: changes the term in force, or creates one from `since`. */
function DaysCell({ term, personcode, category, since, onSaved }) {
  const [v, setV] = useState(term?.credit_days ?? '')
  const [err, setErr] = useState('')
  useEffect(() => { setV(term?.credit_days ?? '') }, [term?.id, term?.credit_days])
  const save = useMutation({
    mutationFn: () => (term
      ? financeApi.supplierTermUpdate({ id: term.id, credit_days: Number(v) })
      : financeApi.supplierTermCreate({ personcode, category, credit_days: Number(v), effective_from: since })),
    onSuccess: () => { setErr(''); onSaved() },
    onError: (e) => setErr(errOf(e, 'تعذّر الحفظ')),
  })
  const dirty = v !== '' && String(v) !== String(term?.credit_days ?? '')
  return (
    <span className="inline-flex items-center gap-1">
      <input type="number" min="0" max="365" step="1" value={v} placeholder="—"
             onChange={e => setV(e.target.value)}
             onKeyDown={e => { if (e.key === 'Enter' && dirty) save.mutate() }}
             onBlur={() => dirty && save.mutate()}
             className="w-16 border rounded px-1 py-0.5 text-xs"
             title={term ? `${term.days_from === 'month_end' ? 'من نهاية الشهر' : 'من تاريخ الفاتورة'} · ساري من ${term.effective_from}` : 'أيام الائتمان'} />
      {term?.early_pay_discount_pct && <span className="text-[10px] text-emerald-700" title="خصم دفع مبكر">{term.early_pay_discount_pct}%</span>}
      {save.isPending && <span className="text-xs text-gray-400">…</span>}
      {err && <span className="text-xs text-red-600">{err}</span>}
    </span>
  )
}

/** Every field of one term (the expanded row). */
function TermForm({ term, onSaved }) {
  const [f, setF] = useState({
    days_from: term.days_from, early_pay_days: term.early_pay_days ?? '', early_pay_discount_pct: term.early_pay_discount_pct ?? '',
    early_pay_bonus_note: term.early_pay_bonus_note || '', effective_to: term.effective_to || '', source_note: term.source_note || '',
  })
  const [msg, setMsg] = useState('')
  const save = useMutation({
    mutationFn: () => financeApi.supplierTermUpdate({ id: term.id, ...f }),
    onSuccess: () => { setMsg('حُفظ'); onSaved() },
    onError: (e) => setMsg(errOf(e, 'تعذّر الحفظ')),
  })
  const set = (k) => (e) => setF(x => ({ ...x, [k]: e.target.value }))
  return (
    <div className="flex flex-wrap items-end gap-2 text-xs border-t py-2">
      <span className="font-semibold w-20">{CAT_LABEL[term.category]} · {term.credit_days} يوم</span>
      <label className="flex flex-col">تبدأ الأيام
        <select value={f.days_from} onChange={set('days_from')} className="border rounded px-1 py-0.5">
          <option value="invoice">من تاريخ الفاتورة</option><option value="month_end">من نهاية الشهر</option>
        </select>
      </label>
      <label className="flex flex-col">دفع مبكر خلال (يوم)
        <input type="number" min="0" max="365" step="1" value={f.early_pay_days} onChange={set('early_pay_days')} className="w-20 border rounded px-1 py-0.5" />
      </label>
      <label className="flex flex-col">خصم %
        <input type="number" min="0" max="99.99" step="0.25" value={f.early_pay_discount_pct} onChange={set('early_pay_discount_pct')} className="w-20 border rounded px-1 py-0.5" />
      </label>
      <label className="flex flex-col">أو بونص (وصف)
        <input value={f.early_pay_bonus_note} onChange={set('early_pay_bonus_note')} className="w-40 border rounded px-1 py-0.5" />
      </label>
      <label className="flex flex-col">ساري حتى
        <input type="date" value={f.effective_to} onChange={set('effective_to')} className="border rounded px-1 py-0.5" />
      </label>
      <label className="flex flex-col">مرجع الاتفاق
        <input value={f.source_note} onChange={set('source_note')} className="w-40 border rounded px-1 py-0.5" />
      </label>
      <button onClick={() => save.mutate()} className="px-2 py-1 border rounded bg-white hover:bg-gray-50">حفظ</button>
      {msg && <span className="text-gray-500">{msg}</span>}
      <span className="text-gray-400">ساري من {term.effective_from}{term.entered_by ? ` · ${term.entered_by}` : ''}</span>
    </div>
  )
}

function TermsTab({ onSaved }) {
  const today = new Date().toISOString().slice(0, 10)
  const [since, setSince] = useState('2000-01-01')
  const [top, setTop] = useState(true)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState({})
  const { data, isLoading } = useQuery({ queryKey: ['supplier-terms', 'terms'], queryFn: () => financeApi.supplierTerms().then(r => r.data) })
  const byParty = useMemo(() => {
    const m = {}
    for (const t of data?.terms || []) (m[t.personcode] ||= []).push(t)
    return m
  }, [data])
  const rows = (data?.suppliers || []).filter(s => (!top || s.is_top10 || s.has_terms)
    && (!q || wildcardMatch(`${s.personcode} ${s.supplier}`, q)))
  const cov = data?.coverage || {}
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Kpi label="تغطية الشروط" value={cov.coverage_pct == null ? '—' : `${cov.coverage_pct}%`} sub="من مفتوح الموردين الفعليين له تاريخ استحقاق" />
        <Kpi label="مفتوح الموردين الفعليين" value={`${fmt(cov.open_real)} ج`} sub={`الحسابات الداخلية منفصلة: ${(data?.internal_codes || []).join('، ')}`} />
        <Kpi label="بشروط" value={`${fmt(cov.with_terms)} ج`} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالمورد أو الكود" className="border rounded-lg px-2 py-1" />
        <label className="flex items-center gap-1"><input type="checkbox" checked={top} onChange={e => setTop(e.target.checked)} /> أكبر 10 بالقيمة + من له شروط</label>
        <label className="flex items-center gap-1 text-gray-600">الشروط الجديدة سارية من
          <input type="date" value={since} onChange={e => setSince(e.target.value)} className="border rounded px-1 py-0.5" />
        </label>
        <span className="text-xs text-gray-400">«كل الأصناف» تُطبق حين لا يوجد شرط للفئة.</span>
      </div>
      {isLoading ? <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead className="bg-gray-50 text-gray-600 text-xs"><tr>
              <th className="text-right px-2 py-2">المورد</th><th className="text-right px-2 py-2">المفتوح</th>
              {CATS.map(([c, l]) => <th key={c} className="text-right px-2 py-2">{l} (يوم)</th>)}
            </tr></thead>
            <tbody>
              {rows.map(s => {
                const terms = byParty[s.personcode] || []
                return (
                  <Fragment key={s.personcode}>
                    <tr className="border-t">
                      <td className="px-2 py-1.5 cursor-pointer" onClick={() => setOpen(o => ({ ...o, [s.personcode]: !o[s.personcode] }))}>
                        {terms.length ? (open[s.personcode] ? '▾ ' : '▸ ') : ''}{s.personcode} · {s.supplier}
                        {s.is_top10 && <span className="mr-1 text-[10px] text-indigo-600">أكبر 10</span>}
                      </td>
                      <td className="px-2 py-1.5">{fmt(s.open)}</td>
                      {CATS.map(([c]) => (
                        <td key={c} className="px-2 py-1.5">
                          <DaysCell term={current(terms.filter(t => t.category === c), today)} personcode={s.personcode}
                                    category={c} since={since} onSaved={onSaved} />
                        </td>
                      ))}
                    </tr>
                    {open[s.personcode] && (
                      <tr><td colSpan={5} className="bg-gray-50 px-4">
                        {terms.map(t => <TermForm key={t.id} term={t} onSaved={onSaved} />)}
                      </td></tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          {!rows.length && <div className="text-center py-10 text-gray-400 text-sm">لا موردين بفواتير مفتوحة.</div>}
        </div>
      )}
    </div>
  )
}

function CalendarTab() {
  const { data, isLoading } = useQuery({ queryKey: ['supplier-terms', 'calendar'], queryFn: () => financeApi.supplierTermsCalendar({ weeks: 13 }).then(r => r.data) })
  if (isLoading) return <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div>
  const weeks = data?.weeks || []
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="متأخر عن الاستحقاق" value={`${fmt(data?.overdue)} ج`} tone="text-red-700" />
        <Kpi label="مستحق خلال 13 أسبوعًا" value={`${fmt(weeks.reduce((s, w) => s + Number(w.due || 0), 0))} ج`} />
        <Kpi label="بدون شروط" value={`${fmt(data?.no_terms)} ج`} tone="text-amber-700" sub="لا تاريخ استحقاق — أدخل الشروط" />
        <Kpi label="حسابات داخلية" value={`${fmt(data?.internal)} ج`} sub="منفصلة — ليست ديون موردين" />
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="bg-gray-50 text-gray-600"><tr>
            <th className="text-right px-2 py-2">المورد</th><th className="text-right px-2 py-2">الفئة</th>
            <th className="text-right px-2 py-2">متأخر</th><th className="text-right px-2 py-2">بدون شروط</th>
            {weeks.map(w => <th key={w.start} className="text-right px-2 py-2" title={`${w.start} → ${w.end}`}>{w.start.slice(8, 10)}/{w.start.slice(5, 7)}</th>)}
            <th className="text-right px-2 py-2">بعد ذلك</th>
          </tr></thead>
          <tbody>
            <tr className="border-t font-semibold bg-gray-50/60">
              <td className="px-2 py-1.5" colSpan={2}>الإجمالي</td>
              <td className="px-2 py-1.5 text-red-700">{fmt(data?.overdue)}</td><td className="px-2 py-1.5">{fmt(data?.no_terms)}</td>
              {weeks.map(w => <td key={w.start} className="px-2 py-1.5">{fmt(w.due)}</td>)}
              <td className="px-2 py-1.5">{fmt(data?.later)}</td>
            </tr>
            {(data?.rows || []).map(r => (
              <tr key={`${r.personcode}-${r.category}`} className="border-t">
                <td className="px-2 py-1.5">{r.personcode} · {r.supplier}</td>
                <td className="px-2 py-1.5">{CAT_LABEL[r.category]}</td>
                <td className="px-2 py-1.5 text-red-700">{r.overdue ? fmt(r.overdue) : ''}</td>
                <td className="px-2 py-1.5 text-amber-700">{r.no_terms ? fmt(r.no_terms) : ''}</td>
                {r.weeks.map((v, i) => <td key={i} className="px-2 py-1.5">{v ? fmt(v) : ''}</td>)}
                <td className="px-2 py-1.5">{r.later ? fmt(r.later) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!!data?.internal_rows?.length && (
        <div className="bg-white rounded-xl border border-gray-200 p-3">
          <div className="text-xs font-semibold text-gray-600 mb-2">حسابات داخلية / افتراضية — منفصلة عن ديون الموردين</div>
          {data.internal_rows.map(r => (
            <div key={r.personcode} className="flex justify-between text-xs border-t py-1">
              <span>{r.personcode} · {r.supplier} <span className="text-gray-400">({r.invoices} فاتورة)</span></span><span>{fmt(r.open)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EarlyTab() {
  const bl = useBranchLabels()
  const { data, isLoading } = useQuery({ queryKey: ['supplier-terms', 'early'], queryFn: () => financeApi.supplierTermsEarlyPay().then(r => r.data) })
  if (isLoading) return <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div>
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Kpi label="خصم متاح لو دُفع في الموعد" value={`${fmt2(data?.available_value)} ج`} tone="text-emerald-700" />
        <Kpi label="خصم فات" value={`${fmt2(data?.foregone_value)} ج`} tone="text-red-700" sub="فاتورة ما زالت مفتوحة بعد آخر موعد للدفع المبكر" />
      </div>
      <p className="text-xs text-gray-500">مرتبة بالعائد السنوي = خصم ÷ (100 − خصم) × 365 ÷ الأيام المكسوبة. للاسترشاد فقط — المالية تقرر ما يُدفع.</p>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="bg-gray-50 text-gray-600"><tr>
            {['المورد', 'الفاتورة', 'الفئة', 'المفتوح', 'آخر موعد', 'الاستحقاق', 'أيام مكسوبة', 'خصم %', 'قيمة الخصم', 'العائد السنوي %'].map(h =>
              <th key={h} className="text-right px-2 py-2">{h}</th>)}
          </tr></thead>
          <tbody>
            {(data?.open || []).map(r => (
              <tr key={`${r.invoice_id}-${r.categories.join()}`} className="border-t">
                <td className="px-2 py-1.5">{r.personcode} · {r.supplier}</td>
                <td className="px-2 py-1.5">{bl(r.branchcode)} · #{r.docnumber} · {r.docdate}</td>
                <td className="px-2 py-1.5">{r.categories.map(c => CAT_LABEL[c]).join('، ')}</td>
                <td className="px-2 py-1.5">{fmt(r.open_amount)}</td>
                <td className="px-2 py-1.5">{r.deadline}</td><td className="px-2 py-1.5">{r.due_date || '—'}</td>
                <td className="px-2 py-1.5">{r.days_gained ?? '—'}</td>
                <td className="px-2 py-1.5">{r.discount_pct ?? (r.bonus_note ? 'بونص' : '—')}</td>
                <td className="px-2 py-1.5">{r.discount_value == null ? (r.bonus_note || '—') : fmt2(r.discount_value)}</td>
                <td className="px-2 py-1.5 font-semibold">{r.annualised_return_pct ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.open?.length && <div className="text-center py-10 text-gray-400 text-sm">لا فرص دفع مبكر — تظهر بعد إدخال أيام وخصم الدفع المبكر في الشروط.</div>}
      </div>
    </div>
  )
}

function OnTimeTab() {
  const { data, isLoading } = useQuery({ queryKey: ['supplier-terms', 'ontime'], queryFn: () => financeApi.supplierTermsOnTime().then(r => r.data) })
  if (isLoading) return <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div>
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Kpi label="تغطية الربط (آخر سنة)" value={data?.coverage_pct == null ? '—' : `${data.coverage_pct}%`} tone="text-amber-700"
             sub="المدفوع المربوط بفواتير في SOFTECH ÷ كل المدفوع — الأرقام تخص الجزء المربوط فقط" />
        <Kpi label="المدفوع للموردين الفعليين" value={`${fmt(data?.paid_value)} ج`} />
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="bg-gray-50 text-gray-600"><tr>
            {['المورد', 'أيام مقابل الشروط', 'محلي', 'مستورد', 'قيمة مقاسة', 'بدون شروط', 'المدفوع', 'تغطية الربط %'].map(h =>
              <th key={h} className="text-right px-2 py-2">{h}</th>)}
          </tr></thead>
          <tbody>
            {(data?.rows || []).map(r => {
              const cat = (c) => r.by_category.find(x => x.category === c)?.days_vs_terms
              return (
                <tr key={r.personcode} className="border-t">
                  <td className="px-2 py-1.5">{r.personcode} · {r.supplier}</td>
                  <td className={`px-2 py-1.5 font-semibold ${Number(r.days_vs_terms) > 0 ? 'text-red-700' : 'text-emerald-700'}`}>{r.days_vs_terms ?? '—'}</td>
                  <td className="px-2 py-1.5">{cat('local') ?? '—'}</td><td className="px-2 py-1.5">{cat('imported') ?? '—'}</td>
                  <td className="px-2 py-1.5">{fmt(r.value)}</td><td className="px-2 py-1.5">{fmt(r.no_terms_value)}</td>
                  <td className="px-2 py-1.5">{fmt(r.paid_value)}</td>
                  <td className="px-2 py-1.5">{r.coverage_pct ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {!data?.rows?.length && <div className="text-center py-10 text-gray-400 text-sm">لا مدفوعات للموردين في آخر سنة.</div>}
      </div>
      <p className="text-xs text-gray-500">موجب = دُفع بعد الاستحقاق، سالب = قبله. فاتورة مسددة بالكامل عبر ربط SOFTECH فقط؛ المدفوع بلا ربط لا يُحسب.</p>
    </div>
  )
}

function ResidueTab() {
  const [cls, setCls] = useState('real')
  const { data, isLoading } = useQuery({ queryKey: ['supplier-terms', 'residue'], queryFn: () => financeApi.supplierTermsResidue().then(r => r.data) })
  if (isLoading) return <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div>
  const rows = (data?.rows || []).filter(r => r.account_class === cls)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Kpi label="موردون فعليون — مفتوح أكثر من سنة" value={`${fmt(data?.real)} ج`} />
        <Kpi label="حسابات داخلية — مفتوح أكثر من سنة" value={`${fmt(data?.internal)} ج`} />
      </div>
      <div className="flex gap-2 text-sm">
        {[['real', 'موردون فعليون'], ['internal', 'حسابات داخلية']].map(([k, l]) => (
          <button key={k} onClick={() => setCls(k)} className={`px-3 py-1 rounded-lg border ${cls === k ? 'bg-brand-600 text-white' : 'bg-white'}`}>{l}</button>
        ))}
        <span className="text-xs text-gray-400 self-center">للقراءة — الإغلاق يتم في SOFTECH.</span>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="bg-gray-50 text-gray-600"><tr>
            {['المورد', 'الفرع', 'الفاتورة', 'التاريخ', 'العمر (يوم)', 'القيمة', 'المفتوح', 'مطابقة مقترحة', 'الحالة'].map(h =>
              <th key={h} className="text-right px-2 py-2">{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.invoice_id} className="border-t">
                <td className="px-2 py-1.5">{r.personcode} · {r.supplier}</td><td className="px-2 py-1.5">{r.branch_name}</td>
                <td className="px-2 py-1.5">#{r.docnumber}</td><td className="px-2 py-1.5">{r.docdate}</td>
                <td className="px-2 py-1.5">{r.age_days}</td><td className="px-2 py-1.5">{fmt(r.doc_value)}</td>
                <td className="px-2 py-1.5">{fmt(r.open_in_softech)}</td>
                <td className="px-2 py-1.5">{fmt(Number(r.matched_approved || 0) + Number(r.matched_high_pending || 0) + Number(r.under_review || 0))}</td>
                <td className="px-2 py-1.5">{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="text-center py-10 text-gray-400 text-sm">لا بنود مفتوحة أكثر من سنة.</div>}
      </div>
    </div>
  )
}

export default function SupplierTermsPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('terms')
  const [msg, setMsg] = useState('')
  const [since, setSince] = useState(null)
  useHelpTab(tab)
  const reload = () => qc.invalidateQueries({ queryKey: ['supplier-terms'] })
  const status = useQuery({
    queryKey: ['supplier-terms-recompute'],
    queryFn: () => financeApi.supplierTermsRecomputeStatus().then(r => r.data),
    enabled: since != null,
    refetchInterval: 3000,
  })
  useEffect(() => {
    if (since != null && status.data && !status.data.running) { setSince(null); setMsg('اكتملت إعادة الحساب.'); reload() }
  }, [status.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const recompute = () => financeApi.supplierTermsRecompute()
    .then(r => { setMsg(r.data.detail); setSince(Date.now()) })
    .catch(e => setMsg(errOf(e, 'تعذّر بدء إعادة الحساب')))
  const exportX = () => financeApi.supplierTermsExport(SHEET[tab]).then(res => {
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a'); a.href = url; a.download = `supplier_terms_${SHEET[tab]}.xlsx`
    document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
  })

  return (
    <div className="p-6 space-y-4" dir="rtl">
      <div data-tour="finance-supplier-terms-freshness">
        <DataFreshnessBar domains={['ap_reconciliation', 'purchases']} onRefresh={recompute} />
      </div>
      {since != null && <ProgressBar label="إعادة حساب الاستحقاقات" message="تقسيم الفواتير المفتوحة محلي / مستورد…" since={since} />}
      {msg && since == null && <div className="text-sm bg-white border rounded-lg px-3 py-2">{msg}</div>}
      <div className="flex flex-wrap items-center gap-2">
        <div data-tour="finance-supplier-terms-tabs" className="flex flex-wrap gap-1">
          {TABS.map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)}
                    className={`px-3 py-1.5 rounded-lg text-sm border ${tab === k ? 'bg-brand-600 text-white border-brand-600' : 'bg-white hover:bg-gray-50'}`}>{l}</button>
          ))}
        </div>
        <span className="flex-1" />
        <button data-tour="finance-supplier-terms-export" onClick={exportX} className="px-3 py-1.5 border rounded-lg bg-white hover:bg-gray-50 text-sm">⬇️ تصدير Excel</button>
      </div>
      {tab === 'terms' && <TermsTab onSaved={reload} />}
      {tab === 'calendar' && <CalendarTab />}
      {tab === 'early' && <EarlyTab />}
      {tab === 'ontime' && <OnTimeTab />}
      {tab === 'residue' && <ResidueTab />}
    </div>
  )
}
