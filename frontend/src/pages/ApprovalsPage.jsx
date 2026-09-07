/**
 * ApprovalsPage — Generic approval inbox + history
 * All approval workflows: HR requests, batch quarantine, pricing, etc.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { approvalsApi } from '../api/client'

const STATUS_LABELS = {
  pending:   { label: 'بانتظار القرار', color: 'bg-amber-100 text-amber-800' },
  in_review: { label: 'قيد المراجعة',   color: 'bg-amber-100 text-amber-800' },
  approved:  { label: 'موافق عليه',     color: 'bg-green-100 text-green-800' },
  rejected:  { label: 'مرفوض',          color: 'bg-red-100 text-red-800' },
  cancelled: { label: 'ملغى',           color: 'bg-gray-100 text-gray-600' },
  expired:   { label: 'منتهي الصلاحية', color: 'bg-gray-100 text-gray-600' },
}

function StatusBadge({ status }) {
  const cfg = STATUS_LABELS[status] || { label: status, color: 'bg-gray-100 text-gray-600' }
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cfg.color}`}>{cfg.label}</span>
}

function DecideModal({ request, onClose }) {
  const qc = useQueryClient()
  const [decision, setDecision] = useState('approved')
  const [notes, setNotes]       = useState('')
  const [error, setError]       = useState(null)

  const mutation = useMutation({
    mutationFn: () => approvalsApi.decide(request.id, { decision, notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['approvals'] })
      onClose()
    },
    onError: e => setError(e.response?.data?.detail || 'حدث خطأ'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-1">اتخاذ قرار</h3>
        <p className="text-sm text-gray-500 mb-4">{request.title}</p>

        <div className="flex gap-3 mb-4">
          {['approved','rejected'].map(d => (
            <button key={d} onClick={() => setDecision(d)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border-2 transition ${
                decision === d
                  ? d === 'approved' ? 'border-green-500 bg-green-50 text-green-700'
                                     : 'border-red-500 bg-red-50 text-red-700'
                  : 'border-gray-200 text-gray-500'
              }`}>
              {d === 'approved' ? '✅ موافقة' : '❌ رفض'}
            </button>
          ))}
        </div>

        <textarea
          value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="ملاحظات (اختياري)..."
          className="w-full border rounded-lg p-3 text-sm resize-none h-24 mb-4"
        />

        {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">
            إلغاء
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'جاري...' : 'تأكيد القرار'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ApprovalsPage() {
  const [tab, setTab]         = useState('pending')
  const [selected, setSelected] = useState(null)

  // Pending tab → only requests awaiting MY decision (includes multi-step in_review).
  // History tab → my/all closed requests (backend now accepts a comma status list).
  const { data, isLoading } = useQuery({
    queryKey: ['approvals', tab],
    queryFn:  () => (tab === 'pending'
      ? approvalsApi.pending({})
      : approvalsApi.requests({ status: 'approved,rejected,cancelled,expired' })
    ).then(r => r.data),
  })

  const requests = data?.results || data || []

  return (
    <div className="p-6 max-w-5xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">صندوق الموافقات</h1>
          <p className="text-sm text-gray-500 mt-1">إدارة طلبات الموافقة لجميع سير العمل</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'pending', label: 'بانتظار القرار' },
          { key: 'history', label: 'السجل' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
      ) : requests.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <div className="text-4xl mb-3">✅</div>
          <p>{tab === 'pending' ? 'لا توجد طلبات بانتظار القرار' : 'لا يوجد سجل'}</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-right font-semibold text-gray-600">العنوان</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">النوع</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">مقدم الطلب</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">التاريخ</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {requests.map(req => (
                <tr key={req.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{req.title}</td>
                  <td className="px-4 py-3 text-gray-500">{req.workflow_name || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{req.requested_by_name || '—'}</td>
                  <td className="px-4 py-3"><StatusBadge status={req.status} /></td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {req.requested_at ? new Date(req.requested_at).toLocaleDateString('ar-EG') : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {tab === 'pending' && (
                      <button
                        onClick={() => setSelected(req)}
                        className="px-3 py-1 bg-brand-600 text-white rounded-lg text-xs hover:bg-brand-700"
                      >
                        اتخاذ قرار
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && <DecideModal request={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
