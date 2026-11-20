/**
 * OutHereTab — /supply «ناقص هنا · موجود هناك» (C06, P-30 list without waiting for newqty).
 *
 * A/B items at zero at a retail branch today while another live branch holds stock above its safety level, and how
 * much each could send. The server decides every number (apps/purchasing/out_here.py, the transfer engine's own
 * pairing on today's stock); this tab only shows it. Read-only: the transfer itself is made on the transfers screen.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { exportJobsApi, supplyApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import useExportJob from '../../hooks/useExportJob'
import ExportJobStatus from '../../components/ExportJobStatus'
import { Chip, q, money, errText, inputCls, btnGhost, SortTh, useSort, txt } from './supplyUi'

export default function OutHereTab() {
  const bl = useBranchLabels()
  const [branch, setBranch] = useState('')
  const [abc, setAbc] = useState('A,B')
  const params = { abc, ...(branch ? { branch } : {}) }

  const { data, isLoading, error } = useQuery({
    queryKey: ['supply-out-here', branch, abc],
    queryFn: () => supplyApi.outHere(params).then(r => r.data),
  })
  const rows = data?.rows || []
  const grid = useSort(rows, {
    branch: txt(r => r.branch_code), item: txt(r => r.item_name), abc: txt(r => r.abc_class),
    rate: r => r.monthly_avg, need: r => r.need, qty: r => r.transfer_qty, value: r => r.value,
  })
  const totals = useMemo(() => ({ n: rows.length, value: rows.reduce((s, r) => s + r.value, 0) }), [rows])
  // Stage 4: built as a background job (start → progress → download)
  const exp = useExportJob({
    storageKey: 'export-job:supply-out-here',
    start: () => exportJobsApi.start('/supply/out-here/export/', params),
  })

  return (
    <div className="space-y-3">
      <div className="text-sm text-content/80 bg-surface-2/60 border border-line rounded p-3 leading-6">
        أصناف فئة A/B رصيدها صفر في فرع النهارده، وفي فرع تاني رصيد فوق حد الأمان بتاعه — من رصيد اليوم مباشرة.
        الكمية المقترحة من نفس منطق «التحويلات المقترحة» في المشتريات، والفرع المصدر عمره ما ينزل تحت الأمان.
        للعرض بس: التحويل نفسه بيتعمل من <Link to="/transfers" className="underline">شاشة التحويلات</Link>.
        {data?.calc_date && <span className="text-content/60"> · الفئة والأمان من تشغيل المحرك {data.calc_date}</span>}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select value={branch} onChange={e => setBranch(e.target.value)} className={inputCls} data-tour="purchasing-supply-outhere-branch">
          <option value="">كل الفروع</option>
          {(data?.branches || []).map(b => <option key={b.branch_code} value={b.branch_code}>{bl(b.branch_code)}</option>)}
        </select>
        <select value={abc} onChange={e => setAbc(e.target.value)} className={inputCls}>
          <option value="A,B">A + B</option>
          <option value="A">A فقط</option>
          <option value="B">B فقط</option>
        </select>
        <span className="text-content/70">{totals.n} صنف · {money(totals.value)}</span>
        <span className="flex-1" />
        <button data-tour="purchasing-supply-outhere-export" onClick={() => exp.run()} disabled={exp.busy} className={btnGhost}>
          {exp.busy ? '… جارٍ تجهيز الملف' : '⬇ Excel'}
        </button>
      </div>
      <div className="flex justify-end"><ExportJobStatus exp={exp} /></div>
      {error && <div className="text-sm bg-surface-2 border border-line rounded px-3 py-2">{errText(error)}</div>}

      {!branch && (data?.branches || []).length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {data.branches.map(b => (
            <button key={b.branch_code} onClick={() => setBranch(b.branch_code)}
              className="rounded border border-line px-2 py-1 hover:border-primary/50">
              {bl(b.branch_code)}: <b>{b.items}</b>{b.a_items > 0 && <span className="text-content/60"> ({b.a_items} A)</span>}
            </button>
          ))}
        </div>
      )}

      {isLoading ? <div className="text-center py-10 text-content/50">جارٍ التحميل…</div> : rows.length === 0 ? (
        <div className="text-center py-14 text-content/50">مفيش صنف A/B ناقص في فرع وموجود فوق الأمان في فرع تاني.</div>
      ) : (
        <div data-tour="purchasing-supply-outhere-grid" className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm whitespace-nowrap">
            <thead className="bg-surface-2 text-content/70 text-xs">
              <tr>
                <SortTh k="branch" {...grid} className="px-2 py-2 text-right">الفرع (ناقص)</SortTh>
                <SortTh k="item" {...grid} className="px-2 py-2 text-right">الصنف</SortTh>
                <SortTh k="abc" {...grid} className="px-2 py-2 text-right">الفئة</SortTh>
                <SortTh k="rate" {...grid} className="px-2 py-2 text-right">المعدل/شهر</SortTh>
                <SortTh k="need" {...grid} className="px-2 py-2 text-right">الاحتياج</SortTh>
                <SortTh k="qty" {...grid} className="px-2 py-2 text-right">المقترح</SortTh>
                <th className="px-2 py-2 text-right">من</th>
                <SortTh k="value" {...grid} className="px-2 py-2 text-right">القيمة</SortTh>
              </tr>
            </thead>
            <tbody>
              {grid.sorted.map(r => (
                <tr key={`${r.branch_code}-${r.item_id}`} className="border-t border-line">
                  <td className="px-2 py-1.5">{bl(r.branch_code)}</td>
                  <td className="px-2 py-1.5">{r.item_name} <span className="text-xs text-content/50">{r.item_code}</span></td>
                  <td className="px-2 py-1.5"><Chip tone={r.abc_class === 'A' ? 'emerald' : 'gray'}>{r.abc_class}</Chip></td>
                  <td className="px-2 py-1.5">{q(r.monthly_avg)}</td>
                  <td className="px-2 py-1.5">{q(r.need)}</td>
                  <td className="px-2 py-1.5 font-semibold">
                    {q(r.transfer_qty)}
                    {r.short_after > 0 && <span className="text-xs text-content/60"> (يتبقى {q(r.short_after)})</span>}
                  </td>
                  <td className="px-2 py-1.5 text-xs">
                    {r.sources.map(s => (
                      <div key={s.branch_code} title={`الرصيد ${q(s.stock_now)} · الأمان ${q(s.safety)}`}>
                        {bl(s.branch_code)}: <b>{q(s.qty)}</b>
                      </div>
                    ))}
                  </td>
                  <td className="px-2 py-1.5">{money(r.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
