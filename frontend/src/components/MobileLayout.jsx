/**
 * MobileLayout.jsx — reusable full-screen phone shell for the standalone
 * mobile web surfaces (no desktop sidebar / hover-rail chrome).
 *
 * Generalizes the pattern first used by RiderLayout: a slim sticky top bar,
 * scrollable content, and a fixed bottom tab bar sized for a thumb. RTL +
 * safe-area aware (env(safe-area-inset-bottom) via the `pb-safe-bottom` util).
 *
 * Pass `tabs` to render the bottom navigation. Each tab: { to, label, icon,
 * roles?, badge? }. A tab with badge:'approvals' shows a live pending-approvals
 * count (operational engine + pricing/discount).
 * `title` is shown in the top bar (defaults to the active tab's label).
 */
import { useState } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import useAuthStore from '../store/authStore'
import { approvalsApi, pricingApprovalsApi, notificationsApi } from '../api/client'
import { useOnline, useOfflineQueue } from './mobileUi'

// Keep the bottom bar to 5 slots; beyond that, overflow into a "More" sheet.
const INLINE_MAX = 5

export default function MobileLayout({ title = 'صيدليات الرزيقي', tabs = [], children }) {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const online = useOnline()
  const { pending, toasts } = useOfflineQueue()
  const [moreOpen, setMoreOpen] = useState(false)
  const role = user?.role || 'viewer'
  const visibleTabs = tabs.filter(t => !t.roles || t.roles.includes(role))

  // Split into inline tabs + overflow ("More") when there are too many for the bar.
  const overflow    = visibleTabs.length > INLINE_MAX
  const inlineTabs  = overflow ? visibleTabs.slice(0, INLINE_MAX - 1) : visibleTabs
  const moreTabs    = overflow ? visibleTabs.slice(INLINE_MAX - 1) : []
  const moreActive  = moreTabs.some(t => location.pathname.startsWith(t.to))

  // Top-bar title reflects the active section (falls back to the app name).
  const activeTab   = visibleTabs.find(t => location.pathname === t.to || location.pathname.startsWith(t.to + '/'))
  const headerTitle = activeTab?.label || title

  // Live pending-approvals count for the approvals tab badge (operational + pricing).
  const wantsApprovalsBadge = visibleTabs.some(t => t.badge === 'approvals')
  const { data: approvalsCount = 0 } = useQuery({
    queryKey: ['m-approvals-count'],
    enabled: wantsApprovalsBadge,
    refetchInterval: 60_000,
    queryFn: async () => {
      const [op, hr, pricing] = await Promise.all([
        approvalsApi.pending({ category: 'operational' }).then(r => (r.data || []).length).catch(() => 0),
        approvalsApi.pending({ category: 'hr' }).then(r => (r.data || []).length).catch(() => 0),
        pricingApprovalsApi.pendingCount().then(r => {
          const d = r.data
          return typeof d === 'number' ? d : (d?.count ?? d?.pending ?? 0)
        }).catch(() => 0),
      ])
      return op + hr + pricing
    },
  })
  const badgeFor = (tab) => (tab.badge === 'approvals' ? approvalsCount : 0)

  // Notifications bell (top bar) — unread count.
  const { data: unread = 0 } = useQuery({
    queryKey: ['m-notif-unread'],
    refetchInterval: 60_000,
    queryFn: () => notificationsApi.unreadCount().then(r => r.data?.count ?? 0).catch(() => 0),
  })

  return (
    <div className="min-h-screen bg-gray-50 font-cairo flex flex-col" dir="rtl">

      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 bg-brand-600 text-white px-4 py-2.5 flex items-center justify-between shadow">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-7 h-7 bg-white/15 rounded-lg flex items-center justify-center shrink-0">
            <span className="text-white font-black text-sm leading-none">ر</span>
          </div>
          <div className="leading-tight min-w-0">
            <div className="font-bold text-sm truncate">{headerTitle}</div>
            <div className="text-[11px] text-white/70 truncate">
              {user?.full_name || user?.username}
              {user?.branch_name ? ` · ${user.branch_name}` : ''}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => navigate('/m/notifications')}
            className="relative w-9 h-9 flex items-center justify-center rounded-lg bg-white/15 active:bg-white/30"
            title="الإشعارات"
          >
            <span className="text-lg leading-none">🔔</span>
            {unread > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                {unread > 99 ? '99+' : unread}
              </span>
            )}
          </button>
          <button
            onClick={() => { logout(); navigate('/login') }}
            className="text-xs bg-white/15 hover:bg-white/25 active:bg-white/30 rounded-lg px-3 py-1.5 font-medium"
          >
            خروج
          </button>
        </div>
      </header>

      {/* Offline banner — queries auto-refetch on reconnect */}
      {!online && (
        <div className="bg-amber-500 text-white text-[11px] text-center py-1 font-medium">
          لا يوجد اتصال بالإنترنت — سيُعاد التحميل تلقائياً عند عودة الاتصال
          {pending > 0 && ` · ${pending} إجراء بانتظار المزامنة`}
        </div>
      )}

      {/* Pending-sync indicator when online but the queue hasn't drained yet */}
      {online && pending > 0 && (
        <div className="bg-blue-500 text-white text-[11px] text-center py-1 font-medium flex items-center justify-center gap-1.5">
          <span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          جارٍ مزامنة {pending} إجراء...
        </div>
      )}

      {/* Sync toasts (success / failure) — auto-dismiss */}
      {toasts.length > 0 && (
        <div className="fixed top-14 inset-x-0 z-50 flex flex-col items-center gap-1.5 px-3 pointer-events-none">
          {toasts.map(t => (
            <div
              key={t.id}
              className={`max-w-sm w-full text-center text-[12px] font-medium rounded-xl px-3 py-2 shadow-lg ${
                t.kind === 'ok' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
              }`}
            >
              {t.kind === 'ok' ? '✅ ' : '⚠️ '}{t.text}
            </div>
          ))}
        </div>
      )}

      {/* ── Content ──────────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto pb-20">{children ?? <Outlet />}</main>

      {/* ── Bottom tab bar ───────────────────────────────────────────────── */}
      {visibleTabs.length > 0 && (
        <nav className="fixed bottom-0 inset-x-0 z-30 bg-white border-t border-gray-200 flex pb-safe-bottom shadow-[0_-2px_8px_rgba(0,0,0,0.04)]">
          {inlineTabs.map(tab => {
            const count = badgeFor(tab)
            return (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={tab.end}
                className={({ isActive }) =>
                  `relative flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors ${
                    isActive ? 'text-brand-600' : 'text-gray-400 hover:text-gray-600'
                  }`
                }
              >
                <span className="relative text-xl leading-none">
                  {tab.icon}
                  {count > 0 && (
                    <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                      {count > 99 ? '99+' : count}
                    </span>
                  )}
                </span>
                <span>{tab.label}</span>
              </NavLink>
            )
          })}

          {overflow && (
            <button
              onClick={() => setMoreOpen(true)}
              className={`relative flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors ${
                moreActive ? 'text-brand-600' : 'text-gray-400'
              }`}
            >
              <span className="relative text-xl leading-none">
                ☰
                {moreTabs.reduce((n, t) => n + badgeFor(t), 0) > 0 && (
                  <span className="absolute -top-1.5 -right-2.5 w-2 h-2 rounded-full bg-red-500" />
                )}
              </span>
              <span>المزيد</span>
            </button>
          )}
        </nav>
      )}

      {/* "More" overflow sheet */}
      {moreOpen && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-end" onClick={() => setMoreOpen(false)}>
          <div className="bg-white rounded-t-2xl w-full p-3 pb-safe-bottom" dir="rtl" onClick={e => e.stopPropagation()}>
            <div className="grid grid-cols-3 gap-2">
              {moreTabs.map(tab => {
                const count = badgeFor(tab)
                return (
                  <NavLink
                    key={tab.to}
                    to={tab.to}
                    onClick={() => setMoreOpen(false)}
                    className={({ isActive }) =>
                      `relative flex flex-col items-center justify-center gap-1 py-4 rounded-xl border text-xs font-medium ${
                        isActive ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-gray-200 text-gray-600'
                      }`
                    }
                  >
                    <span className="text-2xl leading-none">{tab.icon}</span>
                    <span>{tab.label}</span>
                    {count > 0 && (
                      <span className="absolute top-1.5 left-1.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                        {count > 99 ? '99+' : count}
                      </span>
                    )}
                  </NavLink>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
