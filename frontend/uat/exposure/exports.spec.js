// W4 — Excel exports carrying customer numbers, downloaded as each user and scanned cell by cell.
//   • reservations bulk export (POST /api/reservations/bulk/ action=export): record rule (D2/D3/D4) —
//     the file holds only reservations the user can see; numbers hidden for phone-hidden staff and viewers.
//   • PIC analytics background export: customer rule (B-2), "phones masked like the screen".
import { test } from '@playwright/test'
import { stateFile } from '../lib/users.js'
import { reference } from '../lib/expected.js'
import { gotoSettled } from '../lib/page.js'
import { EXPOSURE_USERS, sees, branchRule } from './rules.js'
import { checkPhones, branchLeak, decision, api, xlsxText } from './scan.js'

const XLSX = /spreadsheetml|octet-stream/

for (const key of EXPOSURE_USERS) {
  test.describe(`exposure exports as ${key}`, () => {
    test.use({ storageState: stateFile(key) })

    test(`${key} reservations Excel export`, async ({ page }) => {
      await gotoSettled(page, '/reservations/list')
      const route = 'POST /api/reservations/bulk/ export'
      // 1) other-branch reservations only: the file must hold no data row
      for (const b of ['A', 'B']) {
        if (sees(key, b)) continue
        const ids = reference(b).reservations || []
        if (!ids.length) continue
        const res = await api(page, 'POST', '/api/reservations/bulk/', { action: 'export', ids })
        if (res.status() !== 200 || !XLSX.test(res.headers()['content-type'] || '')) continue
        const { text, rows } = xlsxText(await res.body())
        const dataRows = Math.max(0, ...Object.values(rows)) - 1
        if (dataRows > 0) branchLeak(key, route, `absent (${branchRule(key, 'reservations', b).src})`,
          `export of ${ids.length} branch-${b} reservation ids returned ${dataRows} data rows`)
        checkPhones({ key, domain: 'reservations', route, files: [{ name: `branch-${b} ids`, text }] })
      }
      // 2) own + other ids together: numbers in the file follow the record rule
      const ids = [...(reference('A').reservations || []), ...(reference('B').reservations || [])].slice(0, 200)
      const res = await api(page, 'POST', '/api/reservations/bulk/', { action: 'export', ids })
      test.info().annotations.push({ type: 'export', description: `status ${res.status()}` })
      if (res.status() !== 200 || !XLSX.test(res.headers()['content-type'] || '')) return
      const { text } = xlsxText(await res.body())
      checkPhones({ key, domain: 'reservations', route, files: [{ name: 'reservations.xlsx', text }] })
    })

    test(`${key} PIC analytics export`, async ({ page }) => {
      test.setTimeout(300_000)
      await gotoSettled(page, '/dashboard')
      const access = await api(page, 'GET', '/api/pic-analytics/access/')
      if (!access.ok()) return
      const acc = await access.json().catch(() => ({}))
      if (acc.can_export === false || acc.can_view === false) return
      const route = 'PIC analytics export'
      let start = await api(page, 'POST', '/api/pic-analytics/export/jobs/')
      let job = await start.json().catch(() => ({}))
      if (start.status() === 409 && job.id) { /* an earlier job is still running: wait for it */ }
      else if (start.status() !== 202) {
        test.info().annotations.push({ type: 'export', description: `start ${start.status()}` })
        return
      }
      const deadline = Date.now() + 240_000
      let st = job
      while (Date.now() < deadline) {
        const r = await api(page, 'GET', `/api/pic-analytics/export/jobs/${job.id}/`)
        st = await r.json().catch(() => ({}))
        if (['done', 'failed'].includes(st.status) || st.error) break
        await page.waitForTimeout(5_000)
      }
      if (st.status !== 'done') {
        decision(key, route, 'PIC export finishes within 4 min on the copy (to scan it)', `job ended as ${st.status || 'unknown'} ${String(st.error || '').slice(0, 80)}`)
        return
      }
      const file = await api(page, 'GET', `/api/pic-analytics/export/jobs/${job.id}/download/`)
      if (file.status() !== 200) return
      const { text } = xlsxText(await file.body())
      checkPhones({ key, domain: 'picAnalytics', route, files: [{ name: 'pic-analytics.xlsx', text }] })
    })
  })
}
