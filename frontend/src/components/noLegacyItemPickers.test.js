// S3 Task 5 — one item box everywhere: ItemSearchInput and MultiItemPicker are gone, and no
// file under src/ may import them again (ItemSearchWidget is the only item picker).
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(process.cwd(), 'src')
const LEGACY = /\bfrom\s+['"][^'"]*\/(ItemSearchInput|MultiItemPicker)['"]|import\(\s*['"][^'"]*\/(ItemSearchInput|MultiItemPicker)['"]/

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(jsx?|tsx?)$/.test(name)) out.push(p)
  }
  return out
}

describe('legacy item pickers', () => {
  it('the components are deleted', () => {
    const names = walk(SRC).map(p => relative(SRC, p).replace(/\\/g, '/'))
    expect(names).not.toContain('components/ItemSearchInput.jsx')
    expect(names).not.toContain('components/MultiItemPicker.jsx')
  })

  it('no file under src/ imports ItemSearchInput or MultiItemPicker', () => {
    const offenders = walk(SRC)
      .filter(p => LEGACY.test(readFileSync(p, 'utf8')))
      .map(p => relative(SRC, p).replace(/\\/g, '/'))
    expect(offenders).toEqual([])
  })
})
