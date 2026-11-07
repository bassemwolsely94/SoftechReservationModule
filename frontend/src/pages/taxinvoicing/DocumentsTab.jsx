import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import DocumentDetail from './DocumentDetail'
import { Badge, DOC_STATUS_TONE, Failed, Field, fmt, fmtTime, Grid, INPUT, Loading } from './ui'

const STATUSES = [
  ['draft', 'مسودة'], ['approved', 'معتمدة'], ['submitting', 'جارٍ الإرسال'], ['uncertain', 'نتيجة غير مؤكدة'],
  ['submitted', 'مُرسلة'], ['valid', 'مقبولة'], ['invalid', 'غير صالحة'], ['rejected', 'مرفوضة عند الإرسال'],
]
const TYPES = [['i', 'فاتورة'], ['c', 'إشعار دائن'], ['d', 'إشعار مدين']]

const COLUMNS = [
  { key: 'internal_id', label: 'رقم المستند', className: 'font-medium whitespace-nowrap' },
  { key: 'doc_type_label', label: 'النوع' },
  { key: 'status_label', label: 'الحالة', render: r => <Badge tone={DOC_STATUS_TONE[r.status]}>{r.status_label}</Badge> },
  { key: 'claim_number', label: 'المطالبة' },
  { key: 'client', label: 'الجهة', className: 'max-w-[240px] truncate' },
  { key: 'source_claim_total', label: 'إجمالي المطالبة', type: 'number', render: r => fmt(r.source_claim_total) },
  { key: 'total_amount', label: 'إجمالي المستند', type: 'number', render: r => fmt(r.total_amount), className: 'font-bold' },
  { key: 'vat_amount', label: 'الضريبة', type: 'number', render: r => fmt(r.vat_amount) },
  { key: 'created_at', label: 'أُنشئ', type: 'date', render: r => fmtTime(r.created_at), className: 'whitespace-nowrap' },
  { key: 'approved_at', label: 'اعتُمد', type: 'date', render: r => fmtTime(r.approved_at), className: 'whitespace-nowrap' },
]

export default function DocumentsTab({ me, docId, go }) {
  const [f, setF] = useState({ status: '', type: '', q: '' })
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v.trim()))
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'documents', params],
    queryFn: () => taxInvoicingApi.documents(params).then(r => r.data),
    placeholderData: prev => prev,
    enabled: !docId,
  })

  if (docId) return <DocumentDetail key={docId} id={docId} me={me} go={go} />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2" data-tour="tax-invoicing-main-doc-filters">
        <Field label="الحالة">
          <select value={f.status} onChange={e => set('status', e.target.value)} className={INPUT}>
            <option value="">الكل</option>
            {STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="النوع">
          <select value={f.type} onChange={e => set('type', e.target.value)} className={INPUT}>
            <option value="">الكل</option>
            {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="بحث" className="grow min-w-[200px]">
          <input value={f.q} onChange={e => set('q', e.target.value)} placeholder="رقم المستند، المطالبة، أو رقم المصلحة…" className={INPUT} />
        </Field>
      </div>
      {isLoading ? <Loading /> : error ? <Failed error={error} /> : (
        <Grid columns={COLUMNS} rows={data} onOpen={r => go('documents', { doc: r.id })}
          data-tour="tax-invoicing-main-doc-grid" empty="لا توجد مستندات بهذه الفلاتر" />
      )}
    </div>
  )
}
