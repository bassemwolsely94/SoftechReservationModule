// Open a screen and wait until it has settled, on production-sized data.
//
// Time-to-content, not time-to-idle (W2 lessons, ported 2026-11-19): waiting for networkidle never
// ends on polling screens (bell, freshness, queue status) — 125 min for one user. A visit waits for
// the FIRST of: content (main or an h1 with text, no spinner, no loading text) or a refusal
// (refusal text, URL left the route). Then SETTLE_MS collects late API errors, and a section still
// saying "loading" gets up to capMs to clear (dataMs = when it did).
export const SPINNERS = '[aria-busy="true"], .animate-spin, [data-loading="true"]'
export const REFUSED_TEXT = /غير مصرح|ليس لديك صلاحية|لا تملك صلاحية/
// A bare "403"/"Forbidden" is a refusal only on a near-empty screen: on a data screen it is a
// figure or a code (W2 run 4b: admin "refused" on /finance with data 200).
export const REFUSED_CODE = /(^|[^0-9])403([^0-9]|$)|Forbidden/
export const LOADING = /جار[ٍِ]?\s*التحميل|Loading\.\.\./
// Anchored: unanchored, /finance → /finance/dashboard (its own index) counted as a refusal.
export const LANDING = /^\/(dashboard|login|rider|m|m\/me)\/?$/
const SETTLE_MS = 1_500
const READ_MS = 5_000   // every text read is bounded; an unbounded one hung a whole sweep

/** Pure status rule, shared by every sweep (unit-tested in page.test.mjs). */
export function classify({ url, finalUrl, text, ms, timedOut, consoleErrors, apiErrors, slowMs }) {
  const crashed = consoleErrors.some(e => e.startsWith('pageerror')) || apiErrors.some(e => e.status >= 500 && e.status !== 503)
  if (crashed) return 'crash'
  const wanted = new URL(url, 'http://x').pathname
  if (REFUSED_TEXT.test(text) ||
      ((REFUSED_CODE.test(text) || apiErrors.some(e => e.status === 403)) && text.length < 200) ||
      (finalUrl !== wanted && LANDING.test(finalUrl))) return 'refused'
  if (timedOut) return 'slow'
  if (text.length < 20) return 'blank'
  return ms > slowMs ? 'slow' : 'ok'
}

/**
 * @returns {Promise<{ms: number, status: 'ok'|'refused'|'blank'|'crash'|'slow',
 *                    consoleErrors: string[], apiErrors: Array<{url: string, status: number}>, finalUrl: string,
 *                    blocker?: string, dataMs?: number}>}
 */
export async function gotoSettled(page, url, { capMs = 60_000, slowMs = 5_000 } = {}) {
  const consoleErrors = []
  const apiErrors = []
  const onConsole = m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)) }
  const onPageError = e => consoleErrors.push(`pageerror: ${String(e).slice(0, 300)}`)
  const onResponse = r => {
    if (r.url().includes('/api/') && r.status() >= 400) apiErrors.push({ url: r.url().replace(/^https?:\/\/[^/]+/, ''), status: r.status() })
  }
  const wanted = url.split('?')[0]
  page.on('console', onConsole); page.on('pageerror', onPageError); page.on('response', onResponse)
  const t0 = Date.now()
  let timedOut = false, ms, blocker, dataMs
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: capMs })
    await page.waitForFunction(({ wanted, spin, refused, loading }) => {
      const p = location.pathname.replace(/\/$/, '') || '/'
      if (p !== (wanted.replace(/\/$/, '') || '/')) return true                     // redirected
      const root = document.querySelector('main') || document.querySelector('#root')
      const text = root ? root.innerText : ''
      if (new RegExp(refused).test(text)) return true                              // refusal text
      // main / h1 only: an icon-only (collapsed) nav rail has no text and must not count as "rendered".
      const hasText = [document.querySelector('main'), ...document.querySelectorAll('h1')].some(e => e && e.innerText.trim().length > 0)
      return hasText && !document.querySelector(spin) && !new RegExp(loading).test(text)
    }, { wanted, spin: SPINNERS, refused: REFUSED_TEXT.source, loading: LOADING.source }, { timeout: capMs, polling: 200 })
      .catch(() => { timedOut = true })
    ms = Date.now() - t0
    if (timedOut) blocker = await page.evaluate(({ spin, loading }) => {
      const sp = document.querySelector(spin)
      const main = document.querySelector('main')
      return [sp ? `spinner ${sp.tagName.toLowerCase()} in ${sp.closest('main') ? 'main' : (sp.closest('header,nav,aside')?.tagName.toLowerCase() || 'page')}` : '',
        new RegExp(loading).test(main?.innerText || '') ? 'loading text in main' : '',
        main ? `main text ${main.innerText.trim().length}` : 'no <main>', `path ${location.pathname}`].filter(Boolean).join('; ')
    }, { spin: SPINNERS, loading: LOADING.source }).catch(() => 'page did not answer')
    await page.waitForTimeout(SETTLE_MS)
    // "Still loading" is judged after giving the section up to capMs, not 1.5 s after first content.
    if (!timedOut && LOADING.test(await page.locator('main').first().innerText({ timeout: READ_MS }).catch(() => ''))) {
      await page.waitForFunction(loading => !new RegExp(loading).test(document.querySelector('main')?.innerText || ''),
        LOADING.source, { timeout: capMs, polling: 250 }).catch(() => {})
      dataMs = Date.now() - t0
    }
  } finally {
    page.off('console', onConsole); page.off('pageerror', onPageError); page.off('response', onResponse)
  }
  if (ms === undefined) ms = Date.now() - t0
  const finalUrl = new URL(page.url()).pathname
  const text = (await page.locator('main, #root').first().innerText({ timeout: READ_MS }).catch(() => '')).trim()
  const status = classify({ url, finalUrl, text, ms, timedOut, consoleErrors, apiErrors, slowMs })
  return { ms, status, consoleErrors, apiErrors, finalUrl, blocker, dataMs }
}

/** Screenshot with a bound: an unbounded one waited out a whole sweep. undefined when it fails. */
export async function shot(page, file, { timeout = 15_000 } = {}) {
  try { await page.screenshot({ path: file, timeout }); return file } catch { return undefined }
}
