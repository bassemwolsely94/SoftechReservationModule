/**
 * PaymentAuditPage — Bank Statement Import + Exception Triage
 * Covers: upload statement, run matching, review exceptions
 */
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { paymentAuditApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import useServerSort from '../hooks/useServerSort'
import SortTh from '../components/SortTh'

const EXC_SORT = ['exception_type', 'payment__amount', 'payment__reference_number', 'status', 'created_at']
const STMT_SORT = ['bank_name', 'total_lines', 'matched_lines', 'status', 'imported_at']

// type / status labels come from the server (exception_type_label, status_label)

const EXCEPTION_STATUS_COLORS = {
  open:          'bg-amber-100 text-amber-800',
  investigating: 'bg-amber-100 text-amber-800',
  resolved:   'bg-green-100 text-green-800',
  dismissed:  'bg-gray-100 text-gray-500',
  escalated:  'bg-red-100 text-red-700',
}

function UploadModal({ onClose }) {
  const qc       = useQueryClient()
  const fileRef  = useRef(null)
  const [file, setFile]     = useState(null)
  const [bankRef, setBankRef] = useState('')
  const [err, setErr]       = useState(null)

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('file', file)
      if (bankRef) fd.append('bank_reference', bankRef)
      return paymentAuditApi.uploadStatement(fd)
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['payment-audit', 'statements'] }); onClose() },
    onError:   e  => setErr(e.response?.data?.detail || 'فشل الرفع'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-4">رفع كشف حساب بنكي</h3>
        <div className="mb-4">
          <label className="block text-xs text-gray-500 mb-1">المرجع البنكي (اختياري)</label>
          <input value={bankRef} onChange={e => setBankRef(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm" />
        </div>
        <div className="mb-4">
          <label className="block text-xs text-gray-500 mb-1">الملف (CSV / Excel)</label>
          <input type="file" ref={fileRef} data-tour="finance-payment-audit-upload-file" accept=".csv,.xlsx,.xls"
            onChange={e => setFile(e.target.files[0])}
            className="w-full text-sm" />
        </div>
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button data-tour="finance-payment-audit-upload-save" onClick={() => upload.mutate()} disabled={upload.isPending || !file}
            className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg disabled:opacity-50">
            {upload.isPending ? 'جاري الرفع...' : 'رفع'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ResolveModal({ exception, onClose }) {
  const qc    = useQueryClient()
  const [note, setNote] = useState('')
  const [err, setErr]   = useState(null)

  const resolve = useMutation({
    mutationFn: () => paymentAuditApi.resolveException(exception.id, { resolution_notes: note }),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['payment-audit', 'exceptions'] }); onClose() },
    onError:    e  => setErr(e.response?.data?.detail || 'خطأ'),
  })

  const dismiss = useMutation({
    mutationFn: () => paymentAuditApi.dismissException(exception.id),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['payment-audit', 'exceptions'] }); onClose() },
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-1">معالجة الاستثناء</h3>
        <p className="text-sm text-gray-500 mb-4">
          {exception.exception_type_label || exception.exception_type}{exception.payment_amount ? ' — ' + Number(exception.payment_amount).toLocaleString('ar-EG') + ' ج' : ''}
        </p>
        <textarea data-tour="finance-payment-audit-note" value={note} onChange={e => setNote(e.target.value)}
          placeholder="ملاحظة التسوية..."
          className="w-full border rounded-lg p-3 text-sm resize-none h-20 mb-4" />
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button data-tour="finance-payment-audit-dismiss" onClick={() => dismiss.mutate()} disabled={dismiss.isPending}
            className="px-4 py-2 text-sm text-gray-500 border rounded-lg hover:bg-gray-50 disabled:opacity-50">
            تجاهل
          </button>
          <button data-tour="finance-payment-audit-resolve" onClick={() => resolve.mutate()} disabled={resolve.isPending}
            className="px-5 py-2 text-sm bg-green-600 text-white rounded-lg disabled:opacity-50">
            {resolve.isPending ? 'جاري...' : 'حل الاستثناء'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function PaymentAuditPage() {
  const qc = useQueryClient()
  const [tab, setTab]       = useState('exceptions')
  useHelpTab(tab)
  const [showUpload, setShowUpload] = useState(false)
  const [resolving, setResolving]   = useState(null)

  const [excOrdering, setExcOrdering]   = useState('')
  const [stmtOrdering, setStmtOrdering] = useState('')
  const excSort  = useServerSort(excOrdering,  setExcOrdering,  { allowed: EXC_SORT }).headerProps
  const stmtSort = useServerSort(stmtOrdering, setStmtOrdering, { allowed: STMT_SORT }).headerProps
  const { data: stmtsData, isLoading: stmtsLoading } = useQuery({
    queryKey: ['payment-audit', 'statements', stmtOrdering],
    queryFn:  () => paymentAuditApi.statements(stmtOrdering ? { ordering: stmtOrdering } : {}).then(r => r.data),
    enabled:  tab === 'statements',
  })

  const { data: excData, isLoading: excLoading } = useQuery({
    queryKey: ['payment-audit', 'exceptions', excOrdering],
    queryFn:  () => paymentAuditApi.exceptions({ status: 'open', ...(excOrdering ? { ordering: excOrdering } : {}) }).then(r => r.data),
    enabled:  tab === 'exceptions',
  })

  const runMatch = useMutation({
    mutationFn: id => paymentAuditApi.runMatching(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['payment-audit', 'statements'] }),
  })

  const statements = stmtsData?.results || stmtsData || []
  const exceptions  = excData?.results  || excData   || []

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">مراجعة المدفوعات</h1>
          <p className="text-sm text-gray-500 mt-1">كشوف الحساب البنكية · مطابقة المدفوعات · استثناءات</p>
        </div>
        <button data-tour="finance-payment-audit-upload" onClick={() => setShowUpload(true)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700">
          + رفع كشف حساب
        </button>
      </div>

      <div data-tour="finance-payment-audit-tabs" className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'exceptions', label: '⚠️ الاستثناءات' },
          { key: 'statements', label: '🏦 الكشوف البنكية' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
            {t.key === 'exceptions' && exceptions.length > 0 && (
              <span className="mr-2 bg-red-500 text-white text-xs rounded-full px-1.5">
                {exceptions.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Exceptions tab */}
      {tab === 'exceptions' && (
        excLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : exceptions.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-4xl mb-3">✅</div>
            <p>لا توجد استثناءات مفتوحة</p>
          </div>
        ) : (
          <div data-tour="finance-payment-audit-exceptions" className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <SortTh {...excSort('exception_type')} className="px-4 py-3 text-right font-semibold text-gray-600">نوع الاستثناء</SortTh>
                  <SortTh {...excSort('payment__amount', 'number')} className="px-4 py-3 text-right font-semibold text-gray-600">المبلغ</SortTh>
                  <SortTh {...excSort('payment__reference_number')} className="px-4 py-3 text-right font-semibold text-gray-600">المرجع</SortTh>
                  <SortTh {...excSort('status')} className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</SortTh>
                  <SortTh {...excSort('created_at', 'date')} className="px-4 py-3 text-right font-semibold text-gray-600">التاريخ</SortTh>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {exceptions.map(ex => (
                  <tr key={ex.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">
                      {ex.exception_type_label || ex.exception_type}
                    </td>
                    <td className="px-4 py-3 font-semibold">
                      {ex.payment_amount ? Number(ex.payment_amount).toLocaleString('ar-EG') + ' ج' : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                      {ex.payment_ref || '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${EXCEPTION_STATUS_COLORS[ex.status] || 'bg-gray-100'}`}>
                        {ex.status_label || ex.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {ex.created_at ? new Date(ex.created_at).toLocaleDateString('ar-EG') : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {ex.status === 'open' && (
                        <button data-tour="finance-payment-audit-handle" onClick={() => setResolving(ex)}
                          className="text-xs text-brand-600 hover:underline">
                          معالجة
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Statements tab */}
      {tab === 'statements' && (
        stmtsLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : statements.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p>لا توجد كشوف حساب مرفوعة</p>
          </div>
        ) : (
          <div data-tour="finance-payment-audit-statements" className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <SortTh {...stmtSort('bank_name')} className="px-4 py-3 text-right font-semibold text-gray-600">البنك / الحساب</SortTh>
                  <SortTh {...stmtSort('total_lines', 'number')} className="px-4 py-3 text-right font-semibold text-gray-600">إجمالي السطور</SortTh>
                  <SortTh {...stmtSort('matched_lines', 'number')} className="px-4 py-3 text-right font-semibold text-gray-600">مطابق</SortTh>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">نسبة المطابقة</th>
                  <SortTh {...stmtSort('status')} className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</SortTh>
                  <SortTh {...stmtSort('imported_at', 'date')} className="px-4 py-3 text-right font-semibold text-gray-600">التاريخ</SortTh>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {statements.map(s => (
                  <tr key={s.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-xs">
                      {s.bank_name || `#${s.id}`}
                      {s.account_number && <span className="text-gray-400 font-mono"> · {s.account_number}</span>}
                    </td>
                    <td className="px-4 py-3">{s.total_lines ?? '—'}</td>
                    <td className="px-4 py-3">{s.matched_lines ?? '—'}</td>
                    <td className="px-4 py-3">
                      {s.match_rate != null ? (
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-gray-200 rounded-full h-1.5">
                            <div className="bg-green-500 h-1.5 rounded-full"
                              style={{ width: `${Math.min(100, Math.round(s.match_rate))}%` }} />
                          </div>
                          <span className="text-xs">{Math.round(s.match_rate)}%</span>
                        </div>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        s.status === 'completed' ? 'bg-green-100 text-green-800' :
                        s.status === 'pending' ? 'bg-amber-100 text-amber-800' :
                        s.status === 'failed' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-600'
                      }`}>
                        {s.status_label || s.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {s.imported_at ? new Date(s.imported_at).toLocaleDateString('ar-EG') : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {s.status === 'pending' && (
                        <button
                          data-tour="finance-payment-audit-run-matching"
                          onClick={() => runMatch.mutate(s.id)}
                          disabled={runMatch.isPending}
                          className="text-xs text-brand-600 hover:underline disabled:opacity-50"
                        >
                          تشغيل المطابقة
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {showUpload && <UploadModal onClose={() => setShowUpload(false)} />}
      {resolving  && <ResolveModal exception={resolving} onClose={() => setResolving(null)} />}
    </div>
  )
}
