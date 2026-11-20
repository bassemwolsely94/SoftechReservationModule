/**
 * BoughtDearerTab.jsx — «اشترينا أغلى» (C17): one month's purchase lines bought above the cheapest
 * recent accredited supplier for the same item, with the EGP paid above it, per buyer and supplier.
 * Visibility only — it orders nothing. The server computes every number
 * (apps/supply/bought_dearer.py); this screen filters, sorts and downloads.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import { FreshnessBar } from './AvailabilityControls'
import { btnGhost, downloadBlob, errText, inputCls, money, q, SortTh, txt, useSort } from './supplyUi'

const lastMonth = () => {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function Groups({ title, rows, label }) {
  if (!rows?.length) return null
  return (
    <div className="rounded border border-line bg-surface p-2 text-xs min-w-[240px]">
      <div className="font-semibold mb-1">{title}</div>
      {rows.slice(0, 8).map(g => (
        <div key={label(g)} className="flex justify-between gap-3 py-0.5">
          <span className="truncate">{label(g)}</span>
          <span className="tabular-nums whitespace-nowrap">{g.lines} سطر · <b>{money(g.egp_above)}</b> ج</span>
        </div>
      ))}
    </div>
  )
}

export default function BoughtDearerTab() {
  const [month, setMonth] = useState(lastMonth)
  const rq = useQuery({
    queryKey: ['bought-dearer', month],
    queryFn: () => supplyApi.boughtDearer({ month }).then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })
  const xlsM = useMutation({
    mutationFn: () => supplyApi.boughtDearerExcel({ month }),
    onSuccess: (res) => downloadBlob(res.data, `bought_dearer_${month}.xlsx`),
  })
  const d = rq.data
  const grid = useSort(d?.lines || [], {
    date: r => r.date, code: txt(r => r.code), name: r => r.name, buyer: r => r.buyer_name || r.buyer_code,
    supplier: r => r.supplier_name, disc: r => r.discount_pct, cheaper: r => r.cheaper_discount_pct,
    gap: r => r.gap_pct, units: r => r.units, egp: r => r.egp_above,
  }, { key: 'egp', dir: 'desc' })
  const th = (k, label) => <SortTh k={k} sort={grid.sort} onSort={grid.onSort} className="px-2 py-1.5 whitespace-nowrap">{label}</SortTh>
  return (
    <div className="space-y-3">
      <FreshnessBar domains={['purchases']} onRefreshed={() => rq.refetch()} />
      <div className="text-xs text-content/70 leading-6 rounded border border-line bg-surface p-2">
        كل سطر شراء في الشهر اتشرى بخصم أقل من أرخص مورد معتمد للصنف نفسه خلال آخر {d?.stale_days ?? 90} يوماً قبله
        بأكثر من {d?.better_pct ?? 1} نقطة. التكلفة شاملة الضريبة وبعد البونص، والمخازن والحسابات الوهمية مش سعر للمقارنة.
        «دفعنا زيادة» = الفرق × سعر الجمهور × الكمية. للمتابعة بس — مفيش أي طلب بيتعمل من هنا.
      </div>
      <div className="flex flex-wrap items-end gap-3" data-tour="purchasing-supply-dearer-filters">
        <label className="flex flex-col gap-1 text-xs text-content/60">الشهر
          <input type="month" value={month} onChange={e => e.target.value && setMonth(e.target.value)} className={inputCls} />
        </label>
        <button type="button" className={btnGhost} disabled={xlsM.isPending || !d} onClick={() => xlsM.mutate()}>
          {xlsM.isPending ? '…' : '⬇ Excel'}
        </button>
        {d && (
          <span className="text-sm text-content/80 mb-1.5">
            {q(d.totals.lines)} سطر من {q(d.totals.lines_checked)} — دفعنا زيادة <b className="text-amber-700">{money(d.totals.egp_above)} ج</b>
          </span>
        )}
      </div>
      {rq.isLoading ? <div className="text-content/50 text-sm p-4">جارٍ الحساب…</div>
        : rq.isError ? <div className="text-rose-600 text-sm p-4">{errText(rq.error)}</div>
        : (
          <>
            <div className="flex flex-wrap gap-3" data-tour="purchasing-supply-dearer-groups">
              <Groups title="حسب المورد" rows={d.by_supplier} label={g => g.name} />
              <Groups title="حسب المشتري" rows={d.by_buyer} label={g => g.name || g.code || '—'} />
            </div>
            {!d.lines.length ? <div className="text-content/50 text-sm p-4">مفيش سطور اتشرت أغلى في الشهر ده.</div> : (
              <div className="overflow-x-auto rounded border border-line" data-tour="purchasing-supply-dearer-table">
                <table className="w-full text-xs text-right">
                  <thead className="bg-surface-2 text-content/70">
                    <tr>{th('date', 'التاريخ')}{th('code', 'الكود')}{th('name', 'الصنف')}{th('buyer', 'المشتري')}
                      {th('supplier', 'المورد')}{th('disc', 'خصمنا %')}{th('cheaper', 'الأرخص %')}{th('gap', 'الفرق')}
                      {th('units', 'الكمية')}{th('egp', 'دفعنا زيادة')}</tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {grid.sorted.map(r => (
                      <tr key={`${r.doc_number}-${r.code}-${r.date}-${r.supplier}`} className="hover:bg-surface-2">
                        <td className="px-2 py-1 whitespace-nowrap">{r.date}</td>
                        <td className="px-2 py-1 font-mono">{r.code}</td>
                        <td className="px-2 py-1">{r.name}</td>
                        <td className="px-2 py-1">{r.buyer_name || r.buyer_code || '—'}</td>
                        <td className="px-2 py-1 whitespace-nowrap" title={`${r.branch_name || ''} · ${r.doc_number}`}>{r.supplier_name}</td>
                        <td className="px-2 py-1 tabular-nums">{q(r.discount_pct)}%</td>
                        <td className="px-2 py-1 whitespace-nowrap" title={r.cheaper_date}>
                          <b className="tabular-nums">{q(r.cheaper_discount_pct)}%</b> {r.cheaper_supplier}
                        </td>
                        <td className="px-2 py-1 tabular-nums text-amber-700">{q(r.gap_pct)}</td>
                        <td className="px-2 py-1 tabular-nums">{q(r.units)}</td>
                        <td className="px-2 py-1 tabular-nums font-semibold">{money(r.egp_above)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
    </div>
  )
}
