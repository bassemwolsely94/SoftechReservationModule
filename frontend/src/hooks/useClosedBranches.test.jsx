import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
  migrateLegacyTokens: vi.fn(),
  branchesApi: { listAll: vi.fn(() => Promise.resolve({ data: [] })) },
}))

const { default: useAuthStore } = await import('../store/authStore')
const { default: useClosedBranches } = await import('./useClosedBranches')

function Probe() {
  const { toggle } = useClosedBranches([])
  return <div data-testid="bar">{toggle}</div>
}

function renderProbe() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><Probe /></QueryClientProvider>)
}

beforeEach(() => useAuthStore.setState({ user: null, isAuthenticated: true, isLoading: false }))
afterEach(cleanup)

describe('useClosedBranches toggle', () => {
  it('shows «إظهار الفروع المغلقة» to an admin', () => {
    useAuthStore.setState({ user: { role: 'admin' } })
    renderProbe()
    expect(screen.queryByText('إظهار الفروع المغلقة')).not.toBeNull()
  })

  it('hides the toggle from non-admins (the server serves the full list to admins only)', () => {
    useAuthStore.setState({ user: { role: 'pharmacist' } })
    renderProbe()
    expect(screen.queryByText('إظهار الفروع المغلقة')).toBeNull()
  })
})
