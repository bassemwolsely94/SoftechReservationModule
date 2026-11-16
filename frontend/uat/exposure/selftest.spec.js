// W4 detector self-test: pure functions only (no browser, no findings written), so a quiet run
// means "nothing leaked", not "the detector never looks". Synthetic numbers only.
import { test, expect } from '@playwright/test'
import zlib from 'node:zlib'
import { normalise, needleOf, jsonHits, recordVisibility, xlsxText } from './scan.js'
import { phoneRule, branchRule, sees, BRANCH } from './rules.js'

test('number normalising and needles', () => {
  expect(needleOf('+20 100 123 4567')).toBe('1001234567')
  expect(needleOf('01001234567')).toBe('1001234567')
  expect(needleOf('0223456789')).toBe('0223456789'.slice(-10))
  expect(needleOf('12345')).toBeNull()
  expect(normalise('010-0123 4567')).toBe('01001234567')
  expect(normalise('٠١٠٠١٢٣٤٥٦٧')).toBe('01001234567')
  expect(normalise('•••••••567')).not.toContain('1001234567')
})

test('JSON hits carry their record branch; echoed search keys are ignored', () => {
  const body = { q: '01001234567', results: [{ id: 1, branch: BRANCH.A.id, customer: { phone: '0100 123 4567', preferred_branch: BRANCH.B.id } }] }
  const hits = jsonHits(body, '1001234567')
  expect(hits).toHaveLength(1)
  expect(hits[0].path).toBe('results[0].customer.phone')
  expect(recordVisibility('pharmacist@B', hits[0].ancestors)).toBe(false)
  expect(recordVisibility('pharmacist', hits[0].ancestors)).toBe(true)
})

test('rules follow B-2 / D2 / D3 / D4', () => {
  expect(sees('pharmacist@B', 'A')).toBe(false)
  expect(sees('multi', 'A') && sees('multi', 'B')).toBe(true)
  expect(sees('restricted', 'B')).toBe(false)
  expect(phoneRule('pharmacist@B', 'customers', 'A').rule).toBe('masked')          // B-2
  expect(phoneRule('pharmacist@B', 'customers', 'B').rule).toBe('full')
  expect(phoneRule('phoneHidden', 'customers', 'A').rule).toBe('masked')           // D3
  expect(phoneRule('pharmacist@B', 'reservations', 'A', true).rule).toBe('full')   // D2
  expect(phoneRule('pharmacist@B', 'reservations', 'A', false).rule).toBe('masked')
  expect(phoneRule('pharmacist@B', 'reservations', 'A', null).rule).toBe('decision')
  expect(phoneRule('viewer@B', 'reservations', 'B', true).rule).toBe('masked')     // D4
  expect(phoneRule('pharmacist@B', 'insurance', 'B').rule).toBe('decision')
  expect(branchRule('pharmacist@B', 'reservations', 'A').rule).toBe('absent')
  expect(branchRule('pharmacist@B', 'customer360', 'A').rule).toBe('full')         // CANARY GET-DETAIL
  expect(branchRule('pharmacist@B', 'transfers', 'A', ['A', 'B']).rule).toBe('full') // decision 3
})

test('xlsx reader sees every stored cell', () => {
  // a one-entry stored zip holding a shared-strings part
  const xml = Buffer.from('<sst><si><t>01001234567</t></si></sst>')
  const name = Buffer.from('xl/sharedStrings.xml')
  const data = zlib.deflateRawSync(xml)
  const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(8, 8)
  local.writeUInt32LE(data.length, 18); local.writeUInt32LE(xml.length, 22); local.writeUInt16LE(name.length, 26)
  const central = Buffer.alloc(46); central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(8, 10)
  central.writeUInt32LE(data.length, 20); central.writeUInt32LE(xml.length, 24); central.writeUInt16LE(name.length, 28)
  central.writeUInt32LE(0, 42)
  const cdStart = local.length + name.length + data.length
  const eocd = Buffer.alloc(22); eocd.writeUInt32LE(0x06054b50, 0); eocd.writeUInt16LE(1, 8); eocd.writeUInt16LE(1, 10)
  eocd.writeUInt32LE(central.length + name.length, 12); eocd.writeUInt32LE(cdStart, 16)
  const zip = Buffer.concat([local, name, data, central, name, eocd])
  expect(xlsxText(zip).text).toContain('01001234567')
})
