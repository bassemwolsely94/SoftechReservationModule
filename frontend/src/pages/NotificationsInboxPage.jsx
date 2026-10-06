/**
 * NotificationsInboxPage.jsx  —  /notifications
 * Full-page notification inbox: filters (category / read-state / search) +
 * bulk actions (mark read · snooze · delete) + "load more" pagination.
 */
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { notificationsApi } from '../api/client'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatin = s => s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
const timeAgo = d => { try { return toLatin(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) } catch { return '' } }

const CATEGORIES = [
  ['', 'كل الفئات'], ['global', 'عام'], ['reservations', 'الحجوزات'], ['delivery', 'التوصيل'],
  ['transfers', 'التحويلات'], ['demand', 'الطلب الضائع'], ['followups', 'المتابعات'],
  ['monitoring', 'المراقبة'], ['settings', 'النظام'], ['reports', 'التقارير'], ['mentions', 'الإشارات'],
]
const PAGE = 30

export default function NotificationsInboxPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [category, setCategory] = useState('')
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(PAGE)
  const [selected, setSelected] = useState(() => new Set())

  const params = useMemo(() => {
    const p = { limit, offset: 0 }
    if (category) p.category = category
    if (unreadOnly) p.unread_only = 'true'
    if (search.trim()) p.search = search.trim()
    return p
  }, [category, unreadOnly, search, limit])

  const { data: items = [], isFetching } = useQuery({
    queryKey: ['inbox', params],
    queryFn: () => notificationsApi.list(params).then(r => Array.isArray(r.data) ? r.data : []),
    placeholderData: keepPreviousData,
  })

  const after = () => { setSelected(new Set()); qc.invalidateQueries({ queryKey: ['inbox'] }) }
  const bulk = useMutation({ mutationFn: (body) => notificationsApi.bulk(body), onSuccess: after })

  const allSelected = items.length > 0 && items.every(n => selected.has(n.id))
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(items.map(n => n.id)))
  const toggleOne = (id) => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const ids = [...selected]
  const runBulk = (action, minutes) => { if (ids.length) bulk.mutate({ ids, action, minutes }) }

  function openNotif(n) {
    if (!n.is_read) bulk.mutate({ ids: [n.id], action: 'read' })
    if (n.reservation) navigate(`/reservations/${n.reservation}`)
    else if (n.transfer_request_id_ref) navigate(`/transfers/${n.transfer_request_id_ref}`)
    else if (n.demand_id_ref) navigate(`/demands/${n.demand_id_ref}`)
  }

  return (
    <div className="p-6 max-w-4xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">📥 كل الإشعارات</h1>
        <span className="text-sm text-gray-400">{items.length}{items.length >= limit ? '+' : ''} إشعار</span>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <select value={category} onChange={e => { setCategory(e.target.value); setLimit(PAGE) }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white">
          {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input value={search} onChange={e => { setSearch(e.target.value); setLimit(PAGE) }}
          placeholder="بحث…" className="text-sm border border-gray-200 rounded-lg px-3 py-2 flex-1 min-w-[160px]" />
        <button onClick={() => { setUnreadOnly(u => !u); setLimit(PAGE) }}
          className={`text-sm rounded-lg px-3 py-2 border font-medium ${unreadOnly ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-200'}`}>
          غير المقروء فقط
        </button>
      </div>

      {/* Bulk bar */}
      {ids.length > 0 && (
        <div className="flex items-center gap-2 mb-3 bg-brand-50 border border-brand-100 rounded-xl px-3 py-2">
          <span className="text-sm font-medium text-brand-800">{ids.length} محدد</span>
          <div className="flex-1" />
          <button onClick={() => runBulk('read')} className="text-xs bg-white border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50">تعليم كمقروء</button>
          <button onClick={() => runBulk('snooze', 60)} className="text-xs bg-white border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-amber-50">تأجيل ساعة</button>
          <button onClick={() => runBulk('delete')} className="text-xs bg-white border border-red-200 text-red-600 rounded-lg px-3 py-1.5 hover:bg-red-50">حذف</button>
        </div>
      )}

      {/* List */}
      <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100 bg-gray-50">
          <input type="checkbox" checked={allSelected} onChange={toggleAll} className="accent-brand-600" />
          <span className="text-xs text-gray-400">تحديد الكل</span>
        </div>
        {items.length === 0 ? (
          <div className="py-16 text-center text-gray-400 text-sm">{isFetching ? 'جارٍ التحميل…' : 'لا توجد إشعارات'}</div>
        ) : items.map(n => (
          <div key={n.id} className={`flex items-start gap-3 px-4 py-3 border-b border-gray-50 last:border-0 ${!n.is_read ? 'bg-blue-50/40' : ''}`}>
            <input type="checkbox" checked={selected.has(n.id)} onChange={() => toggleOne(n.id)} className="mt-1 accent-brand-600" />
            <span className="text-lg leading-none mt-0.5">{n.type_icon}</span>
            <div className="flex-1 min-w-0 cursor-pointer" onClick={() => openNotif(n)}>
              <div className={`text-sm ${n.is_read ? 'text-gray-700' : 'font-semibold text-gray-900'}`}>{n.title}</div>
              {n.body && <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{n.body}</div>}
              <div className="text-[11px] text-gray-400 mt-1">{n.time_ago || timeAgo(n.created_at)} · {n.type_label}</div>
            </div>
            {!n.is_read && <span className="w-2 h-2 rounded-full bg-blue-500 mt-1.5 shrink-0" />}
          </div>
        ))}
      </div>

      {items.length >= limit && (
        <div className="text-center mt-4">
          <button onClick={() => setLimit(l => l + PAGE)} disabled={isFetching}
            className="text-sm border border-gray-200 rounded-xl px-5 py-2 hover:bg-gray-50 disabled:opacity-50">
            {isFetching ? 'جارٍ التحميل…' : 'تحميل المزيد'}
          </button>
        </div>
      )}
    </div>
  )
}
