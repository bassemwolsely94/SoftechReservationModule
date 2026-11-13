import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ROLE_LABELS } from './roleLabels'

// The role keys the backend accepts (apps/users/models.py ROLE_CHOICES). vitest runs in frontend/.
function backendRoleKeys() {
  const src = readFileSync(resolve(process.cwd(), '../apps/users/models.py'), 'utf8')
  const block = src.split('ROLE_CHOICES = [')[1].split(']')[0]
  return [...block.matchAll(/\(\s*'([a-z_]+)'/g)].map(m => m[1])
}

describe('ROLE_LABELS', () => {
  it('labels every backend role, so the user screen can assign it', () => {
    const keys = backendRoleKeys()
    expect(keys).toContain('supervisor')
    expect(keys).toContain('quality_manager')
    for (const key of keys) expect(ROLE_LABELS[key], key).toBeTruthy()
  })
})
