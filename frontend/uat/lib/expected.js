// What each UAT user SHOULD see, from `export_uat_expectations` (the backend's own rules).
// The file holds real reference phones: git-ignored, never copied into reports.
import fs from 'node:fs'
import path from 'node:path'

const file = path.resolve(__dirname, '..', '.uat-expected.json')
if (!fs.existsSync(file)) throw new Error('uat/lib/expected.js: run `manage.py export_uat_expectations --settings=config.settings_uat` first')
const data = JSON.parse(fs.readFileSync(file, 'utf-8'))

/** -> {username, role, perms, branchIds, allBranches, seesPhones} */
export const expectedFor = key => {
  const e = data.users[key]
  if (!e) throw new Error(`no expectations for '${key}'`)
  return e
}
/** Same answer as usePermission(module, action) for that user. */
export const can = (key, module, action) => {
  const e = expectedFor(key)
  return e.role === 'admin' || !!e.perms?.[module]?.[action]
}
/** Sample real records of branch 'A' or 'B': {customers:[{id,pic,phone,name}], reservations, transfers, demand, posOrders, shortage, invoices} */
export const reference = branch => data.reference[branch]
/** Digits only, for phone matching across formats (spaces, dashes, +20). */
export const phoneDigits = p => String(p || '').replace(/\D/g, '').replace(/^20(?=1\d{9}$)/, '0')
/** For reports: never the full number. */
export const last3 = p => `…${phoneDigits(p).slice(-3)}`
