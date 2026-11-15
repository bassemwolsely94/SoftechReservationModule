import { describe, it, expect } from 'vitest'
import { escapeHtml, escapeDeep } from './escapeHtml'

describe('escapeHtml', () => {
  it('neutralises markup', () => {
    expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;')
  })
  it('keeps Arabic text, numbers and empty values', () => {
    expect(escapeHtml('باراسيتامول 500')).toBe('باراسيتامول 500')
    expect(escapeHtml(12)).toBe('12')
    expect(escapeHtml(null)).toBe('')
  })
})

describe('escapeDeep', () => {
  it('escapes strings at every depth and leaves other values alone', () => {
    const out = escapeDeep({ name: '<b>x</b>', qty: 2, ok: true, none: null,
                             items: [{ name: 'a&b' }], nested: { note: "it's" } })
    expect(out).toEqual({ name: '&lt;b&gt;x&lt;/b&gt;', qty: 2, ok: true, none: null,
                          items: [{ name: 'a&amp;b' }], nested: { note: 'it&#39;s' } })
  })
  it('does not mutate the input', () => {
    const src = { name: '<x>' }
    escapeDeep(src)
    expect(src.name).toBe('<x>')
  })
})
