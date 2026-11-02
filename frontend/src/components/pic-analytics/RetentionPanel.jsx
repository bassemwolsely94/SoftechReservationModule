/**
 * RetentionPanel — الولاء والتكرار (doc 33 §4/§6): frequency classes A (months bought),
 * B (longest streak), C (buying cycle), loyal count, retention %, the overdue list and the
 * monthly cohort table. All numbers come from the server.
 */
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { BarRow, KpiCard, fmt, fmtDate, fmtPct } from './KpiCards'

const CYCLE = [
  ['m1', 'كل شهر أو أقل'], ['m2', 'كل شهرين'], ['m3', 'كل 3 شهور'],
  ['m4_6', 'كل 4–6 شهور'], ['m7_12', 'كل 7–12 شهر'], ['y1plus', 'سنة أو أكثر'], ['', 'غير محدد (أقل من زيارتين)'],
]

function ClassBars({ title, rows }) {
  const max = Math.max(...rows.map(r => r.value), 1)
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-bold text-gray-700 mb-2">{title}</h3>
      {rows.map(r => <BarRow key={r.label} label={r.label} value={r.value} max={max} />)}
    </div>
  )
}

function Overdue({ data, page, onPage }) {
  const rows = data?.rows || []
  const count = data?.count || 0
  const pages = Math.max(1, Math.ceil(count / 50))
  const kb = useGridKeyboard({ rows, getKey: r => r.pic })
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-overdue">
      <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">عملاء تأخروا عن دورة شرائهم</h3>
      <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr><th className="px-3 py-2 text-right">العميل</th><th className="px-3 py-2">آخر زيارة</th>
              <th className="px-3 py-2">الدورة (يوم)</th><th className="px-3 py-2">أيام التأخير</th>
              <th className="px-3 py-2">إجمالي الشراء</th></tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.pic} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 ${rp.className}`}>
                  <td className="px-3 py-1.5">
                    <div className="font-medium text-gray-800">{r.name || '—'}</div>
                    <div className="text-gray-400 tabular-nums">{r.pic}{r.phone ? ` · ${r.phone}` : ''}</div>
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-center">{fmtDate(r.last_visit)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-center">{fmt(r.cycle_days, 1)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-center text-red-600 font-bold">{fmt(r.days_overdue)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-center">{fmt(r.lifetime_net)}</td>
                </tr>
              )
            })}
            {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">لا عملاء متأخرون</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between px-4 py-2 text-xs text-gray-500 border-t border-gray-100">
        <span>{fmt(count)} عميل · صفحة {page} من {pages}</span>
        <span className="flex gap-2">
          <button className="btn-secondary text-xs py-1" disabled={page <= 1} onClick={() => onPage(page - 1)}>← السابق</button>
          <button className="btn-secondary text-xs py-1" disabled={page >= pages} onClick={() => onPage(page + 1)}>التالي →</button>
        </span>
      </div>
    </div>
  )
}

function Cohorts({ rows }) {
  const cols = Array.from({ length: 12 }, (_, i) => i + 1)
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="pic-analytics-cohorts">
      <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">الأفواج الشهرية — نسبة العودة بعد كل شهر</h3>
      <table className="w-full text-xs">
        <thead className="bg-gray-50 text-gray-500">
          <tr><th className="px-3 py-2 text-right">شهر أول شراء</th><th className="px-3 py-2">الحجم</th>
            {cols.map(k => <th key={k} className="px-2 py-2">+{k}</th>)}</tr>
        </thead>
        <tbody>
          {(rows || []).map(r => (
            <tr key={r.cohort} className="border-t border-gray-100">
              <td className="px-3 py-1.5 tabular-nums">{r.cohort}</td>
              <td className="px-3 py-1.5 tabular-nums text-center">{fmt(r.size)}</td>
              {cols.map((k, i) => {
                const v = r.months[i]
                return (
                  <td key={k} className="px-2 py-1.5 tabular-nums text-center"
                      style={v === undefined ? undefined : { background: `rgba(34,197,94,${Math.min(v, 100) / 200})` }}>
                    {v === undefined ? '' : fmt(v, 0)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function RetentionPanel({ data, overdue, overduePage, onOverduePage }) {
  const fr = data?.frequency
  const a = fr ? Object.entries(fr.a).map(([k, v]) => ({ label: `${k} شهر`, value: v })) : []
  const b = fr ? Object.entries(fr.b).map(([k, v]) => ({ label: `${k} متتالي`, value: v })) : []
  const c = fr ? CYCLE.map(([k, label]) => ({ label, value: fr.c[k] || 0 })) : []
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-tour="pic-analytics-retention-kpis">
        <KpiCard label="الاحتفاظ بالعملاء" value={fmtPct(data?.retention?.retention_pct)} tone="blue"
                 sub={data?.retention?.prev_period ? `مقابل ${data.retention.prev_period[0]} → ${data.retention.prev_period[1]}` : undefined} />
        <KpiCard label="عملاء مخلصون" value={fmt(fr?.loyal)} tone="green" sub="اشتروا 10 شهور أو أكثر من 12" />
        <KpiCard label="متأخرون عن دورتهم" value={fmt(fr?.overdue)} tone="red" />
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div data-tour="pic-analytics-freq-a"><ClassBars title="أ — شهور الشراء (آخر 12 شهر)" rows={a} /></div>
        <ClassBars title="ب — أطول تتابع شهري" rows={b} />
        <ClassBars title="ج — دورة الشراء" rows={c} />
      </div>
      <Overdue data={overdue} page={overduePage} onPage={onOverduePage} />
      <Cohorts rows={data?.cohorts} />
    </div>
  )
}
