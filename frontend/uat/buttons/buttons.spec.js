// W3: button visibility. Per UAT user × screen that renders for that user:
//   every [data-perm="module:action"] on screen must be allowed by the matrix  → else P1 `button`
//   every primary action the matrix allows must be on screen                   → else P3 `button`
// data-perm comes from <CanDo> and the usePermission() call sites (product change in this batch).
import fs from 'node:fs'
import path from 'node:path'
import { test } from '@playwright/test'
import { UAT_USERS, BRANCH_B, stateFile } from '../lib/users.js'
import { can, reference } from '../lib/expected.js'
import { finding } from '../lib/findings.js'
import { gotoSettled } from '../lib/page.js'
import { SCREENS, urlFor } from './primaryActions.js'

const OUT = path.resolve(__dirname, '..', '..', 'test-results-uat', 'buttons-matrix.json')
const RENDERED = new Set(['ok', 'slow'])
const refs = { A: reference('A'), B: reference('B') }
const matrix = {}

test.afterAll(() => {
  fs.mkdirSync(path.dirname(OUT), { recursive: true })
  const prev = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf-8')) : {}
  fs.writeFileSync(OUT, JSON.stringify({ ...prev, ...matrix }, null, 1))
})

for (const u of UAT_USERS) {
  test.describe(`${u.key} (${u.role})`, () => {
    test.use({ storageState: stateFile(u.key) })

    test('gated controls on screen match the matrix', async ({ page }) => {
      test.setTimeout(SCREENS.length * 75_000)
      const home = u.branch && BRANCH_B && String(u.branch) === String(BRANCH_B.code) ? 'B' : 'A'
      const row = matrix[u.key] = {}
      for (const screen of SCREENS) {
        const url = urlFor(screen, refs, home)
        if (!url) { row[screen.route] = { status: 'skipped', reason: 'no reference id' }; continue }
        const r = await gotoSettled(page, url)
        const cell = row[url] = { status: r.status, ms: r.ms, perms: [], denied: [], missing: [] }
        if (!RENDERED.has(r.status)) continue

        // 1. nothing gated is shown that the matrix denies
        const seen = await page.$$eval('[data-perm]', els => els.map(e => ({
          perm: e.getAttribute('data-perm'),
          hook: e.getAttribute('data-tour') || e.querySelector('[data-tour]')?.getAttribute('data-tour') || '',
          text: (e.innerText || '').trim().slice(0, 40),
        })))
        const byPerm = new Map()
        for (const s of seen) if (!byPerm.has(s.perm)) byPerm.set(s.perm, s)
        cell.perms = [...byPerm.keys()]
        for (const [perm, s] of byPerm) {
          const [module, action] = perm.split(':')
          if (!can(u.key, module, action)) {
            cell.denied.push(perm)
            finding({ ws: 'W3', key: u.key, route: url, kind: 'button', severity: 'P1',
              expected: `no control gated by ${perm} (matrix denies it to ${u.role})`,
              actual: `shown: ${s.hook || s.text || 'control'} [data-perm=${perm}]` })
          }
        }

        // 2. the primary actions the matrix allows are there
        for (const a of screen.actions) {
          const [module, action] = a.perm.split(':')
          if (!can(u.key, module, action)) continue
          if (await page.locator(a.sel).count() === 0) {
            cell.missing.push(a.perm)
            finding({ ws: 'W3', key: u.key, route: url, kind: 'button', severity: 'P3',
              expected: `primary action «${a.label}» (${a.perm} allowed to ${u.role})`,
              actual: `not on screen (${a.sel})` })
          }
        }
      }
    })
  })
}
