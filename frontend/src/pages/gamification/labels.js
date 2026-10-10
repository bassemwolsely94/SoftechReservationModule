// Shared labels for the gamification screens (Arabic / English pairs).
export const ROLES = [
  ['', 'كل الأدوار', 'All roles'], ['salesperson', 'مندوب بيع', 'Salesperson'],
  ['pharmacist', 'صيدلي', 'Pharmacist'], ['call_center', 'كول سنتر', 'Call center'],
  ['delivery', 'توصيل', 'Delivery'], ['purchasing', 'مشتريات', 'Purchasing'],
  ['supervisor', 'مشرف', 'Supervisor'], ['quality_manager', 'جودة', 'Quality'],
]
const ROLE_NAMES = Object.fromEntries([...ROLES.slice(1), ['admin', 'مدير النظام', 'Admin'],
  ['viewer', 'مشاهد', 'Viewer']].map(([k, ar, en]) => [k, [ar, en]]))
export const roleLabel = (role, t) => (ROLE_NAMES[role] ? t(...ROLE_NAMES[role]) : role)
