import { describe, expect, it } from 'vitest'
import { NAV_GROUPS, navItemVisible } from './navGroups'

const item = (to) => NAV_GROUPS.flatMap(g => g.items).find(i => i.to === to)
const view = (...mods) => Object.fromEntries(mods.map(m => [m, { view: true }]))

describe('menu follows the role matrix (role review)', () => {
  it('/vision-corpus: the catalog_tools grant opens it, catalog alone does not', () => {
    const it_ = item('/vision-corpus')
    expect(it_.roles).toBeNull()
    expect(it_.module).toBe('catalog_tools')
    expect(navItemVisible(it_, { role: 'call_center', perms: view('catalog_tools') })).toBe(true)
    expect(navItemVisible(it_, { role: 'call_center', perms: view('catalog') })).toBe(false)
  })

  it('/shortage: a viewer with shortage.view sees it', () => {
    expect(navItemVisible(item('/shortage'), { role: 'viewer', perms: view('shortage') })).toBe(true)
  })

  it('/settings: purchasing without a settings grant does not see it', () => {
    expect(navItemVisible(item('/settings'), { role: 'purchasing', perms: view('purchasing') })).toBe(false)
    expect(navItemVisible(item('/settings'), { role: 'pharmacist', perms: view('settings') })).toBe(true)
  })

  it('/delivery/dispatch: a salesperson with dispatch.view sees it', () => {
    expect(navItemVisible(item('/delivery/dispatch'), { role: 'salesperson', perms: view('dispatch') })).toBe(true)
    expect(navItemVisible(item('/delivery/dispatch'), { role: 'salesperson', perms: view('delivery') })).toBe(false)
  })

  it('/customers/merge asks for customers.edit, not view', () => {
    const m = item('/customers/merge')
    expect(navItemVisible(m, { role: 'call_center', perms: view('customers') })).toBe(false)
    expect(navItemVisible(m, { role: 'call_center', perms: { customers: { view: true, edit: true } } })).toBe(true)
  })

  it('the coupons entry needs vouchers view plus export or edit', () => {
    const c = item('/vouchers?tab=coupons')
    expect(navItemVisible(c, { role: 'viewer', perms: view('vouchers') })).toBe(false)
    expect(navItemVisible(c, { role: 'viewer', perms: { vouchers: { view: true, export: true } } })).toBe(true)
  })

  it('/loyalty/branch no longer lists the bogus role "branch"', () => {
    expect(item('/loyalty/branch').roles).toBeNull()
  })

  it('admin sees a module item without the grant; unloaded perms do not hide it', () => {
    expect(navItemVisible(item('/code-maps'), { role: 'admin', perms: {} })).toBe(true)
    expect(navItemVisible(item('/code-maps'), { role: 'viewer', perms: null })).toBe(true)
  })

  it('capability-switch items keep their cap rule', () => {
    expect(navItemVisible(item('/usage-print'), { role: 'viewer', user: { role: 'viewer', can_usage_print: true } })).toBe(true)
    expect(navItemVisible(item('/usage-print'), { role: 'viewer', user: { role: 'viewer' } })).toBe(false)
  })
})
