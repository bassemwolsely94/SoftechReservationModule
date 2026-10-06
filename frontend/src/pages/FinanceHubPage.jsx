/**
 * FinanceHubPage.jsx
 * Route: /finance  (nested layout — child pages render via <Outlet />)
 *
 * Tabs:
 *   Dashboard   /finance/dashboard
 *   P&L         /finance/pnl
 *   Cash Flow   /finance/cashflow
 *   Expenses    /finance/expenses
 *   COA         /finance/coa
 *   Schema      /finance/schema   (admin only)
 */

import { Outlet, NavLink, useLocation } from 'react-router-dom'
import useAuthStore from '../store/authStore'

const TABS = [
  { to: '/finance/dashboard', label: 'لوحة القيادة',     icon: '💹' },
  { to: '/finance/pnl',       label: 'الأرباح والخسائر', icon: '📊' },
  { to: '/finance/cashflow',  label: 'التدفق النقدي',    icon: '🌊' },
  { to: '/finance/expenses',  label: 'المصروفات',        icon: '💸' },
  { to: '/finance/coa',       label: 'دليل الحسابات',    icon: '🗂️' },
  { to: '/finance/schema',    label: 'اكتشاف المخطط',   icon: '🔍', adminOnly: true },
]

export default function FinanceHubPage() {
  const { user } = useAuthStore()
  const role = user?.role || ''
  const isAdmin = ['admin'].includes(role)

  const visibleTabs = TABS.filter(t => !t.adminOnly || isAdmin)

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-6 pt-5 pb-0 shadow-sm">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-3xl">💹</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">الذكاء المالي</h1>
            <p className="text-sm text-gray-500">
              منصة التحليل المالي والرؤى الاستراتيجية — مصدر البيانات: SOFTECH
            </p>
          </div>
        </div>

        {/* ── Tab bar ───────────────────────────────────────────────────────── */}
        <nav className="flex gap-1 overflow-x-auto">
          {visibleTabs.map(tab => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium rounded-t-lg
                 border-b-2 whitespace-nowrap transition-colors
                 ${isActive
                   ? 'border-green-600 text-green-700 bg-green-50'
                   : 'border-transparent text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                 }`
              }
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* ── Tab content ─────────────────────────────────────────────────────── */}
      <div className="p-6">
        <Outlet />
      </div>
    </div>
  )
}
