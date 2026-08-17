/**
 * DeliveryDashboard.jsx — Delivery Management System v3
 * Full order detail panel, SOFTECH items (code/qty/discount), WhatsApp integration.
 */
import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { deliveryApi, branchesApi } from '../api/client'
import DeliveryBackfillModal from '../components/DeliveryBackfillModal'

const fmt     = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const _today  = () => new Date().toISOString().slice(0, 10)
const _daysAgo = d => { const dt = new Date(); dt.setDate(dt.getDate() - d); return dt.toISOString().slice(0, 10) }
const fmtTime = dt => dt ? new Date(dt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '—'
const fmtDate = dt => dt ? new Date(dt).toLocaleDateString('en-US', { day: '2-digit', month: 'short' }) : '—'

// ── Status map ────────────────────────────────────────────────────────────────
const STATUS_MAP = {
  created:              { label: 'جديد',               color: 'bg-gray-100 text-gray-600',    dot: 'bg-gray-400',    whatsapp: false },
  pending_review:       { label: 'بانتظار المراجعة',  color: 'bg-yellow-100 text-yellow-700', dot: 'bg-yellow-400',  whatsapp: false },
  preparing:            { label: 'جاري التحضير',      color: 'bg-orange-100 text-orange-700', dot: 'bg-orange-400',  whatsapp: true  },
  ready:                { label: 'جاهز للتسليم',      color: 'bg-teal-100 text-teal-700',     dot: 'bg-teal-400',    whatsapp: true  },
  assigned:             { label: 'تم التكليف',        color: 'bg-blue-100 text-blue-700',     dot: 'bg-blue-500',    whatsapp: true  },
  driver_accepted:      { label: 'السائق قبل',        color: 'bg-indigo-100 text-indigo-700', dot: 'bg-indigo-500',  whatsapp: true  },
  out_for_delivery:     { label: 'في الطريق',         color: 'bg-amber-100 text-amber-700',   dot: 'bg-amber-500 animate-pulse', whatsapp: true },
  delivered:            { label: 'تم التسليم',       color: 'bg-green-100 text-green-700',    dot: 'bg-green-500',   whatsapp: true  },
  partial_delivery:     { label: 'تسليم جزئي',       color: 'bg-lime-100 text-lime-700',      dot: 'bg-lime-500',    whatsapp: true  },
  customer_unavailable: { label: 'العميل غير متاح',  color: 'bg-pink-100 text-pink-700',      dot: 'bg-pink-500',    whatsapp: true  },
  failed:               { label: 'فشل التسليم',       color: 'bg-red-100 text-red-700',        dot: 'bg-red-500',     whatsapp: true  },
  returned:             { label: 'مُعاد',             color: 'bg-purple-100 text-purple-700',  dot: 'bg-purple-400',  whatsapp: false },
  cancelled:            { label: 'ملغى',              color: 'bg-gray-100 text-gray-400',      dot: 'bg-gray-300',    whatsapp: true  },
  closed:               { label: 'مغلق',              color: 'bg-gray-100 text-gray-500',      dot: 'bg-gray-400',    whatsapp: false },
}

const PAYMENT_LABELS = {
  cash: 'كاش 💵', visa: 'فيزا 💳', insurance: 'تأمين 🏥',
  mixed: 'مختلط', wallet: 'محفظة', pending: 'غير محدد',
}
const SOURCE_LABELS = { call_center: '📞 كول سنتر', branch_pos: '🏪 POS الفرع' }

function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP.created
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

function KpiCard({ label, value, sub, color = 'gray', icon }) {
  const cls = {
    gray:   'bg-gray-50  border-gray-200  text-gray-700',
    blue:   'bg-blue-50  border-blue-200  text-blue-800',
    amber:  'bg-amber-50 border-amber-200 text-amber-800',
    green:  'bg-green-50 border-green-200 text-green-800',
    red:    'bg-red-50   border-red-200   text-red-800',
    brand:  'bg-brand-50 border-brand-200 text-brand-800',
    purple: 'bg-purple-50 border-purple-200 text-purple-800',
  }
  return (
    <div className={`rounded-xl border p-4 ${cls[color] || cls.gray}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-500 mb-0.5">{label}</p>
          <p className="text-2xl font-bold font-mono">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </div>
        <span className="text-2xl opacity-40">{icon}</span>
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// ORDER DETAIL PANEL
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function WhatsAppButton({ orderId, phone, size = 'sm' }) {
  const [sent, setSent] = useState(false)
  const { data: waData, isLoading, refetch } = useQuery({
    queryKey: ['delivery-wa', orderId],
    queryFn:  () => deliveryApi.whatsapp(orderId).then(r => r.data),
    enabled:  false,
  })

  const open = async () => {
    const res = await refetch()
    if (res.data?.whatsapp_url) {
      window.open(res.data.whatsapp_url, '_blank')
      setSent(true)
    }
  }

  const cls = size === 'lg'
    ? 'flex items-center gap-2 px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors'
    : 'flex items-center gap-1.5 px-3 py-1.5 text-xs bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors'

  if (!phone) return null
  return (
    <button onClick={open} disabled={isLoading} className={cls}>
      {isLoading ? '⏳' : '💬'} واتساب {sent && '✓'}
    </button>
  )
}

function OrderItems({ orderId }) {
  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: ['delivery-items', orderId],
    queryFn:  () => deliveryApi.getItems(orderId).then(r => r.data),
    staleTime: 60_000,
  })

  if (isLoading) return <div className="text-center py-6 text-gray-400 animate-pulse text-sm">جاري تحميل الأصناف…</div>
  if (isError)   return <div className="text-center py-6 text-red-400 text-sm">تعذر تحميل الأصناف</div>
  if (!items.length) return <div className="text-center py-6 text-gray-400 text-sm">لا توجد بيانات أصناف متاحة</div>

  const totalSaved = items.reduce((s, i) => s + (i.amount_saved || 0), 0)

  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-right px-3 py-2 font-semibold text-gray-600">كود</th>
              <th className="text-right px-3 py-2 font-semibold text-gray-600">اسم الصنف</th>
              <th className="text-center px-3 py-2 font-semibold text-gray-600">الكمية</th>
              <th className="text-center px-3 py-2 font-semibold text-gray-600">سعر الوحدة</th>
              <th className="text-center px-3 py-2 font-semibold text-red-500">خصم %</th>
              <th className="text-center px-3 py-2 font-semibold text-gray-600">السعر الفعلي</th>
              <th className="text-left px-3 py-2 font-semibold text-gray-700">الإجمالي</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((item, i) => (
              <tr key={i} className="hover:bg-gray-50/50">
                <td className="px-3 py-2 font-mono text-gray-500 text-[11px]">{item.item_code}</td>
                <td className="px-3 py-2 text-gray-800 max-w-[280px]">
                  <div className="whitespace-normal break-words">{item.item_name}</div>
                </td>
                <td className="px-3 py-2 text-center font-mono">
                  {fmt(item.quantity, 0)}
                  {item.supplied_qty != null && item.supplied_qty !== item.quantity && (
                    <span className="text-amber-500 mr-1">/{fmt(item.supplied_qty)}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-center font-mono text-gray-500 line-through">
                  {item.discount_pct > 0 ? fmt(item.sale_price, 2) : '—'}
                </td>
                <td className="px-3 py-2 text-center">
                  {item.discount_pct > 0 ? (
                    <span className="px-1.5 py-0.5 bg-red-50 text-red-600 rounded font-semibold">
                      {fmt(item.discount_pct, 0)}%
                    </span>
                  ) : '—'}
                </td>
                <td className="px-3 py-2 text-center font-mono">{fmt(item.trans_price, 2)}</td>
                <td className="px-3 py-2 text-left font-mono font-semibold text-gray-800">
                  {fmt(item.line_total, 2)} ج.م
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-gray-50 border-t border-gray-200">
            <tr>
              <td colSpan={6} className="px-3 py-2 text-left text-xs text-gray-500">
                {items.length} صنف
                {totalSaved > 0 && (
                  <span className="mr-3 text-green-600 font-medium">
                    وفّرت: {fmt(totalSaved, 2)} ج.م 🎉
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-left font-mono font-bold text-gray-800">
                {fmt(items.reduce((s, i) => s + (i.line_total || 0), 0), 2)} ج.م
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

function StatusHistory({ logs }) {
  if (!logs?.length) return <p className="text-xs text-gray-400 text-center py-3">لا يوجد سجل حالات</p>
  return (
    <div className="space-y-1.5">
      {logs.map((log, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
          <div className="mt-1 w-1.5 h-1.5 rounded-full bg-gray-400 shrink-0" />
          <div className="flex-1">
            <span className="text-gray-500">{log.from_status || '—'}</span>
            <span className="text-gray-400 mx-1.5">→</span>
            <span className="font-medium text-gray-700">{log.to_status}</span>
            {log.notes && <span className="text-gray-400 mr-2">· {log.notes}</span>}
          </div>
          <span className="text-gray-400 shrink-0">{fmtTime(log.recorded_at)}</span>
        </div>
      ))}
    </div>
  )
}

function OrderDetailPanel({ orderId, onClose, onAction }) {
  const { data: order, isLoading } = useQuery({
    queryKey: ['delivery-order', orderId],
    queryFn:  () => deliveryApi.get(orderId).then(r => r.data),
    enabled:  !!orderId,
    refetchInterval: 15_000,
  })

  const [tab, setTab] = useState('details')
  const [showBackfill, setShowBackfill] = useState(false)

  if (isLoading || !order) {
    return (
      <div className="fixed inset-0 bg-black/30 z-40 flex items-center justify-center" onClick={onClose}>
        <div className="bg-white rounded-2xl p-6 animate-pulse text-gray-400">جاري التحميل…</div>
      </div>
    )
  }

  const sm = STATUS_MAP[order.status] || STATUS_MAP.created
  const hasWA = sm.whatsapp && (order.customer_phone || order.customer_phone_alt)

  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-start justify-end" onClick={onClose}>
      <div
        className="bg-white h-full w-full max-w-2xl shadow-2xl overflow-y-auto"
        onClick={e => e.stopPropagation()}
        dir="rtl"
      >
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-200 px-5 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
            <div>
              <p className="font-bold text-gray-800 text-lg">{order.order_number}</p>
              <p className="text-xs text-gray-500">{SOURCE_LABELS[order.source_type]} · {fmtDate(order.ordered_at)} {fmtTime(order.ordered_at)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={order.status} />
            <button onClick={() => setShowBackfill(true)}
              className="text-xs px-2.5 py-1 rounded-lg border border-amber-200 text-amber-700 bg-amber-50 hover:bg-amber-100"
              title="إدخال يدوي عند عدم تسجيل السائق">✍️ إدخال يدوي</button>
            {hasWA && <WhatsAppButton orderId={order.id} phone={order.customer_phone} size="sm" />}
          </div>
        </div>

        {/* Customer + Financial summary */}
        <div className="px-5 py-4 grid grid-cols-2 gap-4 bg-gray-50 border-b border-gray-200">
          {/* Customer */}
          <div className="space-y-1.5">
            <p className="text-xs text-gray-400 font-semibold uppercase tracking-wide">العميل</p>
            <p className="font-bold text-gray-800">{order.customer_name}</p>
            {order.customer_phone && (
              <a href={`tel:${order.customer_phone}`} className="flex items-center gap-1.5 text-sm text-blue-600 hover:underline font-mono">
                📞 {order.customer_phone}
              </a>
            )}
            {order.customer_phone_alt && (
              <a href={`tel:${order.customer_phone_alt}`} className="flex items-center gap-1.5 text-xs text-blue-500 hover:underline font-mono">
                📱 {order.customer_phone_alt}
              </a>
            )}
            {(order.delivery_area || order.delivery_governorate) && (
              <p className="text-xs text-gray-600">
                📍 {[order.delivery_area, order.delivery_district, order.delivery_governorate].filter(Boolean).join('، ')}
              </p>
            )}
            {order.delivery_address && (
              <p className="text-xs text-gray-500 leading-relaxed">{order.delivery_address}</p>
            )}
            {order.delivery_landmark && (
              <p className="text-xs text-amber-600">🏢 {order.delivery_landmark}</p>
            )}
            {order.google_maps_url && (
              <a href={order.google_maps_url} target="_blank" rel="noopener noreferrer"
                className="text-xs text-blue-500 hover:underline flex items-center gap-1">
                🗺️ خرائط جوجل
              </a>
            )}
          </div>

          {/* Financials */}
          <div className="space-y-1.5">
            <p className="text-xs text-gray-400 font-semibold uppercase tracking-wide">المالية</p>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">قيمة الطلب</span>
                <span className="font-mono font-semibold">{fmt(order.total_value, 2)} ج.م</span>
              </div>
              {order.delivery_fees > 0 && (
                <div className="flex justify-between">
                  <span className="text-gray-500">رسوم توصيل</span>
                  <span className="font-mono">{fmt(order.delivery_fees, 2)} ج.م</span>
                </div>
              )}
              <div className="flex justify-between border-t border-gray-200 pt-1 font-bold">
                <span>الإجمالي</span>
                <span className="font-mono text-brand-700">{fmt(order.total_with_fees, 2)} ج.م</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">طريقة الدفع</span>
                <span>{PAYMENT_LABELS[order.payment_method] || order.payment_method}</span>
              </div>
              {order.collected_amount != null && (
                <div className="flex justify-between text-xs">
                  <span className="text-gray-400">محصَّل</span>
                  <span className={`font-mono font-semibold ${order.cash_variance < 0 ? 'text-red-600' : 'text-green-600'}`}>
                    {fmt(order.collected_amount, 2)} ج.م
                  </span>
                </div>
              )}
            </div>
            {/* SOFTECH Reference Block */}
            <div className="mt-3 pt-3 border-t border-gray-200 space-y-1">
              <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide">مراجع SOFTECH</p>
              {order.softech_doc_number5 && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">مستند التجهيز</span>
                  <span className="font-mono text-sm font-bold text-brand-700 bg-brand-50 px-2 py-0.5 rounded">
                    {order.softech_doc_number5}
                  </span>
                </div>
              )}
              {order.softech_doc_date5 && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">تاريخ المستند</span>
                  <span className="text-xs font-mono text-gray-600">{order.softech_doc_date5}</span>
                </div>
              )}
              {order.softech_crm_order_no && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">رقم طلب CRM</span>
                  <span className="text-xs font-mono text-gray-600">
                    {order.softech_crm_branch}-{order.softech_crm_order_no}
                  </span>
                </div>
              )}
              {order.softech_branch_code && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">فرع التنفيذ</span>
                  <span className="text-xs font-mono text-gray-600">{order.softech_branch_code}</span>
                </div>
              )}
              {order.softech_doc_ref && order.softech_doc_ref !== '0' && order.softech_doc_ref !== '' && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">رقم الفاتورة</span>
                  <span className="font-mono text-sm font-bold text-green-700 bg-green-50 px-2 py-0.5 rounded">
                    {order.softech_doc_ref} ✅
                  </span>
                </div>
              )}
              {(!order.softech_doc_ref || order.softech_doc_ref === '0' || order.softech_doc_ref === '') && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">رقم الفاتورة</span>
                  <span className="text-xs text-amber-600 font-medium">⏳ لم يُصرف بعد</span>
                </div>
              )}
            </div>
            {order.branch_name && (
              <p className="text-xs text-gray-500">🏪 {order.branch_name}</p>
            )}
          </div>
        </div>

        {/* Driver info if assigned */}
        {order.driver_name && (
          <div className="px-5 py-3 bg-indigo-50 border-b border-indigo-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-indigo-500">🚴</span>
              <span className="text-sm font-medium text-indigo-800">{order.driver_name}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-indigo-600">
              {order.dispatched_at && <span>خرج: {fmtTime(order.dispatched_at)}</span>}
              {order.delivered_at  && <span>وصل: {fmtTime(order.delivered_at)}</span>}
              {order.delivery_minutes > 0 && <span>⏱ {order.delivery_minutes} د</span>}
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex border-b border-gray-200 px-5">
          {[
            { id: 'details', label: 'الأصناف 📦' },
            { id: 'timeline', label: 'سجل الحالات 📋' },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="px-5 py-4">
          {tab === 'details' && <OrderItems orderId={order.id} />}
          {tab === 'timeline' && <StatusHistory logs={order.status_logs} />}
        </div>

        {/* Notes */}
        {order.notes && (
          <div className="px-5 pb-4">
            <p className="text-xs text-gray-400 mb-1">ملاحظات</p>
            <p className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3 leading-relaxed">{order.notes}</p>
          </div>
        )}

        {/* WhatsApp action bar */}
        {hasWA && (
          <div className="sticky bottom-0 bg-white border-t border-gray-200 px-5 py-3">
            <p className="text-xs text-gray-400 mb-2">إبلاغ العميل عبر واتساب</p>
            <WhatsAppButton orderId={order.id} phone={order.customer_phone || order.customer_phone_alt} size="lg" />
          </div>
        )}
      </div>

      {showBackfill && (
        <DeliveryBackfillModal
          order={order}
          onClose={() => setShowBackfill(false)}
          onDone={() => { setShowBackfill(false); onAction && onAction() }}
        />
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MODALS (Assign / Cancel / Fail / Cash)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function AssignModal({ order, onClose, onDone }) {
  const [driverId, setDriverId] = useState('')
  const [driverName, setDriverName] = useState('')
  const [vehicle, setVehicle]       = useState('')
  const [notes, setNotes]           = useState('')

  const { data: driversRaw } = useQuery({
    queryKey: ['delivery-drivers-active'],
    queryFn:  () => deliveryApi.listDrivers({ status: 'active' }).then(r => r.data?.results || r.data || []),
  })
  const drivers = driversRaw || []

  const mut = useMutation({
    mutationFn: () => deliveryApi.assign(order.id, { driver_id: driverId || undefined, driver_name: driverName, vehicle, notes }),
    onSuccess:  () => { onDone(); onClose() },
  })

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-800 mb-4">تكليف سائق — {order.order_number}</h2>
        <div className="space-y-3">
          {drivers.length > 0 && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">اختر من قائمة السائقين</label>
              <select value={driverId} onChange={e => { setDriverId(e.target.value); const d = drivers.find(d => String(d.id) === e.target.value); if (d) setDriverName(d.full_name) }}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
                <option value="">— اختر سائق —</option>
                {drivers.map(d => <option key={d.id} value={d.id}>{d.full_name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className="block text-xs text-gray-500 mb-1">اسم السائق</label>
            <input value={driverName} onChange={e => setDriverName(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">المركبة</label>
              <input value={vehicle} onChange={e => setVehicle(e.target.value)} placeholder="دراجة / سيارة..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">ملاحظات</label>
              <input value={notes} onChange={e => setNotes(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
            </div>
          </div>
        </div>
        {mut.isError && <p className="text-xs text-red-500 mt-2">{mut.error?.response?.data?.detail || 'حدث خطأ'}</p>}
        <div className="flex gap-3 mt-5">
          <button onClick={onClose} className="flex-1 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">إلغاء</button>
          <button disabled={(!driverName.trim() && !driverId) || mut.isPending} onClick={() => mut.mutate()}
            className="flex-1 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {mut.isPending ? 'جارٍ…' : 'تكليف السائق'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ReasonModal({ order, title, color, action, label, onClose, onDone }) {
  const [reason, setReason] = useState('')
  const mut = useMutation({
    mutationFn: () => action(order.id, { reason }),
    onSuccess:  () => { onDone(); onClose() },
  })
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h2 className={`text-lg font-bold mb-4 text-${color}-700`}>{title} — {order.order_number}</h2>
        <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3}
          placeholder="اكتب السبب هنا..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-red-400 focus:outline-none resize-none" />
        {mut.isError && <p className="text-xs text-red-500 mt-2">{mut.error?.response?.data?.detail || 'حدث خطأ'}</p>}
        <div className="flex gap-3 mt-4">
          <button onClick={onClose} className="flex-1 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">رجوع</button>
          <button disabled={!reason.trim() || mut.isPending} onClick={() => mut.mutate()}
            className={`flex-1 py-2 bg-${color}-600 text-white rounded-lg text-sm font-medium hover:bg-${color}-700 disabled:opacity-50`}>
            {mut.isPending ? 'جارٍ…' : label}
          </button>
        </div>
      </div>
    </div>
  )
}

function CashModal({ order, onClose, onDone }) {
  const expected = Number(order.total_value || 0) + Number(order.delivery_fees || 0)
  const [amount, setAmount] = useState(String(expected))
  const mut = useMutation({
    mutationFn: () => deliveryApi.collectCash(order.id, { collected_amount: Number(amount) }),
    onSuccess:  () => { onDone(); onClose() },
  })
  const variance = Number(amount) - expected
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-800 mb-4">تحصيل نقدي — {order.order_number}</h2>
        <div className="bg-gray-50 rounded-lg p-3 mb-4 text-sm space-y-1">
          <div className="flex justify-between"><span className="text-gray-500">قيمة الأصناف:</span><span className="font-mono">{fmt(order.total_value, 2)} ج.م</span></div>
          {order.delivery_fees > 0 && <div className="flex justify-between"><span className="text-gray-500">رسوم التوصيل:</span><span className="font-mono">{fmt(order.delivery_fees, 2)} ج.م</span></div>}
          <div className="flex justify-between font-bold border-t border-gray-200 pt-1"><span>الإجمالي:</span><span className="font-mono">{fmt(expected, 2)} ج.م</span></div>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">المبلغ المحصَّل *</label>
          <input type="number" value={amount} onChange={e => setAmount(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-brand-400 focus:outline-none" />
        </div>
        {amount && !isNaN(Number(amount)) && (
          <div className={`mt-2 text-xs font-medium ${variance < 0 ? 'text-red-600' : variance > 0 ? 'text-orange-600' : 'text-green-600'}`}>
            {variance < 0 ? `⚠️ عجز: ${fmt(Math.abs(variance), 2)} ج.م` : variance > 0 ? `ℹ️ زيادة: ${fmt(variance, 2)} ج.م` : '✅ مطابق تماماً'}
          </div>
        )}
        <div className="flex gap-3 mt-4">
          <button onClick={onClose} className="flex-1 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">إلغاء</button>
          <button disabled={!amount || mut.isPending} onClick={() => mut.mutate()}
            className="flex-1 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50">
            {mut.isPending ? 'جارٍ…' : 'تأكيد التحصيل'}
          </button>
        </div>
      </div>
    </div>
  )
}

function NewOrderModal({ branches, onClose, onDone }) {
  const [form, setForm] = useState({
    source_type: 'call_center', branch: '', customer_name: '',
    customer_phone: '', customer_phone_alt: '',
    delivery_address: '', delivery_area: '', delivery_governorate: '', delivery_landmark: '',
    total_value: '', delivery_fees: '0', payment_method: 'cash', notes: '',
  })
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const mut = useMutation({
    mutationFn: () => deliveryApi.create({ ...form, total_value: Number(form.total_value) || 0, delivery_fees: Number(form.delivery_fees) || 0 }),
    onSuccess: () => { onDone(); onClose() },
  })
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl p-6 overflow-y-auto max-h-[90vh]" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-800 mb-5">طلب توصيل جديد</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">مصدر الطلب *</label>
            <select value={form.source_type} onChange={e => set('source_type', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              <option value="call_center">📞 كول سنتر</option>
              <option value="branch_pos">🏪 POS الفرع</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">الفرع *</label>
            <select value={form.branch} onChange={e => set('branch', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              <option value="">اختر الفرع</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </div>
          <div className="col-span-2">
            <label className="block text-xs text-gray-500 mb-1">اسم العميل *</label>
            <input value={form.customer_name} onChange={e => set('customer_name', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">الهاتف</label>
            <input value={form.customer_phone} onChange={e => set('customer_phone', e.target.value)} dir="ltr"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">هاتف بديل</label>
            <input value={form.customer_phone_alt} onChange={e => set('customer_phone_alt', e.target.value)} dir="ltr"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div className="col-span-2">
            <label className="block text-xs text-gray-500 mb-1">العنوان التفصيلي</label>
            <textarea value={form.delivery_address} onChange={e => set('delivery_address', e.target.value)} rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none resize-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">المنطقة</label>
            <input value={form.delivery_area} onChange={e => set('delivery_area', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">المحافظة</label>
            <input value={form.delivery_governorate} onChange={e => set('delivery_governorate', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">قيمة الطلب (ج.م) *</label>
            <input type="number" value={form.total_value} onChange={e => set('total_value', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">رسوم التوصيل (ج.م)</label>
            <input type="number" value={form.delivery_fees} onChange={e => set('delivery_fees', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">طريقة الدفع</label>
            <select value={form.payment_method} onChange={e => set('payment_method', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              {Object.entries(PAYMENT_LABELS).map(([v,l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">ملاحظات</label>
            <input value={form.notes} onChange={e => set('notes', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
        </div>
        {mut.isError && <p className="text-xs text-red-500 mt-3">{JSON.stringify(mut.error?.response?.data)}</p>}
        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">إلغاء</button>
          <button disabled={!form.customer_name.trim() || !form.branch || mut.isPending} onClick={() => mut.mutate()}
            className="flex-1 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
            {mut.isPending ? 'جارٍ الحفظ…' : 'إنشاء الطلب'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// ORDER ROW ACTIONS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function OrderActions({ order, onAssign, onFail, onCancel, onCash, refetch }) {
  const mut = fn => useMutation({ mutationFn: fn, onSuccess: refetch }) // eslint-disable-line
  const acceptMut      = useMutation({ mutationFn: () => deliveryApi.accept(order.id, {}),      onSuccess: refetch }) // eslint-disable-line
  const dispatchMut    = useMutation({ mutationFn: () => deliveryApi.dispatch(order.id, {}),    onSuccess: refetch }) // eslint-disable-line
  const completeMut    = useMutation({ mutationFn: () => deliveryApi.complete(order.id, {}),    onSuccess: refetch }) // eslint-disable-line
  const partialMut     = useMutation({ mutationFn: () => deliveryApi.partial(order.id, {}),     onSuccess: refetch }) // eslint-disable-line
  const unavailableMut = useMutation({ mutationFn: () => deliveryApi.unavailable(order.id, {}), onSuccess: refetch }) // eslint-disable-line
  const closeMut       = useMutation({ mutationFn: () => deliveryApi.close(order.id, {}),       onSuccess: refetch }) // eslint-disable-line
  const returnMut      = useMutation({ mutationFn: () => deliveryApi.return(order.id, {}),      onSuccess: refetch }) // eslint-disable-line

  const btn = (label, cls, onClick, disabled = false) => (
    <button onClick={onClick} disabled={disabled}
      className={`px-3 py-1.5 text-xs rounded-lg transition-colors disabled:opacity-50 font-medium ${cls}`}>
      {label}
    </button>
  )

  switch (order.status) {
    case 'created': case 'pending_review': case 'preparing': case 'ready':
      return (<div className="flex gap-1.5 flex-wrap">
        {btn('تكليف سائق', 'bg-blue-600 text-white hover:bg-blue-700', () => onAssign(order))}
        {btn('إلغاء', 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200', () => onCancel(order))}
      </div>)
    case 'assigned':
      return (<div className="flex gap-1.5 flex-wrap">
        {btn('السائق قبل ✓', 'bg-indigo-600 text-white hover:bg-indigo-700', () => acceptMut.mutate(), acceptMut.isPending)}
        {btn('إلغاء', 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200', () => onCancel(order))}
      </div>)
    case 'driver_accepted':
      return (<div className="flex gap-1.5 flex-wrap">
        {btn('خرج للتوصيل 🚚', 'bg-amber-500 text-white hover:bg-amber-600', () => dispatchMut.mutate(), dispatchMut.isPending)}
        {btn('إلغاء', 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200', () => onCancel(order))}
      </div>)
    case 'out_for_delivery':
      return (<div className="flex gap-1.5 flex-wrap">
        {btn('تسليم ✓', 'bg-green-600 text-white hover:bg-green-700', () => completeMut.mutate(), completeMut.isPending)}
        {btn('جزئي', 'bg-lime-500 text-white hover:bg-lime-600', () => partialMut.mutate(), partialMut.isPending)}
        {btn('غير متاح', 'bg-pink-500 text-white hover:bg-pink-600', () => unavailableMut.mutate(), unavailableMut.isPending)}
        {btn('فشل ✗', 'bg-red-100 text-red-700 hover:bg-red-200 border border-red-200', () => onFail(order))}
      </div>)
    case 'customer_unavailable':
      return (<div className="flex gap-1.5 flex-wrap">
        {btn('إعادة المحاولة', 'bg-amber-500 text-white hover:bg-amber-600', () => dispatchMut.mutate(), dispatchMut.isPending)}
        {btn('فشل ✗', 'bg-red-100 text-red-700 hover:bg-red-200 border border-red-200', () => onFail(order))}
        {btn('إلغاء', 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200', () => onCancel(order))}
      </div>)
    case 'delivered': case 'partial_delivery':
      return (<div className="flex gap-1.5 flex-wrap">
        {order.payment_method === 'cash' && (
          btn('تحصيل نقدي 💵', 'bg-green-100 text-green-700 hover:bg-green-200 border border-green-300', () => onCash(order))
        )}
        {btn('إغلاق', 'bg-gray-600 text-white hover:bg-gray-700', () => closeMut.mutate(), closeMut.isPending)}
      </div>)
    case 'failed':
      return (<div className="flex gap-1.5 flex-wrap">
        {btn('إعادة', 'bg-purple-600 text-white hover:bg-purple-700', () => returnMut.mutate(), returnMut.isPending)}
      </div>)
    case 'returned':
      return btn('إغلاق', 'bg-gray-600 text-white hover:bg-gray-700', () => closeMut.mutate(), closeMut.isPending)
    default: return null
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// STATUS FILTER TABS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const STATUS_FILTERS = [
  { value: '',                    label: 'الكل' },
  { value: 'created',             label: 'جديد' },
  { value: 'assigned',            label: 'مكلَّف' },
  { value: 'driver_accepted',     label: 'قبل السائق' },
  { value: 'out_for_delivery',    label: 'في الطريق' },
  { value: 'delivered',           label: 'مُسلَّم' },
  { value: 'customer_unavailable',label: 'غير متاح' },
  { value: 'failed',              label: 'فشل' },
  { value: 'cancelled',           label: 'ملغى' },
]

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MAIN DASHBOARD
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function DeliveryDashboard() {
  const qc = useQueryClient()

  const [statusFilter, setStatusFilter] = useState('')
  const [branchFilter, setBranchFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [search,       setSearch]       = useState('')
  const [dateFrom,     setDateFrom]     = useState(_today())
  const [dateTo,       setDateTo]       = useState(_today())
  const [showNew,      setShowNew]      = useState(false)
  const [showTime,     setShowTime]     = useState(false)
  const [detailId,     setDetailId]     = useState(null)
  const [assignTarget, setAssignTarget] = useState(null)
  const [failTarget,   setFailTarget]   = useState(null)
  const [cancelTarget, setCancelTarget] = useState(null)
  const [cashTarget,   setCashTarget]   = useState(null)

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data?.results || r.data || []),
    staleTime: 300_000,
  })

  const { data: summary } = useQuery({
    queryKey: ['delivery-summary'],
    queryFn:  () => deliveryApi.summary().then(r => r.data),
    refetchInterval: 30_000,
  })

  const params = {
    ...(statusFilter ? { status: statusFilter }       : {}),
    ...(branchFilter ? { branch: branchFilter }       : {}),
    ...(sourceFilter ? { source_type: sourceFilter }  : {}),
    ...(search       ? { search }                     : {}),
    date_from: dateFrom,
    date_to:   dateTo,
  }

  const { data: ordersData, isLoading, refetch } = useQuery({
    queryKey: ['delivery-orders', params],
    queryFn:  () => deliveryApi.list(params).then(r => r.data),
    refetchInterval: 20_000,
  })
  const orders = ordersData?.results || ordersData || []

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['delivery-orders'] })
    qc.invalidateQueries({ queryKey: ['delivery-summary'] })
  }, [qc])

  return (
    <div className="p-6 space-y-5 max-w-screen-xl mx-auto" dir="rtl">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">لوحة التوصيل</h1>
          <p className="text-sm text-gray-500 mt-0.5">إدارة طلبات التوصيل — دورة الحياة الكاملة</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowNew(true)}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 flex items-center gap-2">
            + طلب جديد
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <KpiCard label="إجمالي اليوم"      value={fmt(summary.total_today)}            color="brand"  icon="📦" />
          <KpiCard label="في الانتظار"        value={fmt(summary.pending)}               color="gray"   icon="⏳" />
          <KpiCard label="مكلَّف"             value={fmt(summary.assigned)}              color="blue"   icon="👤" />
          <KpiCard label="في الطريق"          value={fmt(summary.out_for_delivery)}      color="amber"  icon="🚚" />
          <KpiCard label="مُسلَّم اليوم"      value={fmt(summary.delivered_today)}       color="green"  icon="✅" />
          <KpiCard label="فشل اليوم"          value={fmt(summary.failed_today)}          color="red"    icon="❌" />
          <KpiCard label="معدل النجاح"
            value={`${fmt(summary.success_rate_today, 1)}%`}
            sub={`متوسط: ${fmt(summary.avg_delivery_minutes)} د`}
            color={summary.success_rate_today >= 80 ? 'green' : 'amber'} icon="📊" />
          <KpiCard label="متأخرة الآن"
            value={fmt(summary.late_orders)}
            sub={`نقدي معلق: ${fmt(summary.cash_outstanding)} ج.م`}
            color={summary.late_orders > 0 ? 'red' : 'gray'} icon="⚠️" />
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-center">
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="بحث — اسم، هاتف، رقم طلب..."
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none min-w-52" />
          <select value={branchFilter} onChange={e => setBranchFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
          <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
            <option value="">كل المصادر</option>
            <option value="call_center">📞 كول سنتر</option>
            <option value="branch_pos">🏪 POS الفرع</option>
          </select>
          <button type="button" onClick={() => setShowTime(v => !v)}
            className={`flex items-center gap-1 px-3 py-2 text-xs rounded-lg border transition-colors
              ${showTime ? 'bg-brand-50 border-brand-400 text-brand-700' : 'bg-white border-gray-300 text-gray-600 hover:border-brand-400'}`}>
            🗓️ التاريخ {showTime ? '▲' : '▼'}
          </button>
        </div>
        {showTime && (
          <div className="flex flex-wrap gap-3 items-center pt-2 border-t border-gray-100">
            {[{l:'اليوم',f:_today(),t:_today()},{l:'أمس',f:_daysAgo(1),t:_daysAgo(1)},{l:'٧ أيام',f:_daysAgo(7),t:_today()},{l:'٣٠ يوم',f:_daysAgo(30),t:_today()}].map(r => (
              <button key={r.l} onClick={() => { setDateFrom(r.f); setDateTo(r.t) }}
                className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${dateFrom===r.f && dateTo===r.t ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'}`}>
                {r.l}
              </button>
            ))}
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none" />
            <span className="text-gray-400 text-xs">—</span>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
              className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none" />
          </div>
        )}
        <div className="flex gap-1.5 flex-wrap">
          {STATUS_FILTERS.map(f => (
            <button key={f.value} onClick={() => setStatusFilter(f.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
                statusFilter === f.value ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
              }`}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Orders list */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-600">{orders.length} طلب</span>
        </div>
        {isLoading && <div className="text-center py-12 text-brand-500 animate-pulse">جارٍ التحميل…</div>}
        {!isLoading && !orders.length && (
          <div className="text-center py-16 text-gray-400"><span className="text-4xl block mb-3">🛵</span>لا توجد طلبات مطابقة</div>
        )}
        <div className="divide-y divide-gray-50">
          {orders.map(order => (
            <div key={order.id}
              className={`px-5 py-4 hover:bg-gray-50/50 transition-colors ${order.is_late ? 'border-r-2 border-red-400' : ''}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-3 flex-1 min-w-0"
                  onClick={() => setDetailId(order.id)}
                  style={{ cursor: 'pointer' }}>
                  <div className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${STATUS_MAP[order.status]?.dot?.split(' ')[0] || 'bg-gray-400'}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] font-mono text-gray-400">{order.order_number}</span>
                      <span className="font-semibold text-gray-800">{order.customer_name}</span>
                      {order.customer_phone && (
                        <a href={`tel:${order.customer_phone}`} onClick={e => e.stopPropagation()}
                          className="text-xs text-blue-600 hover:underline font-mono">
                          {order.customer_phone}
                        </a>
                      )}
                      <StatusBadge status={order.status} />
                      {order.is_late && <span className="text-xs px-2 py-0.5 bg-red-100 text-red-600 rounded-full font-medium">⚠️ متأخر</span>}
                      <span className="text-xs text-gray-400">{SOURCE_LABELS[order.source_type]}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-xs text-gray-500">
                      {order.branch_name && <span>🏪 {order.branch_name}</span>}
                      {(order.delivery_area || order.delivery_governorate) && (
                        <span>📍 {[order.delivery_area, order.delivery_governorate].filter(Boolean).join('، ')}</span>
                      )}
                      {order.driver_name && <span className="text-indigo-600">🚴 {order.driver_name}</span>}
                      {order.total_with_fees > 0 && (
                        <span className="font-mono text-gray-700">{fmt(order.total_with_fees, 2)} ج.م · {PAYMENT_LABELS[order.payment_method] || ''}</span>
                      )}
                      <span className="text-gray-400">{fmtTime(order.ordered_at)}</span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 shrink-0" onClick={e => e.stopPropagation()}>
                  {/* WhatsApp quick button — only on relevant statuses */}
                  {STATUS_MAP[order.status]?.whatsapp && order.customer_phone && (
                    <WhatsAppButton orderId={order.id} phone={order.customer_phone} size="sm" />
                  )}
                  <OrderActions
                    order={order}
                    onAssign={setAssignTarget}
                    onFail={setFailTarget}
                    onCancel={setCancelTarget}
                    onCash={setCashTarget}
                    refetch={invalidate}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Detail panel */}
      {detailId && <OrderDetailPanel orderId={detailId} onClose={() => setDetailId(null)} onAction={invalidate} />}

      {/* Modals */}
      {showNew      && <NewOrderModal   branches={branches}    onClose={() => setShowNew(false)}      onDone={invalidate} />}
      {assignTarget && <AssignModal     order={assignTarget}   onClose={() => setAssignTarget(null)}  onDone={invalidate} />}
      {failTarget   && <ReasonModal     order={failTarget}     title="فشل التوصيل" color="red"    action={deliveryApi.fail}   label="تأكيد الفشل"   onClose={() => setFailTarget(null)}   onDone={invalidate} />}
      {cancelTarget && <ReasonModal     order={cancelTarget}   title="إلغاء الطلب" color="red"    action={deliveryApi.cancel} label="تأكيد الإلغاء" onClose={() => setCancelTarget(null)} onDone={invalidate} />}
      {cashTarget   && <CashModal       order={cashTarget}     onClose={() => setCashTarget(null)}    onDone={invalidate} />}
    </div>
  )
}
