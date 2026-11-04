/**
 * StatementsPage.jsx — «القوائم المالية»
 * Route: /finance/statements?tab=trading|position|branches|comparison
 *
 *   trading     trading account + P&L in finance's two-column layout, with ratios
 *   position    statement of financial position; `check` shown only when ≠ 0 (red)
 *   branches    branch P&L with the HQ allocation rows (report-time only, posts nothing)
 *   comparison  years × lines, value and % of sales («الختامية المجمعة»)
 *
 * Every figure comes from the server; this page lays them out. Print hides the filters.
 * Trading / position take an optional closing-stock value (`closing_stock`) that replaces the
 * 5302 entries for that report only — the server validates it and posts nothing.
 */
import { Fragment, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useHelpTab from '../../../help/useHelpTab'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import {
  money, pct, errOf, listOf, rangeOf, todayIso, saveBlob, PeriodPicker,
  inputCls, btnPlain, ErrorBox,
} from './glUi'

const TABS = [
  ['trading',    'المتاجرة والأرباح والخسائر'],
  ['position',   'المركز المالي'],
  ['branches',   'أرباح الفروع'],
  ['comparison', 'مقارنة السنوات'],
]

/** Value of `key` at the top level or one level down (the server may group sections). */
function pick(d, ...keys) {
  if (!d) return undefined
  for (const k of keys) {
    if (d[k] !== undefined && typeof d[k] !== 'object') return d[k]
    if (d[k] && typeof d[k] === 'object' && 'amount' in d[k]) return d[k].amount
  }
  for (const v of Object.values(d)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const hit = pick(v, ...keys)
      if (hit !== undefined) return hit
    }
  }
  return undefined
}

// «يخصم» lines: a positive deduction shows in parentheses; a negative one keeps its sign
const amt = (v, neg = false) => (v === undefined || v === null ? '' : neg && Number(v) > 0 ? `(${money(v)})` : money(v))

// ── trading + P&L lines: [label, key(s), column, kind] — column 0 = detail, 1 = total ──
const TRADING = [
  { label: 'صافي المبيعات', keys: ['net_sales'], col: 1 },
  { label: 'يخصم: تكلفة المبيعات', head: true },
  { label: 'مخزون أول المدة', keys: ['opening_stock'], col: 0, indent: true },
  { label: 'يضاف: صافي المشتريات', keys: ['net_purchases'], col: 0, indent: true },
  { label: 'يخصم: مخزون آخر المدة', keys: ['closing_stock'], col: 0, indent: true, neg: true },
  { label: 'تكلفة المبيعات', keys: ['cost_of_sales'], col: 1, neg: true, optional: true },
  { label: 'مجمل الربح', keys: ['gross_profit'], col: 1, strong: true },
  { label: 'يضاف: إيرادات أخرى', keys: ['other_revenue'], col: 0 },
  { label: 'يضاف: أرباح وخسائر رأسمالية', keys: ['capital_gains'], col: 0 },
  { label: 'يخصم: المصروفات العمومية', keys: ['general_expenses'], col: 0, neg: true },
  { label: 'يخصم: مصروفات بيع وتوزيع', keys: ['selling_expenses'], col: 0, neg: true },
  { label: 'يخصم: مصروفات التشغيل', keys: ['operating_expenses'], col: 0, neg: true },
  { label: 'يخصم: المصروفات التمويلية', keys: ['financing_expenses'], col: 0, neg: true },
  { label: 'يخصم: الإهلاكات', keys: ['depreciation'], col: 0, neg: true },
  { label: 'إجمالي المصروفات', keys: ['total_expenses'], col: 1, neg: true, optional: true },
  { label: 'يخصم: حسابات بدون بند', keys: ['unclassified'], col: 0, neg: true, optional: true, hideZero: true },
  { label: 'صافي الربح', keys: ['net_profit'], col: 1, strong: true },
]
const RATIOS = [
  ['هامش مجمل الربح', 'gross_margin', 'pct'], ['هامش صافي الربح', 'net_margin', 'pct'],
  ['نسبة المصروفات', 'expense_ratio', 'pct'], ['متوسط المبيعات الشهري', 'monthly_avg_sales', 'money'],
]

function TwoColumn({ lines, data }) {
  return (
    <table className="w-full text-sm">
      <tbody>
        {lines.map((l, i) => {
          if (l.head) return <tr key={i}><td className="px-3 pt-3 pb-1 font-medium text-gray-700" colSpan={3}>{l.label}</td></tr>
          const v = pick(data, ...l.keys)
          if (l.optional && (v === undefined || (l.hideZero && Number(v) === 0))) return null
          const cls = l.strong ? 'font-bold border-t border-gray-300 bg-gray-50' : ''
          return (
            <tr key={i} className={cls}>
              <td className={`px-3 py-1.5 ${l.indent ? 'pe-3 ps-8' : ''}`}>{l.label}</td>
              <td className="px-3 py-1.5 text-left font-mono tabular-nums w-40" dir="ltr">{l.col === 0 ? amt(v, l.neg) : ''}</td>
              <td className="px-3 py-1.5 text-left font-mono tabular-nums w-40" dir="ltr">{l.col === 1 ? amt(v, l.neg) : ''}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Trading({ data }) {
  return (
    <div className="grid md:grid-cols-3 gap-4">
      <div className="md:col-span-2 bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <TwoColumn lines={TRADING} data={data} />
      </div>
      <div className="bg-white rounded-xl border border-gray-200 p-3 space-y-2 h-fit">
        <div className="text-sm font-medium text-gray-700">النسب</div>
        {RATIOS.map(([l, k, kind]) => (
          <div key={k} className="flex justify-between text-sm">
            <span className="text-gray-600">{l}</span>
            <span className="font-mono tabular-nums" dir="ltr">{kind === 'pct' ? pct(pick(data, k)) : money(pick(data, k))}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const POSITION = [
  { label: 'الأصول طويلة الأجل', head: true },
  { label: 'الأصول الثابتة (التكلفة)', keys: ['fixed_assets'], col: 0, indent: true },
  { label: 'يخصم: مجمع الإهلاك', keys: ['accumulated_depreciation'], col: 0, indent: true, neg: true },
  { label: 'صافي الأصول الثابتة', keys: ['net_fixed_assets', 'long_term_net', 'net'], col: 1, optional: true },
  { label: 'الأصول المتداولة', head: true },
  { label: 'المخزون', keys: ['inventory'], col: 0, indent: true },
  { label: 'العملاء والمقبوضات التجارية', keys: ['receivables'], col: 0, indent: true },
  { label: 'مدينون وأرصدة مدينة أخرى', keys: ['other_debtors'], col: 0, indent: true },
  { label: 'تأمينات لدى الغير', keys: ['deposits'], col: 0, indent: true },
  { label: 'النقدية بالصندوق والبنوك', keys: ['cash'], col: 0, indent: true },
  { label: 'إجمالي الأصول المتداولة', keys: ['total_current_assets', 'current_assets_total'], col: 1, optional: true },
  { label: 'الخصوم المتداولة', head: true },
  { label: 'دائنون وأرصدة دائنة أخرى', keys: ['creditors'], col: 0, indent: true },
  { label: 'بنوك سحب على المكشوف', keys: ['overdraft'], col: 0, indent: true },
  { label: 'أوراق الدفع', keys: ['notes_payable'], col: 0, indent: true },
  { label: 'الموردون', keys: ['suppliers'], col: 0, indent: true },
  { label: 'إجمالي الخصوم المتداولة', keys: ['total_current_liabilities', 'current_liabilities_total'], col: 1, neg: true, optional: true },
  { label: 'رأس المال العامل', keys: ['working_capital'], col: 1, strong: true },
  { label: 'حسابات ميزانية بدون بند', keys: ['unclassified'], col: 1, optional: true, hideZero: true },
  { label: 'إجمالي الاستثمار', keys: ['total_investment'], col: 1, strong: true },
  { label: 'ويُموَّل من: حقوق الملكية', head: true },
  { label: 'رأس المال', keys: ['capital'], col: 0, indent: true },
  { label: 'جاري الشركاء', keys: ['partners'], col: 0, indent: true },
  { label: 'الأرباح والخسائر', keys: ['profit_and_loss'], col: 0, indent: true },
  { label: 'إجمالي حقوق الملكية', keys: ['total_equity', 'equity_total'], col: 1, strong: true, optional: true },
]

function Position({ data }) {
  const check = pick(data, 'check')
  const off = check !== undefined && Number(check) !== 0
  return (
    <div className="space-y-3">
      <div data-tour="finance-gl-position-check">
        {off ? (
          <div className="rounded-lg border border-red-300 bg-red-50 text-red-700 px-3 py-2 text-sm font-medium">
            الميزانية غير متوازنة: إجمالي الاستثمار − حقوق الملكية = <span className="font-mono" dir="ltr">{money(check)}</span>
          </div>
        ) : check !== undefined && <div className="text-xs text-green-700">✓ إجمالي الاستثمار = حقوق الملكية</div>}
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto max-w-3xl">
        <TwoColumn lines={POSITION} data={data} />
      </div>
    </div>
  )
}

const EXPENSE_KEYS = ['general_expenses', 'selling_expenses', 'depreciation', 'operating_expenses', 'financing_expenses']

/**
 * Branch P&L: the server sends one column per branch (HQ first, total last), each with the
 * trading/P&L figures before allocation, `allocation` (line → HQ share moved in) and `after`.
 */
function Branches({ data }) {
  const cols = data?.columns || []
  if (!cols.length) return <EmptyState title="لا توجد أرقام للفروع في هذه الفترة" />
  const lines = TRADING.filter(l => l.keys)
  const cell = 'px-3 py-1.5 text-left font-mono tabular-nums'
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600 text-xs">
          <tr>
            <th className="text-right px-3 py-2">البند</th>
            {cols.map((c, i) => (
              <th key={i} className={`text-left px-3 py-2 whitespace-nowrap ${c.is_total ? 'bg-gray-100' : ''}`}>{c.label || c.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map(l => (
            <tr key={l.keys[0]} className={`border-t border-gray-100 ${l.strong ? 'font-bold bg-gray-50' : ''}`}>
              <td className="px-3 py-1.5 whitespace-nowrap">{l.label}</td>
              {cols.map((c, i) => <td key={i} className={cell} dir="ltr">{money(c[l.keys[0]], { blankZero: true })}</td>)}
            </tr>
          ))}
          {EXPENSE_KEYS.map(k => (
            <tr key={`alloc-${k}`} className="border-t border-gray-100 bg-amber-50/50 text-amber-900">
              <td className="px-3 py-1.5 whitespace-nowrap">توزيع {TRADING.find(l => l.keys?.[0] === k)?.label.replace('يخصم: ', '') || k}</td>
              {cols.map((c, i) => <td key={i} className={cell} dir="ltr">{money(c.allocation?.[k], { blankZero: true })}</td>)}
            </tr>
          ))}
          <tr className="border-t-2 border-gray-300 font-bold bg-gray-50">
            <td className="px-3 py-2 whitespace-nowrap">صافي الربح بعد التوزيع</td>
            {cols.map((c, i) => <td key={i} className={cell} dir="ltr">{money(c.after?.net_profit)}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

/** Comparison: [{year, empty, values: {...}, pct_of_sales: {...}}] — every figure from the server. */
function Comparison({ data }) {
  const years = listOf(data)
  if (!years.length) return <EmptyState title="لا توجد سنوات للمقارنة" />
  const lines = TRADING.filter(l => l.keys)
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600 text-xs">
          <tr>
            <th className="text-right px-3 py-2" rowSpan={2}>البند</th>
            {years.map(y => (
              <th key={y.year} className="text-center px-3 py-1 border-s border-gray-200" colSpan={2}>
                {y.year}{y.empty && <span className="ms-1 font-normal text-gray-400">(لا قيود)</span>}
              </th>
            ))}
          </tr>
          <tr>
            {years.map(y => (
              <Fragment key={y.year}>
                <th className="text-left px-3 py-1 border-s border-gray-200">القيمة</th>
                <th className="text-left px-3 py-1">% من المبيعات</th>
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map(l => (
            <tr key={l.keys[0]} className={`border-t border-gray-100 ${l.strong ? 'font-bold bg-gray-50' : ''}`}>
              <td className="px-3 py-1.5 whitespace-nowrap">{l.label}</td>
              {years.map(y => (
                <Fragment key={y.year}>
                  <td className="px-3 py-1.5 text-left font-mono tabular-nums border-s border-gray-100" dir="ltr">{money(y.values?.[l.keys[0]], { blankZero: true })}</td>
                  <td className="px-3 py-1.5 text-left font-mono tabular-nums text-gray-500" dir="ltr">{pct(y.pct_of_sales?.[l.keys[0]])}</td>
                </Fragment>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Server warnings (missing opening / closing stock, …) — shown above the statement, never hidden.
 *  trading / position: data.warnings; branches: the total column's; comparison: each year's. */
function warningsOf(tab, data) {
  if (!data) return []
  if (tab === 'branches') return (data.columns || []).find(c => c.is_total)?.warnings || []
  if (tab === 'comparison') return listOf(data).flatMap(y => (y.values?.warnings || []).map(w => `${y.year}: ${w}`))
  return data.warnings || []
}

function Warnings({ list }) {
  if (!list.length) return null
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2 space-y-1">
      {list.map((w, i) => <div key={i}>⚠ {w}</div>)}
    </div>
  )
}

export default function StatementsPage() {
  const perms = usePermissions('ledger')
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(([k]) => k === params.get('tab')) ? params.get('tab') : 'trading'
  useHelpTab(tab)
  const setTab = (k) => { const p = new URLSearchParams(params); p.set('tab', k); setParams(p, { replace: true }) }

  const thisYear = Number(todayIso().slice(0, 4))
  const [period, setPeriod] = useState(() => ({ kind: 'year', ...rangeOf('year') }))
  const [asOf, setAsOf] = useState(todayIso())
  const [years, setYears] = useState(`${thisYear - 1},${thisYear}`)
  const [stockDraft, setStockDraft] = useState('')
  const [stock, setStock] = useState('')          // applied on Enter / leaving the field
  const [err, setErr] = useState('')
  const stockParam = stock.trim() ? { closing_stock: stock.trim() } : {}

  const call = {
    trading:    { params: { from: period.from, to: period.to, ...stockParam }, get: glApi.statements, xlsx: glApi.statementsXlsx },
    position:   { params: { as_of: asOf, ...stockParam }, get: glApi.position, xlsx: glApi.positionXlsx },
    branches:   { params: { from: period.from, to: period.to }, get: glApi.branchPl, xlsx: glApi.branchPlXlsx },
    comparison: { params: { years: years.replace(/\s/g, '') }, get: glApi.comparison, xlsx: glApi.comparisonXlsx },
  }[tab]
  const q = useQuery({
    queryKey: ['gl', 'statements', tab, call.params],
    queryFn: () => call.get(call.params).then(r => r.data),
  })
  const exportXlsx = () => saveBlob(call.xlsx(call.params), `القوائم_المالية_${tab}.xlsx`)
    .then(() => setErr(''), (e) => setErr(errOf(e, 'تعذّر التصدير')))

  const title = tab === 'position' ? `قائمة المركز المالي في ${asOf}`
    : tab === 'comparison' ? `مقارنة السنوات ${years}`
    : `${TABS.find(([k]) => k === tab)[1]} من ${period.from} إلى ${period.to}`

  return (
    <div className="space-y-3" dir="rtl">
      <div className="flex gap-1 border-b border-gray-200 no-print" data-tour="finance-gl-statements-tabs">
        {TABS.map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
                  className={`px-4 py-2 text-sm border-b-2 -mb-px ${tab === k ? 'border-green-600 text-green-700 font-medium' : 'border-transparent text-gray-600 hover:text-gray-900'}`}>{l}</button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 no-print">
        {(tab === 'trading' || tab === 'branches') && <PeriodPicker value={period} onChange={setPeriod} />}
        {tab === 'position' && (
          <>
            <label className="text-xs text-gray-500">في تاريخ</label>
            <input type="date" className={inputCls} value={asOf} min="2026-01-01" onChange={e => setAsOf(e.target.value)} />
          </>
        )}
        {tab === 'comparison' && (
          <>
            <label className="text-xs text-gray-500">السنوات</label>
            <input className={`${inputCls} w-40`} dir="ltr" value={years} onChange={e => setYears(e.target.value)} placeholder="2025,2026" />
          </>
        )}
        {(tab === 'trading' || tab === 'position') && (
          <div className="flex items-center gap-1" data-tour="finance-gl-closing-stock">
            <label className="text-xs text-gray-500" htmlFor="gl-closing-stock">مخزون آخر المدة (اختياري)</label>
            <input id="gl-closing-stock" className={`${inputCls} w-36`} dir="ltr" inputMode="decimal"
                   placeholder="من القيود" value={stockDraft}
                   onChange={e => setStockDraft(e.target.value)}
                   onBlur={() => setStock(stockDraft)}
                   onKeyDown={e => { if (e.key === 'Enter') setStock(stockDraft) }} />
            {stock && (
              <button type="button" className="text-xs text-gray-500 hover:text-gray-800"
                      onClick={() => { setStock(''); setStockDraft('') }} title="الرجوع لقيود 5302">✕</button>
            )}
          </div>
        )}
        <div className="ms-auto flex gap-2">
          <button type="button" className={btnPlain} onClick={() => window.print()}>🖨️ طباعة</button>
          {perms.export && <button type="button" className={btnPlain} onClick={exportXlsx}>📥 Excel</button>}
        </div>
      </div>
      <ErrorBox>{err || (q.isError ? errOf(q.error, 'تعذّر تحميل القائمة') : '')}</ErrorBox>

      <h2 className="text-base font-bold text-gray-800">{title}</h2>
      {(tab === 'trading' || tab === 'position') && stock && q.data?.stock_basis === 'supplied' && (
        <div className="text-xs text-gray-500">مخزون آخر المدة من القيمة المُدخلة ({money(stock)}) بدل قيود 5302 — للعرض فقط، مبيتسجلش قيد.</div>
      )}
      <Warnings list={warningsOf(tab, q.data)} />
      {q.isLoading ? <SkeletonTable rows={10} cols={3} /> : q.isError ? null : (
        tab === 'trading' ? <Trading data={q.data} />
          : tab === 'position' ? <Position data={q.data} />
          : tab === 'branches' ? <Branches data={q.data} />
          : <Comparison data={q.data} />
      )}
    </div>
  )
}
