/**
 * RetentionPanel — الولاء والتكرار (doc 33 §4/§6): frequency classes A (months bought),
 * B (longest streak), C (buying cycle), loyal count, retention %, the overdue list and the
 * monthly cohort table. All numbers come from the server.
 */
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { BarRow, KpiCard, fmt, fmtDate, fmtPct } from './KpiCards'
import Explain from './Explain'

const CYCLE = [
  ['m1', 'كل شهر أو أقل'], ['m2', 'كل شهرين'], ['m3', 'كل 3 شهور'],
  ['m4_6', 'كل 4–6 شهور'], ['m7_12', 'كل 7–12 شهر'], ['y1plus', 'سنة أو أكثر'], ['', 'غير محدد (أقل من زيارتين)'],
]

function ClassBars({ title, rows, explain }) {
  const max = Math.max(...rows.map(r => r.value), 1)
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-bold text-gray-700">{title}</h3>
      {explain && <Explain className="mb-2" {...explain} />}
      {rows.map(r => <BarRow key={r.label} label={r.label} value={r.value} max={max} />)}
    </div>
  )
}

function Overdue({ data, page, onPage, factor }) {
  const rows = data?.rows || []
  const count = data?.count || 0
  const pages = Math.max(1, Math.ceil(count / 50))
  const kb = useGridKeyboard({ rows, getKey: r => r.pic })
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-overdue">
      <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">عملاء تأخروا عن دورة شرائهم</h3>
      <Explain id="ret-overdue-table" className="px-4 pb-1"
               hint={`الدورة (يوم) = متوسط الأيام بين الزيارات · أيام التأخير = الأيام من آخر زيارة − ${fmt(factor, 1)}× الدورة · إجمالي الشراء = صافي مشترياته (لمدير الفرع: من فرعه فقط)`} />
      <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr><th className="px-3 py-2 text-right">العميل</th>
              <th className="px-3 py-2" title="تاريخ آخر يوم شراء حتى نهاية الفترة">آخر زيارة</th>
              <th className="px-3 py-2" title="متوسط الأيام بين زياراته">الدورة (يوم)</th>
              <th className="px-3 py-2" title={`الأيام من آخر زيارة − ${fmt(factor, 1)}× الدورة`}>أيام التأخير</th>
              <th className="px-3 py-2" title="صافي مشترياته (لمدير الفرع: من فرعه فقط)">إجمالي الشراء</th></tr>
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
      <Explain id="ret-cohorts" className="px-4 pb-1"
               hint="كل سطر = العملاء اللي أول شراء ليهم كان في الشهر ده؛ كل خانة = نسبة منهم رجعت اشترت بعد شهر/شهرين…"
               lines={['«الحجم» = عدد عملاء الفوج. «+1» = النسبة اللي اشترت في الشهر التالي لشهر أول شراء، «+2» بعده بشهرين، وهكذا.',
                       'الخانات اللي لسه ما جاش وقتها (بعد نهاية الفترة) بتفضل فاضية. اللون الأخضر الأغمق = نسبة أعلى.']}
               example="فوج 2026-03 حجمه 200، و70 منهم اشتروا في أبريل ← +1 = 35%" />
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
  const th = data?.thresholds || {}
  const loyalMonths = fr?.loyal_months ?? th.loyal_months
  const factor = th.overdue_factor
  const prev = data?.retention?.prev_period
  const a = fr ? Object.entries(fr.a).map(([k, v]) => ({ label: `${k} شهر`, value: v })) : []
  const b = fr ? Object.entries(fr.b).map(([k, v]) => ({ label: `${k} متتالي`, value: v })) : []
  const c = fr ? CYCLE.map(([k, label]) => ({ label, value: fr.c[k] || 0 })) : []
  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        الكروت وأ/ب/ج عن العملاء اللي اشتروا في الفترة المختارة (من كل الفروع، آخر 12 شهر لحد نهاية الفترة). الاحتفاظ والمجموعات (cohorts) موضحين في سطورهم.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-start" data-tour="pic-analytics-retention-kpis">
        <div className="space-y-1">
          <KpiCard label="الاحتفاظ بالعملاء" value={fmtPct(data?.retention?.retention_pct)} tone="blue"
                   sub={prev ? `مقابل ${prev[0]} → ${prev[1]}` : undefined} />
          <Explain id="ret-retention" hint="من اشترى في الفترة السابقة ورجع اشترى في الفترة دي"
                   lines={[prev ? `الفترة السابقة = نفس عدد الأيام قبل الفترة مباشرة (${prev[0]} → ${prev[1]}).`
                                : 'الفترة السابقة = نفس عدد الأيام قبل الفترة مباشرة.',
                           'النسبة = اللي رجع اشترى ÷ اللي اشترى في الفترة السابقة. بتظهر «—» لو الفترة السابقة قبل بداية بياناتنا.']}
                   example="100 عميل اشتروا في سبتمبر، 32 منهم اشتروا تاني في أكتوبر ← 32%" />
        </div>
        <div className="space-y-1">
          <KpiCard label="عملاء مخلصون" value={fmt(fr?.loyal)} tone="green" />
          <Explain id="ret-loyal" hint={`اشتروا في ${loyalMonths ?? '—'} شهور أو أكثر من آخر 12 شهر`}
                   lines={['بنعد الشهور المختلفة اللي فيها زيارة واحدة على الأقل (نفس عمود «أ»)، والعدد المطلوب للإخلاص إعداد في النظام.']}
                   example={`اشترى في ${loyalMonths ?? '—'} شهور من آخر 12 ← مخلص`} />
        </div>
        <div className="space-y-1">
          <KpiCard label="متأخرون عن دورتهم" value={fmt(fr?.overdue)} tone="red" />
          <Explain id="ret-overdue" hint={`فات على آخر زيارة أكتر من ${fmt(factor, 1)}× المدة المعتادة بين زياراتهم`}
                   lines={['الدورة = متوسط الأيام بين زيارات العميل، فمحتاج زيارتين على الأقل — اللي زار مرة واحدة ملوش دورة ومش بيتعد متأخر.',
                           'التأخير بيتقاس لحد نهاية الفترة المختارة.']}
                   example={`بيشتري كل 30 يوم في المتوسط وآخر زيارة من 50 يوم ← 50 > ${fmt(30 * (factor ?? 0), 0)} ← متأخر`} />
        </div>
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div data-tour="pic-analytics-freq-a">
          <ClassBars title="أ — شهور الشراء (آخر 12 شهر)" rows={a}
                     explain={{ id: 'ret-a', hint: 'في كام شهر مختلف اشترى العميل خلال آخر 12 شهر',
                                lines: ['كل شريط = عدد العملاء اللي عدد شهور شرائهم كده.'],
                                example: 'اشترى في يناير وفبراير ويونيو ← 3 شهور' }} />
        </div>
        <ClassBars title="ب — أطول تتابع شهري" rows={b}
                   explain={{ id: 'ret-b', hint: 'أطول عدد شهور ورا بعض من غير ما يفوّت شهر',
                              lines: ['كل شريط = عدد العملاء اللي أطول تتابع ليهم كده.'],
                              example: 'يناير–فبراير–مارس ثم انقطع ← 3' }} />
        <ClassBars title="ج — دورة الشراء" rows={c}
                   explain={{ id: 'ret-c', hint: 'متوسط عدد الأيام بين زياراته',
                              lines: ['الفئات: كل شهر أو أقل (حتى 31 يوم)، كل شهرين، كل 3 شهور، 4–6، 7–12، وسنة أو أكثر.',
                                      '«غير محدد (أقل من زيارتين)» = عميل زار مرة واحدة بس، فمفيش دورة تتحسب له.',
                                      'فواتير نفس اليوم = زيارة واحدة.'],
                              example: 'زيارات في 1/1 و31/1 و2/3 ← متوسط 30 يوم ← «كل شهر أو أقل»' }} />
      </div>
      <Overdue data={overdue} page={overduePage} onPage={onOverduePage} factor={factor} />
      <Cohorts rows={data?.cohorts} />
    </div>
  )
}
