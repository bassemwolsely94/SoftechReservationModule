import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { transfersApi, branchesApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Status config ─────────────────────────────────────────────────────────────

const STATUS = {
  draft:          { label: 'مسودة',               dot: '#9ca3af', bg: '#f9fafb', text: '#6b7280',  icon: '📝' },
  pending:        { label: 'بانتظار الموافقة',    dot: '#f59e0b', bg: '#fffbeb', text: '#92400e',  icon: '⏳' },
  approved:       { label: 'معتمد',               dot: '#3b82f6', bg: '#eff6ff', text: '#1e40af',  icon: '✅' },
  rejected:       { label: 'مرفوض',               dot: '#ef4444', bg: '#fef2f2', text: '#991b1b',  icon: '❌' },
  needs_revision: { label: 'يحتاج تعديل',         dot: '#f59e0b', bg: '#fefce8', text: '#713f12',  icon: '✏️' },
  sent_to_erp:    { label: 'تم الإرسال للـ ERP',  dot: '#8b5cf6', bg: '#f5f3ff', text: '#5b21b6',  icon: '📤' },
  completed:      { label: 'مكتمل',               dot: '#10b981', bg: '#f0fdf4', text: '#166534',  icon: '🎉' },
  cancelled:      { label: 'ملغي',                dot: '#d1d5db', bg: '#f9fafb', text: '#9ca3af',  icon: '🚫' },
}

const KANBAN_COLS = ['draft','pending','needs_revision','approved','sent_to_erp','completed']

function timeAgo(dt) {
  if (!dt) return '—'
  try { return formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }) } catch { return '' }
}

function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.draft
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.text }}>
      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: s.dot }} />
      {s.label}
    </span>
  )
}

// ── Item Search ───────────────────────────────────────────────────────────────

function ItemSearch({ onSelect }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const { data: results } = useQuery({
    queryKey: ['item-search', q],
    queryFn: () => itemsApi.list({ search: q, page_size: 10 }).then(r => r.data.results || r.data),
    enabled: q.length >= 2,
    staleTime: 10_000,
  })
  return (
    <div className="relative">
      <input className="input-field text-sm" placeholder="ابحث بالاسم أو الكود..."
        value={q} onChange={e => { setQ(e.target.value); setOpen(true) }} autoComplete="off" />
      {open && q.length >= 2 && results?.length > 0 && (
        <div className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-56 overflow-y-auto">
          {results.map(item => (
            <button key={item.id} type="button"
              className="w-full text-right px-4 py-2.5 hover:bg-brand-50 transition-colors border-b border-gray-50 last:border-0"
              onClick={() => { onSelect(item); setQ(''); setOpen(false) }}>
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold text-gray-800 text-sm truncate">{item.name}</div>
                {item.unit_price > 0 && (
                  <span className="flex-shrink-0 text-xs font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                    {Number(item.unit_price).toFixed(2)} ج.م
                  </span>
                )}
              </div>
              <div className="text-xs text-blue-500 font-mono">كود: {item.softech_id}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Create Request Modal ──────────────────────────────────────────────────────

function CreateRequestModal({ branches, userBranchId, onClose, onCreated }) {
  const [sourceBranch, setSourceBranch]           = useState(String(userBranchId || ''))
  const [destinationBranch, setDestinationBranch] = useState('')
  const [notes, setNotes]                         = useState('')
  const [items, setItems]                         = useState([])
  const [itemStocks, setItemStocks]               = useState({})
  const [submitAndSend, setSubmitAndSend]         = useState(false)
  const [submitting, setSubmitting]               = useState(false)
  const [error, setError]                         = useState('')
  const qc = useQueryClient()

  useEffect(() => {
    if (items.length === 0) return
    items.forEach(row => {
      if (itemStocks[row.item.id]) return
      itemsApi.stock(row.item.id)
        .then(res => setItemStocks(prev => ({ ...prev, [row.item.id]: res.data || [] })))
        .catch(() => {})
    })
  }, [items]) // eslint-disable-line react-hooks/exhaustive-deps

  function addItem(item) {
    if (items.find(i => i.item.id === item.id)) return
    setItems(prev => [...prev, { item, qty: '', notes: '' }])
    itemsApi.stock(item.id)
      .then(res => setItemStocks(prev => ({ ...prev, [item.id]: res.data || [] })))
      .catch(() => {})
  }
  function updateItem(idx, field, value) {
    setItems(prev => prev.map((row, i) => i === idx ? { ...row, [field]: value } : row))
  }
  function removeItem(idx) { setItems(prev => prev.filter((_, i) => i !== idx)) }

  async function handleSubmit() {
    if (!sourceBranch)      { setError('اختر الفرع الطالب'); return }
    if (!destinationBranch) { setError('اختر الفرع المصدر'); return }
    if (sourceBranch === destinationBranch) { setError('الفرعان لا يمكن أن يكونا نفس الفرع'); return }
    if (items.length === 0) { setError('أضف صنفاً واحداً على الأقل'); return }
    const bad = items.find(i => !i.qty || Number(i.qty) <= 0)
    if (bad) { setError(`أدخل الكمية لـ: ${bad.item.name}`); return }

    setSubmitting(true); setError('')
    try {
      const payload = {
        requesting_branch: Number(sourceBranch),
        supplying_branch:  Number(destinationBranch),
        notes,
        items: items.map(i => ({ item: i.item.id, quantity: i.qty, notes: i.notes || '' })),
      }
      const res = await transfersApi.create(payload)
      const newId = res.data.id
      if (submitAndSend) await transfersApi.submit(newId)
      qc.invalidateQueries(['transfers'])
      onCreated(newId, submitAndSend)
      onClose()
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' — ') : 'حدث خطأ')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <div>
            <h2 className="font-bold text-gray-900">طلب تحويل مخزون جديد</h2>
            <p className="text-xs text-gray-400 mt-0.5">يمكنك إضافة عدة أصناف · الطلب لا يؤثر على المخزون</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl p-1">✕</button>
        </div>

        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">
          {/* Branches */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">الفرع الطالب *</label>
              <select className="input-field" value={sourceBranch}
                onChange={e => setSourceBranch(e.target.value)}>
                <option value="">اختر...</option>
                {(branches || []).filter(b => String(b.id) !== destinationBranch).map(b => (
                  <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">الفرع المصدر (يمتلك المخزون) *</label>
              <select className="input-field" value={destinationBranch}
                onChange={e => setDestinationBranch(e.target.value)}>
                <option value="">اختر...</option>
                {(branches || []).filter(b => String(b.id) !== sourceBranch).map(b => (
                  <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Item search */}
          <div>
            <label className="label">إضافة أصناف *</label>
            <ItemSearch onSelect={addItem} />
            <p className="text-xs text-gray-400 mt-1">اكتب حرفين للبحث · يمكن إضافة عدة أصناف</p>
          </div>

          {/* Items list */}
          {items.length === 0 ? (
            <div className="border-2 border-dashed border-gray-200 rounded-xl py-8 text-center">
              <div className="text-3xl mb-2">💊</div>
              <div className="text-sm text-gray-400">ابحث عن صنف أعلاه لإضافته</div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs font-bold text-gray-500">الأصناف المضافة ({items.length})</div>
              {items.map((row, idx) => {
                const allBranches   = itemStocks[row.item.id]
                const destId        = Number(destinationBranch)
                const supplyRow     = allBranches?.find(b => b.branch === destId)
                const otherBranches = allBranches?.filter(b => b.branch !== destId && b.quantity_on_hand > 0) || []
                const stockColor    = qty =>
                  qty >= 5  ? 'bg-green-100 text-green-700 ring-green-300'
                  : qty > 0 ? 'bg-amber-100 text-amber-700 ring-amber-300'
                  :           'bg-red-100 text-red-600 ring-red-300'
                return (
                  <div key={row.item.id} className="bg-brand-50 border border-brand-100 rounded-xl px-3 pt-2.5 pb-2">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-gray-800 text-sm truncate">{row.item.name}</div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-brand-600 font-mono">كود: {row.item.softech_id}</span>
                          {row.item.unit_price > 0 && (
                            <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                              {Number(row.item.unit_price).toFixed(2)} ج.م
                            </span>
                          )}
                        </div>
                      </div>
                      <input type="number" min="0.001" step="0.001" placeholder="الكمية"
                        value={row.qty} onChange={e => updateItem(idx, 'qty', e.target.value)}
                        className="w-24 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:border-brand-400" />
                      <input placeholder="ملاحظة"
                        value={row.notes} onChange={e => updateItem(idx, 'notes', e.target.value)}
                        className="w-28 border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand-400" />
                      <button onClick={() => removeItem(idx)} className="text-gray-300 hover:text-red-400 text-xl leading-none flex-shrink-0">✕</button>
                    </div>
                    {!allBranches ? (
                      <div className="mt-2 flex gap-1.5">
                        {[1,2,3].map(i => <div key={i} className="h-5 w-20 bg-gray-200 rounded animate-pulse" />)}
                      </div>
                    ) : (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        {destinationBranch && (
                          <>
                            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ring-2 ${stockColor(supplyRow?.quantity_on_hand ?? 0)}`}>
                              <span>🏭</span>
                              <span>{supplyRow ? (supplyRow.branch_name_ar || supplyRow.branch_name) : (branches?.find(b => b.id === destId)?.name_ar || 'الفرع المصدر')}</span>
                              <span className="font-black text-sm">{supplyRow?.quantity_on_hand ?? 0}</span>
                            </div>
                            {otherBranches.length > 0 && <span className="text-gray-300 text-xs">|</span>}
                          </>
                        )}
                        {otherBranches.map(b => (
                          <div key={b.branch} className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ring-1 ${stockColor(b.quantity_on_hand)}`}>
                            <span>{b.branch_name_ar || b.branch_name}</span>
                            <span className="font-bold">{b.quantity_on_hand}</span>
                          </div>
                        ))}
                        {!destinationBranch && allBranches.filter(b => b.quantity_on_hand > 0).map(b => (
                          <div key={b.branch} className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ring-1 ${stockColor(b.quantity_on_hand)}`}>
                            <span>{b.branch_name_ar || b.branch_name}</span>
                            <span className="font-bold">{b.quantity_on_hand}</span>
                          </div>
                        ))}
                        {allBranches.every(b => b.quantity_on_hand <= 0) && (
                          <span className="text-[11px] text-red-400 font-medium">لا يوجد مخزون في أي فرع</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="label">ملاحظات عامة (اختياري)</label>
            <textarea rows={2} className="input-field resize-none text-sm"
              placeholder="سبب الطلب، أولوية، تفاصيل إضافية..."
              value={notes} onChange={e => setNotes(e.target.value)} />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">{error}</div>
          )}
        </div>

        <div className="px-6 py-4 border-t flex-shrink-0">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none mr-auto">
              <input type="checkbox" checked={submitAndSend}
                onChange={e => setSubmitAndSend(e.target.checked)} className="rounded" />
              حفظ وتقديم الطلب مباشرةً
            </label>
            <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
            <button onClick={handleSubmit} disabled={submitting || items.length === 0}
              className="btn-primary text-sm disabled:opacity-50">
              {submitting ? 'جارٍ...' : submitAndSend ? '📤 حفظ وتقديم' : '💾 حفظ كمسودة'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Kanban Card ───────────────────────────────────────────────────────────────

function KanbanCard({ r, onClick }) {
  const s = STATUS[r.status] || STATUS.draft
  return (
    <div onClick={onClick}
      className="bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md hover:border-brand-200 cursor-pointer p-3 transition-all">
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="font-bold text-brand-700 font-mono text-xs">{r.request_number}</span>
        <span className="text-[10px] text-gray-400 flex-shrink-0">{timeAgo(r.created_at)}</span>
      </div>
      <div className="text-xs text-gray-700 mb-1 leading-snug">
        <span className="font-semibold">{r.requesting_branch_name}</span>
        <span className="text-gray-400 mx-1">→</span>
        <span className="text-gray-500">{r.supplying_branch_name || '—'}</span>
      </div>
      {r.notes && (
        <div className="text-[11px] text-gray-400 truncate mb-2">{r.notes}</div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded font-medium">
          {r.total_items} صنف
        </span>
        <span className="text-[10px] text-gray-400">{r.created_by_name}</span>
      </div>
    </div>
  )
}

// ── Kanban View ───────────────────────────────────────────────────────────────

function KanbanView({ requests, navigate }) {
  return (
    <div className="flex gap-4 overflow-x-auto pb-4 px-6 pt-2 min-h-[60vh]" style={{ scrollbarWidth: 'thin' }}>
      {KANBAN_COLS.map(statusKey => {
        const s     = STATUS[statusKey]
        const cards = requests.filter(r => r.status === statusKey)
        return (
          <div key={statusKey} className="flex-shrink-0 w-64">
            {/* Column header */}
            <div className="flex items-center gap-2 mb-3 px-1">
              <span>{s.icon}</span>
              <span className="font-bold text-sm text-gray-700">{s.label}</span>
              <span className="mr-auto bg-gray-200 text-gray-600 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                {cards.length}
              </span>
            </div>
            {/* Cards */}
            <div className="space-y-2 min-h-[100px] rounded-xl p-2"
              style={{ background: s.bg + '80' }}>
              {cards.length === 0 ? (
                <div className="text-center py-8 text-xs text-gray-400">لا يوجد</div>
              ) : (
                cards.map(r => (
                  <KanbanCard key={r.id} r={r} onClick={() => navigate(`/transfers/${r.id}`)} />
                ))
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── List View ─────────────────────────────────────────────────────────────────

function ListView({ requests, navigate }) {
  return (
    <div className="px-6 py-4">
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">رقم الطلب</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الفرع الطالب</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الفرع المصدر</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الأصناف</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الحالة</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">بواسطة</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">ملاحظات</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">التاريخ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {requests.map(r => (
              <tr key={r.id} onClick={() => navigate(`/transfers/${r.id}`)}
                className="cursor-pointer hover:bg-brand-50 transition-colors">
                <td className="px-4 py-3">
                  <div className="font-bold text-brand-700 font-mono text-sm">{r.request_number}</div>
                </td>
                <td className="px-4 py-3">
                  <span className="bg-brand-50 text-brand-700 px-2 py-0.5 rounded text-xs font-medium">
                    {r.requesting_branch_name}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-xs">
                    {r.supplying_branch_name || '—'}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500 tabular-nums">{r.total_items} صنف</td>
                <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                <td className="px-4 py-3 text-xs text-gray-500">{r.created_by_name}</td>
                <td className="px-4 py-3 text-xs text-gray-400 max-w-[160px] truncate">{r.notes || '—'}</td>
                <td className="px-4 py-3 text-xs text-gray-400">{timeAgo(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TransfersPage() {
  const navigate     = useNavigate()
  const qc           = useQueryClient()
  const { user }     = useAuthStore()

  const [viewMode, setViewMode]   = useState('list')   // 'list' | 'kanban'
  const [showCreate, setShowCreate] = useState(false)
  const [savedToast, setSavedToast] = useState('')     // success message
  const [filters, setFilters] = useState({
    status: '', requesting_branch: '', supplying_branch: '',
    search: '', date_from: '', date_to: '',
  })

  const userBranchId = user?.branch_id

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const { data: requests = [], isLoading } = useQuery({
    queryKey: ['transfers', filters],
    queryFn: () => transfersApi.list({
      status:             filters.status             || undefined,
      requesting_branch:  filters.requesting_branch  || undefined,
      supplying_branch:   filters.supplying_branch   || undefined,
      search:             filters.search             || undefined,
      date_from:          filters.date_from          || undefined,
      date_to:            filters.date_to            || undefined,
      page_size:          500,
    }).then(r => r.data.results || r.data),
    refetchInterval: 30_000,
  })

  function handleCreated(id, wasSubmitted) {
    qc.invalidateQueries(['transfers'])
    if (wasSubmitted) {
      navigate(`/transfers/${id}`)
    } else {
      setSavedToast('✅ تم حفظ الطلب كمسودة بنجاح')
      setTimeout(() => setSavedToast(''), 4000)
    }
  }

  const pendingCount  = requests.filter(r => r.status === 'pending').length
  const draftCount    = requests.filter(r => r.status === 'draft').length
  const approvedCount = requests.filter(r => r.status === 'approved').length

  const activeFiltersCount = [
    filters.requesting_branch, filters.supplying_branch,
    filters.date_from, filters.date_to,
  ].filter(Boolean).length

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Toast */}
      {savedToast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-green-600 text-white px-6 py-3 rounded-xl shadow-xl text-sm font-semibold animate-bounce-once">
          {savedToast}
        </div>
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-10">
        {/* Row 1: title + view toggle + new button */}
        <div className="flex items-center gap-3 flex-wrap">
          <div>
            <h1 className="text-lg font-black text-gray-900">طلبات التحويل</h1>
            <p className="text-xs text-gray-400">
              {requests.length} طلب
              {draftCount    > 0 && <span className="text-gray-500 mr-2">· {draftCount} مسودة</span>}
              {pendingCount  > 0 && <span className="text-orange-600 mr-2">· {pendingCount} بانتظار الموافقة</span>}
              {approvedCount > 0 && <span className="text-blue-600 mr-2">· {approvedCount} معتمد</span>}
            </p>
          </div>
          <div className="flex-1" />

          {/* View toggle */}
          <div className="flex bg-gray-100 rounded-lg p-0.5 gap-0.5">
            <button onClick={() => setViewMode('list')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                viewMode === 'list' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}>☰ قائمة</button>
            <button onClick={() => setViewMode('kanban')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                viewMode === 'kanban' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}>⬛ كانبان</button>
          </div>

          <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
            + طلب تحويل جديد
          </button>
        </div>

        {/* Row 2: status tabs */}
        <div className="flex gap-1 mt-3 overflow-x-auto no-scrollbar">
          {[
            { label: 'الكل',                value: '' },
            { label: 'مسوداتي',             value: 'draft' },
            { label: 'بانتظار الموافقة',    value: 'pending' },
            { label: 'معتمد',               value: 'approved' },
            { label: 'يحتاج تعديل',         value: 'needs_revision' },
            { label: 'تم الإرسال للـ ERP',  value: 'sent_to_erp' },
            { label: 'مكتمل',               value: 'completed' },
            { label: 'ملغي',                value: 'cancelled' },
          ].map(f => (
            <button key={f.value}
              onClick={() => setFilters(prev => ({ ...prev, status: f.value }))}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                filters.status === f.value
                  ? 'bg-brand-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {f.label}
            </button>
          ))}
        </div>

        {/* Row 3: search + branch + date filters */}
        <div className="flex gap-2 mt-2 flex-wrap items-center">
          <input className="input-field w-48 text-xs" placeholder="🔍 بحث برقم الطلب..."
            value={filters.search}
            onChange={e => setFilters(f => ({ ...f, search: e.target.value }))} />

          <select className="input-field w-44 text-xs" value={filters.requesting_branch}
            onChange={e => setFilters(f => ({ ...f, requesting_branch: e.target.value }))}>
            <option value="">الفرع الطالب (الكل)</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>

          <select className="input-field w-44 text-xs" value={filters.supplying_branch}
            onChange={e => setFilters(f => ({ ...f, supplying_branch: e.target.value }))}>
            <option value="">الفرع المصدر (الكل)</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>

          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-500">من</span>
            <input type="date" className="input-field text-xs w-36" value={filters.date_from}
              onChange={e => setFilters(f => ({ ...f, date_from: e.target.value }))} />
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-500">إلى</span>
            <input type="date" className="input-field text-xs w-36" value={filters.date_to}
              onChange={e => setFilters(f => ({ ...f, date_to: e.target.value }))} />
          </div>

          {(filters.search || activeFiltersCount > 0) && (
            <button className="btn-secondary text-xs px-3"
              onClick={() => setFilters({ status: filters.status, requesting_branch: '', supplying_branch: '', search: '', date_from: '', date_to: '' })}>
              مسح الفلاتر {activeFiltersCount > 0 && `(${activeFiltersCount})`}
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="px-6 py-5 space-y-2 animate-pulse">
          {[1,2,3,4].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl" />)}
        </div>
      ) : requests.length === 0 ? (
        <div className="max-w-6xl mx-auto px-6 py-10">
          <div className="card text-center py-16">
            <div className="text-5xl mb-3">🔀</div>
            <div className="text-gray-600 font-semibold">لا توجد طلبات تحويل</div>
            <div className="text-gray-400 text-xs mt-1 mb-5">
              {filters.status || activeFiltersCount > 0
                ? 'لا توجد طلبات تطابق هذه الفلاتر'
                : 'اضغط "+ طلب تحويل جديد" لإنشاء أول طلب'}
            </div>
            {!filters.status && activeFiltersCount === 0 && (
              <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
                + طلب تحويل جديد
              </button>
            )}
          </div>
        </div>
      ) : viewMode === 'kanban' ? (
        <KanbanView requests={requests} navigate={navigate} />
      ) : (
        <ListView requests={requests} navigate={navigate} />
      )}

      {showCreate && (
        <CreateRequestModal
          branches={branches}
          userBranchId={userBranchId}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
