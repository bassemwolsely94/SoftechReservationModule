import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { reservationsApi, branchesApi } from '../api/client'
import { StatusBadge, PriorityBadge, STATUS_OPTIONS, PRIORITY_OPTIONS } from '../components/StatusBadge'
import BranchSelect from '../components/BranchSelect'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// ── Status transition graph (mirrors backend _VALID_TRANSITIONS) ──────────────
const VALID_TRANSITIONS = {
  pending:   ['available', 'cancelled', 'expired'],
  available: ['contacted', 'confirmed', 'cancelled', 'expired'],
  contacted: ['confirmed', 'available', 'cancelled', 'expired'],
  confirmed: ['fulfilled', 'cancelled', 'expired'],
  expired:   ['pending'],
  fulfilled: [],
  cancelled: [],
}

const STATUS_LABELS = {
  pending:   'قيد الانتظار',
  available: 'المخزون متاح',
  contacted: 'تم التواصل',
  confirmed: 'مؤكد — قادم',
  fulfilled: 'تم التسليم',
  cancelled: 'ملغي',
  expired:   'منتهي',
}

// Natural forward order — used to prevent showing backward jumps in bulk
const STATUS_ORDER = ['pending', 'available', 'contacted', 'confirmed', 'fulfilled']

function FilterBar({ filters, onChange, branches }) {
  return (
    <div className="card mb-4 flex flex-wrap gap-3 items-center" dir="rtl">
      <input
        type="text"
        placeholder="بحث بالاسم أو الرقم..."
        className="input-field w-48"
        value={filters.search}
        onChange={e => onChange({ ...filters, search: e.target.value, page: 1 })}
      />
      <select
        className="input-field w-44"
        value={filters.status}
        onChange={e => onChange({ ...filters, status: e.target.value, page: 1 })}
      >
        <option value="">كل الحالات</option>
        {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <select
        className="input-field w-36"
        value={filters.priority}
        onChange={e => onChange({ ...filters, priority: e.target.value, page: 1 })}
      >
        <option value="">كل الأولويات</option>
        {PRIORITY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <BranchSelect
        size="sm"
        value={filters.branch}
        onChange={v => onChange({ ...filters, branch: v, page: 1 })}
        branches={branches || []}
        allLabel="كل الفروع"
        className="w-52"
      />
      <button
        className="btn-secondary text-sm"
        onClick={() => onChange({ search: '', status: '', priority: '', branch: '', page: 1 })}
      >
        مسح الفلاتر
      </button>
    </div>
  )
}

// ── Bulk action toolbar ────────────────────────────────────────────────────────
function BulkToolbar({ selectedIds, selectedReservations, onClear, onAction }) {
  const [bulkStatus, setBulkStatus] = useState('')
  const [loading, setLoading] = useState(false)

  // Compute which target statuses are valid for at least one selected reservation.
  // Only show forward transitions (by STATUS_ORDER index) + cancelled.
  const validOptions = (() => {
    const reachable = new Set()
    for (const r of selectedReservations) {
      const nexts = VALID_TRANSITIONS[r.status] || []
      nexts.forEach(s => reachable.add(s))
    }
    // Build ordered list: forward steps first (in stage order), then cancelled
    const forward = STATUS_ORDER.filter(s => reachable.has(s))
    const rest = ['cancelled', 'expired'].filter(s => reachable.has(s))
    return [...forward, ...rest].map(s => ({ value: s, label: STATUS_LABELS[s] || s }))
  })()

  // For the chosen target status, how many selected reservations can actually move?
  const previewCounts = (() => {
    if (!bulkStatus) return null
    let willUpdate = 0, willSkip = 0
    for (const r of selectedReservations) {
      const nexts = VALID_TRANSITIONS[r.status] || []
      nexts.includes(bulkStatus) ? willUpdate++ : willSkip++
    }
    return { willUpdate, willSkip }
  })()

  async function handleChangeStatus() {
    if (!bulkStatus) return
    setLoading(true)
    try {
      await onAction('change_status', { status: bulkStatus })
      setBulkStatus('')
    } finally {
      setLoading(false)
    }
  }

  async function handleExport() {
    setLoading(true)
    try {
      const res = await reservationsApi.bulk({ action: 'export', ids: selectedIds })
      const url = URL.createObjectURL(new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'reservations.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mb-3 space-y-2" dir="rtl">
      <div className="flex flex-wrap items-center gap-3 bg-brand-50 border border-brand-200 rounded-xl px-4 py-2.5 text-sm">
        <span className="font-semibold text-brand-700">{selectedIds.length} محدد</span>
        <div className="h-4 border-r border-brand-200" />

        {/* Change status — only valid forward transitions */}
        <div className="flex items-center gap-2">
          <select
            className="input-field text-xs py-1 w-48"
            value={bulkStatus}
            onChange={e => setBulkStatus(e.target.value)}
          >
            <option value="">تغيير الحالة...</option>
            {validOptions.length === 0
              ? <option disabled>لا توجد انتقالات متاحة</option>
              : validOptions.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))
            }
          </select>
          <button
            disabled={!bulkStatus || loading}
            onClick={handleChangeStatus}
            className="btn-primary text-xs py-1 px-3 disabled:opacity-40"
          >
            {loading ? '...' : 'تطبيق'}
          </button>
        </div>

        <div className="h-4 border-r border-brand-200" />

        {/* Export */}
        <button
          disabled={loading}
          onClick={handleExport}
          className="btn-secondary text-xs py-1 px-3 flex items-center gap-1"
        >
          📥 تصدير Excel
        </button>

        <div className="flex-1" />
        <button onClick={onClear} className="text-gray-400 hover:text-red-500 text-xs">
          ✕ إلغاء التحديد
        </button>
      </div>

      {/* Preview: show update/skip counts before confirming */}
      {previewCounts && (
        <div className="flex items-center gap-3 text-xs px-4 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-800">
          <span>سيتم تحديث <strong>{previewCounts.willUpdate}</strong> حجز</span>
          {previewCounts.willSkip > 0 && (
            <span className="text-amber-600">— سيتم تخطي <strong>{previewCounts.willSkip}</strong> لأن حالتها لا تسمح بهذا الانتقال</span>
          )}
        </div>
      )}
    </div>
  )
}

export default function ReservationsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [searchParams] = useSearchParams()
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkMsg, setBulkMsg] = useState('')

  const [filters, setFilters] = useState({
    search: '',
    status: searchParams.get('status') || '',
    priority: '',
    branch: '',
    page: 1,
  })

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['reservations', filters],
    queryFn: () => reservationsApi.list({
      search: filters.search || undefined,
      status: filters.status || undefined,
      priority: filters.priority || undefined,
      branch: filters.branch || undefined,
      page: filters.page,
    }).then(r => r.data),
    keepPreviousData: true,
    staleTime: 30_000,
  })

  const { data: branches } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const reservations = data?.results || []
  const totalCount = data?.count || 0
  const totalPages = Math.ceil(totalCount / 50)
  const allPageIds = reservations.map(r => r.id)
  const allSelected = allPageIds.length > 0 && allPageIds.every(id => selectedIds.includes(id))

  function toggleSelect(id) {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  function toggleAll() {
    setSelectedIds(allSelected ? [] : allPageIds)
  }

  async function handleBulkAction(action, params) {
    setBulkMsg('')
    try {
      const res = await reservationsApi.bulk({ action, ids: selectedIds, ...params })
      if (action !== 'export') {
        const d = res.data
        setBulkMsg(
          `✅ تم تحديث ${d.updated} حجز` +
          (d.skipped ? ` — تم تخطي ${d.skipped} بسبب قيود الحالة` : '')
        )
        setSelectedIds([])
        qc.invalidateQueries(['reservations'])
      }
    } catch (e) {
      setBulkMsg('❌ ' + (e.response?.data?.detail || 'حدث خطأ'))
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/reservations')}
            className="text-sm text-gray-500 hover:text-brand-600 transition-colors flex items-center gap-1"
            title="عودة إلى الكانبان"
          >
            ⬛ كانبان
          </button>
          <div>
            <h1 className="text-2xl font-black text-gray-800">الحجوزات — قائمة</h1>
            <p className="text-sm text-gray-500">{totalCount.toLocaleString('en-US')} حجز</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/reservations/new')} className="btn-primary flex items-center gap-2">
            <span className="text-lg">+</span>
            حجز جديد
          </button>
        </div>
      </div>

      <FilterBar filters={filters} onChange={f => { setFilters(f); setSelectedIds([]) }} branches={branches} />

      {/* Bulk toolbar */}
      {selectedIds.length > 0 && (
        <BulkToolbar
          selectedIds={selectedIds}
          selectedReservations={reservations.filter(r => selectedIds.includes(r.id))}
          onClear={() => setSelectedIds([])}
          onAction={handleBulkAction}
        />
      )}
      {bulkMsg && (
        <div className="mb-3 text-sm px-4 py-2 rounded-lg bg-green-50 border border-green-200 text-green-700">
          {bulkMsg}
        </div>
      )}

      {/* Table */}
      <div className={`card p-0 overflow-hidden transition-opacity ${isFetching ? 'opacity-70' : ''}`}>
        {isError ? (
          <div className="p-10 text-center">
            <div className="text-3xl mb-2">⚠️</div>
            <div className="text-red-600 font-medium mb-3">حدث خطأ أثناء تحميل الحجوزات</div>
            <button onClick={() => refetch()} className="btn-secondary text-sm">إعادة المحاولة</button>
          </div>
        ) : isLoading ? (
          <div className="p-8 text-center text-gray-400">جارٍ التحميل...</div>
        ) : reservations.length === 0 ? (
          <div className="p-12 text-center">
            <div className="text-4xl mb-3">📋</div>
            <div className="text-gray-500 font-medium">لا توجد حجوزات مطابقة للفلاتر</div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-3 py-3">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                  />
                </th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">#</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">العميل</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">الصنف</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">الفرع</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">الحالة</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">الأولوية</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">المتابعة</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">تاريخ الإنشاء</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {reservations.map(r => (
                <tr
                  key={r.id}
                  className={`hover:bg-brand-50 transition-colors duration-100 ${selectedIds.includes(r.id) ? 'bg-brand-50' : ''}`}
                >
                  <td className="px-3 py-3" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(r.id)}
                      onChange={() => toggleSelect(r.id)}
                      className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                    />
                  </td>
                  <td
                    className="px-4 py-3 text-gray-400 font-mono text-xs cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  >{r.id}</td>
                  <td
                    className="px-4 py-3 cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  >
                    <div className="font-semibold text-gray-800">{r.customer_name || r.contact_name}</div>
                    <div className="text-xs text-gray-400">{r.customer_phone || r.contact_phone}</div>
                  </td>
                  <td
                    className="px-4 py-3 cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  >
                    {(() => {
                      const primary = { name: r.item_name || r.manual_item_name || '—', code: r.item_softech_id }
                      const extras = (r.lines || []).map(l => ({ name: l.item_name, code: l.item_softech_id }))
                      const allItems = [primary, ...extras]
                      return (
                        <div className="space-y-0.5">
                          {allItems.map((item, idx) => (
                            <div key={idx} className="flex items-start gap-1">
                              <span className="text-[10px] font-mono text-gray-400 shrink-0 mt-px">{idx + 1}.</span>
                              <div className="min-w-0">
                                <div className="text-xs font-medium text-gray-900 leading-snug break-words">{item.name}</div>
                                {item.code && <div className="text-[10px] font-mono text-gray-400">كود: {item.code}</div>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )
                    })()}
                  </td>
                  <td
                    className="px-4 py-3 text-gray-600 text-xs cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  >{r.branch_name}</td>
                  <td
                    className="px-4 py-3 cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  ><StatusBadge status={r.status} /></td>
                  <td
                    className="px-4 py-3 cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  ><PriorityBadge priority={r.priority} /></td>
                  <td
                    className="px-4 py-3 text-xs text-gray-500 cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  >
                    {r.follow_up_date
                      ? toLatinDigits(format(new Date(r.follow_up_date), 'd MMM', { locale: ar }))
                      : '—'}
                  </td>
                  <td
                    className="px-4 py-3 text-xs text-gray-400 cursor-pointer"
                    onClick={() => navigate(`/reservations/${r.id}`)}
                  >
                    {toLatinDigits(format(new Date(r.created_at), 'd MMM yyyy', { locale: ar }))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
            <span className="text-sm text-gray-500">
              صفحة {filters.page} من {totalPages}
            </span>
            <div className="flex gap-2">
              <button
                disabled={filters.page <= 1}
                onClick={() => setFilters(f => ({ ...f, page: f.page - 1 }))}
                className="btn-secondary text-xs disabled:opacity-40"
              >السابق</button>
              <button
                disabled={filters.page >= totalPages}
                onClick={() => setFilters(f => ({ ...f, page: f.page + 1 }))}
                className="btn-secondary text-xs disabled:opacity-40"
              >التالي</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
