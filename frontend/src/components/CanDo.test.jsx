// CanDo marks what it lets through with data-perm="module:action" so the role UAT can check every
// visible permission-gated control against the backend's matrix. The wrapper must not add a box.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

vi.mock('../api/client', () => ({
  usersApi: { myPermissions: vi.fn() },
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
  migrateLegacyTokens: vi.fn(),
}))

const { default: usePermissionStore } = await import('../store/permissionStore')
const { default: CanDo } = await import('./CanDo')

beforeEach(() => usePermissionStore.setState({
  permissions: { demand: { create: true, delete: false } }, role: 'pharmacist', isLoading: false,
}))
afterEach(cleanup)

describe('CanDo', () => {
  it('wraps allowed children in a data-perm marker', () => {
    render(<CanDo module="demand" action="create"><button>new</button></CanDo>)
    const marker = screen.getByRole('button', { name: 'new' }).parentElement
    expect(marker.getAttribute('data-perm')).toBe('demand:create')
  })

  it('renders nothing (and no marker) when denied', () => {
    const { container } = render(<CanDo module="demand" action="delete"><button>del</button></CanDo>)
    expect(screen.queryByRole('button', { name: 'del' })).toBeNull()
    expect(container.querySelector('[data-perm]')).toBeNull()
    expect(container.innerHTML).toBe('')
  })

  it('renders the fallback unmarked when denied', () => {
    const { container } = render(
      <CanDo module="demand" action="delete" fallback={<span>no</span>}><button>del</button></CanDo>)
    expect(screen.getByText('no')).toBeTruthy()
    expect(container.querySelector('[data-perm]')).toBeNull()
  })

  it('the marker is layout-neutral (display: contents)', () => {
    const { container } = render(<CanDo module="demand" action="create"><button>new</button></CanDo>)
    expect(container.querySelector('[data-perm]').style.display).toBe('contents')
  })
})
