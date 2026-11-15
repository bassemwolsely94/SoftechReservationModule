/**
 * SOFTECH sales ↔ ETA receipts, per branch and month (spec §Phase 3). Display only: the server learns which device
 * belongs to which branch, decides every outcome, and audits exports and refreshes.
 */
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useBranchLabels from '../../hooks/useBranchLabels'
import useServerSort from '../../hooks/useServerSort'
import { ActionMsg, Btn, Failed, fmt, fmtDate, fmtInt, fmtTime, Loading, Notice, useAction } from './ui'

export const OUTCOME_LABELS = {
  matched: '✅ مطابق', amount_differs: '⚠️ المبلغ مختلف', missing_at_eta: '❌ ليس لدى المصلحة', eta_only: '❓ لدى المصلحة فقط',
  not_valid: '🚫 غير صالح لدى المصلحة', duplicate: '🔁 أُرسل مرتين', by_invoice: '📄 بفاتورة',
}
// why a line differs, decided by the server from the SOFTECH lines: items with no ETA code are left off receipts
export const REASON_LABELS = {
  all_uncoded: 'كل أصنافه بلا كود مصلحة', uncoded_lines: 'الفرق = أصناف بلا كود مصلحة', some_uncoded: 'بعض أصنافه بلا كود مصلحة',
  till_silent: 'الجهاز لم يرسل أغلب إيصالات اليوم', eta_other_day: 'المصلحة سجلته في يوم مجاور',
  no_channel_rule: 'قناة بيع بلا قاعدة ضريبية',
}
const CODING_LABELS = { approved: 'كود معتمد', missing: 'بدون كود', pending: 'قيد الاعتماد', rejected: 'كود مرفوض' }
const REQUEST_LABELS = {
  prepared: 'جاهز للإرسال', sending: 'جارٍ الإرسال', submitted: 'لدى المصلحة', approved: 'اعتمدته المصلحة',
  rejected: 'رفضته المصلحة', failed: 'لم يُقبل', uncertain: 'غير مؤكد', cancelled: 'أُلغي',
}
const UNCODED_SORT = ['value', 'docs', 'qty', 'itemcode', 'last_day']
const GAP_SORT = ['softech_total', 'day', 'branch', 'channel']
const channelText = r => (r.channel ? (r.channel_label ? `${r.channel} · ${r.channel_label}` : r.channel) : '—')
const ORDER = ['matched', 'amount_differs', 'missing_at_eta', 'eta_only', 'not_valid', 'duplicate', 'by_invoice']
const TH = 'px-2 py-1.5 text-right text-xs font-semibold text-gray-500 whitespace-nowrap'

function save(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function Lines({ system, pick }) {
  const [page, setPage] = useState(1)
  const bl = useBranchLabels()
  const act = useAction()
  const [reason, setReason] = useState('')
  const params = { system, branch: pick.branch, month: pick.month, outcome: pick.outcome, reason: reason || undefined, page }
  const q = useQuery({ queryKey: ['tax-invoicing', 'recon-lines', params], queryFn: () => taxInvoicingApi.reconLines(params).then(r => r.data),
    placeholderData: keepPreviousData })
  if (q.isLoading) return <Loading />
  if (q.error) return <Failed error={q.error} />
  const d = q.data
  return (
    <div className="space-y-2 mt-3" data-tour="tax-invoicing-main-recon-lines">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-bold">{bl(pick.branch)} · {pick.month} · {OUTCOME_LABELS[pick.outcome]}</span>
        <span className="text-gray-500">{fmtInt(d.count)}</span>
        {['missing_at_eta', 'amount_differs'].includes(pick.outcome) && (
          <select aria-label="السبب" className="border border-gray-200 rounded px-1 py-0.5 text-xs" value={reason}
            onChange={e => { setReason(e.target.value); setPage(1) }}>
            <option value="">كل الأسباب</option>
            {Object.entries(REASON_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            <option value="none">سبب غير معروف</option>
          </select>
        )}
        <Btn disabled={act.pending || !d.count}
          onClick={() => act.run(() => taxInvoicingApi.reconExport({ system, branch: pick.branch, month: pick.month, outcome: pick.outcome, reason: reason || undefined }),
            r => { save(r instanceof Blob ? r : new Blob([r]), `eta-recon-${pick.branch}-${pick.month}-${pick.outcome}.xlsx`); return 'تم التصدير' })}>
          تصدير Excel
        </Btn>
      </div>
      <table className="w-full text-sm">
        <thead><tr>{['اليوم', 'النوع', 'رقم SOFTECH', 'القناة', 'إجمالي SOFTECH', 'إجمالي المصلحة', 'حالة المصلحة', 'مرات الإرسال', 'السبب', 'بلا كود'].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
        <tbody>
          {d.rows.map(r => (
            <tr key={r.id} className="border-t border-gray-100">
              <td className="px-2 py-1">{fmtDate(r.day)}</td>
              <td className="px-2 py-1">{r.doccode === '30' ? 'مرتجع' : 'بيع'}</td>
              <td className="px-2 py-1">{r.docnumber}</td>
              <td className="px-2 py-1 text-xs">{channelText(r)}</td>
              <td className="px-2 py-1">{fmt(r.softech_total)}</td>
              <td className="px-2 py-1">{fmt(r.eta_total)}</td>
              <td className="px-2 py-1">{r.eta_status || '—'}</td>
              <td className="px-2 py-1">{r.eta_count}</td>
              <td className="px-2 py-1 text-xs">{REASON_LABELS[r.reason] || '—'}</td>
              <td className="px-2 py-1">{r.uncoded_total == null ? '—' : fmt(r.uncoded_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center gap-2 text-xs">
        <Btn disabled={page <= 1} onClick={() => setPage(p => p - 1)}>السابق</Btn>
        <span>صفحة {fmtInt(d.page)} من {fmtInt(d.pages)}</span>
        <Btn disabled={page >= d.pages} onClick={() => setPage(p => p + 1)}>التالي</Btn>
      </div>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

// the notes under a count: how many of them a known cause explains
function explained(row, outcome) {
  const r = row.reasons || {}
  const out = []
  if (outcome === 'missing_at_eta') {
    if (r.all_uncoded) out.push({ n: r.all_uncoded, text: 'بلا كود', title: 'كل أصنافه بلا كود مصلحة' })
    if (r.till_silent) out.push({ n: r.till_silent, text: 'توقف الإرسال', title: 'الجهاز لم يرسل أغلب إيصالات ذلك اليوم' })
    if (r.no_channel_rule) out.push({ n: r.no_channel_rule, text: 'قناة بلا قاعدة', title: 'قناة البيع ليس لها قاعدة ضريبية محددة' })
  }
  if (outcome === 'amount_differs' && r.uncoded_lines) out.push({ n: r.uncoded_lines, text: 'بلا كود', title: 'الفرق = أصناف بلا كود مصلحة' })
  if (outcome === 'matched' && r.eta_other_day) out.push({ n: r.eta_other_day, text: 'في يوم مجاور', title: 'المصلحة سجلته قبل أو بعد منتصف الليل' })
  return out
}

// sales missing at ETA that no known cause explains, biggest first, to check by hand
function Gaps({ system, branches, channels }) {
  const bl = useBranchLabels()
  const act = useAction()
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('-softech_total')
  const [f, setF] = useState({ branch: '', channel: '' })
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: GAP_SORT, defaultOrdering: '-softech_total' })
  const params = { system, outcome: 'missing_at_eta', reason: 'none', page, ordering, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)) }
  const q = useQuery({ enabled: open, queryKey: ['tax-invoicing', 'recon-gaps', params],
    queryFn: () => taxInvoicingApi.reconLines(params).then(r => r.data), placeholderData: keepPreviousData })
  const set = (k, v) => { setF(x => ({ ...x, [k]: v })); setPage(1) }
  return (
    <div className="border-t border-gray-100 pt-3 space-y-2" data-tour="tax-invoicing-main-recon-gaps">
      <Btn onClick={() => setOpen(x => !x)}>{open ? 'إخفاء' : 'عرض'} المبيعات الناقصة بلا سبب معروف (الأكبر أولاً)</Btn>
      {open && (
        <>
          <div className="text-xs text-gray-500">مبيعات ليست لدى المصلحة ولا يفسرها كود ناقص ولا توقف الإرسال ولا قناة بلا قاعدة. راجعها يدوياً من الأكبر.</div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <select aria-label="الفرع" className="border border-gray-200 rounded px-1 py-0.5 text-xs" value={f.branch} onChange={e => set('branch', e.target.value)}>
              <option value="">كل الفروع</option>
              {branches.map(b => <option key={b} value={b}>{bl(b)}</option>)}
            </select>
            <select aria-label="القناة" className="border border-gray-200 rounded px-1 py-0.5 text-xs" value={f.channel} onChange={e => set('channel', e.target.value)}>
              <option value="">كل القنوات</option>
              {channels.map(c => <option key={c.code} value={c.code}>{c.label ? `${c.code} · ${c.label}` : c.code}</option>)}
            </select>
            {q.data && <span className="text-gray-500 text-xs">{fmtInt(q.data.count)} مستند · {fmt(q.data.total)} ج</span>}
            <Btn disabled={act.pending || !q.data?.count}
              onClick={() => act.run(() => taxInvoicingApi.reconExport({ ...params, page: undefined }),
                r => { save(r instanceof Blob ? r : new Blob([r]), `eta-recon-gaps-${system}.xlsx`); return 'تم التصدير' })}>
              تصدير Excel
            </Btn>
          </div>
          {q.isLoading ? <Loading /> : q.error ? <Failed error={q.error} /> : q.data && (
            <>
              <table className="w-full text-sm">
                <thead><tr>
                  <SortTh {...headerProps('branch')} className={TH}>الفرع</SortTh>
                  <SortTh {...headerProps('day', 'date')} className={TH}>اليوم</SortTh>
                  <th className={TH}>النوع</th><th className={TH}>رقم SOFTECH</th>
                  <SortTh {...headerProps('channel')} className={TH}>القناة</SortTh>
                  <SortTh {...headerProps('softech_total', 'number')} className={TH}>إجمالي SOFTECH</SortTh>
                </tr></thead>
                <tbody>
                  {q.data.rows.map(r => (
                    <tr key={r.id} className="border-t border-gray-100">
                      <td className="px-2 py-1 whitespace-nowrap">{bl(r.branch)}</td>
                      <td className="px-2 py-1">{fmtDate(r.day)}</td>
                      <td className="px-2 py-1">{r.doccode === '30' ? 'مرتجع' : 'بيع'}</td>
                      <td className="px-2 py-1">{r.docnumber}</td>
                      <td className="px-2 py-1 text-xs">{channelText(r)}</td>
                      <td className="px-2 py-1 font-semibold">{fmt(r.softech_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center gap-2 text-xs">
                <Btn disabled={page <= 1} onClick={() => setPage(p => p - 1)}>السابق</Btn>
                <span>صفحة {fmtInt(q.data.page)} من {fmtInt(q.data.pages)}</span>
                <Btn disabled={page >= q.data.pages} onClick={() => setPage(p => p + 1)}>التالي</Btn>
              </div>
            </>
          )}
          <ActionMsg msg={act.msg} />
        </>
      )}
    </div>
  )
}

function Uncoded({ system, branches }) {
  const bl = useBranchLabels()
  const act = useAction()
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('-value')
  const [f, setF] = useState({ branch: '', open: '1', q: '' })
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: UNCODED_SORT, defaultOrdering: '-value' })
  const params = { system, page, ordering, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)) }
  const q = useQuery({ enabled: open, queryKey: ['tax-invoicing', 'recon-uncoded', params],
    queryFn: () => taxInvoicingApi.reconUncoded(params).then(r => r.data), placeholderData: keepPreviousData })
  const set = (k, v) => { setF(x => ({ ...x, [k]: v })); setPage(1) }
  return (
    <div className="border-t border-gray-100 pt-3 space-y-2" data-tour="tax-invoicing-main-recon-uncoded">
      <Btn onClick={() => setOpen(x => !x)}>{open ? 'إخفاء' : 'عرض'} الأصناف التي بلا كود مصلحة (مرتبة بقيمة المبيعات)</Btn>
      {open && (
        <>
          <div className="text-xs text-gray-500">هذه الأصناف لا تظهر في إيصالات المصلحة؛ تسجيل كود لها من شاشة أكواد المصلحة يغلق معظم الفروق.</div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <input aria-label="بحث" className="border border-gray-200 rounded px-2 py-0.5 text-xs" placeholder="كود أو اسم الصنف"
              value={f.q} onChange={e => set('q', e.target.value)} />
            <select aria-label="الفرع" className="border border-gray-200 rounded px-1 py-0.5 text-xs" value={f.branch} onChange={e => set('branch', e.target.value)}>
              <option value="">كل الفروع</option>
              {branches.map(b => <option key={b} value={b}>{bl(b)}</option>)}
            </select>
            <label className="text-xs flex items-center gap-1">
              <input type="checkbox" checked={f.open === '1'} onChange={e => set('open', e.target.checked ? '1' : '')} />
              ما زالت بلا كود اليوم فقط
            </label>
            {q.data && <span className="text-gray-500 text-xs">{fmtInt(q.data.count)} صنف · {fmt(q.data.total_value)} ج</span>}
            <Btn disabled={act.pending || !q.data?.count}
              onClick={() => act.run(() => taxInvoicingApi.reconUncodedExport({ ...params, page: undefined }),
                r => { save(r instanceof Blob ? r : new Blob([r]), `eta-uncoded-items-${system}.xlsx`); return 'تم التصدير' })}>
              تصدير Excel
            </Btn>
          </div>
          {q.isLoading ? <Loading /> : q.error ? <Failed error={q.error} /> : q.data && (
            <>
              <table className="w-full text-sm">
                <thead><tr>
                  <SortTh {...headerProps('itemcode')} className={TH}>كود الصنف</SortTh>
                  <th className={TH}>الصنف</th>
                  <SortTh {...headerProps('docs', 'number')} className={TH}>الإيصالات</SortTh>
                  <SortTh {...headerProps('qty', 'number')} className={TH}>الكمية</SortTh>
                  <SortTh {...headerProps('value', 'number')} className={TH}>قيمة المبيعات</SortTh>
                  <SortTh {...headerProps('last_day', 'date')} className={TH}>آخر بيع</SortTh>
                  <th className={TH}>حالة الكود</th><th className={TH}>آخر طلب كود</th>
                </tr></thead>
                <tbody>
                  {q.data.rows.map(r => (
                    <tr key={r.itemcode} className="border-t border-gray-100">
                      <td className="px-2 py-1">{r.itemcode}</td>
                      <td className="px-2 py-1">{r.name || '—'}</td>
                      <td className="px-2 py-1">{fmtInt(r.docs)}</td>
                      <td className="px-2 py-1">{fmt(r.qty)}</td>
                      <td className="px-2 py-1 font-semibold">{fmt(r.value)}</td>
                      <td className="px-2 py-1">{fmtDate(r.last_day)}</td>
                      <td className="px-2 py-1">{CODING_LABELS[r.coding_status] || r.coding_status}</td>
                      <td className="px-2 py-1">{REQUEST_LABELS[r.request_status] || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center gap-2 text-xs">
                <Btn disabled={page <= 1} onClick={() => setPage(p => p - 1)}>السابق</Btn>
                <span>صفحة {fmtInt(q.data.page)} من {fmtInt(q.data.pages)}</span>
                <Btn disabled={page >= q.data.pages} onClick={() => setPage(p => p + 1)}>التالي</Btn>
              </div>
            </>
          )}
          <ActionMsg msg={act.msg} />
        </>
      )}
    </div>
  )
}

export default function ReconSection({ system, me }) {
  const bl = useBranchLabels()
  const act = useAction()
  const [pick, setPick] = useState(null)
  const q = useQuery({ queryKey: ['tax-invoicing', 'recon', system], queryFn: () => taxInvoicingApi.reconSummary({ system }).then(r => r.data) })
  if (q.isLoading) return <Loading />
  if (q.error) return <Failed error={q.error} />
  const d = q.data
  return (
    <div className="space-y-3" data-tour="tax-invoicing-main-recon">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
        <span>مبيعات ومرتجعات SOFTECH مقابل إيصالات المصلحة. آخر حساب: {fmtTime(d.last_run_at)}</span>
        {me?.can_edit && (
          <>
            <Btn disabled={act.pending} data-tour="tax-invoicing-main-recon-refresh"
              onClick={() => act.run(() => taxInvoicingApi.reconRefresh({ system }), 'بدأ الحساب لآخر 35 يوماً في الخلفية')}>إعادة حساب آخر 35 يوماً</Btn>
            <Btn disabled={act.pending}
              onClick={() => act.run(() => taxInvoicingApi.reconRefresh({ system, months: 24 }), 'بدأ حساب كل السجل في الخلفية؛ قد يستغرق وقتاً')}>حساب كل السجل</Btn>
          </>
        )}
      </div>
      {d.last_error && <Notice tone="amber">آخر حساب توقف: {d.last_error}</Notice>}
      {d.devices.length > 0 && (
        <div className="text-xs text-gray-500">
          الأجهزة: {d.devices.map(x => `${x.pos_serial} ← ${bl(x.branch)} (من ${fmtDate(x.first_day)})`).join(' · ')}
        </div>
      )}
      {!d.rows.length ? <div className="py-8 text-center text-gray-400">لم تُحسب المطابقة بعد</div> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr>
              <th className={TH}>الفرع</th><th className={TH}>الشهر</th>
              {ORDER.map(o => <th key={o} className={TH}>{OUTCOME_LABELS[o]}</th>)}
              <th className={TH}>SOFTECH</th><th className={TH}>المصلحة</th>
            </tr></thead>
            <tbody>
              {d.rows.map(r => (
                <tr key={`${r.branch}-${r.month}`} className="border-t border-gray-100">
                  <td className="px-2 py-1 whitespace-nowrap">{bl(r.branch)}</td>
                  <td className="px-2 py-1">{r.month}</td>
                  {ORDER.map(o => (
                    <td key={o} className="px-2 py-1">
                      {r[o] ? (
                        <>
                          <button type="button" className={`underline ${['matched', 'by_invoice'].includes(o) ? 'text-gray-700' : 'text-red-700 font-bold'}`}
                            onClick={() => setPick({ branch: r.branch, month: r.month, outcome: o })}>{fmtInt(r[o])}</button>
                          {explained(r, o).map(x => (
                            <div key={x.text} className="text-[11px] text-gray-500" title={x.title}>منها {fmtInt(x.n)} {x.text}</div>
                          ))}
                        </>
                      ) : <span className="text-gray-300">0</span>}
                    </td>
                  ))}
                  <td className="px-2 py-1">{fmt(r.softech_total)}</td>
                  <td className="px-2 py-1">{fmt(r.eta_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pick && <Lines key={`${pick.branch}-${pick.month}-${pick.outcome}`} system={system} pick={pick} />}
      {d.rows.length > 0 && <Uncoded system={system} branches={[...new Set(d.rows.map(r => r.branch))]} />}
      {d.rows.length > 0 && <Gaps system={system} branches={[...new Set(d.rows.map(r => r.branch))]} channels={d.channels || []} />}
      <ActionMsg msg={act.msg} />
    </div>
  )
}
