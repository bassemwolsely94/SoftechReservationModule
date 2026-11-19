// UAT users, from the git-ignored file `seed_uat_users` writes. Never print PASSWORD.
import fs from 'node:fs'
import path from 'node:path'

const here = __dirname
const file = path.resolve(here, '..', '.uat-users.json')
if (!fs.existsSync(file)) throw new Error('uat/lib/users.js: run `manage.py seed_uat_users --settings=config.settings_uat` first')
const data = JSON.parse(fs.readFileSync(file, 'utf-8'))

/** @type {Array<{key: string, username: string, role: string, shape: string, branch: string}>} */
export const UAT_USERS = data.users
export const PASSWORD = data.password
export const BRANCH_A = data.branchA
export const BRANCH_B = data.branchB
export const userByKey = key => {
  const u = UAT_USERS.find(x => x.key === key)
  if (!u) throw new Error(`no UAT user '${key}'`)
  return u
}
export const usersWhere = pred => UAT_USERS.filter(pred)
// File-safe name for a key ('real:ali', 'pharmacist@B').
export const safeKey = key => key.replace(/[^a-zA-Z0-9_-]/g, '_')
export const stateFile = key => path.resolve(here, '..', '.auth', `${safeKey(key)}.json`)
