// W5a reservations: create → available → contacted (salesperson/call-center screen buttons) →
// confirmed → fulfilled (pharmacist «العميل قادم» / «تم الصرف»), then a role that must not change it.
import { test, expect } from '@playwright/test'
import { assertReaderCopy } from '../../lib/guard.js'
import { BRANCH_A } from '../../lib/users.js'
import {
  asUser, step, clickFor, mustRefuse, firstWho, firstNot, tag, FAKE_PHONE, BASE, remember, recall,
} from './_ops.js'

const AREA = 'reservations'
const STATUS_URL = /\/api\/reservations\/\d+\/change-status\/$/

test.describe('reservations: create → fulfil', () => {
  const creator = firstWho(['salesperson', 'call_center', 'pharmacist'], 'reservations', 'create')
  const fulfiller = firstWho(['pharmacist', 'supervisor'], 'reservations', 'finalize')
  const outsider = firstNot(['viewer', 'quality_manager', 'accountant', 'delivery'], 'reservations', 'edit')
  let id = null
  const note = tag('reservation')

  test.beforeAll(async () => { await assertReaderCopy(BASE) })

  test(`${creator} creates a reservation and marks it available → contacted`, async ({ browser }) => {
    remember(AREA, null)
    expect(creator, 'some branch-A role may create reservations').toBeTruthy()
    const { page, close } = await asUser(browser, creator)
    try {
      await step(creator, '/reservations/new', 'create reservation', async () => {
        await page.goto('/reservations/new')
        await page.getByPlaceholder('اكتب اسم الصنف يدوياً...').fill(`${note} صنف يدوي`)
        const contact = page.locator('[data-tour="reservations-new-contact"]')
        await contact.locator('input').first().fill('عميل UAT')
        await contact.locator('input[dir="ltr"]').fill(FAKE_PHONE(1))
        await page.getByPlaceholder('أي تفاصيل إضافية...').fill(note)
        const { body } = await clickFor(page, page.locator('[data-tour="reservations-new-submit"]'), /\/api\/reservations\/$/)
        id = body.id; remember(AREA, { id })
        await expect(page).toHaveURL(new RegExp(`/reservations/${id}$`))
      })
      const route = `/reservations/${id}`
      for (const [label, status] of [[/المخزون متاح/, 'available'], [/تم التواصل/, 'contacted']]) {
        await step(creator, route, `quick button → ${status}`, async () => {
          const btn = page.locator('[data-tour="reservations-detail-quick-status"]', { hasText: label })
          await expect(btn).toBeVisible()
          await clickFor(page, btn, STATUS_URL)
          const r = await (await page.request.get(`/api/reservations/${id}/`)).json()
          expect(r.status).toBe(status)
        })
      }
    } finally { await close() }
  })

  test(`${fulfiller} confirms the customer is coming and fulfils it`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no reservation from the previous step')
    const { page, close } = await asUser(browser, fulfiller)
    const route = `/reservations/${id}`
    try {
      await page.goto(route)
      for (const [label, status] of [[/العميل قادم/, 'confirmed'], [/تم الصرف/, 'fulfilled']]) {
        await step(fulfiller, route, `quick button → ${status}`, async () => {
          const btn = page.locator('[data-tour="reservations-detail-quick-status"]', { hasText: label })
          await expect(btn).toBeVisible()
          await clickFor(page, btn, STATUS_URL)
          const r = await (await page.request.get(`/api/reservations/${id}/`)).json()
          expect(r.status).toBe(status)
        })
      }
    } finally { await close() }
  })

  test(`${outsider} must not change a reservation's status`, async ({ browser }) => {
    id ??= recall(AREA).id
    test.skip(!id, 'no reservation from the previous step')
    expect(outsider).toBeTruthy()
    const { page, api, close } = await asUser(browser, outsider)
    try {
      await page.goto('/dashboard')
      await mustRefuse(api, { key: outsider, route: `/reservations/${id}`, what: 'POST change-status (cancel) on a reservation',
                              method: 'POST', url: `/api/reservations/${id}/change-status/`, data: { status: 'cancelled', note: 'UAT refusal check' } })
      await mustRefuse(api, { key: outsider, route: '/reservations/new', what: 'POST a new reservation',
                              method: 'POST', url: '/api/reservations/',
                              data: { manual_item_name: 'UAT-refusal', contact_name: 'UAT', contact_phone: FAKE_PHONE(9), branch: BRANCH_A.id, notes: 'UAT-refusal' } })
    } finally { await close() }
  })
})
