import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { reservationsApi, branchesApi } from '../api/client'
import { StatusBadge, PriorityBadge, STATUS_OPTIONS, PRIORITY_OPTIONS } from '../components/StatusBadge'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

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
      <select
        className="input-field w-44"
        value={filters.branch}
        onChange={e => onChange({ ...filters, branch: e.target.value, page: 1 })}
      >
        <option value="">كل الفروع</option>
        {(branches || []).map(b => (
          <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
        ))}
      </select>
      <button
        className="btn-secondary text-sm"
        onClick={() => onChange({ search: '', status: '', priority: '', branch: '', page: 1 })}
      >
        مسح الفلاتر
      </button>
    </div>
  )
}

export default function ReservationsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [filters, setFilters] = useState({
    search: '',
    status: searchParams.get('status') || '',
    priority: '',
    branch: '',
    page: 1,
  })

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['reservations', filters],
    queryFn: () => reservationsApi.list({
      search: filters.search || undefined,
      status: filters.status || undefined,
      priority: filters.priority || undefined,
      branch: filters.branch || undefined,
      page: filters.page,
    }).then(r => r.data),
    keepPreviousData: true,
  })

  const { data: branches } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const reservations = data?.results || []
  const totalCount = data?.count || 0
  const totalPages = Math.ceil(totalCount / 50)

  return (
    <div className="p-6 max-w-7xl mx-auto" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-black text-gray-800">الحجوزات</h1>
          <p className="text-sm text-gray-500">{totalCount.toLocaleString('ar-EG')} حجز</p>
        </div>
        <button onClick={() => navigate('/reservations/new')} className="btn-primary flex items-center gap-2">
          <span className="text-lg">+</span>
          حجز جديد
        </button>
      </div>

      <FilterBar filters={filters} onChange={setFilters} branches={branches} />

      {/* Table */}
      <div className={`card p-0 overflow-hidden transition-opacity ${isFetching ? 'opacity-70' : ''}`}>
        {isLoading ? (
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
                  onClick={() => navigate(`/reservations/${r.id}`)}
                  className="hover:bg-brand-50 cursor-pointer transition-colors duration-100"
                >
                  <td className="px-4 py-3 text-gray-400 font-mono text-xs">{r.id}</td>
                  <td className="px-4 py-3">
                    <div className="font-semibold text-gray-800">{r.contact_name}</div>
                    <div className="text-xs text-gray-400">{r.contact_phone}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-gray-800 font-medium">{r.item_name}</div>
                    <div className="text-xs text-gray-400">الكمية: {r.quantity_requested}</div>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{r.branch_name}</td>
                  <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                  <td className="px-4 py-3"><PriorityBadge priority={r.priority} /></td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {r.follow_up_date
                      ? format(new Date(r.follow_up_date), 'd MMM', { locale: ar })
                      : '—'}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {format(new Date(r.created_at), 'd MMM yyyy', { locale: ar })}
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
