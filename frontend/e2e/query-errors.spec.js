// Full audit FE-7: a failed read must not look like "no data". The dispatch board used to show
// «لا توجد طلبات بانتظار سائق» while the delivery API answered 500.
import { test, expect } from '@playwright/test'
import { stateFile } from './users.js'

test.describe('failed reads say so', () => {
  test.use({ storageState: stateFile('admin') })

  test('the dispatch board shows an error, not "no orders", when the delivery API fails', async ({ page }) => {
    await page.route('**/api/delivery/**', route => route.fulfill({
      status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'خطأ تجريبي في السيرفر' }),
    }))
    await page.goto('/delivery/dispatch')

    // the two lists show their own error with a retry …
    await expect(page.getByTestId('query-state-error')).toHaveCount(2, { timeout: 20_000 })
    await expect(page.getByTestId('query-state-error').first()).toContainText('خطأ تجريبي في السيرفر')
    await expect(page.getByText('لا توجد طلبات بانتظار سائق')).toHaveCount(0)
    // … and the driver list (no own error state) is reported by the page strip
    await expect(page.getByTestId('query-error-strip')).toContainText('خطأ تجريبي في السيرفر')

    // once the server answers again, «إعادة المحاولة» brings the page back
    await page.unroute('**/api/delivery/**')
    await page.getByTestId('query-error-strip').getByText('إعادة المحاولة').click()
    await expect(page.getByTestId('query-error-strip')).toHaveCount(0, { timeout: 20_000 })
  })
})
