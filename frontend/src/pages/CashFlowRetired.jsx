/**
 * CashFlowRetired.jsx — Route: /finance/cashflow (P-43)
 *
 * The old cash-flow page was not used by finance and read a stale mirror. It is
 * removed from the finance tabs; saved links land here. When the 13-week cash
 * view (P-40) exists, this route redirects to it instead.
 */
import { Link } from 'react-router-dom'

export default function CashFlowRetired() {
  return (
    <div className="max-w-xl mx-auto mt-10 bg-white border border-gray-200 rounded-xl p-6 text-center" dir="rtl"
      data-tour="finance-cashflow-retired">
      <div className="text-3xl mb-2">🌊</div>
      <h2 className="text-lg font-bold text-gray-900 mb-1">صفحة التدفق النقدي اتشالت</h2>
      <p className="text-sm text-gray-600 mb-4">
        هتتبدّل بعرض النقدية لـ ١٣ أسبوع (قريباً). لحد ده استخدم الأرباح والخسائر والمصروفات.
      </p>
      <Link to="/finance/pnl" className="text-sm font-bold text-green-700 hover:underline">
        ← الأرباح والخسائر
      </Link>
    </div>
  )
}
