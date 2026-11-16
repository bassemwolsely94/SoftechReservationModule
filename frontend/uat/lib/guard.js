// The safety gate every write-capable UAT test calls first: the server must be a reader copy
// with every SOFTECH / tax writer off (owner approval for POS push + pricing approval is for the
// copy only - design §7.1). Reads the existing admin-only /api/sync/writer-switches/.
import { request } from '@playwright/test'
import { stateFile } from './users.js'

export async function assertReaderCopy(baseURL) {
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
