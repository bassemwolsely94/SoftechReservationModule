/**
 * shortcuts/commands.js — the central command registry.
 *
 * One source of truth for the Ctrl+K palette's navigation + action commands,
 * replacing scattered ad-hoc shortcuts. Each command:
 *   { id, title, title_en, icon, keywords[], section, run(ctx) }
 * ctx = { navigate, setMode, mode, logout }.
 *
 * `matchScore` powers ranking: exact title/keyword > startsWith > includes.
 */
import { normalizeSearch } from './normalize'

const nav = (id, path, title, title_en, icon, keywords = []) => ({
  id, title, title_en, icon, section: 'navigate',
  keywords: [title, title_en, ...keywords],
  run: ({ navigate }) => navigate(path),
})

export function buildCommands() {
  return [
    // ── Navigation ──
    nav('go-pos', '/pos', 'نقطة البيع (POS)', 'POS order', '🧾', ['بيع', 'كاشير', 'sell', 'cashier']),
    nav('go-reservations', '/reservations', 'الحجوزات', 'Reservations', '📌', ['حجز', 'reserve']),
    nav('go-demand', '/demand', 'الطلبات غير الملباة', 'Demand', '📥', ['نواقص', 'lost sales']),
    nav('go-transfers', '/transfers', 'التحويلات', 'Transfers', '🔁', ['نقل', 'transfer']),
    nav('go-customers', '/customers', 'العملاء', 'Customers', '👥', ['عميل', 'client']),
    nav('go-products', '/products', 'الأصناف', 'Products', '💊', ['صنف', 'دواء', 'item', 'drug']),
    nav('go-inventory', '/inventory', 'المخزون', 'Inventory', '📦', ['stock']),
    nav('go-stock-count', '/stock-count', 'الجرد', 'Stock count', '🔢', ['جرد', 'count']),
    nav('go-shortage', '/shortage', 'النواقص', 'Shortage', '📝', ['نقص']),
    nav('go-vouchers', '/vouchers', 'القسائم', 'Vouchers', '🎟️', ['قسيمة', 'coupon']),
    nav('go-incentives', '/incentives', 'الحوافز', 'Incentives', '🏆', ['حافز']),
    nav('go-procurement', '/procurement', 'المشتريات', 'Procurement', '🛒', ['شراء', 'purchase']),
    nav('go-analytics', '/analytics', 'التحليلات', 'Analytics', '📊', ['تقارير', 'reports']),
    nav('go-finance', '/finance', 'المالية', 'Finance', '💰', ['حسابات']),
    nav('go-insurance', '/insurance', 'التأمين', 'Insurance', '🩺', ['تأمين', 'motalba']),
    nav('go-loyalty', '/loyalty', 'الولاء والنقاط', 'Loyalty', '⭐', ['نقاط', 'points']),
    nav('go-forecasting', '/forecasting', 'التنبؤ', 'Forecasting', '🔮', ['توقع']),
    nav('go-batches', '/batches', 'التشغيلات والصلاحية', 'Batches / expiry', '📅', ['صلاحية', 'expiry']),
    nav('go-approvals', '/approvals', 'الموافقات', 'Approvals', '✅', ['موافقة', 'approve']),
    nav('go-sync', '/sync', 'المزامنة', 'Sync', '🔄', ['سوفتك', 'softech']),
    nav('go-users', '/users', 'المستخدمون', 'Users', '👤', ['صلاحيات', 'permissions']),
    nav('go-settings', '/settings', 'الإعدادات', 'Settings', '⚙️', ['اعدادات', 'config']),

    // ── Actions ──
    {
      id: 'toggle-theme', section: 'action', icon: '🌗',
      title: 'تبديل الوضع الفاتح/الداكن', title_en: 'Toggle light/dark',
      keywords: ['ثيم', 'داكن', 'فاتح', 'theme', 'dark', 'light'],
      run: ({ cycleMode }) => cycleMode && cycleMode(),
    },
    {
      id: 'logout', section: 'action', icon: '🚪',
      title: 'تسجيل الخروج', title_en: 'Log out',
      keywords: ['خروج', 'signout', 'logout'],
      run: ({ logout, navigate }) => { logout && logout(); navigate('/login') },
    },
  ]
}

/** Rank a command against a normalized query. Returns -1 for no match. */
export function matchScore(cmd, nq) {
  if (!nq) return 0
  const hay = cmd.keywords.map(normalizeSearch)
  let best = -1
  for (const h of hay) {
    if (!h) continue
    if (h === nq) return 100
    if (h.startsWith(nq)) best = Math.max(best, 70)
    else if (h.includes(nq)) best = Math.max(best, 40)
  }
  return best
}
