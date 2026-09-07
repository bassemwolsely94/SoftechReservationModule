import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reservationsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import BranchSelect from '../components/BranchSelect'
import CanDo from '../components/CanDo'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// ── Status config ─────────────────────────────────────────────────────────────
const COLUMNS = [
  { key: 'pending',   label: 'قيد الانتظار',     color: '#6b7280', bg: '#f9fafb', dot: '#9ca3af' },
  { key: 'available', label: 'المخزون متاح',       color: '#d97706', bg: '#fffbeb', dot: '#f59e0b' },
  { key: 'contacted', label: 'تم التواصل',          color: '#2563eb', bg: '#eff6ff', dot: '#3b82f6' },
  { key: 'confirmed', label: 'مؤكد — قادم',        color: '#7c3aed', bg: '#f5f3ff', dot: '#8b5cf6' },
  { key: 'fulfilled', label: 'تم التسليم',          color: '#059669', bg: '#ecfdf5', dot: '#10b981' },
  { key: 'cancelled', label: 'ملغي / منتهي',       color: '#dc2626', bg: '#fef2f2', dot: '#ef4444' },
]

const PRIORITY_BADGE = {
  normal:  { label: 'عادي',        cls: 'bg-gray-100 text-gray-600' },
  urgent:  { label: 'عاجل 🔴',     cls: 'bg-red-100 text-red-700' },
  chronic: { label: 'مزمن 💊',     cls: 'bg-purple-100 text-purple-700' },
  high:    { label: 'مهم 🟡',      cls: 'bg-yellow-100 text-yellow-700' },
}

const STATUS_TRANSITIONS = {
  pending:   ['available', 'cancelled'],
  available: ['contacted', 'cancelled'],
  contacted: ['confirmed', 'cancelled'],   // 'expired' removed — expiry is system-only (scheduler)
  confirmed: ['fulfilled', 'cancelled'],
  fulfilled: [],
  cancelled: [],
  expired:   [],
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function timeAgo(dt) {
  try { return toLatinDigits(formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true })) }
  catch { return '' }
}

function formatDate(d) {
  if (!d) return '—'
  try { return format(new Date(d), 'dd/MM/yyyy') } catch { return d }
}

// ── Card component ────────────────────────────────────────────────────────────
function ReservationCard({ reservation, onStatusChange, onOpen, isCCOrAdmin, pendingStatus }) {
  const col = COLUMNS.find(c => c.key === reservation.status) || COLUMNS[0]
  const pri = PRIORITY_BADGE[reservation.priority] || PRIORITY_BADGE.normal
  const transitions = STATUS_TRANSITIONS[reservation.status] || []
  const isBusy = !!pendingStatus  // mutation in flight for this card

  return (
    <div
      className="bg-white rounded-xl shadow-sm border border-gray-100 p-3 cursor-pointer hover:shadow-md hover:border-gray-200 transition-all duration-150 select-none"
      onClick={() => onOpen(reservation)}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          {/* Reservation number */}
          <div className="text-[10px] font-mono text-gray-400 mb-1">#{reservation.id}</div>
          {/* All items — primary + extra lines, uniform size, numbered */}
          {(() => {
            const primary = { name: reservation.item_name || reservation.manual_item_name || '—', code: reservation.item_softech_id }
            const extras = (reservation.lines || []).map(l => ({ name: l.item_name, code: l.item_softech_id }))
            const allItems = [primary, ...extras]
            return (
              <div className="space-y-1">
                {allItems.map((item, idx) => (
                  <div key={idx} className="flex items-start gap-1.5">
                    <span className="text-[11px] font-mono text-gray-400 shrink-0 mt-px">{idx + 1}.</span>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-gray-900 leading-snug break-words">{item.name}</div>
                      {item.code && <div className="text-[10px] font-mono text-gray-400">كود: {item.code}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )
          })()}
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap flex-shrink-0 ${pri.cls}`}>
          {pri.label}
        </span>
      </div>

      {/* Customer */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-gray-400 text-xs">👤</span>
        <span className="text-xs text-gray-700 truncate">{reservation.customer_name}</span>
      </div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-gray-400 text-xs">📞</span>
        <span className="text-xs text-gray-600 font-mono" dir="ltr">{reservation.contact_phone}</span>
      </div>

      {/* Branch badge — shown for CC/admin */}
      {isCCOrAdmin && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="text-gray-400 text-xs">🏥</span>
          <span className="text-xs bg-brand-50 text-brand-700 px-1.5 py-0.5 rounded font-medium truncate">
            {reservation.branch_name}
          </span>
        </div>
      )}

      {/* Qty + image indicator */}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-50">
        <span className="text-xs text-gray-500">الكمية: <strong>{reservation.quantity_requested}</strong></span>
        <div className="flex items-center gap-2">
          {reservation.image_url && (
            <span className="text-gray-400 text-xs" title="يحتوي صورة">🖼️</span>
          )}
          <span className="text-xs text-gray-400">{timeAgo(reservation.created_at)}</span>
        </div>
      </div>

      {/* Quick status buttons */}
      {transitions.length > 0 && (
        <div className="flex gap-1 mt-2 flex-wrap" onClick={e => e.stopPropagation()}>
          {transitions.map(s => {
            const tc = COLUMNS.find(c => c.key === s)
            return (
              <button
                key={s}
                disabled={isBusy}
                onClick={() => !isBusy && onStatusChange(reservation.id, s)}
                style={{ borderColor: tc?.dot, color: tc?.color }}
                className={`text-xs border rounded px-2 py-0.5 transition-opacity bg-white
                  ${isBusy ? 'opacity-40 cursor-not-allowed' : 'hover:opacity-80'}`}
              >
                {isBusy ? '...' : `→ ${tc?.label}`}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Column component ──────────────────────────────────────────────────────────
function KanbanColumn({ col, cards, onStatusChange, onOpen, isCCOrAdmin, pendingIds }) {
  return (
    <div className="flex flex-col" style={{ minWidth: 280, maxWidth: 320, flex: '0 0 290px' }}>
      {/* Column header */}
      <div
        className="flex items-center justify-between px-3 py-2.5 rounded-t-xl font-semibold text-sm sticky top-0 z-10"
        style={{ background: col.bg, color: col.color, borderBottom: `2px solid ${col.dot}` }}
      >
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: col.dot }} />
          {col.label}
        </div>
        <span
          className="text-xs font-bold px-2 py-0.5 rounded-full"
          style={{ background: col.dot + '22', color: col.color }}
        >
          {cards.length}
        </span>
      </div>

      {/* Cards */}
      <div
        className="flex flex-col gap-2 p-2 rounded-b-xl overflow-y-auto"
        style={{ background: col.bg + 'cc', minHeight: 100, maxHeight: 'calc(100vh - 220px)' }}
      >
        {cards.length === 0 && (
          <div className="text-center py-8 text-gray-300 text-xs select-none">لا توجد حجوزات</div>
        )}
        {cards.map(r => (
          <ReservationCard
            key={r.id}
            reservation={r}
            onStatusChange={onStatusChange}
            onOpen={onOpen}
            isCCOrAdmin={isCCOrAdmin}
            pendingStatus={pendingIds?.has(r.id)}
          />
        ))}
      </div>
    </div>
  )
}


// ── List View ─────────────────────────────────────────────────────────────────
function ReservationListView({ reservations, onOpen, isCCOrAdmin }) {
  const [sortKey, setSortKey] = useState('created_at')
  const [sortDir, setSortDir] = useState('desc')

  const toggleSort = key => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = [...reservations].sort((a, b) => {
    let va = a[sortKey] ?? ''
    let vb = b[sortKey] ?? ''
    if (typeof va === 'string') va = va.toLowerCase()
    if (typeof vb === 'string') vb = vb.toLowerCase()
    if (va < vb) return sortDir === 'asc' ? -1 : 1
    if (va > vb) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  const SortIcon = ({ k }) => sortKey === k
    ? <span className="text-brand-500 mr-0.5">{sortDir === 'asc' ? '↑' : '↓'}</span>
    : <span className="text-gray-300 mr-0.5">↕</span>

  const Th = ({ k, children, cls = '' }) => (
    <th
      className={`px-3 py-2.5 text-right text-xs font-semibold text-gray-500 whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none ${cls}`}
      onClick={() => toggleSort(k)}
    >
      {children}<SortIcon k={k} />
    </th>
  )

  if (sorted.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm py-16">
        لا توجد حجوزات حسب الفلاتر المحددة.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto" dir="rtl">
      <table className="w-full text-sm border-collapse">
        <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
          <tr>
            <Th k="id">#</Th>
            <Th k="item_name">الصنف</Th>
            <Th k="customer_name">العميل</Th>
            <Th k="contact_phone">الهاتف</Th>
            {isCCOrAdmin && <Th k="branch_name">الفرع</Th>}
            <Th k="status">الحالة</Th>
            <Th k="priority">الأولوية</Th>
            <Th k="quantity_requested" cls="w-16">الكمية</Th>
            <Th k="follow_up_date">المتابعة</Th>
            <Th k="created_at">تاريخ الإنشاء</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => {
            const col = COLUMNS.find(c => c.key === r.status) || COLUMNS[0]
            const pri = PRIORITY_BADGE[r.priority] || PRIORITY_BADGE.normal
            return (
              <tr
                key={r.id}
                className="hover:bg-blue-50/40 cursor-pointer transition-colors"
                onClick={() => onOpen(r)}
              >
                <td className="px-3 py-2.5 text-gray-400 font-mono text-xs">#{r.id}</td>
                <td className="px-3 py-2.5 max-w-[220px]">
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
                <td className="px-3 py-2.5">
                  <div className="text-gray-800 truncate max-w-[140px]">{r.customer_name}</div>
                </td>
                <td className="px-3 py-2.5 text-xs font-mono text-gray-600" dir="ltr">{r.contact_phone}</td>
                {isCCOrAdmin && (
                  <td className="px-3 py-2.5 text-xs text-brand-700 bg-brand-50/30">
                    {r.branch_name}
                  </td>
                )}
                <td className="px-3 py-2.5">
                  <span
                    className="text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
                    style={{ background: col.bg, color: col.color, border: `1px solid ${col.dot}` }}
                  >
                    {col.label}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${pri.cls}`}>
                    {pri.label}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-center text-gray-700 font-medium">{r.quantity_requested}</td>
                <td className="px-3 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                  {r.follow_up_date
                    ? <span className="text-orange-600">{formatDate(r.follow_up_date)}</span>
                    : <span className="text-gray-300">—</span>}
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-400 whitespace-nowrap">{timeAgo(r.created_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


// ── Main Kanban Page ──────────────────────────────────────────────────────────
export default function ReservationsKanban() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const isCCOrAdmin = user?.role === 'admin' || user?.role === 'call_center'

  const [viewMode, setViewMode] = useState('kanban')   // 'kanban' | 'list'
  const [filterBranch, setFilterBranch] = useState('')
  const [filterPriority, setFilterPriority] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      // API returns paginated {results:[]} or plain []
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
  })

  const reservationsQuery = useQuery({
    queryKey: ['reservations-kanban', filterBranch, filterPriority, filterStatus, search, dateFrom, dateTo],
    queryFn: () => reservationsApi.list({
      branch:    filterBranch    || undefined,
      priority:  filterPriority  || undefined,
      status:    filterStatus    || undefined,
      search:    search          || undefined,
      date_from: dateFrom        || undefined,
      date_to:   dateTo          || undefined,
      page_size: 500,
    }).then(r => r.data.results || r.data),
    staleTime:        30_000,  // don't refetch if data is fresh from a tab switch
    refetchInterval:  60_000,  // background refresh every 60s (was 30s — halves the load)
  })
 
  const rawList = reservationsQuery.data
  const reservationsList = Array.isArray(rawList) ? rawList : []
  const hasData = reservationsList.length > 0
  const isLoading = reservationsQuery.isLoading
  const reservationsError = reservationsQuery.error

  // Status change mutation with optimistic update so the card moves immediately
  const changeMutation = useMutation({
    mutationFn: ({ id, status, note }) => reservationsApi.changeStatus(id, status, note || ''),
    onMutate: async ({ id, status: newStatus }) => {
      // Cancel any in-flight refetches so they don't overwrite our optimistic data
      await qc.cancelQueries({ queryKey: ['reservations-kanban'] })
      const previous = qc.getQueryData(['reservations-kanban',
        filterBranch, filterPriority, filterStatus, search, dateFrom, dateTo])
      // Optimistically move the card to the new column
      qc.setQueryData(['reservations-kanban',
        filterBranch, filterPriority, filterStatus, search, dateFrom, dateTo],
        (old) => Array.isArray(old)
          ? old.map(r => r.id === id ? { ...r, status: newStatus } : r)
          : old
      )
      return { previous }
    },
    onError: (_err, _vars, context) => {
      // Roll back on error
      if (context?.previous !== undefined) {
        qc.setQueryData(['reservations-kanban',
          filterBranch, filterPriority, filterStatus, search, dateFrom, dateTo],
          context.previous)
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['reservations-kanban'] }),
  })

  // Navigate to full detail page
  const openDetail = (r) => navigate(`/reservations/${r.id}`)

  // Track which reservation IDs have a mutation in flight (for button guards)
  const [pendingIds, setPendingIds] = useState(new Set())
  const handleStatusChange = (id, newStatus, note) => {
    if (pendingIds.has(id)) return   // double-click guard
    setPendingIds(prev => new Set(prev).add(id))
    changeMutation.mutate(
      { id, status: newStatus, note },
      { onSettled: () => setPendingIds(prev => { const s = new Set(prev); s.delete(id); return s }) }
    )
  }


  // Branch filter helper (applied consistently everywhere)
  const passesBranchFilter = (r) =>
    isCCOrAdmin || r.branch_id === user?.branch_id

  // Group by status — cancelled column also absorbs 'expired' cards
  const grouped = COLUMNS.reduce((acc, col) => {
    if (col.key === 'cancelled') {
      // Merge cancelled + expired into the single cancelled column
      acc[col.key] = reservationsList.filter(r =>
        (r.status === 'cancelled' || r.status === 'expired') && passesBranchFilter(r)
      )
    } else {
      acc[col.key] = reservationsList.filter(r =>
        r.status === col.key && passesBranchFilter(r)
      )
    }
    return acc
  }, {})

  const totalActive = reservationsList.filter(r => !['fulfilled','cancelled','expired'].includes(r.status)).length


  return (
    <div className="flex flex-col h-full" dir="rtl">

      {/* Top bar */}
      <div className="bg-white border-b">
        {/* Row 1: title + view toggle + new button */}
        <div className="flex items-center gap-3 px-5 py-2.5 flex-wrap">
          <div>
            <h1 className="text-lg font-bold text-gray-900">لوحة الحجوزات</h1>
            <p className="text-xs text-gray-400">{totalActive} حجز نشط · {reservationsList.length} إجمالي</p>
          </div>

          <div className="flex-1" />

          {/* View mode toggle */}
          <div className="flex items-center rounded-lg border border-gray-200 overflow-hidden text-sm">
            <button
              onClick={() => setViewMode('kanban')}
              className={`px-3 py-1.5 transition-colors ${viewMode === 'kanban' ? 'bg-brand-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              title="عرض كانبان"
            >
              ⬛ كانبان
            </button>
            <button
              onClick={() => navigate('/reservations/list')}
              className="px-3 py-1.5 border-r border-gray-200 transition-colors bg-white text-gray-600 hover:bg-gray-50"
              title="عرض قائمة مع إجراءات جماعية"
            >
              ☰ قائمة
            </button>
          </div>

          <CanDo module="reservations" action="create">
            <button
              onClick={() => navigate('/reservations/new')}
              className="bg-brand-600 text-white px-4 py-1.5 rounded-lg text-sm font-semibold hover:bg-brand-700 transition-colors whitespace-nowrap"
            >
              + حجز جديد
            </button>
          </CanDo>
        </div>

        {/* Row 2: filters */}
        <div className="flex items-center gap-2 px-5 pb-2.5 flex-wrap">
          {/* Search */}
          <input
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-44 focus:outline-none focus:border-blue-300"
            placeholder="بحث..."
            aria-label="بحث في الحجوزات"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          {/* Branch filter (CC/admin only) */}
          {isCCOrAdmin && (
            <BranchSelect
              size="sm"
              value={filterBranch}
              onChange={setFilterBranch}
              branches={branches}
              allLabel="كل الفروع"
              className="w-52"
            />
          )}

          {/* Priority filter */}
          <select
            aria-label="تصفية حسب الأولوية"
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
            value={filterPriority}
            onChange={e => setFilterPriority(e.target.value)}
          >
            <option value="">كل الأولويات</option>
            <option value="urgent">عاجل</option>
            <option value="chronic">مزمن</option>
            <option value="normal">عادي</option>
          </select>

          {/* Status filter (more useful in list mode) */}
          <select
            aria-label="تصفية حسب الحالة"
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
          >
            <option value="">كل الحالات</option>
            {COLUMNS.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>

          {/* Date range */}
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <span>من</span>
            <input
              type="date"
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-blue-300"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
            />
            <span>إلى</span>
            <input
              type="date"
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-blue-300"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
            />
            {(dateFrom || dateTo) && (
              <button
                onClick={() => { setDateFrom(''); setDateTo('') }}
                className="text-gray-400 hover:text-gray-600 transition-colors text-base leading-none"
                title="مسح التواريخ"
              >✕</button>
            )}
          </div>
        </div>
      </div>

      {/* Content area */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm" role="status" aria-live="polite">
          جاري تحميل الحجوزات...
        </div>
      ) : reservationsError ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-sm">
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3">حدث خطأ أثناء تحميل الحجوزات.</div>
          <button className="px-3 py-1.5 rounded-lg border border-red-300 text-red-700 hover:bg-red-50" onClick={() => reservationsQuery.refetch()}>
            إعادة المحاولة
          </button>
        </div>
      ) : viewMode === 'list' ? (
        <ReservationListView
          reservations={reservationsList}
          onOpen={openDetail}
          isCCOrAdmin={isCCOrAdmin}
        />
      ) : (
        /* Kanban board */
        <div className="flex-1 overflow-x-auto">
          <div className="flex gap-3 p-4 h-full" style={{ width: 'max-content', minWidth: '100%' }}>
            {!hasData ? (
              <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
                لا توجد حجوزات حالياً حسب الفلاتر المحددة.
              </div>
            ) : (
              COLUMNS.map(col => (
                <KanbanColumn
                  key={col.key}
                  col={col}
                  cards={grouped[col.key] || []}
                  onStatusChange={handleStatusChange}
                  onOpen={openDetail}
                  isCCOrAdmin={isCCOrAdmin}
                  pendingIds={pendingIds}
                />
              ))
            )}
          </div>
        </div>
      )}

    </div>
  )
}
