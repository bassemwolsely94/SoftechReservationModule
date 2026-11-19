// node --test frontend/uat/lib/page.test.mjs — the shared screen-status rule (W2 lessons).
import test from 'node:test'
import assert from 'node:assert/strict'
import { classify } from './page.js'

const base = { url: '/finance', finalUrl: '/finance', text: 'x'.repeat(500), ms: 800, timedOut: false,
               consoleErrors: [], apiErrors: [], slowMs: 5_000 }
const st = o => classify({ ...base, ...o })

test('a data screen showing the figure 403 is not a refusal', () => {
  assert.equal(st({ text: 'إجمالي 403 جنيه ' + 'x'.repeat(300) }), 'ok')
})

test('a bare 403 on a near-empty screen is a refusal', () => {
  assert.equal(st({ text: 'Error 403' }), 'refused')
  assert.equal(st({ text: 'short', apiErrors: [{ url: '/api/x/', status: 403 }] }), 'refused')
})

test('refusal wording is a refusal whatever the length', () => {
  assert.equal(st({ text: 'ليس لديك صلاحية ' + 'x'.repeat(300) }), 'refused')
})

test('a screen redirecting to its own dashboard is not refused; the main dashboard is', () => {
  assert.equal(st({ finalUrl: '/finance/dashboard' }), 'ok')
  assert.equal(st({ finalUrl: '/dashboard' }), 'refused')
  assert.equal(st({ finalUrl: '/m/me' }), 'refused')
})

test('crash, slow, blank', () => {
  assert.equal(st({ consoleErrors: ['pageerror: boom'] }), 'crash')
  assert.equal(st({ apiErrors: [{ url: '/api/x/', status: 500 }] }), 'crash')
  assert.equal(st({ apiErrors: [{ url: '/api/x/', status: 503 }] }), 'ok')
  assert.equal(st({ timedOut: true }), 'slow')
  assert.equal(st({ ms: 6_000 }), 'slow')
  assert.equal(st({ text: 'hi' }), 'blank')
})
