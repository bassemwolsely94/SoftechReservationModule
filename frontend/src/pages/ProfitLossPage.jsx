/**
 * ProfitLossPage.jsx
 * Route: /finance/pnl
 *
 * P&L Statement — Revenue → COGS → Gross Profit → Expenses → Net Profit
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { financeApi } from '../api/client'

const fmt  = (n, d = 0) => parseFloat(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const pct  = (n, d = 1) => `${fmt(n, d)}%`

function PnlRow({ label, value, indent = 0, bold = false, separator = false, color }) {
  const colorClass = color === 'green' ? 'text-green-700'
    : color === 'red'   ? 'text-red-600'
    : color === 'blue'  ? 'text-blue-700'
    : 'text-gray-800'

  return (
    <>
      {separator && <tr><td colSpan={2} className="py-2"><div className="border-t border-gray-200" /></td></tr>}
      <tr className="hover:bg-gray-50">
        <td className={`px-4 py-2 text-sm ${bold ? 'font-semibold' : ''} ${colorClass}`}
            style={{ paddingRight: `${16 + indent * 16}px` }}>
          {label}
        </td>
        <td className={`px-4 py-2 text-sm text-left ${bold ? 'font-semibold' : ''} ${colorClass}`}>
          {value}
        </td>
      </tr>
    </>
  )
}

export default function ProfitLossPage() {
  const today = new Date()
  const [year,  setYear]  = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)

  const MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
  const YEARS     = Array.from({ length: 5 }, (_, i) => today.getFullYear() - i)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['finance-pnl', year, month],
    queryFn:  () => financeApi.pnl({ year, month }).then(r => r.data),
    staleTime: 60_000,
  })

  return (
    <div className="space-y-5" dir="rtl">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold text-gray-700">قائمة الأرباح والخسائر</h2>
        <div className="flex gap-2 mr-auto">
          <select value={year} onChange={e => setYear(Number(e.target.value))}
            className="border rounded-lg px-3 py-1.5 text-sm">
            {YEARS.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <select value={month} onChange={e => setMonth(Number(e.target.value))}
            className="border rounded-lg px-3 py-1.5 text-sm">
            {MONTHS_AR.map((m, i) => <option key={i+1} value={i+1}>{m}</option>)}
          </select>
        </div>
      </div>

      {isLoading && <div className="text-center py-16 text-gray-400 animate-pulse">جارٍ التحميل…</div>}
      {isError   && <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">تعذّر التحميل. قم بتشغيل المزامنة أولاً.</div>}

      {data && !isLoading && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden max-w-2xl">
          {/* Header */}
          <div className="bg-green-700 text-white px-4 py-3">
            <div className="font-bold text-base">قائمة الأرباح والخسائر</div>
            <div className="text-sm text-green-200">
              {data.period} — {data.branch || 'موحد (جميع الفروع)'}
            </div>
          </div>

          <table className="w-full">
            <tbody>
              {/* Revenue */}
              <PnlRow label="الإيرادات" bold separator />
              <PnlRow label="إجمالي المبيعات"    value={fmt(data.revenue?.gross_revenue)} indent={1} />
              <PnlRow label="المرتجعات"           value={`(${fmt(data.revenue?.returns_value)})`} indent={1} color="red" />
              <PnlRow label="صافي الإيرادات"      value={fmt(data.revenue?.net_revenue)} indent={1} bold color="blue" />

              {/* COGS */}
              <PnlRow label="تكلفة البضاعة المباعة" bold separator />
              <PnlRow label="إجمالي المشتريات"    value={fmt(data.cogs?.total_purchases)} indent={1} />
              <PnlRow label="مرتجعات المشتريات"   value={`(${fmt(data.cogs?.total_purchase_returns)})`} indent={1} color="red" />
              <PnlRow label="صافي المشتريات (تكلفة)" value={fmt(data.cogs?.net_purchases)} indent={1} bold />

              {/* Gross Profit */}
              <PnlRow label="إجمالي الربح"
                value={`${fmt(data.gross_profit)}  (${pct(data.gross_margin_pct)})`}
                bold separator
                color={parseFloat(data.gross_profit) >= 0 ? 'green' : 'red'}
              />

              {/* Expenses */}
              <PnlRow label="المصروفات التشغيلية" bold separator />
              <PnlRow label="الرواتب"              value={fmt(data.expenses?.payroll)}    indent={1} />
              <PnlRow label="الإيجارات"            value={fmt(data.expenses?.rent)}       indent={1} />
              <PnlRow label="المرافق"              value={fmt(data.expenses?.utilities)}  indent={1} />
              <PnlRow label="مصروفات أخرى"        value={fmt(data.expenses?.other)}      indent={1} />
              <PnlRow label="إجمالي المصروفات"     value={`(${fmt(data.expenses?.total)})`} indent={1} bold color="red" />

              {/* Profits */}
              <PnlRow label="الربح التشغيلي" value={fmt(data.operating_profit)} bold separator
                color={parseFloat(data.operating_profit) >= 0 ? 'green' : 'red'} />
              <PnlRow label="EBITDA"         value={fmt(data.ebitda)} indent={1} />
              <PnlRow label="صافي الربح"
                value={`${fmt(data.net_profit)}  (${pct(data.net_margin_pct)})`}
                bold separator
                color={parseFloat(data.net_profit) >= 0 ? 'green' : 'red'}
              />
            </tbody>
          </table>

          {!data.is_complete && (
            <div className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
              ⚠ بيانات جزئية — بعض مصادر البيانات لم تُزامن بعد
            </div>
          )}
        </div>
      )}
    </div>
  )
}
