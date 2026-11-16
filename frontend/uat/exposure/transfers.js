// Transfers are visible to the requesting OR the supplying side (owner decision 3). The reference
// transfers name only the requesting branch, so the supplying side is read once as admin.
import { request } from '@playwright/test'
import { stateFile } from '../lib/users.js'
import { reference } from '../lib/expected.js'
import { seesBranchValue } from './rules.js'

let sidesCache = null

/** -> Map(id -> {number, branch: 'A'|'B', sides: [requestingValue, supplyingValue]}) */
export async function transferSides(baseURL) {
  if (sidesCache) return sidesCache
  const out = new Map()
  const ctx = await request.newContext({ baseURL, storageState: stateFile('admin') })
  try {
    for (const b of ['A', 'B']) {
      for (const t of reference(b).transfers || []) {
        const res = await ctx.get(`/api/transfers/${t.id}/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        let sides = [null, null]
        if (res.ok()) {
          const j = await res.json()
          sides = [j.requesting_branch ?? j.requesting_branch_id, j.supplying_branch ?? j.supplying_branch_id]
        }
        out.set(t.id, { number: t.number, branch: b, sides })
      }
    }
  } finally {
    await ctx.dispose()
  }
  sidesCache = out
  return out
}

/** Ids and numbers of reference transfers this user may legitimately see (either side is theirs). */
export async function transferSkips(baseURL, key) {
  const skip = new Set()
  for (const [id, t] of await transferSides(baseURL)) {
    if (t.sides.some(s => s != null && seesBranchValue(key, s) === true)) {
      skip.add(String(id)); if (t.number) skip.add(t.number)
    }
  }
  return skip
}
