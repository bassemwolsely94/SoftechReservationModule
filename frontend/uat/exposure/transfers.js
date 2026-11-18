// Transfers are visible to the requesting OR the supplying side (owner decision 3). The reference
// transfers name only the requesting branch, so the supplying side is read once as admin.
import { request } from '@playwright/test'
import { userByKey, PASSWORD } from '../lib/users.js'
import { reference } from '../lib/expected.js'
import { seesBranchValue } from './rules.js'

let sidesCache = null

/** -> Map(id -> {number, branch: 'A'|'B', sides: [requestingValue, supplyingValue]}) */
export async function transferSides(baseURL) {
  if (sidesCache) return sidesCache
  const out = new Map()
  // signs in through the login API: the saved admin session expires after 1 h (run 3 read every
  // transfer as 401, learnt no sides and flagged a legitimately visible transfer)
  const ctx = await request.newContext({ baseURL })
  try {
    const login = await ctx.post('/api/auth/login/', { headers: { 'X-Requested-With': 'XMLHttpRequest' },
      data: { username: userByKey('admin').username, password: PASSWORD } })
    if (!login.ok()) throw new Error(`transferSides: admin login ${login.status()}; cannot tell which transfers are visible`)
    for (const b of ['A', 'B']) {
      for (const t of reference(b).transfers || []) {
        const res = await ctx.get(`/api/transfers/${t.id}/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        let sides = [null, null]
        if (!res.ok()) throw new Error(`transferSides: transfer #${t.id} answered ${res.status()} to admin`)
        {
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
