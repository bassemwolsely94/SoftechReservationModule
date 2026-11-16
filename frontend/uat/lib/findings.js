// One JSON line per finding in test-results-uat/findings.jsonl; the report is built from it.
// Never put a full phone number in a finding: use last3() from expected.js.
import fs from 'node:fs'
import path from 'node:path'

export const FINDINGS_FILE = path.resolve(__dirname, '..', '..', 'test-results-uat', 'findings.jsonl')
const KINDS = new Set(['screen', 'button', 'phone', 'branch', 'workflow', 'crash', 'slow', 'decision'])
const SEVERITIES = new Set(['P0', 'P1', 'P2', 'P3'])

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
  if (/\d{8,}/.test(`${f.expected} ${f.actual}`)) throw new Error('finding: looks like a full phone number - use last3()')
  fs.mkdirSync(path.dirname(FINDINGS_FILE), { recursive: true })
  fs.appendFileSync(FINDINGS_FILE, JSON.stringify({ at: new Date().toISOString(), ...f }) + '\n')
}
