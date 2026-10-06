/**
 * SupplierCodeReport.jsx — how many supplier lines match by the supplier's own product
 * code (confirmed mappings + the nightly SOFTECH itemssuppliers copy), per supplier, with
 * conflicts (code says another item than the one a person confirmed) and lines the code
 * can now match. Backend: apps/supply/code_report.py. Read-only.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import ProgressBar from '../../components/ProgressBar'
import { btnGhost, downloadBlob, errText, fmtDate, inputCls } from './supplyUi'

function Tile({ label, value, sub, tone = '' }) {
  return (
    <div className={`rounded-lg border border-line bg-surface px-3 py-2 min-w-[9rem] ${tone}`}>
      <div className="text-[11px] text-content/60">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-content">{value ?? '—'}</div>
      {sub && <div className="text-[11px] text-content/50">{sub}</div>}
    </div>
  )
}

export default function SupplierCodeReport({ onClose }) {
  const [days, setDays] = useState(365)
  const rq = useQuery({ queryKey: ['supply-code-report', days],
    queryFn: () => supplyApi.supplierCodeReport(days).then(r => r.data) })
  const xl = useMutation({
    mutationFn: () => supplyApi.supplierCodeReportExcel(days),
    onSuccess: (res) => downloadBlob(res.data, `supplier_codes_${days}d.xlsx`),
  })
  const d = rq.data
  const t = d?.totals
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-content">مطابقة أسطر الموردين بكود المورد</h3>
        <select value={days} onChange={e => setDays(Number(e.target.value))} className={`${inputCls} text-xs w-28`}>
          {[30, 90, 180, 365, 730].map(n => <option key={n} value={n}>آخر {n} يوم</option>)}
        </select>
        <button type="button" className={btnGhost} disabled={!d || xl.isPending} onClick={() => xl.mutate()}>
          {xl.isPending ? 'جارٍ التجهيز…' : 'تصدير Excel'}</button>
        <button type="button" className="ms-auto text-xs text-content/50 hover:text-primary" onClick={onClose}>إغلاق</button>
      </div>
      {rq.isLoading && <ProgressBar label="حساب التقرير" />}
      {xl.isPending && <ProgressBar since={xl.submittedAt} label="تجهيز ملف Excel" />}
      {rq.isError && <div className="text-xs text-rose-600">{errText(rq.error)}</div>}
      {d && (
        <>
          <div className={`text-xs rounded border px-2 py-1 ${d.mirror.empty
            ? 'border-amber-300 bg-amber-50 text-amber-800' : 'border-line bg-surface text-content/70'}`}>
            {d.mirror.empty
              ? '⚠ نسخة أكواد الموردين من SOFTECH فارغة بعد — تُملأ ليلاً (04:30) عندما يكون سيرفر 100 متاحاً. الأرقام الحالية من المطابقات المؤكدة فقط.'
              : `نسخة SOFTECH: ${d.mirror.links.toLocaleString('en-US')} ربط صنف/مورد · ${d.mirror.with_code.toLocaleString('en-US')} بكود مورد · ${d.mirror.suppliers} مورد · آخر مزامنة ${fmtDate(d.mirror.synced_at)}`}
          </div>
          <div className="flex flex-wrap gap-2">
            <Tile label="أسطر الموردين" value={t.lines} />
            <Tile label="بها كود مورد" value={t.with_code} sub={t.code_rate != null ? `${t.code_rate}% من الأسطر` : ''} />
            <Tile label="مطابقة بالكود الآن" value={t.matched} tone="border-emerald-300"
              sub={`${t.match_rate ?? 0}% · مؤكدة ${t.by_mapping} · SOFTECH ${t.by_mirror}`} />
            <Tile label="يمكن مطابقتها الآن" value={t.newly_matchable} sub="أسطر غير مطابقة يحددها كودها" />
            <Tile label="تعارض مع المؤكد" value={t.conflicts} tone={t.conflicts ? 'border-rose-300' : ''}
              sub={t.agrees + t.conflicts ? `يوافق ${t.agrees} (${t.agree_rate}%)` : ''} />
            <Tile label="كود غامض / غير معروف" value={`${t.ambiguous} / ${t.unknown}`} />
            <Tile label="مطابقة بالباركود" value={t.by_barcode} />
          </div>
          <div className="overflow-auto max-h-72 rounded border border-line bg-surface">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface text-content/60">
                <tr>
                  {['المورد', 'الأسطر', 'بها كود', 'مطابقة بالكود', 'مؤكدة', 'SOFTECH', 'غامض', 'غير معروف',
                    'يمكن مطابقتها', 'تعارض', 'باركود', 'أكواد بالنسخة'].map(h =>
                    <th key={h} className="px-2 py-1.5 font-medium text-center whitespace-nowrap">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {d.suppliers.map(s => (
                  <tr key={s.vendor_id} className="border-t border-line text-center tabular-nums">
                    <td className="px-2 py-1 text-start whitespace-nowrap">{s.supplier} <span className="text-content/40">{s.personcode}</span></td>
                    <td className="px-2 py-1">{s.lines}</td>
                    <td className="px-2 py-1">{s.with_code}</td>
                    <td className="px-2 py-1 font-semibold text-emerald-700">{s.matched}{s.match_rate != null ? ` (${s.match_rate}%)` : ''}</td>
                    <td className="px-2 py-1">{s.by_mapping}</td>
                    <td className="px-2 py-1">{s.by_mirror}</td>
                    <td className="px-2 py-1">{s.ambiguous}</td>
                    <td className="px-2 py-1">{s.unknown}</td>
                    <td className="px-2 py-1">{s.newly_matchable}</td>
                    <td className={`px-2 py-1 ${s.conflicts ? 'text-rose-700 font-semibold' : ''}`}>{s.conflicts}</td>
                    <td className="px-2 py-1">{s.by_barcode}</td>
                    <td className="px-2 py-1 text-content/60">{s.mirror_codes}</td>
                  </tr>
                ))}
                {d.suppliers.length === 0 && <tr><td colSpan={12} className="p-3 text-center text-content/50">لا أسطر موردين في هذه الفترة.</td></tr>}
              </tbody>
            </table>
          </div>
          {d.conflicts.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-rose-700">تعارضات ({d.conflicts.length}) — الكود يشير لصنف غير الصنف المؤكد</summary>
              <ul className="mt-1 space-y-0.5">
                {d.conflicts.map(c => (
                  <li key={`${c.source}-${c.line_id}`}>{c.supplier} · كود {c.code} · «{c.text}» — مؤكد: {c.confirmed_item} ← الكود: {c.code_item}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  )
}
