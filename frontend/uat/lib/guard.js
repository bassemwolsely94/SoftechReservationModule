// Safety gates. assertUatCopy: the server answering is the restored UAT copy (config.settings_uat
// stamps every response with X-UAT-Copy: elrezeiky_uat…) — checked before ANY login, so a reused
// Vite proxying to the office writer on :8000, or any other server, stops the run.
// assertReaderCopy: every write-capable test calls it first — the copy with every SOFTECH / tax
// writer off (owner approval for POS push + pricing approval is for the copy only, design §7.1).
import { request } from '@playwright/test'
import { stateFile } from './users.js'

export async function assertUatCopy(baseURL) {
  const ctx = await request.newContext({ baseURL })
  try {
    const res = await ctx.get('/api/auth/me/')
    const db = res.headers()['x-uat-copy'] || ''
    if (!db.startsWith('elrezeiky_uat')) {
      throw new Error(`NOT the UAT copy: ${baseURL} answered without X-UAT-Copy (got ${JSON.stringify(db)}) — stop`)
    }
    return db
  } finally {
    await ctx.dispose()
  }
}

export async function assertReaderCopy(baseURL) {
  await assertUatCopy(baseURL)
  const ctx = await request.newContext({ baseURL, storageState: stateFile('admin') })
  try {
    const res = await ctx.get('/api/sync/writer-switches/')
    if (res.status() !== 200) throw new Error(`writer-switches answered ${res.status()}`)
    const s = await res.json()
    const on = (s.flags || []).filter(f => f.value || f.effective).map(f => f.flag)
    if (s.writer_instance || !s.softech_read_only || on.length) {
      throw new Error(`NOT a reader copy: writer_instance=${s.writer_instance} read_only=${s.softech_read_only} on=${on.join(',')}`)
    }
    return s
  } finally {
    await ctx.dispose()
  }
}
