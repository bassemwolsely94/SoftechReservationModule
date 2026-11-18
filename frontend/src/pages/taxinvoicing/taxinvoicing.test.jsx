// The owner's display rules for the review screen: the server's numbers are shown as they are, the
// "all lines" switch is only for approvers and only changes the query, and live sending shows as off.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({
  document: vi.fn(),
  print: vi.fn(),
  documents: vi.fn(),
  importInspect: vi.fn(),
  importPreview: vi.fn(),
  importApply: vi.fn(),
  submit: vi.fn(),
  approve: vi.fn(),
  preview: vi.fn(),
  items: vi.fn(),
  updateItem: vi.fn(),
  previewReceipts: vi.fn(),
  submitReceipts: vi.fn(),
  etaStatus: vi.fn(),
  etaCheckLogin: vi.fn(),
  codes: vi.fn(),
  codeCandidates: vi.fn(),
  codesPrepare: vi.fn(),
  codesSend: vi.fn(),
  codesRefresh: vi.fn(),
  codesCheck: vi.fn(),
  codesAddFromCatalog: vi.fn(),
  codeGpc: vi.fn(() => Promise.resolve({ data: { loaded: true, rows: [{ code: '10000673', name_ar: 'أدوية', name_en: 'Medicines', used: 5 }] } })),
  chainLookup: vi.fn(),
  startChain: vi.fn(),
  undoChainStart: vi.fn(),
  endTestMapping: vi.fn(),
  setSendFrom: vi.fn(),
  historyProgress: vi.fn(),
  historyRefresh: vi.fn(),
  historyDocuments: vi.fn(),
  historyReceipts: vi.fn(),
  historyDocument: vi.fn(),
  historyReceipt: vi.fn(),
  historyDocumentPdf: vi.fn(),
  historyExport: vi.fn(),
  reconSummary: vi.fn(),
  reconLines: vi.fn(),
  reconExport: vi.fn(),
  reconRefresh: vi.fn(),
  reconUncoded: vi.fn(),
  reconUncodedExport: vi.fn(),
  saveReceiptConfig: vi.fn(),
  codingQueue: vi.fn(),
  codingDecide: vi.fn(),
  codingReopen: vi.fn(),
  codingSetBrick: vi.fn(),
  codingSuggest: vi.fn(),
  etaHolds: vi.fn(),
  egsSheet: vi.fn(() => Promise.resolve({ data: { versions: [], build: { state: 'idle' }, pending: { ready: 0, skipped: [] }, can_build: false } })),
  egsSheetBuild: vi.fn(),
  egsSheetDownload: vi.fn(),
  egsAgent: vi.fn(() => Promise.resolve({ data: { switch: false, agent: { at: null, version: null, outdated: true }, live: null,
    last_fetch: null, held: null, jobs: [], busy: false, has_version: true, can_approve: false } })),
  egsAgentFetch: vi.fn(),
  egsAgentWrite: vi.fn(),
  egsAgentImport: vi.fn(),
}))

vi.mock('../../components/DataFreshnessBar', () => ({ default: () => null }))
vi.mock('../../api/client', () => ({
  taxInvoicingApi: api,
  branchesApi: { list: vi.fn(() => Promise.resolve({ data: [{ softech_branch_id: '170', name_ar: 'فرع الجيش' }] })) },
}))

const { default: DocumentDetail } = await import('./DocumentDetail')
const { default: PrintTab } = await import('./PrintTab')
const { default: ImportTab, buildOptions } = await import('./ImportTab')
const { default: ItemsTab } = await import('./ItemsTab')
const { BranchActions, ChainStart, TestMapping, SendFrom } = await import('./ReceiptsTab')
const { default: CodesTab, CodeCheck, Candidates, Gs1Candidates } = await import('./CodesTab')
const { HistoryProgress } = await import('./SettingsTab')
const { default: HistoryTab } = await import('./HistoryTab')
const { default: QueueTab } = await import('./QueueTab')
const { default: EgsSheetPanel, REMINDER } = await import('./EgsSheetPanel')
const { default: EgsAgentPart, OUTDATED, SWITCH_OFF, jobResult } = await import('./EgsAgentPart')

const line = (id, status) => ({
  id, docnumber: '55', docdate: '2026-10-01', branch: '170', itemcode: `I${id}`, item_name: `صنف ${id}`, quantity: '1',
  gross: '10', discount: '0', net: '10', status, status_label: status, reason: '', code_type: 'EGS', eta_code: 'EG-1-1',
  tax_treatment: 'taxable', vat_rate: '14', net_ex_vat: '8.77', vat_amount: '1.23', total_incl_vat: '10',
})

function doc(overrides = {}) {
  return {
    id: 7, internal_id: 'INV-2026-1', doc_type: 'i', doc_type_label: 'فاتورة', status: 'draft', status_label: 'مسودة', claim_id: 9,
    claim_number: 'C-9', client: 'جهة', original_id: null, lines: [line(1, 'approved')], view: 'approved',
    counts: { approved: 1, exempt: 0, uncoded: 2, pending: 1, excluded: 3, unresolved: 3, total: 7 },
    totals: { sales: '10', discount: '0', net: '8.77', vat: '1.23', total: '10' },
    reconciliation: { source_total: '70', proposed_total: '10', difference: '60', excluded_total: '30', unresolved_total: '30', unexplained: '0', within_tolerance: true, rows: [] },
    blockers: [{ code: 'uncoded', message: '2 صنف بدون كود معتمد' }], affected_skus: [], reviews: [],
    presentation_mode: 'summary', fiscal_mode: 'detailed', fiscal_mode_reason: 'سبب', attempts: [], events: [], notes: [], ...overrides,
  }
}

const ME = {
  can_create: true, can_edit: true, can_approve: true, can_view_all_lines: true, can_finalize: true, submit_enabled: false,
  receipt_submit_enabled: false,
  line_statuses: [['approved', 'معتمد'], ['exempt', 'معفى'], ['uncoded', 'غير مُرمَّز'], ['pending', 'قيد المراجعة'], ['excluded', 'مستبعد']].map(([key, label]) => ({ key, label })),
}

function show(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)

describe('document review', () => {
  it('hides "show all source lines" from a user without the right', async () => {
    api.document.mockResolvedValue({ data: doc() })
    show(<DocumentDetail id="7" me={{ ...ME, can_view_all_lines: false, can_approve: false }} go={() => {}} />)
    await screen.findByText(/البنود المعتمدة/)
    expect(screen.queryByText('عرض كل بنود المصدر')).toBeNull()
    expect(api.document).toHaveBeenCalledWith('7', {})
  })

  it('asks the server for view=all only when switched on, and keeps the counts visible in both views', async () => {
    api.document.mockImplementation((_id, params) => Promise.resolve({
      data: doc(params.view === 'all' ? { view: 'all', lines: [line(1, 'approved'), line(2, 'uncoded')] } : {}),
    }))
    show(<DocumentDetail id="7" me={ME} go={() => {}} />)
    await screen.findByText(/البنود المعتمدة \(1 من 7\)/)
    expect(screen.getByText(/غير محسوم: 3 · مستبعد: 3/)).toBeTruthy()
    fireEvent.click(screen.getByLabelText('عرض كل بنود المصدر'))
    await screen.findByText(/كل بنود المصدر \(2\)/)
    expect(api.document).toHaveBeenLastCalledWith('7', { view: 'all' })
    expect(screen.getByText(/غير محسوم: 3 · مستبعد: 3/)).toBeTruthy()
  })

  it('shows the blockers and disables approve while the server lists any', async () => {
    api.document.mockResolvedValue({ data: doc() })
    show(<DocumentDetail id="7" me={ME} go={() => {}} />)
    await screen.findByText('2 صنف بدون كود معتمد')
    expect(screen.getByRole('button', { name: /اعتماد المستند/ }).disabled).toBe(true)
  })

  it('says sending is off and keeps the send button disabled when submit_enabled is false', async () => {
    api.document.mockResolvedValue({ data: doc({ status: 'approved', status_label: 'معتمدة', blockers: [] }) })
    show(<DocumentDetail id="7" me={ME} go={() => {}} />)
    await screen.findByText(/الإرسال الفعلي مغلق/)
    const input = screen.getByLabelText(/اكتب رقم المستند للتأكيد/)
    fireEvent.change(input, { target: { value: 'INV-2026-1' } })
    expect(screen.getByRole('button', { name: 'إرسال للمصلحة' }).disabled).toBe(true)
    expect(api.submit).not.toHaveBeenCalled()
  })
})

describe('printed invoice', () => {
  // jsdom applies no print CSS, so this is the only unit-level guard: a plain `.tax-print-sheet` rule
  // loses to the `body:has(...) *` rule that hides the shell, and the page prints blank.
  it('keeps the sheet rules as specific as the rule that hides the shell', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf-8')
    expect(css).toContain('body:has(.tax-print-sheet) * { visibility: hidden; }')
    expect(css).toMatch(/body:has\(\.tax-print-sheet\) \.tax-print-sheet,\s+body:has\(\.tax-print-sheet\) \.tax-print-sheet \* \{ visibility: visible; \}/)
  })

  it('shows one summary row, no VAT column and a clear statement when no VAT is due', async () => {
    api.documents.mockResolvedValue({ data: [] })
    api.print.mockResolvedValue({ data: {
      internal_id: 'INV-2026-1', doc_type_label: 'فاتورة', status: 'approved', status_label: 'معتمدة', is_official: false,
      issuer: { name: 'الرزيقي', tax_id: '1' }, buyer: { name: 'جهة', tax_id: '2' }, claim_number: 'C-9',
      rows: [{ description: 'مطالبة مالية — C-9', quantity: '1', net: '100', vat: '0', total: '100' }],
      no_vat_due: true, totals: { net: '100', vat: '0', total: '100' },
    } })
    show(<PrintTab docId="7" go={() => {}} />)
    await screen.findByText('مطالبة مالية — C-9')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText(/لا توجد ضريبة قيمة مضافة مستحقة/)).toBeTruthy()
    expect(screen.getByText(/نسخة غير رسمية/)).toBeTruthy()
    expect(screen.queryByRole('columnheader', { name: 'الضريبة' })).toBeNull()
  })
})

describe('sending receipts', () => {
  const dryRun = over => ({ data: { dry_run: true, count: 2, submit_enabled: false, receipts: [], ...over } })
  const sendButton = () => screen.queryByRole('button', { name: 'إرسال الدفعة للمصلحة' })

  async function preview() {
    fireEvent.click(screen.getByRole('button', { name: 'معاينة الإرسال' }))
    await screen.findByText(/معاينة فقط/)
  }

  it('offers no send before the dry run', () => {
    show(<BranchActions branch="170" label="170 · الجيش" me={ME} />)
    expect(sendButton()).toBeNull()
  })

  it('stays disabled while the server says sending is off, even with the code typed', async () => {
    api.previewReceipts.mockResolvedValue(dryRun())
    show(<BranchActions branch="170" label="170 · الجيش" me={ME} />)
    await preview()
    fireEvent.change(screen.getByLabelText(/اكتب كود الفرع/), { target: { value: '170' } })
    expect(sendButton().disabled).toBe(true)
    expect(screen.getByText('معطل طالما الإرسال الفعلي مغلق.')).toBeTruthy()
  })

  it('is not offered without finalize', () => {
    show(<BranchActions branch="170" label="170" me={{ ...ME, can_finalize: false }} />)
    expect(screen.queryByRole('button', { name: 'معاينة الإرسال' })).toBeNull()
    expect(sendButton()).toBeNull()
  })

  it('needs something to send and the typed code, then sends that code once', async () => {
    api.previewReceipts.mockResolvedValue(dryRun({ submit_enabled: true }))
    api.submitReceipts.mockResolvedValue({ data: { status: 'submitted', count: 2 } })
    show(<BranchActions branch="170" label="170 · الجيش" me={ME} />)
    await preview()
    expect(sendButton().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/اكتب كود الفرع/), { target: { value: '170' } })
    fireEvent.click(sendButton())
    await screen.findByText(/أُرسلت دفعة من 2 إيصال/)
    expect(api.submitReceipts).toHaveBeenCalledTimes(1)
    expect(api.submitReceipts).toHaveBeenCalledWith('170', '170')
    expect(sendButton()).toBeNull()   // the next batch needs a new dry run
  })

  it('stops at an uncertain result and says to ask the Authority first', async () => {
    api.previewReceipts.mockResolvedValue(dryRun({ submit_enabled: true }))
    api.submitReceipts.mockResolvedValue({ data: { status: 'uncertain', count: 2 } })
    show(<BranchActions branch="170" label="170" me={ME} />)
    await preview()
    fireEvent.change(screen.getByLabelText(/اكتب كود الفرع/), { target: { value: '170' } })
    fireEvent.click(sendButton())
    await screen.findByText(/نتيجة غير مؤكدة لـ 2 إيصال/)
  })

  it('shows the server refusal', async () => {
    api.previewReceipts.mockResolvedValue(dryRun({ submit_enabled: true }))
    api.submitReceipts.mockRejectedValue({ response: { data: { detail: 'اكتب كود الفرع للتأكيد' } } })
    show(<BranchActions branch="170" label="170" me={ME} />)
    await preview()
    fireEvent.change(screen.getByLabelText(/اكتب كود الفرع/), { target: { value: '999' } })
    fireEvent.click(sendButton())
    await screen.findByText('اكتب كود الفرع للتأكيد')
  })
})

describe('item mapping', () => {
  const row = {
    id: 3, itemcode: '1003', item_name: 'كريم', coding_status: 'pending', coding_status_label: 'قيد الاعتماد', code_type: '', eta_code: '',
    tax_treatment: 'unclassified', tax_treatment_label: 'غير مصنف', vat_rate: '0', disposition: 'review', disposition_label: 'مراجعة',
    list_status: 'black', list_status_label: 'سوداء', listed_reason: '', treatment_confirmed_at: null,
  }

  it('saves one question alone and shows the server refusal', async () => {
    api.items.mockResolvedValue({ data: [row] })
    api.updateItem.mockRejectedValue({ response: { data: { detail: 'المعاملة الضريبية وقرار الإدراج للمحاسب' } } })
    show(<ItemsTab me={ME} go={() => {}} />)
    fireEvent.click(await screen.findByText('كريم'))
    const column = screen.getByText('قرار الإدراج في الفاتورة').parentElement
    fireEvent.click(within(column).getByRole('button', { name: 'حفظ' }))
    await screen.findByText('المعاملة الضريبية وقرار الإدراج للمحاسب')
    expect(api.updateItem).toHaveBeenCalledWith(3, { disposition: 'review' })
  })
})

describe('item import', () => {
  it('sends only what the user mapped', () => {
    const o = buildOptions({
      sheet: 'S', headerRow: '2', mapping: { itemcode: '3', eta_code: '', list_flag: '0' },
      blackText: 'B, اسود ,', whiteText: '', codedStatus: 'pending', overwrite: false,
    })
    expect(o).toEqual({
      sheet: 'S', header_row: 2, mapping: { itemcode: 3, list_flag: 0 }, black_values: ['B', 'اسود'], white_values: [],
      coded_status: 'pending', overwrite_conflicts: false,
    })
  })

  it('preselects no column from the header names, and apply sends the preview hash', async () => {
    api.importInspect.mockResolvedValue({ data: {
      sheets: [{ name: 'S', rows: 3, columns: [{ index: 0, header: 'itemcode', samples: ['1'] }, { index: 1, header: 'eta_code', samples: ['EG-1'] }] }],
      fields: { itemcode: 'كود الصنف', eta_code: 'كود المصلحة' },
    } })
    api.importPreview.mockResolvedValue({ data: {
      dry_run: true, preview_hash: 'HASH', issues: [], issue_counts: {}, issues_truncated: false, sample: [],
      counts: { rows: 1, valid: 1, errors: 0, warnings: 0, new: 1, updated: 0, conflicts: 0, duplicates: 0, coded: 0, not_coded: 1, black: 0, white: 0, unlisted: 1 },
    } })
    api.importApply.mockResolvedValue({ data: { written: 1, conflicts_skipped: 0, revalidated_drafts: 0, counts: {} } })
    const { container } = show(<ImportTab me={ME} />)
    const file = new File(['x'], 'items.xlsx')
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'قراءة الأعمدة' }))
    const select = await screen.findByLabelText('كود الصنف', { selector: 'select' })
    expect(select.value).toBe('')
    expect(screen.getByRole('button', { name: 'معاينة بدون حفظ' }).disabled).toBe(true)
    fireEvent.change(select, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'معاينة بدون حفظ' }))
    fireEvent.click(await screen.findByRole('button', { name: /اعتماد الاستيراد/ }))
    await waitFor(() => expect(api.importApply).toHaveBeenCalled())
    const [, options, hash] = api.importApply.mock.calls[0]
    expect(hash).toBe('HASH')
    expect(options.mapping).toEqual({ itemcode: 0 })
  })
})

describe('ETA item codes', () => {
  const status = { environment: 'preprod', label: 'التجريبية (Pre-production)', api_base: 'https://api.preprod.invoicing.eta.gov.eg',
    is_production: false, production_allowed: false, erp_client_configured: true, invoice_submit_enabled: false,
    receipt_submit_enabled: false, coding_send_enabled: false }
  const request = { id: 3, itemcode: '50001', item_code: 'EG-1-50001', code_name: 'Panadol', code_name_ar: 'بانادول',
    parent_code: '10000454', status: 'prepared', status_label: 'جاهز للإرسال', error: '', eta_status: '', sent_at: null, checked_at: null }

  beforeEach(() => {
    api.etaStatus.mockResolvedValue({ data: status })
    api.codes.mockResolvedValue({ data: { summary: { by_status: { prepared: 1 }, candidates: 4 }, rows: [request] } })
    api.codeCandidates.mockResolvedValue({ data: [] })
  })

  it('shows the pre-production badge and keeps sending disabled while the switch is off', async () => {
    show(<CodesTab me={{ ...ME, coding_send_enabled: false, code_request_statuses: [] }} />)
    expect(await screen.findByText('التجريبية (Pre-production)')).toBeTruthy()
    expect(await screen.findByText('EG-1-50001')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('اختيار EG-1-50001'))
    expect(screen.getByText('إرسال للمصلحة').closest('button').disabled).toBe(true)
  })

  it('offers no send or login test without finalize', async () => {
    show(<CodesTab me={{ ...ME, can_finalize: false, coding_send_enabled: true, code_request_statuses: [] }} />)
    expect(await screen.findByText('EG-1-50001')).toBeTruthy()
    expect(screen.queryByText('إرسال للمصلحة')).toBeNull()
    expect(screen.queryByText('اختبار الدخول')).toBeNull()
  })

  it('sends the ticked requests with the typed count', async () => {
    api.codesSend.mockResolvedValue({ data: { submitted: 1, failed: 0, uncertain: 0, stopped: '' } })
    show(<CodesTab me={{ ...ME, coding_send_enabled: true, code_request_statuses: [] }} />)
    fireEvent.click(await screen.findByLabelText('اختيار EG-1-50001'))
    fireEvent.change(screen.getByLabelText(/اكتب عدد المختار/), { target: { value: '1' } })
    fireEvent.click(screen.getByText('إرسال للمصلحة'))
    await waitFor(() => expect(api.codesSend).toHaveBeenCalledWith({ ids: [3], confirm: '1' }))
  })
})

describe('device chain start', () => {
  const row = { branch: '150', device_serial: '2VA0280VY1', chain_start: '', has_chain_receipts: false }
  const latest = { uuid: 'a'.repeat(64), receipt_number: 'R-9', issued: '2026-11-12T10:00:00Z', status: 'Valid', submitter: 'Invoicer POS' }

  it('hands over only after the other program is confirmed stopped and the branch code typed', async () => {
    api.chainLookup.mockResolvedValue({ data: { device_serial: '2VA0280VY1', looked_back_days: 400, found: 1, latest } })
    api.startChain.mockResolvedValue({ data: {} })
    show(<ChainStart branch="150" row={row} me={ME} />)
    fireEvent.click(screen.getByText('ابحث في المصلحة عن إيصالات هذا الجهاز'))
    const start = (await screen.findByText('استلام السلسلة بعد هذا الإيصال')).closest('button')
    fireEvent.change(screen.getByLabelText(/اكتب كود الفرع/), { target: { value: '150' } })
    expect(start.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText(/توقف عن الإصدار/))
    expect(start.disabled).toBe(false)
    fireEvent.click(start)
    await waitFor(() => expect(api.startChain).toHaveBeenCalledWith('150',
      { mode: 'handover', confirm: '150', other_program_stopped: true, expected_uuid: latest.uuid }))
  })

  it('starts a fresh chain when ETA shows nothing from the device', async () => {
    api.chainLookup.mockResolvedValue({ data: { device_serial: '2VA0280VY1', looked_back_days: 400, found: 0, latest: null } })
    api.startChain.mockResolvedValue({ data: {} })
    show(<ChainStart branch="150" row={row} me={ME} />)
    fireEvent.click(screen.getByText('ابحث في المصلحة عن إيصالات هذا الجهاز'))
    fireEvent.change(await screen.findByLabelText(/اكتب كود الفرع/), { target: { value: '150' } })
    fireEvent.click(screen.getByText('بدء سلسلة جديدة'))
    await waitFor(() => expect(api.startChain).toHaveBeenCalledWith('150', { mode: 'fresh', confirm: '150' }))
  })

  it('offers nothing to change without finalize', () => {
    show(<ChainStart branch="150" row={row} me={{ ...ME, can_finalize: false }} />)
    expect(screen.queryByText('ابحث في المصلحة عن إيصالات هذا الجهاز')).toBeNull()
  })
})

describe('ETA code check', () => {
  const summary = { checks: { found: 5, inactive: 0, not_found: 2, unchecked: 9 },
    environment: { label: 'التجريبية (Pre-production)', api_base: 'https://api.preprod.invoicing.eta.gov.eg', is_production: false } }

  it('shows the counts for the system in use and registers picked existing codes as mirror requests', async () => {
    api.codeCandidates.mockResolvedValue({ data: [{ id: 4, itemcode: '60002', eta_code: 'EG-1-60002', item_name: 'Brufen', gpc_code: '10000454' }] })
    api.codesPrepare.mockResolvedValue({ data: { created: [1], skipped: [] } })
    show(<CodeCheck me={ME} summary={summary} />)
    expect(screen.getByText(/غير موجود 2/)).toBeTruthy()
    fireEvent.click(await screen.findByLabelText('اختيار 60002'))
    fireEvent.click(screen.getByText(/تجهيز تسجيلها/))
    await waitFor(() => expect(api.codesPrepare).toHaveBeenCalledWith({ ids: [4], kind: 'mirror' }))
  })

  it('offers no mirror list against production', () => {
    show(<CodeCheck me={ME} summary={{ ...summary, environment: { ...summary.environment, is_production: true } }} />)
    expect(api.codeCandidates).not.toHaveBeenCalled()
  })
})

describe('GPC category and GS1', () => {
  it('shows the suggested category and prepares with it when ticked', async () => {
    api.codeCandidates.mockResolvedValue({ data: [{ id: 9, itemcode: '71009', item_name: 'Newtab', item_name_ar: 'نيوتاب', gpc_code: '',
      suggested: { code: '10000673', name: 'أدوية', basis: 'family', basis_value: 'TAB', share: 67 }, coding_status_label: 'بلا كود' }] })
    api.codesPrepare.mockResolvedValue({ data: { created: [1], skipped: [] } })
    show(<Candidates me={ME} />)
    expect(await screen.findByText('10000673')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('اختيار 71009'))
    fireEvent.click(screen.getByText(/تجهيز طلبات \(/))
    await waitFor(() => expect(api.codesPrepare).toHaveBeenCalledWith({ ids: [9], parent_code: '', use_suggested: true }))
  })

  it('takes a brick picked from the list for the whole batch', async () => {
    api.codeCandidates.mockResolvedValue({ data: [{ id: 9, itemcode: '71009', item_name: 'Newtab', gpc_code: '', suggested: null, coding_status_label: 'بلا كود' }] })
    api.codesPrepare.mockResolvedValue({ data: { created: [1], skipped: [] } })
    show(<Candidates me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 71009'))
    await waitFor(() => expect(api.codeGpc).toHaveBeenCalled())
    await waitFor(() => expect(document.querySelectorAll('#tax-gpc-bricks option').length).toBe(1))
    fireEvent.change(screen.getByLabelText('فئة GPC'), { target: { value: '10000673 أدوية' } })
    fireEvent.click(screen.getByText(/تجهيز طلبات \(/))
    await waitFor(() => expect(api.codesPrepare).toHaveBeenCalledWith({ ids: [9], parent_code: '10000673', use_suggested: true }))
  })

  it('prepares GS1 reuse requests for ticked barcodes', async () => {
    api.codeCandidates.mockResolvedValue({ data: [{ id: 5, itemcode: '71010', barcode: '4006381333931', item_name: 'Shampoo' }] })
    api.codesPrepare.mockResolvedValue({ data: { created: [2], skipped: [] } })
    show(<Gs1Candidates me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 71010'))
    fireEvent.click(screen.getByText(/تجهيز طلبات GS1/))
    await waitFor(() => expect(api.codesPrepare).toHaveBeenCalledWith({ ids: [5], kind: 'gs1' }))
  })
})

describe('new catalog items', () => {
  it('offers to add catalog items that have no tax profile yet', async () => {
    api.codes.mockResolvedValue({ data: { summary: { catalog_without_profile: 12 }, rows: [] } })
    api.codeCandidates.mockResolvedValue({ data: [] })
    api.codesAddFromCatalog.mockResolvedValue({ data: { added: 12 } })
    show(<Candidates me={ME} />)
    fireEvent.click(await screen.findByText(/إضافة أصناف الكتالوج الجديدة \(12\)/))
    await waitFor(() => expect(api.codesAddFromCatalog).toHaveBeenCalled())
  })
})

describe('test-only branch mapping', () => {
  it('marks a branch test-only, and ends it with a reason', async () => {
    api.saveReceiptConfig.mockResolvedValue({ data: {} })
    const { unmount } = show(<TestMapping branch="170" row={{ test_env: '', has_chain_receipts: false }} me={ME} />)
    fireEvent.click(screen.getByText('جعله إعداداً تجريبياً فقط'))
    await waitFor(() => expect(api.saveReceiptConfig).toHaveBeenCalledWith({ branch: '170', test_only: true }))
    unmount()
    api.endTestMapping.mockResolvedValue({ data: {} })
    show(<TestMapping branch="170" row={{ test_env: 'preprod', has_chain_receipts: true }} me={ME} />)
    expect(screen.getByText(/إعداد تجريبي فقط \(preprod\)/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('سبب إنهاء الإعداد التجريبي'), { target: { value: 'انتهت التجربة' } })
    fireEvent.click(screen.getByText('إنهاء الإعداد التجريبي'))
    await waitFor(() => expect(api.endTestMapping).toHaveBeenCalledWith('170', 'انتهت التجربة'))
  })
})

describe('branch send start', () => {
  it('sets when the branch starts sending, with a reason', async () => {
    api.setSendFrom.mockResolvedValue({ data: { rechecked: 7 } })
    show(<SendFrom branch="150" row={{ send_from: null }} me={ME} />)
    fireEvent.change(screen.getByLabelText('بداية الإرسال'), { target: { value: '2026-11-14T08:00' } })
    fireEvent.change(screen.getByLabelText('سبب بداية الإرسال'), { target: { value: 'بدء التشغيل' } })
    fireEvent.click(screen.getByText('حفظ بداية الإرسال'))
    await waitFor(() => expect(api.setSendFrom).toHaveBeenCalledWith('150', expect.objectContaining({ reason: 'بدء التشغيل' })))
    expect(await screen.findByText(/أُعيد فحص 7/)).toBeTruthy()
  })
})

describe('ETA history progress', () => {
  it('shows both systems and refreshes one', async () => {
    const kind = { states: { planned: 2, requested: 1, loaded: 5, failed: 0, too_big: 0 }, windows: 8, rows: 1234,
      loaded_from: '2022-06-01', loaded_to: '2022-07-30', last_loaded_at: null, last_error: '' }
    api.historyProgress.mockResolvedValue({ data: { systems: [
      { system: 'preprod', label: 'التجريبية', why_not: '', documents: kind, receipts: kind },
      { system: 'production', label: 'الفعلية', why_not: 'قراءة سجل المنظومة production مغلقة', documents: kind, receipts: kind },
    ] } })
    api.historyRefresh.mockResolvedValue({ data: { started: true } })
    show(<HistoryProgress me={ME} />)
    expect(await screen.findByText(/قراءة سجل المنظومة production مغلقة/)).toBeTruthy()
    fireEvent.click(screen.getAllByText('تحديث الآن')[0])
    await waitFor(() => expect(api.historyRefresh).toHaveBeenCalledWith({ system: 'preprod' }))
  })
})

describe('ETA history tab', () => {
  const doc = { id: 7, uuid: 'U-7', internal_id: 'INV-7', doc_type: 'i', direction: 'sent', status: 'valid', issued_at: '2026-10-01T10:00:00Z',
    issuer_name: 'الرزيقى', receiver_name: 'شركة النور', receiver_id: '999888777', total_amount: '114.00000' }

  it('lists the live system first, filters, sorts and opens a document with its lines', async () => {
    api.historyDocuments.mockResolvedValue({ data: { count: 1, page: 1, pages: 1, total_amount: '114.00000', rows: [doc] } })
    api.historyDocument.mockResolvedValue({ data: { ...doc, lines: [{ internal_code: '60001', description: 'Panadol', item_code: 'EG-1', quantity: '2', unit_value: '50', net_total: '100', tax: '14', total: '114' }],
      validation: [{ name: 'Step-03', status: 'Valid', error: null }], detail_unavailable: '' } })
    show(<HistoryTab />)
    expect(await screen.findByText('INV-7')).toBeTruthy()
    expect(api.historyDocuments).toHaveBeenCalledWith(expect.objectContaining({ system: 'production', page: 1 }))
    fireEvent.change(screen.getByLabelText('الاتجاه'), { target: { value: 'received' } })
    await waitFor(() => expect(api.historyDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ direction: 'received' })))
    fireEvent.click(screen.getByText('INV-7'))
    expect(await screen.findByText('Panadol')).toBeTruthy()
    expect(screen.getByText(/Step-03: Valid/)).toBeTruthy()
  })

  it('switches to receipts of the test system with the device filter', async () => {
    api.historyDocuments.mockResolvedValue({ data: { count: 0, page: 1, pages: 1, total_amount: null, rows: [] } })
    api.historyReceipts.mockResolvedValue({ data: { count: 1, page: 1, pages: 1, total_amount: '10.00000', devices: ['POS-A'],
      rows: [{ id: 3, uuid: 'R', receipt_number: '900', pos_serial: 'POS-A', issued_at: '2026-11-01T10:00:00Z', status: 'valid', total_amount: '10.00000', submitter: 'Invoicer' }] } })
    show(<HistoryTab />)
    fireEvent.click(await screen.findByText('التجريبية'))
    fireEvent.click(screen.getByText('الإيصالات'))
    expect(await screen.findByText('900')).toBeTruthy()
    expect(api.historyReceipts).toHaveBeenLastCalledWith(expect.objectContaining({ system: 'preprod' }))
    fireEvent.change(screen.getByLabelText('الجهاز'), { target: { value: 'POS-A' } })
    await waitFor(() => expect(api.historyReceipts).toHaveBeenLastCalledWith(expect.objectContaining({ device: 'POS-A' })))
  })
})

describe('SOFTECH ↔ ETA reconciliation', () => {
  it('shows outcomes per branch and month and drills into the missing ones', async () => {
    api.historyDocuments.mockResolvedValue({ data: { count: 0, page: 1, pages: 1, total_amount: null, rows: [] } })
    api.reconSummary.mockResolvedValue({ data: { last_run_at: null, last_error: '', outcomes: [], devices: [{ pos_serial: '7M7HMM1', branch: '150', first_day: '2025-03-05', source: 'auto', sample: '20/20' }],
      rows: [{ branch: '150', month: '2026-11', matched: 120, amount_differs: 0, missing_at_eta: 3, eta_only: 0, not_valid: 0, duplicate: 0, by_invoice: 2, softech_total: '1000.00', eta_total: '990.00' }] } })
    api.reconLines.mockResolvedValue({ data: { count: 1, page: 1, pages: 1, rows: [{ id: 1, day: '2026-11-05', doccode: '115', docnumber: '716999', softech_total: '50.00', eta_total: null, eta_status: '', eta_count: 0 }] } })
    show(<HistoryTab me={ME} />)
    fireEvent.click(await screen.findByText('المطابقة'))
    fireEvent.click(await screen.findByText('3'))
    expect(await screen.findByText('716999')).toBeTruthy()
    expect(api.reconLines).toHaveBeenCalledWith(expect.objectContaining({ system: 'production', branch: '150', month: '2026-11', outcome: 'missing_at_eta' }))
  })

  it('shows why a sale is missing and ranks the items with no ETA code', async () => {
    api.historyDocuments.mockResolvedValue({ data: { count: 0, page: 1, pages: 1, total_amount: null, rows: [] } })
    api.reconSummary.mockResolvedValue({ data: { last_run_at: null, last_error: '', outcomes: [], devices: [],
      rows: [{ branch: '150', month: '2026-11', matched: 120, amount_differs: 0, missing_at_eta: 3, eta_only: 0, not_valid: 0, duplicate: 0, by_invoice: 0,
        softech_total: '1000.00', eta_total: '990.00', reasons: { all_uncoded: 2, till_silent: 1, eta_other_day: 4 } }] } })
    api.reconLines.mockResolvedValue({ data: { count: 1, page: 1, pages: 1, rows: [{ id: 1, day: '2026-11-05', doccode: '115', docnumber: '716999',
      softech_total: '50.00', eta_total: null, eta_status: '', eta_count: 0, reason: 'all_uncoded', uncoded_total: '50.00' }] } })
    api.reconUncoded.mockResolvedValue({ data: { count: 1, page: 1, pages: 1, total_value: '879.00',
      rows: [{ itemcode: '2', name: 'D.L.V.', docs: 79, qty: '879.00', value: '879.00', last_day: '2026-11-14', coding_status: 'missing', coded_now: false, request_status: '' }] } })
    show(<HistoryTab me={ME} />)
    fireEvent.click(await screen.findByText('المطابقة'))
    expect(await screen.findByText('منها 2 بلا كود')).toBeTruthy()
    expect(screen.getByText('منها 1 توقف الإرسال')).toBeTruthy()
    expect(screen.getByText('منها 4 في يوم مجاور')).toBeTruthy()
    fireEvent.click(await screen.findByText('3'))
    expect(await screen.findByRole('cell', { name: 'كل أصنافه بلا كود مصلحة' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('السبب'), { target: { value: 'all_uncoded' } })
    await waitFor(() => expect(api.reconLines).toHaveBeenLastCalledWith(expect.objectContaining({ reason: 'all_uncoded', outcome: 'missing_at_eta' })))
    fireEvent.click(screen.getByText(/عرض الأصناف التي بلا كود مصلحة/))
    expect(await screen.findByText('D.L.V.')).toBeTruthy()
    expect(api.reconUncoded).toHaveBeenCalledWith(expect.objectContaining({ system: 'production', ordering: '-value', open: '1' }))
  })

  it('lists the missing sales with no known cause, biggest first, with their channel', async () => {
    api.historyDocuments.mockResolvedValue({ data: { count: 0, page: 1, pages: 1, total_amount: null, rows: [] } })
    api.reconSummary.mockResolvedValue({ data: { last_run_at: null, last_error: '', outcomes: [], devices: [],
      channels: [{ code: '90', label: 'عميل Delivery' }],
      rows: [{ branch: '150', month: '2026-11', matched: 120, amount_differs: 0, missing_at_eta: 9, eta_only: 0, not_valid: 0, duplicate: 0, by_invoice: 0,
        softech_total: '1000.00', eta_total: '990.00', reasons: { no_channel_rule: 5 } }] } })
    api.reconLines.mockResolvedValue({ data: { count: 1, page: 1, pages: 1, total: '80002.00', rows: [{ id: 7, branch: '150', day: '2026-11-05', doccode: '115',
      docnumber: '935521', channel: '90', channel_label: 'عميل Delivery', softech_total: '80002.00', eta_total: null, reason: '' }] } })
    show(<HistoryTab me={ME} />)
    fireEvent.click(await screen.findByText('المطابقة'))
    expect(await screen.findByText('منها 5 قناة بلا قاعدة')).toBeTruthy()
    fireEvent.click(screen.getByText(/عرض المبيعات الناقصة بلا سبب معروف/))
    expect(await screen.findByText('90 · عميل Delivery')).toBeTruthy()
    expect(api.reconLines).toHaveBeenCalledWith(expect.objectContaining({ system: 'production', outcome: 'missing_at_eta', reason: 'none', ordering: '-softech_total' }))
    fireEvent.change(screen.getByLabelText('القناة'), { target: { value: '90' } })
    await waitFor(() => expect(api.reconLines).toHaveBeenLastCalledWith(expect.objectContaining({ channel: '90', reason: 'none' })))
  })
})

describe('production coding queue', () => {
  const qrow = (itemcode, value, extra = {}) => ({
    id: Number(itemcode), itemcode, name: `Item ${itemcode}`, name_ar: '', value, docs: 3, last_day: '2026-11-14',
    premark: 'code', premark_reason: 'official', note: 'اشتُري من موزع أو مخزن أو مصنع', sources: { OFFICIAL_DISTRIBUTOR: 12 },
    vat_rate: '0', vat_flagged: false, vat_why: 'catalog', eta_last_status: '', decision: null, decided_by: '', decided_at: null,
    brick: '10000673', brick_name: 'أدوية', brick_source: 'medicine', brick_confidence: '', brick_reason: '', brick_second: '',
    brick_second_name: '', own_brick: '', own_brick_name: '', brick_confirmed: false, ...extra,
  })
  const rows = [
    qrow('900', '5000.00'),
    qrow('901', '1200.00', { premark: 'keep_out', premark_reason: 'unofficial_only', note: 'لم يُشترَ من موزع أو مخزن أو مصنع' }),
    qrow('902', '300.00', { vat_flagged: true, vat_why: 'zero_for_type' }),
  ]

  beforeEach(() => {
    api.codingQueue.mockResolvedValue({ data: { count: 3, page: 1, pages: 1, total_value: '6500.00', catalog_without_profile: false, rows } })
    api.etaHolds.mockResolvedValue({ data: { on_eta_not_in_sheet: [{ code_type: 'EGS', item_code: 'EG-1-77', code_name: 'Old item', status: 'Active', itemcode: '77' }],
      in_sheet_not_on_eta: ['55'], counts: { usages: 10, active: 8, matched: 7, unmatched: 1, sheet: 9 } } })
    api.codingDecide.mockResolvedValue({ data: { decided: ['901'], skipped: [] } })
  })

  it('renders the rows biggest sales first, as the server sends them', async () => {
    show(<QueueTab me={ME} />)
    await screen.findByText('Item 900')
    const grid = screen.getByTestId('coding-queue-grid')
    const names = within(grid).getAllByText(/^Item 9\d\d$/).map(e => e.textContent)
    expect(names).toEqual(['Item 900', 'Item 901', 'Item 902'])
    expect(api.codingQueue).toHaveBeenCalledWith(expect.objectContaining({ ordering: '-value', page: 1 }))
  })

  it('disables the bulk accept while the selection holds a row whose VAT needs checking', async () => {
    show(<QueueTab me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 900'))
    expect(screen.getByRole('button', { name: /قبول المقترح/ }).disabled).toBe(false)
    fireEvent.click(screen.getByLabelText('اختيار 902'))
    expect(screen.getByRole('button', { name: /قبول المقترح/ }).disabled).toBe(true)
  })

  it('K on the selected row keeps it out of coding', async () => {
    show(<QueueTab me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 901'))
    fireEvent.keyDown(screen.getByTestId('coding-queue-grid'), { code: 'KeyK', key: 'k' })
    await waitFor(() => expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['901'], decision: 'keep_out' }))
  })

  it('decides a flagged row on its own with the rate chosen for it', async () => {
    show(<QueueTab me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 902'))
    const code = screen.getAllByRole('button', { name: 'كوّد' })[0]
    expect(code.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('نسبة ضريبة 902'), { target: { value: '14' } })
    fireEvent.keyDown(screen.getByTestId('coding-queue-grid'), { code: 'KeyC', key: 'c' })
    await waitFor(() => expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['902'], decision: 'code', vat_rate: '14', brick: '10000673' }))
  })

  it('Enter accepts each selected row by its own pre-mark', async () => {
    show(<QueueTab me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 900'))
    fireEvent.click(screen.getByLabelText('اختيار 901'))
    fireEvent.mouseDown(screen.getByText('Item 900'))
    fireEvent.keyDown(screen.getByTestId('coding-queue-grid'), { code: 'Enter', key: 'Enter' })
    await waitFor(() => expect(api.codingDecide).toHaveBeenCalledTimes(2))
    expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['900'], decision: 'code', vat_rate: '0', brick: '10000673' })
    expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['901'], decision: 'keep_out' })
  })

  it('leaves Enter on a focused row button to that button, not to the active row', async () => {
    show(<QueueTab me={ME} />)
    fireEvent.mouseDown(await screen.findByText('Item 900'))
    const row901 = screen.getByText('Item 901').closest('tr')
    const keepOut = within(row901).getByRole('button', { name: 'استبعد' })
    keepOut.focus()
    expect(fireEvent.keyDown(keepOut, { code: 'Enter', key: 'Enter' })).toBe(true)   // not prevented: the button clicks
    expect(fireEvent.keyDown(keepOut, { code: 'KeyK', key: 'k' })).toBe(true)
    expect(api.codingDecide).not.toHaveBeenCalled()
    fireEvent.click(keepOut)
    await waitFor(() => expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['901'], decision: 'keep_out' }))
  })

  it('reloads the queue when a decision is refused', async () => {
    api.codingDecide.mockRejectedValue({ response: { status: 409, data: { detail: 'للصنف قرار سابق — أعد فتحه أولاً' } } })
    show(<QueueTab me={ME} />)
    const row900 = (await screen.findByText('Item 900')).closest('tr')
    const before = api.codingQueue.mock.calls.length
    fireEvent.click(within(row900).getByRole('button', { name: 'استبعد' }))
    expect(await screen.findByText('للصنف قرار سابق — أعد فتحه أولاً')).toBeTruthy()
    await waitFor(() => expect(api.codingQueue.mock.calls.length).toBeGreaterThan(before))
  })

  it('reports a refused group and still saves the other on Enter', async () => {
    api.codingDecide.mockImplementation(body => (body.decision === 'keep_out'
      ? Promise.reject({ response: { status: 409, data: { detail: 'للصنف قرار سابق' } } })
      : Promise.resolve({ data: { decided: ['900'], skipped: [] } })))
    show(<QueueTab me={ME} />)
    fireEvent.click(await screen.findByLabelText('اختيار 900'))
    fireEvent.click(screen.getByLabelText('اختيار 901'))
    fireEvent.mouseDown(screen.getByText('Item 900'))
    fireEvent.keyDown(screen.getByTestId('coding-queue-grid'), { code: 'Enter', key: 'Enter' })
    expect(await screen.findByText(/قُرر 1 — تُرك 1: 901 \(للصنف قرار سابق\)/)).toBeTruthy()
  })

  it('hides the decide buttons without approve', async () => {
    show(<QueueTab me={{ ...ME, can_approve: false }} />)
    await screen.findByText('Item 900')
    expect(screen.queryByRole('button', { name: /قبول المقترح/ })).toBeNull()
    expect(screen.queryByLabelText('اختيار 900')).toBeNull()
  })

  describe('GPC brick column', () => {
    const aiRow = qrow('903', '250.00', { brick: '10000777', brick_name: 'كريمات البشرة', brick_source: 'ai', brick_confidence: 'medium',
      brick_reason: '<b>كريم</b> للبشرة', own_brick: '10000999', own_brick_name: 'مستحضرات' })
    const s1Row = qrow('904', '200.00', { decision: 'code', decided_by: 'admin', brick: '', brick_name: '', brick_source: '', brick_confirmed: false })
    beforeEach(() => {
      api.codingQueue.mockResolvedValue({ data: { count: 5, page: 1, pages: 1, total_value: '6950.00', catalog_without_profile: false,
        rows: [...rows, aiRow, s1Row] } })
      api.codeGpc.mockImplementation(({ q } = {}) => Promise.resolve({ data: { loaded: true,
        rows: q ? [{ code: '10002222', name_ar: 'كريمات', used: 0 }, { code: '10003333', name_ar: 'لوشن', used: 0 }] : [] } }))
    })

    it('labels where each brick came from, the AI confidence and reason as text, and a missing brick', async () => {
      show(<QueueTab me={ME} />)
      const row903 = (await screen.findByText('Item 903')).closest('tr')
      expect(within(row903).getByText('اقتراح ذكي · متوسطة')).toBeTruthy()
      expect(within(row903).getByText('<b>كريم</b> للبشرة')).toBeTruthy()      // plain text, never HTML
      expect(row903.querySelector('b')).toBeNull()
      expect(within(row903).getByText(/في ملف الشركة:/).textContent).toContain('10000999')
      const row900 = screen.getByText('Item 900').closest('tr')
      expect(within(row900).getByText('دواء')).toBeTruthy()
      const row904 = screen.getByText('Item 904').closest('tr')
      expect(within(row904).getByText('تحتاج فئة')).toBeTruthy()
    })

    it('disables bulk accept and code while the selection holds an AI suggestion that is not high-confidence', async () => {
      show(<QueueTab me={ME} />)
      fireEvent.click(await screen.findByLabelText('اختيار 900'))
      fireEvent.click(screen.getByLabelText('اختيار 903'))
      const accept = screen.getByRole('button', { name: /قبول المقترح/ })
      expect(accept.disabled).toBe(true)
      expect(accept.title).toBe('في المختار صنف فئته اقتراح ذكي يحتاج تأكيداً — قرره وحده')
    })

    it('a single code sends the brick shown on the row, so the server cannot save a different one', async () => {
      show(<QueueTab me={ME} />)
      const row903 = (await screen.findByText('Item 903')).closest('tr')
      fireEvent.click(within(row903).getByRole('button', { name: 'كوّد' }))
      await waitFor(() => expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['903'], decision: 'code', vat_rate: '0', brick: '10000777' }))
    })

    it('keeps the AI brick guard on Enter when only one of the ticked rows is to be coded', async () => {
      show(<QueueTab me={ME} />)
      fireEvent.click(await screen.findByLabelText('اختيار 901'))    // pre-marked keep_out
      fireEvent.click(screen.getByLabelText('اختيار 903'))           // pre-marked code, medium AI brick
      const accept = screen.getByRole('button', { name: /قبول المقترح/ })
      expect(accept.disabled).toBe(true)
      expect(accept.title).toBe('في المختار صنف فئته اقتراح ذكي يحتاج تأكيداً — قرره وحده')
      fireEvent.mouseDown(screen.getByText('Item 903'))
      fireEvent.keyDown(screen.getByTestId('coding-queue-grid'), { code: 'Enter', key: 'Enter' })
      expect(api.codingDecide).not.toHaveBeenCalled()
    })

    it('says when asking again stopped because the AI provider does not answer', async () => {
      api.codingSuggest.mockResolvedValue({ data: { asked: [{ itemcode: '903', brick: '', error: 'لم يرد مزود الذكاء الاصطناعي' }],
        skipped: [], stopped: 'provider' } })
      show(<QueueTab me={ME} />)
      fireEvent.click(await screen.findByLabelText('اختيار 903'))
      fireEvent.click(screen.getByRole('button', { name: 'اقترح مرة أخرى' }))
      expect(await screen.findByText(/توقف السؤال: مزود الذكاء الاصطناعي لا يرد/)).toBeTruthy()
    })

    it('picks a brick with the keyboard for an undecided row and sends it with the decision', async () => {
      show(<QueueTab me={ME} />)
      const row903 = (await screen.findByText('Item 903')).closest('tr')
      fireEvent.click(within(row903).getByRole('button', { name: 'اختيار فئة 903' }))
      const box = screen.getByLabelText('بحث فئة 903')
      fireEvent.change(box, { target: { value: 'كريم' } })
      await waitFor(() => expect(api.codeGpc).toHaveBeenCalledWith({ q: 'كريم' }))
      await screen.findByText('لوشن')
      // keys typed in the picker never reach the grid shortcuts
      expect(fireEvent.keyDown(box, { code: 'KeyK', key: 'k' })).toBe(true)
      fireEvent.keyDown(box, { code: 'ArrowDown', key: 'ArrowDown' })
      fireEvent.keyDown(box, { code: 'Enter', key: 'Enter' })
      expect(api.codingDecide).not.toHaveBeenCalled()
      expect(within(row903).getByText('اختيار يدوي')).toBeTruthy()
      fireEvent.click(within(row903).getByRole('button', { name: 'كوّد' }))
      await waitFor(() => expect(api.codingDecide).toHaveBeenCalledWith({ itemcodes: ['903'], decision: 'code', vat_rate: '0', brick: '10003333' }))
    })

    it('ignores Enter while the search results are still for an earlier text', async () => {
      show(<QueueTab me={ME} />)
      const row903 = (await screen.findByText('Item 903')).closest('tr')
      fireEvent.click(within(row903).getByRole('button', { name: 'اختيار فئة 903' }))
      const box = screen.getByLabelText('بحث فئة 903')
      fireEvent.change(box, { target: { value: 'كريم' } })
      await screen.findByText('لوشن')
      api.codeGpc.mockImplementation(() => Promise.resolve({ data: { loaded: true, rows: [{ code: '10004444', name_ar: 'صابون', used: 0 }] } }))
      fireEvent.change(box, { target: { value: 'صابون' } })
      fireEvent.keyDown(box, { code: 'Enter', key: 'Enter' })     // still showing the «كريم» list: nothing picked
      expect(within(row903).queryByText('اختيار يدوي')).toBeNull()
      await screen.findByText('صابون')
      fireEvent.keyDown(box, { code: 'Enter', key: 'Enter' })
      expect(within(row903).getByText('اختيار يدوي')).toBeTruthy()
      expect(within(row903).getByText('10004444')).toBeTruthy()
    })

    it('sets the brick of an item already decided "code"', async () => {
      api.codingSetBrick.mockResolvedValue({ data: { itemcode: '904', brick: '10002222', brick_source: 'person', brick_name: 'كريمات' } })
      show(<QueueTab me={ME} />)
      const row904 = (await screen.findByText('Item 904')).closest('tr')
      fireEvent.click(within(row904).getByRole('button', { name: 'اختيار فئة 904' }))
      fireEvent.change(screen.getByLabelText('بحث فئة 904'), { target: { value: '1000' } })
      fireEvent.click(await screen.findByText('كريمات'))
      await waitFor(() => expect(api.codingSetBrick).toHaveBeenCalledWith({ itemcode: '904', brick: '10002222' }))
    })

    it('asks again for the selection and shows the server refusal when the switch is off', async () => {
      api.codingSuggest.mockRejectedValue({ response: { status: 400, data: { detail: 'اقتراح الفئة بالذكاء الاصطناعي متوقف — فعّله من الإعدادات أولاً' } } })
      show(<QueueTab me={ME} />)
      fireEvent.click(await screen.findByLabelText('اختيار 903'))
      fireEvent.click(screen.getByRole('button', { name: 'اقترح مرة أخرى' }))
      await waitFor(() => expect(api.codingSuggest).toHaveBeenCalledWith({ itemcodes: ['903'] }))
      expect(await screen.findByText('اقتراح الفئة بالذكاء الاصطناعي متوقف — فعّله من الإعدادات أولاً')).toBeTruthy()
    })
  })

  it('shows what ETA production holds that our sheet lacks', async () => {
    show(<QueueTab me={ME} />)
    fireEvent.click(await screen.findByRole('button', { name: /عرض ما لدى المصلحة/ }))
    expect(await screen.findByText('EG-1-77')).toBeTruthy()
  })
})

describe('Invoicer codes file panel', () => {
  const version = (extra = {}) => ({ number: 2, built_at: '2026-11-17T10:00:00Z', source: 'build', built_by: 'محاسب', note: '',
    coded_rows: 36010, total_rows: 36500, added: 3, coded: 2, skipped: [{ itemcode: '7', why: 'x' }, { itemcode: '8', why: 'y' }], size: 15000000, has_file: true, ...extra })
  const sheet = (extra = {}) => ({ data: { versions: [version(), version({ number: 1, source: 'seed', added: 0, coded: 0 })],
    build: { state: 'idle' }, pending: { ready: 4, skipped: [{ itemcode: '500', why: 'لا توجد فئة GPC للصنف' }] }, can_build: true, ...extra } })

  it('shows the latest version, its counts, the reminder and the skipped reasons on demand', async () => {
    api.egsSheet.mockResolvedValue(sheet())
    show(<EgsSheetPanel />)
    expect(await screen.findByText(/النسخة 2/)).toBeTruthy()
    expect(screen.getByText('36,010')).toBeTruthy()
    expect(screen.getByText(REMINDER)).toBeTruthy()
    expect(REMINDER).toBe('بعد استبدال الملف في D:\\invoicer_mini أغلق Excel — الملف المفتوح يوقف رفع الإيصالات')
    expect(screen.getByText('القيم في الأعمدة L–P مكتوبة كأرقام وليست معادلات.')).toBeTruthy()
    expect(screen.queryByText(/لا توجد فئة GPC للصنف/)).toBeNull()
    expect(screen.getByText('تُرك في هذه النسخة').querySelector('b').textContent).toBe('2')
    expect(screen.getByRole('button', { name: /متروك الآن/ }).textContent).toContain('1')
    fireEvent.click(screen.getByRole('button', { name: /متروك الآن/ }))
    expect(screen.getByText(/لا توجد فئة GPC للصنف/)).toBeTruthy()
  })

  it('starts a build and downloads the full file of the latest version', async () => {
    api.egsSheet.mockResolvedValue(sheet())
    api.egsSheetBuild.mockResolvedValue({ data: { started: true } })
    api.egsSheetDownload.mockResolvedValue({ data: new Blob(['x']) })
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    show(<EgsSheetPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'بناء نسخة جديدة' }))
    await waitFor(() => expect(api.egsSheetBuild).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'تنزيل الملف كاملاً' }))
    await waitFor(() => expect(api.egsSheetDownload).toHaveBeenCalledWith(2, 'full'))
    fireEvent.click(screen.getByRole('button', { name: 'الصفوف الجديدة فقط' }))
    await waitFor(() => expect(api.egsSheetDownload).toHaveBeenCalledWith(2, 'new'))
  })

  it('shows a refused build with its reasons, such as a duplicate itemcode in the held sheet', async () => {
    api.egsSheet.mockResolvedValue(sheet({ build: { state: 'refused', refused: ['كود صنف مكرر في العمود J: 300'], finished_at: '2026-11-17T10:02:00Z' } }))
    show(<EgsSheetPanel />)
    const box = await screen.findByTestId('egs-sheet-refused')
    expect(within(box).getByText('كود صنف مكرر في العمود J: 300')).toBeTruthy()
  })

  it('polls while a build runs and disables the build button', async () => {
    api.egsSheet.mockResolvedValue(sheet({ build: { state: 'running', started_at: '2026-11-17T10:00:00Z' } }))
    show(<EgsSheetPanel />)
    expect((await screen.findByRole('button', { name: 'جارٍ البناء…' })).disabled).toBe(true)
    await waitFor(() => expect(api.egsSheet.mock.calls.length).toBeGreaterThan(1), { timeout: 6000 })
  }, 10000)

  it('offers no build or download without the approve permission', async () => {
    api.egsSheet.mockResolvedValue(sheet({ can_build: false }))
    show(<EgsSheetPanel />)
    await screen.findByText(/النسخة 2/)
    expect(screen.queryByRole('button', { name: 'بناء نسخة جديدة' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'تنزيل الملف كاملاً' })).toBeNull()
  })
})


describe('seal PC agent part of the Invoicer codes file panel', () => {
  const codes = items => ({ count: items.length, items })
  const state = (extra = {}) => ({ data: {
    switch: false, agent: { at: '2026-11-18T01:00:00Z', version: 2, min_version: 2, outdated: false }, live: null,
    last_fetch: null, held: null, jobs: [], busy: false, has_version: true, can_approve: true, ...extra } })
  const fetchRow = (extra = {}) => ({ id: 5, finished_at: '2026-11-18T03:00:00Z', live: { coded_rows: 36011, total_rows: 36500 },
    latest: 2, matches_version: null, hand_edits: true, current: true, has_copy: true, importable: true, import_removes: 0,
    added_vs_latest: codes(['900']), removed_vs_latest: codes([]), ...extra })

  it('shows the agent, the switch off as preview only, and asks for a read and a preview', async () => {
    api.egsAgent.mockResolvedValue(state())
    api.egsAgentFetch.mockResolvedValue({ data: { job: { id: 1 } } })
    api.egsAgentWrite.mockResolvedValue({ data: { job: { id: 2, mode: 'preview', status: 'pending' } } })
    show(<EgsAgentPart />)
    expect(await screen.findByText(SWITCH_OFF)).toBeTruthy()
    expect(screen.getByText('إصدار البرنامج').querySelector('b').textContent).toBe('2')
    expect(screen.queryByText(OUTDATED)).toBeNull()
    expect(screen.queryByRole('button', { name: 'اكتب الآن' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'اقرأ الملف الحالي' }))
    await waitFor(() => expect(api.egsAgentFetch).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'معاينة الآن' }))
    await waitFor(() => expect(api.egsAgentWrite).toHaveBeenCalledWith({}))
    expect(await screen.findByText('طُلبت المعاينة — لا يُكتب شيء في الملف')).toBeTruthy()
  })

  it('says «اكتب الآن» with the switch on and reports nothing to write', async () => {
    api.egsAgent.mockResolvedValue(state({ switch: true }))
    api.egsAgentWrite.mockResolvedValue({ data: { job: null } })
    show(<EgsAgentPart />)
    fireEvent.click(await screen.findByRole('button', { name: 'اكتب الآن' }))
    expect(await screen.findByText('الملف الحالي هو آخر نسخة — لا شيء يُكتب')).toBeTruthy()
  })

  it('warns when the seal PC runs an old agent', async () => {
    api.egsAgent.mockResolvedValue(state({ agent: { at: '2026-11-18T01:00:00Z', version: 0, outdated: true } }))
    show(<EgsAgentPart />)
    expect(await screen.findByText(OUTDATED)).toBeTruthy()
    expect(OUTDATED).toContain('حدّث برنامج الختم على جهاز الختم')
  })

  it('lists the differences of the last read on demand', async () => {
    api.egsAgent.mockResolvedValue(state({ last_fetch: fetchRow({ hand_edits: false, matches_version: 2, importable: false }) }))
    show(<EgsAgentPart />)
    expect(await screen.findByText('مطابق للنسخة 2')).toBeTruthy()
    expect(screen.queryByText('900')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /في الملف الحالي وليس في النسخة 2/ }))
    expect(screen.getByText('900')).toBeTruthy()
    expect(screen.queryByTestId('egs-agent-held')).toBeNull()
  })

  it('a hold offers the import, and the removals checkbox only when the import drops coded items', async () => {
    const held = { id: 9, version: 2, added: codes(['900']), removed: codes(['0200']) }
    api.egsAgent.mockResolvedValue(state({ last_fetch: fetchRow({ import_removes: 1 }), held }))
    api.egsAgentImport.mockResolvedValue({ data: { version: { number: 3 } } })
    show(<EgsAgentPart />)
    const box = await screen.findByTestId('egs-agent-held')
    expect(within(box).getByText(/الكتابة موقوفة/).textContent).toContain('+1 / −1')
    const importBtn = within(box).getByRole('button', { name: 'استورد التعديلات' })
    expect(importBtn.disabled).toBe(true)
    fireEvent.click(within(box).getByRole('checkbox'))
    fireEvent.click(importBtn)
    await waitFor(() => expect(api.egsAgentImport).toHaveBeenCalledWith({ job: 5, allow_removals: true }))
  })

  it('no removals: no checkbox, the import goes at once', async () => {
    api.egsAgent.mockResolvedValue(state({ last_fetch: fetchRow(), held: { id: 9, version: 2, added: codes(['900']), removed: codes([]) } }))
    api.egsAgentImport.mockResolvedValue({ data: { version: { number: 3 } } })
    show(<EgsAgentPart />)
    const box = await screen.findByTestId('egs-agent-held')
    expect(within(box).queryByRole('checkbox')).toBeNull()
    fireEvent.click(within(box).getByRole('button', { name: 'استورد التعديلات' }))
    await waitFor(() => expect(api.egsAgentImport).toHaveBeenCalledWith({ job: 5, allow_removals: false }))
  })

  it('writing over hand edits asks for a reason inline, then sends override with it', async () => {
    api.egsAgent.mockResolvedValue(state({ last_fetch: fetchRow(), held: { id: 9, version: 2, added: codes(['900']), removed: codes([]) } }))
    api.egsAgentWrite.mockResolvedValue({ data: { job: { id: 3, mode: 'preview', status: 'pending' } } })
    show(<EgsAgentPart />)
    fireEvent.click(await screen.findByRole('button', { name: 'اكتب فوقها' }))
    const confirm = screen.getByRole('button', { name: 'تأكيد المعاينة فوقها' })
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('سبب الكتابة فوق التعديلات'), { target: { value: 'المالك طلب' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(api.egsAgentWrite).toHaveBeenCalledWith({ override: true, note: 'المالك طلب' }))
  })

  it('offers no buttons without the approve permission', async () => {
    api.egsAgent.mockResolvedValue(state({ can_approve: false, last_fetch: fetchRow(), held: { id: 9, version: 2, added: codes(['900']), removed: codes([]) } }))
    show(<EgsAgentPart />)
    await screen.findByTestId('egs-agent-held')
    for (const name of ['اقرأ الملف الحالي', 'معاينة الآن', 'استورد التعديلات', 'اكتب فوقها']) {
      expect(screen.queryByRole('button', { name })).toBeNull()
    }
  })

  it('shows recent jobs with their outcome and polls only while one waits', async () => {
    const jobs = [
      { id: 2, kind: 'egs_write', mode: 'preview', status: 'busy', override: false, created_at: '2026-11-18T03:05:00Z', error: 'the sheet stayed in use', result: {} },
      { id: 1, kind: 'egs_fetch', mode: 'preview', status: 'pending', override: false, created_at: '2026-11-18T03:00:00Z', error: '', result: {} },
    ]
    api.egsAgent.mockResolvedValue(state({ jobs, busy: true }))
    show(<EgsAgentPart />)
    const grid = await screen.findByLabelText('مهام جهاز الختم')
    expect(within(grid).getByText('the sheet stayed in use')).toBeTruthy()
    expect(within(grid).getByText('الملف مفتوح في المحصّل')).toBeTruthy()
    await waitFor(() => expect(api.egsAgent.mock.calls.length).toBeGreaterThan(1), { timeout: 6000 })
  }, 10000)

  it('does not poll when no job waits', async () => {
    api.egsAgent.mockResolvedValue(state())
    show(<EgsAgentPart />)
    await screen.findByText(SWITCH_OFF)
    await new Promise(r => setTimeout(r, 4500))
    expect(api.egsAgent.mock.calls.length).toBe(1)
  }, 8000)

  it('words each job outcome', () => {
    expect(jobResult({ kind: 'egs_write', status: 'done', result: { preview: true, would_write: true } })).toBe('معاينة: كان سيُكتب')
    expect(jobResult({ kind: 'egs_write', status: 'done', result: { written: true, backup: 'b.xlsx' } })).toBe('كُتب الملف · نسخة احتياطية b.xlsx')
    expect(jobResult({ kind: 'egs_write', status: 'held', result: { added: 1, removed: 0 } })).toBe('+1 / −0 عن آخر نسخة')
    expect(jobResult({ kind: 'egs_fetch', status: 'done', result: { coded_rows: 5, total_rows: 9, matches_version: 2 } })).toBe('مكوّد 5 من 9 · = النسخة 2')
  })
})
