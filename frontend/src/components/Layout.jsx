import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import useAuthStore from '../store/authStore'
import useNotificationStore from '../store/notificationStore'
import { useQuery } from '@tanstack/react-query'
import { syncApi } from '../api/client'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'
import NotificationBell from './NotificationBell'
import ModuleNotificationBell from './ModuleNotificationBell'
import BrandMark from './BrandMark'

const toLatinDigits = s =>
  s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// Per-module sidebar notification hints (quiet feeds kept out of the main bell).
// Maps a nav route to its notification category. delivery/transfers/reservations
// are NOT here — they ride the alarming main bell now.
const ROUTE_CATEGORY = {
  '/demand': 'demand', '/followups': 'followups',
}

// ── Group icons (SVG) ─────────────────────────────────────────────────────────
const GroupIcon = ({ id, size = 20 }) => {
  const cls = `w-[${size}px] h-[${size}px]`
  const icons = {
    home: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <path d="M3 12L12 3l9 9"/><path d="M9 21V12h6v9"/><path d="M3 12v9h18V12"/>
      </svg>
    ),
    operations: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="8" rx="1"/>
        <rect x="3" y="13" width="8" height="8" rx="1"/><rect x="13" y="13" width="8" height="8" rx="1"/>
      </svg>
    ),
    callcenter: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 10.8 19.79 19.79 0 01.01 2.22 2 2 0 012 .04h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.09 7.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 14.92v2z"/>
      </svg>
    ),
    customers: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>
      </svg>
    ),
    inventory: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
        <polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>
      </svg>
    ),
    purchasing: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/>
        <path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/>
      </svg>
    ),
    analytics: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/>
      </svg>
    ),
    finance: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>
      </svg>
    ),
    hr: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>
      </svg>
    ),
    admin: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.07 4.93a10 10 0 010 14.14M4.93 4.93a10 10 0 000 14.14"/>
        <path d="M12 2a10 10 0 100 20A10 10 0 0012 2z" strokeDasharray="2 4"/>
      </svg>
    ),
  }
  return icons[id] || <span className="text-base">{id}</span>
}

// ── Navigation data ───────────────────────────────────────────────────────────
const NAV_GROUPS = [
  {
    id: 'home', label: 'الرئيسية', section: null,
    items: [
      { to: '/dashboard', icon: '◈', label: 'الرئيسية', roles: null },
      { to: '/me',        icon: '🙋', label: 'لوحتي الشخصية', roles: null },
    ],
  },
  {
    id: 'operations', label: 'العمليات', section: 'العمليات',
    items: [
      { to: '/pos',           icon: '🧾', label: 'نقطة البيع',        roles: ['admin','call_center','pharmacist','salesperson','supervisor'] },
      { to: '/reservations',  icon: '📋', label: 'الحجوزات',         roles: ['admin','call_center','pharmacist','salesperson','supervisor','viewer','quality_manager'] },
      { to: '/transfers',     icon: '🔀', label: 'طلبات التحويل',    roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/transits',      icon: '🚛', label: 'التحويلات قيد النقل', roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/demand',        icon: '🔍', label: 'الطلب الضائع',     roles: ['admin','call_center','pharmacist','salesperson','supervisor','viewer','quality_manager'] },
      { to: '/followups',     icon: '💊', label: 'متابعة المزمن',    roles: ['admin','call_center','pharmacist','salesperson','supervisor','quality_manager'] },
      { to: '/delivery',      icon: '🚚', label: 'توصيل الطلبات',    roles: ['admin','pharmacist','delivery','call_center','supervisor','quality_manager'] },
      { to: '/delivery/dispatch', icon: '🧭', label: 'لوحة التوزيع',  roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/rider',         icon: '🛵', label: 'مهام السائق',       roles: ['admin','delivery','supervisor'] },
      { to: '/stock-count',   icon: '📦', label: 'الجرد الفعلي',     roles: ['admin','pharmacist','supervisor','quality_manager'] },
      { to: '/tasks',         icon: '✅', label: 'المهام التشغيلية', roles: ['admin','call_center','pharmacist','supervisor'] },
      { to: '/announcements', icon: '📢', label: 'الإعلانات',        roles: null },
    ],
  },
  {
    id: 'callcenter', label: 'مركز الاتصال', section: 'مركز الاتصال',
    items: [
      { to: '/omni/inbox',            icon: '📥', label: 'الصندوق الموحد',  roles: ['admin','call_center','supervisor'] },
      { to: '/omni/accounts',         icon: '📡', label: 'حسابات القنوات',  roles: ['admin','supervisor'] },
      { to: '/omni/wallboard',        icon: '📊', label: 'لوحة المشرف',     roles: ['admin','supervisor','quality_manager'] },
      { to: '/omni/automations',      icon: '⚙️', label: 'الأتمتة',         roles: ['admin','supervisor'] },
      { to: '/omni/analytics',        icon: '📈', label: 'تحليلات التواصل', roles: ['admin','supervisor','quality_manager'] },
      { to: '/callcenter',            icon: '📞', label: 'الحالات',         roles: ['admin','call_center','supervisor'] },
      { to: '/callcenter/analytics',  icon: '📊', label: 'جودة الاتصال',    roles: ['admin','supervisor','quality_manager'] },
      { to: '/campaigns',             icon: '📱', label: 'حملات واتساب',    roles: ['admin','call_center','supervisor','purchasing'] },
      { to: '/whatsapp/inbox',        icon: '💬', label: 'صندوق واتساب',    roles: ['admin','call_center','supervisor'] },
      { to: '/pbx/live',              icon: '☎️', label: 'المكالمات الحية', roles: ['admin','call_center','supervisor'] },
    ],
  },
  {
    id: 'customers', label: 'العملاء', section: 'العملاء',
    items: [
      { to: '/customers',          icon: '👥', label: 'العملاء',             roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager','delivery'] },
      { to: '/vouchers',           icon: '🎫', label: 'القسائم',             roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','quality_manager'] },
      { to: '/loyalty',            icon: '🏆', label: 'النقاط والولاء',      roles: ['admin','call_center','pharmacist','salesperson','supervisor'] },
      { to: '/loyalty/branch',     icon: '🔍', label: 'استعلام نقاط الفرع', roles: ['admin','branch','pharmacist','supervisor'] },
      { to: '/referral',           icon: '🔗', label: 'الإحالات',            roles: ['admin','call_center','supervisor'] },
    ],
  },
  {
    id: 'inventory', label: 'المخزون', section: 'المخزون',
    items: [
      { to: '/products',             icon: '💊', label: 'المنتجات',        roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/inventory',            icon: '🗃️', label: 'لوحة المخزون',   roles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/batches',              icon: '🧪', label: 'الدفعات والانتهاء', roles: ['admin','pharmacist','purchasing','quality_manager','supervisor'] },
      { to: '/shortage',             icon: '🚨', label: 'النواقص',         roles: ['admin','pharmacist','call_center','salesperson','purchasing','supervisor','quality_manager'] },
      { to: '/catalog-intelligence', icon: '🧠', label: 'ذكاء الكتالوج',   roles: ['admin','pharmacist','purchasing'] },
      { to: '/chronic-classifier',   icon: '🧬', label: 'الأدوية المزمنة',  roles: ['admin','pharmacist','call_center','supervisor'] },
      { to: '/image-enrichment',     icon: '🖼️', label: 'صور المنتجات',   roles: ['admin','pharmacist','purchasing'] },
      { to: '/recommendations',      icon: '🔗', label: 'التوصيات الذكية', roles: ['admin','pharmacist','call_center','purchasing'] },
    ],
  },
  {
    id: 'purchasing', label: 'المشتريات', section: 'المشتريات',
    items: [
      { to: '/purchasing',        icon: '📊', label: 'توصيات الشراء',    roles: ['admin','purchasing','viewer'] },
      { to: '/procurement',       icon: '🛒', label: 'ذكاء المشتريات',   roles: ['admin','purchasing'] },
      { to: '/invoices',          icon: '🧾', label: 'فواتير الموردين',   roles: ['admin','purchasing'] },
      { to: '/pricing-approvals', icon: '🏷️', label: 'موافقات الأسعار', roles: ['admin','purchasing','pharmacist'] },
      { to: '/discount-alignment', icon: '🎯', label: 'مطابقة الخصومات', roles: ['admin','purchasing','pharmacist'] },
    ],
  },
  {
    id: 'analytics', label: 'التحليلات', section: 'التحليلات',
    items: [
      { to: '/analytics',   icon: '📈', label: 'المبيعات والأداء', roles: ['admin','purchasing','pharmacist','supervisor','quality_manager','viewer'] },
      { to: '/forecasting', icon: '🔮', label: 'التنبؤ بالطلب',   roles: ['admin','purchasing','pharmacist','quality_manager'] },
      { to: '/incentives',  icon: '💰', label: 'الحوافز',          roles: ['admin','purchasing','quality_manager'] },
      { to: '/my-incentives', icon: '🏅', label: 'حوافزي',         roles: null },
      { to: '/targets',     icon: '🎯', label: 'الأهداف البيعية',  roles: ['admin','supervisor','purchasing','pharmacist','quality_manager','viewer'] },
      { to: '/kpi-board',   icon: '📊', label: 'لوحة مؤشرات الفروع', roles: ['admin','supervisor','purchasing','pharmacist','quality_manager','viewer'] },
      { to: '/forecast-scenarios', icon: '🔮', label: 'سيناريوهات التنبؤ', roles: ['admin','supervisor','purchasing'] },
      { to: '/insights',    icon: '📋', label: 'التقارير السردية', roles: ['admin','supervisor','purchasing','quality_manager','viewer'] },
    ],
  },
  {
    id: 'finance', label: 'المالية', section: 'المالية',
    items: [
      { to: '/finance',        icon: '💹', label: 'الذكاء المالي',   roles: ['admin','purchasing','pharmacist','quality_manager'] },
      { to: '/cheques',        icon: '📝', label: 'تخطيط الشيكات',  roles: ['admin','purchasing','pharmacist'] },
      { to: '/payments',       icon: '💳', label: 'متابعة المدفوعات', roles: ['admin','purchasing','pharmacist'] },
      { to: '/payment-audit',  icon: '🏦', label: 'مراجعة الكشوف',  roles: ['admin','purchasing','pharmacist'] },
      { to: '/insurance',      icon: '🏥', label: 'مطالبات التأمين', roles: ['admin','purchasing'] },
    ],
  },
  {
    id: 'hr', label: 'الموارد البشرية', section: 'الموارد البشرية',
    items: [
      { to: '/hr',        icon: '👨‍💼', label: 'الإجازات والطلبات', roles: null },
      { to: '/approvals', icon: '✔️', label: 'صندوق الموافقات',    roles: ['admin','supervisor','pharmacist','quality_manager','purchasing'] },
    ],
  },
  {
    id: 'admin', label: 'الإدارة', section: 'الإدارة',
    items: [
      { to: '/audit',            icon: '🛡️', label: 'المراجعة والأمان', roles: ['admin','supervisor','quality_manager'] },
      { to: '/users',            icon: '👤', label: 'المستخدمون',        roles: ['admin','supervisor'] },
      { to: '/permissions',      icon: '🔐', label: 'الصلاحيات',         roles: ['admin'] },
      { to: '/erp-permissions',  icon: '🧩', label: 'صلاحيات Softech',   roles: ['admin'] },
      { to: '/settings',         icon: '⚙️', label: 'الإعدادات',         roles: ['admin','pharmacist'] },
      { to: '/sync',             icon: '⟳', label: 'المزامنة',            roles: ['admin'] },
    ],
  },
]

// Find which group owns a given pathname
function groupForPath(pathname, groups) {
  for (const g of groups) {
    for (const item of g.items) {
      if (pathname === item.to || pathname.startsWith(item.to + '/')) return g.id
    }
  }
  return null
}

export default function Layout() {
  const { user, logout } = useAuthStore()
  const moduleCounts = useNotificationStore(s => s.moduleCounts)
  const notifVisible = useNotificationStore(s => s.visible)
  const routeHint = to => moduleCounts[ROUTE_CATEGORY[to]] || 0
  const groupHint = group => (group.items || []).reduce((n, it) => n + routeHint(it.to), 0)
  const navigate  = useNavigate()
  const location  = useLocation()
  const userRole  = user?.role || 'viewer'

  // Filter groups + items by role
  const visibleGroups = NAV_GROUPS
    .map(g => ({ ...g, items: g.items.filter(n => !n.roles || n.roles.includes(userRole)) }))
    .filter(g => g.items.length > 0)

  // Which group is pinned open (clicked) — auto-tracks active route
  const activeRouteGroup = groupForPath(location.pathname, visibleGroups)
  const [pinnedGroup, setPinnedGroup] = useState(activeRouteGroup)
  const [hoverGroup,  setHoverGroup]  = useState(null)
  const [railOnly,    setRailOnly]    = useState(false) // full collapse to icon strip only
  const hoverTimer = useRef(null)

  // Sync pinned group when route changes
  useEffect(() => {
    if (activeRouteGroup) setPinnedGroup(activeRouteGroup)
  }, [activeRouteGroup])

  // Clicking a desktop (OS) notification → navigate to the linked record
  useEffect(() => {
    const onNav = (e) => { if (e.detail) navigate(e.detail) }
    window.addEventListener('notif:navigate', onNav)
    return () => window.removeEventListener('notif:navigate', onNav)
  }, [navigate])

  const displayedGroupId = hoverGroup ?? pinnedGroup
  const displayedGroup   = visibleGroups.find(g => g.id === displayedGroupId)

  const { data: syncStatus } = useQuery({
    queryKey: ['syncStatus'],
    queryFn: () => syncApi.status().then(r => r.data),
    refetchInterval: 60_000,
  })

  function handleRailEnter(groupId) {
    clearTimeout(hoverTimer.current)
    setHoverGroup(groupId)
  }

  function handleRailLeave() {
    hoverTimer.current = setTimeout(() => setHoverGroup(null), 120)
  }

  function handlePanelEnter() {
    clearTimeout(hoverTimer.current)
  }

  function handlePanelLeave() {
    hoverTimer.current = setTimeout(() => setHoverGroup(null), 120)
  }

  function handleGroupClick(groupId) {
    setPinnedGroup(prev => prev === groupId && !hoverGroup ? null : groupId)
  }

  return (
    <div className="flex min-h-screen bg-gray-50 font-cairo" dir="rtl">

      {/* ── Sidebar shell ─────────────────────────────────────────────────── */}
      <aside className="flex shrink-0 h-screen sticky top-0 z-40">

        {/* ── Icon rail (always visible) ──────────────────────────────────── */}
        <div className="flex flex-col w-[60px] bg-[#0f172a] border-l border-slate-800 h-full">

          {/* Logo mark */}
          <div className="flex items-center justify-center h-14 border-b border-slate-800 shrink-0">
            <div className="w-9 h-9 bg-white rounded-lg flex items-center justify-center shadow-sm">
              <BrandMark size={30} />
            </div>
          </div>

          {/* Group icons */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden py-2 flex flex-col items-center gap-0.5 scrollbar-hide">
            {visibleGroups.map(group => {
              const isActive = displayedGroupId === group.id
              const hasActiveRoute = activeRouteGroup === group.id
              return (
                <button
                  key={group.id}
                  onMouseEnter={() => handleRailEnter(group.id)}
                  onMouseLeave={handleRailLeave}
                  onClick={() => { handleGroupClick(group.id); if (railOnly) setRailOnly(false) }}
                  title={group.label}
                  className={`
                    relative w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-150
                    ${isActive
                      ? 'bg-brand-600 text-white shadow-lg shadow-brand-900/40'
                      : hasActiveRoute
                        ? 'bg-slate-700 text-brand-300'
                        : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
                    }
                  `}
                >
                  <GroupIcon id={group.id} />
                  {/* Active route dot */}
                  {hasActiveRoute && !isActive && (
                    <span className="absolute top-1.5 left-1.5 w-1.5 h-1.5 rounded-full bg-brand-400" />
                  )}
                  {/* Module notification hint (demand / followups) */}
                  {groupHint(group) > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
                      {groupHint(group) > 99 ? '99+' : groupHint(group)}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* Collapse toggle */}
          <div className="shrink-0 flex flex-col items-center gap-1 py-3 border-t border-slate-800">
            {/* Sync dot */}
            {syncStatus && (
              <div
                title={syncStatus.last_at ? `آخر مزامنة ${toLatinDigits(formatDistanceToNow(new Date(syncStatus.last_at), { locale: ar, addSuffix: true }))}` : 'لم تتم مزامنة بعد'}
                className={`w-2 h-2 rounded-full mb-1 ${
                  syncStatus.status === 'success'  ? 'bg-emerald-400' :
                  syncStatus.status === 'running'  ? 'bg-yellow-400 animate-pulse' : 'bg-red-400'
                }`}
              />
            )}
            {/* User avatar */}
            <div
              className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center cursor-default"
              title={`${user?.full_name || user?.username} — ${user?.branch_name || user?.role}`}
            >
              <span className="text-white text-xs font-bold">
                {(user?.full_name || user?.username || '?')[0]}
              </span>
            </div>
            {/* Logout */}
            <button
              onClick={() => { logout(); navigate('/login') }}
              title="تسجيل الخروج"
              className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 hover:text-red-400 hover:bg-slate-800 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>

        {/* ── Item panel (slides beside the rail) ─────────────────────────── */}
        <div
          onMouseEnter={handlePanelEnter}
          onMouseLeave={handlePanelLeave}
          className={`
            flex flex-col bg-[#1e293b] border-l border-slate-700 h-full
            transition-all duration-200 overflow-hidden
            ${(displayedGroup && !railOnly) ? 'w-[220px]' : 'w-0'}
          `}
        >
          {displayedGroup && (
            <>
              {/* Panel header */}
              <div className="flex items-center justify-between px-4 h-14 border-b border-slate-700 shrink-0">
                <span className="text-sm font-bold text-slate-100 tracking-wide">
                  {displayedGroup.label}
                </span>
                <button
                  onClick={() => setRailOnly(true)}
                  className="w-6 h-6 rounded flex items-center justify-center text-slate-500 hover:text-slate-200 hover:bg-slate-700 transition-colors"
                  title="إخفاء القائمة"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              </div>

              {/* Items */}
              <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
                {displayedGroup.items.map(item => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/procurement'}
                    onClick={() => setHoverGroup(null)}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors duration-100
                      ${isActive
                        ? 'bg-brand-600 text-white font-semibold shadow-sm'
                        : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                      }`
                    }
                  >
                    <span className="text-base w-5 text-center flex-shrink-0 leading-none">{item.icon}</span>
                    <span className="flex-1 leading-snug">{item.label}</span>
                    {routeHint(item.to) > 0 && (
                      <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center">
                        {routeHint(item.to) > 99 ? '99+' : routeHint(item.to)}
                      </span>
                    )}
                  </NavLink>
                ))}
              </nav>

              {/* Panel footer — user info */}
              <div className="shrink-0 px-4 py-3 border-t border-slate-700">
                <div className="text-xs font-semibold text-slate-300 truncate">
                  {user?.full_name || user?.username}
                </div>
                <div className="text-[10px] text-slate-500 truncate mt-0.5">
                  {user?.branch_name || user?.role}
                </div>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* ── Main content ──────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto flex flex-col min-w-0">

        {/* Top header bar */}
        <header className="shrink-0 bg-white border-b border-gray-200 px-6 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <span className="font-semibold text-gray-800">صيدليات الرزيقي</span>
            <span className="text-gray-300">·</span>
            <span>منصة العمليات</span>
          </div>

          <div className="flex items-center gap-3">
            <NotificationBell />
            {/* Quiet feeds beside the bell — hidden if the role can't see them */}
            {notifVisible.has('mentions')   && <ModuleNotificationBell category="mentions"   icon="💬" label="الإشارات (المنشن)" />}
            {notifVisible.has('reports')    && <ModuleNotificationBell category="reports"    icon="📊" label="التقارير الدورية" />}
            {notifVisible.has('monitoring') && <ModuleNotificationBell category="monitoring" icon="📡" label="المراقبة (SLA والمسار)" />}
            {notifVisible.has('settings')   && <ModuleNotificationBell category="settings"   icon="⚙️" label="النظام والإعدادات" />}
            <div className="w-px h-5 bg-gray-200" />
            <NavLink
              to="/security"
              title="أمان الحساب — المصادقة الثنائية"
              className="text-gray-400 hover:text-brand-600 transition-colors p-1 rounded-lg hover:bg-brand-50"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </NavLink>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-brand-600 flex items-center justify-center">
                <span className="text-white text-xs font-bold">
                  {(user?.full_name || user?.username || '?')[0]}
                </span>
              </div>
              <div className="text-sm leading-tight hidden sm:block">
                <div className="font-semibold text-gray-800">{user?.full_name || user?.username}</div>
                <div className="text-xs text-gray-400">{user?.branch_name || user?.role}</div>
              </div>
            </div>
            <button
              onClick={() => { logout(); navigate('/login') }}
              className="text-gray-400 hover:text-red-500 transition-colors p-1 rounded-lg hover:bg-red-50"
              title="تسجيل الخروج"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
