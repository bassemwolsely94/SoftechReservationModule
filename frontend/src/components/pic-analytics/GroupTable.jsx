/**
 * GroupTable — one table for branches / salespeople / channels / categories (doc 33 §6).
 * Rows come from the server as {rows, total}; GP is shown only when the rows carry it.
 */
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { fmt } from './KpiCards'

const getKey = r => r.key

export default function GroupTable({ data, title, note, firstLabel = 'الاسم' }) {
  const rows = data?.rows || []
  const total = data?.total
  const hasGp = rows.some(r => 'gp' in r) || (total && 'gp' in total)
  const kb = useGridKeyboard({ rows, getKey })
  const cell = 'px-3 py-2 tabular-nums'
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {title && <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">{title}</h3>}
      <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-3 py-2 text-right">{firstLabel}</th>
              <th className={cell}>عملاء</th><th className={cell}>جدد</th><th className={cell}>عائدون</th>
              <th className={cell}>مُعاد تنشيطهم</th><th className={cell}>زيارات</th><th className={cell}>صافي</th>
              {hasGp && <th className={cell}>الربح</th>}
              <th className={cell}>سلة (صافي)</th><th className={cell}>أصناف/زيارة</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.key} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 ${rp.className}`}>
                  <td className="px-3 py-2 font-medium text-gray-800">{r.label}</td>
                  <td className={cell}>{fmt(r.distinct_pics)}</td><td className={cell}>{fmt(r.new)}</td>
                  <td className={cell}>{fmt(r.returning)}</td><td className={cell}>{fmt(r.reactivated)}</td>
                  <td className={cell}>{fmt(r.visits)}</td><td className={cell}>{fmt(r.net)}</td>
                  {hasGp && <td className={cell}>{fmt(r.gp)}</td>}
                  <td className={cell}>{fmt(r.basket_net, 2)}</td><td className={cell}>{fmt(r.units_per_visit, 2)}</td>
                </tr>
              )
            })}
            {total && (
              <tr className="border-t-2 border-gray-300 bg-gray-50 font-bold">
                <td className="px-3 py-2">{total.label}</td>
                <td className={cell}>{fmt(total.distinct_pics)}</td><td className={cell}>{fmt(total.new)}</td>
                <td className={cell}>{fmt(total.returning)}</td><td className={cell}>{fmt(total.reactivated)}</td>
                <td className={cell}>{fmt(total.visits)}</td><td className={cell}>{fmt(total.net)}</td>
                {hasGp && <td className={cell}>{fmt(total.gp)}</td>}
                <td className={cell}>{fmt(total.basket_net, 2)}</td><td className={cell}>{fmt(total.units_per_visit, 2)}</td>
              </tr>
            )}
            {rows.length === 0 && (
              <tr><td colSpan={10} className="px-3 py-6 text-center text-gray-400">لا بيانات</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {note && <p className="text-xs text-gray-400 px-4 py-2">{note}</p>}
    </div>
  )
}
