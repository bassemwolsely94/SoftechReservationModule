// node --test frontend/uat/lib/findings.test.mjs — the privacy check of the findings writer.
import test from 'node:test'
import assert from 'node:assert/strict'
import { looksLikePhone, asciiDigits } from './findings.js'

test('plain, formatted and international numbers are caught', () => {
  for (const s of ['01012345678', '010 1234 5678', '+20-10-1234-5678', '(010) 1234.5678']) {
    assert.equal(looksLikePhone(`call ${s} now`), true, s)
  }
})

test('Arabic-Indic digits are caught', () => {
  assert.equal(asciiDigits('٠١٠'), '010')
  assert.equal(looksLikePhone('رقم ٠١٠١٢٣٤٥٦٧٨'), true)
})

test('last-3, dates, money and ids are allowed', () => {
  for (const s of ['…678', '2026-11-17', '1,234.50 EGP', 'reservation 71', 'JV-2026-000004']) {
    assert.equal(looksLikePhone(s), false, s)
  }
})
