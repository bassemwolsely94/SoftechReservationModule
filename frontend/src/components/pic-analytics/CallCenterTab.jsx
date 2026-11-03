/**
 * CallCenterTab — «مركز الاتصال» (doc 33 §7). Management only: one row per call-center agent
 * extension plus the team's new-PICs-sold card. All numbers come from the server.
 */
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../SortTh'
import { KpiCard, fmt, fmtDuration } from './KpiCards'
import Explain from './Explain'

const getKey = r => r.agent_ext
const getValue = (r, k) => (k === 'name' ? (r.staff_name || r.pbx_name || '') : r[k])

export default function CallCenterTab({ data }) {
  const { sorted: rows, headerProps } = useSortableRows(data?.rows || [], { getValue, persistKey: 'pic-call-center' })
  const kb = useGridKeyboard({ rows, getKey })
  const cell = 'px-3 py-2 tabular-nums'
  const th = data?.thresholds || {}
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-tour="pic-analytics-calls-team">
        <KpiCard label="عملاء جدد باعها الفريق" value={fmt(data?.team_new_pics_sold)} tone="green"
                 sub="بكود البائع في الإعدادات" />
      </div>
      <Explain id="cc-table" hint="سطر لكل رقم داخلي لموظف في مركز الاتصال، عن مكالمات الفترة (بدون مكالمات التحويل)."
               lines={[
                 `مكالمة ← شراء %: من المكالمات المُجابة مع عملاء، كام نسبة اللي اشترى صاحبها خلال ${th.purchase_days ?? '—'} أيام. «شراء نفس اليوم %» = اشترى في نفس يوم المكالمة.`,
                 'عملاء تم الوصول إليهم = عملاء مميّزين ردّ عليهم الموظف. متوسط المحاولات = كام اتصال صادر لنفس الرقم في اليوم لحد ما رد. لم يُوصل إليهم = أرقام ما ردّتش خلال اليوم.',
                 'عملاء جدد باعهم: عملاء أول شراء لهم في الفترة بفاتورة بكود البائع المربوط بالموظف (— لو الرقم الداخلي غير مرتبط بموظف له كود). بطاقة الفريق = كل فواتير أكواد البائعين المحددة في إعدادات الكول سنتر، وممكن تختلف عن مجموع الصفوف (الصف بيعتمد على كود الموظف المربوط بالرقم الداخلي).',
                 'المكالمة على رقم مشترك بين أكتر من PIC بتتحسب مرة واحدة على أحدث مشترٍ.',
               ]}
               example={`موظف رد على 40 مكالمة لعملاء، و12 منهم اشتروا خلال ${th.purchase_days ?? '—'} أيام ← 30%`} />
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-calls-grid">
        <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <SortTh {...headerProps('name', 'text')} className="px-3 py-2 text-right">الموظف</SortTh>
                <SortTh {...headerProps('agent_ext', 'number')} className={cell}>الداخلي</SortTh>
                <SortTh {...headerProps('calls_in', 'number')} className={cell}>واردة</SortTh>
                <SortTh {...headerProps('calls_out', 'number')} className={cell}>صادرة</SortTh>
                <SortTh {...headerProps('answered', 'number')} className={cell}>تمت الإجابة</SortTh>
                <SortTh {...headerProps('talk_seconds', 'number')} className={cell}>وقت الحديث</SortTh>
                <SortTh {...headerProps('pics_reached', 'number')} className={cell}>عملاء تم الوصول إليهم</SortTh>
                <SortTh {...headerProps('call_to_purchase_pct', 'number')} className={cell}>مكالمة ← شراء %</SortTh>
                <SortTh {...headerProps('call_to_purchase_same_day_pct', 'number')} className={cell}>شراء نفس اليوم %</SortTh>
                <SortTh {...headerProps('new_pics_sold', 'number')} className={cell}>عملاء جدد باعهم</SortTh>
                <SortTh {...headerProps('unanswered_out', 'number')} className={cell}>صادرة بلا رد</SortTh>
                <SortTh {...headerProps('avg_attempts_to_reach', 'number')} className={cell}>متوسط المحاولات</SortTh>
                <SortTh {...headerProps('not_reached', 'number')} className={cell}>لم يُوصل إليهم</SortTh>
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
                    <td className={cell}>{r.call_to_purchase_same_day_pct == null ? '—' : `${fmt(r.call_to_purchase_same_day_pct, 1)}%`}</td>
                    <td className={cell} title={r.new_pics_sold == null ? 'الرقم الداخلي غير مرتبط بموظف له كود سوفتك' : undefined}>{fmt(r.new_pics_sold)}</td>
                    <td className={cell}>{fmt(r.unanswered_out)}</td>
                    <td className={cell}>{fmt(r.avg_attempts_to_reach, 2)}</td><td className={cell}>{fmt(r.not_reached)}</td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={13} className="px-3 py-6 text-center text-gray-400">لا مكالمات في هذه الفترة</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
