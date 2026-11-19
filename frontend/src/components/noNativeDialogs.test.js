// D-25 / FE-9 — native window.confirm / alert / prompt block the tab (CLAUDE.md rule 11).
// Converted screens use ConfirmButton / useConfirm (components/InlineConfirm.jsx) and toasts.
// Every file listed here must stay free of them; add a file once its batch is converted.
// The count of what is left is printed so the next batch can pick the busiest screens.
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(process.cwd(), 'src')

// `window.confirm(`, `window.alert (`, `globalThis.prompt(`, or a bare `confirm(` / `alert(` / `prompt(`
// that is not a method (`api.confirm(`) and not part of a longer name (`confirmInline(`).
const NATIVE = /(?:\b(?:window|globalThis|self)\s*\.\s*(?:confirm|alert|prompt)\s*\()|(?:(?<![\w$.])(?:confirm|alert|prompt)\s*\()/

// Batch 1 (D-25): the busiest screens outside the ones other sessions were editing.
const CONVERTED = [
  'pages/CallCenterPage.jsx',
  'pages/ReservationDetailPage.jsx',
  'pages/CustomerDetailPage.jsx',
  'pages/TransferDetailPage.jsx',
  'pages/InvoicePage.jsx',
  'pages/InsuranceClaimsPage.jsx',
  'pages/PurchasingDashboard.jsx',
  'pages/DemandPage.jsx',
  'pages/DemandDetailPage.jsx',
  // batch 2
  'pages/InsuranceClaimDetailPage.jsx',
  // batch 3
  'pages/FollowUpsPage.jsx',
  // batch 4
  'pages/DiscountAlignmentPage.jsx',
  'pages/CasesPage.jsx',
  'pages/ForecastScenarioPage.jsx',
  'pages/ImageEnrichmentPage.jsx',
  'pages/InsurancePrintPage.jsx',
  'pages/InsurancePrintProfilesPage.jsx',
  // batch 5
  'pages/SupplierCategoriesPage.jsx',
  'pages/SettingsPage.jsx',
  'pages/ProcurementDashboard.jsx',
  'pages/FinanceSchemaPage.jsx',
  'pages/DemandDashboardPage.jsx',
  'components/TwoFactorSetup.jsx',
  'components/ReceiptPrint.jsx',
  'pages/mobile/MobileDeliveryDetailPage.jsx',
  'pages/invoices/BundleWorkbench.jsx',
  'pages/UsersPage.jsx',
  'pages/ReservationsKanban.jsx',
  'pages/ProductCatalogPage.jsx',
  'pages/OmniAutomationsPage.jsx',
  'pages/OffersPage.jsx',
  'pages/DeliveryDashboard.jsx',
  'pages/AuditPage.jsx',
  'components/followups/CallListsPanel.jsx',
  'components/PrescriptionOcrModal.jsx',
  'components/InTransitTab.jsx',
  'components/HRPrint.jsx',
  'components/ui.jsx',
  'components/InlineConfirm.jsx',
]

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(jsx?|tsx?)$/.test(name) && !/\.test\.[jt]sx?$/.test(name)) out.push(p)
  }
  return out
}

// comments are not calls: drop // line comments and /* … */ blocks before matching
const code = (src) => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')

describe('native browser dialogs', () => {
  it('the guard catches every way of calling one, and not the replacements', () => {
    for (const src of [
      "if (!window.confirm('حذف؟')) return",
      'window.alert(msg)',
      "const n = prompt('ملاحظات:')",
      "if (!confirm('حذف هذا السطر؟')) return",
      "onError: (e) => alert(e.message)",
      'globalThis.prompt ("x")',
    ]) expect(NATIVE.test(src), src).toBe(true)
    for (const src of [
      'await invoicesApi.confirm(invoiceId)',
      "await confirmInline('متابعة؟')",
      "await ask('سبب:')",
      "toast.error('فشل')",
      'const { confirm, ask, ui } = useConfirm()',
    ]) expect(NATIVE.test(src), src).toBe(false)
  })

  it('the converted screens contain no window.confirm / alert / prompt', () => {
    const offenders = CONVERTED.filter(rel => NATIVE.test(code(readFileSync(join(SRC, rel), 'utf8'))))
    expect(offenders).toEqual([])
  })

  it('reports how many native dialogs are left for later batches', () => {
    const left = walk(SRC)
      .map(p => [relative(SRC, p).replace(/\\/g, '/'), code(readFileSync(p, 'utf8'))])
      .map(([rel, src]) => [rel, (src.match(new RegExp(NATIVE.source, 'g')) || []).length])
      .filter(([, n]) => n > 0)
    const total = left.reduce((s, [, n]) => s + n, 0)
    console.info(`[D-25] native dialogs left: ${total} in ${left.length} files`)
    expect(left.some(([rel]) => CONVERTED.includes(rel))).toBe(false)
  })
})
