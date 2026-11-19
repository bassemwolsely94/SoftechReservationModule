/**
 * What ETA holds for us (the history mirror), per ETA system. Display only: the server filters, sorts, pages,
 * masks personal IDs, asks ETA for a document's lines and official PDF, and audits PDFs and exports.
 */
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { exportJobsApi, taxInvoicingApi } from '../../api/client'
import useExportJob from '../../hooks/useExportJob'
import ExportJobStatus from '../../components/ExportJobStatus'
import SortTh from '../../components/SortTh'
import ReconSection from './ReconSection'
import useServerSort from '../../hooks/useServerSort'
import { ActionMsg, Badge, Btn, Failed, Field, fmt, fmtInt, fmtTime, INPUT, Loading, Notice, Section, useAction } from './ui'

const SYSTEMS = [['production', 'الفعلية'], ['preprod', 'التجريبية']]
const KINDS = [['documents', 'الفواتير والإشعارات'], ['receipts', 'الإيصالات'], ['recon', 'المطابقة']]
const DOC_TYPES = { i: 'فاتورة', c: 'إشعار دائن', d: 'إشعار مدين' }
const STATUS = { valid: 'مقبول', invalid: 'غير صالح', rejected: 'مرفوض', cancelled: 'ملغى', submitted: 'قيد المراجعة' }
const TONE = { valid: 'bg-emerald-50 text-emerald-700 border-emerald-200', cancelled: 'bg-gray-100 text-gray-600 border-gray-200',
  rejected: 'bg-red-50 text-red-700 border-red-200', invalid: 'bg-red-50 text-red-700 border-red-200' }
const DOC_SORT = ['issued_at', 'total_amount', 'status', 'internal_id', 'receiver_name', 'issuer_name', 'doc_type']
const RECEIPT_SORT = ['issued_at', 'total_amount', 'status', 'receipt_number', 'pos_serial']
const TH = 'px-2 py-1.5 text-right text-xs font-semibold text-gray-500 whitespace-nowrap'

function save(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function Lines({ lines }) {
  if (!lines) return null
  if (!lines.length) return <div className="text-xs text-gray-500">لا توجد بنود في رد المصلحة</div>
  return (
    <table className="w-full text-xs">
      <thead><tr>{['الكود', 'البيان', 'كود المصلحة', 'الكمية', 'سعر الوحدة', 'الصافي', 'الضريبة', 'الإجمالي'].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
      <tbody>
        {lines.map((l, i) => (
          <tr key={i} className="border-t border-gray-100">
            <td className="px-2 py-1">{l.internal_code || '—'}</td>
            <td className="px-2 py-1 max-w-[260px] truncate" title={l.description}>{l.description || '—'}</td>
            <td className="px-2 py-1 font-mono" dir="ltr">{l.item_code || '—'}</td>
            <td className="px-2 py-1">{l.quantity ?? '—'}</td>
            <td className="px-2 py-1">{fmt(l.unit_value)}</td>
            <td className="px-2 py-1">{fmt(l.net_total)}</td>
            <td className="px-2 py-1">{fmt(l.tax)}</td>
            <td className="px-2 py-1 font-bold">{fmt(l.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** One document or receipt as ETA holds it: its lines (asked from ETA once), ETA's checks, the official PDF. */
export function HistoryDetail({ kind, id }) {
  const act = useAction()
  const q = useQuery({
    queryKey: ['tax-invoicing', 'history-detail', kind, id],
    queryFn: () => (kind === 'documents' ? taxInvoicingApi.historyDocument(id) : taxInvoicingApi.historyReceipt(id)).then(r => r.data),
  })
  if (q.isLoading) return <Loading />
  if (q.error) return <Failed error={q.error} />
  const d = q.data
  return (
    <div className="space-y-2" data-tour="tax-invoicing-main-history-detail">
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600">
        <span dir="ltr" className="font-mono">{d.uuid}</span>
        {d.branch && <span>فرع المصلحة {d.branch}</span>}
        {d.cancel_until && <span>يمكن إلغاؤه حتى {fmtTime(d.cancel_until)}</span>}
        {kind === 'documents' && (
          <Btn disabled={act.pending} data-tour="tax-invoicing-main-history-pdf"
            onClick={() => act.run(() => taxInvoicingApi.historyDocumentPdf(id), r => {
              save(r instanceof Blob ? r : new Blob([r], { type: 'application/pdf' }), `${d.internal_id || d.uuid}.pdf`)
              return 'تم تنزيل ملف المصلحة'
            })}>
            ملف المصلحة PDF
          </Btn>
        )}
      </div>
      {d.detail_unavailable && <Notice tone="amber">تفاصيل البنود غير متاحة الآن: {d.detail_unavailable}</Notice>}
      <Lines lines={d.lines} />
      {d.validation?.length > 0 && (
        <div className="text-xs text-gray-600">
          خطوات تحقق المصلحة: {d.validation.map(s => `${s.name}: ${s.status}${s.error ? ` (${JSON.stringify(s.error)})` : ''}`).join(' · ')}
        </div>
      )}
      <ActionMsg msg={act.msg} />
    </div>
  )
}

export default function HistoryTab({ me }) {
  const [system, setSystem] = useState('production')
  const [kind, setKind] = useState('documents')
  const [f, setF] = useState({ date_from: '', date_to: '', direction: '', status: '', doc_type: '', device: '', q: '' })
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('')
  const [open, setOpen] = useState(null)
  const act = useAction()
  const set = (k, v) => { setF(x => ({ ...x, [k]: v })); setPage(1) }
  const params = { system, page, ordering, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v)) }
  const list = useQuery({
    enabled: kind !== 'recon',
    queryKey: ['tax-invoicing', 'history', kind, params],
    queryFn: () => (kind === 'documents' ? taxInvoicingApi.historyDocuments(params) : taxInvoicingApi.historyReceipts(params)).then(r => r.data),
    placeholderData: keepPreviousData,
  })
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) },
    { allowed: kind === 'documents' ? DOC_SORT : RECEIPT_SORT, defaultOrdering: '-issued_at' })
  const data = list.data
  // Stage 4: the file is built as a background job (start → progress → download)
  const exp = useExportJob({
    storageKey: 'export-job:eta-history',
    start: () => exportJobsApi.start(`/tax-invoicing/history/${kind}/export/`, { ...params, page: undefined }),
  })
  const exportFile = () => exp.run()

  return (
    <Section title="سجل المصلحة" data-tour="tax-invoicing-main-history"
      hint="نسخة للقراءة فقط مما تحتفظ به المصلحة لكل منظومة. لا يُرسل شيء من هنا."
      actions={<>
        <Btn disabled={exp.busy || !data?.count} onClick={exportFile} data-tour="tax-invoicing-main-history-export">
          {exp.busy ? '… جارٍ تجهيز الملف' : 'تصدير Excel'}</Btn>
        <ExportJobStatus exp={exp} className="w-56" />
      </>}>
      <div className="flex flex-wrap items-end gap-2 mb-3">
        <div className="flex rounded-md border border-gray-200 overflow-hidden" role="group" aria-label="المنظومة">
          {SYSTEMS.map(([k, label]) => (
            <button key={k} type="button" onClick={() => { setSystem(k); setPage(1); setOpen(null) }}
              className={`px-3 py-1 text-sm ${system === k ? 'bg-gray-900 text-white' : 'bg-white text-gray-600'}`}>{label}</button>
          ))}
        </div>
        <div className="flex rounded-md border border-gray-200 overflow-hidden" role="group" aria-label="النوع">
          {KINDS.map(([k, label]) => (
            <button key={k} type="button" onClick={() => { setKind(k); setPage(1); setOrdering(''); setOpen(null) }}
              className={`px-3 py-1 text-sm ${kind === k ? 'bg-gray-900 text-white' : 'bg-white text-gray-600'}`}>{label}</button>
          ))}
        </div>
        {kind !== 'recon' && (
          <>
        <Field label="من"><input type="date" className={INPUT} value={f.date_from} onChange={e => set('date_from', e.target.value)} aria-label="من تاريخ" /></Field>
        <Field label="إلى"><input type="date" className={INPUT} value={f.date_to} onChange={e => set('date_to', e.target.value)} aria-label="إلى تاريخ" /></Field>
        {kind === 'documents' && (
          <>
            <Field label="الاتجاه">
              <select className={INPUT} value={f.direction} onChange={e => set('direction', e.target.value)} aria-label="الاتجاه">
                <option value="">الكل</option><option value="sent">صادرة منا</option><option value="received">واردة إلينا</option>
              </select>
            </Field>
            <Field label="النوع">
              <select className={INPUT} value={f.doc_type} onChange={e => set('doc_type', e.target.value)} aria-label="نوع المستند">
                <option value="">الكل</option>{Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
          </>
        )}
        {kind === 'receipts' && (
          <Field label="الجهاز">
            <select className={INPUT} value={f.device} onChange={e => set('device', e.target.value)} aria-label="الجهاز">
              <option value="">الكل</option>{(data?.devices || []).map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
        )}
        <Field label="الحالة">
          <select className={INPUT} value={f.status} onChange={e => set('status', e.target.value)} aria-label="الحالة">
            <option value="">الكل</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="بحث" className="grow min-w-[180px]">
          <input className={`${INPUT} w-full`} value={f.q} onChange={e => set('q', e.target.value)}
            placeholder={kind === 'documents' ? 'الرقم الداخلي، الاسم، الرقم الضريبي، UUID' : 'رقم الإيصال أو UUID'} aria-label="بحث" />
        </Field>
          </>
        )}
      </div>
      {kind === 'recon' ? <ReconSection system={system} me={me} /> : list.isLoading ? <Loading /> : list.error ? <Failed error={list.error} /> : (
        <>
          <div className="text-xs text-gray-600 mb-2">{fmtInt(data.count)} {kind === 'documents' ? 'مستند' : 'إيصال'} · الإجمالي {fmt(data.total_amount)}</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr>
                <SortTh {...headerProps('issued_at')} className={TH}>تاريخ الإصدار</SortTh>
                {kind === 'documents' ? (
                  <>
                    <SortTh {...headerProps('doc_type')} className={TH}>النوع</SortTh>
                    <SortTh {...headerProps('internal_id')} className={TH}>الرقم الداخلي</SortTh>
                    <th className={TH}>الاتجاه</th>
                    <SortTh {...headerProps('issuer_name')} className={TH}>المُصدر</SortTh>
                    <SortTh {...headerProps('receiver_name')} className={TH}>المستلم</SortTh>
                  </>
                ) : (
                  <>
                    <SortTh {...headerProps('receipt_number')} className={TH}>رقم الإيصال</SortTh>
                    <SortTh {...headerProps('pos_serial')} className={TH}>الجهاز</SortTh>
                    <th className={TH}>البرنامج المرسل</th>
                  </>
                )}
                <SortTh {...headerProps('status')} className={TH}>الحالة</SortTh>
                <SortTh {...headerProps('total_amount')} className={TH}>الإجمالي</SortTh>
              </tr></thead>
              <tbody>
                {data.rows.map(r => (
                  <FragmentRow key={r.id} r={r} kind={kind} open={open === r.id} onToggle={() => setOpen(o => (o === r.id ? null : r.id))} />
                ))}
              </tbody>
            </table>
            {!data.rows.length && <div className="py-8 text-center text-gray-400">لا توجد بيانات لهذه الفلاتر</div>}
          </div>
          <div className="flex items-center gap-2 mt-2 text-xs">
            <Btn disabled={page <= 1} onClick={() => setPage(p => p - 1)}>السابق</Btn>
            <span>صفحة {fmtInt(data.page)} من {fmtInt(data.pages)}</span>
            <Btn disabled={page >= data.pages} onClick={() => setPage(p => p + 1)}>التالي</Btn>
          </div>
        </>
      )}
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
    </Section>
  )
}

function FragmentRow({ r, kind, open, onToggle }) {
  return (
    <>
      <tr className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${open ? 'bg-gray-50' : ''}`} onClick={onToggle}>
        <td className="px-2 py-1.5 whitespace-nowrap">{fmtTime(r.issued_at)}</td>
        {kind === 'documents' ? (
          <>
            <td className="px-2 py-1.5">{DOC_TYPES[r.doc_type] || r.doc_type}</td>
            <td className="px-2 py-1.5 whitespace-nowrap">{r.internal_id || '—'}</td>
            <td className="px-2 py-1.5">{r.direction === 'sent' ? 'صادرة' : 'واردة'}</td>
            <td className="px-2 py-1.5 max-w-[200px] truncate" title={r.issuer_name}>{r.issuer_name || r.issuer_rin}</td>
            <td className="px-2 py-1.5 max-w-[200px] truncate" title={r.receiver_name}>{r.receiver_name || r.receiver_id || '—'}</td>
          </>
        ) : (
          <>
            <td className="px-2 py-1.5">{r.receipt_number}</td>
            <td className="px-2 py-1.5 font-mono text-xs" dir="ltr">{r.pos_serial}</td>
            <td className="px-2 py-1.5 text-xs">{r.submitter || '—'}</td>
          </>
        )}
        <td className="px-2 py-1.5"><Badge tone={TONE[r.status]}>{STATUS[r.status] || r.status}</Badge></td>
        <td className="px-2 py-1.5 font-bold">{fmt(r.total_amount)}</td>
      </tr>
      {open && (
        <tr><td colSpan={kind === 'documents' ? 8 : 6} className="px-2 py-3 bg-gray-50"><HistoryDetail kind={kind} id={r.id} /></td></tr>
      )}
    </>
  )
}
