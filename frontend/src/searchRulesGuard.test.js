// S4 — every local search filter uses the system's search rules (utils/wildcard.js: * and % wildcards,
// word order). A hand-rolled `.toLowerCase().includes(q)` bypasses them, so no file under src/ may
// add one. Not a search box (status/flag lists)? Add it to ALLOW with a reason, keyed by
// 'path::matched text'; a stale entry fails so the list cannot rot.
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

const SRC = join(process.cwd(), 'src')
const PATTERNS = [
  /\.toLowerCase\(\)\s*\.includes\(/g,
  /\.includes\(\s*(?:q|search|query|needle|term|ql|filter|s)\s*\)/g,
  /\.toLowerCase\(\)\s*\.indexOf\(/g,
  /\.indexOf\(\s*(?:q|search|query|s)\s*\)/g,
]

const ALLOW = {
  'pages/supply/AvailabilityInboxTab.jsx::.includes(filter)': 'flag list membership (state filter chips), not a search',
  'components/AnalyticsFilterPanel.jsx::.includes(s)': 'toggles a code in the selected-codes array, list membership, not a search',
  'components/ItemOperationalFiltersBar.jsx::.includes(s)': 'toggles a code in the selected-codes array, list membership, not a search',
  'pages/finance/gl/PeriodClosePage.jsx::.includes(s)': 'is this import status one of the selectable statuses, not a search',
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.jsx?$/.test(name) && !/\.test\./.test(name)) out.push(p)
  }
  return out
}

function scan(files) {
  const hits = {}   // key -> ['path:line', …]
  for (const p of files) {
    const rel = relative(SRC, p).split(sep).join('/')
    if (rel === 'utils/wildcard.js') continue
    readFileSync(p, 'utf8').split(/\r?\n/).forEach((line, i) => {
      for (const re of PATTERNS) {
        for (const m of line.matchAll(re)) {
          const k = `${rel}::${m[0].replace(/\s+/g, '')}`
          ;(hits[k] = hits[k] || []).push(`${rel}:${i + 1}`)
        }
      }
    })
  }
  return hits
}

describe('search rules guard', () => {
  it('the patterns catch the shapes they guard', () => {
    for (const src of ['a.name.toLowerCase().includes(q)', "x.toLowerCase() .includes('a')", 'list.includes(search)', 'ids.includes( term )',
    'v.includes(s)', "x.toLowerCase().indexOf('a')", 'hay.indexOf(q)', 'hay.indexOf( search )'])
      expect(PATTERNS.some(re => { re.lastIndex = 0; return re.test(src) }), src).toBe(true)
    for (const src of ['list.includes(x)', 'a.toLowerCase() === b', 'arr.indexOf(x)']) {
      expect(PATTERNS.some(re => { re.lastIndex = 0; return re.test(src) }), src).toBe(false)
    }
  })

  it('no local filter hand-rolls a contains match (use utils/wildcard.js wildcardMatch)', () => {
    const hits = scan(walk(SRC))
    const offenders = Object.entries(hits).filter(([k]) => !(k in ALLOW))
      .map(([k, v]) => `${v.join(', ')}  [${k}]`)
    expect(offenders, 'use wildcardMatch from utils/wildcard.js so the box follows the search rules').toEqual([])
  })

  it('ALLOW has no stale entries and every reason is written out', () => {
    const hits = scan(walk(SRC))
    expect(Object.keys(ALLOW).filter(k => !(k in hits))).toEqual([])
    expect(Object.entries(ALLOW).filter(([, why]) => (why || '').trim().length < 10)).toEqual([])
  })
})
