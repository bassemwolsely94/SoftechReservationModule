import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { transfersApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import BranchSelect from '../components/BranchSelect'
import CanDo from '../components/CanDo'
import TransferModuleTabs from '../components/TransferModuleTabs'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

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
  try { return toLatinDigits(formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true })) } catch { return '' }
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
  const location     = useLocation()
  const { user }     = useAuthStore()

  // 'قيد النقل' now lives on its own page (/transits). Redirect any legacy
  // navigation that still asks for the in-transit tab via router state.
  useEffect(() => {
    if (location.state?.tab === 'in_transit') {
      navigate('/transits', { replace: true })
    }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const [viewMode, setViewMode]   = useState('list')   // 'list' | 'kanban'
  const [savedToast, setSavedToast] = useState(location.state?.savedToast || '')
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

  // Auto-dismiss toast that came from NewTransferPage navigation state
  useEffect(() => {
    if (savedToast) {
      const t = setTimeout(() => setSavedToast(''), 4000)
      // Clear the location state so refresh doesn't re-show it
      window.history.replaceState({}, '')
      return () => clearTimeout(t)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const pendingCount  = requests.filter(r => r.status === 'pending').length
  const draftCount    = requests.filter(r => r.status === 'draft').length
  const approvedCount = requests.filter(r => r.status === 'approved').length

  const activeFiltersCount = [
    filters.search, filters.requesting_branch, filters.supplying_branch,
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
      <div className="bg-white border-b border-gray-200 sticky top-0 z-10">

        {/* Module switcher (requests ⇄ in-transit, separate pages) */}
        <TransferModuleTabs active="requests" />

        {/* Row 1: title + view toggle + new button */}
        <div className="px-6 py-4">
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

          <CanDo module="transfers" action="create">
            <button onClick={() => navigate('/transfers/new')} className="btn-primary text-sm">
              + طلب تحويل جديد
            </button>
          </CanDo>
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

          <BranchSelect
            size="sm"
            value={filters.requesting_branch}
            onChange={v => setFilters(f => ({ ...f, requesting_branch: v }))}
            branches={branches}
            allLabel="الفرع الطالب (الكل)"
            className="w-52"
          />

          <BranchSelect
            size="sm"
            value={filters.supplying_branch}
            onChange={v => setFilters(f => ({ ...f, supplying_branch: v }))}
            branches={branches}
            allLabel="الفرع المصدر (الكل)"
            className="w-52"
          />

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

          {activeFiltersCount > 0 && (
            <button className="btn-secondary text-xs px-3"
              onClick={() => setFilters(f => ({ ...f, search: '', requesting_branch: '', supplying_branch: '', date_from: '', date_to: '' }))}>
              مسح الفلاتر ({activeFiltersCount})
            </button>
          )}
        </div>
        </div>

      </div> {/* end sticky header */}

      {/* ── Requests content ──────────────────────────────────────────────── */}
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
              <button onClick={() => navigate('/transfers/new')} className="btn-primary text-sm">
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

    </div>
  )
}
