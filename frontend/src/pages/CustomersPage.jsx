import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { customersApi } from '../api/client'
import { EmptyState, SkeletonTable, PageHeader } from '../components/ui'

const TYPE_COLOR = {
  blue:  'bg-blue-100 text-blue-700',
  green: 'bg-green-100 text-green-700',
  gray:  'bg-gray-100 text-gray-600',
}

export default function CustomersPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [debounceTimer, setDebounceTimer] = useState(null)

  const handleSearch = useCallback((value) => {
    setSearch(value)
    setPage(1)
    if (debounceTimer) clearTimeout(debounceTimer)
    const t = setTimeout(() => setDebouncedSearch(value), 300)
    setDebounceTimer(t)
  }, [debounceTimer])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['customers', debouncedSearch, page],
    queryFn: () => customersApi.list({
      search: debouncedSearch || undefined,
      page,
    }).then(r => r.data),
    placeholderData: prev => prev,
  })

  const customers   = data?.results || []
  const totalCount  = data?.count   || 0
  const totalPages  = Math.ceil(totalCount / 50)

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      <PageHeader
        title="العملاء"
        subtitle={`${totalCount.toLocaleString('ar-EG')} عميل مسجَّل`}
      />

      <div className="page-body">
        {/* Search bar */}
        <div className="mb-4 flex gap-2 items-center">
          <div className="relative flex-1 max-w-md">
            <input
              type="text"
              placeholder="ابحث بالاسم أو رقم الهاتف أو كود SOFTECH..."
              className="input-field pr-9"
              value={search}
              onChange={e => handleSearch(e.target.value)}
              autoFocus
            />
            <span className="absolute right-3 top-2.5 text-gray-400 pointer-events-none">
              🔍
            </span>
          </div>
          {debouncedSearch && (
            <button
              onClick={() => { setSearch(''); setDebouncedSearch(''); setPage(1) }}
              className="btn-ghost text-xs"
            >
              مسح ✕
            </button>
          )}
          {isFetching && !isLoading && (
            <span className="text-xs text-gray-400 animate-pulse">جارٍ التحديث...</span>
          )}
        </div>

        {/* Table card */}
        <div className={`card p-0 overflow-hidden transition-opacity duration-200 ${isFetching && !isLoading ? 'opacity-70' : ''}`}>
          {isLoading ? (
            <div className="p-2">
              <SkeletonTable rows={10} cols={5} />
            </div>
          ) : customers.length === 0 ? (
            <EmptyState
              preset={debouncedSearch ? 'search' : 'customers'}
              action={
                debouncedSearch ? (
                  <button
                    onClick={() => { setSearch(''); setDebouncedSearch('') }}
                    className="btn-secondary text-sm"
                  >
                    مسح البحث
                  </button>
                ) : null
              }
            />
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden sm:block overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>الاسم</th>
                      <th>الهاتف</th>
                      <th>النوع</th>
                      <th>الفرع المفضل</th>
                      <th>الخصم</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customers.map(c => (
                      <tr
                        key={c.id}
                        onClick={() => navigate(`/customers/${c.id}`)}
                        className="cursor-pointer"
                      >
                        <td>
                          <div className="font-semibold text-gray-800">{c.name}</div>
                          {c.softech_id && (
                            <div className="text-xs text-gray-400 font-mono mt-0.5">
                              {c.softech_id}
                            </div>
                          )}
                        </td>
                        <td>
                          <div className="font-mono text-sm" dir="ltr">{c.phone}</div>
                          {c.phone_alt && (
                            <div className="text-xs text-gray-400 font-mono" dir="ltr">
                              {c.phone_alt}
                            </div>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${TYPE_COLOR[c.customer_type_color] || TYPE_COLOR.gray}`}>
                            {c.customer_type_label}
                          </span>
                        </td>
                        <td className="text-gray-500 text-xs">{c.preferred_branch_name || '—'}</td>
                        <td className="text-gray-600 tabnum">
                          {c.discount_percent > 0 ? `${c.discount_percent}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="sm:hidden divide-y divide-gray-50">
                {customers.map(c => (
                  <button
                    key={c.id}
                    onClick={() => navigate(`/customers/${c.id}`)}
                    className="w-full flex items-center gap-3 px-4 py-3 text-right hover:bg-brand-50 transition-colors"
                  >
                    {/* Avatar */}
                    <div className="w-10 h-10 rounded-full bg-brand-100 flex items-center justify-center shrink-0">
                      <span className="text-brand-700 font-bold text-sm">
                        {c.name?.[0] || '?'}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-gray-800 truncate">{c.name}</div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5" dir="ltr">
                        {c.phone}
                      </div>
                    </div>
                    <span className={`badge text-xs shrink-0 ${TYPE_COLOR[c.customer_type_color] || TYPE_COLOR.gray}`}>
                      {c.customer_type_label}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
              <span className="text-xs text-gray-500">
                صفحة {page} من {totalPages} · {totalCount.toLocaleString('ar-EG')} نتيجة
              </span>
              <div className="flex gap-1.5">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage(p => p - 1)}
                  className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
                >
                  ← السابق
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage(p => p + 1)}
                  className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
                >
                  التالي →
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
