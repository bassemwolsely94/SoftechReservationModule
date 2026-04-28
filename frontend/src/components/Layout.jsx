import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import useAuthStore from '../store/authStore'
import { useQuery } from '@tanstack/react-query'
import { syncApi } from '../api/client'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'
import NotificationPanel from './NotificationPanel'

const NAV = [
  { to: '/dashboard',    icon: '◈',  label: 'الرئيسية',             roles: null },
  { to: '/reservations', icon: '📋', label: 'الحجوزات',             roles: null },
  { to: '/transfers',    icon: '🔀', label: 'طلبات التحويل',        roles: null },
  { to: '/purchasing',   icon: '📊', label: 'لوحة المشتريات',      roles: ['admin', 'purchasing'] },
  { to: '/customers',    icon: '👥', label: 'العملاء',               roles: null },
  { to: '/sync',         icon: '⟳',  label: 'المزامنة',             roles: ['admin'] },
]

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)

  const { data: syncStatus } = useQuery({
    queryKey: ['syncStatus'],
    queryFn: () => syncApi.status().then(r => r.data),
    refetchInterval: 60_000,
  })

  const handleLogout = () => { logout(); navigate('/login') }
  const userRole = user?.role || 'viewer'
  const visibleNav = NAV.filter(n => !n.roles || n.roles.includes(userRole))

  return (
    <div className="flex min-h-screen bg-gray-50 font-cairo" dir="rtl">

      {/* Sidebar */}
      <aside className={`flex flex-col bg-brand-700 text-white transition-all duration-200 ${collapsed ? 'w-16' : 'w-60'}`}>

        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-brand-600">
          <div className="w-9 h-9 bg-white rounded-lg flex items-center justify-center flex-shrink-0">
            <span className="text-brand-700 font-black text-lg">ر</span>
          </div>
          {!collapsed && (
            <div>
              <div className="font-bold text-sm leading-tight">صيدليات الرزيقي</div>
              <div className="text-brand-300 text-xs">منصة العمليات</div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-4 space-y-0.5 px-2">
          {visibleNav.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150
                ${isActive
                  ? 'bg-white text-brand-700 shadow-sm'
                  : 'text-brand-100 hover:bg-brand-600'
                }`
              }
            >
              <span className="text-base w-5 text-center flex-shrink-0">{item.icon}</span>
              {!collapsed && <span className="flex-1">{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Sync status */}
        {!collapsed && syncStatus && (
          <div className="px-4 py-3 border-t border-brand-600">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                syncStatus.status === 'success' ? 'bg-green-400' :
                syncStatus.status === 'running' ? 'bg-yellow-400 animate-pulse' : 'bg-red-400'
              }`} />
              <div className="text-xs text-brand-300 truncate">
                {syncStatus.last_at
                  ? `آخر مزامنة ${formatDistanceToNow(new Date(syncStatus.last_at), { locale: ar, addSuffix: true })}`
                  : 'لم تتم مزامنة بعد'
                }
              </div>
            </div>
          </div>
        )}

        {/* User footer */}
        <div className="px-3 py-4 border-t border-brand-600">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-brand-500 flex items-center justify-center flex-shrink-0">
              <span className="text-white text-sm font-bold">
                {(user?.full_name || user?.username || '?')[0]}
              </span>
            </div>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-white truncate">
                  {user?.full_name || user?.username}
                </div>
                <div className="text-xs text-brand-300 truncate">
                  {user?.branch_name || user?.role}
                </div>
              </div>
            )}
            {!collapsed && <NotificationPanel collapsed={collapsed} />}
            {!collapsed && (
              <button
                onClick={handleLogout}
                className="text-brand-300 hover:text-white transition-colors flex-shrink-0"
                title="تسجيل الخروج"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(c => !c)}
          className="w-full py-2 text-brand-300 hover:text-white hover:bg-brand-600 transition-colors text-xs border-t border-brand-600"
        >
          {collapsed ? '◀' : '▶'}
        </button>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}
