// The owner's display rules for the review screen: the server's numbers are shown as they are, the
// "all lines" switch is only for approvers and only changes the query, and live sending shows as off.
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
}))

vi.mock('../../api/client', () => ({
  taxInvoicingApi: api,
  branchesApi: { list: vi.fn(() => Promise.resolve({ data: [{ softech_branch_id: '170', name_ar: 'فرع الجيش' }] })) },
}))

const { default: DocumentDetail } = await import('./DocumentDetail')
const { default: PrintTab } = await import('./PrintTab')
const { default: ImportTab, buildOptions } = await import('./ImportTab')
const { default: ItemsTab } = await import('./ItemsTab')

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

const ME = { can_create: true, can_edit: true, can_approve: true, can_view_all_lines: true, can_finalize: true, submit_enabled: false }

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
