/**
 * BatchesPage — FEFO Batch Management + Near-Expiry Dashboard
 * Covers: batch list, near-expiry KPIs, active alerts, quarantine action
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { batchesApi } from '../api/client'

function KpiCard({ label, value, sub, color = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function QuarantineModal({ batch, onClose }) {
  const qc    = useQueryClient()
  const [reason, setReason] = useState('')
  const [err, setErr]       = useState(null)

  const mutation = useMutation({
    mutationFn: () => batchesApi.quarantine(batch.id, reason),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['batches'] }); onClose() },
    onError:   e  => setErr(e.response?.data?.detail || 'حدث خطأ'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-1">عزل دفعة</h3>
        <p className="text-sm text-gray-500 mb-4">
          {batch.item_name} — دفعة {batch.batch_number}
        </p>
        <textarea
          value={reason} onChange={e => setReason(e.target.value)}
          placeholder="سبب العزل (مطلوب)..."
          className="w-full border rounded-lg p-3 text-sm resize-none h-24 mb-4"
        />
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !reason.trim()}
            className="px-5 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'جاري...' : 'تأكيد العزل'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function BatchesPage() {
  const [tab, setTab]           = useState('alerts')
  const [quarantineBatch, setQ] = useState(null)
  const [filters, setFilters]   = useState({ expiring_in_days: 180 })

  const { data: summary } = useQuery({
    queryKey: ['batches', 'near-expiry-summary'],
    queryFn:  () => batchesApi.nearExpirySummary({}).then(r => r.data),
  })

  const { data: alertsData, isLoading: alertsLoading } = useQuery({
    queryKey: ['batches', 'alerts'],
    queryFn:  () => batchesApi.alerts({}).then(r => r.data),
    enabled:  tab === 'alerts',
  })

  const { data: batchData, isLoading: batchLoading } = useQuery({
    queryKey: ['batches', 'list', filters],
    queryFn:  () => batchesApi.list(filters).then(r => r.data),
    enabled:  tab === 'list',
  })

  const alerts  = alertsData?.results || alertsData || []
  const batches = batchData?.results  || batchData  || []

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">إدارة الدفعات (FEFO)</h1>
        <p className="text-sm text-gray-500 mt-1">مراقبة انتهاء الصلاحية · نظام الصرف الأول انتهاء أولاً</p>
      </div>

      {/* KPI cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <KpiCard label="دفعات تنتهي خلال 30 يوم"  value={summary.lt_30?.batches}  sub={`${summary.lt_30?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`}  color="text-red-600" />
          <KpiCard label="دفعات تنتهي خلال 90 يوم"  value={summary.lt_90?.batches}  sub={`${summary.lt_90?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`}  color="text-amber-600" />
          <KpiCard label="دفعات تنتهي خلال 180 يوم" value={summary.lt_180?.batches} sub={`${summary.lt_180?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`} color="text-yellow-600" />
          <KpiCard label="قيمة البضاعة المعرضة للخطر" value={summary.total_at_risk_value != null ? `${Math.round(summary.total_at_risk_value).toLocaleString('ar-EG')} ج` : '—'} color="text-gray-700" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'alerts', label: '🚨 تنبيهات الانتهاء' },
          { key: 'list',   label: '📦 قائمة الدفعات'   },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Alerts tab */}
      {tab === 'alerts' && (
        alertsLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-4xl mb-3">✅</div>
            <p>لا توجد تنبيهات انتهاء صلاحية نشطة</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الفرع</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">رقم الدفعة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ الانتهاء</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الكمية</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الحد (أيام)</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map(a => (
                  <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{a.batch?.item_name || a.item_name || '—'}</td>
                    <td className="px-4 py-3 text-gray-500">{a.batch?.branch_name || '—'}</td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{a.batch?.batch_number || '—'}</td>
                    <td className="px-4 py-3 text-red-600 font-medium">
                      {a.batch?.expiry_date ? new Date(a.batch.expiry_date).toLocaleDateString('ar-EG') : '—'}
                    </td>
                    <td className="px-4 py-3">{a.batch?.current_qty ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-800">
                        {a.threshold_days} يوم
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Batch list tab */}
      {tab === 'list' && (
        <>
          <div className="flex gap-3 mb-4">
            <select
              value={filters.expiring_in_days}
              onChange={e => setFilters(f => ({ ...f, expiring_in_days: e.target.value }))}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              <option value={30}>تنتهي خلال 30 يوم</option>
              <option value={90}>تنتهي خلال 90 يوم</option>
              <option value={180}>تنتهي خلال 180 يوم</option>
              <option value={365}>تنتهي خلال سنة</option>
            </select>
            <select
              value={filters.is_quarantined || ''}
              onChange={e => setFilters(f => ({ ...f, is_quarantined: e.target.value || undefined }))}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              <option value="">الكل</option>
              <option value="false">غير معزول</option>
              <option value="true">في العزل</option>
            </select>
          </div>

          {batchLoading ? (
            <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
          ) : batches.length === 0 ? (
            <div className="text-center py-16 text-gray-400">لا توجد دفعات بهذه المعايير</div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الفرع</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">رقم الدفعة</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ الانتهاء</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الكمية</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {batches.map(b => (
                    <tr key={b.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium">{b.item_name || b.item?.name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500">{b.branch_name || b.branch?.name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs">{b.batch_number}</td>
                      <td className="px-4 py-3 text-gray-700">
                        {b.expiry_date ? new Date(b.expiry_date).toLocaleDateString('ar-EG') : '—'}
                      </td>
                      <td className="px-4 py-3">{b.current_qty}</td>
                      <td className="px-4 py-3">
                        {b.is_quarantined ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">معزول</span>
                        ) : b.is_expired ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">منتهي</span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">نشط</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {!b.is_quarantined && !b.is_expired && (
                          <button
                            onClick={() => setQ(b)}
                            className="text-xs text-red-600 hover:underline"
                          >
                            عزل
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {quarantineBatch && <QuarantineModal batch={quarantineBatch} onClose={() => setQ(null)} />}
    </div>
  )
}
