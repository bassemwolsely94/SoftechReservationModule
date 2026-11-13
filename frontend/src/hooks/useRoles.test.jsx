import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const ROLES = [
  { value: 'admin', label_ar: 'مدير النظام', label_en: 'Admin', description: '' },
  { value: 'supervisor', label_ar: 'مشرف', label_en: 'Supervisor', description: '' },
  { value: 'quality_manager', label_ar: 'مدير الجودة', label_en: 'Quality manager', description: '' },
  { value: 'accountant', label_ar: 'محاسب', label_en: 'Accountant', description: '' },
]

let resolveRoles
vi.mock('../api/client', () => ({
  authApi: { roles: vi.fn(() => new Promise((res) => { resolveRoles = () => res({ data: { roles: ROLES } }) })) },
}))

const { default: useRoles } = await import('./useRoles')

function Wrapper({ children }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }))
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

afterEach(cleanup)

describe('useRoles', () => {
  it('falls back to the key while loading, then labels from the registry', async () => {
    const { result } = renderHook(() => useRoles(), { wrapper: Wrapper })
    expect(result.current.roleLabel('admin')).toBe('admin')
    resolveRoles()
    await waitFor(() => expect(result.current.roles.length).toBe(4))
    expect(result.current.roleLabel('supervisor')).toBe('مشرف')
    expect(result.current.roleLabel('supervisor', 'en')).toBe('Supervisor')
    expect(result.current.roleLabel('zzz')).toBe('zzz')
    expect(result.current.roleLabelT('quality_manager', (ar, en) => en)).toBe('Quality manager')
  })
})
