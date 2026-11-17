// S3 Task 5 — one item box everywhere: ItemSearchInput and MultiItemPicker are gone, and no
// file under src/ may import them again (ItemSearchWidget is the only item picker).
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(process.cwd(), 'src')
// `from '…/X'`, `from '…/X.jsx'`, `import('…/X')`, `require('…/X.js')`, `vi.mock('…/X')`
const LEGACY = /(?:\bfrom\s+|\bimport\(\s*|\brequire\(\s*|\bvi\.mock\(\s*)['"][^'"]*\/(?:ItemSearchInput|MultiItemPicker)(?:\.jsx?)?['"]/

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(jsx?|tsx?)$/.test(name)) out.push(p)
  }
  return out
}

describe('legacy item pickers', () => {
  it('the guard catches every way of pulling one in', () => {
    for (const src of [
      "import X from '../components/ItemSearchInput'",
      "import X from './MultiItemPicker.jsx'",
      'const X = require("../components/ItemSearchInput.js")',
      "vi.mock('../components/MultiItemPicker', () => ({}))",
      "const m = await import( '../components/ItemSearchInput' )",
    ]) expect(LEGACY.test(src), src).toBe(true)
    expect(LEGACY.test("import W from '../components/ItemSearchWidget'")).toBe(false)
  })

  it('the components are deleted', () => {
    const names = walk(SRC).map(p => relative(SRC, p).replace(/\\/g, '/'))
    expect(names).not.toContain('components/ItemSearchInput.jsx')
    expect(names).not.toContain('components/MultiItemPicker.jsx')
  })

  it('no file under src/ imports ItemSearchInput or MultiItemPicker', () => {
    const offenders = walk(SRC)
      .map(p => [p, relative(SRC, p).replace(/\\/g, '/')])
      .filter(([, rel]) => rel !== 'components/noLegacyItemPickers.test.js')   // its own samples
      .filter(([p]) => LEGACY.test(readFileSync(p, 'utf8')))
      .map(([, rel]) => rel)
    expect(offenders).toEqual([])
  })
})
