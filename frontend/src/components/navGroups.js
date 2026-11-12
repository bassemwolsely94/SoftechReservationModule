/**
 * The side menu: groups and items, with who sees each item. Pure data, so the browser tests
 * (frontend/e2e) and the unit tests read the same list Layout renders.
 *
 *   roles   null = everyone; a list = only these roles (an empty list = nobody by role)
 *   cap     a server-computed per-user capability that also shows the item (user[cap] truthy)
 *   module  hides the item once the role matrix takes that module's view away
 *
 * The menu only hides; the server is the real guard (every API checks the role itself).
 */
export const NAV_GROUPS = [
  {
    id: 'home', label: 'الرئيسية', section: null,
    items: [
      { to: '/dashboard', icon: '◈', label: 'الرئيسية', roles: null },
      { to: '/me',        icon: '🙋', label: 'لوحتي الشخصية', roles: null },
      { to: '/gamification', icon: '🏆', label: 'التحفيز والمستويات', roles: null },
      { to: '/help',      icon: '📖', label: 'دليل الاستخدام', roles: null },
    ],
  },
  {
    id: 'operations', label: 'العمليات', section: 'العمليات',
    items: [
      { to: '/pos',           icon: '🧾', label: 'نقطة البيع',        roles: ['admin','call_center','pharmacist','salesperson','supervisor'] },
      { to: '/pos/exceptions', icon: '🛠️', label: 'مركز الاستثناءات', roles: ['admin','supervisor','pharmacist'] },
      { to: '/usage-print',   icon: '🏷️', label: 'طريقة الاستخدام',   roles: [], cap: 'can_usage_print' },
      { to: '/reservations',  icon: '📋', label: 'الحجوزات',         roles: ['admin','call_center','pharmacist','salesperson','supervisor','viewer','quality_manager'] },
      { to: '/missed-sales',  icon: '🛒', label: 'مبيعات فائتة',     roles: ['admin','call_center','pharmacist','salesperson','supervisor','quality_manager'] },
      { to: '/transfers',     icon: '🔀', label: 'طلبات التحويل',    roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/transits',      icon: '🚛', label: 'التحويلات قيد النقل', roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/demand',        icon: '🔍', label: 'الطلب الضائع',     roles: ['admin','call_center','pharmacist','salesperson','supervisor','viewer','quality_manager'] },
      { to: '/followups',     icon: '💊', label: 'متابعة المزمن',    roles: ['admin','call_center','pharmacist','salesperson','supervisor','quality_manager'] },
      { to: '/followups/reminders', icon: '💬', label: 'تذكيرات الصرف واتساب', roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/delivery',      icon: '🚚', label: 'توصيل الطلبات',    roles: ['admin','pharmacist','delivery','call_center','supervisor','quality_manager'] },
      { to: '/delivery/dispatch', icon: '🧭', label: 'لوحة التوزيع',  roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/rider',         icon: '🛵', label: 'مهام السائق',       roles: ['admin','delivery','supervisor'] },
      { to: '/stock-count',   icon: '📦', label: 'الجرد الفعلي',     roles: ['admin','pharmacist','supervisor','quality_manager'] },
      { to: '/tasks',         icon: '✅', label: 'المهام التشغيلية', roles: null, module: 'tasks' },
      { to: '/announcements', icon: '📢', label: 'الإعلانات',        roles: null },
    ],
  },
  {
    id: 'callcenter', label: 'مركز الاتصال', section: 'مركز الاتصال',
    items: [
      { to: '/omni/inbox',            icon: '📥', label: 'الصندوق الموحد',  roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/omni/accounts',         icon: '📡', label: 'حسابات القنوات',  roles: ['admin','supervisor','quality_manager'] },
      { to: '/omni/wallboard',        icon: '📊', label: 'لوحة المشرف',     roles: ['admin','supervisor','quality_manager','call_center'] },
      { to: '/omni/automations',      icon: '⚙️', label: 'الأتمتة',         roles: ['admin','supervisor'] },
      { to: '/omni/analytics',        icon: '📈', label: 'تحليلات التواصل', roles: ['admin','supervisor','quality_manager'] },
      { to: '/callcenter',            icon: '📞', label: 'الحالات',         roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/callcenter/analytics',  icon: '📊', label: 'جودة الاتصال',    roles: ['admin','supervisor','quality_manager'] },
      { to: '/campaigns',             icon: '📱', label: 'حملات واتساب',    roles: ['admin','call_center','supervisor','purchasing'] },
      { to: '/whatsapp/inbox',        icon: '💬', label: 'صندوق واتساب',    roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/pbx/live',              icon: '☎️', label: 'المكالمات الحية', roles: ['admin','call_center','supervisor','quality_manager'] },
    ],
  },
  {
    id: 'customers', label: 'العملاء', section: 'العملاء',
    items: [
      { to: '/customers',          icon: '👥', label: 'العملاء',             roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager','delivery'] },
      { to: '/customers/merge',    icon: '🔀', label: 'دمج الأكواد المكررة', roles: ['admin','supervisor','call_center'] },
      { to: '/customers/pic-analytics', icon: '📊', label: 'تحليلات العملاء', roles: ['admin','supervisor'], cap: 'can_pic_analytics' },
      { to: '/vouchers',           icon: '🎫', label: 'القسائم',             roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','quality_manager'] },
      { to: '/vouchers?tab=coupons', icon: '🎟️', label: 'كوبونات الهدايا',   roles: ['admin','supervisor','purchasing','quality_manager'] },
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
      { to: '/stock-audit',          icon: '🔎', label: 'تدقيق حركات المخزون', roles: ['admin','supervisor','quality_manager'], cap: 'can_stock_audit' },
      { to: '/shortage',             icon: '🚨', label: 'النواقص',         roles: ['admin','pharmacist','call_center','salesperson','purchasing','supervisor','quality_manager'] },
      { to: '/market-shortage',      icon: '📉', label: 'نواقص السوق',     roles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/phantom-sales',        icon: '🩹', label: 'مبيعات وهمية',    roles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/cash-optimization',    icon: '💰', label: 'تحسين الكاش',     roles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/catalog-intelligence', icon: '🧠', label: 'ذكاء الكتالوج',   roles: ['admin','pharmacist','purchasing'] },
      { to: '/chronic-classifier',   icon: '🧬', label: 'الأدوية المزمنة',  roles: ['admin','pharmacist','call_center','supervisor'] },
      { to: '/composition',          icon: '⚗️', label: 'تنقية المواد الفعّالة', roles: ['admin','pharmacist','purchasing','supervisor'] },
      { to: '/counselling',          icon: '📘', label: 'إرشادات الاستخدام', roles: ['admin','pharmacist','quality_manager'], module: 'counselling' },
      { to: '/ingredient-search',    icon: '🔬', label: 'بحث المواد الفعّالة', roles: ['admin','pharmacist','purchasing','supervisor','call_center','quality_manager'] },
      { to: '/image-enrichment',     icon: '🖼️', label: 'صور المنتجات',   roles: ['admin','pharmacist','purchasing'] },
      { to: '/recommendations',      icon: '🔗', label: 'التوصيات الذكية', roles: ['admin','pharmacist','call_center','purchasing'] },
      { to: '/offers',               icon: '🎁', label: 'العروض والتخفيضات', roles: ['admin','supervisor','purchasing'] },
    ],
  },
  {
    id: 'purchasing', label: 'المشتريات', section: 'المشتريات',
    items: [
      { to: '/purchasing',        icon: '📊', label: 'توصيات الشراء',    roles: ['admin','purchasing','viewer'], cap: 'can_run_engine' },
      { to: '/procurement',       icon: '🛒', label: 'ذكاء المشتريات',   roles: ['admin','purchasing'] },
      { to: '/supply',            icon: '🔄', label: 'التوريد والمعدلات', roles: ['admin','purchasing','supervisor'], cap: 'can_supply_write' },
      { to: '/invoices',          icon: '🧾', label: 'فواتير الموردين',   roles: ['admin','purchasing'] },
      { to: '/pricing-approvals', icon: '🏷️', label: 'موافقات الأسعار', roles: ['admin','purchasing','pharmacist','supervisor','quality_manager'] },
      { to: '/discount-alignment', icon: '🎯', label: 'مطابقة الخصومات', roles: ['admin','purchasing','pharmacist','supervisor','quality_manager'] },
    ],
  },
  {
    id: 'analytics', label: 'التحليلات', section: 'التحليلات',
    items: [
      { to: '/analytics',   icon: '📈', label: 'المبيعات والأداء', roles: ['admin','purchasing','pharmacist','supervisor','quality_manager','viewer'] },
      { to: '/forecasting', icon: '🔮', label: 'التنبؤ بالطلب',   roles: ['admin','purchasing','pharmacist','quality_manager'] },
      { to: '/incentives',  icon: '💰', label: 'الحوافز',          roles: ['admin','quality_manager','purchasing'] },
      { to: '/my-incentives', icon: '🏅', label: 'حوافزي',         roles: null },
      { to: '/targets',     icon: '🎯', label: 'الأهداف البيعية',  roles: ['admin','supervisor','purchasing','pharmacist','quality_manager','viewer'] },
      { to: '/kpi-board',   icon: '📊', label: 'لوحة مؤشرات الفروع', roles: ['admin','supervisor','purchasing','pharmacist','quality_manager','viewer'] },
      { to: '/salesperson-board', icon: '🧑‍💼', label: 'متابعة المندوبين', roles: ['admin','supervisor','purchasing'] },
      { to: '/forecast-scenarios', icon: '🔮', label: 'سيناريوهات التنبؤ', roles: ['admin','supervisor','purchasing'] },
      { to: '/insights',    icon: '📋', label: 'التقارير السردية', roles: ['admin','supervisor','purchasing','quality_manager','viewer'] },
      { to: '/referral-stats', icon: '🩺', label: 'إحالات الأطباء', roles: ['admin','supervisor','pharmacist','quality_manager','viewer'] },
      { to: '/vision-corpus', icon: '👁️', label: 'المحرك البصري', roles: ['admin','supervisor','purchasing','pharmacist'] },
    ],
  },
  {
    id: 'finance', label: 'المالية', section: 'المالية',
    items: [
      { to: '/finance/journal', icon: '📒', label: 'الحسابات العامة', roles: ['admin','accountant'] },
      { to: '/finance',        icon: '💹', label: 'الذكاء المالي',   roles: ['admin','purchasing','pharmacist','quality_manager','accountant'] },
      { to: '/cheques',        icon: '📝', label: 'تخطيط الشيكات',  roles: ['admin','purchasing','pharmacist','accountant'] },
      // P-43: /payments (external payments, no data yet) hidden from the menu — the
      // route and code stay; re-add this line if finance asks for it.
      { to: '/payment-audit',  icon: '🏦', label: 'مراجعة الكشوف',  roles: ['admin','purchasing','pharmacist','quality_manager','accountant'] },
      { to: '/reconciliation', icon: '🔗', label: 'سداد الموردين',  roles: ['admin','purchasing','quality_manager','accountant'] },
      { to: '/insurance',      icon: '🏥', label: 'مطالبات التأمين', roles: ['admin','purchasing'] },
      { to: '/replacement',    icon: '🔁', label: 'بدل الروشتة',     roles: ['admin','supervisor','purchasing','quality_manager','pharmacist'] },
      { to: '/commerce',       icon: '🧩', label: 'المستندات التجارية', roles: ['admin','purchasing'] },
    ],
  },
  {
    id: 'hr', label: 'الموارد البشرية', section: 'الموارد البشرية',
    items: [
      { to: '/hr',        icon: '👨‍💼', label: 'الإجازات والطلبات', roles: null },
      { to: '/hr/attendance', icon: '🖐️', label: 'الحضور والبصمة', roles: [], cap: 'can_hr_attendance' },
      { to: '/approvals', icon: '✔️', label: 'صندوق الموافقات',    roles: ['admin','supervisor','pharmacist','quality_manager','purchasing'] },
    ],
  },
  {
    id: 'admin', label: 'الإدارة', section: 'الإدارة',
    items: [
      { to: '/audit',            icon: '🛡️', label: 'المراجعة والأمان', roles: ['admin','supervisor','quality_manager'] },
      { to: '/users',            icon: '👤', label: 'المستخدمون',        roles: ['admin','supervisor'] },
      { to: '/phone-alerts',     icon: '📲', label: 'تنبيهات الموبايل',   roles: ['admin','supervisor'] },
      { to: '/permissions',      icon: '🔐', label: 'الصلاحيات',         roles: ['admin'] },
      { to: '/erp-permissions',  icon: '🧩', label: 'صلاحيات Softech',   roles: ['admin'] },
      { to: '/settings',         icon: '⚙️', label: 'الإعدادات',         roles: ['admin','pharmacist'] },
      { to: '/sync',             icon: '⟳', label: 'المزامنة',            roles: ['admin'] },
      { to: '/data-health',      icon: '🩺', label: 'صحة البيانات',       roles: ['admin','supervisor','quality_manager'], module: 'data_health' },
      { to: '/access/networks',  icon: '🌐', label: 'الشبكات الموثوقة',   roles: ['admin'] },
      { to: '/access/devices',   icon: '💻', label: 'الأجهزة',            roles: ['admin'] },
      { to: '/access/zone-policy', icon: '🛰️', label: 'سياسة الشبكات',      roles: ['admin'] },
    ],
  },
]

/** The rule Layout applies: is this menu item shown to this user? */
export function navItemVisible(item, { role, user, perms } = {}) {
  const userRole = role || user?.role || 'viewer'
  return (!item.roles || item.roles.includes(userRole) || (!!item.cap && !!user?.[item.cap]))
    && (!item.module || !perms || userRole === 'admin' || !!perms[item.module]?.view)
}
