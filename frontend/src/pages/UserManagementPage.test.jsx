import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

const ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'delivery',
  'viewer', 'supervisor', 'quality_manager', 'accountant']

vi.mock('../api/client', () => ({
  authApi: { roles: vi.fn(() => Promise.resolve({ data: { roles: ROLES.map((value) => (
    { value, label_ar: `ar-${value}`, label_en: value, description: '' })) } })) },
  usersApi: {
    erpUsers: vi.fn(() => Promise.resolve({ data: { results: [] } })),
    create: vi.fn(), update: vi.fn(),
  },
  branchesApi: { list: vi.fn(() => Promise.resolve({ data: [] })) },
}))

const { UserDrawer } = await import('./UserManagementPage')

describe('UserDrawer role dropdown', () => {
  afterEach(cleanup)

  it('offers every registry role, including supervisor and quality_manager', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <UserDrawer user={null} branches={[]} onClose={() => {}} onSaved={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(container.querySelector('option[value="quality_manager"]')).toBeTruthy())
    for (const r of ROLES) expect(container.querySelector(`option[value="${r}"]`), r).toBeTruthy()
    expect(container.querySelector('option[value="supervisor"]').textContent).toBe('ar-supervisor')
  })
})
