/**
 * ReconciliationPage — سداد فواتير الموردين (A/P–A/R reconciliation workbench)
 *
 * Read-only reconstruction + human-approved MIRROR allocations (doc 23).
 * Tabs: المقترحات (candidates) · الاستثناءات (exceptions) · الحصر (parties + ledger).
 * Approve/Reject write only to our PostgreSQL mirror — never to SOFTECH.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reconciliationApi } from '../api/client'
import { wildcardMatch } from '../utils/wildcard'
import useHelpTab from '../help/useHelpTab'

const money = (v) => Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Save an Excel/blob API response as a file. (Every export button called this, but it
// was never defined in this page → a silent ReferenceError after the download finished.)
function downloadBlob(data, filename) {
  const blob = data instanceof Blob ? data
    : new Blob([data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

// Run an export and turn any failure into a readable message (the server's JSON error
// arrives as a Blob because the request asks for responseType 'blob').
async function runExport(fetcher, filename) {
  try {
    const r = await fetcher()
    downloadBlob(r.data, filename)
    return null
  } catch (e) {
    let msg = 'تعذّر التصدير'
    const d = e?.response?.data
    if (d instanceof Blob) {
      try { msg = JSON.parse(await d.text()).detail || msg } catch { /* not JSON */ }
    } else if (d?.detail) {
      msg = d.detail
    }
    return `${msg}${e?.response?.status ? ` (${e.response.status})` : ''}`
  }
}
// «المتبقي (محسوب)» — calculated here, NOT a SOFTECH field (APInvoice.remaining_calc)
const CALC_TIP = 'حقل محسوب (ليس من SOFTECH): قيمة الفاتورة − المسدد في SOFTECH − المطابقات المعتمدة بانتظار الكتابة'
function Remaining({ value, after, returnCredit = 0, compact = false }) {
  const v = Number(value ?? 0)
  const a = after === undefined || after === null ? null : Number(after)
  const shown = a ?? v
  const rc = Number(returnCredit || 0)
  const netLine = rc > 0.005 && (
    <span className="block text-[10px] text-sky-800" title="حقل محسوب: المتبقي − الرصيد المفتوح للمرتجعات التي تشير لهذه الفاتورة">
      ↩ مرتجع مفتوح {money(rc)} → ƒ الصافي {Math.max(shown - rc, 0) <= 1 ? '✓ صفر' : money(shown - rc)}
    </span>
  )
  if (shown <= 1) {
    return <span className="text-green-700 text-xs whitespace-nowrap" title={CALC_TIP}>✓ مسددة بالكامل</span>
  }
  return (
    <span className="whitespace-nowrap" title={a !== null ? `${CALC_TIP} − هذا المقترح` : CALC_TIP}>
      <span className="text-[10px] text-sky-700 font-semibold ml-0.5">ƒ</span>
      <b className="text-amber-700">{money(shown)}</b>
      {!compact && a !== null && Math.abs(a - v) > 0.005 && <span className="block text-[10px] text-gray-400">الآن {money(v)}</span>}
      {netLine}
    </span>
  )
}

// what else touches this match, on the same line: other vouchers on the same invoice (⚔)
// and the invoice this voucher's reference names when it is a different one (🔎)
function RivalsLine({ c, full = false }) {
  const rv = c.rivals || []
  const no = c.names_other
  if (!rv.length && !no) return null
  const cls = full ? 'whitespace-normal' : 'truncate'
  return (
    <>
      {rv.length > 0 && (
        <div className={`text-[10px] text-red-700 ${cls}`} title={rv.map(r => `${r.voucher} — ${r.state}`).join('\n')}>
          ⚔ سند آخر على نفس الفاتورة: {rv.map(r => `${r.voucher} [${r.state}]`).join(' · ')}
        </div>
      )}
      {no && (
        <div className={`text-[10px] text-indigo-700 ${cls}`} title={`السند يسمي الفاتورة ${no.invoice} (${no.docdate}, ${no.value}) — ${no.state}`}>
          🔎 السند يسمي فاتورة أخرى {no.invoice} ({no.docdate}, {money(no.value)}) — {no.state}
        </div>
      )}
    </>
  )
}

// what a voucher is bound to: refunds (↩, matched NET) and correction-chain partners (⛓)
function VoucherBindings({ pay, full = false }) {
  if (!pay) return null
  const items = [pay.bind_note, pay.chain_partners].filter(Boolean)
  if (!items.length) return null
  return items.map((t, i) => (
    <div key={i} className={`text-[10px] ${t.startsWith('⛓') ? 'text-orange-700' : 'text-violet-700'} ${full ? 'whitespace-normal' : 'truncate'}`} title={t}>{t}</div>
  ))
}

// SOFTECH entry timestamp (trans_time, Cairo local) → 'YYYY-MM-DD HH:MM:SS'
const stamp = (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '')

// document date + the moment it was entered in SOFTECH (time only when same day)
function When({ date, at }) {
  const t = stamp(at)
  const sameDay = t && date && t.startsWith(String(date))
  return (
    <div className="leading-tight">
      <div>{date || (t ? t.slice(0, 10) : '—')}</div>
      {t && <div className="text-[10px] text-gray-500 tabular-nums" title={`وقت الإدخال في SOFTECH: ${t}`}>
        {sameDay ? `🕒 ${t.slice(11)}` : `🕒 أُدخل ${t}`}</div>}
    </div>
  )
}

const CONF = {
  high:     { label: 'ثقة عالية',  cls: 'bg-green-100 text-green-800 border-green-300' },
  medium:   { label: 'ثقة متوسطة', cls: 'bg-amber-100 text-amber-800 border-amber-300' },
  low:      { label: 'ثقة منخفضة', cls: 'bg-gray-100 text-gray-600 border-gray-300' },
  conflict: { label: 'تعارض',      cls: 'bg-red-100 text-red-700 border-red-300' },
}
const OUTCOME = {
  exact:       { icon: '✓', cls: 'text-green-600' },
  approximate: { icon: '≈', cls: 'text-amber-600' },
  conflict:    { icon: '⚠', cls: 'text-orange-600' },
  mismatch:    { icon: '✕', cls: 'text-gray-400' },
}
const EXC_SEV = {
  info:     'bg-sky-50 text-sky-700 border-sky-200',
  warning:  'bg-amber-50 text-amber-700 border-amber-200',
  critical: 'bg-red-50 text-red-700 border-red-200',
}

// ── KPI tiles ─────────────────────────────────────────────────────────────────
function Kpis({ d }) {
  if (!d) return null
  const tiles = [
    { label: 'الفواتير', value: d.invoices?.count, sub: `${money(d.invoices?.value)} ج.م` },
    { label: 'السندات', value: d.payments?.count, sub: `${money(d.payments?.value)} ج.م` },
    { label: 'سندات بلا ربط', value: d.payments?.unallocated_count, sub: `${money(d.payments?.unallocated_value)} ج.م`, warn: true },
    { label: 'مقترحات', value: d.candidates?.total, sub: `عالية: ${d.candidates?.by_confidence?.high || 0}` },
    { label: 'قيمة مقترحة', value: money(d.candidates?.proposed_value), sub: 'قابلة للاعتماد', money: true },
    { label: 'استثناءات', value: d.exceptions?.total, sub: `حرجة: ${d.exceptions?.by_severity?.critical || 0}`, warn: (d.exceptions?.total || 0) > 0 },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
      {tiles.map((t, i) => (
        <div key={i} className={`rounded-xl border p-3 ${t.warn ? 'border-amber-300 bg-amber-50' : 'border-gray-200 bg-white'}`}>
          <div className="text-xs text-gray-500">{t.label}</div>
          <div className={`text-xl font-bold ${t.money ? 'text-[#022871]' : 'text-gray-800'}`}>{t.value ?? 0}</div>
          <div className="text-[11px] text-gray-400 mt-0.5">{t.sub}</div>
        </div>
      ))}
    </div>
  )
}

// ── invoice item lines — loaded from SOFTECH only when the button is pressed ─
function InvoiceLines({ invoiceId, compact = false }) {
  const [open, setOpen] = useState(false)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['recon', 'invoice-lines', invoiceId],
    queryFn: () => reconciliationApi.invoiceLines(invoiceId).then(r => r.data),
    enabled: open && !!invoiceId,
    staleTime: 10 * 60 * 1000,
  })
  if (!invoiceId) return null
  return (
    <div className={compact ? '' : 'mt-1'}>
      <button onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
              className="text-[11px] px-2 py-0.5 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-50">
        {open ? '▲ إخفاء الأصناف' : '📦 أصناف الفاتورة'}
      </button>
      {open && (
        <div className="mt-1 border border-gray-200 rounded bg-white overflow-x-auto" onClick={e => e.stopPropagation()}>
          {isLoading && <div className="text-[11px] text-gray-400 p-2">جارٍ القراءة من SOFTECH…</div>}
          {isError && <div className="text-[11px] text-red-600 p-2">{error?.response?.data?.detail || 'تعذّر تحميل الأصناف'}</div>}
          {data && (
            <table className="w-full text-[11px]">
              <thead className="bg-gray-50 text-gray-500">
                <tr>{['الكود', 'الصنف', 'الكمية', 'السعر', 'خصم %', 'الإجمالي', 'الصلاحية', ''].map(h => <th key={h} className="p-1 text-right font-medium">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.lines.map((l, i) => (
                  <tr key={i} className={l.is_free ? 'bg-green-50' : ''}>
                    <td className="p-1 text-gray-400">{l.itemcode}</td>
                    <td className="p-1">{l.name || '—'}</td>
                    <td className="p-1">{Number(l.qty)}</td>
                    <td className="p-1">{money(l.price)}</td>
                    <td className="p-1">{Number(l.discount_pct).toFixed(2)}</td>
                    <td className="p-1 font-medium">{money(l.total)}</td>
                    <td className="p-1 text-gray-500">{l.expiry || '—'}</td>
                    <td className="p-1">{l.is_free ? <span className="text-green-700">مجاني</span> : l.returned_from ? <span className="text-orange-700">من فاتورة {l.returned_from}</span> : ''}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-gray-50">
                  <td colSpan={5} className="p-1 text-gray-500">{data.count} صنف · قيمة المستند {money(data.doc_value)}</td>
                  <td className="p-1 font-bold">{money(data.lines_total)}</td>
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

// ── evidence chips ──────────────────────────────────────────────────────────
function Evidence({ ev }) {
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {ev.map((e) => {
        const o = OUTCOME[e.outcome] || OUTCOME.mismatch
        return (
          <span key={e.id} className="inline-flex items-center gap-1 text-xs bg-gray-50 border border-gray-200 rounded px-2 py-0.5" title={e.detail}>
            <span className={o.cls}>{o.icon}</span>
            <span className="text-gray-600">{e.signal_display}</span>
            {Number(e.contribution) > 0 && <span className="text-gray-400">+{Number(e.contribution)}</span>}
          </span>
        )
      })}
    </div>
  )
}

// ── the review grid: one column layout shared by the header and every row ────
const GRID_COLS = 'grid grid-cols-[26px_104px_minmax(130px,1fr)_minmax(150px,1.3fr)_86px_96px_104px_minmax(150px,1.3fr)_86px_96px_104px_14px] items-center gap-2'
const GRID_MIN = 'min-w-[1290px]'

// sortable column header: first click = largest/newest first, second = reverse
function SortTh({ label, field, ordering, setOrdering, className = '' }) {
  if (!field) return <div className={`text-gray-500 font-medium ${className}`}>{label}</div>
  const on = ordering === field || ordering === `-${field}`
  const next = ordering === `-${field}` ? field : `-${field}`
  return (
    <button type="button" onClick={() => setOrdering(next)} title={`ترتيب حسب ${label}`} aria-label={`ترتيب حسب ${label}`}
            className={`text-right font-medium flex items-center gap-1 ${on ? 'text-[#022871]' : 'text-gray-500 hover:text-[#022871]'} ${className}`}>
      {label}<span className="text-[10px]">{on ? (ordering.startsWith('-') ? '▼' : '▲') : '↕'}</span>
    </button>
  )
}

function GridHeader({ ordering, setOrdering, allChecked, someChecked, onToggleAll, plain = false }) {
  const s = (label, field) => <SortTh label={label} field={plain ? null : field} ordering={ordering} setOrdering={setOrdering} />
  return (
    <div className={`${GRID_COLS} ${GRID_MIN} px-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-lg sticky top-0 z-10`}>
      {plain ? <span /> : (
        <input type="checkbox" checked={allChecked} ref={el => { if (el) el.indeterminate = !allChecked && someChecked }}
               onChange={onToggleAll} title="تحديد كل صفوف الصفحة" />
      )}
      {s('الثقة', 'confidence_score')}
      {s('المورد', 'party__name')}
      {s('الفاتورة', 'invoice__docnumber')}
      {s('تاريخ الفاتورة', 'invoice__docdate')}
      {s('قيمة الفاتورة', 'invoice__doc_value')}
      <div className="text-gray-500 font-medium" title={`${CALC_TIP} − هذا المقترح (إن لم يُعتمد بعد)`}>
        <span className="text-sky-700 font-semibold">ƒ</span> المتبقي (محسوب)
      </div>
      {s('السند', null)}
      {s('تاريخ السند', 'payment__voucher_date')}
      {s('مبلغ السند', 'payment__amount')}
      {s('المبلغ المقترح', 'proposed_amount')}
      <span />
    </div>
  )
}

// ── a single candidate review row (the workbench unit) ────────────────────────
function CandidateRow({ c, onApprove, onReject, onWrite, onGroup, onReverse, busy, writeState, selected, onToggle }) {
  const [open, setOpen] = useState(false)
  const conf = CONF[c.confidence_class] || CONF.low
  const inv = c.invoice_detail, pay = c.payment_detail
  const wr = writeState?.[c.allocation?.id]
  const grouped = c.group_key && c.strategy !== 'pairwise'
  const writtenReview = c.status === 'written' && c.decision_note?.startsWith('مكتوب — يحتاج مراجعة')
  const held = c.status === 'proposed' && c.decision_note?.startsWith('يحتاج مراجعة')
  return (
    <div className={`border rounded-lg bg-white ${selected ? 'border-[#022871] ring-1 ring-[#022871]/30' : 'border-gray-200'} ${GRID_MIN}`}>
      <div className={`${GRID_COLS} px-3 py-2 cursor-pointer hover:bg-gray-50 text-sm`} onClick={() => setOpen(!open)}>
        <input type="checkbox" checked={!!selected} onClick={e => e.stopPropagation()} onChange={() => onToggle?.(c)} />
        <div className="min-w-0">
          <span className={`text-[11px] font-semibold border rounded-full px-1.5 py-0.5 whitespace-nowrap ${conf.cls}`}>{Number(c.confidence_score)}% · {conf.label}</span>
          {c.strategy && c.strategy !== 'pairwise' && <div className="text-[10px] text-sky-700 truncate mt-0.5" title={c.strategy_display}>{c.strategy_display}</div>}
        </div>
        <div className="min-w-0 text-xs text-[#022871] truncate" title={`${c.party_code} · ${c.party_name}`}>{c.party_code} · {c.party_name}</div>
        <div className="min-w-0">
          <div className="truncate"><b>{inv?.branchcode}/{inv?.docnumber}</b> <span className="text-[11px] text-gray-400">{inv?.branch_name}</span></div>
          {held && <div className="text-[10px] text-orange-700 truncate" title={c.decision_note}>⚠ {c.decision_note.replace('يحتاج مراجعة: ', '')}</div>}
          {writtenReview && <div className="text-[10px] text-amber-700 truncate" title={c.decision_note}>⚠ {c.decision_note.replace('مكتوب — يحتاج مراجعة: ', '')}</div>}
          {!held && !writtenReview && inv?.comments && <div className="text-[10px] text-amber-700 truncate" title={inv.comments}>📝 {inv.comments}</div>}
        </div>
        <div className="text-xs text-gray-600"><When date={inv?.docdate} at={inv?.trans_time} /></div>
        <div className="text-xs">{money(inv?.doc_value)}</div>
        <div className="text-xs">
          <Remaining value={inv?.remaining_calc} returnCredit={inv?.open_return_credit}
                     after={c.status === 'proposed' ? Number(inv?.remaining_calc ?? 0) - Number(c.proposed_amount || 0) : undefined} />
        </div>
        <div className="min-w-0">
          <div className="truncate"><b>{pay?.branchcode}/{pay?.cheqsno}</b> <span className="text-[11px] text-gray-400">{pay?.user_name || pay?.usercode || ''}</span></div>
          {c.duplicate_of?.length > 0
            ? <div className="text-[10px] text-red-600 truncate">⚠ سند مكرر محتمل مع {c.duplicate_of.join('، ')}</div>
            : pay?.note && <div className="text-[10px] text-gray-400 truncate" title={pay.note}>«{pay.note}»</div>}
          <VoucherBindings pay={pay} />
          <RivalsLine c={c} />
        </div>
        <div className="text-xs text-gray-600"><When date={pay?.voucher_date} at={pay?.trans_time} /></div>
        <div className="text-xs">{money(pay?.amount)}</div>
        <div className="font-bold text-[#022871] whitespace-nowrap">{money(c.proposed_amount)}</div>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div className="border-t border-gray-100 p-3 bg-gray-50/50">
          <div className="text-xs text-gray-600 mb-2">
            المورد: <b className="text-[#022871]">{c.party_code} · {c.party_name}</b>
            {c.decided_by_name && <span className="mr-3">· اعتمد: {c.decided_by_name}{c.decided_at ? ` (${c.decided_at.slice(0, 10)})` : ''}</span>}
          </div>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div className="bg-white rounded border border-gray-200 p-2 space-y-0.5">
              <div className="font-semibold text-gray-700 mb-1">الفاتورة {inv?.doccode}/{inv?.docnumber}</div>
              <div>تاريخ الفاتورة: {inv?.docdate}</div>
              <div>وقت الإدخال في SOFTECH: <span className="tabular-nums">{stamp(inv?.trans_time) || '—'}</span></div>
              <div>الفرع: {inv?.branchcode} · {inv?.branch_name || '—'}</div>
              <div>المستخدم: {inv?.user_name || '—'}{inv?.usercode ? ` (${inv.usercode})` : ''}</div>
              <div>القيمة: {money(inv?.doc_value)} · المسدد في SOFTECH: {money(inv?.doc_value_pay)}</div>
              <div className="rounded bg-sky-50 border border-sky-200 px-1.5 py-0.5 my-0.5">
                <span className="text-sky-800 font-semibold">ƒ المتبقي (محسوب)</span> الآن: <Remaining value={inv?.remaining_calc} compact />
                {c.status === 'proposed' && <> · بعد هذا المقترح: <Remaining value={Number(inv?.remaining_calc ?? 0) - Number(c.proposed_amount || 0)} compact /></>}
                <div className="text-[10px] text-gray-500">{CALC_TIP}</div>
              </div>
              {inv?.returns_bound?.length > 0 && (
                <div className="rounded bg-sky-50/60 border border-sky-200 px-1.5 py-0.5 my-0.5">
                  <div className="text-sky-800 font-semibold">↩ مرتجعات تشير لهذه الفاتورة</div>
                  {inv.returns_bound.map(r => (
                    <div key={r.id}>مرتجع {r.label} ({r.docdate}) بقيمة {money(r.amount)} · المفتوح منه {Number(r.open) > 0 ? money(r.open) : '✓ خُصم/استُرد'}</div>
                  ))}
                  {Number(inv.open_return_credit) > 0 && <div>ƒ الصافي بعد المرتجع: <b>{money(inv.net_remaining)}</b></div>}
                </div>
              )}
              {inv?.bound_receipts?.length > 0 && (
                <div className="rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 my-0.5 text-amber-900">
                  🔗 مقبوضات تشير لهذه الفاتورة (تحتاج تحديد: استرداد أم خصم): {inv.bound_receipts.join(' · ')}
                </div>
              )}
              <div>مستند المورد: {inv?.docnumber2 || '—'}</div>
              <div>ملاحظات الفاتورة: <span className="text-amber-800 whitespace-pre-wrap">{inv?.comments || '—'}</span></div>
              <InvoiceLines invoiceId={inv?.id} />
            </div>
            <div className="bg-white rounded border border-gray-200 p-2 space-y-0.5">
              <div className="font-semibold text-gray-700 mb-1">السند {pay?.branchcode}/{pay?.cheqsno}</div>
              <div>تاريخ السند (السداد): {pay?.voucher_date}</div>
              <div>وقت الإدخال في SOFTECH: <span className="tabular-nums">{stamp(pay?.trans_time) || '—'}</span></div>
              <div>الفرع: {pay?.branchcode} · {pay?.branch_name || '—'}</div>
              <div>المستخدم: {pay?.user_name || '—'}{pay?.usercode ? ` (${pay.usercode})` : ''}</div>
              <div>النوع: {pay?.cheqtype === '10' ? 'مقبوضات' : 'مدفوعات'}</div>
              <div>المبلغ: {money(pay?.amount)}
                {Number(pay?.refunded_amount) > 0 && <> · مسترد منه {money(pay.refunded_amount)} · <b>الصافي {money(pay.net_amount)}</b></>}
                {' '}· متاح: {money(pay?.unallocated_amount)}</div>
              <VoucherBindings pay={pay} full />
              <RivalsLine c={c} full />
              <div>المسلسل: {pay?.cheqsno} · المسلسل الداخلي: {pay?.cheqno || '—'}</div>
              <div>ملاحظات السند: <span className="text-amber-800 whitespace-pre-wrap">{pay?.note || '—'}</span></div>
              {pay?.chain_note && <div className="mt-1 rounded bg-orange-50 border border-orange-200 text-orange-800 px-1.5 py-0.5">⛓ {pay.chain_note}</div>}
              {c.payment_flags?.map((f, i) => (
                <div key={i} className="mt-1 rounded bg-red-50 border border-red-200 text-red-700 px-1.5 py-0.5">⚠ {f.label}: {f.detail}</div>
              ))}
              <div>رقم الإيصال: {pay?.ourcheqsno || '—'}</div>
            </div>
          </div>
          <Evidence ev={c.evidence || []} />
          {c.status === 'proposed' ? (
            <div className="flex gap-2 mt-3 flex-wrap">
              <button disabled={busy} onClick={() => onApprove(c)} className="px-3 py-1.5 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">✓ اعتماد {money(c.proposed_amount)}</button>
              <button disabled={busy} onClick={() => onReject(c)} className="px-3 py-1.5 text-sm rounded-lg bg-white border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-50">✕ رفض</button>
              {grouped && (
                <>
                  <span className="text-xs text-gray-400 self-center mr-2">المجموعة {c.group_key}:</span>
                  <button disabled={busy} onClick={() => onGroup(c, 'approve')} className="px-3 py-1.5 text-sm rounded-lg bg-green-50 border border-green-300 text-green-700 hover:bg-green-100 disabled:opacity-50">✓ اعتماد المجموعة كاملة</button>
                  <button disabled={busy} onClick={() => onGroup(c, 'reject')} className="px-3 py-1.5 text-sm rounded-lg bg-white border border-red-200 text-red-500 hover:bg-red-50 disabled:opacity-50">✕ رفض المجموعة</button>
                </>
              )}
            </div>
          ) : (
            <div className="mt-3">
              <div className="text-xs text-gray-500 mb-1">الحالة: {c.status_display}
                {c.allocation && <span className="mr-2">· تخصيص #{c.allocation.id} ({c.allocation.origin})</span>}
              </div>
              {c.status === 'approved' && c.allocation && (
                <>
                  <button disabled={busy} onClick={() => onWrite(c)}
                          className="px-3 py-1.5 text-sm rounded-lg bg-[#022871] text-white hover:bg-[#03399e] disabled:opacity-50">
                    🖊 كتابة في SOFTECH
                  </button>
                  {wr && (
                    <div className={`mt-2 rounded-lg border p-2 text-xs ${wr.written ? 'border-green-300 bg-green-50' : wr.error ? 'border-red-300 bg-red-50' : 'border-sky-200 bg-sky-50'}`}>
                      {wr.error ? <span className="text-red-700">{wr.error}</span>
                        : wr.written ? <span className="text-green-800">✓ تمت الكتابة في SOFTECH{wr.already_present ? ' (موجود مسبقًا)' : ''}</span>
                        : <span className="text-sky-800">تشغيل تجريبي (الكتابة الفعلية معطّلة بالعلم AP_RECONCILE_WRITER_ENABLED)</span>}
                      {wr.plan?.statements && (
                        <div className="mt-1 space-y-0.5 font-mono text-[10px] text-gray-600" dir="ltr">
                          {wr.plan.statements.filter(s => s.kind === 'write').map((s, i) => (
                            <div key={i} className="truncate" title={s.sql}>{s.label}: {s.sql}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
              {c.status === 'written' && c.allocation && (
                <button disabled={busy} onClick={() => onReverse(c)}
                        className="px-3 py-1.5 text-sm rounded-lg bg-white border border-orange-300 text-orange-700 hover:bg-orange-50 disabled:opacity-50">
                  ↩ عكس من SOFTECH (مطابقة خاطئة)
                </button>
              )}
              {wr?.reversed && <div className="mt-2 text-xs text-orange-800">تم العكس في SOFTECH — الفاتورة عادت مفتوحة ورُفض المقترح.</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── multi-select action bar (appears once rows are ticked) ────────────────────
const SEL_LABEL = { approve: 'اعتُمد', reject: 'رُفض', review: 'أُرسل للمراجعة', reverse: 'عُكس من SOFTECH' }

function SelectionBar({ sel, clear, done }) {
  const [note, setNote] = useState('')
  const [confirm, setConfirm] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const rows = [...sel.values()]
  if (!rows.length && !msg) return null
  const total = rows.reduce((s, r) => s + Number(r.proposed_amount || 0), 0)
  const count = (st) => rows.filter(r => r.status === st).length
  const nProp = count('proposed'), nAppr = count('approved'), nWrit = count('written'), nRej = count('rejected')
  const nHeld = rows.filter(r => r.status === 'proposed' && r.decision_note?.startsWith('يحتاج مراجعة')).length
  const run = async (action) => {
    // SOFTECH writes/reversals: second click confirms (inline, no popup)
    if ((action === 'write' || action === 'reverse') && confirm !== action) { setConfirm(action); return }
    setConfirm(''); setBusy(true); setMsg(null)
    try {
      if (action === 'write') {
        const cids = rows.filter(r => r.status === 'approved').map(r => r.id)
        const t = { written: 0, skipped: 0, reasons: {} }
        const skip = []
        let remaining = Infinity, guard = 0
        while (remaining > 0 && guard < 20) {
          const { data: r } = await reconciliationApi.bulkWrite({ candidate_ids: cids, skip_ids: skip })
          t.written += r.written + r.already_present
          t.skipped += r.skipped
          skip.push(...(r.skipped_ids || []))
          Object.entries(r.reasons || {}).forEach(([k, v]) => { t.reasons[k] = (t.reasons[k] || 0) + v })
          remaining = r.remaining
          guard += 1
          if (r.written + r.already_present + r.skipped === 0) break
        }
        setMsg({ ok: true, text: `كُتب في SOFTECH ${t.written}${t.skipped ? ` · مُتخطّى ${t.skipped}` : ''}`, errors: t.reasons })
      } else {
        const ids = action === 'reverse' ? rows.filter(r => r.status === 'written').map(r => r.id) : rows.map(r => r.id)
        const agg = { done: 0, failed: 0, held_included: 0, errors: {} }
        for (let i = 0; i < ids.length; i += 200) {
          const { data: r } = await reconciliationApi.selectionAction({ action, ids: ids.slice(i, i + 200), note })
          agg.done += r.done || 0
          agg.failed += r.failed || 0
          agg.held_included += r.held_included || 0
          Object.entries(r.errors || {}).forEach(([k, v]) => { agg.errors[k] = (agg.errors[k] || 0) + v })
        }
        setMsg({ ok: true, errors: agg.errors,
                 text: `${SEL_LABEL[action]}: ${agg.done}${agg.failed ? ` · تعذّر ${agg.failed}` : ''}${agg.held_included ? ` (منها ${agg.held_included} كانت محجوزة للمراجعة — اعتمدتها أنت)` : ''}` })
      }
      clear()
      done()
    } catch (e) {
      setMsg({ ok: false, text: e.response?.data?.detail || 'فشل الإجراء' })
    } finally {
      setBusy(false)
    }
  }
  const btn = (action, label, cls, show = true) => show && (
    <button key={action} disabled={busy} onClick={() => run(action)}
            className={`px-3 py-1 rounded-lg text-sm disabled:opacity-50 ${confirm === action ? 'bg-red-600 text-white' : cls}`}>
      {confirm === action ? `اضغط مرة أخرى للتأكيد — ${label}` : label}
    </button>
  )
  return (
    <div className="sticky top-0 z-20 mb-2 rounded-xl border border-[#022871]/30 bg-sky-50 p-2 shadow-sm">
      {rows.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap text-sm">
          <span className="font-semibold text-[#022871]">محدد {rows.length}</span>
          <span className="text-gray-600">· إجمالي المقترح {money(total)} ج.م</span>
          {nHeld > 0 && <span className="text-[11px] text-orange-700">({nHeld} محجوزة للمراجعة — راجعها قبل الاعتماد)</span>}
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="ملاحظة (اختياري)"
                 className="border border-gray-200 rounded px-2 py-0.5 text-xs w-48 bg-white" />
          <span className="mr-auto" />
          {btn('approve', `✓ اعتماد المحدد (${nProp})`, 'bg-green-600 text-white hover:bg-green-700', nProp > 0)}
          {btn('reject', `✕ رفض المحدد (${nProp})`, 'bg-white border border-red-300 text-red-600 hover:bg-red-50', nProp > 0)}
          {btn('write', `🖊 كتابة المحدد في SOFTECH (${nAppr})`, 'bg-[#022871] text-white hover:bg-[#03399e]', nAppr > 0)}
          {btn('reverse', `↩ عكس المحدد من SOFTECH (${nWrit})`, 'bg-white border border-orange-300 text-orange-700 hover:bg-orange-50', nWrit > 0)}
          {btn('review', nRej && !nProp && !nAppr && !nWrit ? '↺ إعادة فتح للمراجعة' : '⚠ إرسال للمراجعة', 'bg-white border border-amber-400 text-amber-800 hover:bg-amber-50')}
          <button onClick={() => { clear(); setConfirm('') }} className="text-xs text-gray-500 hover:text-red-600">✕ إلغاء التحديد</button>
        </div>
      )}
      {msg && (
        <div className={`text-sm mt-1 ${msg.ok ? 'text-green-800' : 'text-red-700'}`}>
          {msg.text}
          {msg.errors && Object.keys(msg.errors).length > 0 && (
            <div className="text-xs text-gray-600">{Object.entries(msg.errors).map(([k, v]) => `${k} ×${v}`).join(' · ')}</div>
          )}
          <button onClick={() => setMsg(null)} className="text-xs text-gray-400 mr-2">إخفاء</button>
        </div>
      )}
    </div>
  )
}

// ── grouped review: every voucher proposed for one invoice (or every invoice for
//    one voucher) together, with what is still owed and an «exceeds» warning ────
const ORIGIN_LBL = { softech: 'SOFTECH', written: 'مكتوب', approved: 'معتمد' }

function GroupCard({ g, by, sel, toggle, rowProps, onResolve, resolving }) {
  const o = g.object || {}
  const excess = Number(g.excess || 0)
  const remaining = Number(g.remaining || 0)
  const picked = g.candidates.filter(c => sel.has(c.id))
  const pickedSum = picked.reduce((s, c) => s + Number(c.proposed_amount || 0), 0)
  const pickable = g.candidates.filter(c => c.status === 'proposed')
  const others = pickable.filter(c => !sel.has(c.id))
  const over = pickedSum > Math.max(remaining, 0) + 0.01
  const allPicked = pickable.length > 0 && pickable.every(c => sel.has(c.id))
  return (
    <div className={`rounded-xl border-2 p-2 space-y-1.5 ${excess > 0 ? 'border-red-300 bg-red-50/30' : 'border-gray-200 bg-gray-50/40'}`}>
      <div className="flex items-start gap-2 flex-wrap text-sm px-1">
        <input type="checkbox" className="mt-1" checked={allPicked} disabled={!pickable.length}
               onChange={() => pickable.forEach(c => { if (allPicked === sel.has(c.id)) toggle(c) })} title="تحديد كل مقترحات المجموعة" />
        {by === 'invoice' ? (
          <div className="min-w-0">
            <div>🧾 <b>فاتورة {o.branchcode}/{o.docnumber}</b>
              <span className="text-xs text-gray-500 mx-1">تاريخ الفاتورة {o.docdate} · 🕒 {stamp(o.trans_time) || '—'} · {o.branch_name} · {o.user_name || o.usercode || '—'}</span>
              <span className="text-xs text-[#022871]">{o.party_code} · {o.party_name}</span></div>
            {o.comments && <div className="text-[11px] text-amber-700">📝 {o.comments}</div>}
            {o.returns_bound?.length > 0 && (
              <div className="text-[11px] text-sky-800">↩ مرتجعات تشير لها: {o.returns_bound.map(r => `${r.label} (${money(r.amount)}${Number(r.open) > 0 ? `، مفتوح ${money(r.open)}` : ''})`).join(' · ')}</div>
            )}
            {o.bound_receipts?.length > 0 && <div className="text-[11px] text-amber-800">🔗 مقبوضات تشير لها (تحتاج تحديد): {o.bound_receipts.join(' · ')}</div>}
          </div>
        ) : (
          <div className="min-w-0">
            <div>💳 <b>سند {o.branchcode}/{o.cheqsno}</b>
              <span className="text-xs text-gray-500 mx-1">تاريخ السند {o.voucher_date} · 🕒 {stamp(o.trans_time) || '—'} · {o.branch_name} · {o.user_name || o.usercode || '—'} · داخلي {o.cheqno || '—'}</span>
              <span className="text-xs text-[#022871]">{o.party_code} · {o.party_name}</span></div>
            {o.note && <div className="text-[11px] text-gray-500">«{o.note}»</div>}
            <VoucherBindings pay={o} full />
          </div>
        )}
        <div className="mr-auto flex gap-3 text-xs text-gray-600 flex-wrap">
          {by === 'invoice'
            ? <><span>القيمة <b>{money(o.doc_value)}</b></span><span>مسدد في SOFTECH {money(o.doc_value_pay)}</span></>
            : <span>مبلغ السند <b>{money(o.amount)}</b></span>}
          {by === 'invoice'
            ? <span title={CALC_TIP}><span className="text-sky-700 font-semibold">ƒ</span> المتبقي (محسوب) <Remaining value={remaining} returnCredit={o.open_return_credit} compact /></span>
            : <span>المتاح من السند{Number(o.refunded_amount) > 0 ? ' (الصافي بعد الاسترداد)' : ''} <b className="text-[#022871]">{money(remaining)}</b></span>}
          <span>مجموع المقترح <b>{money(g.pending)}</b> ({g.n} {by === 'invoice' ? 'سند' : 'فاتورة'})</span>
        </div>
      </div>
      {excess > 0 && (
        <div className="text-xs rounded-lg bg-red-100 border border-red-200 text-red-800 px-2 py-1">
          ⚠ {by === 'invoice' ? 'السندات المقترحة معًا تتجاوز المتبقي على الفاتورة' : 'الفواتير المقترحة معًا تتجاوز المتاح من السند'} بـ <b>{money(excess)}</b> ج.م — حدّد ما تعتمده فقط.
        </div>
      )}
      {g.links?.length > 0 && (
        <div className="text-[11px] text-gray-600 flex flex-wrap gap-1 px-1">
          <span>مربوط حاليًا:</span>
          {g.links.map((l, i) => (
            <span key={i} className="rounded-full bg-white border border-gray-200 px-2">
              {ORIGIN_LBL[l.origin] || l.origin} · {by === 'invoice'
                ? `سند ${l.payment} ${stamp(l.voucher_time) || l.voucher_date}`
                : `فاتورة ${l.invoice} ${stamp(l.invoice_time) || l.docdate}`} · {money(l.amount)}
            </span>
          ))}
        </div>
      )}
      <div className="overflow-x-auto space-y-1">
        {g.candidates.map(c => <CandidateRow key={c.id} c={c} selected={sel.has(c.id)} onToggle={toggle} {...rowProps} />)}
      </div>
      {picked.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap text-xs px-1">
          <span className={over ? 'text-red-700 font-semibold' : 'text-gray-600'}>
            المحدد هنا {picked.length} · {money(pickedSum)} من {money(remaining)} {over && '— يتجاوز المتبقي، لن يُعتمد الزائد'}
          </span>
          {others.length > 0 && picked.some(c => c.status === 'proposed') && (
            <button disabled={resolving} onClick={() => onResolve(picked.filter(c => c.status === 'proposed').map(c => c.id), others.map(c => c.id))}
                    className="px-3 py-1 rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
              ✓ اعتماد المحدد ({picked.length}) ورفض الباقي ({others.length})
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── tabs ──────────────────────────────────────────────────────────────────────
function CandidatesTab({ scope }) {
  const qc = useQueryClient()
  const [conf, setConf] = useState('')
  const [strategy, setStrategy] = useState('')
  const [status, setStatus] = useState('proposed')
  const [writeState, setWriteState] = useState({})
  const [bulkResult, setBulkResult] = useState(null)
  const [writeResult, setWriteResult] = useState(null)
  const [ordering, setOrdering] = useState('-confidence_score')
  const [pageSize, setPageSize] = useState(50)
  const [view, setView] = useState('list')          // list | invoice | payment
  const [only, setOnly] = useState('multi')         // grouped: multi | over | all
  const [gorder, setGorder] = useState('-excess')
  const [sel, setSel] = useState(() => new Map())   // candidate id → row
  const held = status === 'held'
  const wreview = status === 'written_review'
  const baseParams = { ...scope, ...(held ? { held: 1 } : wreview ? { written_review: 1 } : { status }), ...(conf ? { confidence_class: conf } : {}), ...(strategy ? { strategy } : {}) }
  const [page, setPage] = useState(1)
  const filterKey = JSON.stringify({ baseParams, view, only, gorder, ordering, pageSize })
  const [lastKey, setLastKey] = useState(filterKey)
  if (lastKey !== filterKey) { setLastKey(filterKey); setPage(1); setSel(new Map()) }
  const grouped = view !== 'list'
  const params = grouped
    ? { ...baseParams, by: view, only, gorder, page, page_size: 20 }
    : { ...baseParams, page, ordering, page_size: pageSize }
  const { data, isLoading } = useQuery({
    queryKey: ['recon', grouped ? 'groups' : 'candidates', params],
    queryFn: () => (grouped ? reconciliationApi.candidateGroups(params) : reconciliationApi.candidates(params)).then(r => r.data),
  })
  const toggle = (c) => setSel(m => { const n = new Map(m); n.has(c.id) ? n.delete(c.id) : n.set(c.id, c); return n })
  const done = () => qc.invalidateQueries({ queryKey: ['recon'] })
  const resolve = useMutation({
    mutationFn: ({ approve: ids, reject }) => reconciliationApi.selectionAction({ action: 'approve', ids, reject_ids: reject }),
    onSuccess: (r) => {
      const d = r.data
      setBulkResult({ approved: d.done, skipped: d.failed, rejectedRest: d.rejected, errors: d.errors })
      setSel(new Map())
      done()
    },
    onError: (e) => setBulkResult({ error: e.response?.data?.detail || 'فشل الإجراء' }),
  })
  const approve = useMutation({ mutationFn: (c) => reconciliationApi.approve(c.id), onSuccess: done })
  const reject = useMutation({ mutationFn: (c) => reconciliationApi.reject(c.id), onSuccess: done })
  const group = useMutation({
    mutationFn: ({ c, action }) => action === 'approve'
      ? reconciliationApi.bulkApprove({ group: c.group_key })
      : reconciliationApi.bulkReject({ group: c.group_key, note: 'رفض مجموعة بعد المراجعة' }),
    onSuccess: done,
  })
  const write = useMutation({
    mutationFn: (c) => reconciliationApi.writeSoftech(c.allocation.id).then(r => ({ id: c.allocation.id, data: r.data })),
    onSuccess: ({ id, data }) => { setWriteState(s => ({ ...s, [id]: data })); done() },
    onError: (e, c) => setWriteState(s => ({ ...s, [c.allocation.id]: { error: e.response?.data?.detail || 'فشل الكتابة' } })),
  })
  const reverse = useMutation({
    mutationFn: (c) => reconciliationApi.reverseSoftech(c.allocation.id, 'مطابقة خاطئة بعد المراجعة')
      .then(r => ({ id: c.allocation.id, data: r.data })),
    onSuccess: ({ id, data }) => { setWriteState(s => ({ ...s, [id]: data })); done() },
    onError: (e, c) => setWriteState(s => ({ ...s, [c.allocation.id]: { error: e.response?.data?.detail || 'فشل العكس' } })),
  })
  // Bulk-approve every HIGH-confidence proposed candidate in scope (bounded per
  // call; drain `remaining`). Mirror allocations only.
  const bulk = useMutation({
    mutationFn: async () => {
      const totals = { approved: 0, skipped: 0, held: 0 }
      let remaining = Infinity, guard = 0
      while (remaining > 0 && guard < 200) {
        const { data: r } = await reconciliationApi.bulkApprove({ ...scope, confidence_class: 'high', ...(strategy ? { strategy } : {}) })
        totals.approved += r.approved
        totals.skipped += r.skipped
        totals.held = r.held_for_review ?? totals.held
        remaining = r.remaining
        guard += 1
        if (r.approved === 0) break
      }
      return totals
    },
    onSuccess: (totals) => { setBulkResult(totals); done() },
    onError: (e) => setBulkResult({ error: e.response?.data?.detail || 'فشل الاعتماد الجماعي' }),
  })
  // Write every APPROVED allocation in scope to SOFTECH, 200 per call, looping on
  // `remaining`; rows the live guards refuse are skipped (never retried in-loop).
  const bulkWrite = useMutation({
    mutationFn: async () => {
      const t = { written: 0, already_present: 0, skipped: 0, value: 0, reasons: {} }
      const skip = []
      let remaining = Infinity, guard = 0
      while (remaining > 0 && guard < 300) {
        const { data: r } = await reconciliationApi.bulkWrite({ ...scope, ...(conf ? { confidence_class: conf } : {}), ...(strategy ? { strategy } : {}), skip_ids: skip })
        t.written += r.written; t.already_present += r.already_present; t.skipped += r.skipped
        t.value += Number(r.written_value || 0)
        skip.push(...(r.skipped_ids || []))
        Object.entries(r.reasons || {}).forEach(([k, v]) => { t.reasons[k] = (t.reasons[k] || 0) + v })
        remaining = r.remaining
        guard += 1
        setWriteResult({ ...t, running: true })
        if (r.written + r.already_present + r.skipped === 0) break
      }
      return t
    },
    onSuccess: (t) => { setWriteResult(t); done() },
    onError: (e) => setWriteResult({ error: e.response?.data?.detail || 'فشل الكتابة الجماعية' }),
  })
  const [exportError, setExportError] = useState(null)
  const [exportingReview, setExportingReview] = useState(false)
  const exportReview = async () => {
    setExportingReview(true)
    setExportError(await runExport(() => reconciliationApi.reviewExport(scope), 'reconciliation_review.xlsx'))
    setExportingReview(false)
  }
  const busy = approve.isPending || reject.isPending || write.isPending || bulk.isPending || group.isPending || reverse.isPending || bulkWrite.isPending || resolve.isPending
  const rows = data?.results || []
  const rowProps = { busy, writeState, onApprove: approve.mutate, onReject: reject.mutate, onWrite: write.mutate,
                     onGroup: (cand, action) => group.mutate({ c: cand, action }), onReverse: reverse.mutate }
  const pageChecked = !grouped && rows.length > 0 && rows.every(c => sel.has(c.id))
  const pageSome = !grouped && rows.some(c => sel.has(c.id))
  const toggleAll = () => setSel(m => {
    const n = new Map(m)
    rows.forEach(c => (pageChecked ? n.delete(c.id) : n.set(c.id, c)))
    return n
  })
  const GROUP_ORDERS = [['-excess', 'الأكبر تجاوزًا'], ['-n', 'الأكثر عددًا'], ['-pending', 'الأعلى مقترحًا'],
                        ['-date', 'الأحدث تاريخًا'], ['date', 'الأقدم تاريخًا'], ['-value', 'الأعلى قيمة'], ['value', 'الأقل قيمة']]
  const STATUSES = [['held', '⚠ يحتاج مراجعة'], ['written_review', '⚠ مكتوبة — تحتاج مراجعة'], ['proposed', 'مقترحة'], ['approved', 'معتمدة'], ['written', 'مكتوبة'], ['rejected', 'مرفوضة']]
  const STRATS = [['', 'كل الطرق'], ['pairwise', 'مباشرة'], ['exact_unique', 'مبلغ فريد'], ['same_amount_nearest', 'نفس المبلغ-الأقرب'], ['subset_window', 'مجموع متتالٍ'],
                  ['subset_oldest', 'بالأقدم'], ['multi_ref', 'عدة فواتير'], ['installments', 'أقساط'], ['fifo_residual', 'توزيع المتبقي']]
  return (
    <div>
      <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
        <span className="text-gray-500">الحالة:</span>
        {STATUSES.map(([k, l]) => (
          <button key={k} onClick={() => setStatus(k)} className={`px-2 py-1 rounded-lg border ${status === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
        <button onClick={exportReview} disabled={exportingReview} className="mr-auto px-3 py-1 rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50">
          {exportingReview ? 'جارٍ التجهيز…' : '⬇ تصدير المتوسطة والمنخفضة للمراجعة'}
        </button>
        {exportError && <span className="text-red-600 text-xs w-full">{exportError}</span>}
      </div>
      <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
        <span className="text-gray-500">الثقة:</span>
        {['', 'high', 'medium', 'low', 'conflict'].map(k => (
          <button key={k} onClick={() => setConf(k)} className={`px-2 py-1 rounded-lg border ${conf === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>
            {k === '' ? 'الكل' : CONF[k].label}
          </button>
        ))}
        <span className="text-gray-400 mr-auto">{grouped ? '' : (data?.count ?? 0)}</span>
        {status === 'proposed' && (
          <button disabled={busy} onClick={() => { setBulkResult(null); bulk.mutate() }}
                  className="px-3 py-1 rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 text-sm">
            {bulk.isPending ? 'جارٍ الاعتماد…' : '✓ اعتماد كل الثقة العالية'}
          </button>
        )}
        {status === 'approved' && (
          <button disabled={busy} onClick={() => { setWriteResult(null); bulkWrite.mutate() }}
                  className="px-3 py-1 rounded-lg bg-[#022871] text-white hover:bg-[#03399e] disabled:opacity-50 text-sm">
            {bulkWrite.isPending ? 'جارٍ الكتابة في SOFTECH…' : '🖊 كتابة كل المعتمد في SOFTECH'}
          </button>
        )}
      </div>
      <div className="flex items-center gap-1 mb-3 text-xs flex-wrap">
        <span className="text-gray-500 ml-1">طريقة المطابقة:</span>
        {STRATS.map(([k, l]) => (
          <button key={k} onClick={() => setStrategy(k)} className={`px-2 py-0.5 rounded-full border ${strategy === k ? 'bg-sky-700 text-white border-sky-700' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1 mb-3 text-xs flex-wrap">
        <span className="text-gray-500 ml-1">العرض:</span>
        {[['list', '☰ جدول'], ['invoice', '🧾 مجمّع حسب الفاتورة'], ['payment', '💳 مجمّع حسب السند']].map(([k, l]) => (
          <button key={k} onClick={() => setView(k)} className={`px-2 py-0.5 rounded-lg border ${view === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
        {grouped ? (
          <>
            <span className="text-gray-300 mx-1">|</span>
            {[['multi', 'المتعددة فقط'], ['over', '⚠ تتجاوز القيمة فقط'], ['all', 'الكل']].map(([k, l]) => (
              <button key={k} onClick={() => setOnly(k)} className={`px-2 py-0.5 rounded-full border ${only === k ? 'bg-sky-700 text-white border-sky-700' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
            ))}
            <span className="text-gray-500 mr-2">ترتيب المجموعات:</span>
            <select value={gorder} onChange={e => setGorder(e.target.value)} className="border border-gray-200 rounded px-1 py-0.5 bg-white">
              {GROUP_ORDERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            {data?.stats && (
              <span className="mr-auto text-gray-600">
                {data.stats.groups} مجموعة · {data.stats.candidates} مقترح
                {Number(data.stats.over) > 0 && <span className="text-red-700"> · {data.stats.over} تتجاوز القيمة ({money(data.stats.excess_total)} ج.م)</span>}
              </span>
            )}
          </>
        ) : (
          <span className="mr-auto flex items-center gap-1 text-gray-500">
            صفوف الصفحة
            <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))} className="border border-gray-200 rounded px-1 py-0.5 bg-white">
              {[50, 100, 200, 500].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </span>
        )}
      </div>
      {status === 'proposed' && (
        <div className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-lg p-2 mb-2">
          «اعتماد كل الثقة العالية» يُنشئ التخصيصات لكل المقترحات عالية الثقة في هذا النطاق ما عدا المحجوزة للمراجعة (⚠ يحتاج مراجعة) — الكتابة في SOFTECH خطوة منفصلة من تبويب «معتمدة». المقترحات المتوسطة والمنخفضة تحتاج مراجعة: اعتمد أو ارفض كل مقترح أو المجموعة كاملة.
        </div>
      )}
      {bulkResult && (
        <div className={`text-sm rounded-lg p-2 mb-2 border ${bulkResult.error ? 'border-red-300 bg-red-50 text-red-700' : 'border-green-300 bg-green-50 text-green-800'}`}>
          {bulkResult.error
            ? bulkResult.error
            : `تم اعتماد ${bulkResult.approved} مقترح${bulkResult.rejectedRest ? ` · رُفض الباقي ${bulkResult.rejectedRest}` : ''}${bulkResult.skipped ? ` · تخطّي ${bulkResult.skipped} (سعة/تعارض)` : ''}${bulkResult.held ? ` · ${bulkResult.held} عالية الثقة محجوزة للمراجعة (⚠ يحتاج مراجعة) — تُعتمد فرديًا أو كمجموعة بعد المراجعة` : ''}.`}
          {bulkResult.errors && Object.keys(bulkResult.errors).length > 0 && (
            <div className="text-xs text-gray-600">{Object.entries(bulkResult.errors).map(([k, v]) => `${k} ×${v}`).join(' · ')}</div>
          )}
        </div>
      )}
      {status === 'approved' && !writeResult && <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2 mb-2">الكتابة في SOFTECH فعلية (سداد في الرئيسي): تُسجَّل كل مطابقة في chequestrans وتُحدَّث الفاتورة. أي مطابقة خاطئة يمكن عكسها من تبويب «مكتوبة».</div>}
      {writeResult && (
        <div className={`text-sm rounded-lg p-2 mb-2 border ${writeResult.error ? 'border-red-300 bg-red-50 text-red-700' : 'border-sky-300 bg-sky-50 text-sky-900'}`}>
          {writeResult.error ? writeResult.error : (
            <>
              {writeResult.running ? 'جارٍ الكتابة… ' : 'انتهت الكتابة: '}
              كُتب {writeResult.written} ({money(writeResult.value)} ج.م)
              {writeResult.already_present ? ` · موجود مسبقًا ${writeResult.already_present}` : ''}
              {writeResult.skipped ? ` · مُتخطّى ${writeResult.skipped}` : ''}
              {Object.keys(writeResult.reasons || {}).length > 0 && (
                <div className="text-xs mt-1 text-gray-600">{Object.entries(writeResult.reasons).map(([k, v]) => `${k} ×${v}`).join(' · ')}</div>
              )}
            </>
          )}
        </div>
      )}
      {(approve.isError || reject.isError || group.isError) && <div className="text-red-600 text-sm mb-2">{(approve.error || reject.error || group.error)?.response?.data?.detail || 'فشل الإجراء'}</div>}
      <SelectionBar sel={sel} clear={() => setSel(new Map())} done={done} />
      {isLoading ? <div className="text-gray-400 py-8 text-center">جارٍ التحميل…</div> : grouped ? (
        <div className="space-y-3">
          {rows.length === 0 && <div className="text-gray-400 py-8 text-center">لا توجد مجموعات في هذا النطاق</div>}
          <Pager page={page} setPage={setPage} count={data?.count} size={20} />
          <div className="overflow-x-auto">
            <div className={`${GRID_MIN} space-y-3`}>
              <GridHeader plain />
              {rows.map(g => (
                <GroupCard key={g.id} g={g} by={data.by} sel={sel} toggle={toggle} rowProps={rowProps}
                           resolving={resolve.isPending}
                           onResolve={(ids, rej) => { setBulkResult(null); resolve.mutate({ approve: ids, reject: rej }) }} />
              ))}
            </div>
          </div>
          <Pager page={page} setPage={setPage} count={data?.count} size={20} />
        </div>
      ) : (
        <div className="space-y-2">
          {rows.length === 0 && <div className="text-gray-400 py-8 text-center">لا يوجد في هذا النطاق</div>}
          <Pager page={page} setPage={setPage} count={data?.count} size={pageSize} />
          <div className="overflow-x-auto">
            <div className={`${GRID_MIN} space-y-1`}>
              <GridHeader ordering={ordering} setOrdering={setOrdering} allChecked={pageChecked}
                          someChecked={pageSome} onToggleAll={toggleAll} />
              {rows.map(c => <CandidateRow key={c.id} c={c} selected={sel.has(c.id)} onToggle={toggle} {...rowProps} />)}
            </div>
          </div>
          <Pager page={page} setPage={setPage} count={data?.count} size={pageSize} />
        </div>
      )}
    </div>
  )
}

const EXC_TYPES = [['', 'كل الأنواع'], ['cancelled_reversed', 'سند مُلغى مربوط'], ['supplier_mismatch', 'تصحيح لمورد آخر'],
                   ['paid_returned', 'مسددة رغم إرجاعها'], ['open_return', 'مرتجع مستحق'],
                   ['receipt_on_invoice', 'مقبوضات تشير لفاتورة (تحديد)'], ['misallocation', 'ربط خاطئ'],
                   ['duplicate_payment', 'سند مكرر'], ['duplicate_invoice', 'فاتورة مكررة'], ['overpayment', 'دفع زائد'],
                   ['orphan_payment', 'سند بلا فاتورة'], ['unpaid_old', 'فاتورة قديمة'], ['anomaly', 'شذوذ']]

function ExceptionsTab({ scope }) {
  const [etype, setEtype] = useState('')
  const [sev, setSev] = useState('')
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('-created_at')
  const base = { ...scope, status: 'open', ordering, ...(etype ? { exception_type: etype } : {}), ...(sev ? { severity: sev } : {}) }
  const key = JSON.stringify(base)
  const [lastKey, setLastKey] = useState(key)
  if (lastKey !== key) { setLastKey(key); setPage(1) }
  const params = { ...base, page }
  const { data, isLoading } = useQuery({
    queryKey: ['recon', 'exceptions', params],
    queryFn: () => reconciliationApi.exceptions(params).then(r => r.data),
  })
  const rows = data?.results || []
  return (
    <div>
      <div className="flex items-center gap-1 mb-2 text-xs flex-wrap">
        <span className="text-gray-500 ml-1">النوع:</span>
        {EXC_TYPES.map(([k, l]) => (
          <button key={k} onClick={() => setEtype(k)} className={`px-2 py-0.5 rounded-full border ${etype === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1 mb-3 text-xs flex-wrap">
        <span className="text-gray-500 ml-1">الخطورة:</span>
        {[['', 'الكل'], ['critical', 'حرج'], ['warning', 'تحذير'], ['info', 'معلومة']].map(([k, l]) => (
          <button key={k} onClick={() => setSev(k)} className={`px-2 py-0.5 rounded-full border ${sev === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
        <span className="text-gray-500 mr-3">ترتيب:</span>
        <select value={ordering} onChange={e => setOrdering(e.target.value)} className="border border-gray-200 rounded px-1 py-0.5 bg-white">
          {[['-created_at', 'الأحدث رصدًا'], ['-invoice__doc_value', 'قيمة الفاتورة ↓'], ['invoice__doc_value', 'قيمة الفاتورة ↑'],
            ['-invoice__docdate', 'تاريخ الفاتورة ↓'], ['invoice__docdate', 'تاريخ الفاتورة ↑'],
            ['-payment__amount', 'مبلغ السند ↓'], ['payment__amount', 'مبلغ السند ↑'],
            ['-payment__voucher_date', 'تاريخ السند ↓'], ['payment__voucher_date', 'تاريخ السند ↑'],
            ['party__name', 'المورد'], ['severity', 'الخطورة'], ['exception_type', 'النوع']].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="text-gray-400 mr-auto">{data?.count ?? 0}</span>
      </div>
      {isLoading ? <div className="text-gray-400 py-8 text-center">جارٍ التحميل…</div> : (
        <div className="space-y-2">
          {rows.length === 0 && <div className="text-gray-400 py-8 text-center">لا توجد استثناءات مفتوحة في هذا النطاق</div>}
          {rows.map(e => (
            <div key={e.id} className={`border rounded-lg p-3 text-sm ${EXC_SEV[e.severity] || EXC_SEV.warning}`}>
              <div className="flex items-center gap-2">
                <span className="font-semibold">{e.exception_type_display}</span>
                <span className="text-xs opacity-70">{e.severity_display}</span>
                <span className="text-xs mr-auto font-medium">{e.party_code} · {e.party_name}</span>
              </div>
              <div className="text-xs mt-1 opacity-90">{e.detail}</div>
              {(e.invoice_detail || e.payment_detail) && (
                <div className="text-[11px] mt-1 opacity-75 flex flex-wrap gap-x-4">
                  {e.invoice_detail && (
                    <span>فاتورة {e.invoice_detail.docnumber} · ƒ المتبقي (محسوب) {Number(e.invoice_detail.remaining_calc ?? 0) <= 1 ? '✓ مسددة' : money(e.invoice_detail.remaining_calc)} · تاريخ الفاتورة {e.invoice_detail.docdate} · 🕒 {stamp(e.invoice_detail.trans_time) || '—'} · فرع {e.invoice_detail.branchcode} {e.invoice_detail.branch_name} · {e.invoice_detail.user_name || e.invoice_detail.usercode || '—'}
                      {e.invoice_detail.comments ? ` · 📝 ${e.invoice_detail.comments}` : ''}</span>
                  )}
                  {e.payment_detail && (
                    <span>سند {e.payment_detail.branchcode}/{e.payment_detail.cheqsno} (داخلي {e.payment_detail.cheqno || '—'} · إيصال {e.payment_detail.ourcheqsno || '—'}) · تاريخ السند {e.payment_detail.voucher_date} · 🕒 {stamp(e.payment_detail.trans_time) || '—'} · {e.payment_detail.branch_name} · {e.payment_detail.user_name || e.payment_detail.usercode || '—'}
                      {e.payment_detail.note ? ` · «${e.payment_detail.note}»` : ''}</span>
                  )}
                </div>
              )}
              {e.invoice_detail && <InvoiceLines invoiceId={e.invoice_detail.id} />}
            </div>
          ))}
          <Pager page={page} setPage={setPage} count={data?.count} />
        </div>
      )}
    </div>
  )
}

function LedgerDrawer({ personcode, onClose }) {
  const { data } = useQuery({
    queryKey: ['recon', 'timeline', personcode],
    queryFn: () => reconciliationApi.partyTimeline(personcode).then(r => r.data),
    enabled: !!personcode,
  })
  const eq = data?.equation
  return (
    <div className="fixed inset-0 bg-black/40 flex justify-start z-50" dir="rtl" onClick={onClose}>
      <div className="bg-white w-full max-w-2xl h-full overflow-y-auto p-5 shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-bold text-lg text-[#022871]">حصر: {data?.party?.name || personcode}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        {eq && (
          <div className="grid grid-cols-2 gap-2 text-sm mb-4">
            {[
              ['رصيد افتتاحي', eq.opening_balance], ['مشتريات', eq.purchases],
              ['مرتجعات', eq.returns], ['مدفوعات', eq.payments],
              ['المتوقع (نموذجنا)', eq.expected_closing], ['رصيد SOFTECH', eq.softech_balance],
            ].map(([l, v]) => (
              <div key={l} className="bg-gray-50 rounded p-2 border border-gray-100">
                <div className="text-xs text-gray-500">{l}</div>
                <div className="font-semibold">{money(v)}</div>
              </div>
            ))}
            {eq.snapshot_balance != null && (
              <div className="rounded p-2 border border-sky-200 bg-sky-50">
                <div className="text-xs text-sky-700">رصيد SOFTECH اللحظي (من الحركات)</div>
                <div className="font-semibold text-sky-800">{money(eq.snapshot_balance)}</div>
              </div>
            )}
            {eq.snapshot_vs_softech != null && (
              <div className="rounded p-2 border border-green-200 bg-green-50">
                <div className="text-xs text-green-700">تطابق اللقطة مع السجل (≈0)</div>
                <div className="font-semibold text-green-800">{money(eq.snapshot_vs_softech)}</div>
              </div>
            )}
            {eq.model_vs_snapshot != null && (
              <div className="col-span-2 rounded p-2 border border-amber-200 bg-amber-50">
                <div className="text-xs text-amber-700">فرق الترحيل (رصيد SOFTECH يتحرك بأكثر من قيمة المستندات — قيود لا تظهر في المشتريات/المدفوعات)</div>
                <div className="font-bold text-amber-800">{money(eq.model_vs_snapshot)} ج.م</div>
              </div>
            )}
            <div className="col-span-2 rounded p-2 border border-gray-200 bg-gray-50">
              <div className="text-xs text-gray-500">إجمالي الفرق (SOFTECH − نموذجنا)</div>
              <div className="font-bold text-gray-700">{money(eq.unexplained_variance)} ج.م</div>
            </div>
          </div>
        )}
        <div className="text-xs text-gray-500 mb-1 flex justify-between">
          <span>الحركات ({data?.event_count || 0})</span>
          <span className="text-gray-400">الرصيد = رصيد SOFTECH بعد الحركة</span>
        </div>
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-[55vh] overflow-y-auto">
          {(data?.events || []).map((e, i) => (
            <div key={i} className="flex items-center gap-2 px-3 py-1.5 text-xs">
              <span className={`w-14 ${e.kind === 'payment' ? 'text-red-600' : e.kind === 'return' ? 'text-orange-600' : 'text-green-700'}`}>
                {e.kind === 'payment' ? 'سند' : e.kind === 'return' ? 'مرتجع' : 'شراء'}
              </span>
              <span className="text-gray-500 w-24">{e.date}</span>
              <span className="flex-1 text-gray-700 truncate" title={`${e.branch || ''} — ${e.user || ''}`}>
                {e.ref} {e.note ? `«${e.note}»` : ''}
                <span className="text-gray-400 mr-2">{e.branch} · {e.user}</span>
              </span>
              <span className={Number(e.delta) < 0 ? 'text-red-600' : 'text-green-700'}>{money(e.delta)}</span>
              <span className="w-24 text-left font-semibold text-sky-700" title="رصيد SOFTECH بعد الحركة">{money(e.softech_balance_after)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function PartiesTab({ scope }) {
  const [pc, setPc] = useState(null)
  const [q, setQ] = useState('')
  const [ordering, setOrdering] = useState('-softech_balance')
  const [page, setPage] = useState(1)
  const base = { ...scope, ...(q ? { search: q } : {}), ordering }
  const key = JSON.stringify(base)
  const [lastKey, setLastKey] = useState(key)
  if (lastKey !== key) { setLastKey(key); setPage(1) }
  const { data, isLoading } = useQuery({
    queryKey: ['recon', 'parties', base, page],
    queryFn: () => reconciliationApi.parties({ ...base, page }).then(r => r.data),
  })
  const rows = data?.results || []
  return (
    <div>
      <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالكود أو الاسم…"
               className="border border-gray-200 rounded-lg px-3 py-1 w-64" />
        <span className="text-gray-500">ترتيب:</span>
        {[['-softech_balance', 'الأعلى رصيدًا'], ['softech_balance', 'الأقل رصيدًا'], ['softech_personcode', 'الكود']].map(([k, l]) => (
          <button key={k} onClick={() => setOrdering(k)} className={`px-2 py-1 rounded-lg border ${ordering === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
        <span className="text-gray-400 mr-auto">{data?.count ?? 0} مورد</span>
      </div>
      {isLoading ? <div className="text-gray-400 py-8 text-center">جارٍ التحميل…</div> : (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100">
          {rows.map(p => (
            <div key={p.id} className="flex items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 cursor-pointer" onClick={() => setPc(p.softech_personcode)}>
              <span className="text-gray-400 w-16">{p.softech_personcode}</span>
              <span className="flex-1 text-gray-700">{p.name || '—'}</span>
              <span className="text-xs text-gray-500">{p.party_type_display}</span>
              <span className="font-semibold text-[#022871]">{money(p.softech_balance)}</span>
              <span className="text-gray-300">حصر ›</span>
            </div>
          ))}
          {rows.length === 0 && <div className="text-gray-400 py-6 text-center">لا يوجد</div>}
        </div>
      )}
      <Pager page={page} setPage={setPage} count={data?.count} />
      {pc && <LedgerDrawer personcode={pc} onClose={() => setPc(null)} />}
    </div>
  )
}

// ── incomplete payments: invoices paid part-way + part-used vouchers ─────────
function PartialPanel({ scope }) {
  const [exporting, setExporting] = useState(false)
  const [invOrd, setInvOrd] = useState('')
  const [payOrd, setPayOrd] = useState('')
  const params = { ...scope, ...(invOrd ? { inv_ordering: invOrd } : {}), ...(payOrd ? { pay_ordering: payOrd } : {}) }
  const { data, isLoading } = useQuery({
    queryKey: ['recon', 'partial', params],
    queryFn: () => reconciliationApi.partial(params).then(r => r.data),
  })
  const th = (cols, ord, setOrd) => cols.map(([h, f]) => (
    <th key={h} className="p-2 text-right font-medium"><SortTh label={h} field={f} ordering={ord} setOrdering={setOrd} /></th>
  ))
  const t = data?.totals
  const [exportError, setExportError] = useState(null)
  const exportXlsx = async () => {
    setExporting(true)
    setExportError(await runExport(() => reconciliationApi.partialExport(scope), 'partial_payments.xlsx'))
    setExporting(false)
  }
  if (isLoading) return <div className="text-gray-400 py-8 text-center">جارٍ الحساب…</div>
  if (!data) return null
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
          <div className="text-xs text-gray-500">فواتير مسددة جزئياً</div>
          <div className="text-lg font-bold text-[#022871]">{t.invoices}</div>
          <div className="text-[11px] text-gray-500">مسدد {money(t.invoices_paid)} · متبقٍّ {money(t.invoices_remaining)}</div>
        </div>
        <div className="rounded-xl border border-red-200 bg-red-50 p-3">
          <div className="text-xs text-gray-500">المتبقي على الفواتير الجزئية</div>
          <div className="text-lg font-bold text-red-700">{money(t.invoices_remaining)}</div>
        </div>
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-3">
          <div className="text-xs text-gray-500">سندات لم تُستكمل (مال بلا فاتورة)</div>
          <div className="text-lg font-bold text-[#022871]">{t.vouchers}</div>
          <div className="text-[11px] text-gray-500">متبقٍّ {money(t.vouchers_unallocated)}</div>
        </div>
        <button onClick={exportXlsx} disabled={exporting}
                className="rounded-xl border border-[#022871] text-[#022871] bg-white hover:bg-sky-50 p-3 text-sm font-semibold disabled:opacity-50">
          {exporting ? 'جارٍ التجهيز…' : '⬇ تصدير المدفوعات غير المكتملة'}
        </button>
      </div>
      {exportError && <div className="text-red-600 text-sm">{exportError}</div>}
      <div className="border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>{th([['المورد', 'supplier'], ['الفرع'], ['الفاتورة'], ['تاريخ الفاتورة', 'docdate'], ['المستخدم'], ['القيمة', 'doc_value'],
                     ['المسدد', 'paid'], ['ƒ المتبقي (محسوب)', 'remaining'], ['%'], ['السندات التي سددتها [المستخدم]'], ['ملاحظات'], ['الأصناف']], invOrd, setInvOrd)}</tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.invoices.map(r => (
              <tr key={`${r.branchcode}-${r.docnumber}-${r.personcode}`}>
                <td className="p-2">{r.personcode} · {r.supplier}</td>
                <td className="p-2">{r.branchcode} · {r.branch_name}</td>
                <td className="p-2">{r.docnumber}</td>
                <td className="p-2 whitespace-nowrap"><When date={r.docdate} at={r.entered_at} /></td>
                <td className="p-2">{r.user_name || r.usercode || '—'}</td>
                <td className="p-2">{money(r.doc_value)}</td>
                <td className="p-2 text-green-700">{money(r.paid)}</td>
                <td className="p-2 font-semibold text-red-700">{money(r.remaining)}</td>
                <td className="p-2">{r.paid_pct}%</td>
                <td className="p-2 text-gray-600">{r.vouchers}</td>
                <td className="p-2 text-amber-800 max-w-48 truncate" title={r.comments}>{r.comments || '—'}</td>
                <td className="p-2"><InvoiceLines invoiceId={r.invoice_id} compact /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-sm font-semibold text-gray-700">سندات لم تُستكمل — جزء من مبلغها لم يُربط بفاتورة</div>
      <div className="border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>{th([['المورد', 'supplier'], ['الفرع'], ['المسلسل'], ['المسلسل الداخلي'], ['رقم الإيصال'], ['تاريخ السند', 'voucher_date'],
                     ['المستخدم'], ['المبلغ', 'amount'], ['المخصص', 'allocated'], ['المتبقي', 'unallocated'], ['ملاحظات السند'], ['الفواتير']], payOrd, setPayOrd)}</tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.vouchers.map(r => (
              <tr key={`${r.voucher}-${r.personcode}`}>
                <td className="p-2">{r.personcode} · {r.supplier}</td>
                <td className="p-2">{r.branchcode} · {r.branch_name}</td>
                <td className="p-2">{r.cheqsno}</td>
                <td className="p-2">{r.cheqno || '—'}</td>
                <td className="p-2">{r.ourcheqsno || '—'}</td>
                <td className="p-2 whitespace-nowrap"><When date={r.voucher_date} at={r.entered_at} /></td>
                <td className="p-2">{r.user_name || r.usercode || '—'}</td>
                <td className="p-2">{money(r.amount)}</td>
                <td className="p-2 text-green-700">{money(r.allocated)}</td>
                <td className="p-2 font-semibold text-sky-800">{money(r.unallocated)}</td>
                <td className="p-2 text-gray-500">{r.note}</td>
                <td className="p-2 text-gray-600">{r.invoices}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── unpaid invoices for the finance department ───────────────────────────────
function UnpaidTab({ scope }) {
  const [status, setStatus] = useState('uncovered')
  const [exporting, setExporting] = useState(false)
  const [ordering, setOrdering] = useState('')
  const params = { ...scope, status, ...(ordering ? { ordering } : {}) }
  const { data, isLoading, isError } = useQuery({
    queryKey: ['recon', 'unpaid', params],
    queryFn: () => reconciliationApi.unpaid(params).then(r => r.data),
    enabled: status !== 'partial',
  })
  const t = data?.totals
  const [exportError, setExportError] = useState(null)
  const exportXlsx = async () => {
    setExporting(true)
    setExportError(await runExport(() => reconciliationApi.unpaidExport(scope), 'unpaid_supplier_invoices.xlsx'))
    setExporting(false)
  }
  const exportReturns = async () => {
    setExporting(true)
    setExportError(await runExport(() => reconciliationApi.returnsChainsExport(scope), 'returns_and_correction_chains.xlsx'))
    setExporting(false)
  }
  const FILTERS = [['uncovered', 'غير مسددة فعلياً (بلا سند)'], ['review', 'تحت المراجعة'],
                   ['all', 'كل المفتوح في SOFTECH'], ['partial', 'مسددة جزئياً / سندات لم تُستكمل']]
  if (status === 'partial') {
    return (
      <div className="space-y-3">
        <div className="flex gap-2 text-sm flex-wrap">
          {FILTERS.map(([k, l]) => (
            <button key={k} onClick={() => setStatus(k)} className={`px-2 py-1 rounded-lg border ${status === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
          ))}
        </div>
        <PartialPanel scope={scope} />
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {t && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            ['المفتوح في SOFTECH', t.open_in_softech, `${t.invoices} فاتورة · ${t.suppliers} مورد`, ''],
            ['مغطى بمطابقة', t.matched, 'معتمد / بانتظار الكتابة', 'border-green-200 bg-green-50'],
            ['تحت المراجعة', t.under_review, 'مطابقات متوسطة/منخفضة', 'border-amber-200 bg-amber-50'],
            ['غير مسدد فعلياً', t.unpaid_uncovered, `${t.unpaid_invoices} فاتورة بلا أي سند`, 'border-red-200 bg-red-50'],
            ['مرتجعات مستحقة على المورد', t.open_returns, 'لم تُخصم ولم تُسترد', 'border-sky-200 bg-sky-50'],
            ['صافي المستحق للموردين', t.net_payable, 'غير مسدد − مرتجعات مستحقة', 'border-[#022871] bg-white'],
          ].map(([l, v, sub, cls]) => (
            <div key={l} className={`rounded-xl border p-3 ${cls || 'border-gray-200 bg-white'}`}>
              <div className="text-xs text-gray-500">{l}</div>
              <div className="text-lg font-bold text-[#022871]">{money(v)}</div>
              <div className="text-[11px] text-gray-400">{sub}</div>
            </div>
          ))}
          <button onClick={exportXlsx} disabled={exporting}
                  className="rounded-xl border border-[#022871] text-[#022871] bg-white hover:bg-sky-50 p-3 text-sm font-semibold disabled:opacity-50">
            {exporting ? 'جارٍ التجهيز…' : '⬇ تصدير Excel للإدارة المالية'}
          </button>
          <button onClick={exportReturns} disabled={exporting}
                  className="rounded-xl border border-sky-700 text-sky-800 bg-white hover:bg-sky-50 p-3 text-sm font-semibold disabled:opacity-50">
            ⬇ المرتجعات وسلاسل التصحيح (مدفوعات/مقبوضات)
          </button>
        </div>
      )}
      {exportError && <div className="text-red-600 text-sm">{exportError}</div>}
      <div className="flex gap-2 text-sm flex-wrap">
        {FILTERS.map(([k, l]) => (
          <button key={k} onClick={() => setStatus(k)} className={`px-2 py-1 rounded-lg border ${status === k ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>{l}</button>
        ))}
        <span className="text-gray-400 mr-auto self-center">{data?.row_count ?? 0} فاتورة</span>
      </div>
      {isLoading && <div className="text-gray-400 py-8 text-center">جارٍ الحساب…</div>}
      {isError && <div className="text-red-600 text-sm">تعذّر تحميل التقرير</div>}
      {data && (
        <>
          <div className="border border-gray-200 rounded-lg overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-gray-500">
                <tr>{['المورد', 'رصيد SOFTECH', 'فواتير مفتوحة', 'مغطى', 'تحت المراجعة', 'غير مسدد فعلياً', 'مرتجعات مستحقة', 'صافي المستحق'].map(h => <th key={h} className="p-2 text-right font-medium">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.suppliers.slice(0, 40).map(s => (
                  <tr key={s.personcode}>
                    <td className="p-2">{s.personcode} · {s.supplier}</td>
                    <td className="p-2">{money(s.softech_balance)}</td>
                    <td className="p-2">{s.invoices}</td>
                    <td className="p-2 text-green-700">{money(s.matched)}</td>
                    <td className="p-2 text-amber-700">{money(s.under_review)}</td>
                    <td className="p-2 font-semibold text-red-700">{money(s.unpaid_uncovered)}</td>
                    <td className="p-2 text-sky-800">{money(s.open_returns)}</td>
                    <td className="p-2 font-bold text-[#022871]">{money(s.net_payable)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border border-gray-200 rounded-lg overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-gray-500">
                <tr>{[['المورد', 'supplier'], ['الفرع', 'branchcode'], ['الفاتورة', 'docnumber'], ['مستند المورد'], ['تاريخ الفاتورة', 'docdate'],
                      ['المستخدم'], ['القيمة', 'doc_value'], ['المسدد', 'paid_in_softech'], ['مغطى'],
                      ['ƒ المتبقي (محسوب)', 'remaining_calc'], ['تحت المراجعة', 'under_review'],
                      ['غير مسدد', 'unpaid_uncovered'], ['الحالة'], ['ملاحظات'], ['الأصناف']].map(([h, f]) => (
                  <th key={h} className="p-2 text-right font-medium"><SortTh label={h} field={f} ordering={ordering} setOrdering={setOrdering} /></th>
                ))}</tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.rows.map(r => (
                  <tr key={r.invoice_id}>
                    <td className="p-2">{r.personcode} · {r.supplier}</td>
                    <td className="p-2">{r.branchcode} · {r.branch_name}</td>
                    <td className="p-2">{r.docnumber}</td>
                    <td className="p-2">{r.supplier_docnumber || '—'}</td>
                    <td className="p-2 whitespace-nowrap"><When date={r.docdate} at={r.entered_at} /></td>
                    <td className="p-2">{r.user_name || r.usercode || '—'}</td>
                    <td className="p-2">{money(r.doc_value)}</td>
                    <td className="p-2">{money(r.paid_in_softech)}</td>
                    <td className="p-2 text-green-700">{money(Number(r.matched_approved) + Number(r.matched_high_pending))}</td>
                    <td className="p-2"><Remaining value={r.remaining_calc} returnCredit={r.returned_open} compact /></td>
                    <td className="p-2 text-amber-700">{money(r.under_review)}</td>
                    <td className="p-2 font-semibold text-red-700">{money(r.unpaid_uncovered)}</td>
                    <td className="p-2">{r.status}</td>
                    <td className="p-2 text-amber-800 max-w-48 truncate" title={r.comments}>{r.comments || '—'}</td>
                    <td className="p-2"><InvoiceLines invoiceId={r.invoice_id} compact /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.row_count > data.rows.length && <div className="text-xs text-gray-400">يُعرض أكبر {data.rows.length} — التصدير يحوي الكل.</div>}
        </>
      )}
    </div>
  )
}

// ── shared filter bar: multi-select suppliers · date range · value range ─────
function SupplierMultiSelect({ partyType, selected, onChange }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const { data: options = [] } = useQuery({
    queryKey: ['recon', 'supplier-options', partyType],
    queryFn: () => reconciliationApi.supplierOptions({ party_type: partyType }).then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })
  const byCode = Object.fromEntries(options.map(o => [o.code, o]))
  const needle = q.trim().toLowerCase()
  const shown = needle
    ? options.filter(o => o.code.includes(needle) || wildcardMatch(o.name, needle))
    : options
  const toggle = (code) => onChange(selected.includes(code) ? selected.filter(c => c !== code) : [...selected, code])
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)}
              className="border border-gray-200 rounded-lg px-3 py-1 text-sm bg-white min-w-56 text-right flex items-center gap-2">
        <span className="text-gray-500">الموردون:</span>
        <span className="font-medium text-[#022871]">{selected.length ? `${selected.length} محدد` : 'الكل'}</span>
        <span className="text-gray-400 mr-auto">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-96 max-w-[90vw] bg-white border border-gray-200 rounded-lg shadow-lg p-2" onMouseLeave={() => setOpen(false)}>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="ابحث بالكود أو الاسم…"
                 className="w-full border border-gray-200 rounded px-2 py-1 text-sm mb-2" />
          <div className="flex gap-2 text-xs mb-1">
            <button className="text-sky-700" onClick={() => onChange([...new Set([...selected, ...shown.map(o => o.code)])])}>تحديد الظاهر ({shown.length})</button>
            <button className="text-red-600" onClick={() => onChange([])}>مسح التحديد</button>
          </div>
          <div className="max-h-72 overflow-y-auto divide-y divide-gray-50">
            {shown.slice(0, 400).map(o => (
              <label key={o.code} className="flex items-center gap-2 px-1 py-1 text-sm cursor-pointer hover:bg-gray-50">
                <input type="checkbox" checked={selected.includes(o.code)} onChange={() => toggle(o.code)} />
                <span className="text-gray-400 w-12">{o.code}</span>
                <span className="flex-1 truncate">{o.name}</span>
                <span className="text-[11px] text-gray-400">{money(o.balance)}</span>
              </label>
            ))}
            {shown.length === 0 && <div className="text-xs text-gray-400 p-2">لا نتائج</div>}
          </div>
        </div>
      )}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1 max-w-xl">
          {selected.map(c => (
            <span key={c} className="text-[11px] bg-sky-50 border border-sky-200 text-sky-800 rounded-full px-2 py-0.5">
              {c} · {byCode[c]?.name?.slice(0, 22) || ''}
              <button className="mr-1 text-sky-500" onClick={() => toggle(c)}>✕</button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function FilterBar({ partyType, filters, setFilters }) {
  const [amin, setAmin] = useState(filters.amount_min || '')
  const [amax, setAmax] = useState(filters.amount_max || '')
  const commit = () => setFilters(f => ({ ...f, amount_min: amin, amount_max: amax }))
  const onKey = (e) => { if (e.key === 'Enter') commit() }
  const active = filters.personcodes.length || filters.inv_date_from || filters.inv_date_to
    || filters.pay_date_from || filters.pay_date_to || filters.amount_min || filters.amount_max
  const dateRange = (label, fromKey, toKey, tone) => (
    <div className={`flex items-center gap-1 rounded-lg border px-2 py-0.5 ${tone}`}>
      <span className="font-medium">{label}</span>
      <span className="text-gray-500">من</span>
      <input type="date" value={filters[fromKey]} onChange={e => setFilters(f => ({ ...f, [fromKey]: e.target.value }))}
             className="border border-gray-200 rounded px-1 py-0.5 bg-white" />
      <span className="text-gray-500">إلى</span>
      <input type="date" value={filters[toKey]} onChange={e => setFilters(f => ({ ...f, [toKey]: e.target.value }))}
             className="border border-gray-200 rounded px-1 py-0.5 bg-white" />
    </div>
  )
  return (
    <div className="flex items-start gap-3 flex-wrap bg-gray-50 border border-gray-200 rounded-xl p-2 text-sm">
      <SupplierMultiSelect partyType={partyType} selected={filters.personcodes}
                           onChange={(codes) => setFilters(f => ({ ...f, personcodes: codes }))} />
      {dateRange('تاريخ الفاتورة', 'inv_date_from', 'inv_date_to', 'border-green-200 bg-green-50/60 text-green-900')}
      {dateRange('تاريخ السند (السداد)', 'pay_date_from', 'pay_date_to', 'border-sky-200 bg-sky-50/60 text-sky-900')}
      <label className="flex items-center gap-1" title="قيمة المستند: قيمة الفاتورة / مبلغ السند / المبلغ المقترح">
        <span className="text-gray-500">القيمة من</span>
        <input type="number" step="any" value={amin} onChange={e => setAmin(e.target.value)} onBlur={commit} onKeyDown={onKey}
               className="border border-gray-200 rounded px-2 py-0.5 w-24" />
        <span className="text-gray-500">إلى</span>
        <input type="number" step="any" value={amax} onChange={e => setAmax(e.target.value)} onBlur={commit} onKeyDown={onKey}
               className="border border-gray-200 rounded px-2 py-0.5 w-24" />
      </label>
      {active ? (
        <button onClick={() => { setAmin(''); setAmax(''); setFilters({ personcodes: [], inv_date_from: '', inv_date_to: '', pay_date_from: '', pay_date_to: '', amount_min: '', amount_max: '' }) }}
                className="text-red-600 text-xs self-center">✕ مسح كل الفلاتر</button>
      ) : null}
      <span className="text-[11px] text-gray-400 self-center mr-auto">الفلاتر تنطبق على كل التبويبات والإجماليات والتصدير والإجراءات الجماعية</span>
    </div>
  )
}

function Pager({ page, setPage, count, size = 50 }) {
  const pages = Math.max(1, Math.ceil((count || 0) / size))
  if (pages <= 1) return null
  return (
    <div className="flex items-center gap-2 text-sm justify-center py-2">
      <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-2 py-0.5 border rounded disabled:opacity-40">السابق</button>
      <span className="text-gray-500">صفحة {page} من {pages} · {count} صف</span>
      <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="px-2 py-0.5 border rounded disabled:opacity-40">التالي</button>
    </div>
  )
}

// ── page shell ────────────────────────────────────────────────────────────────
export default function ReconciliationPage() {
  const [tab, setTab] = useState('candidates')
  useHelpTab(tab)
  const [partyType, setPartyType] = useState('supplier')
  const [filters, setFilters] = useState({ personcodes: [], inv_date_from: '', inv_date_to: '', pay_date_from: '', pay_date_to: '', amount_min: '', amount_max: '' })
  const scope = {
    party_type: partyType,
    ...(filters.personcodes.length ? { personcodes: filters.personcodes.join(',') } : {}),
    ...(filters.inv_date_from ? { inv_date_from: filters.inv_date_from } : {}),
    ...(filters.inv_date_to ? { inv_date_to: filters.inv_date_to } : {}),
    ...(filters.pay_date_from ? { pay_date_from: filters.pay_date_from } : {}),
    ...(filters.pay_date_to ? { pay_date_to: filters.pay_date_to } : {}),
    ...(filters.amount_min !== '' ? { amount_min: filters.amount_min } : {}),
    ...(filters.amount_max !== '' ? { amount_max: filters.amount_max } : {}),
  }

  const { data: dash } = useQuery({
    queryKey: ['recon', 'dashboard', scope],
    queryFn: () => reconciliationApi.dashboard(scope).then(r => r.data),
  })

  const tabs = [
    ['candidates', 'المقترحات'],
    ['exceptions', 'الاستثناءات'],
    ['unpaid', 'غير المسددة (للمالية)'],
    ['parties', 'الحصر'],
  ]
  return (
    <div className="p-5 space-y-4" dir="rtl">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-bold text-[#022871]">سداد فواتير الموردين — التسوية</h1>
        <div className="flex gap-1 text-sm">
          {['supplier', 'customer'].map(t => (
            <button key={t} onClick={() => setPartyType(t)} className={`px-3 py-1 rounded-lg border ${partyType === t ? 'bg-[#022871] text-white border-[#022871]' : 'bg-white border-gray-200 text-gray-600'}`}>
              {t === 'supplier' ? 'موردون' : 'عملاء'}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-400 mr-auto">الاعتماد يُنشئ ربطًا داخليًا — الكتابة في SOFTECH (سداد من الرئيسي) خطوة منفصلة قابلة للعكس</span>
      </div>

      <FilterBar key={partyType} partyType={partyType} filters={filters}
                 setFilters={(u) => setFilters(prev => (typeof u === 'function' ? u(prev) : u))} />

      <Kpis d={dash} />

      <div className="flex gap-2 border-b border-gray-200">
        {tabs.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 text-sm border-b-2 -mb-px ${tab === k ? 'border-[#022871] text-[#022871] font-semibold' : 'border-transparent text-gray-500'}`}>{l}</button>
        ))}
      </div>

      {tab === 'candidates' && <CandidatesTab scope={scope} />}
      {tab === 'exceptions' && <ExceptionsTab scope={scope} />}
      {tab === 'unpaid' && <UnpaidTab scope={scope} />}
      {tab === 'parties' && <PartiesTab scope={scope} />}
    </div>
  )
}
