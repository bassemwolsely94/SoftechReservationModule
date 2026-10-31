/**
 * ExpiryBucketsTile — the dashboard's one-line expiry picture (P-26): shelf risk kept apart from
 * book residue (return candidates 105, write-off 102, expired cosmetics 103). The closed branch
 * (store 110) is never counted. Numbers come from /api/batches/stock-expiry/summary/; shown to
 * users with catalog view (the /batches read permission).
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { batchesApi } from '../api/client'
import { usePermission } from '../hooks/usePermission'
import DataFreshnessBar from './DataFreshnessBar'

const fmt = (n) => Number(n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })

export default function ExpiryBucketsTile() {
  const navigate = useNavigate()
  const canView = usePermission('catalog', 'view')
  const { data } = useQuery({
    queryKey: ['batches', 'stock-expiry-summary'],
    queryFn: () => batchesApi.stockExpirySummary({}).then(r => r.data),
    enabled: canView,
    staleTime: 10 * 60 * 1000,
  })
  if (!canView || !data?.buckets) return null
  const b = data.buckets
  return (
    <div data-tour="general-dashboard-expiry" onClick={() => navigate('/batches')}
         className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm cursor-pointer hover:border-gray-300">
      <b className="text-gray-800">⏳ الصلاحية</b>
      <span>على الرف: <b className="text-red-700">{fmt(b.live?.expired?.value)} ج</b> منتهية ·
        <b className="text-amber-700"> {fmt(data.total_at_risk_value)} ج</b> تنتهي خلال 180 يوم</span>
      <span className="text-gray-400">|</span>
      <span>{b.return_candidate?.label}: <b>{fmt(b.return_candidate?.value)} ج</b></span>
      <span>{b.write_off?.label}: <b>{fmt(b.write_off?.value)} ج</b></span>
      <span>{b.cosmetics_expired?.label}: <b>{fmt(b.cosmetics_expired?.value)} ج</b></span>
      <span className="mr-auto" onClick={e => e.stopPropagation()}><DataFreshnessBar domains={['expiry']} compact /></span>
    </div>
  )
}
