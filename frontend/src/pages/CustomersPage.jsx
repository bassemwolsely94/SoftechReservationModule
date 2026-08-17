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

const CHURN_CFG = {
  low:      { label: 'مستقر',   cls: 'bg-green-50  text-green-700',  dot: '#10b981' },
  medium:   { label: 'مراقبة', cls: 'bg-yellow-50 text-yellow-700', dot: '#f59e0b' },
  high:     { label: 'خطر',    cls: 'bg-red-50    text-red-700',    dot: '#ef4444' },
  critical: { label: 'حرج',    cls: 'bg-red-100   text-red-900',    dot: '#991b1b' },
}

const SEG_COLOR = {
  vip:     'bg-purple-100 text-purple-700',
  loyal:   'bg-blue-100   text-blue-700',
  regular: 'bg-gray-100   text-gray-600',
  at_risk: 'bg-orange-100 text-orange-700',
  dormant: 'bg-gray-50    text-gray-500',
  new:     'bg-green-50   text-green-600',
  churned: 'bg-red-100    text-red-700',
}

function ChurnBadge({ segment }) {
  if (!segment) return null
  const c = CHURN_CFG[segment] || CHURN_CFG.low
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${c.cls}`}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.dot }} />
      {c.label}
    </span>
  )
}

export default function CustomersPage() {
  const navigate = useNavigate()
  const [search,          setSearch]          = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page,            setPage]            = useState(1)
  const [debounceTimer,   setDebounceTimer]   = useState(null)
  const [churnFilter,     setChurnFilter]     = useState('')
  const [ordering,        setOrdering]        = useState('')

  const handleSearch = useCallback((value) => {
    setSearch(value)
    setPage(1)
    if (debounceTimer) clearTimeout(debounceTimer)
    const t = setTimeout(() => setDebouncedSearch(value), 300)
    setDebounceTimer(t)
  }, [debounceTimer])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['customers', debouncedSearch, page, churnFilter, ordering],
    queryFn: () => customersApi.list({
      search:        debouncedSearch  || undefined,
      churn_segment: churnFilter      || undefined,
      ordering:      ordering         || undefined,
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
        subtitle={`${totalCount.toLocaleString('en-US')} عميل مسجَّل`}
      />

      <div className="page-body">
        {/* Search + filter bar */}
        <div className="mb-4 flex gap-2 items-center flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-md">
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

          {/* Churn filter */}
          <select
            value={churnFilter}
            onChange={e => { setChurnFilter(e.target.value); setPage(1) }}
            className="input-field text-xs py-2 w-36"
          >
            <option value="">كل العملاء</option>
            <option value="critical">🚨 انقطاع حرج</option>
            <option value="high">🔴 انقطاع مرتفع</option>
            <option value="medium">⚠️ انقطاع متوسط</option>
            <option value="low">✅ مستقر</option>
          </select>

          {/* Sort */}
          <select
            value={ordering}
            onChange={e => { setOrdering(e.target.value); setPage(1) }}
            className="input-field text-xs py-2 w-40"
          >
            <option value="">الترتيب: الاسم</option>
            <option value="-churn_score">الأعلى خطر انقطاع</option>
            <option value="-ltv">الأعلى قيمة (LTV)</option>
            <option value="-days_since_last_visit">الأطول غياباً</option>
            <option value="-last_visit_date">آخر زيارة</option>
          </select>

          {(debouncedSearch || churnFilter) && (
            <button
              onClick={() => { setSearch(''); setDebouncedSearch(''); setChurnFilter(''); setPage(1) }}
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
                      <th>القناة / الشريحة</th>
                      <th>خطر الانقطاع</th>
                      <th>آخر زيارة</th>
                      <th>الفرع</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customers.map(c => (
                      <tr
                        key={c.id}
                        onClick={() => navigate(`/customers/${c.id}`)}
                        className={`cursor-pointer ${
                          c.churn_segment === 'critical' ? 'bg-red-50 hover:bg-red-100' :
                          c.churn_segment === 'high'     ? 'hover:bg-orange-50' : ''
                        }`}
                      >
                        {/* Name + SOFTECH code */}
                        <td>
                          <div className="font-semibold text-gray-800">{c.name}</div>
                          {c.softech_id && (
                            <div className="text-xs text-gray-400 font-mono mt-0.5">
                              {c.softech_id}
                            </div>
                          )}
                        </td>

                        {/* Phone */}
                        <td>
                          <div className="font-mono text-sm" dir="ltr">{c.phone}</div>
                          {c.whatsapp_phone && c.whatsapp_phone !== c.phone && (
                            <div className="text-[10px] text-green-600 font-mono" dir="ltr">
                              💬 {c.whatsapp_phone}
                            </div>
                          )}
                        </td>

                        {/* Channel type + RFM segment */}
                        <td>
                          <div className="flex flex-col gap-1">
                            <span className={`badge text-xs ${TYPE_COLOR[c.customer_type_color] || TYPE_COLOR.gray}`}>
                              {c.customer_type_label}
                            </span>
                            {c.segment && (
                              <span className={`badge text-[10px] ${SEG_COLOR[c.segment] || 'bg-gray-100 text-gray-500'}`}>
                                {c.segment}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Churn risk */}
                        <td>
                          {c.churn_segment ? (
                            <div className="flex flex-col gap-1 items-start">
                              <ChurnBadge segment={c.churn_segment} />
                              {c.churn_score > 0 && (
                                <div className="w-16 bg-gray-100 rounded-full h-1.5 mt-0.5">
                                  <div
                                    className={`h-1.5 rounded-full ${
                                      c.churn_score >= 0.7 ? 'bg-red-600' :
                                      c.churn_score >= 0.45 ? 'bg-orange-500' : 'bg-yellow-400'
                                    }`}
                                    style={{ width: `${Math.min(100, c.churn_score * 100)}%` }}
                                  />
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>

                        {/* Days since last visit */}
                        <td>
                          {c.days_since_last_visit != null ? (
                            <div>
                              <span className={`text-sm font-semibold ${
                                c.days_since_last_visit > 180 ? 'text-red-600' :
                                c.days_since_last_visit > 90  ? 'text-orange-500' :
                                'text-gray-700'
                              }`}>
                                {c.days_since_last_visit}د
                              </span>
                              {c.last_visit_date && (
                                <div className="text-[10px] text-gray-400">{c.last_visit_date}</div>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>

                        {/* Branch */}
                        <td className="text-gray-500 text-xs">{c.preferred_branch_name || '—'}</td>
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
                    className={`w-full flex items-center gap-3 px-4 py-3 text-right transition-colors ${
                      c.churn_segment === 'critical' ? 'bg-red-50 hover:bg-red-100' :
                      'hover:bg-brand-50'
                    }`}
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
                      {c.days_since_last_visit != null && (
                        <div className={`text-[10px] mt-0.5 ${
                          c.days_since_last_visit > 180 ? 'text-red-500' :
                          c.days_since_last_visit > 90  ? 'text-orange-500' : 'text-gray-400'
                        }`}>
                          آخر زيارة منذ {c.days_since_last_visit} يوم
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className={`badge text-xs ${TYPE_COLOR[c.customer_type_color] || TYPE_COLOR.gray}`}>
                        {c.customer_type_label}
                      </span>
                      <ChurnBadge segment={c.churn_segment} />
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
              <span className="text-xs text-gray-500">
                صفحة {page} من {totalPages} · {totalCount.toLocaleString('en-US')} نتيجة
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
