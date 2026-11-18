/**
 * Guard against TanStack Query v4 call shapes that v5 silently misreads (full audit FE-4 / FE-5).
 *
 *  • qc.invalidateQueries(['key']) — v5 reads the array as a filters object with no queryKey, so it
 *    matches EVERY query: every save re-fetched every active query on the page (bell, freshness bar,
 *    lists). Write qc.invalidateQueries({ queryKey: ['key'] }).
 *  • keepPreviousData: true — ignored by v5, so tables blank out on every filter/page change.
 *    Write placeholderData: keepPreviousData (imported from @tanstack/react-query).
 */
import { describe, expect, it } from 'vitest'

const sources = import.meta.glob(['../**/*.{js,jsx}', '!../**/*.test.{js,jsx}'],
  { query: '?raw', import: 'default', eager: true })

function offenders(re) {
  const hits = []
  for (const [file, text] of Object.entries(sources)) {
    text.split('\n').forEach((line, i) => { if (re.test(line)) hits.push(`${file}:${i + 1}`) })
  }
  return hits
}

describe('TanStack Query v5 call shapes', () => {
  it('scans the source tree', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(100)
  })

  it('never passes a bare array to the query-client filter methods', () => {
    expect(offenders(/\b(invalidateQueries|refetchQueries|removeQueries|cancelQueries|resetQueries)\(\s*\[/)).toEqual([])
  })

  it('never uses the v4 keepPreviousData: true option', () => {
    expect(offenders(/\bkeepPreviousData\s*:\s*true\b/)).toEqual([])
  })
})
