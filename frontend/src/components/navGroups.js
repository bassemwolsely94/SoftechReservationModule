/**
 * The side menu: groups and items, with who sees each item. Pure data, so the browser tests
 * (frontend/e2e) and the unit tests read the same list Layout renders.
 *
 *   roles   null = everyone; a list = only these roles (an empty list = nobody by role)
 *   cap     a server-computed per-user capability that also shows the item (user[cap] truthy)
 *   module  the role matrix decides (`roles: null` + module = whoever holds that module's view; role review 2026-11-20);
 *           optional `action` (default view) and `anyOf` (extra actions, any one) mirror the screen's server rule
 *   legacyRoles / legacyCap  the item's role list (and capability) from before the role review: used
 *           only while its `module` has no matrix rows at all (my-permissions `seeded`), where the server
 *           fails open for the legacy roles — so a database never seeded keeps today's menu (C1)
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
      { to: '/pos/exceptions', icon: '🛠️', label: 'مركز الاستثناءات', roles: ['admin','supervisor','pharmacist'], module: 'pos' },
      // /usage-print and /hr/attendance: per-user capability switches (cap), not role checks — kept as-is
      { to: '/usage-print',   icon: '🏷️', label: 'طريقة الاستخدام',   roles: [], cap: 'can_usage_print' },
      { to: '/reservations',  icon: '📋', label: 'الحجوزات',         roles: ['admin','call_center','pharmacist','salesperson','supervisor','viewer','quality_manager'] },
      { to: '/missed-sales',  icon: '🛒', label: 'مبيعات فائتة',     roles: ['admin','call_center','pharmacist','salesperson','supervisor','quality_manager'], module: 'reservations' },
      { to: '/transfers',     icon: '🔀', label: 'طلبات التحويل',    roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/transits',      icon: '🚛', label: 'التحويلات قيد النقل', roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/demand',        icon: '🔍', label: 'الطلب الضائع',     roles: ['admin','call_center','pharmacist','salesperson','supervisor','viewer','quality_manager'] },
      { to: '/followups',     icon: '💊', label: 'متابعة المزمن',    roles: null, module: 'followups', legacyRoles: ['admin','call_center','pharmacist','salesperson','supervisor','quality_manager'] },
      { to: '/followups/reminders', icon: '💬', label: 'تذكيرات الصرف واتساب', roles: null, module: 'followups', legacyRoles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/delivery',      icon: '🚚', label: 'توصيل الطلبات',    roles: null, module: 'delivery', legacyRoles: ['admin','pharmacist','delivery','call_center','supervisor','quality_manager'] },
      { to: '/delivery/dispatch', icon: '🧭', label: 'لوحة التوزيع',  roles: null, module: 'dispatch', legacyRoles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/marketplace',   icon: '🛍️', label: 'المنصات والتطبيقات', roles: [], cap: 'can_marketplace' },
      { to: '/rider',         icon: '🛵', label: 'مهام السائق',       roles: null, module: 'rider', legacyRoles: ['admin','delivery','supervisor'] },
      { to: '/stock-count',   icon: '📦', label: 'الجرد الفعلي',     roles: null, module: 'stockcount', legacyRoles: ['admin','pharmacist','supervisor','quality_manager'] },
      { to: '/tasks',         icon: '✅', label: 'المهام التشغيلية', roles: null, module: 'tasks' },
      { to: '/announcements', icon: '📢', label: 'الإعلانات',        roles: null },
    ],
  },
  {
    id: 'callcenter', label: 'مركز الاتصال', section: 'مركز الاتصال',
    items: [
      { to: '/omni/inbox',            icon: '📥', label: 'الصندوق الموحد',  roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/omni/accounts',         icon: '📡', label: 'حسابات القنوات',  roles: null, module: 'callcenter', legacyRoles: ['admin','supervisor','quality_manager'] },
      { to: '/omni/wallboard',        icon: '📊', label: 'لوحة المشرف',     roles: ['admin','supervisor','quality_manager','call_center'] },
      { to: '/omni/automations',      icon: '⚙️', label: 'الأتمتة',         roles: null, module: 'callcenter', legacyRoles: ['admin','supervisor'] },
      { to: '/omni/analytics',        icon: '📈', label: 'تحليلات التواصل', roles: null, module: 'callcenter', legacyRoles: ['admin','supervisor','quality_manager'] },
      { to: '/callcenter',            icon: '📞', label: 'الحالات',         roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/callcenter/analytics',  icon: '📊', label: 'جودة الاتصال',    roles: null, module: 'callcenter', legacyRoles: ['admin','supervisor','quality_manager'] },
      { to: '/campaigns',             icon: '📱', label: 'حملات واتساب',    roles: null, module: 'campaigns', legacyRoles: ['admin','call_center','supervisor','purchasing'] },
      { to: '/whatsapp/inbox',        icon: '💬', label: 'صندوق واتساب',    roles: ['admin','call_center','supervisor','quality_manager'] },
      { to: '/pbx/live',              icon: '☎️', label: 'المكالمات الحية', roles: ['admin','call_center','supervisor','quality_manager'] },
    ],
  },
  {
    id: 'customers', label: 'العملاء', section: 'العملاء',
    items: [
      { to: '/customers',          icon: '👥', label: 'العملاء',             roles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager','delivery'] },
      { to: '/customers/merge',    icon: '🔀', label: 'دمج الأكواد المكررة', roles: null, module: 'customers', action: 'edit', legacyRoles: ['admin','supervisor','call_center'] },
      { to: '/customers/pic-analytics', icon: '📊', label: 'تحليلات العملاء', roles: ['admin','supervisor'], cap: 'can_pic_analytics' },
      { to: '/vouchers',           icon: '🎫', label: 'القسائم',             roles: null, module: 'vouchers', legacyRoles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','quality_manager'] },
      { to: '/vouchers?tab=coupons', icon: '🎟️', label: 'كوبونات الهدايا',   roles: null, module: 'vouchers', anyOf: ['export', 'edit'], legacyRoles: ['admin','supervisor','purchasing','quality_manager'] },
      { to: '/loyalty',            icon: '🏆', label: 'النقاط والولاء',      roles: null, module: 'loyalty', legacyRoles: ['admin','call_center','pharmacist','salesperson','supervisor'] },
      { to: '/loyalty/branch',     icon: '🔍', label: 'استعلام نقاط الفرع', roles: null, module: 'loyalty', legacyRoles: ['admin','branch','pharmacist','supervisor'] },
      { to: '/referral',           icon: '🔗', label: 'الإحالات',            roles: null, module: 'loyalty', legacyRoles: ['admin','call_center','supervisor'] },
    ],
  },
  {
    id: 'inventory', label: 'المخزون', section: 'المخزون',
    items: [
      { to: '/products',             icon: '💊', label: 'المنتجات',        roles: null, module: 'catalog', legacyRoles: ['admin','call_center','pharmacist','salesperson','purchasing','supervisor','viewer','quality_manager'] },
      { to: '/inventory',            icon: '🗃️', label: 'لوحة المخزون',   roles: null, module: 'stock', legacyRoles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/batches',              icon: '🧪', label: 'الدفعات والانتهاء', roles: null, module: 'stock', legacyRoles: ['admin','pharmacist','purchasing','quality_manager','supervisor'] },
      { to: '/stock-audit',          icon: '🔎', label: 'تدقيق حركات المخزون', roles: ['admin','supervisor','quality_manager'], cap: 'can_stock_audit' },
      { to: '/shortage',             icon: '🚨', label: 'النواقص',         roles: null, module: 'shortage', legacyRoles: ['admin','pharmacist','call_center','salesperson','purchasing','supervisor','quality_manager'] },
      { to: '/market-shortage',      icon: '📉', label: 'نواقص السوق',     roles: null, module: 'shortage', legacyRoles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/phantom-sales',        icon: '🩹', label: 'مبيعات وهمية',    roles: null, module: 'analytics', legacyRoles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/cash-optimization',    icon: '💰', label: 'تحسين الكاش',     roles: null, module: 'analytics', legacyRoles: ['admin','pharmacist','purchasing','supervisor','quality_manager'] },
      { to: '/catalog-intelligence', icon: '🧠', label: 'ذكاء الكتالوج',   roles: null, module: 'catalog_tools', legacyRoles: ['admin','pharmacist','purchasing'] },
      { to: '/chronic-classifier',   icon: '🧬', label: 'الأدوية المزمنة',  roles: null, module: 'chronic', legacyRoles: ['admin','pharmacist','call_center','supervisor'] },
      { to: '/composition',          icon: '⚗️', label: 'تنقية المواد الفعّالة', roles: null, module: 'chronic', legacyRoles: ['admin','pharmacist','purchasing','supervisor'] },
      { to: '/counselling',          icon: '📘', label: 'إرشادات الاستخدام', roles: null, module: 'counselling', legacyRoles: ['admin','pharmacist','quality_manager'] },
      { to: '/ingredient-search',    icon: '🔬', label: 'بحث المواد الفعّالة', roles: null, module: 'catalog', legacyRoles: ['admin','pharmacist','purchasing','supervisor','call_center','quality_manager'] },
      { to: '/image-enrichment',     icon: '🖼️', label: 'صور المنتجات',   roles: null, module: 'catalog_tools', legacyRoles: ['admin','pharmacist','purchasing'] },
      { to: '/recommendations',      icon: '🔗', label: 'التوصيات الذكية', roles: null, module: 'recommendations', legacyRoles: ['admin','pharmacist','call_center','purchasing'] },
      { to: '/offers',               icon: '🎁', label: 'العروض والتخفيضات', roles: ['admin','supervisor','purchasing'] },
    ],
  },
  {
    id: 'purchasing', label: 'المشتريات', section: 'المشتريات',
    items: [
      { to: '/purchasing',        icon: '📊', label: 'توصيات الشراء',    roles: null, module: 'purchasing', legacyRoles: ['admin','purchasing','viewer'], legacyCap: 'can_run_engine' },
      { to: '/procurement',       icon: '🛒', label: 'ذكاء المشتريات',   roles: null, module: 'purchasing', legacyRoles: ['admin','purchasing'] },
      { to: '/supply',            icon: '🔄', label: 'التوريد والمعدلات', roles: null, module: 'purchasing', legacyRoles: ['admin','purchasing','supervisor'], legacyCap: 'can_supply_write' },
      { to: '/invoices',          icon: '🧾', label: 'فواتير الموردين',   roles: ['admin','purchasing'] },
      { to: '/pricing-approvals', icon: '🏷️', label: 'موافقات الأسعار', roles: ['admin','purchasing','pharmacist','supervisor','quality_manager'] },
      { to: '/discount-alignment', icon: '🎯', label: 'مطابقة الخصومات', roles: ['admin','purchasing','pharmacist','supervisor','quality_manager'] },
      // supplier-portal robot: shown by the matrix grant rpa.view (the server checks every action)
      { to: '/rpa/portals',      icon: '🛒', label: 'مواقع الموردين',   roles: null, module: 'rpa' },
    ],
  },
  {
    id: 'analytics', label: 'التحليلات', section: 'التحليلات',
    items: [
      { to: '/analytics',   icon: '📈', label: 'المبيعات والأداء', roles: null, module: 'analytics', legacyRoles: ['admin','purchasing','pharmacist','supervisor','quality_manager','viewer'] },
      { to: '/forecasting', icon: '🔮', label: 'التنبؤ بالطلب',   roles: null, module: 'forecast', legacyRoles: ['admin','purchasing','pharmacist','quality_manager'] },
      { to: '/incentives',  icon: '💰', label: 'الحوافز',          roles: ['admin','quality_manager','purchasing'] },
      { to: '/my-incentives', icon: '🏅', label: 'حوافزي',         roles: null },
      { to: '/targets',     icon: '🎯', label: 'الأهداف البيعية',  roles: null, module: 'analytics', legacyRoles: ['admin','supervisor','purchasing','pharmacist','quality_manager','viewer'] },
      { to: '/kpi-board',   icon: '📊', label: 'لوحة مؤشرات الفروع', roles: null, module: 'analytics', legacyRoles: ['admin','supervisor','purchasing','pharmacist','quality_manager','viewer'] },
      { to: '/salesperson-board', icon: '🧑‍💼', label: 'متابعة المندوبين', roles: null, module: 'forecast', legacyRoles: ['admin','supervisor','purchasing'] },
      // The lost-demand dashboard is an analytics page (the server checks analytics view): purchasing
      // holds analytics but not demand, so it had no menu way in (UAT W2, owner 2026-11-19). The
      // recovery list stays under «الطلب الضائع»: its follow-up actions are demand work.
      { to: '/demand/dashboard', icon: '🔍', label: 'تحليلات الطلب الضائع', roles: null, module: 'analytics' },
      { to: '/forecast-scenarios', icon: '🔮', label: 'سيناريوهات التنبؤ', roles: null, module: 'forecast', legacyRoles: ['admin','supervisor','purchasing'] },
      { to: '/insights',    icon: '📋', label: 'التقارير السردية', roles: null, module: 'analytics', legacyRoles: ['admin','supervisor','purchasing','quality_manager','viewer'] },
      { to: '/referral-stats', icon: '🩺', label: 'إحالات الأطباء', roles: null, module: 'analytics', legacyRoles: ['admin','supervisor','pharmacist','quality_manager','viewer'] },
      { to: '/vision-corpus', icon: '👁️', label: 'المحرك البصري', roles: null, module: 'catalog_tools', legacyRoles: ['admin','supervisor','purchasing','pharmacist'] },
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
      { to: '/reconciliation', icon: '🔗', label: 'سداد الموردين',  roles: null, module: 'reconciliation', legacyRoles: ['admin','purchasing','quality_manager','accountant'] },
      { to: '/insurance',      icon: '🏥', label: 'مطالبات التأمين', roles: ['admin','purchasing'] },
      // Whoever holds module tax_invoicing (seed: admin, accountant); the server checks each action.
      { to: '/tax-invoicing',  icon: '🧾', label: 'الفواتير الضريبية', roles: null, module: 'tax_invoicing' },
      { to: '/replacement',    icon: '🔁', label: 'بدل الروشتة',     roles: ['admin','supervisor','purchasing','quality_manager','pharmacist'] },
      { to: '/commerce',       icon: '🧩', label: 'المستندات التجارية', roles: ['admin','purchasing'] },
    ],
  },
  {
    id: 'hr', label: 'الموارد البشرية', section: 'الموارد البشرية',
    items: [
      { to: '/hr',        icon: '👨‍💼', label: 'الإجازات والطلبات', roles: null },
      // per-user capability switch (can_hr_attendance), not a role check — kept as-is
      { to: '/hr/attendance', icon: '🖐️', label: 'الحضور والبصمة', roles: [], cap: 'can_hr_attendance' },
      // roles null + module: shown by the matrix grant of `crews` (admin by default), like /tax-invoicing
      { to: '/crews',     icon: '👥', label: 'الأطقم',             roles: null, module: 'crews' },
      { to: '/approvals', icon: '✔️', label: 'صندوق الموافقات',   roles: ['admin','supervisor','pharmacist','quality_manager','purchasing'] },
    ],
  },
  {
    id: 'admin', label: 'الإدارة', section: 'الإدارة',
    items: [
      { to: '/audit',            icon: '🛡️', label: 'المراجعة والأمان', roles: ['admin','supervisor','quality_manager'] },
      { to: '/users',            icon: '👤', label: 'المستخدمون',        roles: ['admin','supervisor'] },
      { to: '/phone-alerts',     icon: '📲', label: 'تنبيهات الموبايل',   roles: null, module: 'alerts' },
      { to: '/permissions',      icon: '🔐', label: 'الصلاحيات',         roles: ['admin'] },
      { to: '/erp-permissions',  icon: '🧩', label: 'صلاحيات Softech',   roles: ['admin'] },
      { to: '/settings',         icon: '⚙️', label: 'الإعدادات',         roles: null, module: 'settings', legacyRoles: ['admin','pharmacist'] },
      { to: '/code-maps',        icon: '🏷️', label: 'ترميزات SOFTECH',   roles: null, module: 'code_maps', legacyRoles: ['admin'] },
      { to: '/rpa',              icon: '🤖', label: 'روبوت الإدخال',      roles: null, module: 'rpa' },
      { to: '/sync',             icon: '⟳', label: 'المزامنة',            roles: ['admin'] },
      { to: '/data-health',      icon: '🩺', label: 'صحة البيانات',       roles: ['admin','supervisor','quality_manager'], module: 'data_health' },
      { to: '/access/networks',  icon: '🌐', label: 'الشبكات الموثوقة',   roles: null, module: 'access_control', legacyRoles: ['admin'] },
      { to: '/access/devices',   icon: '💻', label: 'الأجهزة',            roles: null, module: 'access_control', legacyRoles: ['admin'] },
      { to: '/access/zone-policy', icon: '🛰️', label: 'سياسة الشبكات',      roles: null, module: 'access_control', legacyRoles: ['admin'] },
    ],
  },
]

/** The rule Layout (and MobileLayout's tabs) apply: is this menu item shown to this user?
 *  `module` asks the role matrix (view, or `action`; `anyOf` = any one of these actions on top of view).
 *  `seeded` = modules the matrix has rows for; a module outside it is decided by `legacyRoles`. */
export function navItemVisible(item, { role, user, perms, seeded } = {}) {
  const userRole = role || user?.role || 'viewer'
  if (moduleUnseeded(item.module, item.legacyRoles, perms, seeded) && userRole !== 'admin') {
    return item.legacyRoles.includes(userRole) || (!!item.legacyCap && !!user?.[item.legacyCap])
      || (!!item.cap && !!user?.[item.cap])
  }
  const roleOk = !item.roles || item.roles.includes(userRole) || (!!item.cap && !!user?.[item.cap])
  if (!roleOk) return false
  if (!item.module || !perms || userRole === 'admin') return true
  const grant = perms[item.module]
  if (!grant?.[item.action || 'view']) return false
  return !item.anyOf || item.anyOf.some(a => !!grant[a])
}

/** True when `module` has no matrix rows (the server fails open for legacy roles) and the caller
 *  carries an old role list to fall back on. Unknown list (not loaded / old server) = false. */
export function moduleUnseeded(module, legacyRoles, perms, seeded) {
  return !!module && Array.isArray(legacyRoles) && !!perms && Array.isArray(seeded) && !seeded.includes(module)
}

/** May this user run a write `actions` (any one) on `module`? The predicate behind useModuleAction:
 *  admin yes; permissions not loaded no; a module with no matrix rows (server fails open for the
 *  legacy roles) by `legacyRoles` when given; otherwise the matrix. Screens use it to hide or
 *  disable write controls from view-only roles (final review I4). */
export function moduleActionAllowed({ role, perms, seeded } = {}, module, actions, legacyRoles) {
  if (role === 'admin') return true
  if (!perms) return false
  if (moduleUnseeded(module, legacyRoles, perms, seeded)) return legacyRoles.includes(role || 'viewer')
  const grant = perms[module] || {}
  return [].concat(actions).some(a => !!grant[a])
}

/** The pre-review role list of the menu item for `path` (its `legacyRoles`), so route guards and
 *  in-page write gates reuse the one list instead of repeating role literals. */
export function legacyRolesFor(path) {
  for (const g of NAV_GROUPS) {
    const it = g.items.find(i => i.to === path)
    if (it) return it.legacyRoles
  }
  return undefined
}
