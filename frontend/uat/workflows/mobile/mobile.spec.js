// W8 mobile /m worked through per role (docs/uat/runs/w8-plan.md), on a phone-sized screen.
//
// Per user (the ten home roles in branch A, the branch-B twins, and the phone-visibility users):
//   tabs      — the bottom bar + «المزيد» sheet show exactly what the live matrix grants (P2 on drift);
//   creates   — reservation, demand, transfer request, shortage list + line, QA round: a role holding
//               the create grant does it through the phone form; a role without it is refused by the
//               server (P1 when allowed) and the form does not crash (P3 when it is offered anyway);
//   branch    — the branch picker shows only when /auth/me can_pick_any_branch; a picker creates for
//               the other branch, a non-picker is refused for it;
//   cancel    — the reservation cancel button and the server follow reservations:edit (role review
//               decision 6);
//   phones    — mobile customer search shows a full phone only per apps/customers/access.py
//               phones_visible; findings carry the last 3 digits only.
// The delivery role is sent from /m to /rider (rider.spec.js covers it).
import { test, expect } from '@playwright/test'
import { BRANCH_A, BRANCH_B, userByKey, UAT_USERS } from '../../lib/users.js'
import { expectedFor, reference, phoneDigits, last3 } from '../../lib/expected.js'
import { gotoSettled } from '../../lib/page.js'
import { finding } from '../../lib/findings.js'
import {
  WS, HOME, TWINS_B, asUser, live, allows, registry, requireRoleReviewCopy, flag, step, call, raw,
  mustRefuse, mustAllow, clickFor, field, tag, FAKE_PHONE, BASE, idOf, rows,
} from '../_w8.js'

test.use({ trace: 'off' })
test.describe.configure({ timeout: 15 * 60_000 })

const REG = registry()
const QA_WRITE = ['create', 'edit', 'approve', 'finalize', 'export']   // apps/qa/views.py _QA_WRITE
const branchOf = key => (userByKey(key).shape === 'twinB' ? BRANCH_B : BRANCH_A)
const otherOf = key => (branchOf(key).id === BRANCH_A.id ? BRANCH_B : BRANCH_A)
const canPick = l => l.role === 'admin' || !!l.me.can_pick_any_branch
const qaWorker = l => !!REG[l.role]?.qa_inspections && (l.role === 'admin' || allows(l, 'hr', QA_WRITE) === true)
// every mobile user except the delivery role (sent to /rider)
const MOBILE_USERS = [...HOME, ...TWINS_B].filter(k => userByKey(k).role !== 'delivery')

test.beforeAll(async () => { await requireRoleReviewCopy(BASE) })

// ── tabs ──────────────────────────────────────────────────────────────────────────────────────────
// MOBILE_TABS (frontend/src/App.jsx) → the server grant each one stands for. null = not judged.
const TAB_RULES = {
  '/m/me': () => true,
  '/m/pos': l => allows(l, 'pos', 'view'),
  '/m/reservations': l => allows(l, 'reservations', 'view'),
  '/m/transfers': l => allows(l, 'transfers', 'view'),
  '/m/demand': l => allows(l, 'demand', 'view'),
  '/m/shortage': l => allows(l, 'shortage', 'view'),
  '/m/delivery': l => allows(l, 'delivery', 'view'),
  '/m/approvals': l => allows(l, 'approvals', 'view'),
  '/m/items': () => true,
  '/m/customers': l => allows(l, 'customers', 'view'),
  '/m/vouchers': l => allows(l, 'vouchers', 'view'),
  '/m/tasks': l => allows(l, 'tasks', 'view'),
  '/m/daily-count': l => !!l.me.features?.daily_count,
  '/m/stock-count': l => allows(l, 'stockcount', 'view'),
  '/m/qa': l => qaWorker(l),
  '/m/attendance': () => true,
  '/m/my-incentives': () => true,
  '/m/gamification': () => true,
}

async function shownTabs(page) {
  const hrefs = new Set()
  const read = async sel => {
    for (const h of await page.locator(sel).evaluateAll(as => as.map(a => a.getAttribute('href')))) if (h) hrefs.add(h.replace(/\/$/, ''))
  }
  await page.locator('nav[data-tour="mshell-tabs"]').waitFor({ timeout: 30_000 })
  await read('nav[data-tour="mshell-tabs"] a[href]')
  const more = page.locator('[data-tour="mshell-more"]')
  if (await more.count()) {
    await more.click()
    await page.waitForTimeout(300)
    await read('div.fixed.inset-0 a[href^="/m/"]')
    await page.keyboard.press('Escape').catch(() => {})
    await page.mouse.click(5, 5).catch(() => {})
  }
  return hrefs
}

for (const key of MOBILE_USERS) {
  test(`tabs: ${key} sees the matrix's mobile tabs`, async ({ browser }) => {
    const { page, api, close } = await asUser(browser, key)
    try {
      const l = await live(api)
      const r = await gotoSettled(page, '/m/me')
      if (r.status === 'crash') flag({ key, route: '/m/me', kind: 'crash', severity: 'P1', expected: '«لوحتي» opens', actual: `crash (${r.consoleErrors[0] || r.apiErrors.map(e => e.status).join(',')})` })
      const shown = await shownTabs(page)
      for (const [to, rule] of Object.entries(TAB_RULES)) {
        const want = rule(l)
        if (want === null) continue            // module without matrix rows on this copy: not judged
        const has = shown.has(to)
        if (has !== want) {
          flag({ key, route: to, kind: 'screen', severity: 'P2',
            expected: `mobile tab ${to} ${want ? 'shown' : 'hidden'} (matrix / registry for ${l.role})`,
            actual: `tab ${has ? 'shown' : 'hidden'}` })
        }
      }
    } finally { await close() }
  })
}

// ── creates + branch picker ───────────────────────────────────────────────────────────────────────
const AREAS = {
  reservations: {
    allowed: l => allows(l, 'reservations', 'create'),
    newRoute: '/m/reservations/new',
    submitSel: '[data-tour="reservations-new-submit"]',
    pickerSel: '[data-tour="reservations-mnew-details"] select',
    apiCreate: (branch, note) => ({ method: 'POST', url: '/api/reservations/', data: {
      manual_item_name: `${note} صنف`, contact_name: 'UAT', contact_phone: FAKE_PHONE(5), branch: branch.id, notes: note } }),
    async ui(page, { branch, pick, note }) {
      await page.locator('[data-tour="reservations-mnew-manual"]').click()
      await page.getByPlaceholder('اكتب اسم الصنف يدوياً...').fill(`${note} صنف`)
      const details = page.locator('[data-tour="reservations-mnew-details"]')
      if (pick) await details.locator('select').first().selectOption(String(branch.id))
      await field(details, 'اسم التواصل', 'input').fill('عميل UAT')
      await field(details, 'هاتف التواصل', 'input').fill(FAKE_PHONE(5))
      await page.getByPlaceholder('أي تفاصيل إضافية...').fill(note)
      let r = await clickFor(page, page.locator(this.submitSel), /\/api\/reservations\/(\?force=true)?$/, 'POST', [200, 201, 409])
      if (r.status === 409) r = await clickFor(page, page.locator('[data-tour="reservations-new-dup-force"]'), /\/api\/reservations\/\?force=true$/)
      return idOf(r.body)
    },
    get: id => `/api/reservations/${id}/`,
  },
  demand: {
    allowed: l => allows(l, 'demand', 'create'),
    newRoute: '/m/demand/new',
    submitSel: '[data-tour="demand-mobile-new-submit"]',
    pickerSel: '[data-tour="demand-mobile-new-details"] select',
    apiCreate: (branch, note) => ({ method: 'POST', url: '/api/demand/', data: {
      phone: FAKE_PHONE(6), branch: branch.id, notes: note, items: [{ item_name_free: `${note} صنف`, quantity: 1 }] } }),
    async ui(page, { branch, pick, note }) {
      await page.getByPlaceholder('01xxxxxxxxx').fill(FAKE_PHONE(6))
      await page.getByPlaceholder('أو اكتب اسم صنف غير مكوَّد...').fill(`${note} صنف`)
      await page.locator('[data-tour="demand-mobile-new-manual"]').click()
      if (pick) await page.locator(this.pickerSel).first().selectOption(String(branch.id))
      await page.getByPlaceholder('أي تفاصيل...').fill(note)
      const r = await clickFor(page, page.locator(this.submitSel), /\/api\/demand\/$/)
      return idOf(r.body)
    },
    get: id => `/api/demand/${id}/`,
  },
  transfers: {
    allowed: l => allows(l, 'transfers', 'create'),
    newRoute: '/m/transfers/new',
    submitSel: '[data-tour="transfers-new-submit"] button.btn-primary',
    pickerSel: '[data-tour="transfers-new-branches"] select',
    pickerCount: 2,                                   // the supplying-branch select is always there
    apiCreate: (branch, note, ctx) => ({ method: 'POST', url: '/api/transfers/', data: {
      requesting_branch: branch.id, supplying_branch: (branch.id === BRANCH_A.id ? BRANCH_B : BRANCH_A).id,
      notes: note, items: [{ item: ctx.itemId, quantity: 1 }] } }),
    async ui(page, { branch, pick, note }) {
      const box = page.locator('[data-tour="transfers-new-branches"]')
      if (pick) await field(box, 'الفرع الطالب', 'select').selectOption(String(branch.id))
      const supplying = branch.id === BRANCH_A.id ? BRANCH_B : BRANCH_A
      await field(box, 'الفرع المصدر', 'select').selectOption(String(supplying.id))
      const items = page.locator('[data-tour="transfers-new-items"]')
      await items.getByPlaceholder('ابحث وأضف صنفاً...').fill('panadol')
      await items.getByText(/PANADOL/i).first().click()
      await page.getByPlaceholder('سبب الطلب أو أي تفاصيل...').fill(note)
      const r = await clickFor(page, page.locator(this.submitSel), /\/api\/transfers\/(\?submit=1)?$/)
      return idOf(r.body)
    },
    get: id => `/api/transfers/${id}/`,
  },
  shortage: {
    allowed: l => allows(l, 'shortage', 'create'),
    newRoute: '/m/shortage/new',
    submitSel: '[data-tour="shortage-mobile-create"]',
    pickerSel: '[data-tour="shortage-mobile-form"] select',
    apiCreate: (branch, note) => ({ method: 'POST', url: '/api/shortage/lists/', data: { branch: branch.id, title: note, notes: note } }),
    async ui(page, { branch, pick, note, key }) {
      if (pick) await page.locator(this.pickerSel).first().selectOption(String(branch.id))
      await page.getByPlaceholder('مثال: نواقص الجرد الأسبوعي').fill(note)
      const r = await clickFor(page, page.locator(this.submitSel), /\/api\/shortage\/lists\/$/)
      let id = idOf(r.body)
      if (!id) {
        // known W5a finding: the create answer carries no id, so the screen opens /m/shortage/undefined
        finding({ ws: WS, key, route: '/m/shortage/new', kind: 'workflow', severity: 'P2',
          expected: 'a new shortage list opens after «إنشاء»',
          actual: 'POST /api/shortage/lists/ answers without the new id; the phone opens /m/shortage/undefined' })
        const found = await call(page.request, 'GET', `/api/shortage/lists/?search=${encodeURIComponent(note)}`)
        id = rows(found).find(x => x.title === note)?.id
        if (id) await page.goto(`/m/shortage/${id}`)
      }
      // the shortage line, on the list's own phone screen
      await page.getByPlaceholder('اسم الصنف الناقص...').fill(`${note} صنف`)
      await clickFor(page, page.getByRole('button', { name: '+ إضافة' }), new RegExp(`/api/shortage/lists/${id}/add-item/$`))
      const list = await call(page.request, 'GET', `/api/shortage/lists/${id}/`)
      expect((list.items || []).some(i => String(i.raw_name || i.name || '').includes(note)), 'the new line is on the list').toBe(true)
      return id
    },
    get: id => `/api/shortage/lists/${id}/`,
  },
  qa: {
    allowed: l => qaWorker(l),
    newRoute: '/m/qa',
    submitSel: '[data-tour="hr-qa-new"]',
    pickerSel: '[data-tour="hr-qa-new-form"] select',
    pickerCount: 2,                                   // the template select is always there
    apiCreate: (branch, _note, ctx) => ({ method: 'POST', url: '/api/qa/inspections/', data: { template: ctx.templateId, branch: branch.id } }),
    async openForm(page) {
      await page.locator('[data-tour="hr-qa-new"]').click()
      await page.locator('[data-tour="hr-qa-new-form"] select').first().waitFor({ timeout: 30_000 })
    },
    async ui(page, { branch, pick }) {
      if (pick) await page.locator(this.pickerSel).nth(1).selectOption(String(branch.id))
      const r = await clickFor(page, page.locator('[data-tour="hr-qa-start"]'), /\/api\/qa\/inspections\/$/)
      const id = idOf(r.body)
      await expect(page).toHaveURL(new RegExp(`/m/qa/${id}$`))
      // the round: answer the first checklist line and submit
      await page.locator('[data-tour="hr-qa-result"]').first().locator('button').first().click()
      await clickFor(page, page.locator('[data-tour="hr-qa-submit"]'), new RegExp(`/api/qa/inspections/${id}/submit/$`))
      return id
    },
    get: id => `/api/qa/inspections/${id}/`,
  },
}

/** Ids the API creates need, read with an admin session (catalogue item, QA template). */
async function createContext(browser) {
  const { api, close } = await asUser(browser, 'admin', { desktop: true })
  try {
    const items = rows(await call(api, 'GET', '/api/items/?search=panadol&page_size=5'))
    const tpls = rows(await call(api, 'GET', '/api/qa/templates/'))
    return { itemId: items[0]?.id, templateId: tpls[0]?.id }
  } finally { await close() }
}

for (const key of MOBILE_USERS) {
  test(`creates: ${key} on the phone (reservation, demand, transfer, shortage line, QA round)`, async ({ browser }) => {
    const ctx = await createContext(browser)
    const { page, api, close } = await asUser(browser, key)
    try {
      const l = await live(api)
      const pick = canPick(l)
      const home = branchOf(key), other = otherOf(key)
      for (const [area, A] of Object.entries(AREAS)) {
        const may = A.allowed(l)
        if (may === null) continue
        const note = tag(`${area}-${key.replace(/\W/g, '')}`)
        const route = A.newRoute
        if (may) {
          // own branch, through the phone form
          await step(key, route, `${area}: create on the phone`, async () => {
            const r = await gotoSettled(page, route)
            expect(r.status, `${route} opens`).not.toBe('crash')
            if (A.openForm) await A.openForm(page)
            const pickers = await page.locator(A.pickerSel).count()
            const showsPicker = pickers >= (A.pickerCount || 1)
            if (showsPicker !== pick) {
              flag({ key, route, kind: 'branch', severity: 'P2',
                expected: `branch picker ${pick ? 'shown' : 'hidden'} (can_pick_any_branch=${!!l.me.can_pick_any_branch})`,
                actual: `picker ${showsPicker ? 'shown' : 'hidden'}` })
            }
            const id = await A.ui(page, { branch: home, pick: showsPicker && pick, note, key })
            expect(id, `${area}: the new record has an id`).toBeTruthy()
            const rec = await call(api, 'GET', A.get(id))
            const recBranch = rec.branch ?? rec.requesting_branch ?? rec.branch_id
            if (recBranch !== undefined && Number(recBranch) !== home.id) {
              flag({ key, route, kind: 'branch', severity: 'P1', expected: `${area} saved for the user's branch ${home.code}`, actual: `saved for branch id ${recBranch}` })
            }
          })
          // the other branch: allowed only for a picker
          const req = A.apiCreate(other, `${note}-x`, ctx)
          if (area === 'transfers' && !ctx.itemId) continue
          if (area === 'qa' && !ctx.templateId) continue
          if (pick) await mustAllow(api, { key, route, what: `${area}: create for the other branch ${other.code} (picker)`, ...req })
          else await mustRefuse(api, { key, route, what: `${area}: create for another branch ${other.code} (no picker)`, ...req, alsoRefused: [400] })
        } else {
          // no create grant: the server refuses, the phone stays calm
          const req = A.apiCreate(home, `${note}-refusal`, ctx)
          if (!(area === 'transfers' && !ctx.itemId) && !(area === 'qa' && !ctx.templateId)) {
            await mustRefuse(api, { key, route, what: `${area}: create without the create grant`, ...req })
          }
          const r = await gotoSettled(page, route)
          if (r.status === 'crash') {
            flag({ key, route, kind: 'crash', severity: 'P1', expected: `${route} refuses calmly`, actual: `crash (${(r.consoleErrors[0] || '').slice(0, 120)})` })
          } else if (r.finalUrl === route && await page.locator(A.submitSel).first().isVisible().catch(() => false)) {
            finding({ ws: WS, key, route, kind: 'button', severity: 'P3',
              expected: `no ${area} create control without the create grant (the server refuses it)`,
              actual: `${A.submitSel} offered on ${route}` })
          }
        }
      }
    } finally { await close() }
  })
}

// ── reservation cancel follows reservations:edit ─────────────────────────────────────────────────
for (const key of HOME.filter(k => userByKey(k).role !== 'delivery')) {
  test(`cancel: ${key} — mobile reservation cancel follows reservations:edit`, async ({ browser }) => {
    const { page, api, close } = await asUser(browser, key)
    let id
    try {
      const l = await live(api)
      const view = allows(l, 'reservations', 'view'), edit = allows(l, 'reservations', 'edit')
      test.skip(view === null || edit === null, 'reservations has no matrix rows on this copy')
      test.skip(!view, `${key} has no reservations view`)
      const note = tag(`cancel-${key}`)
      const a = await asUser(browser, 'admin')
      try {
        id = idOf(await call(a.api, 'POST', '/api/reservations/', {
          manual_item_name: `${note} صنف`, contact_name: 'UAT', contact_phone: FAKE_PHONE(7), branch: BRANCH_A.id, notes: note }))
      } finally { await a.close() }
      const route = `/m/reservations/${id}`
      const r = await gotoSettled(page, route)
      if (r.status === 'crash') flag({ key, route: '/m/reservations/:id', kind: 'crash', severity: 'P1', expected: 'reservation opens', actual: 'crash' })
      const cancelBtn = page.locator('[data-tour="reservations-detail-status"] button', { hasText: /^إلغاء$/ })
      const shown = await cancelBtn.isVisible().catch(() => false)
      if (shown !== edit) {
        flag({ key, route: '/m/reservations/:id', kind: 'button', severity: edit ? 'P2' : 'P3',
          expected: `«إلغاء» ${edit ? 'offered' : 'not offered'} (reservations:edit=${edit}, role review decision 6)`,
          actual: `«إلغاء» ${shown ? 'offered' : 'not offered'} on a pending reservation` })
      }
      if (edit && shown) {
        await step(key, '/m/reservations/:id', 'cancel with a reason on the phone', async () => {
          await cancelBtn.click()
          await page.locator('select').filter({ has: page.locator('option', { hasText: '— اختر سبب الإلغاء —' }) }).selectOption({ index: 1 })
          await clickFor(page, page.locator('[data-tour="reservations-detail-status-confirm"]'), new RegExp(`/api/reservations/${id}/change-status/$`))
          expect((await call(api, 'GET', `/api/reservations/${id}/`)).status).toBe('cancelled')
        })
      } else if (!edit) {
        await mustRefuse(api, { key, route: '/m/reservations/:id', severity: 'P2', what: 'cancel a reservation without reservations:edit',
          method: 'POST', url: `/api/reservations/${id}/change-status/`, data: { status: 'cancelled', note: 'UAT-W8 refusal' } })
      }
    } finally { await close() }
  })
}

// ── mobile customer search: phones per apps/customers/access.py ─────────────────────────────────
const PHONE_USERS = UAT_USERS.filter(u => !u.key.startsWith('real:') && u.role !== 'delivery').map(u => u.key)
const refCustomer = b => (reference(b)?.customers || []).find(c => phoneDigits(c.phone).length >= 10)

for (const key of PHONE_USERS) {
  test(`phones: ${key} — mobile customer search masks per the phone rule`, async ({ browser }) => {
    const { page, api, close } = await asUser(browser, key)
    try {
      const l = await live(api)
      const view = allows(l, 'customers', 'view')
      test.skip(view === null, 'customers has no matrix rows on this copy')
      const exp = expectedFor(key)
      const allBranches = !!l.me.can_pick_any_branch
      for (const [label, branch] of [['A', BRANCH_A], ['B', BRANCH_B]]) {
        const c = refCustomer(label)
        if (!c) continue
        const digits = phoneDigits(c.phone)
        if (!view) {
          const r = await raw(api, 'GET', `/api/customers/?search=${digits}&page_size=10`)
          if (r.status === 200 && rows(r.body).some(x => phoneDigits(x.phone) === digits)) {
            flag({ key, route: '/m/customers', kind: 'phone', severity: 'P1', expected: 'no customers view: no customer phone', actual: `full phone ${last3(c.phone)} returned` })
          }
          continue
        }
        const own = allBranches || (exp.branchIds || []).includes(branch.id)
        const visible = !!l.me.can_see_customer_phone && own
        await gotoSettled(page, '/m/customers')
        const search = page.locator('[data-tour="customers-mobile-search"] input').first()
        const resP = page.waitForResponse(r => /\/api\/customers\/\?/.test(r.url()) && r.url().includes(digits), { timeout: 30_000 })
        await search.fill(digits)
        const res = await resP.catch(() => null)
        if (!res) { flag({ key, route: '/m/customers', kind: 'workflow', severity: 'P2', expected: 'customer search answers', actual: `no search answer for a branch-${label} customer (${last3(c.phone)})` }); continue }
        if (res.status() >= 500) { flag({ key, route: '/m/customers', kind: 'crash', severity: 'P1', expected: 'customer search answers', actual: `HTTP ${res.status()}` }); continue }
        const body = await res.json().catch(() => null)
        const row = rows(body).find(x => x.id === c.id)
        if (!row) {
          // a full phone finds any customer (findable_q) — not finding it is a search gap, not a leak
          finding({ ws: WS, key, route: '/m/customers', kind: 'workflow', severity: 'P3',
            expected: `a full-phone search finds the branch-${label} reference customer`, actual: `not in the answer (${last3(c.phone)})` })
          continue
        }
        const got = phoneDigits(row.phone)
        if (visible && got !== digits) {
          flag({ key, route: '/m/customers', kind: 'phone', severity: 'P2', expected: `full phone shown (own branch, phones allowed) ${last3(c.phone)}`, actual: `masked or other: …${got.slice(-3)} (${got.length} digits)` })
        }
        if (!visible && got === digits) {
          flag({ key, route: '/m/customers', kind: 'phone', severity: 'P1',
            expected: `phone masked (${l.me.can_see_customer_phone ? `branch-${label} customer outside the user's branches` : 'can_see_customer_phone off'})`,
            actual: `full phone in the API answer ${last3(c.phone)}` })
        }
        // and nothing on the screen spells the full number when it must be masked
        if (!visible) {
          await page.waitForTimeout(800)
          const text = (await page.locator('main, #root').first().innerText({ timeout: 5_000 }).catch(() => '')).replace(/\D/g, '')
          if (text.includes(digits)) {
            flag({ key, route: '/m/customers', kind: 'phone', severity: 'P1', expected: 'masked phone on the screen', actual: `full number rendered ${last3(c.phone)}` })
          }
        }
        await search.fill('')
      }
    } finally { await close() }
  })
}

// ── delivery role never sees /m ───────────────────────────────────────────────────────────────────
for (const key of [...HOME, ...TWINS_B].filter(k => userByKey(k).role === 'delivery')) {
  test(`shell: ${key} is sent from /m to /rider`, async ({ browser }) => {
    const { page, close } = await asUser(browser, key)
    try {
      for (const route of ['/m', '/m/reservations/new', '/m/customers']) {
        const r = await gotoSettled(page, route)
        if (!/^\/rider\/?$/.test(r.finalUrl)) {
          flag({ key, route, kind: 'screen', severity: 'P1', expected: 'delivery role sent to /rider (N3 H4)', actual: `landed on ${r.finalUrl} (${r.status})` })
        }
      }
    } finally { await close() }
  })
}
