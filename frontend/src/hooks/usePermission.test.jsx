import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, renderHook } from '@testing-library/react'

vi.mock('../api/client', () => ({
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
  usersApi: { myPermissions: vi.fn(() => new Promise(() => {})) },
  migrateLegacyTokens: vi.fn(),
}))

const { default: usePermissionStore } = await import('../store/permissionStore')
const { usePermission, usePermissionAny } = await import('./usePermission')

// The matrix the gates read: a quality manager holds callcenter view + export only (seed default).
const QM = { callcenter: { view: true, export: true }, settings: {} }
const CALL_CENTER = { callcenter: { view: true, create: true, edit: true, export: true, assign: true } }

beforeEach(() => usePermissionStore.setState({ permissions: null, role: null, isLoading: false }))
afterEach(cleanup)

describe('usePermission (UAT D5 gates)', () => {
  it('is false while the matrix has not loaded (fail-closed)', () => {
    const { result } = renderHook(() => usePermission('callcenter', 'view'))
    expect(result.current).toBe(false)
  })
  it('reads one module action from the matrix', () => {
    usePermissionStore.setState({ permissions: QM })
    expect(renderHook(() => usePermission('callcenter', 'view')).result.current).toBe(true)
    expect(renderHook(() => usePermission('callcenter', 'edit')).result.current).toBe(false)
    expect(renderHook(() => usePermission('settings', 'create')).result.current).toBe(false)
  })
})

describe('usePermissionAny', () => {
  const CC_WRITE = ['create', 'edit', 'approve']

  it('a quality manager (callcenter view only) may not write cases', () => {
    usePermissionStore.setState({ permissions: QM })
    expect(renderHook(() => usePermissionAny('callcenter', CC_WRITE)).result.current).toBe(false)
  })
  it('any one of the actions is enough', () => {
    usePermissionStore.setState({ permissions: CALL_CENTER })
    expect(renderHook(() => usePermissionAny('callcenter', CC_WRITE)).result.current).toBe(true)
    usePermissionStore.setState({ permissions: { callcenter: { approve: true } } })
    expect(renderHook(() => usePermissionAny('callcenter', CC_WRITE)).result.current).toBe(true)
  })
  it('an unknown module or an unloaded matrix is false', () => {
    expect(renderHook(() => usePermissionAny('callcenter', CC_WRITE)).result.current).toBe(false)
    usePermissionStore.setState({ permissions: {} })
    expect(renderHook(() => usePermissionAny('purchasing', ['edit'])).result.current).toBe(false)
  })
})
