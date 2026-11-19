// W4 exposure rules: for each domain (a group of screens), what a user may see of a record that
// belongs to branch A or B, and of a customer whose home branch is A or B:
//   branch: 'absent' | 'full' | 'decision'        (the record itself)
//   phone:  'masked' | 'full' | 'decision'        (a reference customer's full number)
//
// Derived ONLY from (design §7.1):
//   [ROLES]   apps/users/roles.py — all_branches roles; exported per user as expectedFor(key).allBranches /
//             branchIds (core/branch_scope.branch_ids: home + allowed − restricted; all-branch roles
//             see every branch except a restricted one).
//   [B-1]     finance is company-level for the all-branch roles (roles.py accountant comment, PERMISSION_MATRIX).
//   [B-2]     apps/customers/access.py docstring: browse / name-search own customers only; another
//             branch's customer is found by FULL phone and opens, but its numbers are masked;
//             can_see_customer_phone=False masks every number (phones_visible / customer_phone).
//   [B-3]     supervisor / quality_manager are all-branch (roles.py, branch_scope docstring).
//   [D2-D8]   docs/security/PHONE_MASKING_PLAN.md as built in access.record_phones_visible: a number
//             needed to serve a record the user can see is shown whatever the customer's home
//             branch (D2); hidden for can_see_customer_phone=False (D3) and for the viewer role
//             (D4 reservations, D7 call-center inboxes); a rider keeps the number of orders assigned
//             to them (D5); referral leads masked except the adder and all-branch roles (D8).
//   [DEC3]    owner decision 3 (PERMISSION_MATRIX "branch scope" column): transfers are visible to
//             the requesting OR the supplying side; stock is network-wide.
//   [CANARY]  apps/tests/security/baselines/branch_canary_leaks.txt GET-DETAIL lines: customer
//             profile / POS summary / loyalty account open whatever the branch (B-2); insurance
//             claims are an HQ module (admin + purchasing), company-level.
//   [PHONE-CANARY] apps/tests/security/baselines/phone_canary_leaks.txt: only riders' own mobiles and
//             channel accounts' business numbers — no customer number is excused anywhere.
// Anything these sources do not settle is 'decision' (a question for the owner, never a P0).
import { expectedFor } from '../lib/expected.js'
import { BRANCH_A, BRANCH_B, UAT_USERS } from '../lib/users.js'

export const WS = 'W4'

/** The users W4 visits as (task 8: branch-B users, phone-hidden, multi-branch, restricted), plus
 *  the A-side phone-visible pharmacist (over-masking baseline) and the A viewer (D4 / D7). */
export const EXPOSURE_USERS = ['pharmacist@B', 'salesperson@B', 'viewer@B', 'delivery@B',
  'phoneHidden', 'phoneVisible', 'multi', 'restricted', 'viewer']
  .filter(k => UAT_USERS.some(u => u.key === k))

export const BRANCH = { A: BRANCH_A, B: BRANCH_B }

/** [ROLES] branch_scope.branch_ids(), as exported for this user. */
export function sees(key, branch) {
  const e = expectedFor(key)
  return !!e.allBranches || (e.branchIds || []).includes(BRANCH[branch].id)
}

/** 'A' | 'B' | 'other' | null for a branch value from a JSON record (pk, SOFTECH code, name, or object). */
export function branchOf(value) {
  if (value == null || value === '') return null
  if (typeof value === 'object') return branchOf(value.id ?? value.code ?? value.softech_branch_id ?? value.name)
  const s = String(value).trim()
  for (const b of ['A', 'B']) {
    const br = BRANCH[b]
    if (s === String(br.id) || s === String(br.code) || s === br.name) return b
  }
  return 'other'
}

/** May the user see a record whose branch value is `value`? null = not identifiable.
 *  A third branch ('other') is visible to all-branch users and to a pk in the exported branchIds. */
export function seesBranchValue(key, value) {
  const b = branchOf(value)
  if (b === null) return null
  if (b === 'A' || b === 'B') return sees(key, b)
  const e = expectedFor(key)
  if (e.allBranches) return true
  const raw = typeof value === 'object' ? value.id : value
  return /^\d+$/.test(String(raw)) && String(raw).length <= 2 ?   // pks are 1-2 digits, SOFTECH codes 3
 (e.branchIds || []).includes(Number(raw)) : null
}

// kind 'customer' = numbers shown because of WHO the customer is (B-2: access.customer_phone);
// kind 'record'   = numbers shown to serve a record (D2: access.record_phone).
// routes: desktop and mobile screens of the domain. listApi: the list endpoint whose results[].id
// are compared with reference ids of a branch the user may not see. refKey: reference(...) list.
export const DOMAINS = {
  customers:    { kind: 'customer', routes: ['/customers', '/m/customers'], listApi: /\/api\/customers\/(\?|$)/, refKey: 'customers',
                  src: 'B-2: browse / name-search own customers only' },
  customer360:  { kind: 'customer', routes: [], src: 'B-2 + CANARY GET-DETAIL /api/customers/<id>/: a found customer opens, other-branch phones masked' },
  reservations: { kind: 'record', routes: ['/reservations', '/reservations/list', '/m/reservations'], listApi: /\/api\/reservations\/(\?|$)/, refKey: 'reservations',
                  detail: id => `/reservations/${id}`, detailApi: id => `/api/reservations/${id}/`,
                  src: 'PERMISSION_MATRIX reservations: own (branch_scope); D2/D4' },
  demand:       { kind: 'record', routes: ['/demand', '/demand/dashboard', '/m/demand'], listApi: /\/api\/demand\/(\?|$)/, refKey: 'demand',
                  detail: id => `/demand/${id}`, detailApi: id => `/api/demand/${id}/`,
                  src: 'PERMISSION_MATRIX demand: own list/detail; analytics network-wide (open); D2' },
  followups:    { kind: 'record', routes: ['/followups', '/followups/reminders', '/refills'],
                  src: 'PERMISSION_MATRIX followups: own (branch_scope); D2 + PHONE_MASKING_PLAN part 1 #11 (wa.me links)' },
  transfers:    { kind: 'record', routes: ['/transfers', '/m/transfers'], listApi: /\/api\/transfers\/(\?|$)/, refKey: 'transfers',
                  detail: id => `/transfers/${id}`, detailApi: id => `/api/transfers/${id}/`,
                  src: 'DEC3: requesting OR supplying side' },
  pos:          { kind: 'record', routes: ['/pos', '/pos/exceptions', '/m/pos', '/missed-sales'], listApi: /\/api\/pos-orders\/(\?|$)/, refKey: 'posOrders',
                  detailApi: id => `/api/pos-orders/${id}/`,
                  src: 'PERMISSION_MATRIX pos: own — orders, queue, exceptions; D2 (POS share on WhatsApp)' },
  shortage:     { kind: 'record', routes: ['/shortage', '/m/shortage'], listApi: /\/api\/shortage\/lists\/(\?|$)/, refKey: 'shortage',
                  detail: id => `/shortage/${id}`, detailApi: id => `/api/shortage/lists/${id}/`,
                  src: 'PERMISSION_MATRIX shortage: own lists' },
  delivery:     { kind: 'record', routes: ['/delivery', '/delivery/dispatch', '/m/delivery', '/rider'],
                  src: 'PERMISSION_MATRIX delivery: own (+ rider: assigned orders); D5' },
  callcenter:   { kind: 'record', routes: ['/callcenter', '/callcenter/cases', '/callcenter/callbacks', '/omni/inbox', '/whatsapp/inbox', '/pbx/live'],
                  src: 'PERMISSION_MATRIX callcenter: own + assigned; D1 / D7 (viewer masked)' },
  insurance:    { kind: 'insurance', routes: ['/insurance', '/insurance/rosters'],
                  src: 'CANARY: insurance claims HQ module (admin + purchasing), company-level; no phone rule stated' },
  referral:     { kind: 'customer', routes: ['/referral', '/referral-stats'],
                  src: 'D8: leads masked except adder + all-branch roles; reference customers follow B-2' },
  loyalty:      { kind: 'customer', routes: ['/loyalty', '/loyalty/branch'],
                  src: 'CANARY GET-DETAIL /api/loyalty/customers/<id>/account/: opens whatever the branch (B-2)' },
  picAnalytics: { kind: 'customer', routes: ['/customers/pic-analytics'],
                  src: 'PERMISSION_MATRIX pic_analytics: own — named managers their branches; export masks like the screen' },
  sales:        { kind: 'customer', routes: ['/history', '/sales', '/segments'], invoices: true,
                  src: 'PERMISSION_MATRIX analytics: own — sales, customers, churn; customer search B-2' },
  search:       { kind: 'customer', routes: [], src: 'B-2: name search own only; full phone finds any customer, masked' },
  exports:      { kind: 'byDomain', routes: [], src: 'each export follows its screen domain' },
}

/**
 * Branch rule for a record of `branch` in `domain`, seen by user `key`.
 * `sides` (transfers only): ['A','B'|'other'] = requesting / supplying side.
 */
export function branchRule(key, domain, branch, sides = null) {
  const d = DOMAINS[domain]
  if (!d) return { rule: 'decision', src: `unknown domain ${domain}` }
  if (domain === 'customer360' || domain === 'loyalty') return { rule: 'full', src: d.src }
  if (domain === 'insurance') return { rule: 'full', src: d.src }   // company-level for its holders
  if (domain === 'transfers' && sides) {
    const visible = sides.some(s => s !== 'other' && s && sees(key, s))
    return { rule: visible ? 'full' : 'absent', src: d.src }
  }
  return { rule: sees(key, branch) ? 'full' : 'absent', src: `${d.src} [ROLES branch_ids]` }
}

/**
 * Phone rule for a reference customer whose home branch is `custBranch`, shown on `domain`.
 * `recordVisible` (record domains): does the record carrying the number belong to one of the user's
 * branches (true / false), or is its branch not identifiable in the response (null)?
 */
export function phoneRule(key, domain, custBranch, recordVisible = null) {
  const e = expectedFor(key)
  const d = DOMAINS[domain]
  if (!d) return { rule: 'decision', src: `unknown domain ${domain}` }
  if (!e.seesPhones) return { rule: 'masked', src: 'B-2 / D3: can_see_customer_phone=False masks every number' }
  if (d.kind === 'insurance') return { rule: 'decision', src: d.src }
  if (d.kind === 'customer') {
    return sees(key, custBranch)
      ? { rule: 'full', src: 'B-2: own customer' }
      : { rule: 'masked', src: 'B-2: another branch\'s customer is masked' }
  }
  // record kind — access.record_phones_visible
  if (e.role === 'viewer') return { rule: 'masked', src: 'D4 / D7: viewer role masked on records' }
  if (sees(key, custBranch)) return { rule: 'full', src: 'D2: own record, own customer' }
  if (recordVisible === true) return { rule: 'full', src: 'D2: number on the user\'s own-branch record' }
  if (domain === 'delivery' && e.role === 'delivery') return { rule: 'decision', src: 'D5: rider keeps numbers of orders assigned to them — assignment not visible here' }
  if (recordVisible === false) return { rule: 'masked', src: 'D2 only covers records the user can see' }
  return { rule: 'decision', src: 'D2: record branch not identifiable in the response' }
}
