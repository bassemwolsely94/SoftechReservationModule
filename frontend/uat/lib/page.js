// Open a screen and wait until it has settled, on production-sized data.
const SPINNERS = '[aria-busy="true"], .animate-spin, [data-loading="true"]'
const REFUSED_TEXT = /غير مصرح|ليس لديك صلاحية|لا تملك صلاحية|403|Forbidden/

/**
 * @returns {Promise<{ms: number, status: 'ok'|'refused'|'blank'|'crash'|'slow',
 *                    consoleErrors: string[], apiErrors: Array<{url: string, status: number}>, finalUrl: string}>}
 */
export async function gotoSettled(page, url, { capMs = 60_000, slowMs = 5_000 } = {}) {
  const consoleErrors = []
  const apiErrors = []
  const onConsole = m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)) }
  const onPageError = e => consoleErrors.push(`pageerror: ${String(e).slice(0, 300)}`)
  const onResponse = r => {
    if (r.url().includes('/api/') && r.status() >= 400) apiErrors.push({ url: r.url().replace(/^https?:\/\/[^/]+/, ''), status: r.status() })
  }
  page.on('console', onConsole); page.on('pageerror', onPageError); page.on('response', onResponse)
  const t0 = Date.now()
  let timedOut = false
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: capMs })
    await page.waitForLoadState('networkidle', { timeout: capMs }).catch(() => { timedOut = true })
    await page.waitForFunction(sel => !document.querySelector(sel), SPINNERS, { timeout: Math.max(1_000, capMs - (Date.now() - t0)) })
      .catch(() => { timedOut = true })
  } finally {
    page.off('console', onConsole); page.off('pageerror', onPageError); page.off('response', onResponse)
  }
  const ms = Date.now() - t0
  const finalUrl = new URL(page.url()).pathname
  const text = (await page.locator('main, #root').first().innerText().catch(() => '')).trim()
  const crashed = consoleErrors.some(e => e.startsWith('pageerror')) || apiErrors.some(e => e.status >= 500 && e.status !== 503)
  let status
  if (crashed) status = 'crash'
  else if (REFUSED_TEXT.test(text) || apiErrors.some(e => e.status === 403) && text.length < 200 ||
           (finalUrl !== new URL(url, 'http://x').pathname && /\/(dashboard|login|rider|m)$/.test(finalUrl))) status = 'refused'
  else if (timedOut) status = 'slow'
  else if (text.length < 20) status = 'blank'
  else status = ms > slowMs ? 'slow' : 'ok'
  return { ms, status, consoleErrors, apiErrors, finalUrl }
}
