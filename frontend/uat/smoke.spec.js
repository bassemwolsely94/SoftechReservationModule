// The UAT harness works end to end on the copy: reader guard, a settled screen, expectations load.
import { test, expect } from '@playwright/test'
import { stateFile, BRANCH_A } from './lib/users.js'
import { expectedFor, can, reference } from './lib/expected.js'
import { gotoSettled } from './lib/page.js'
import { assertReaderCopy } from './lib/guard.js'

test('the UAT server is a reader copy with every writer off', async ({ baseURL }) => {
  const s = await assertReaderCopy(baseURL)
  expect(s.writer_instance).toBe(false)
  expect(s.softech_read_only).toBe(true)
})

test.describe('pharmacist in branch A', () => {
  test.use({ storageState: stateFile('pharmacist') })

  test('dashboard settles and identity matches the expectations', async ({ page }) => {
    const r = await gotoSettled(page, '/dashboard')
    expect(['ok', 'slow']).toContain(r.status)
    const me = await (await page.request.get('/api/auth/me/')).json()
    expect(me.role).toBe('pharmacist')
    expect(expectedFor('pharmacist').branchIds).toContain(BRANCH_A.id)
    expect(can('pharmacist', 'reservations', 'view')).toBe(true)
    expect(reference('A').customers.length).toBeGreaterThan(0)
  })
})
