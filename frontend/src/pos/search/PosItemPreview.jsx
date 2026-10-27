/**
 * PosItemPreview — side preview for the highlighted search result: large image, every branch's
 * stock, badges and (when a customer is chosen) how long ago THIS customer last bought the item.
 * Last purchase comes from the existing GET /customers/{id}/purchases/?doc_code=115 (sales only),
 * fetched once per customer and cached — nothing is read from SOFTECH.
 */
import { useQuery } from '@tanstack/react-query'
import { customersApi } from '../../api/client'
import { BranchStockPill } from '../design'
import useBranchNames from './useBranchNames'
import { ItemBadges, HereStock } from './PosResultRow'

function useLastPurchaseDays(customerId, softechId) {
  const { data } = useQuery({
    queryKey: ['pos-cust-sales', customerId],
    queryFn: () => customersApi.purchases(customerId, 115).then(r => r.data),
    enabled: !!customerId,
    staleTime: 10 * 60 * 1000,
  })
  if (!customerId || !Array.isArray(data)) return null
  let best = null
  for (const inv of data) {
    if (inv.is_return) continue
    if ((inv.lines || []).some(l => String(l.item_softech_id) === String(softechId))) {
      const t = new Date(inv.invoice_date).getTime()
      if (Number.isFinite(t) && (best == null || t > best)) best = t
    }
  }
  return best == null ? null : Math.max(0, Math.floor((Date.now() - best) / 86400000))
}

export default function PosItemPreview({ item, hereBranchId, customerId, className = '' }) {
  const nameOf = useBranchNames()
  const days = useLastPurchaseDays(customerId, item?.softech_id)
  if (!item) return null
  const all = item.branch_stock || []
  return (
    <div className={`p-3 space-y-2 text-sm ${className}`} dir="rtl">
      {item.thumb
        ? <img src={item.thumb} alt="" className="w-full max-h-48 object-contain rounded bg-gray-50" />
        : <div className="w-full h-24 rounded bg-gray-50 text-gray-300 flex items-center justify-center text-xs">لا توجد صورة</div>}
      <div className="font-bold text-gray-900 leading-snug">{item.name}</div>
      <div className="flex gap-1 flex-wrap"><ItemBadges item={item} /></div>
      <div>
        {item.qty_at_branch != null && <div className="mb-1.5"><HereStock qty={item.qty_at_branch} branchName={nameOf(hereBranchId)} /></div>}
        <div className="text-[11px] text-gray-500 mb-1">فروع أخرى</div>
        <div className="flex flex-wrap gap-1">
          {all.filter(b => String(b.branch_id) !== String(hereBranchId)).map(b => (
            <BranchStockPill key={b.branch_id} size="xs" name={nameOf(b.branch_id) || `#${b.branch_id}`} qty={b.qty} />
          ))}
          {!all.length && <span className="text-xs text-gray-400">لا بيانات رصيد للشبكة</span>}
        </div>
      </div>
      {days != null && (
        <div className="text-xs text-indigo-700 bg-indigo-50 rounded px-2 py-1">
          آخر شراء لهذا العميل: {days === 0 ? 'اليوم' : `منذ ${days} يوم`}
        </div>
      )}
    </div>
  )
}
