import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { Badge, Btn, Failed, fmtInt, Grid, LINE_STATUS_TONE, Loading } from './ui'

const STATUS_LABEL = { uncoded: 'غير مُرمَّز', pending: 'قيد المراجعة', held: 'إيصالات محجوزة' }

export default function ExceptionsTab({ go }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'exceptions'],
    queryFn: () => taxInvoicingApi.exceptions().then(r => r.data),
  })
  if (isLoading) return <Loading />
  if (error) return <Failed error={error} />

  const columns = [
    { key: 'itemcode', label: 'الكود', className: 'whitespace-nowrap' },
    { key: 'item_name', label: 'الصنف', render: r => r.item_name || '—', className: 'max-w-[240px] truncate' },
    { key: 'status', label: 'الحالة', value: r => STATUS_LABEL[r.status] || r.status, render: r => (
      <Badge tone={LINE_STATUS_TONE[r.status]}>{STATUS_LABEL[r.status] || r.status}</Badge>) },
    { key: 'reason', label: 'السبب', className: 'max-w-[280px]' },
    { key: 'lines', label: 'بنود في المسودات', type: 'number', render: r => fmtInt(r.lines) },
    { key: 'drafts', label: 'المسودات الموقوفة', value: r => r.drafts.length, type: 'number', render: r => (
      r.drafts.length ? (
        <div className="flex flex-wrap gap-1">
          {r.drafts.map(d => (
            <button key={d.id} type="button" onClick={() => go('documents', { doc: d.id })}
              title={`المطالبة ${d.claim_number}`}
              className="px-1.5 py-0.5 rounded border border-gray-200 text-[11px] text-primary hover:underline">{d.internal_id}</button>
          ))}
        </div>
      ) : '—') },
    { key: 'held_receipt_lines', label: 'بنود إيصالات محجوزة', type: 'number', render: r => (r.held_receipt_lines
      ? <button type="button" className="text-primary font-bold hover:underline" onClick={() => go('receipts', { status: 'held' })}>{fmtInt(r.held_receipt_lines)}</button>
      : '—') },
    { key: 'resolve', label: '', sortable: false, render: r => (
      <Btn variant="primary" data-tour="tax-invoicing-main-exceptions-resolve"
        onClick={() => go('items', r.profile_id ? { q: r.itemcode } : { new: r.itemcode })}>
        حل في الأصناف
      </Btn>) },
  ]
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        كل صنف لم يُحسم وما يوقفه. بند واحد غير محسوم يوقف المستند كله، وبعد حل الصنف يُعاد فحص مسوداته تلقائياً.
      </p>
      <Grid columns={columns} rows={data} getKey={r => r.itemcode} data-tour="tax-invoicing-main-exceptions-grid"
        onOpen={r => go('items', r.profile_id ? { q: r.itemcode } : { new: r.itemcode })}
        empty="✅ لا توجد أصناف غير محسومة" />
    </div>
  )
}
