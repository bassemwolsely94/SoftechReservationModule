import { Outlet, NavLink, Navigate, useLocation } from 'react-router-dom'
import { ProcurementFilterProvider, ProcurementFilterBar } from '../components/ProcurementFilters'

const TABS = [
  { to: '/procurement/overview',  icon: '🛒', label: 'نظرة عامة'       },
  { to: '/procurement/history',   icon: '📜', label: 'سجل المشتريات'   },
  { to: '/procurement/segments',  icon: '🗂️', label: 'تصنيف الموردين'  },
  { to: '/procurement/categories', icon: '🏷️', label: 'الفئات والقواعد' },
  { to: '/procurement/foc',       icon: '🎁', label: 'FOC والتكلفة'    },
]

export default function ProcurementHubPage() {
  const { pathname } = useLocation()

  // Redirect bare /procurement to /procurement/overview
  if (pathname === '/procurement' || pathname === '/procurement/') {
    return <Navigate to="/procurement/overview" replace />
  }

  // The management tab manages the categories themselves — no analytics bar there.
  const showFilterBar = !pathname.startsWith('/procurement/categories')

  return (
    <ProcurementFilterProvider>
      <div className="flex flex-col h-full" dir="rtl">

        {/* ── Tab bar ───────────────────────────────────────────────────────── */}
        <div className="shrink-0 bg-white border-b border-gray-200 px-6 pt-0">
          <nav className="flex gap-0" aria-label="procurement tabs">
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

        {/* ── Shared filter bar (drives every analytics tab) ────────────────── */}
        {showFilterBar && <div className="shrink-0"><ProcurementFilterBar /></div>}

        {/* ── Active tab content ────────────────────────────────────────────── */}
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>

      </div>
    </ProcurementFilterProvider>
  )
}
