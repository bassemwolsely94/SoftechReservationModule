// W3: the screens the button sweep opens, and each main screen's primary actions.
//   route   the screen; `:id` is filled from the UAT reference set (`ref` names the list)
//   actions the primary controls: `perm` = the module:action that gates it in the code,
//           `sel` = a stable selector (the data-tour hook). Allowed by the matrix but not on
//           screen → P3 `button`. Detail screens have no primary actions here: their buttons
//           depend on the record's status, so only the data-perm rule applies to them.
export const SCREENS = [
  { route: '/dashboard', actions: [] },
  { route: '/reservations', actions: [
    { perm: 'reservations:create', sel: '[data-tour="reservations-board-new"]', label: '+ حجز جديد' },
  ] },
  { route: '/transfers', actions: [
    { perm: 'transfers:create', sel: '[data-tour="transfers-list-new"]', label: '+ طلب تحويل جديد' },
  ] },
  { route: '/demand', actions: [
    { perm: 'demand:create', sel: '[data-tour="demand-list-new"]', label: '+ تسجيل طلب جديد' },
    { perm: 'analytics:view', sel: '[data-tour="demand-list-dashboard"]', label: 'لوحة الطلب الضائع' },
  ] },
  { route: '/demand/recovery', actions: [
    { perm: 'analytics:view', sel: '[data-tour="demand-recovery-dashboard"]', label: 'لوحة الطلب الضائع' },
  ] },
  { route: '/vouchers', actions: [
    { perm: 'reservations:create', sel: '[data-tour="vouchers-main-new"]', label: '+ قسيمة جديدة' },
  ] },
  { route: '/stock-count', actions: [
    { perm: 'admin:create', sel: '[data-tour="stockcount-sessions-new"]', label: 'جلسة جرد جديدة' },
  ] },
  { route: '/followups', actions: [] },
  { route: '/reservations/:id', ref: 'reservations', actions: [] },
  { route: '/transfers/:id', ref: 'transfers', actions: [] },
  { route: '/demand/:id', ref: 'demand', actions: [] },
]

const idOf = x => (x && typeof x === 'object' ? x.id : x)

/** The concrete URL of a screen for a user whose records live in `home` ('A'|'B'); null = no id. */
export function urlFor(screen, refs, home) {
  if (!screen.ref) return screen.route
  const other = home === 'A' ? 'B' : 'A'
  const id = idOf(refs[home]?.[screen.ref]?.[0]) ?? idOf(refs[other]?.[screen.ref]?.[0])
  return id == null ? null : screen.route.replace(':id', String(id))
}
