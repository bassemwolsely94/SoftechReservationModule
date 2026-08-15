/**
 * PortalLayout.jsx — lightweight RTL shell for the customer self-service portal.
 *
 * Own shell (NOT the staff MobileLayout). Guards: no portal session → /portal/login.
 * Registers the portal service worker for PWA installability.
 */
import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { portalToken } from '../../portal/portalApi'

const TABS = [
  { to: '/portal',         label: 'طلباتي',     icon: '📦', end: true },
  { to: '/portal/refills', label: 'إعادة الطلب', icon: '🔁' },
  { to: '/portal/loyalty', label: 'نقاطي',      icon: '⭐' },
]

export default function PortalLayout() {
  const navigate = useNavigate()

  useEffect(() => {
    if (!portalToken.get()) navigate('/portal/login', { replace: true })
  }, [navigate])

  useEffect(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/portal-sw.js').catch(() => {})
    }
  }, [])

  const logout = () => { portalToken.clear(); navigate('/portal/login', { replace: true }) }

  return (
    <div className="min-h-screen bg-gray-50 font-cairo flex flex-col" dir="rtl">
      <header className="bg-brand-600 text-white px-4 py-3 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-white/15 rounded-lg flex items-center justify-center"><span className="font-black">ر</span></div>
          <div className="font-bold text-sm">صيدليات الرزيقي</div>
        </div>
        <button onClick={logout} className="text-xs bg-white/15 rounded-lg px-3 py-1.5">خروج</button>
      </header>

      <main className="flex-1 p-4 pb-24"><Outlet /></main>

      <nav className="fixed bottom-0 inset-x-0 bg-white border-t border-gray-200 grid grid-cols-3">
        {TABS.map(t => (
          <NavLink
            key={t.to} to={t.to} end={t.end}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 py-2.5 text-[11px] ${isActive ? 'text-brand-600 font-bold' : 'text-gray-400'}`}
          >
            <span className="text-lg">{t.icon}</span>{t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
