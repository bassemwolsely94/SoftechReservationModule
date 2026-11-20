import { describe, expect, it } from 'vitest'
import { moduleActionAllowed } from '../../components/navGroups'
import {
  WRITE_ACTIONS, RESERVATION_TRANSITIONS, reservationTransitions, isFinalReservationStatus, qaCreateAllowed,
} from './mobileWriteGates'

// grants as /api/users/my-permissions/ returns them (seed_permissions.py)
const RO = { view: true }
const RE = { view: true, export: true }
const RW = { view: true, create: true, edit: true }
const allSeeded = ['reservations', 'demand', 'transfers', 'shortage', 'hr']
const who = (role, perms) => ({ role, perms, seeded: allSeeded })

describe('mobile create gates mirror each endpoint POST rule (UAT W8)', () => {
  it('a view-only role (viewer RO) gets no create form anywhere', () => {
    const u = who('viewer', { reservations: RO, demand: RO, transfers: RO, shortage: RO, hr: RO })
    for (const m of ['reservations', 'demand', 'transfers', 'shortage', 'hr']) {
      expect(moduleActionAllowed(u, m, WRITE_ACTIONS[m])).toBe(false)
    }
  })

  it('view + export (quality manager on reservations) is not a create grant', () => {
    expect(moduleActionAllowed(who('quality_manager', { reservations: RE }), 'reservations',
      WRITE_ACTIONS.reservations)).toBe(false)
  })

  it('a create or edit grant opens the form (server POST accepts any of them)', () => {
    expect(moduleActionAllowed(who('pharmacist', { reservations: RW }), 'reservations', WRITE_ACTIONS.reservations)).toBe(true)
    expect(moduleActionAllowed(who('x', { demand: { view: true, edit: true } }), 'demand', WRITE_ACTIONS.demand)).toBe(true)
    expect(moduleActionAllowed(who('x', { transfers: { finalize: true } }), 'transfers', WRITE_ACTIONS.transfers)).toBe(true)
  })

  it('shortage lists: finalize is not part of the POST rule', () => {
    expect(WRITE_ACTIONS.shortage).toEqual(['create', 'edit', 'approve'])
    expect(moduleActionAllowed(who('x', { shortage: { view: true, finalize: true } }), 'shortage', WRITE_ACTIONS.shortage)).toBe(false)
  })

  it('QA write = hr grant beyond view, export included (apps/qa _QA_WRITE)', () => {
    expect(moduleActionAllowed(who('quality_manager', { hr: RE }), 'hr', WRITE_ACTIONS.hr)).toBe(true)
    expect(moduleActionAllowed(who('viewer', { hr: RO }), 'hr', WRITE_ACTIONS.hr)).toBe(false)
  })

  it('admin always, permissions not loaded never', () => {
    expect(moduleActionAllowed({ role: 'admin', perms: null }, 'demand', WRITE_ACTIONS.demand)).toBe(true)
    expect(moduleActionAllowed({ role: 'pharmacist', perms: null }, 'demand', WRITE_ACTIONS.demand)).toBe(false)
  })

  it('an unseeded module falls back to the legacy role list (shortage)', () => {
    const u = { role: 'pharmacist', perms: {}, seeded: [] }
    const legacy = ['admin', 'pharmacist']
    expect(moduleActionAllowed(u, 'shortage', WRITE_ACTIONS.shortage, legacy)).toBe(true)
    expect(moduleActionAllowed({ ...u, role: 'viewer' }, 'shortage', WRITE_ACTIONS.shortage, legacy)).toBe(false)
  })
})

describe('qaCreateAllowed: hr write AND the server reading the list to this role', () => {
  it('needs the hr write grant', () => {
    expect(qaCreateAllowed(false, null)).toBe(false)
    expect(qaCreateAllowed(true, null)).toBe(true)
  })
  it('a refused inspections list (role outside the QA roles) hides the plus', () => {
    expect(qaCreateAllowed(true, { response: { status: 403 } })).toBe(false)
  })
  it('a network failure does not hide it (the server decides on submit)', () => {
    expect(qaCreateAllowed(true, { message: 'Network Error' })).toBe(true)
  })
})

describe('reservation status buttons (mobile detail)', () => {
  it('no buttons at all without the change-status grant, cancel included', () => {
    for (const s of Object.keys(RESERVATION_TRANSITIONS)) {
      expect(reservationTransitions(s, false)).toEqual([])
    }
  })
  it('with the grant: the server graph, unchanged', () => {
    expect(reservationTransitions('pending', true)).toEqual(['available', 'cancelled', 'expired'])
    expect(reservationTransitions('expired', true)).toEqual(['pending'])
    expect(reservationTransitions('fulfilled', true)).toEqual([])
  })
  it('final states are told apart from read-only', () => {
    expect(isFinalReservationStatus('cancelled')).toBe(true)
    expect(isFinalReservationStatus('fulfilled')).toBe(true)
    expect(isFinalReservationStatus('pending')).toBe(false)
  })
  it('returns a copy (callers cannot change the graph)', () => {
    reservationTransitions('pending', true).push('x')
    expect(RESERVATION_TRANSITIONS.pending).not.toContain('x')
  })
})
