// node scripts/check-sort.mjs — self-check of the pure sort helpers (the repo has no frontend test runner).
import assert from 'node:assert/strict'
import {
  compareValues, toNumber, sortRows, nextSort, nextOrdering, parseOrdering, ariaSortOf,
} from '../src/hooks/sortCompare.js'

const col = (rows, sort) => sortRows(rows, sort, (r, k) => r[k]).map(r => r.v)
const R = (...vs) => vs.map((v, i) => ({ v, i }))

// numbers: display strings with commas / Arabic digits; empties last in both directions
assert.equal(toNumber('1,234.5'), 1234.5)
assert.equal(toNumber('٣٢'), 32)
assert.equal(toNumber('12%'), 12)
assert.equal(toNumber('—'), null)
assert.equal(toNumber('abc'), null)
assert.deepEqual(col(R(5, null, '1,000', '—', 20), { key: 'v', dir: 'desc', type: 'number' }), ['1,000', 20, 5, null, '—'])
assert.deepEqual(col(R(5, null, '1,000', '—', 20), { key: 'v', dir: 'asc', type: 'number' }), [5, 20, '1,000', null, '—'])

// text: Arabic-aware, natural numbers, empties last
assert.deepEqual(col(R('فرع 10', 'فرع 2', '', 'أحمد'), { key: 'v', dir: 'asc', type: 'text' }), ['أحمد', 'فرع 2', 'فرع 10', ''])
assert.deepEqual(col(R('b', 'a', null, 'c'), { key: 'v', dir: 'desc', type: 'text' }), ['c', 'b', 'a', null])

// dates: ISO strings and Date objects; unparsable = empty (last)
assert.deepEqual(col(R('2026-01-02', '2026-03-01', 'oops'), { key: 'v', dir: 'desc', type: 'date' }), ['2026-03-01', '2026-01-02', 'oops'])
assert.deepEqual(col(R('2026-01-02', '2026-03-01', 'oops'), { key: 'v', dir: 'asc', type: 'date' }), ['2026-01-02', '2026-03-01', 'oops'])

// stable: ties keep the original order, both directions
const ties = R(1, 1, 1)
assert.deepEqual(sortRows(ties, { key: 'v', dir: 'asc', type: 'number' }, (r, k) => r[k]).map(r => r.i), [0, 1, 2])
assert.deepEqual(sortRows(ties, { key: 'v', dir: 'desc', type: 'number' }, (r, k) => r[k]).map(r => r.i), [0, 1, 2])
assert.equal(compareValues(null, 3, 'number', 'desc'), 1)
assert.equal(compareValues(3, null, 'number', 'asc'), -1)
assert.equal(sortRows(ties, null, (r, k) => r[k]), ties)       // no sort = same array, original order

// client click cycle: text asc → desc → default; number desc → asc → default
let s = nextSort(null, 'n', 'text'); assert.deepEqual([s.dir, s.step], ['asc', 1])
s = nextSort(s, 'n', 'text'); assert.deepEqual([s.dir, s.step], ['desc', 2])
assert.equal(nextSort(s, 'n', 'text'), null)
s = nextSort(null, 'n', 'number'); assert.equal(s.dir, 'desc')
s = nextSort(s, 'n', 'number'); assert.equal(s.dir, 'asc')
assert.equal(nextSort(s, 'n', 'number'), null)
s = nextSort(nextSort(null, 'a', 'number'), 'b', 'text'); assert.deepEqual([s.key, s.dir, s.step], ['b', 'asc', 1])
// a default sort on the same key goes default → reversed → default
const def = { key: 'net', dir: 'desc', type: 'number' }
s = nextSort(null, 'net', 'number', def); assert.equal(s.dir, 'asc')
assert.equal(nextSort(s, 'net', 'number', def), null)

// server ordering strings
assert.deepEqual(parseOrdering('-net'), { key: 'net', dir: 'desc' })
assert.deepEqual(parseOrdering(''), { key: '', dir: 'asc' })
assert.equal(nextOrdering('', 'net', 'number'), '-net')
assert.equal(nextOrdering('-net', 'net', 'number'), 'net')
assert.equal(nextOrdering('net', 'net', 'number', '-net'), '-net')
assert.equal(nextOrdering('', 'name', 'text'), 'name')
assert.equal(nextOrdering('name', 'name', 'text'), '-name')
assert.equal(nextOrdering('-name', 'name', 'text', ''), '')
assert.equal(nextOrdering('-net', 'name', 'text'), 'name')
assert.equal(ariaSortOf(true, 'asc'), 'ascending')
assert.equal(ariaSortOf(false), 'none')

console.log('check-sort: all checks passed')
