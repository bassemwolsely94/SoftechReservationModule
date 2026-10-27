/**
 * PortalLoyaltyPage.jsx — customer's loyalty points, tier, and recent activity.
 */
import { useQuery } from '@tanstack/react-query'
import { portalApi } from '../../portal/portalApi'

function fmt(d) {
  if (!d) return ''
  try { return new Date(d).toLocaleDateString('ar-EG', { dateStyle: 'medium' }) } catch { return '' }
}

export default function PortalLoyaltyPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['portal-loyalty'],
    queryFn: () => portalApi.loyalty().then(r => r.data),
  })

  if (isLoading) return <div className="text-center text-sm text-gray-400 py-12">جارٍ التحميل...</div>

  const txns = data?.transactions || []

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="font-bold text-gray-900 text-lg">نقاطي</h1>

      <div className="bg-gradient-to-br from-brand-600 to-brand-sky text-white rounded-2xl p-6 text-center">
        <div className="text-sm opacity-90">رصيد النقاط</div>
        <div className="text-4xl font-black my-1">{data?.points_balance ?? 0}</div>
        {data?.tier && (
          <div className="inline-block text-xs bg-white/20 rounded-full px-3 py-1 mt-1">
            {data.tier.icon} {data.tier.name}
          </div>
        )}
        {!data?.enrolled && <div className="text-xs opacity-80 mt-2">لم يتم تفعيل برنامج النقاط بعد</div>}
      </div>

      {txns.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 divide-y divide-gray-100">
          {txns.map((t, i) => (
            <div key={i} className="flex items-center justify-between p-3.5">
              <div className="min-w-0">
                <div className="text-sm text-gray-800 truncate">{t.reason || t.type}</div>
                <div className="text-[11px] text-gray-400">{fmt(t.created_at)}</div>
              </div>
              <span className={`text-sm font-bold ${t.points >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                {t.points >= 0 ? '+' : ''}{t.points}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
