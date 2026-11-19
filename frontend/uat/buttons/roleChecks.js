// W3 catalogue: every hard-coded role check in frontend/src (a literal role compared with the
// signed-in user's role, a `roles: [...]` menu/tab list, a <RequireRole roles={[...]}> guard, or a
// role-literal list used with `.includes(user?.role)`), scanned from the code, never hand-kept.
//
// Each check gets an INFERRED module:action — what the role matrix would say for the same thing.
// Every inference is a guess ("inferred — needs confirmation"); the verdict compares the roles the
// code lets through with the roles the live matrix (.uat-expected.json) lets through:
//   looser  = code lets a role through that the matrix denies   → P1
//   stricter = the matrix allows a role the code keeps out       → P3
import fs from 'node:fs'
import path from 'node:path'

export const SRC = path.resolve(__dirname, '..', '..', 'src')
export const ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery',
  'viewer', 'supervisor', 'quality_manager', 'accountant']            // apps/users/roles.py
// Names that look like roles in the code but are not in apps/users/roles.py.
const UNKNOWN_ROLE_WORDS = ['manager', 'branch']
const ROLE_WORDS = [...ROLES, ...UNKNOWN_ROLE_WORDS]
const literalRoles = s => [...s.matchAll(/'([a-z_]+)'/g)].map(m => m[1]).filter(r => ROLE_WORDS.includes(r))

// Screen path → module (inferred from core/middleware/module_access.py MODULE_BY_PREFIX, which maps
// the API prefixes; a screen is matched by its own path). Longest prefix wins.
const ROUTE_MODULE = [
  ['/m/pos', 'pos'], ['/m/demand', 'demand'], ['/m/shortage', 'shortage'], ['/m/delivery', 'delivery'],
  ['/m/approvals', 'approvals'], ['/m/customers', 'customers'], ['/m/vouchers', 'vouchers'],
  ['/m/stock-count', 'stockcount'], ['/m/qa', 'hr'], ['/m/reservations', 'reservations'], ['/m/transfers', 'transfers'],
  ['/rider', 'delivery'], ['/replacement/new', 'replacement', 'create'], ['/replacement', 'replacement'],
  ['/pos/exceptions', 'pos', 'approve'], ['/pos', 'pos'], ['/market-shortage', 'shortage'],
  ['/phantom-sales', 'purchasing'], ['/cash-optimization', 'purchasing'], ['/audit', 'audit'],
  ['/users', 'users'], ['/phone-alerts', 'settings'], ['/settings', 'settings'], ['/data-health', 'data_health'],
  ['/invoices', 'invoices'], ['/incentives', 'incentives'], ['/cheques', 'cheques'], ['/approvals', 'approvals'],
  ['/payment-audit', 'finance'], ['/reconciliation', 'finance'], ['/forecasting', 'analytics'],
  ['/usage-print', 'usage_print'], ['/reservations', 'reservations'], ['/missed-sales', 'pos'],
  ['/transfers', 'transfers'], ['/transits', 'transfers'], ['/demand', 'demand'], ['/followups', 'followups'],
  ['/delivery', 'delivery'], ['/stock-count', 'stockcount'], ['/omni', 'callcenter'], ['/callcenter', 'callcenter'],
  ['/campaigns', 'campaigns'], ['/whatsapp', 'callcenter'], ['/pbx', 'callcenter'],
  ['/customers/merge', 'customers', 'edit'], ['/customers/pic-analytics', 'pic_analytics'], ['/customers', 'customers'],
  ['/vouchers', 'vouchers'], ['/loyalty', 'customers'], ['/referral-stats', 'analytics'], ['/referral', 'customers'],
  ['/products', 'catalog'], ['/inventory', 'catalog'], ['/batches', 'catalog'], ['/stock-audit', 'stock_audit'],
  ['/shortage', 'shortage'], ['/catalog-intelligence', 'catalog'], ['/chronic-classifier', 'chronic'],
  ['/composition', 'chronic'], ['/counselling', 'counselling'], ['/ingredient-search', 'catalog'],
  ['/image-enrichment', 'catalog'], ['/recommendations', 'analytics'], ['/offers', 'offers'],
  ['/purchasing', 'purchasing'], ['/procurement', 'purchasing'], ['/supply', 'purchasing'],
  ['/pricing-approvals', 'approvals'], ['/discount-alignment', 'approvals'], ['/analytics', 'analytics'],
  ['/targets', 'analytics'], ['/kpi-board', 'analytics'], ['/salesperson-board', 'analytics'],
  ['/forecast-scenarios', 'analytics'], ['/insights', 'analytics'], ['/vision-corpus', 'catalog'],
  ['/finance/journal', 'ledger'], ['/finance', 'finance'], ['/insurance', 'insurance'], ['/commerce', 'commerce'],
  ['/hr/attendance', 'hr_attendance'], ['/permissions', 'users', 'edit'], ['/erp-permissions', 'users', 'edit'],
  ['/code-maps', 'settings'], ['/sync', 'sync'], ['/access', 'settings'],
]
export function moduleForRoute(route) {
  const p = route.split('?')[0]
  let best = null
  for (const [prefix, module, action = 'view'] of ROUTE_MODULE) {
    if ((p === prefix || p.startsWith(prefix + '/')) && (!best || prefix.length > best.prefix.length)) best = { prefix, module, action }
  }
  return best ? `${best.module}:${best.action}` : null
}

// Checks that are not a screen: file + a text anchor on the line → inferred perm.
//   'branch:all' = the check opens another branch (a branch picker / per-branch breakdown); the
//   table side is then the role's all-branches flag (core.branch_scope), not a module action.
//   routing = not a permission gate (where to land after login); catalogued, no verdict.
//   orMatrix = the code ORs the role with the matrix answer (role only adds, never removes).
//   extra = another per-user switch also opens it (is_staff / a capability), noted in the verdict.
const SITE_PERMS = [
  ['src/App.jsx', "user?.role === 'delivery'", { routing: true, why: 'delivery users land on /rider' }],
  ['src/pages/LoginPage.jsx', "role === 'delivery'", { routing: true, why: 'delivery users land on /rider after login' }],
  ['src/components/MobileLayout.jsx', "role === 'admin'", { routing: true, why: 'admin bypass of the mobile tab module check (generic, not a gate)' }],
  ['src/components/followups/CallListsPanel.jsx', 'CREATORS.includes', { perm: 'followups:create', why: 'create a call list (uses CREATORS)' }],
  ['src/components/followups/CallListsPanel.jsx', 'const CREATORS', { perm: 'followups:create', why: 'create a call list' }],
  ['src/components/InTransitTab.jsx', 'const isAdmin', { perm: 'transfers:approve', why: 'receive for any branch / force-close a transit' }],
  ['src/hooks/useClosedBranches.jsx', 'isAdmin', { perm: 'settings:edit', why: 'show closed branches toggle' }],
  ['src/pages/AnnouncementsPage.jsx', 'const canBroadcast', { perm: 'settings:create', why: 'broadcast an announcement (no announcements module)' }],
  ['src/pages/AnnouncementsPage.jsx', 'const mine', { perm: 'settings:delete', why: 'edit/delete someone else\'s announcement' }],
  ['src/pages/BatchesPage.jsx', 'const isAdmin', { perm: 'catalog:edit', why: 'batch admin actions' }],
  ['src/pages/BatchesPage.jsx', 'const canSync', { perm: 'catalog:edit', why: 'trigger an expiry sync' }],
  ['src/pages/BatchesPage.jsx', 'const canApprove', { perm: 'catalog:approve', why: 'approve a purchase-expiry re-check' }],
  ['src/pages/CallCenterAnalyticsPage.jsx', 'const allowed', { perm: 'callcenter:view', why: 'call-quality analytics screen' }],
  ['src/pages/CallCenterPage.jsx', 'const canEdit', { perm: 'callcenter:edit', why: 'edit a case' }],
  ['src/pages/CallCenterPage.jsx', 'const isManager', { perm: 'callcenter:approve', why: 'manager actions on cases' }],
  ['src/pages/CasesPage.jsx', 'const canEdit', { perm: 'callcenter:edit', why: 'edit a case' }],
  ['src/pages/CasesPage.jsx', 'const canCreate', { perm: 'callcenter:create', why: 'open a case' }],
  ['src/pages/CrewsPage.jsx', 'const isAdmin', { perm: 'crews:view', orMatrix: true, why: 'admin shortcut beside usePermissions(crews)' }],
  ['src/pages/DashboardPage.jsx', 'const isAdminOrCC', { perm: 'branch:all', why: 'per-branch breakdown on the dashboard' }],
  ['src/pages/DashboardPage.jsx', "'quality_manager'].includes(user?.role) &&", { perm: 'purchasing:view', why: 'supply control-tower KPI section' }],
  ['src/pages/DashboardPage.jsx', "user?.role !== 'call_center'", { perm: 'purchasing:view', roles: ['admin', 'purchasing'], why: 'purchasing shortcut card (isAdminOrCC minus call_center)' }],
  ['src/pages/DataHealthPage.jsx', 'const isAdmin', { perm: 'data_health:edit', why: 'rules + held-files tabs' }],
  ['src/pages/DemandPage.jsx', 'const isCCOrAdmin', { perm: 'branch:all', why: 'branch filter on the demand list' }],
  ['src/pages/FinanceHubPage.jsx', 'const isAdmin', { perm: 'finance:edit', why: 'admin-only finance tabs + freshness refresh' }],
  ['src/pages/FollowUpsPage.jsx', "user?.role === 'admin'", { perm: 'settings:edit', why: 'follow-up channel settings' }],
  ['src/pages/ForecastScenarioPage.jsx', 'const canEdit', { perm: 'analytics:edit', why: 'edit a forecast scenario' }],
  ['src/pages/InsightsPage.jsx', 'const canRun', { perm: 'analytics:create', why: 'run a narrative report' }],
  ['src/pages/InsightsPage.jsx', 'const canEditRules', { perm: 'analytics:edit', why: 'edit insight rules (matches InsightRuleViewSet._guard)' }],
  ['src/pages/KpiBoardPage.jsx', 'const canEdit', { perm: 'analytics:edit', why: 'edit branch KPI targets' }],
  ['src/pages/mobile/mobileAccess.js', 'MOBILE_RESERVATION_ROLES =', { perm: 'reservations:view', why: 'mobile reservations' }],
  ['src/pages/mobile/mobileAccess.js', 'MOBILE_TRANSFER_ROLES =', { perm: 'transfers:view', why: 'mobile transfers' }],
  ['src/pages/mobile/MobileNewDemandPage.jsx', 'canPickBranch', { perm: 'branch:all', why: 'pick the branch of a new demand' }],
  ['src/pages/mobile/MobileNewReservationPage.jsx', 'canPickBranch', { perm: 'branch:all', why: 'pick the branch of a new reservation' }],
  ['src/pages/mobile/MobileNewShortagePage.jsx', 'canPickBranch', { perm: 'branch:all', why: 'pick the branch of a shortage line' }],
  ['src/pages/mobile/MobileNewTransferPage.jsx', 'canPickRequesting', { perm: 'branch:all', why: 'pick the requesting branch' }],
  ['src/pages/mobile/MobileQAPage.jsx', 'canPickBranch', { perm: 'branch:all', why: 'pick the branch of a QA round' }],
  ['src/pages/mobile/MobileReservationDetailPage.jsx', 'PRIVILEGED', { perm: 'reservations:edit', why: 'cancel a reservation from mobile' }],
  ['src/pages/mobile/MobileReservationsPage.jsx', 'MOBILE_RESERVATION_ROLES', { perm: 'reservations:view', why: 'mobile reservations screen', rolesFrom: 'MOBILE_RESERVATION_ROLES' }],
  ['src/pages/MyDashboardPage.jsx', 'const isAdmin', { perm: 'approvals:approve', why: 'approval queue on /me' }],
  ['src/pages/NewReservationPage.jsx', 'const isCCOrAdmin', { perm: 'branch:all', why: 'branch picker on a new reservation' }],
  ['src/pages/OmniWallboardPage.jsx', 'const canSpy', { perm: 'callcenter:approve', why: 'listen-in / supervisor controls' }],
  ['src/pages/PbxLivePage.jsx', 'const canConfigure', { perm: 'callcenter:edit', why: 'PBX configuration' }],
  ['src/pages/PermissionsMatrixPage.jsx', 'const isAdmin', { perm: 'users:edit', why: 'edit the role matrix' }],
  ['src/pages/PickZonesPage.jsx', 'const canEdit', { perm: 'purchasing:edit', why: 'edit pick zones' }],
  ['src/pages/PricingApprovalsPage.jsx', 'const isAdmin', { perm: 'approvals:approve', extra: 'is_staff', why: 'approve/replicate a price change' }],
  ['src/pages/PurchasingDashboard.jsx', 'const isAdmin', { perm: 'purchasing:approve', why: 'admin-only purchasing actions' }],
  ['src/pages/PurchasingDashboard.jsx', 'const canRunEngine', { perm: 'purchasing:create', extra: 'can_run_engine', why: 'run the replenishment engine' }],
  ['src/pages/PurchasingPage.jsx', 'const denied', { perm: 'purchasing:view', why: 'purchasing screen guard' }],
  ['src/pages/RecommendationsPage.jsx', 'const isAdmin', { perm: 'analytics:edit', why: 'manage recommendation rules' }],
  ['src/pages/ReservationsKanban.jsx', 'const isCCOrAdmin', { perm: 'branch:all', why: 'branch name on cards (cross-branch board)' }],
  ['src/pages/SalespersonBoardPage.jsx', 'const canEdit', { perm: 'analytics:edit', why: 'edit salesperson targets' }],
  ['src/pages/SettingsPage.jsx', 'const isAdmin', { perm: 'settings:edit', why: 'admin settings sections' }],
  ['src/pages/SupplierSegmentationPage.jsx', 'const isAdmin', { perm: 'purchasing:edit', why: 'edit supplier segments' }],
  ['src/pages/TargetsPage.jsx', 'const canEdit', { perm: 'analytics:edit', why: 'edit sales targets' }],
  ['src/pages/UserManagementPage.jsx', 'const isAdmin', { perm: 'users:edit', why: 'admin-only user fields' }],
  ['src/pages/VouchersPage.jsx', 'const canSeeCoupons', { perm: 'vouchers:edit', why: 'gift-coupons tab' }],
]
// DataFreshnessBar canEdit={user?.is_staff || role…}: the forced-refresh button.
const FRESHNESS = { perm: 'sync:edit', extra: 'is_staff', why: 'forced refresh on the freshness bar' }

// Lines that name a role word but are not about the signed-in user's role.
const NOT_USER_ROLE = /\b(d|s|form|r|c|a)\.role\b|role_label|ColumnMapper|role === 'anon'|t\.roles\.includes|it\.roles|f\.roles|itemRoles/

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (/\.(jsx?|tsx?)$/.test(e.name) && !/\.test\./.test(e.name) && !p.includes('__tests__')) out.push(p)
  }
  return out
}

/** Is this line a role check? → its kind, else null. */
function kindOf(line) {
  if (NOT_USER_ROLE.test(line)) return null
  const lits = literalRoles(line)
  if (/RequireRole\s+roles=\{\[/.test(line)) return lits.length ? 'route-guard' : null
  if (/\broles:\s*(\[|[A-Z_]{4,})/.test(line) && /\bto:\s*'/.test(line)) return 'menu'          // nav / mobile tab
  if (lits.length && /\brole\b\s*\)?\s*(===|!==)\s*'/.test(line)) return 'compare'
  if (lits.length && /\.(includes|has)\(\s*(user|currentUser|me)?\??\.?role\s*\)/.test(line)) return 'list'
  if (lits.length >= 2 && /^\s*(export\s+)?const\s+[A-Z_]+\s*=\s*(new Set\()?\[/.test(line)) {
    const all = [...line.matchAll(/'([^']*)'/g)].map(m => m[1])
    return all.every(x => ROLE_WORDS.includes(x)) ? 'role-list' : null        // FILTER_KEYS etc. are not role lists
  }
  return null
}

/** Allowed roles of a hit (literal roles on the line; a named list resolved from the code). */
function rolesOf(line, kind, fileText, site) {
  if (site?.roles) return site.roles
  let lits = literalRoles(line)
  const named = line.match(/\b([A-Z_]{4,})\.(includes|has)\(/) || line.match(/\broles:\s*([A-Z_]{4,})/)
  if (!lits.length && named) {
    const def = fileText.match(new RegExp(`${named[1]}\\s*=\\s*(new Set\\()?\\[([^\\]]*)\\]`))
    if (def) lits = literalRoles(def[2])
    else if (named[1] === 'MOBILE_RESERVATION_ROLES' || named[1] === 'MOBILE_TRANSFER_ROLES') {
      const acc = fs.readFileSync(path.join(SRC, 'pages', 'mobile', 'mobileAccess.js'), 'utf-8')
      const d = acc.match(new RegExp(`${named[1]}\\s*=\\s*\\[([^\\]]*)\\]`))
      if (d) lits = literalRoles(d[1])
    }
  }
  if (kind === 'compare' && /!==/.test(line) && !/===/.test(line)) return { not: lits }
  return [...new Set(lits)]
}

/** Every role check in src/ with its inferred perm. */
export function scanRoleChecks() {
  const hits = []
  for (const abs of walk(SRC)) {
    const rel = path.relative(path.resolve(SRC, '..'), abs).replace(/\\/g, '/')
    const text = fs.readFileSync(abs, 'utf-8')
    const lines = text.split(/\r?\n/)
    lines.forEach((line, i) => {
      // a named list used with .includes(user?.role) on this line (CREATORS.includes(user?.role))
      let kind = kindOf(line)
      if (!kind && /\b[A-Z_]{4,}\.(includes|has)\(\s*user\??\.role\s*\)/.test(line)) kind = 'list'
      if (!kind) return
      const site = SITE_PERMS.find(([f, anchor]) => f === rel && line.includes(anchor))?.[2]
      const roles = rolesOf(line, kind, text, site)
      // a <Route path="x"> whose element={<RequireRole …>} sits on the next line
      const prevPath = kind === 'route-guard' && !/\bpath="/.test(line) ? (lines[i - 1] || '').match(/\bpath="([^"]+)"/)?.[1] : null
      const to = line.match(/\bto:\s*'([^']+)'/)?.[1] || line.match(/\bpath="([^"]+)"/)?.[1] || prevPath
      let route = to ? (to.startsWith('/') ? to : `/${to}`) : null
      let inferred = null
      if (route) inferred = { perm: moduleForRoute(route), why: `screen ${route}` }
      else if (site) inferred = site
      else if (/DataFreshnessBar|canEdit=\{user\?\.is_staff/.test(line)) inferred = FRESHNESS
      const cap = line.match(/\bcap:\s*'([^']+)'/)?.[1]
      const andModule = line.match(/\bmodule:\s*'([^']+)'/)?.[1]
      hits.push({
        file: rel, line: i + 1, kind, roles, route, cap, andModule,
        code: line.trim().slice(0, 160),
        perm: inferred?.perm || null, why: inferred?.why || 'no inference — needs a decision',
        routing: !!inferred?.routing, orMatrix: !!inferred?.orMatrix,
        extra: inferred?.extra || cap || null,
        unknownRoles: (Array.isArray(roles) ? roles : roles.not).filter(r => UNKNOWN_ROLE_WORDS.includes(r)),
      })
    })
  }
  return hits
}

/**
 * Compare one check with the table.
 * @param hit from scanRoleChecks
 * @param tableAllows (role, perm) => boolean   ('branch:all' → the role's allBranches flag)
 * @returns {{verdict: 'match'|'looser'|'stricter'|'both'|'routing'|'no-inference', looser: string[], stricter: string[]}}
 */
export function verdictFor(hit, tableAllows) {
  if (hit.routing) return { verdict: 'routing', looser: [], stricter: [] }
  if (!hit.perm) return { verdict: 'no-inference', looser: [], stricter: [] }
  const codeAllows = r => {
    const listed = Array.isArray(hit.roles) ? hit.roles.includes(r) : !hit.roles.not.includes(r)
    if (hit.orMatrix) return listed || tableAllows(r, hit.perm)
    if (hit.andModule) return listed && (r === 'admin' || tableAllows(r, `${hit.andModule}:view`))
    return listed
  }
  const looser = [], stricter = []
  for (const r of ROLES) {
    const code = codeAllows(r), table = tableAllows(r, hit.perm)
    if (code && !table) looser.push(r)
    if (!code && table) stricter.push(r)
  }
  const verdict = looser.length && stricter.length ? 'both' : looser.length ? 'looser' : stricter.length ? 'stricter' : 'match'
  return { verdict, looser, stricter }
}
