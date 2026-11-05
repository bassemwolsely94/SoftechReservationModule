// "Hidden means forbidden": for every side-menu item a role does NOT see, the API behind that
// screen must answer 403 for that role. The menu only hides; the server is the guard.
//
// Cases where the code disagrees are NOT decided here: they are listed in KNOWN_GAPS with the
// question for the owner (test plan §3 rule 5), shown as annotations, and the spec stays green
// only for exactly those. Any NEW hidden-but-allowed pair fails the run. Visible-but-403 pairs
// (the menu shows a screen the server refuses) are reported as annotations too.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { ROLES, stateFile } from './users.js'
import { NAV_API } from './navApi.js'
import { NAV_GROUPS, navItemVisible } from '../src/components/navGroups.js'
import { KNOWN_GAPS } from './knownGaps.js'

const ITEMS = NAV_GROUPS.flatMap(g => g.items)

for (const role of ROLES) {
  test.describe(`menu vs API: ${role}`, () => {
    test.use({ storageState: stateFile(role) })

    test(`every menu item hidden from ${role} is refused by the API`, async ({ page }, info) => {
      const me = await (await page.request.get('/api/auth/me/')).json()
      const permsRes = await page.request.get('/api/users/my-permissions/')
      const perms = permsRes.ok() ? (await permsRes.json()).permissions : null

      const rows = []
      for (const item of ITEMS) {
        const api = NAV_API[item.to]
        if (!api) continue
        const visible = navItemVisible(item, { role, user: me, perms })
        const res = await page.request.get(api)
        rows.push({ role, to: item.to, api, visible, status: res.status() })
      }

      // 403/401 = refused (correct). 2xx = the API serves a screen the menu hides (a gap).
      // 404/400/503 = inconclusive: the feature is switched off or the screen needs data first.
      const unexpected = []
      for (const r of rows) {
        const gap = KNOWN_GAPS[`${role} ${r.to}`]
        if (r.status >= 500 && r.status !== 503) {
          unexpected.push(`${r.api} crashed for ${role} (${r.status})`)
        } else if (!r.visible && r.status >= 200 && r.status < 300) {
          if (gap) info.annotations.push({ type: 'owner question', description: `${r.to} hidden from ${role} but ${r.api} → ${r.status}: ${gap}` })
          else unexpected.push(`${r.to} is hidden from ${role} but ${r.api} answered ${r.status}`)
        } else if (!r.visible && ![401, 403].includes(r.status)) {
          info.annotations.push({ type: 'inconclusive', description: `${r.to} hidden from ${role}: ${r.api} → ${r.status}` })
        } else if (r.visible && r.status === 403) {
          info.annotations.push({ type: 'visible but refused', description: `${r.to} shown to ${role} but ${r.api} → 403` })
        }
        if (gap && !(!r.visible && r.status >= 200 && r.status < 300)) {
          unexpected.push(`KNOWN_GAPS entry '${role} ${r.to}' no longer applies (${r.api} → ${r.status}, visible=${r.visible}): remove it`)
        }
      }
      const out = path.resolve(info.project.outputDir, `menu-api-${role}.json`)
      fs.mkdirSync(path.dirname(out), { recursive: true })
      fs.writeFileSync(out, JSON.stringify(rows, null, 1))

      expect(unexpected, unexpected.join('\n')).toEqual([])
    })
  })
}
