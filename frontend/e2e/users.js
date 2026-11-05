// The e2e users. The ONE place their usernames and test password are defined is
// config/settings_e2e.py (E2E_USERS / E2E_PASSWORD), which `seed_e2e_users` reads; this file
// reads the same values from it, so the two can never drift. Test-only credentials for the
// throwaway e2e database.
import fs from 'node:fs'
import path from 'node:path'

// Playwright loads specs as CommonJS here (package.json has no "type": "module"), so __dirname.
const here = __dirname
const src = fs.readFileSync(path.resolve(here, '../../config/settings_e2e.py'), 'utf-8')

const password = src.match(/^E2E_PASSWORD = '([^']+)'/m)?.[1]
const rolesBlock = src.match(/^E2E_ROLES = \[([\s\S]*?)\]/m)?.[1]
if (!password || !rolesBlock) throw new Error('e2e/users.js: cannot read E2E_PASSWORD / E2E_ROLES from config/settings_e2e.py')

export const ROLES = [...rolesBlock.matchAll(/'([a-z_]+)'/g)].map(m => m[1])
export const PASSWORD = password
export const usernameOf = role => `e2e_${role}`
export const stateFile = role => path.resolve(here, '.auth', `${role}.json`)
