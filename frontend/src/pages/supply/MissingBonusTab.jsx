/**
 * MissingBonusTab — /supply «بونص ناقص» (C18).
 *
 * Paid purchase invoices (doc 10) that came with fewer free units than the same supplier's last 3 deliveries of the
 * item gave. The server decides every flag (apps/procurement/missing_bonus.py); this tab only shows them. Read-only:
 * claim the bonus from the supplier before paying.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import { Chip, q, money, errText, inputCls, btnGhost, SortTh, useSort, txt, downloadBlob } from './supplyUi'

const DAYS = [7, 14, 30, 60, 90]

export default function MissingBonusTab() {
  const bl = useBranchLabels()
  const [days, setDays] = useState(30)
  const [branch, setBranch] = useState('')
  const [changed, setChanged] = useState(false)
  const [msg, setMsg] = useState('')
  const params = { days, ...(branch ? { branch } : {}), ...(changed ? { changed: 1 } : {}) }

  const { data, isLoading, error } = useQuery({
    queryKey: ['supply-missing-bonus', days, branch, changed],
    queryFn: () => supplyApi.missingBonus(params).then(r => r.data),
  })
  const rows = data?.rows || []
  const grid = useSort(rows, {
    date: r => r.doc_date, supplier: txt(r => r.supplier_name), item: txt(r => r.item_name),
    paid: r => r.paid_qty, missing: r => r.missing_free, value: r => r.missing_value,
  })
  const total = useMemo(() => rows.reduce((s, r) => s + r.missing_value, 0), [rows])
  const exportXlsx = () => supplyApi.missingBonusExport(params)
    .then(r => downloadBlob(r.data, `missing-bonus-${new Date().toISOString().slice(0, 10)}.xlsx`))
    .catch(e => setMsg(errText(e)))

  return (
    <div className="space-y-3">
      <div className="text-sm text-content/80 bg-surface-2/60 border border-line rounded p-3 leading-6">
        فواتير شراء (مستند 10) جت ببونص أقل من آخر {data?.refs ?? 3} توريدات لنفس الصنف من نفس المورد — كلها كان فيها بونص
        (≥ {data?.min_bonus_pct ?? 5}% من المدفوع) وبنفس الصفقة تقريباً. البونص المتوقع = المدفوع × أقل نسبة في التوريدات دي، بالوحدة الكاملة.
        راجع المورد واطلب البونص قبل السداد. للعرض بس — مفيش حاجة بتتكتب في SOFTECH.
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select value={days} onChange={e => setDays(Number(e.target.value))} className={inputCls}>
          {DAYS.map(d => <option key={d} value={d}>آخر {d} يوم</option>)}
        </select>
        <select value={branch} onChange={e => setBranch(e.target.value)} className={inputCls}>
          <option value="">كل الفروع</option>
          {(data?.branches || []).map(b => <option key={b.branch_code} value={b.branch_code}>{bl(b.branch_code)}</option>)}
        </select>
        <label className="flex items-center gap-1 text-content/70">
          <input type="checkbox" checked={changed} onChange={e => setChanged(e.target.checked)} />
          اعرض «صفقة تغيّرت»
        </label>
        <span className="text-content/70">{rows.length} سطر · {money(total)}</span>
        <span className="flex-1" />
        <button data-tour="purchasing-supply-bonus-export" onClick={exportXlsx} className={btnGhost}>⬇ Excel</button>
      </div>
      {(msg || error) && <div className="text-sm bg-surface-2 border border-line rounded px-3 py-2">{msg || errText(error)}</div>}

      {isLoading ? <div className="text-center py-10 text-content/50">جارٍ التحميل…</div> : rows.length === 0 ? (
        <div className="text-center py-14 text-content/50">مفيش فاتورة جت ببونص أقل من المعتاد في الفترة دي.</div>
      ) : (
        <div data-tour="purchasing-supply-bonus-grid" className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm whitespace-nowrap">
            <thead className="bg-surface-2 text-content/70 text-xs">
              <tr>
                <SortTh k="date" {...grid} className="px-2 py-2 text-right">التاريخ</SortTh>
                <SortTh k="supplier" {...grid} className="px-2 py-2 text-right">المورد</SortTh>
                <th className="px-2 py-2 text-right">الفرع / المستند</th>
                <SortTh k="item" {...grid} className="px-2 py-2 text-right">الصنف</SortTh>
                <SortTh k="paid" {...grid} className="px-2 py-2 text-right">مدفوع + بونص</SortTh>
                <SortTh k="missing" {...grid} className="px-2 py-2 text-right">المتوقع / الناقص</SortTh>
                <th className="px-2 py-2 text-right">آخر التوريدات</th>
                <SortTh k="value" {...grid} className="px-2 py-2 text-right">قيمة الناقص</SortTh>
              </tr>
            </thead>
            <tbody>
              {grid.sorted.map(r => (
                <tr key={r.id} className="border-t border-line">
                  <td className="px-2 py-1.5">{r.doc_date}</td>
                  <td className="px-2 py-1.5">{r.supplier_name || r.supplier_code}</td>
                  <td className="px-2 py-1.5 text-xs">{bl(r.branch_code)} · #{r.doc_number}</td>
                  <td className="px-2 py-1.5">{r.item_name || r.item_code} <span className="text-xs text-content/50">{r.item_code}</span></td>
                  <td className="px-2 py-1.5">{q(r.paid_qty)} + <b>{q(r.free_qty)}</b></td>
                  <td className="px-2 py-1.5">
                    {q(r.expected_free)} / <b className="text-rose-700">{q(r.missing_free)}</b>{' '}
                    <Chip tone={r.kind === 'none' ? 'rose' : 'amber'}>{r.kind === 'none' ? 'بدون بونص' : 'بونص ناقص'}</Chip>
                    {r.deal_changed && <Chip tone="gray">صفقة تغيّرت</Chip>}
                  </td>
                  <td className="px-2 py-1.5 text-xs text-content/70">
                    {r.refs.map(x => <div key={`${x.doc_date}-${x.doc_number}-${x.branch_code}`}>{x.doc_date}: {q(x.paid)}+{q(x.free)}</div>)}
                  </td>
                  <td className="px-2 py-1.5">{money(r.missing_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
