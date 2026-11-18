import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'

vi.mock('../api/client', () => ({
  stockCountApi: { list: vi.fn(() => Promise.resolve({ data: [] })) },
  usersApi: { myPermissions: vi.fn(() => new Promise(() => {})) },
}))

const { SessionsTab } = await import('./StockCountPage')
const { default: usePermissionStore } = await import('../store/permissionStore')

// UAT W5a: «+ جلسة جديدة» was gated on admin:create, so a pharmacist holding stockcount:create
// (which is what POST /api/stockcount/sessions/ checks) could not open a session from the screen.
describe('SessionsTab new-session button', () => {
  afterEach(() => { cleanup(); usePermissionStore.getState().reset() })

  async function renderWith(permissions) {
    usePermissionStore.setState({ permissions, role: 'pharmacist' })
    render(<SessionsTab onSelect={() => {}} refresh={0} />)
    await waitFor(() => expect(screen.queryByText('جاري التحميل...')).toBeNull())
  }

  it('shows for stockcount create without admin', async () => {
    await renderWith({ stockcount: { view: true, create: true } })
    expect(screen.getByText('+ جلسة جديدة')).toBeTruthy()
  })

  it('stays hidden without stockcount create, even with admin create', async () => {
    await renderWith({ stockcount: { view: true }, admin: { create: true } })
    expect(screen.queryByText('+ جلسة جديدة')).toBeNull()
  })
})
