import { describe, expect, it } from 'vitest'
import { NAV_GROUPS, legacyRolesFor, moduleActionAllowed, navItemVisible } from './navGroups'

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

describe('unseeded fallback (role review C1): a module with no matrix rows uses the old role list', () => {
  const fu = () => item('/followups')

  it('module-only items carry their pre-review role list', () => {
    expect(fu().legacyRoles).toEqual(['admin','call_center','pharmacist','salesperson','supervisor','quality_manager'])
    expect(item('/code-maps').legacyRoles).toEqual(['admin'])
    expect(item('/rider').legacyRoles).toEqual(['admin','delivery','supervisor'])
  })

  it('unseeded: a legacy role on the old list sees it without any grant', () => {
    expect(navItemVisible(fu(), { role: 'pharmacist', perms: {}, seeded: [] })).toBe(true)
  })

  it('unseeded: a role off the old list does not, even with a grant', () => {
    expect(navItemVisible(fu(), { role: 'viewer', perms: view('followups'), seeded: [] })).toBe(false)
  })

  it('seeded: the matrix decides, the old list does not matter', () => {
    expect(navItemVisible(fu(), { role: 'pharmacist', perms: {}, seeded: ['followups'] })).toBe(false)
    expect(navItemVisible(fu(), { role: 'viewer', perms: view('followups'), seeded: ['followups'] })).toBe(true)
  })

  it('seeded list unknown (null): the matrix decides, as before', () => {
    expect(navItemVisible(fu(), { role: 'pharmacist', perms: {}, seeded: null })).toBe(false)
  })

  it('unseeded: a legacy capability still opens it (/supply can_supply_write)', () => {
    const s = item('/supply')
    expect(navItemVisible(s, { role: 'viewer', user: { can_supply_write: true }, perms: {}, seeded: [] })).toBe(true)
    expect(navItemVisible(s, { role: 'viewer', user: {}, perms: {}, seeded: [] })).toBe(false)
  })

  it('admin always sees it', () => {
    expect(navItemVisible(item('/code-maps'), { role: 'admin', perms: {}, seeded: [] })).toBe(true)
  })

  it('a mobile tab (roles-free, module only) follows the same rule', () => {
    const tab = { to: '/m/customers', module: 'customers', legacyRoles: ['admin', 'pharmacist'] }
    expect(navItemVisible(tab, { role: 'pharmacist', perms: {}, seeded: [] })).toBe(true)
    expect(navItemVisible(tab, { role: 'viewer', perms: {}, seeded: [] })).toBe(false)
    expect(navItemVisible(tab, { role: 'viewer', perms: view('customers'), seeded: ['customers'] })).toBe(true)
  })
})

describe('write controls on widened screens (final review I4): moduleActionAllowed', () => {
  const ctx = (role, perms, seeded = null) => ({ role, perms, seeded })

  it('a view-only role does not get the write controls (code maps: purchasing holds view)', () => {
    expect(moduleActionAllowed(ctx('purchasing', view('code_maps'), ['code_maps']), 'code_maps', 'edit', ['admin'])).toBe(false)
  })
  it('the edit grant opens them', () => {
    expect(moduleActionAllowed(ctx('purchasing', { code_maps: { view: true, edit: true } }, ['code_maps']),
      'code_maps', 'edit', ['admin'])).toBe(true)
  })
  it('any one of several actions (images: edit or approve)', () => {
    expect(moduleActionAllowed(ctx('pharmacist', { catalog_tools: { approve: true } }), 'catalog_tools', ['edit', 'approve'])).toBe(true)
    expect(moduleActionAllowed(ctx('call_center', view('catalog_tools')), 'catalog_tools', ['edit', 'approve'])).toBe(false)
  })
  it('dispatch board: quality (dispatch view, delivery view+export) cannot assign', () => {
    const perms = { dispatch: { view: true, export: true }, delivery: { view: true, export: true } }
    expect(moduleActionAllowed(ctx('quality_manager', perms, ['delivery']), 'delivery', 'assign',
      legacyRolesFor('/delivery/dispatch'))).toBe(false)
  })
  it('unseeded module: the old route roles keep the controls, others do not', () => {
    const legacy = legacyRolesFor('/catalog-intelligence')
    expect(legacy).toEqual(['admin', 'pharmacist', 'purchasing'])
    expect(moduleActionAllowed(ctx('pharmacist', {}, []), 'catalog', ['edit', 'approve'], legacy)).toBe(true)
    expect(moduleActionAllowed(ctx('call_center', {}, []), 'catalog', ['edit', 'approve'], legacy)).toBe(false)
  })
  it('admin yes; permissions not loaded no', () => {
    expect(moduleActionAllowed(ctx('admin', null), 'code_maps', 'edit', ['admin'])).toBe(true)
    expect(moduleActionAllowed(ctx('pharmacist', null), 'code_maps', 'edit', ['admin'])).toBe(false)
  })
  it('legacyRolesFor: unknown path has none', () => {
    expect(legacyRolesFor('/nope')).toBeUndefined()
    expect(legacyRolesFor('/tasks')).toBeUndefined()
  })
})
