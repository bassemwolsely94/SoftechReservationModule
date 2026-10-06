/**
 * MobileMyIncentivesPage.jsx — salesperson's own incentive earnings (route: /m/my-incentives).
 *
 * Personal, glanceable view over /incentives/my-progress/ — total earned +
 * projected, and a card per active program.
 */
import { useQuery } from '@tanstack/react-query'
import { incentivesApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'

function money(v) {
  const n = Number(v) || 0
  return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

export default function MobileMyIncentivesPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['m-my-incentives'],
    queryFn: () => incentivesApi.myProgress().then(r => r.data),
    retry: false,
  })

  if (isLoading) return <div className="p-3"><MobileLoading /></div>
  if (isError) return <div className="p-3"><MobileError text={error?.response?.data?.detail || 'تعذّر تحميل الحوافز'} onRetry={refetch} /></div>

  const programs = data?.programs || []
  const earned    = programs.reduce((s, p) => s + (Number(p.earned_to_date) || 0), 0)
  const projected = programs.reduce((s, p) => s + (Number(p.projected_total) || 0), 0)

  return (
    <div className="p-3 space-y-3">
      <div>
        <h1 className="text-base font-bold text-gray-900">حوافزي</h1>
        <p className="text-xs text-gray-400">{data?.employee?.name}{data?.as_of_date ? ` — حتى ${data.as_of_date}` : ''}</p>
      </div>

      {/* Totals */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-white rounded-2xl border border-gray-200 p-4 text-center">
          <div className="text-2xl font-bold text-brand-700">{money(earned)}</div>
          <div className="text-[11px] text-gray-400 mt-0.5">المكتسب حتى الآن (ج.م)</div>
        </div>
        <div className="bg-white rounded-2xl border border-gray-200 p-4 text-center">
          <div className="text-2xl font-bold text-gray-700">{money(projected)}</div>
          <div className="text-[11px] text-gray-400 mt-0.5">المتوقع (ج.م)</div>
        </div>
      </div>

      {programs.length === 0 ? (
        <MobileEmpty icon="🏅" text="لا توجد برامج حوافز نشطة" />
      ) : (
        <div className="space-y-2.5">
          {programs.map((p, i) => {
            const pct = p.projected_total ? Math.min(100, Math.round((p.earned_to_date / p.projected_total) * 100)) : 0
            return (
              <div key={p.id || i} className="bg-white rounded-2xl border border-gray-200 p-4">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <span className="font-semibold text-sm text-gray-800">{p.name}</span>
                  <span className="text-sm font-bold text-brand-700">{money(p.earned_to_date)} ج.م</span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full bg-brand-500 rounded-full" style={{ width: `${pct}%` }} />
                </div>
                <div className="text-[11px] text-gray-400 mt-1">المتوقع: {money(p.projected_total)} ج.م</div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
