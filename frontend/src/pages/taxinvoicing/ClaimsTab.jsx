import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { taxInvoicingApi } from '../../api/client'
import { ActionMsg, Badge, Btn, DOC_STATUS_TONE, Failed, fmt, fmtDate, Grid, INPUT, Loading, useAction } from './ui'

export default function ClaimsTab({ me, go }) {
  const [q, setQ] = useState('')
  const act = useAction()
  const params = q.trim() ? { q: q.trim() } : {}
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'claims', params],
    queryFn: () => taxInvoicingApi.claims(params).then(r => r.data),
    placeholderData: prev => prev,
  })
  const openDoc = id => go('documents', { doc: id })

  const columns = [
    { key: 'claim_number', label: 'المطالبة', render: r => (
      <Link to={`/insurance/claims/${r.id}`} className="font-medium text-primary hover:underline">{r.claim_number}</Link>) },
    { key: 'softech_motalba_no', label: 'رقم SOFTECH' },
    { key: 'client', label: 'الجهة', className: 'max-w-[260px] truncate' },
    { key: 'period_to', label: 'الفترة', type: 'date', render: r => `${fmtDate(r.period_from)} ← ${fmtDate(r.period_to)}` },
    { key: 'final_net_after', label: 'صافي المطالبة', type: 'number', render: r => fmt(r.final_net_after), className: 'font-bold whitespace-nowrap' },
    { key: 'invoice_status', label: 'الفاتورة', value: r => r.invoice_status_label, render: r => (r.invoice_id
      ? <Badge tone={DOC_STATUS_TONE[r.invoice_status]}>{r.invoice_status_label}</Badge>
      : <span className="text-xs text-gray-400">لم تُنشأ</span>) },
    { key: 'internal_id', label: 'رقم المستند', render: r => r.internal_id || '—' },
    { key: 'action', label: '', sortable: false, render: r => (r.invoice_id
      ? <Btn onClick={() => openDoc(r.invoice_id)}>فتح الفاتورة</Btn>
      : me.can_create && (
        <Btn variant="primary" disabled={act.pending} data-tour="tax-invoicing-main-open-draft"
          onClick={() => act.run(() => taxInvoicingApi.openInvoice(r.id), null, d => openDoc(d.id))}>
          إنشاء المسودة
        </Btn>
      )) },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث برقم المطالبة أو رقم SOFTECH أو الجهة…"
          className={`${INPUT} w-full max-w-md`} />
        <ActionMsg msg={act.msg} />
      </div>
      {isLoading ? <Loading /> : error ? <Failed error={error} /> : (
        <Grid columns={columns} rows={data} data-tour="tax-invoicing-main-claims-grid"
          onOpen={r => (r.invoice_id ? openDoc(r.invoice_id) : undefined)}
          empty="لا توجد مطالبات مقفلة بهذا البحث" />
      )}
    </div>
  )
}
