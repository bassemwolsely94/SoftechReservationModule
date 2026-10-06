/**
 * FinanceSchemaPage.jsx
 * Route: /finance/schema
 * Admin only — Phase 0 schema discovery management.
 *
 * Features:
 * - View all discovered SOFTECH tables with metadata
 * - Trigger discovery scan
 * - Confirm / enable tables for sync
 * - View column schemas and sample data
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { financeApi } from '../api/client'

const CATEGORY_AR = {
  journal:   'يومية',
  accounts:  'حسابات',
  cash:      'خزينة',
  bank:      'بنك',
  payment:   'مدفوعات',
  invoice:   'فواتير',
  expense:   'مصروفات',
  payroll:   'رواتب',
  budget:    'موازنة',
  tax:       'ضرائب',
  inventory: 'مخزون',
  revenue:   'إيرادات',
  purchase:  'مشتريات',
  receivable:'ذمم مدينة',
  payable:   'ذمم دائنة',
  other:     'أخرى',
}

const CATEGORY_COLORS = {
  journal:   'bg-purple-100 text-purple-700',
  accounts:  'bg-blue-100 text-blue-700',
  cash:      'bg-green-100 text-green-700',
  bank:      'bg-cyan-100 text-cyan-700',
  payment:   'bg-indigo-100 text-indigo-700',
  invoice:   'bg-amber-100 text-amber-700',
  expense:   'bg-orange-100 text-orange-700',
  payroll:   'bg-rose-100 text-rose-700',
  inventory: 'bg-teal-100 text-teal-700',
  other:     'bg-gray-100 text-gray-600',
}

function ColumnList({ columns }) {
  if (!columns?.length) return <div className="text-gray-400 text-sm">لا توجد أعمدة</div>
  return (
    <div className="flex flex-wrap gap-1.5">
      {columns.map(col => (
        <span key={col.colid}
          className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs font-mono"
          title={`type: ${col.type}, length: ${col.length}`}
        >
          {col.name}
        </span>
      ))}
    </div>
  )
}

export default function FinanceSchemaPage() {
  const [search,    setSearch]    = useState('')
  const [category,  setCategory]  = useState('')
  const [filterCon, setFilterCon] = useState('')  // '' | 'confirmed' | 'unconfirmed'
  const [expanded,  setExpanded]  = useState(null)

  const qc = useQueryClient()

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['finance-schema', search, category, filterCon],
    queryFn:  () => financeApi.schema({
      search:       search   || undefined,
      category:     category || undefined,
      is_confirmed: filterCon === 'confirmed' ? 'true' : filterCon === 'unconfirmed' ? 'false' : undefined,
    }).then(r => r.data),
    staleTime: 30_000,
  })

  const discoverMut = useMutation({
    mutationFn: () => financeApi.triggerDiscover(),
    onSuccess:  () => {
      alert('بدأ اكتشاف المخطط في الخلفية. انتظر 2-3 دقائق ثم أعد التحميل.')
      setTimeout(() => refetch(), 5000)
    },
    onError: (err) => alert(`خطأ: ${err.response?.data?.detail || err.message}`),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }) => financeApi.updateSchema(id, data),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['finance-schema'] }),
  })

  const tables = data?.results || data || []
  const categories = [...new Set(tables.map(t => t.category).filter(Boolean))]

  return (
    <div className="space-y-4" dir="rtl">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-700">اكتشاف المخطط — Phase 0</h2>
          <p className="text-xs text-gray-400">الجداول المكتشفة في SOFTECH ذات الصلة المالية</p>
        </div>
        <div className="flex gap-2 mr-auto flex-wrap">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="بحث باسم الجدول…"
            className="border rounded-lg px-3 py-1.5 text-sm w-44 focus:ring-2 focus:ring-green-500"
          />
          <select value={category} onChange={e => setCategory(e.target.value)}
            className="border rounded-lg px-3 py-1.5 text-sm">
            <option value="">كل الفئات</option>
            {categories.map(c => (
              <option key={c} value={c}>{CATEGORY_AR[c] || c}</option>
            ))}
          </select>
          <select value={filterCon} onChange={e => setFilterCon(e.target.value)}
            className="border rounded-lg px-3 py-1.5 text-sm">
            <option value="">الكل</option>
            <option value="confirmed">مؤكد ✓</option>
            <option value="unconfirmed">غير مؤكد</option>
          </select>
          <button
            onClick={() => discoverMut.mutate()}
            disabled={discoverMut.isPending}
            className="px-4 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
          >
            {discoverMut.isPending ? 'جارٍ الاكتشاف…' : '🔍 تشغيل الاكتشاف'}
          </button>
        </div>
      </div>

      {/* Stats */}
      {!isLoading && tables.length > 0 && (
        <div className="flex gap-4 text-sm text-gray-500">
          <span>إجمالي: <strong>{tables.length}</strong></span>
          <span>مؤكد: <strong className="text-green-600">{tables.filter(t => t.is_confirmed).length}</strong></span>
          <span>مفعّل للمزامنة: <strong className="text-blue-600">{tables.filter(t => t.sync_enabled).length}</strong></span>
        </div>
      )}

      {isLoading && <div className="text-center py-12 text-gray-400 animate-pulse">جارٍ التحميل…</div>}

      {!isLoading && tables.length === 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-8 text-center">
          <div className="text-5xl mb-3">🔍</div>
          <div className="text-amber-800 font-semibold">لم يتم الاكتشاف بعد</div>
          <div className="text-amber-700 text-sm mt-1">
            اضغط "تشغيل الاكتشاف" لبدء Phase 0 — سيفحص جميع جداول SOFTECHDB9.
          </div>
        </div>
      )}

      {/* Table list */}
      {tables.map(t => (
        <div key={t.id}
          className={`bg-white rounded-xl border overflow-hidden transition-all
            ${t.is_confirmed ? 'border-green-200' : 'border-gray-200'}`}
        >
          {/* Row header */}
          <div
            className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50"
            onClick={() => setExpanded(expanded === t.id ? null : t.id)}
          >
            <span className="text-gray-400">{expanded === t.id ? '▾' : '▸'}</span>
            <span className="font-mono text-sm font-medium text-gray-800 flex-1">{t.table_name}</span>

            <span className={`px-2 py-0.5 rounded-full text-xs ${CATEGORY_COLORS[t.category] || CATEGORY_COLORS.other}`}>
              {CATEGORY_AR[t.category] || t.category || '—'}
            </span>

            <span className="text-xs text-gray-400">{t.col_count || 0} عمود</span>
            <span className="text-xs text-gray-400">{t.row_count?.toLocaleString('en-US')} صف</span>

            {/* Confirmed toggle */}
            <button
              onClick={e => {
                e.stopPropagation()
                updateMut.mutate({ id: t.id, data: { is_confirmed: !t.is_confirmed } })
              }}
              className={`px-2 py-0.5 text-xs rounded-full border transition-colors
                ${t.is_confirmed
                  ? 'bg-green-50 border-green-300 text-green-700 hover:bg-red-50 hover:text-red-600 hover:border-red-200'
                  : 'bg-gray-50 border-gray-300 text-gray-500 hover:bg-green-50 hover:text-green-700 hover:border-green-300'
                }`}
              title="تأكيد / إلغاء تأكيد"
            >
              {t.is_confirmed ? '✓ مؤكد' : 'تأكيد'}
            </button>

            {/* Sync enabled toggle */}
            <button
              onClick={e => {
                e.stopPropagation()
                updateMut.mutate({ id: t.id, data: { sync_enabled: !t.sync_enabled } })
              }}
              className={`px-2 py-0.5 text-xs rounded-full border transition-colors
                ${t.sync_enabled
                  ? 'bg-blue-50 border-blue-300 text-blue-700'
                  : 'bg-gray-50 border-gray-300 text-gray-400'
                }`}
              title="تفعيل / تعطيل المزامنة"
            >
              {t.sync_enabled ? '⟲ مزامنة' : 'تفعيل'}
            </button>
          </div>

          {/* Expanded content */}
          {expanded === t.id && (
            <div className="border-t border-gray-100 px-4 py-3 space-y-3 bg-gray-50">
              <div>
                <div className="text-xs text-gray-500 mb-1">الغرض المستنتج</div>
                <div className="text-sm text-gray-700">{t.inferred_purpose || '—'}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500 mb-1">الأعمدة</div>
                {/* Load full detail for columns */}
                <ColumnDetailLoader tableId={t.id} />
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function ColumnDetailLoader({ tableId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['finance-schema-detail', tableId],
    queryFn:  () => financeApi.schemaDetail(tableId).then(r => r.data),
    staleTime: 300_000,
  })
  if (isLoading) return <div className="text-gray-400 text-xs">جارٍ التحميل…</div>
  return <ColumnList columns={data?.columns} />
}
