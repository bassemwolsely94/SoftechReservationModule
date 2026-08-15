/**
 * RiderLayout.jsx — minimal full-screen shell for the rider on a phone.
 * No sidebar / desktop chrome — just a slim top bar + the screen content,
 * sized for a smartphone browser.
 */
import { useNavigate } from 'react-router-dom'
import useAuthStore from '../store/authStore'

export default function RiderLayout({ children }) {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-50 font-cairo flex flex-col" dir="rtl">
      <header className="sticky top-0 z-30 bg-brand-600 text-white px-4 py-2.5 flex items-center justify-between shadow">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg">🛵</span>
          <div className="leading-tight min-w-0">
            <div className="font-bold text-sm truncate">صيدليات الرزيقي</div>
            <div className="text-[11px] text-white/70 truncate">{user?.full_name || user?.username}</div>
          </div>
        </div>
        <button
          onClick={() => { logout(); navigate('/login') }}
          className="text-xs bg-white/15 hover:bg-white/25 rounded-lg px-3 py-1.5 font-medium shrink-0"
        >
          خروج
        </button>
      </header>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
