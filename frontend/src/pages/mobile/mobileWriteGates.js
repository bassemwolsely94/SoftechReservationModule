/**
 * mobileWriteGates.js — which write controls a phone screen offers, mirroring each endpoint's
 * server rule exactly (UAT W8, 2026-11-20). The server still decides (CLAUDE.md rule 9); these
 * only stop the screen offering a button the server would refuse. No role lists here: every gate
 * reads the grants /api/users/my-permissions/ returns (via useModuleAction).
 */

// POST rule of each create endpoint — keep in step with the server:
export const WRITE_ACTIONS = {
  // apps/reservations/views.py ReservationsPermission: POST needs create/edit/approve/finalize
  // (covers create AND change-status)
  reservations: ['create', 'edit', 'approve', 'finalize'],
  // apps/demand/views.py DEMAND = matrix_permission('demand', post=(create, edit, approve, finalize))
  demand: ['create', 'edit', 'approve', 'finalize'],
  // apps/transfers/views.py TRANSFERS = matrix_permission('transfers', post=(...same...))
  transfers: ['create', 'edit', 'approve', 'finalize'],
  // apps/shortage/views.py SHORTAGE_LISTS = matrix_permission('shortage', post=(create, edit, approve))
  shortage: ['create', 'edit', 'approve'],
  // apps/qa/views.py QA = matrix_permission('hr', post=_QA_WRITE, exclude_roles=…): the hr grant
  // part; the role part is answered by the server refusing the inspections list (qaCreateAllowed)
  hr: ['create', 'edit', 'approve', 'finalize', 'export'],
}

// Mirror of ReservationViewSet._VALID_TRANSITIONS (apps/reservations/views.py) — only the FALLBACK
// for an older server whose detail answer has no `allowed_transitions` (it cannot see the server's
// "cancel from any state" for its override roles).
export const RESERVATION_TRANSITIONS = {
  pending:   ['available', 'cancelled', 'expired'],
  available: ['contacted', 'confirmed', 'cancelled', 'expired'],
  contacted: ['confirmed', 'available', 'cancelled', 'expired'],
  confirmed: ['fulfilled', 'cancelled', 'expired'],
  expired:   ['pending'],
  fulfilled: [],
  cancelled: [],
}

/** The status buttons to offer: none without the change-status grant (cancel included). */
export function reservationTransitions(status, canChangeStatus) {
  if (!canChangeStatus) return []
  return [...(RESERVATION_TRANSITIONS[status] || [])]
}

// button order on the phone: forward moves first, cancel last
const STATUS_RANK = Object.fromEntries(
  ['pending', 'available', 'contacted', 'confirmed', 'fulfilled', 'expired', 'cancelled'].map((s, i) => [s, i]))

/** The status buttons to offer for reservation `r`: exactly the server's per-requester
 *  `allowed_transitions` (views.allowed_transitions, the rule change-status enforces), or, when an
 *  older server sends none, the local graph gated on the change-status grant. */
export function offeredTransitions(r, canChangeStatus) {
  const list = Array.isArray(r?.allowed_transitions)
    ? r.allowed_transitions.filter(s => s !== r.status)
    : reservationTransitions(r?.status, canChangeStatus)
  const rank = s => STATUS_RANK[s] ?? 99
  return [...new Set(list)].sort((a, b) => rank(a) - rank(b))
}

/** Is the reservation in a final state (no move left in the server's graph)? */
export function isFinalReservationStatus(status) {
  return (RESERVATION_TRANSITIONS[status] || []).length === 0
}

/** QA «+»: the hr write grant AND the server not refusing this role the inspections list
 *  (the QA rule's role part, apps/users/roles.py qa_inspections). `listError` is the list query's
 *  error (axios), if any. */
export function qaCreateAllowed(hasHrWrite, listError) {
  if (!hasHrWrite) return false
  const status = listError?.response?.status
  return !(status === 401 || status === 403)
}
