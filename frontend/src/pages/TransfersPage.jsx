import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { transfersApi, branchesApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Status config ─────────────────────────────────────────────────────────────

const STATUS = {
  draft:          { label: 'مسودة',               dot: '#9ca3af', bg: '#f9fafb', text: '#6b7280' },
  pending:        { label: 'بانتظار الموافقة',    dot: '#f59e0b', bg: '#fffbeb', text: '#92400e' },
  approved:       { label: 'معتمد',               dot: '#3b82f6', bg: '#eff6ff', text: '#1e40af' },
  rejected:       { label: 'مرفوض',               dot: '#ef4444', bg: '#fef2f2', text: '#991b1b' },
  needs_revision: { label: 'يحتاج تعديل',         dot: '#f59e0b', bg: '#fefce8', text: '#713f12' },
  sent_to_erp:    { label: 'تم الإرسال للـ ERP',  dot: '#8b5cf6', bg: '#f5f3ff', text: '#5b21b6' },
  completed:      { label: 'مكتمل',               dot: '#10b981', bg: '#f0fdf4', text: '#166534' },
  cancelled:      { label: 'ملغي',                dot: '#d1d5db', bg: '#f9fafb', text: '#9ca3af' },
}

function timeAgo(dt) {
  if (!dt) return '—'
  try { return formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }) } catch { return '' }
}

function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.draft
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.text }}
    >
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
      <input
        className="input-field text-sm"
        placeholder="ابحث بالاسم أو الكود..."
        value={q}
        onChange={e => { setQ(e.target.value); setOpen(true) }}
        autoComplete="off"
      />
      {open && q.length >= 2 && (results?.length > 0) && (
        <div className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-56 overflow-y-auto">
          {results.map(item => (
            <button key={item.id} type="button"
              className="w-full text-right px-4 py-2.5 hover:bg-brand-50 transition-colors border-b border-gray-50 last:border-0"
              onClick={() => { onSelect(item); setQ(''); setOpen(false) }}>
              <div className="font-semibold text-gray-800 text-sm">{item.name}</div>
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
  const [sourceBranch, setSourceBranch] = useState(String(userBranchId || ''))
  const [destinationBranch, setDestinationBranch] = useState('')
  const [notes, setNotes] = useState('')
  const [items, setItems] = useState([])  // [{item, qty, notes}]
  const [submitAndSend, setSubmitAndSend] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const qc = useQueryClient()

  function addItem(item) {
    if (items.find(i => i.item.id === item.id)) return
    setItems(prev => [...prev, { item, qty: '', notes: '' }])
  }

  function updateItem(idx, field, value) {
    setItems(prev => prev.map((row, i) => i === idx ? { ...row, [field]: value } : row))
  }

  function removeItem(idx) {
    setItems(prev => prev.filter((_, i) => i !== idx))
  }

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
        source_branch:      Number(sourceBranch),
        destination_branch: Number(destinationBranch),
        notes,
        items: items.map(i => ({
          item:     i.item.id,
          quantity: i.qty,
          notes:    i.notes || '',
        })),
      }
      const res = await transfersApi.create(payload)
      const newId = res.data.id

      if (submitAndSend) {
        await transfersApi.submit(newId)
      }

      qc.invalidateQueries(['transfers'])
      onCreated(newId)
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
              {items.map((row, idx) => (
                <div key={row.item.id} className="flex items-center gap-3 bg-brand-50 border border-brand-100 rounded-xl px-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-gray-800 text-sm truncate">{row.item.name}</div>
                    <div className="text-xs text-brand-600 font-mono">كود: {row.item.softech_id}</div>
                  </div>
                  <input type="number" min="0.001" step="0.001" placeholder="الكمية"
                    value={row.qty}
                    onChange={e => updateItem(idx, 'qty', e.target.value)}
                    className="w-24 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:border-brand-400" />
                  <input placeholder="ملاحظة"
                    value={row.notes}
                    onChange={e => updateItem(idx, 'notes', e.target.value)}
                    className="w-28 border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand-400" />
                  <button onClick={() => removeItem(idx)} className="text-gray-300 hover:text-red-400 text-xl leading-none">✕</button>
                </div>
              ))}
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
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer flex-1">
              <input type="checkbox" checked={submitAndSend}
                onChange={e => setSubmitAndSend(e.target.checked)}
                className="rounded" />
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

// ── Main List Page ────────────────────────────────────────────────────────────

export default function TransfersPage() {
  const navigate  = useNavigate()
  const qc        = useQueryClient()
  const { user }  = useAuthStore()

  const [showCreate, setShowCreate] = useState(false)
  const [filters, setFilters] = useState({ status: '', source_branch: '', destination_branch: '', search: '' })

  const isCCOrAdmin = ['admin', 'call_center', 'purchasing'].includes(user?.role)
  const userBranchId = user?.branch_id

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const { data: requests = [], isLoading } = useQuery({
    queryKey: ['transfers', filters],
    queryFn: () => transfersApi.list({
      status:             filters.status             || undefined,
      source_branch:      filters.source_branch      || undefined,
      destination_branch: filters.destination_branch || undefined,
      search:             filters.search             || undefined,
    }).then(r => r.data.results || r.data),
    refetchInterval: 30_000,
  })

  const pendingCount  = requests.filter(r => r.status === 'pending').length
  const draftCount    = requests.filter(r => r.status === 'draft').length
  const approvedCount = requests.filter(r => r.status === 'approved').length

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-10">
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-black text-gray-900">طلبات التحويل</h1>
            <p className="text-xs text-gray-400">
              {requests.length} طلب
              {draftCount    > 0 && <span className="text-gray-500 mr-2">· {draftCount} مسودة</span>}
              {pendingCount  > 0 && <span className="text-orange-600 mr-2">· {pendingCount} بانتظار الموافقة</span>}
              {approvedCount > 0 && <span className="text-blue-600 mr-2">· {approvedCount} معتمد — جاهز للإرسال</span>}
            </p>
          </div>
          <div className="flex-1" />
          <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
            + طلب تحويل جديد
          </button>
        </div>

        {/* Quick filter tabs */}
        <div className="flex gap-1 mt-3 overflow-x-auto no-scrollbar">
          {[
            { label: 'الكل',                value: '' },
            { label: 'مسوداتي',             value: 'draft' },
            { label: 'بانتظار الموافقة',    value: 'pending' },
            { label: 'معتمد',               value: 'approved' },
            { label: 'يحتاج تعديل',         value: 'needs_revision' },
            { label: 'تم الإرسال للـ ERP',  value: 'sent_to_erp' },
            { label: 'مكتمل',               value: 'completed' },
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

        {/* Search + branch filters */}
        <div className="flex gap-2 mt-2 flex-wrap">
          <input className="input-field w-48 text-xs" placeholder="🔍 بحث برقم الطلب أو الصنف..."
            value={filters.search}
            onChange={e => setFilters(f => ({ ...f, search: e.target.value }))} />
          {isCCOrAdmin && (
            <>
              <select className="input-field w-44 text-xs" value={filters.source_branch}
                onChange={e => setFilters(f => ({ ...f, source_branch: e.target.value }))}>
                <option value="">الفرع الطالب (الكل)</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
              </select>
              <select className="input-field w-44 text-xs" value={filters.destination_branch}
                onChange={e => setFilters(f => ({ ...f, destination_branch: e.target.value }))}>
                <option value="">الفرع المصدر (الكل)</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
              </select>
            </>
          )}
          <button className="btn-secondary text-xs px-3"
            onClick={() => setFilters({ status: '', source_branch: '', destination_branch: '', search: '' })}>
            مسح
          </button>
        </div>
      </div>

      {/* List */}
      <div className="max-w-6xl mx-auto px-6 py-5">
        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1,2,3,4].map(i => <div key={i} className="h-20 bg-gray-100 rounded-xl" />)}
          </div>
        ) : requests.length === 0 ? (
          <div className="card text-center py-16">
            <div className="text-5xl mb-3">🔀</div>
            <div className="text-gray-600 font-semibold">لا توجد طلبات تحويل</div>
            <div className="text-gray-400 text-xs mt-1 mb-5">
              {filters.status ? 'لا توجد طلبات بهذه الحالة' : 'اضغط "+ طلب تحويل جديد" لإنشاء أول طلب'}
            </div>
            {!filters.status && (
              <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
                + طلب تحويل جديد
              </button>
            )}
          </div>
        ) : (
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
                  <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">التاريخ</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {requests.map(r => (
                  <tr key={r.id}
                    onClick={() => navigate(`/transfers/${r.id}`)}
                    className="cursor-pointer hover:bg-brand-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-bold text-brand-700 font-mono text-sm">{r.request_number}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="bg-brand-50 text-brand-700 px-2 py-0.5 rounded text-xs font-medium">
                        {r.source_branch_name}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-xs">
                        {r.destination_branch_name}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 tabular-nums">
                      {r.total_items} صنف
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                    <td className="px-4 py-3 text-xs text-gray-500">{r.created_by_name}</td>
                    <td className="px-4 py-3 text-xs text-gray-400">{timeAgo(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate && (
        <CreateRequestModal
          branches={branches}
          userBranchId={userBranchId}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => navigate(`/transfers/${id}`)}
        />
      )}
    </div>
  )
}
