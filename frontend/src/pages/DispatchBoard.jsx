/**
 * DispatchBoard.jsx — /delivery/dispatch
 * Batch ready orders into a driver route, then dispatch the whole run; watch live status.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { deliveryApi } from '../api/client'

const fmt = n => (Number(n) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const RSTATUS = {
  planned:    { label: 'مُخطّط 📝', cls: 'bg-gray-100 text-gray-600' },
  dispatched: { label: 'في الطريق 🚚', cls: 'bg-amber-100 text-amber-700' },
  completed:  { label: 'مكتمل ✅', cls: 'bg-emerald-100 text-emerald-700' },
  cancelled:  { label: 'ملغى', cls: 'bg-red-100 text-red-700' },
}
const today = () => new Date().toISOString().slice(0, 10)

export default function DispatchBoard() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState(() => new Set())
  const [driverId, setDriverId] = useState('')

  const { data: orders = [] } = useQuery({
    queryKey: ['dispatch-ready'],
    queryFn: () => deliveryApi.list({ status: 'ready', limit: 200 }).then(r => {
      const d = Array.isArray(r.data) ? r.data : (r.data.results || [])
      return d.filter(o => o.status === 'ready')
    }),
    refetchInterval: 20_000,
  })
  const { data: drivers = [] } = useQuery({
    queryKey: ['drivers-active'],
    queryFn: () => deliveryApi.listDrivers({ status: 'active' }).then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const { data: routes = [] } = useQuery({
    queryKey: ['routes-today'],
    queryFn: () => deliveryApi.listRoutes({ date: today() }).then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
    refetchInterval: 20_000,
  })

  const after = () => {
    setSelected(new Set()); setDriverId('')
    qc.invalidateQueries({ queryKey: ['dispatch-ready'] })
    qc.invalidateQueries({ queryKey: ['routes-today'] })
  }
  const createRoute = useMutation({
    mutationFn: () => deliveryApi.createRoute({ driver_id: driverId, order_ids: [...selected] }),
    onSuccess: after,
  })
  const dispatchRoute = useMutation({
    mutationFn: (id) => deliveryApi.dispatchRoute(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['routes-today'] }),
  })

  const toggle = (id) => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">🧭 لوحة التوزيع</h1>
      <p className="text-sm text-gray-500 mb-5">جمّع الطلبات الجاهزة في مسار لسائق ثم أطلق المسار دفعة واحدة</p>

      <div className="grid md:grid-cols-2 gap-5">
        {/* Ready orders → build a route */}
        <div className="bg-white rounded-2xl border border-gray-100 p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-bold text-gray-800 text-sm">📦 جاهزة للتكليف ({orders.length})</h2>
            <span className="text-xs text-gray-400">{selected.size} محدد</span>
          </div>
          <div className="max-h-[55vh] overflow-y-auto divide-y divide-gray-50">
            {orders.length === 0 ? <div className="py-10 text-center text-gray-400 text-sm">لا توجد طلبات جاهزة</div>
              : orders.map(o => (
              <label key={o.id} className="flex items-center gap-2 py-2 cursor-pointer">
                <input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} className="accent-brand-600" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-800 truncate">{o.customer_name} · {fmt(o.total_with_fees)} ج.م</div>
                  <div className="text-[11px] text-gray-400 truncate">{o.delivery_area || o.delivery_governorate || '—'} · {o.payment_method === 'cash' ? 'كاش' : o.payment_method}</div>
                </div>
              </label>
            ))}
          </div>
          <div className="flex gap-2 mt-3 pt-3 border-t border-gray-100">
            <select className="input-field flex-1" value={driverId} onChange={e => setDriverId(e.target.value)}>
              <option value="">اختر السائق…</option>
              {drivers.map(d => <option key={d.id} value={d.id}>{d.full_name} ({d.today_order_count})</option>)}
            </select>
            <button onClick={() => createRoute.mutate()} disabled={!driverId || !selected.size || createRoute.isPending}
              className="btn-primary text-sm disabled:opacity-40">إنشاء مسار</button>
          </div>
        </div>

        {/* Today's routes — live status */}
        <div className="bg-white rounded-2xl border border-gray-100 p-4">
          <h2 className="font-bold text-gray-800 text-sm mb-2">🚚 مسارات اليوم ({routes.length})</h2>
          <div className="max-h-[62vh] overflow-y-auto space-y-2">
            {routes.length === 0 ? <div className="py-10 text-center text-gray-400 text-sm">لا توجد مسارات بعد</div>
              : routes.map(r => {
              const st = RSTATUS[r.status] || {}
              const pct = r.stop_count ? Math.round((r.delivered_count / r.stop_count) * 100) : 0
              return (
                <div key={r.id} className="border border-gray-100 rounded-xl p-3">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-gray-800 text-sm">{r.driver_name || 'بدون سائق'} · {r.stop_count} طلب</div>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${st.cls || 'bg-gray-100'}`}>{st.label || r.status}</span>
                  </div>
                  <div className="text-[11px] text-gray-400 mt-0.5">نقدي متوقّع {fmt(r.expected_cash)} ج.م · تم {r.delivered_count}/{r.stop_count}</div>
                  <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden mt-1.5"><div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} /></div>
                  {r.status === 'planned' && (
                    <button onClick={() => dispatchRoute.mutate(r.id)} disabled={dispatchRoute.isPending}
                      className="w-full mt-2 text-xs bg-brand-600 text-white rounded-lg py-1.5 font-medium disabled:opacity-50">🚚 إطلاق المسار</button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
