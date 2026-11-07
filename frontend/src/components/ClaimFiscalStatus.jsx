/**
 * ClaimFiscalStatus — the claim's tax documents, read only, on the insurance claim screen. Insurance
 * staff may see it without holding the tax module; the link only shows to those who can open it.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { taxInvoicingApi } from '../api/client'
import { usePermission } from '../hooks/usePermission'

export default function ClaimFiscalStatus({ claimId }) {
  const canOpen = usePermission('tax_invoicing', 'view')
  const { data, error, isLoading } = useQuery({
    queryKey: ['tax-invoicing', 'claim-fiscal', String(claimId)],
    queryFn: () => taxInvoicingApi.claimFiscalStatus(claimId).then(r => r.data),
    retry: false,
  })
  if (isLoading || error) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-600" data-tour="insurance-claim-fiscal-status">
      <span className="text-gray-500">الوضع الضريبي:</span>
      {data.documents.length === 0 && <span className="text-gray-500">لا توجد فاتورة ضريبية بعد</span>}
      {data.documents.map(d => {
        const text = `${d.doc_type_label} ${d.internal_id} · ${d.status_label}`
        return canOpen
          ? <Link key={d.id} to={`/tax-invoicing?tab=documents&doc=${d.id}`} className="px-2 py-0.5 rounded-full border border-gray-200 bg-white text-primary hover:underline">{text}</Link>
          : <span key={d.id} className="px-2 py-0.5 rounded-full border border-gray-200 bg-white">{text}</span>
      })}
    </div>
  )
}
