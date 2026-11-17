// One JSON line per finding; the report is built from these files.
// They live in frontend/uat-findings/ (git-ignored), OUTSIDE Playwright's outputDir, which every run
// empties. One file per run: UAT_RUN_ID, else today's date — so chunks of one sweep append together.
// Never put a full phone number in a finding: use last3() from expected.js.
import fs from 'node:fs'
import path from 'node:path'

const RUN_ID = (process.env.UAT_RUN_ID || new Date().toISOString().slice(0, 10)).replace(/[^\w.-]/g, '_')
// runs start in frontend/ (scripts/uat/README.md); UAT_FINDINGS_DIR overrides
export const FINDINGS_DIR = path.resolve(process.env.UAT_FINDINGS_DIR || path.join(process.cwd(), 'uat-findings'))
export const FINDINGS_FILE = path.join(FINDINGS_DIR, `${RUN_ID}.jsonl`)
const KINDS = new Set(['screen', 'button', 'phone', 'branch', 'workflow', 'crash', 'slow', 'decision'])
const SEVERITIES = new Set(['P0', 'P1', 'P2', 'P3'])

/** Arabic-Indic and Persian digits → ASCII, so ٠١٠… is seen as a number. */
export const asciiDigits = s => String(s).replace(/[٠-٩]/g, d => String(d.charCodeAt(0) - 0x660))
  .replace(/[۰-۹]/g, d => String(d.charCodeAt(0) - 0x6F0))

const MOBILE = /^(?:20|0)?1[0125]\d{8}$/          // Egyptian mobile, with or without 0 / +20
const LANDLINE = /^(?:0|20)[2-9]\d{8}$/            // landline with its area code: 0 + 9 digits (or 20 + 9)

/** True for any unbroken run of 8+ digits, and for a number written with spaces, dashes, dots,
 *  brackets or a + (010 1234 5678, +20-10-…) when its digits form an Egyptian mobile / landline.
 *  Dates (2026-11-17) and document numbers (JV-2026-000004) pass. */
export function looksLikePhone(text) {
  const t = asciiDigits(text)
  if (/\d{8,}/.test(t)) return true
  const runs = t.match(/\+?\(?\d[\d\s\-.()]*\d/g) || []
  return runs.some(r => {
    const d = r.replace(/\D/g, '')
    return MOBILE.test(d) || LANDLINE.test(d)
  })
}

/**
 * @param {{ws: string, key: string, route: string, kind: string, expected: string, actual: string,
 *          severity: 'P0'|'P1'|'P2'|'P3', evidence?: string}} f
 */
export function finding(f) {
  if (!KINDS.has(f.kind)) throw new Error(`finding: unknown kind ${f.kind}`)
  if (!SEVERITIES.has(f.severity)) throw new Error(`finding: unknown severity ${f.severity}`)
  for (const k of ['ws', 'key', 'route', 'expected', 'actual']) {
    if (typeof f[k] !== 'string') throw new Error(`finding: '${k}' must be a string`)
  }
  for (const [k, v] of Object.entries(f)) {
    if (typeof v === 'string' && looksLikePhone(v)) {
      throw new Error(`finding: '${k}' looks like a full phone number - use last3()`)
    }
  }
  fs.mkdirSync(FINDINGS_DIR, { recursive: true })
  fs.appendFileSync(FINDINGS_FILE, JSON.stringify({ at: new Date().toISOString(), ...f }) + '\n')
}
