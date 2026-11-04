/**
 * RuleEditor.jsx — side panel to read / edit one posting rule (finance-gl Plan 2).
 *
 * Saving never edits in place: the server closes the previous version and creates the next one
 * (effective from the chosen date). «تجربة» runs the rule over a date range (≤ 31 days) and shows
 * the entries and exceptions it WOULD produce — nothing is saved. Amounts are computed by the
 * server; this panel only lists the fields the rule may use.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { AccountPicker } from './EntryEditor'
import {
  OPENING_DATE, money, errOf, listOf, useGlBranches, inputCls, btnPrimary, btnPlain, ErrorBox,
} from './glUi'

export const SOURCE_TYPES = {
  sales_tenders: 'مبيعات نقدي/بطاقة',
  credit_sales: 'مبيعات آجل',
  purchases: 'مشتريات',
  supplier_payments: 'مدفوعات الموردين',
  cheque_maturity: 'استحقاق الشيكات',
  customer_collections: 'تحصيلات العملاء',
  expenses: 'المصروفات',
  treasury_other: 'خزينة أخرى',
}
// Arabic labels only - which fields / conditions / modes exist comes from GET rules/meta/ (rules.py)
const FIELD_LABEL = {
  net: 'الصافي', sales: 'المبيعات', returns: 'المرتجعات', credit: 'الآجل', gross_share: 'الإجمالي قبل الخصم',
  discount_share: 'الخصم', tax_share: 'الضريبة', value: 'القيمة', amount: 'المبلغ',
}
export const CONDITION_LABEL = {
  branch_in: 'الفرع ضمن', branch_not_in: 'الفرع ليس ضمن', kind_in: 'النوع ضمن', paymenttype_in: 'طريقة الدفع',
  doccode_in: 'كود المستند', financialdoc_in: 'المستند المالي', direction_in: 'الاتجاه',
  bank_type_in: 'نوع الخزينة/البنك', expcode_in: 'كود المصروف',
}
export const MAP_KINDS = { bank: 'خزينة / بنك', expense: 'مصروف', card_clearing: 'تسوية بطاقات' }
const MAP_KEY_LABEL = { bankcode: 'كود الخزينة/البنك', expcode: 'كود المصروف', branch_code: 'فرع المستند' }
const BRANCH_LABEL = { source: 'فرع المستند', hq: 'المركز الرئيسي', map: 'فرع الربط', none: 'بدون فرع' }
const PARTY_LABEL = { none: 'بدون', source: 'طرف المستند' }
const GRANULARITY_LABEL = { document: 'مستند', branch_day: 'فرع/يوم', party_day: 'طرف/يوم' }
const BOOK_LABEL = { general: 'عامة', cash: 'نقدية', credit: 'آجل' }

export const summarizeConditions = (c, branchName = (x) => x) => {
  const e = Object.entries(c || {})
  return e.length ? e.map(([k, v]) => `${CONDITION_LABEL[k] || k}: ${(v || []).map(x => (k === 'branch_in' || k === 'branch_not_in' ? branchName(x) : x)).join('،')}`).join(' · ') : 'كل المستندات'
}
export const summarizeLines = (lines, action) => {
  if (action === 'skip') return 'تجاهل (لا ترحيل)'
  return (lines || []).map(l => `${l.side === 'debit' ? 'م' : 'د'} ${l.account || `ربط ${MAP_KINDS[l.account_map] || l.account_map}`}`).join(' / ')
}

const blankLine = (fields) => ({ side: 'debit', account: '', account_map: '', map_key: '', amount: fields?.[0] || '', branch: 'source', party: 'none', cheque: false, description: '' })

const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const monthStart = () => { const d = new Date(); return isoOf(new Date(d.getFullYear(), d.getMonth(), 1)) }
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return isoOf(d) }

/** Branch conditions: pick a branch, store its SOFTECH code, show the labelled name (never a bare code). */
function BranchChips({ values, onChange, disabled, branches, labelOf }) {
  const nameOf = (code) => {
    const b = branches.find(x => String(x.softech_branch_id) === String(code))
    return b ? labelOf(b.id) : code
  }
  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map(v => (
        <span key={v} className="inline-flex items-center gap-1 bg-green-50 text-green-800 border border-green-200 rounded-full px-2 py-0.5 text-xs">
          {nameOf(v)}{!disabled && <button type="button" aria-label="حذف" onClick={() => onChange(values.filter(x => x !== v))}>×</button>}
        </span>
      ))}
      {!disabled && (
        <select className={`${inputCls} !py-0.5`} value="" onChange={e => { const c = e.target.value; if (c && !values.includes(c)) onChange([...values, c]) }}>
          <option value="">+ فرع</option>
          {branches.filter(b => !values.includes(String(b.softech_branch_id))).map(b => (
            <option key={b.id} value={String(b.softech_branch_id)}>{labelOf(b.id)}</option>
          ))}
        </select>
      )}
    </div>
  )
}

function Chips({ values, onChange, disabled }) {
  const [t, setT] = useState('')
  const add = () => { const v = t.trim(); if (v && !values.includes(v)) onChange([...values, v]); setT('') }
  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map(v => (
        <span key={v} className="inline-flex items-center gap-1 bg-green-50 text-green-800 border border-green-200 rounded-full px-2 py-0.5 text-xs">
          {v}{!disabled && <button type="button" aria-label="حذف" onClick={() => onChange(values.filter(x => x !== v))}>×</button>}
        </span>
      ))}
      {!disabled && (
        <input className={`${inputCls} w-24 !py-0.5`} value={t} placeholder="قيمة + Enter" onChange={e => setT(e.target.value)}
               onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add() } }} onBlur={add} />
      )}
    </div>
  )
}

function Preview({ result, labelOf }) {
  const t = result.totals || {}
  return (
    <div className="space-y-2 text-sm">
      <div className="text-gray-700">
        مستندات <b>{t.docs ?? 0}</b> · قيود <b>{t.entries ?? 0}</b> · متجاهَل <b>{t.skipped ?? 0}</b> · استثناءات <b>{t.exceptions ?? 0}</b>
        {' '}· مدين <b className="font-mono">{money(t.debit)}</b> · دائن <b className="font-mono">{money(t.credit)}</b>
      </div>
      {(result.exceptions || []).length > 0 && (
        <ul className="border border-amber-200 bg-amber-50 rounded-lg p-2 text-xs text-amber-800 space-y-0.5 max-h-40 overflow-auto">
          {result.exceptions.slice(0, 50).map((x, i) => (
            <li key={i}><span className="font-mono">{x.source_key}</span> — {x.message}
              {x.detail && Object.keys(x.detail).length > 0 && <span className="text-amber-600"> ({Object.values(x.detail).join(' · ')})</span>}</li>
          ))}
          {result.exceptions.length > 50 && <li>… و{result.exceptions.length - 50} أخرى</li>}
        </ul>
      )}
      <div className="max-h-96 overflow-auto space-y-2">
        {(result.entries || []).slice(0, 40).map((e, i) => (
          <table key={i} className="w-full text-xs border border-gray-200 rounded">
            <caption className="text-right bg-gray-50 px-2 py-1 text-gray-600">{e.entry_date} · {e.source_keys?.length || 0} مستند</caption>
            <tbody>
              {e.lines.map((l, j) => (
                <tr key={j} className="border-t border-gray-100">
                  <td className="px-2 py-1 font-mono">{l.account_code}</td>
                  <td className="px-2 py-1">{l.branch_id ? labelOf(l.branch_id) : ''}</td>
                  <td className="px-2 py-1 font-mono">{l.party_code}</td>
                  <td className="px-2 py-1 text-left font-mono" dir="ltr">{money(l.debit, { blankZero: true })}</td>
                  <td className="px-2 py-1 text-left font-mono" dir="ltr">{money(l.credit, { blankZero: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
        {(result.entries || []).length > 40 && <div className="text-xs text-gray-500">يُعرض أول 40 قيداً من {result.entries.length}</div>}
      </div>
    </div>
  )
}

/** rule = existing PostingRule json (latest version) | null for a new rule */
export default function RuleEditor({ rule, canEdit, onClose, onSaved }) {
  const qc = useQueryClient()
  const { branches, labelOf } = useGlBranches()
  const metaQ = useQuery({
    queryKey: ['gl', 'rules-meta'], staleTime: 30 * 60 * 1000,
    queryFn: () => glApi.rulesMeta().then(r => r.data),
  })
  const meta = metaQ.data
  const isNew = !rule
  const init = () => ({
    code: rule?.code || '', source_type: rule?.source_type || 'sales_tenders', description: rule?.description || '',
    conditions: JSON.parse(JSON.stringify(rule?.conditions || {})), action: rule?.action || 'post',
    granularity: rule?.granularity || 'document', book: rule?.book || 'general', priority: rule?.priority ?? 100,
    effective_from: rule ? monthStart() : OPENING_DATE, lines: JSON.parse(JSON.stringify(rule?.lines || [])),
  })
  const [f, setF] = useState(init)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [pv, setPv] = useState({ from: daysAgo(7), to: daysAgo(1) })
  const [result, setResult] = useState(null)
  useEffect(() => { setF(init()); setResult(null) }, [rule?.code, rule?.version])   // eslint-disable-line react-hooks/exhaustive-deps

  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', 'posting'],
    queryFn: () => glApi.accounts({ active: 'true', page_size: 2000 }).then(r => listOf(r.data)),
    staleTime: 5 * 60 * 1000,
  })
  const accounts = useMemo(() => (accountsQ.data || []).filter(a => a.is_posting !== false), [accountsQ.data])
  const nameOf = useMemo(() => Object.fromEntries(accounts.map(a => [String(a.code), a.name])), [accounts])
  const versionsQ = useQuery({
    queryKey: ['gl', 'rule-versions', rule?.code],
    queryFn: () => glApi.ruleVersions(rule.code).then(r => listOf(r.data)),
    enabled: !!rule?.code,
  })

  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const setLine = (i, patch) => setF(x => ({ ...x, lines: x.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }))
  const body = () => ({
    ...f, priority: Number(f.priority) || 0,
    lines: f.action === 'skip' ? [] : f.lines.map(l => {
      const o = { side: l.side, amount: l.amount, branch: l.branch || 'source', party: l.party || 'none' }
      if (l.account_map) { o.account_map = l.account_map; o.map_key = l.map_key || meta?.map_key_for_kind?.[l.account_map] } else o.account = l.account
      if (l.cheque) o.cheque = true
      if (l.description) o.description = l.description
      return o
    }),
  })

  const save = useMutation({
    mutationFn: () => glApi.ruleSave(body()).then(r => r.data),
    onSuccess: (r) => {
      setErr(''); setMsg(`تم الحفظ: النسخة ${r.version} سارية من ${r.effective_from}`)
      qc.invalidateQueries({ queryKey: ['gl', 'rules'] }); qc.invalidateQueries({ queryKey: ['gl', 'rule-versions'] })
      onSaved?.(r)
    },
    onError: (e) => { setMsg(''); setErr(errOf(e, 'تعذّر حفظ القاعدة')) },
  })
  const test = useMutation({
    mutationFn: () => glApi.rulePreview({ date_from: pv.from, date_to: pv.to, rule: { ...body(), effective_from: pv.from } }).then(r => r.data),
    onSuccess: (d) => { setErr(''); setResult(d) },
    onError: (e) => { setResult(null); setErr(errOf(e, 'تعذّرت التجربة')) },
  })

  const src = f.source_type
  const condKeys = Object.entries(meta?.condition_keys || {}).filter(([, types]) => types.includes(src))
  const srcFields = meta?.source_fields?.[src] || []
  const isCheque = (meta?.cheque_sources || []).includes(src)
  const ro = !canEdit

  return (
    <aside className="bg-white border border-gray-200 rounded-xl p-4 space-y-4 text-sm" dir="rtl" data-tour="finance-gl-rule-editor">
      <div className="flex items-center gap-2">
        <h2 className="font-bold text-gray-800">{isNew ? 'قاعدة جديدة' : `${rule.code} — النسخة ${rule.version}`}</h2>
        {ro && <span className="text-xs text-gray-500">(للعرض فقط)</span>}
        <button type="button" className={`${btnPlain} ms-auto`} onClick={onClose}>إغلاق</button>
      </div>

      {metaQ.isError && <ErrorBox>{errOf(metaQ.error, 'تعذّر تحميل خيارات القواعد')}</ErrorBox>}
      <fieldset disabled={ro || !meta} className="space-y-3 disabled:opacity-90">
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="space-y-0.5"><span className="text-xs text-gray-500">الكود</span>
            <input className={`${inputCls} w-full font-mono`} value={f.code} disabled={!isNew} dir="ltr"
                   onChange={e => set('code', e.target.value.trim())} placeholder="sales-cash" /></label>
          <label className="space-y-0.5"><span className="text-xs text-gray-500">نوع المصدر</span>
            <select className={`${inputCls} w-full`} value={f.source_type} disabled={!isNew}
                    onChange={e => setF(x => ({ ...x, source_type: e.target.value, conditions: {}, lines: [] }))}>
              {Object.entries(SOURCE_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className="space-y-0.5"><span className="text-xs text-gray-500">سارية من (تاريخ المستند)</span>
            <input type="date" className={`${inputCls} w-full`} value={f.effective_from} onChange={e => set('effective_from', e.target.value)} />
            <span className="block text-[11px] text-gray-500">
              {isNew ? 'القاعدة الجديدة تسري على المستندات من 2026-01-01 افتراضياً.'
                : 'النسخة الجديدة تسري من أول الشهر الحالي؛ المستندات قبل هذا التاريخ تبقى على النسخة القديمة.'}
            </span></label>
        </div>
        <label className="block space-y-0.5"><span className="text-xs text-gray-500">الوصف</span>
          <input className={`${inputCls} w-full`} value={f.description} onChange={e => set('description', e.target.value)} /></label>
        <div className="grid gap-2 sm:grid-cols-4">
          <label className="space-y-0.5"><span className="text-xs text-gray-500">الإجراء</span>
            <select className={`${inputCls} w-full`} value={f.action} onChange={e => set('action', e.target.value)}>
              <option value="post">ترحيل</option><option value="skip">تجاهل</option></select></label>
          <label className="space-y-0.5"><span className="text-xs text-gray-500">التجميع</span>
            <select className={`${inputCls} w-full`} value={f.granularity} onChange={e => set('granularity', e.target.value)}>
              {(meta?.granularities || []).map(k => <option key={k} value={k}>{GRANULARITY_LABEL[k] || k}</option>)}</select></label>
          <label className="space-y-0.5"><span className="text-xs text-gray-500">الدفتر</span>
            <select className={`${inputCls} w-full`} value={f.book} onChange={e => set('book', e.target.value)}>
              {(meta?.books || []).map(k => <option key={k} value={k}>{BOOK_LABEL[k] || k}</option>)}</select></label>
          <label className="space-y-0.5"><span className="text-xs text-gray-500">الأولوية</span>
            <input type="number" className={`${inputCls} w-full`} value={f.priority} onChange={e => set('priority', e.target.value)} /></label>
        </div>

        <div className="space-y-1.5">
          <div className="text-xs font-medium text-gray-600">الشروط</div>
          {condKeys.map(([k]) => {
            const on = k in f.conditions
            return (
              <div key={k} className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1 w-44 text-xs">
                  <input type="checkbox" checked={on} onChange={e => setF(x => {
                    const cond = { ...x.conditions }
                    if (e.target.checked) cond[k] = []; else delete cond[k]
                    return { ...x, conditions: cond }
                  })} /> {CONDITION_LABEL[k] || k}
                </label>
                {on && (k === 'branch_in' || k === 'branch_not_in'
                  ? <BranchChips values={f.conditions[k]} disabled={ro} branches={branches} labelOf={labelOf} onChange={v => setF(x => ({ ...x, conditions: { ...x.conditions, [k]: v } }))} />
                  : <Chips values={f.conditions[k]} disabled={ro} onChange={v => setF(x => ({ ...x, conditions: { ...x.conditions, [k]: v } }))} />)}
              </div>
            )
          })}
        </div>

        {f.action === 'post' && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="text-xs font-medium text-gray-600">الأسطر</div>
              {!ro && <button type="button" className="text-xs text-green-700 hover:underline" onClick={() => setF(x => ({ ...x, lines: [...x.lines, blankLine(meta?.source_fields?.[x.source_type])] }))}>+ سطر</button>}
            </div>
            {f.lines.map((l, i) => (
              <div key={i} className="border border-gray-200 rounded-lg p-2 grid gap-2 sm:grid-cols-6 items-end">
                <label className="space-y-0.5"><span className="text-xs text-gray-500">الجهة</span>
                  <select className={`${inputCls} w-full`} value={l.side} onChange={e => setLine(i, { side: e.target.value })}>
                    <option value="debit">مدين</option><option value="credit">دائن</option></select></label>
                <label className="space-y-0.5"><span className="text-xs text-gray-500">الحساب من</span>
                  <select className={`${inputCls} w-full`} value={l.account_map || ''}
                          onChange={e => setLine(i, e.target.value ? { account_map: e.target.value, map_key: meta?.map_key_for_kind?.[e.target.value], account: '' } : { account_map: '', map_key: '' })}>
                    <option value="">حساب ثابت</option>
                    {(meta?.map_kinds || []).map(k => <option key={k} value={k}>ربط: {MAP_KINDS[k] || k}</option>)}</select></label>
                <div className="sm:col-span-2 space-y-0.5">
                  {l.account_map ? (
                    <><span className="text-xs text-gray-500">مفتاح الربط</span>
                      <select className={`${inputCls} w-full`} value={l.map_key || meta?.map_key_for_kind?.[l.account_map] || ''} onChange={e => setLine(i, { map_key: e.target.value })}>
                        {(meta?.map_keys || []).map(k => <option key={k} value={k}>{MAP_KEY_LABEL[k] || k}</option>)}</select></>
                  ) : (
                    <><span className="text-xs text-gray-500">الحساب</span>
                      <AccountPicker value={l.account} name={nameOf[String(l.account)] || ''} accounts={accounts} disabled={ro}
                                     onPick={a => setLine(i, { account: a.code })} /></>
                  )}
                </div>
                <label className="space-y-0.5"><span className="text-xs text-gray-500">المبلغ</span>
                  <select className={`${inputCls} w-full`} value={l.amount} onChange={e => setLine(i, { amount: e.target.value })}>
                    {srcFields.map(a => <option key={a} value={a}>{FIELD_LABEL[a] || a}</option>)}</select></label>
                <label className="space-y-0.5"><span className="text-xs text-gray-500">الفرع</span>
                  <select className={`${inputCls} w-full`} value={l.branch || 'source'} onChange={e => setLine(i, { branch: e.target.value })}>
                    {(meta?.branch_modes || []).map(k => <option key={k} value={k}>{BRANCH_LABEL[k] || k}</option>)}</select></label>
                <label className="space-y-0.5"><span className="text-xs text-gray-500">الطرف</span>
                  <select className={`${inputCls} w-full`} value={l.party || 'none'} onChange={e => setLine(i, { party: e.target.value })}>
                    {(meta?.party_modes || []).map(k => <option key={k} value={k}>{PARTY_LABEL[k] || k}</option>)}</select></label>
                {isCheque && (
                  <label className="flex items-center gap-1 text-xs pb-2"><input type="checkbox" checked={!!l.cheque} onChange={e => setLine(i, { cheque: e.target.checked })} /> رقم الشيك/الاستحقاق</label>
                )}
                <label className="sm:col-span-3 space-y-0.5"><span className="text-xs text-gray-500">البيان ({(meta?.placeholders || []).map(x => `{${x}}`).join(' ')})</span>
                  <input className={`${inputCls} w-full`} value={l.description || ''} onChange={e => setLine(i, { description: e.target.value })} /></label>
                {!ro && <button type="button" className="text-xs text-red-600 hover:underline pb-2" onClick={() => setF(x => ({ ...x, lines: x.lines.filter((_, j) => j !== i) }))}>حذف السطر</button>}
              </div>
            ))}
          </div>
        )}
      </fieldset>

      <ErrorBox>{err}</ErrorBox>
      {msg && <div className="text-sm text-green-700">{msg}</div>}
      {canEdit && (
        <div className="flex items-center gap-2">
          <button type="button" className={btnPrimary} disabled={save.isPending} onClick={() => save.mutate()}>
            {isNew ? 'حفظ القاعدة' : 'حفظ كنسخة جديدة'}
          </button>
          {!isNew && <span className="text-xs text-gray-500">المستندات قبل «سارية من» تبقى على النسخة الحالية</span>}
        </div>
      )}

      <div className="border-t border-gray-100 pt-3 space-y-2" data-tour="finance-gl-rule-test">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-gray-600">تجربة (لا تحفظ شيئاً، حتى 31 يوماً)</span>
          <input type="date" className={inputCls} value={pv.from} onChange={e => setPv(p => ({ ...p, from: e.target.value }))} />
          <input type="date" className={inputCls} value={pv.to} onChange={e => setPv(p => ({ ...p, to: e.target.value }))} />
          <button type="button" className={btnPlain} disabled={test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? 'جاري التجربة…' : 'تجربة'}
          </button>
        </div>
        {result && <Preview result={result} labelOf={labelOf} />}
      </div>

      {!isNew && (
        <div className="border-t border-gray-100 pt-3 space-y-1">
          <div className="text-xs font-medium text-gray-600">سجل النسخ</div>
          {(versionsQ.data || []).map(v => (
            <div key={v.id} className="flex items-center gap-2 text-xs text-gray-700">
              <span className="font-mono">v{v.version}</span>
              <span>{v.effective_from} ← {v.effective_to || 'مفتوحة'}</span>
              <span className={v.is_active ? 'text-green-700' : 'text-gray-400'}>{v.is_active ? 'نشطة' : 'مغلقة'}</span>
              <span className="text-gray-500 truncate">{summarizeLines(v.lines, v.action)}</span>
              {canEdit && (
                <button type="button" className="text-blue-700 hover:underline ms-auto whitespace-nowrap"
                        onClick={() => setF(x => ({ ...x, description: v.description || '', conditions: JSON.parse(JSON.stringify(v.conditions || {})), action: v.action, granularity: v.granularity, book: v.book, priority: v.priority, lines: JSON.parse(JSON.stringify(v.lines || [])) }))}>
                  استخدم كأساس
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </aside>
  )
}
