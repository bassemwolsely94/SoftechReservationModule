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
  saveReceiptConfig: vi.fn(),
}))

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
