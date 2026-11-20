/**
 * MarginBoard — the sales dashboard's «💹 الهامش: قناة × فرع» tab (C19 / P-35).
 *
 * Rows = sales channels, columns = branches; each cell shows the margin on the ONE VAT-aligned basis
 * (apps/analytics/margin.py) with the old VAT-inclusive margin beside it. Every number comes from the server; this
 * only lays it out. Read-only.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '../api/client'
import useBranchLabels from '../hooks/useBranchLabels'

const fmt = (v) => Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const pct = (v) => `${Number(v || 0).toFixed(1)}%`

function Cell({ c, strong }) {
  if (!c) return <td className="px-2 py-1.5 text-center text-gray-300">—</td>
  return (
    <td className={`px-2 py-1.5 text-center ${strong ? 'bg-gray-50 font-semibold' : ''}`}
        title={`إيراد ${fmt(c.revenue)} (بدون ضريبة ${fmt(c.revenue_ex_vat)}) · تكلفة ${fmt(c.cogs)} · ربح ${fmt(c.profit_ex_vat)}`}>
      <div className="font-mono text-green-700">{pct(c.margin_ex_vat_pct)}</div>
      <div className="text-[11px] text-gray-500 font-mono">{fmt(c.profit_ex_vat)} جم</div>
      <div className="text-[10px] text-gray-400 font-mono">بالضريبة {pct(c.margin_incl_vat_pct)}</div>
    </td>
  )
}

export default function MarginBoard({ params }) {
  const bl = useBranchLabels()
  const [sort, setSort] = useState(null)        // {key, dir} — a column's ex-VAT margin; null = by revenue
  const { data, isLoading, isError } = useQuery({
    queryKey: ['analytics-margin-board', params],
    queryFn: () => analyticsApi.marginBoard(params).then(r => r.data),
    staleTime: 60_000,
    retry: 1,
  })
  const rows = useMemo(() => {
    const list = [...(data?.rows || [])]
    if (!sort) return list
    const val = (r) => (sort.key === '__total__' ? r.total : r.cells[sort.key])?.margin_ex_vat_pct ?? -Infinity
    return list.sort((a, b) => (sort.dir === 'asc' ? 1 : -1) * (val(a) - val(b)))
  }, [data, sort])
  const onSort = (key) => setSort(s => (!s || s.key !== key ? { key, dir: 'desc' }
    : s.dir === 'desc' ? { key, dir: 'asc' } : null))
  const arrow = (key) => (sort?.key === key ? (sort.dir === 'desc' ? ' ▼' : ' ▲') : '')
  if (isLoading) return <div className="text-center py-10 text-gray-400 animate-pulse">جارٍ التحميل…</div>
  if (isError || !data) return <div className="text-center py-10 text-red-600">تعذّر تحميل اللوحة</div>
  const cols = data.columns || []
  const colLabel = (c) => c.label || bl(c.branch_code)
  return (
    <div className="space-y-3" data-tour="analytics-sales-margin-board">
      <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg p-3 leading-6">
        الهامش على أساس واحد: {data.basis_label}. السطر الصغير «بالضريبة» = الحساب القديم (الإيراد شامل الضريبة − التكلفة)
        للمقارنة. صافي = مبيعات − مردودات، بنفس فلاتر الصفحة. للعرض فقط — لا يغيّر أي سعر أو خصم.
      </div>
      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full text-sm whitespace-nowrap">
          <thead className="bg-gray-50 text-xs text-gray-600">
            <tr>
              <th className="px-2 py-2 text-right">القناة</th>
              {cols.map(c => (
                <th key={c.key} className="px-2 py-2 text-center cursor-pointer select-none" onClick={() => onSort(c.key)}>
                  {colLabel(c)}{arrow(c.key)}
                </th>
              ))}
              <th className="px-2 py-2 text-center cursor-pointer select-none" onClick={() => onSort('__total__')}>الإجمالي{arrow('__total__')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.channel_code || '-'} className="border-t border-gray-100">
                <td className="px-2 py-1.5 font-medium text-gray-800">{r.channel_label}</td>
                {cols.map(c => <Cell key={c.key} c={r.cells[c.key]} />)}
                <Cell c={r.total} strong />
              </tr>
            ))}
            <tr className="border-t-2 border-gray-300">
              <td className="px-2 py-1.5 font-bold">الإجمالي</td>
              {cols.map(c => <Cell key={c.key} c={data.column_totals[c.key]} strong />)}
              <Cell c={data.total} strong />
            </tr>
            <tr className="border-t border-gray-100 text-xs text-gray-600">
              <td className="px-2 py-1.5">رسوم التوصيل (وحدة التوصيل)</td>
              {cols.map(c => (
                <td key={c.key} className="px-2 py-1.5 text-center font-mono">
                  {c.branch_code ? `${fmt(data.delivery_fees?.[c.branch_code])} جم` : '—'}
                </td>
              ))}
              <td className="px-2 py-1.5 text-center font-mono">
                {fmt(Object.values(data.delivery_fees || {}).reduce((s, v) => s + v, 0))} جم
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
