/**
 * CallCenterTab — «مركز الاتصال» (doc 33 §7). Management only: one row per call-center agent
 * extension plus the team's new-PICs-sold card. All numbers come from the server.
 */
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { KpiCard, fmt, fmtDuration } from './KpiCards'

const getKey = r => r.agent_ext

export default function CallCenterTab({ data }) {
  const rows = data?.rows || []
  const kb = useGridKeyboard({ rows, getKey })
  const cell = 'px-3 py-2 tabular-nums'
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-tour="pic-analytics-calls-team">
        <KpiCard label="عملاء جدد باعها الفريق" value={fmt(data?.team_new_pics_sold)} tone="green"
                 sub="بكود البائع في الإعدادات" />
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-calls-grid">
        <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="px-3 py-2 text-right">الموظف</th><th className={cell}>تحويلة</th>
                <th className={cell}>واردة</th><th className={cell}>صادرة</th><th className={cell}>تمت الإجابة</th>
                <th className={cell}>وقت الحديث</th><th className={cell}>عملاء تم الوصول إليهم</th>
                <th className={cell}>مكالمة ← شراء %</th><th className={cell}>صادرة بلا رد</th>
                <th className={cell}>متوسط المحاولات</th><th className={cell}>لم يُوصل إليهم</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const rp = kb.rowProps(r)
                return (
                  <tr key={r.agent_ext} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 ${rp.className}`}>
                    <td className="px-3 py-2 font-medium text-gray-800">{r.staff_name || r.pbx_name || '—'}</td>
                    <td className={cell}>{r.agent_ext}</td>
                    <td className={cell}>{fmt(r.calls_in)}</td><td className={cell}>{fmt(r.calls_out)}</td>
                    <td className={cell}>{fmt(r.answered)}</td><td className={cell}>{fmtDuration(r.talk_seconds)}</td>
                    <td className={cell}>{fmt(r.pics_reached)}</td>
                    <td className={cell}>{r.call_to_purchase_pct == null ? '—' : `${fmt(r.call_to_purchase_pct, 1)}%`}</td>
                    <td className={cell}>{fmt(r.unanswered_out)}</td>
                    <td className={cell}>{fmt(r.avg_attempts_to_reach, 2)}</td><td className={cell}>{fmt(r.not_reached)}</td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={11} className="px-3 py-6 text-center text-gray-400">لا مكالمات في هذه الفترة</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
