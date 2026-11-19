/**
 * ApprovalsPage — Generic approval inbox + history
 * All approval workflows: HR requests, batch quarantine, pricing, etc.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { approvalsApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import SortTh from '../components/SortTh'
import useSortableRows from '../hooks/useSortableRows'
import useServerSort from '../hooks/useServerSort'
import useGridKeyboard from '../hooks/useGridKeyboard'
import { canBulkDecide, decideMany } from './approvalsBulk'

const SERVER_SORT_KEYS = ['title', 'workflow__name_ar', 'requested_by_sort', 'status_rank', 'requested_at']
const SERVER_KEY = { title: 'title', workflow: 'workflow__name_ar', by: 'requested_by_sort', status: 'status_rank', date: 'requested_at' }
const CLIENT_KEYS = ['title', 'workflow', 'by', 'status', 'date']
const getValue = (r, k) => ({
  title: r.title, workflow: r.workflow_name, by: r.requested_by_name,
  status: (STATUS_LABELS[r.status] || {}).label || r.status, date: r.requested_at,
}[k])

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
    // FE-10: Esc closes; focus starts on «تأكيد القرار», so from the grid ↓ Enter Enter approves one.
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl"
         role="dialog" aria-modal="true" aria-label="اتخاذ قرار"
         onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-1">اتخاذ قرار</h3>
        <p className="text-sm text-gray-500 mb-4">{request.title}</p>

        <div className="flex gap-3 mb-4" data-tour="hr-approvals-decision">
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

        <textarea data-tour="hr-approvals-notes"
          value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="ملاحظات (اختياري)..."
          className="w-full border rounded-lg p-3 text-sm resize-none h-24 mb-4"
        />

        {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">
            إلغاء
          </button>
          <button data-tour="hr-approvals-confirm" autoFocus
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
  useHelpTab(tab)
  const [selected, setSelected] = useState(null)
  const [ordering, setOrdering] = useState('')
  const qc = useQueryClient()

  // Pending tab → only requests awaiting MY decision (includes multi-step in_review).
  // History tab → my/all closed requests (backend now accepts a comma status list).
  const { data, isLoading } = useQuery({
    queryKey: ['approvals', tab, tab === 'history' ? ordering : ''],
    queryFn:  () => (tab === 'pending'
      ? approvalsApi.pending({})
      : approvalsApi.requests({ status: 'approved,rejected,cancelled,expired', ordering: ordering || undefined })
    ).then(r => r.data),
    // keep the rows on screen while a re-sort loads, but never show the other tab's rows
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey?.[1] === tab ? prev : undefined),
  })

  const requests = data?.results || data || []

  // Pending = every row is loaded → sort in the browser. History is paged by the server → the server sorts.
  const client = useSortableRows(requests, { getValue, persistKey: 'approvals-pending', keys: CLIENT_KEYS })
  const server = useServerSort(ordering, setOrdering, { allowed: SERVER_SORT_KEYS })
  const th = (key, type, label) => (
    <SortTh {...(tab === 'pending' ? client.headerProps(key, type) : server.headerProps(SERVER_KEY[key], type))}
            className="px-4 py-3 text-right font-semibold text-gray-600">{label}</SortTh>
  )
  const rows = tab === 'pending' ? client.sorted : requests

  // FE-10: tick rows (Space / Ctrl+A / the box) and decide them together; Enter opens the
  // active row's decision window. Only on «بانتظار القرار» — history is read-only.
  const pending = tab === 'pending'
  const [ticked, setTicked] = useState(() => new Set())
  const [bulkNote, setBulkNote] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkResult, setBulkResult] = useState(null)
  const visibleIds = pending ? rows.map(r => r.id) : []
  const tickedIds = visibleIds.filter(id => ticked.has(id))        // rows that left the list drop out
  const allTicked = visibleIds.length > 0 && tickedIds.length === visibleIds.length
  const toggle = (id) => setTicked(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const toggleAll = () => setTicked(allTicked ? new Set() : new Set(visibleIds))
  const kb = useGridKeyboard({
    rows: pending ? rows : [], getKey: r => r.id, enabled: pending && !selected && !bulkBusy,
    onToggle: r => toggle(r.id), onSelectAll: toggleAll, onConfirm: r => setSelected(r),
  })

  const runBulk = async (decision) => {
    if (!canBulkDecide(decision, tickedIds.length, bulkNote) || bulkBusy) return
    setBulkBusy(true); setBulkResult(null)
    // titles kept now: decided rows leave the list when it refreshes
    const titles = Object.fromEntries(tickedIds.map(id => [id, requests.find(r => r.id === id)?.title]))
    try {
      const res = await decideMany(tickedIds, { decision, notes: bulkNote.trim() }, approvalsApi.decide)
      setBulkResult({ decision, titles, ...res })
      setTicked(new Set(res.failed.map(f => f.id)))                // keep only what still needs attention
      if (!res.failed.length) setBulkNote('')
    } finally {
      setBulkBusy(false)
      qc.invalidateQueries({ queryKey: ['approvals'] })
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-6" data-tour="hr-approvals-header">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">صندوق الموافقات</h1>
          <p className="text-sm text-gray-500 mt-1">إدارة طلبات الموافقة لجميع سير العمل</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6" data-tour="hr-approvals-tabs">
        {[
          { key: 'pending', label: 'بانتظار القرار' },
          { key: 'history', label: 'السجل' },
        ].map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); setBulkResult(null) }}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* outside the table: approving the last requests empties the list, and the result must stay */}
      {pending && bulkResult && (
        <div className="mb-3 rounded-xl border border-gray-200 bg-white p-3 text-sm" role="status" data-testid="approvals-bulk-result">
          <span className={bulkResult.failed.length ? 'text-amber-700' : 'text-green-700'}>
            {bulkResult.decision === 'approved' ? 'تمت الموافقة على' : 'تم رفض'} {bulkResult.done.length}
            {bulkResult.failed.length ? ` · تعذّر ${bulkResult.failed.length} (ما زالت محددة):` : ''}
          </span>
          {bulkResult.failed.length > 0 && (
            <ul className="mt-1 list-disc pr-5 text-red-700">
              {bulkResult.failed.map(f => <li key={f.id}>{bulkResult.titles[f.id] || `#${f.id}`} — {f.detail}</li>)}
            </ul>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
      ) : requests.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <div className="text-4xl mb-3">✅</div>
          <p>{tab === 'pending' ? 'لا توجد طلبات بانتظار القرار' : 'لا يوجد سجل'}</p>
        </div>
      ) : (
        <>
        {pending && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white p-3"
               data-tour="hr-approvals-bulk" data-testid="approvals-bulk-bar">
            <span className="text-sm text-gray-600 min-w-[5.5rem]">
              {tickedIds.length ? `محدد: ${tickedIds.length}` : 'لا شيء محدد'}
            </span>
            <input value={bulkNote} onChange={e => setBulkNote(e.target.value)} disabled={bulkBusy}
                   aria-label="ملاحظة للقرار الجماعي"
                   placeholder="ملاحظة (مطلوبة مع الرفض)..."
                   className="flex-1 min-w-[12rem] border rounded-lg px-3 py-1.5 text-sm" />
            <button onClick={() => runBulk('approved')}
                    disabled={bulkBusy || !canBulkDecide('approved', tickedIds.length, bulkNote)}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-40">
              {bulkBusy ? 'جاري...' : `✅ موافقة على المحدد${tickedIds.length ? ` (${tickedIds.length})` : ''}`}
            </button>
            <button onClick={() => runBulk('rejected')}
                    disabled={bulkBusy || !canBulkDecide('rejected', tickedIds.length, bulkNote)}
                    title={tickedIds.length && !bulkNote.trim() ? 'اكتب سبب الرفض في الملاحظة' : undefined}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium border border-red-300 text-red-700 hover:bg-red-50 disabled:opacity-40">
              {`❌ رفض المحدد${tickedIds.length ? ` (${tickedIds.length})` : ''}`}
            </button>
          </div>
        )}
        <div {...kb.containerProps}
             className={`bg-white rounded-xl border border-gray-200 overflow-hidden ${kb.containerProps.className}`}
             data-tour="hr-approvals-table" data-testid="approvals-grid">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                {pending && (
                  <th className="px-3 py-3 w-8">
                    <input type="checkbox" aria-label="تحديد الكل" checked={allTicked} onChange={toggleAll} />
                  </th>
                )}
                {th('title', 'text', 'العنوان')}
                {th('workflow', 'text', 'النوع')}
                {th('by', 'text', 'مقدم الطلب')}
                {th('status', 'text', 'الحالة')}
                {th('date', 'date', 'التاريخ')}
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(req => {
                const rp = pending ? kb.rowProps(req) : {}
                return (
                <tr key={req.id} {...rp}
                    className={`border-b border-gray-100 hover:bg-gray-50 ${ticked.has(req.id) && pending ? 'bg-brand-50' : ''} ${rp.className || ''}`}>
                  {pending && (
                    <td className="px-3 py-3">
                      <input type="checkbox" aria-label={`تحديد ${req.title}`} checked={ticked.has(req.id)}
                             onChange={() => toggle(req.id)} />
                    </td>
                  )}
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
                        data-tour="hr-approvals-decide"
                        onClick={() => setSelected(req)}
                        className="px-3 py-1 bg-brand-600 text-white rounded-lg text-xs hover:bg-brand-700"
                      >
                        اتخاذ قرار
                      </button>
                    )}
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {pending && (
          <p className="mt-2 text-xs text-gray-400">
            ⌨ ↑↓ تنقّل · مسافة تحديد · Ctrl+A تحديد الكل · Enter يفتح القرار (Enter مرة ثانية يؤكد، Esc يقفل)
          </p>
        )}
        </>
      )}

      {selected && <DecideModal request={selected} onClose={() => {
        setSelected(null)
        setTimeout(() => kb.containerProps.ref.current?.focus(), 0)   // the keys keep working
      }} />}
    </div>
  )
}
