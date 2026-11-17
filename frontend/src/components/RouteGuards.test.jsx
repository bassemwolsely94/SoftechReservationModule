import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('../api/client', () => ({
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
  migrateLegacyTokens: vi.fn(),
}))

const { default: useAuthStore } = await import('../store/authStore')
const { default: usePermissionStore } = await import('../store/permissionStore')
const { RequireAuth, RequireRole } = await import('./RouteGuards')
const { NAV_GROUPS, navItemVisible } = await import('./navGroups')

function renderAt(path, element) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<div>login page</div>} />
        <Route path="/dashboard" element={<div>dashboard page</div>} />
        <Route path="/secret" element={element} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false })
  usePermissionStore.setState({ permissions: null, role: null, isLoading: false })
})
afterEach(cleanup)

describe('RequireRole', () => {
  const guarded = <RequireRole roles={['admin', 'pharmacist']}><div>secret page</div></RequireRole>

  it.each(['admin', 'pharmacist'])('lets %s in', (role) => {
    useAuthStore.setState({ user: { role }, isAuthenticated: true })
    renderAt('/secret', guarded)
    expect(screen.getByText('secret page')).toBeTruthy()
  })

  it.each(['viewer', 'salesperson', 'delivery', 'accountant'])('sends %s to the dashboard', (role) => {
    useAuthStore.setState({ user: { role }, isAuthenticated: true })
    renderAt('/secret', guarded)
    expect(screen.queryByText('secret page')).toBeNull()
    expect(screen.getByText('dashboard page')).toBeTruthy()
  })

  it('a user without a role counts as viewer', () => {
    useAuthStore.setState({ user: {}, isAuthenticated: true })
    renderAt('/secret', <RequireRole roles={['viewer']}><div>secret page</div></RequireRole>)
    expect(screen.getByText('secret page')).toBeTruthy()
  })

  it('no user at all is refused', () => {
    renderAt('/secret', guarded)
    expect(screen.getByText('dashboard page')).toBeTruthy()
  })
})

describe('RequireRole with a matrix module (UAT D5)', () => {
  // /phone-alerts: the role list AND the matrix's settings view must both allow
  const guarded = <RequireRole roles={['admin', 'supervisor']} module="settings"><div>secret page</div></RequireRole>

  it('a listed role without the matrix grant goes to the dashboard', () => {
    useAuthStore.setState({ user: { role: 'supervisor' }, isAuthenticated: true })
    usePermissionStore.setState({ permissions: { users: { view: true } } })
    renderAt('/secret', guarded)
    expect(screen.queryByText('secret page')).toBeNull()
    expect(screen.getByText('dashboard page')).toBeTruthy()
  })

  it('a listed role with the grant gets in', () => {
    useAuthStore.setState({ user: { role: 'supervisor' }, isAuthenticated: true })
    usePermissionStore.setState({ permissions: { settings: { view: true } } })
    renderAt('/secret', guarded)
    expect(screen.getByText('secret page')).toBeTruthy()
  })

  it('the grant alone does not open it to a role off the list', () => {
    useAuthStore.setState({ user: { role: 'pharmacist' }, isAuthenticated: true })
    usePermissionStore.setState({ permissions: { settings: { view: true } } })
    renderAt('/secret', guarded)
    expect(screen.getByText('dashboard page')).toBeTruthy()
  })

  it('waits (no redirect, no page) while the matrix loads', () => {
    useAuthStore.setState({ user: { role: 'supervisor' }, isAuthenticated: true })
    renderAt('/secret', guarded)
    expect(screen.queryByText('secret page')).toBeNull()
    expect(screen.queryByText('dashboard page')).toBeNull()
  })

  it('admin passes before the matrix loads', () => {
    useAuthStore.setState({ user: { role: 'admin' }, isAuthenticated: true })
    renderAt('/secret', guarded)
    expect(screen.getByText('secret page')).toBeTruthy()
  })

  it('a named action other than view is asked', () => {
    useAuthStore.setState({ user: { role: 'supervisor' }, isAuthenticated: true })
    usePermissionStore.setState({ permissions: { pos: { view: true } } })
    renderAt('/secret', <RequireRole roles={['supervisor']} module="pos" action="approve"><div>secret page</div></RequireRole>)
    expect(screen.getByText('dashboard page')).toBeTruthy()
  })
})

describe('RequireAuth', () => {
  const guarded = <RequireAuth><div>secret page</div></RequireAuth>

  it('waits while the session loads (no flash of the page)', () => {
    useAuthStore.setState({ isLoading: true })
    renderAt('/secret', guarded)
    expect(screen.queryByText('secret page')).toBeNull()
    expect(screen.queryByText('login page')).toBeNull()
  })

  it('sends a logged-out user to /login', () => {
    renderAt('/secret', guarded)
    expect(screen.getByText('login page')).toBeTruthy()
  })

  it('shows the page when logged in', () => {
    useAuthStore.setState({ user: { role: 'viewer' }, isAuthenticated: true })
    renderAt('/secret', guarded)
    expect(screen.getByText('secret page')).toBeTruthy()
  })
})

describe('navItemVisible (the side-menu rule)', () => {
  const item = { to: '/x', roles: ['admin', 'pharmacist'] }

  it('roles: null is everyone', () => {
    expect(navItemVisible({ to: '/x', roles: null }, { role: 'viewer' })).toBe(true)
  })
  it('a role list hides from the other roles', () => {
    expect(navItemVisible(item, { role: 'pharmacist' })).toBe(true)
    expect(navItemVisible(item, { role: 'viewer' })).toBe(false)
  })
  it('no role is viewer', () => {
    expect(navItemVisible({ to: '/x', roles: ['viewer'] }, {})).toBe(true)
  })
  it('a per-user capability shows an item the role does not', () => {
    const capItem = { to: '/usage-print', roles: [], cap: 'can_usage_print' }
    expect(navItemVisible(capItem, { role: 'pharmacist', user: {} })).toBe(false)
    expect(navItemVisible(capItem, { role: 'pharmacist', user: { can_usage_print: true } })).toBe(true)
  })
  it('a module item hides once the matrix takes its view away (admin excepted)', () => {
    const modItem = { to: '/tasks', roles: ['admin', 'pharmacist'], module: 'tasks' }
    expect(navItemVisible(modItem, { role: 'pharmacist', perms: null })).toBe(true)
    expect(navItemVisible(modItem, { role: 'pharmacist', perms: { tasks: { view: false } } })).toBe(false)
    expect(navItemVisible(modItem, { role: 'pharmacist', perms: { tasks: { view: true } } })).toBe(true)
    expect(navItemVisible(modItem, { role: 'admin', perms: {} })).toBe(true)
  })
  it('the UAT D5 screens carry the matrix module their API checks', () => {
    const byPath = Object.fromEntries(NAV_GROUPS.flatMap(g => g.items).map(n => [n.to, n]))
    expect(byPath['/pos/exceptions'].module).toBe('pos')
    expect(byPath['/missed-sales'].module).toBe('reservations')
    expect(byPath['/phantom-sales'].module).toBe('analytics')
    expect(byPath['/cash-optimization'].module).toBe('analytics')
    expect(byPath['/phone-alerts'].module).toBe('alerts')
    // «التنبيهات والإعلانات» (owner 2026-11-17): the matrix alone decides — supervisor by default
    expect(navItemVisible(byPath['/phone-alerts'], { role: 'supervisor', perms: { alerts: { view: true } } })).toBe(true)
    expect(navItemVisible(byPath['/phone-alerts'], { role: 'supervisor', perms: { alerts: {} } })).toBe(false)
    expect(navItemVisible(byPath['/phone-alerts'], { role: 'pharmacist', perms: { alerts: { view: true } } })).toBe(true)
    const perms = { pos: { view: true } }
    expect(navItemVisible(byPath['/pos/exceptions'], { role: 'supervisor', perms })).toBe(true)
  })
  it('every menu item has a path and a known shape', () => {
    const items = NAV_GROUPS.flatMap(g => g.items)
    expect(items.length).toBeGreaterThan(20)
    for (const n of items) {
      expect(n.to).toMatch(/^\//)
      expect(n.roles === null || Array.isArray(n.roles)).toBe(true)
    }
  })
})
