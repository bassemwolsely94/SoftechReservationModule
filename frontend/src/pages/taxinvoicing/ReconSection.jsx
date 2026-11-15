/**
 * SOFTECH sales ↔ ETA receipts, per branch and month (spec §Phase 3). Display only: the server learns which device
 * belongs to which branch, decides every outcome, and audits exports and refreshes.
 */
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import { ActionMsg, Btn, Failed, fmt, fmtDate, fmtInt, fmtTime, Loading, Notice, useAction } from './ui'

export const OUTCOME_LABELS = {
  matched: '✅ مطابق', amount_differs: '⚠️ المبلغ مختلف', missing_at_eta: '❌ ليس لدى المصلحة', eta_only: '❓ لدى المصلحة فقط',
  not_valid: '🚫 غير صالح لدى المصلحة', duplicate: '🔁 أُرسل مرتين', by_invoice: '📄 بفاتورة',
}
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
  const params = { system, branch: pick.branch, month: pick.month, outcome: pick.outcome, page }
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
        <Btn disabled={act.pending || !d.count}
          onClick={() => act.run(() => taxInvoicingApi.reconExport({ system, branch: pick.branch, month: pick.month, outcome: pick.outcome }),
            r => { save(r instanceof Blob ? r : new Blob([r]), `eta-recon-${pick.branch}-${pick.month}-${pick.outcome}.xlsx`); return 'تم التصدير' })}>
          تصدير Excel
        </Btn>
      </div>
      <table className="w-full text-sm">
        <thead><tr>{['اليوم', 'النوع', 'رقم SOFTECH', 'إجمالي SOFTECH', 'إجمالي المصلحة', 'حالة المصلحة', 'مرات الإرسال'].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
        <tbody>
          {d.rows.map(r => (
            <tr key={r.id} className="border-t border-gray-100">
              <td className="px-2 py-1">{fmtDate(r.day)}</td>
              <td className="px-2 py-1">{r.doccode === '30' ? 'مرتجع' : 'بيع'}</td>
              <td className="px-2 py-1">{r.docnumber}</td>
              <td className="px-2 py-1">{fmt(r.softech_total)}</td>
              <td className="px-2 py-1">{fmt(r.eta_total)}</td>
              <td className="px-2 py-1">{r.eta_status || '—'}</td>
              <td className="px-2 py-1">{r.eta_count}</td>
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
              onClick={() => act.run(() => taxInvoicingApi.reconRefresh({ system }), 'بدأ الحساب لآخر 30 يوماً في الخلفية')}>إعادة حساب آخر 30 يوماً</Btn>
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
                        <button type="button" className={`underline ${['matched', 'by_invoice'].includes(o) ? 'text-gray-700' : 'text-red-700 font-bold'}`}
                          onClick={() => setPick({ branch: r.branch, month: r.month, outcome: o })}>{fmtInt(r[o])}</button>
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
      <ActionMsg msg={act.msg} />
    </div>
  )
}
