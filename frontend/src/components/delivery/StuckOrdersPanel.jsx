/**
 * C21 — «طلبات عالقة»: open delivery orders older than the threshold, with what the hourly check read
 * from SOFTECH for each one. Read-only: the server decides and (only when its switch is on) closes.
 * Collapsed by default so the board stays calm.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { deliveryApi } from '../../api/client'
import SortTh from '../SortTh'
import useSortableRows from '../../hooks/useSortableRows'

const VERDICT = {
  close:      { label: 'مُسلَّم في SOFTECH — يُغلق', cls: 'bg-green-50 text-green-700' },
  cancel:     { label: 'ملغى في SOFTECH — يُلغى', cls: 'bg-gray-100 text-gray-700' },
  still_open: { label: 'مفتوح في SOFTECH — راجعه', cls: 'bg-amber-50 text-amber-700' },
  not_found:  { label: 'غير موجود في SOFTECH', cls: 'bg-amber-50 text-amber-700' },
  cash_hold:  { label: 'عليه تحصيل — يدوي', cls: 'bg-blue-50 text-blue-700' },
  no_key:     { label: 'بدون رقم SOFTECH', cls: 'bg-gray-50 text-gray-500' },
}

export default function StuckOrdersPanel({ onOpen }) {
  const [open, setOpen] = useState(false)
  const { data } = useQuery({
    queryKey: ['delivery-stuck-orders'],
    queryFn: () => deliveryApi.stuckOrders().then(r => r.data),
    staleTime: 300_000,
  })
  const rows = data?.results || []
  const t = useSortableRows(rows, { defaultSort: { key: 'age_hours', dir: 'desc', type: 'number' } })
  if (!data || !data.total) return null

  const counts = data.last_run?.counts || {}
  const finished = (counts.close || 0) + (counts.cancel || 0)
  return (
    <div className="bg-white rounded-xl border border-amber-200" data-tour="delivery-dashboard-stuck">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm text-right">
        <span className="font-semibold text-amber-800">⏳ طلبات مفتوحة أقدم من {data.min_age_hours} ساعة: {data.total}</span>
        {data.last_run?.at && (
          <span className="text-gray-600">SOFTECH خلّص منها {finished}</span>
        )}
        <span className={`text-xs px-2 py-0.5 rounded ${data.enabled ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
          {data.enabled ? 'الإغلاق التلقائي شغّال' : 'الإغلاق التلقائي مطفأ — تجربة بس'}
        </span>
        <span className="mr-auto text-gray-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="overflow-x-auto border-t border-amber-100 max-h-96">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <SortTh {...t.headerProps('id', 'number')} className="text-right px-3 py-2">#</SortTh>
                <SortTh {...t.headerProps('branch_name', 'text')} className="text-right px-3 py-2">الفرع</SortTh>
                <SortTh {...t.headerProps('customer_name', 'text')} className="text-right px-3 py-2">العميل</SortTh>
                <SortTh {...t.headerProps('status_label', 'text')} className="text-right px-3 py-2">الحالة هنا</SortTh>
                <SortTh {...t.headerProps('age_hours', 'number')} className="text-center px-3 py-2">العمر (ساعة)</SortTh>
                <SortTh {...t.headerProps('verdict', 'text')} className="text-right px-3 py-2">آخر فحص SOFTECH</SortTh>
              </tr>
            </thead>
            <tbody>
              {t.sorted.map(r => {
                const v = VERDICT[r.verdict]
                return (
                  <tr key={r.id} className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer" onClick={() => onOpen?.(r.id)}>
                    <td className="px-3 py-1.5 font-mono">{r.id}</td>
                    <td className="px-3 py-1.5">{r.branch_name}</td>
                    <td className="px-3 py-1.5">{r.customer_name}</td>
                    <td className="px-3 py-1.5">{r.status_label}</td>
                    <td className="px-3 py-1.5 text-center">{r.age_hours}</td>
                    <td className="px-3 py-1.5">
                      {v ? <span className={`text-xs px-2 py-0.5 rounded ${v.cls}`}>{v.label}</span>
                         : <span className="text-xs text-gray-400">لم يُفحص بعد</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {data.total > rows.length && (
            <p className="px-4 py-2 text-xs text-gray-500">يظهر أقدم {rows.length} من {data.total}.</p>
          )}
        </div>
      )}
    </div>
  )
}
