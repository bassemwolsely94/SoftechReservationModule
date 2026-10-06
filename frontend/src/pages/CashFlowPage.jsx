/**
 * CashFlowPage.jsx
 * Route: /finance/cashflow
 *
 * Cash flow summary: inflow, outflow, net — by payment method.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { financeApi } from '../api/client'

const fmt = (n, d = 0) => parseFloat(n || 0).toLocaleString('en-US', {
  minimumFractionDigits: d, maximumFractionDigits: d,
})

const METHOD_LABELS = {
  cash:     'نقدي',
  cheque:   'شيك',
  transfer: 'تحويل بنكي',
  card:     'بطاقة',
  credit:   'آجل',
  other:    'أخرى',
}

const METHOD_ICONS = {
  cash: '💵', cheque: '📝', transfer: '🏦', card: '💳', credit: '📋', other: '🔹',
}

function CashBar({ label, value, total, color }) {
  const pct = total > 0 ? Math.max(2, (value / total) * 100) : 0
  return (
    <div className="flex items-center gap-3">
      <div className="w-28 text-sm text-gray-600 text-right shrink-0">{label}</div>
      <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <div className="w-28 text-sm text-gray-700 font-medium text-left shrink-0">{fmt(value)}</div>
    </div>
  )
}

export default function CashFlowPage() {
  const today = new Date()
  const [year,  setYear]  = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)

  const MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
  const YEARS     = Array.from({ length: 5 }, (_, i) => today.getFullYear() - i)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['finance-cashflow', year, month],
    queryFn:  () => financeApi.cashFlow({ year, month }).then(r => r.data),
    staleTime: 60_000,
  })

  // Derive inflow / outflow by method from by_method array
  const byMethod = data?.by_method || []
  const inflowByMethod  = byMethod.filter(r => r.direction === 'in')
  const outflowByMethod = byMethod.filter(r => r.direction === 'out')
  const totalInflow  = inflowByMethod.reduce((s, r)  => s + parseFloat(r.total || 0), 0)
  const totalOutflow = outflowByMethod.reduce((s, r) => s + parseFloat(r.total || 0), 0)

  return (
    <div className="space-y-6" dir="rtl">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold text-gray-700">التدفقات النقدية</h2>
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
      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
          لا توجد بيانات حركات الخزينة. قم بتشغيل المزامنة أولاً.
        </div>
      )}

      {data && !isLoading && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
              <div className="text-xs text-gray-500 mb-1">إجمالي التدفق الداخل</div>
              <div className="text-xl font-bold text-green-700">↑ {fmt(data.cash_inflow || totalInflow)}</div>
            </div>
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
              <div className="text-xs text-gray-500 mb-1">إجمالي التدفق الخارج</div>
              <div className="text-xl font-bold text-red-600">↓ {fmt(data.cash_outflow || totalOutflow)}</div>
            </div>
            <div className={`border rounded-xl p-4 text-center
              ${parseFloat(data.net_cash_flow) >= 0
                ? 'bg-blue-50 border-blue-200'
                : 'bg-orange-50 border-orange-200'
              }`}>
              <div className="text-xs text-gray-500 mb-1">صافي التدفق</div>
              <div className={`text-xl font-bold ${parseFloat(data.net_cash_flow) >= 0 ? 'text-blue-700' : 'text-orange-600'}`}>
                {fmt(data.net_cash_flow)}
              </div>
            </div>
          </div>

          {/* By Method breakdown */}
          {byMethod.length > 0 ? (
            <div className="grid sm:grid-cols-2 gap-5">
              {/* Inflow */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-sm font-semibold text-green-700 mb-4">التدفق الداخل — بطريقة الدفع</h3>
                <div className="space-y-3">
                  {inflowByMethod.length === 0
                    ? <div className="text-gray-400 text-sm text-center py-4">لا توجد تدفقات داخلة</div>
                    : inflowByMethod.map(r => (
                        <CashBar
                          key={r.payment_method}
                          label={`${METHOD_ICONS[r.payment_method] || '🔹'} ${METHOD_LABELS[r.payment_method] || r.payment_method}`}
                          value={r.total}
                          total={totalInflow}
                          color="#10b981"
                        />
                      ))
                  }
                </div>
              </div>

              {/* Outflow */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-sm font-semibold text-red-600 mb-4">التدفق الخارج — بطريقة الدفع</h3>
                <div className="space-y-3">
                  {outflowByMethod.length === 0
                    ? <div className="text-gray-400 text-sm text-center py-4">لا توجد تدفقات خارجة</div>
                    : outflowByMethod.map(r => (
                        <CashBar
                          key={r.payment_method}
                          label={`${METHOD_ICONS[r.payment_method] || '🔹'} ${METHOD_LABELS[r.payment_method] || r.payment_method}`}
                          value={r.total}
                          total={totalOutflow}
                          color="#ef4444"
                        />
                      ))
                  }
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
              <div className="text-4xl mb-2">🏦</div>
              <div className="text-amber-800 text-sm font-medium">
                لم تُكتشف جداول الخزينة بعد. قم بتشغيل Phase 0 Discovery لاكتشاف جداول الدفع في SOFTECH.
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
