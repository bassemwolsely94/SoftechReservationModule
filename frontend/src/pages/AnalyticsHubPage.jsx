import { Outlet, NavLink, Navigate, useLocation } from 'react-router-dom'

const TABS = [
  { to: '/analytics/sales',         icon: '📈', label: 'المبيعات'       },
  { to: '/analytics/performance',   icon: '🏆', label: 'أداء الموظفين'  },
  { to: '/analytics/reservations',  icon: '📋', label: 'الحجوزات'       },
  { to: '/analytics/transfers',     icon: '🔀', label: 'التحويلات'      },
]

export default function AnalyticsHubPage() {
  const { pathname } = useLocation()

  // Redirect bare /analytics to /analytics/sales
  if (pathname === '/analytics' || pathname === '/analytics/') {
    return <Navigate to="/analytics/sales" replace />
  }

  return (
    <div className="flex flex-col h-full" dir="rtl">

      {/* ── Tab bar ───────────────────────────────────────────────────────── */}
      <div className="shrink-0 bg-white border-b border-gray-200 px-6 pt-0">
        <nav className="flex gap-0" aria-label="analytics tabs">
          {TABS.map(tab => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                `flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap
                ${isActive
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`
              }
            >
              <span className="text-base">{tab.icon}</span>
              <span>{tab.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* ── Active tab content ────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        <Outlet />
      </div>

    </div>
  )
}
