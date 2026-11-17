// W4 guard: a scan against a dead backend finds nothing and "passes". The first full run (2026-11-17)
// lost the shared Django server on 8200 for ~20 min and 260 tests passed empty. Every W4 test now
// probes the backend before and after; a refused connection fails the test, so a quiet run means
// "scanned and clean", never "nothing answered".
import { test } from '@playwright/test'

const API = `http://127.0.0.1:${Number(process.env.UAT_API_PORT || 8200)}/api/auth/me/`

async function probe(request, when) {
  let status = 0
  try { status = (await request.get(API, { timeout: 10_000 })).status() } catch { status = 0 }
  if (status === 0 || status >= 500) throw new Error(`UAT backend not answering ${when} the test (status ${status || 'refused'}); this result does not count`)
}

export function guardBackend() {
  test.beforeEach(async ({ request }) => { await probe(request, 'before') })
  test.afterEach(async ({ request }) => { await probe(request, 'after') })
}
