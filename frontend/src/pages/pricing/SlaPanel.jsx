/** SlaPanel — pending requests aging report (oldest-first), with age buckets. */
import { useQuery } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../../api/client'

const BUCKETS = [
  { key: 'lt1h',  label: '< ساعة',     color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  { key: 'h1_4',  label: '1–4 ساعات',  color: 'bg-blue-50 text-blue-700 border-blue-200' },
  { key: 'h4_24', label: '4–24 ساعة',  color: 'bg-amber-50 text-amber-700 border-amber-200' },
  { key: 'gt24h', label: '> 24 ساعة',  color: 'bg-red-50 text-red-700 border-red-200' },
]

function ageLabel(h) {
  if (h < 1) return `${Math.round(h * 60)} د`
  if (h < 24) return `${h.toFixed(1)} س`
  return `${Math.floor(h / 24)} ي ${Math.round(h % 24)} س`
}

export default function SlaPanel({ onOpen }) {
  const { data, isLoading } = useQuery({
    queryKey: ['pricing-sla'],
    queryFn: () => pricingApprovalsApi.sla().then(r => r.data),
    refetchInterval: 30000,
  })

  if (isLoading) return <div className="text-center py-12 text-gray-400 text-sm">جاري التحميل…</div>
  const rows = data?.requests || []

  return (
    <div className="space-y-4" dir="rtl">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {BUCKETS.map(b => (
          <div key={b.key} className={`rounded-xl border p-4 ${b.color}`}>
            <div className="text-2xl font-bold">{data?.buckets?.[b.key] ?? 0}</div>
            <div className="text-xs mt-0.5">{b.label}</div>
          </div>
        ))}
      </div>

      {data?.oldest_age_hours > 24 && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">
          ⚠ أقدم طلب معلّق منذ {ageLabel(data.oldest_age_hours)} — يحتاج مراجعة عاجلة
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="bg-gray-50 text-right border-b">
            <th className="px-3 py-2 text-xs text-gray-500">العمر</th>
            <th className="px-3 py-2 text-xs text-gray-500">الصنف</th>
            <th className="px-3 py-2 text-xs text-gray-500">التعديل المطلوب</th>
            <th className="px-3 py-2 text-xs text-gray-500">بواسطة</th>
            <th className="px-3 py-2 text-xs text-gray-500"></th>
          </tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="px-3 py-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    r.age_hours > 24 ? 'bg-red-100 text-red-700' :
                    r.age_hours > 4 ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>
                    {ageLabel(r.age_hours)}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="font-medium text-gray-800">{r.item_name}</div>
                  <div className="text-xs text-gray-400 font-mono">{r.item_softech_id}</div>
                </td>
                <td className="px-3 py-2 text-xs">
                  {Object.entries(r.new_values).map(([k, v]) => `${k}: ${v}`).join('، ')}
                  {r.reason && <div className="text-gray-400 mt-0.5 truncate max-w-[200px]">{r.reason}</div>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-600">{r.requested_by}</td>
                <td className="px-3 py-2">
                  <button onClick={() => onOpen?.(r.id)}
                    className="text-xs bg-blue-600 text-white px-3 py-1 rounded-lg hover:bg-blue-700">مراجعة</button>
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={5} className="text-center py-10 text-emerald-600 text-sm">✓ لا توجد طلبات معلّقة</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
