/**
 * MissedTab — «المكالمات الفائتة» (doc 33 §7). Management only. Summary cards, weekday × hour
 * heatmap, the action list (rows) and the unanswered-outgoing section. Numbers arrive masked and
 * the browser never gets a raw one: «اتصل» and «جدولة معاودة» are server-side actions that show the
 * server's answer inline (no modals).
 */
import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { picAnalyticsApi } from '../../api/client'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { errText } from '../../pages/supply/supplyUi'
import { KpiCard, fmt, fmtDateTime } from './KpiCards'
import Heatmap from './Heatmap'
import Explain from './Explain'

const PAGE_SIZE = 50
const getKey = r => r.call_id
const getAgent = r => r.agent_ext

export function Pager({ count, page, onPage, noun }) {
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  return (
    <div className="flex items-center justify-between px-4 py-2 border-t border-gray-100 text-xs text-gray-500">
      <span>{fmt(count)} {noun} · صفحة {page} من {pages}</span>
      <div className="flex gap-2">
        <button className="btn-secondary text-xs py-1" disabled={page <= 1} onClick={() => onPage(page - 1)}>← السابق</button>
        <button className="btn-secondary text-xs py-1" disabled={page >= pages} onClick={() => onPage(page + 1)}>التالي →</button>
      </div>
    </div>
  )
}

function Unanswered({ rows }) {
  const kb = useGridKeyboard({ rows, getKey: getAgent })
  const cell = 'px-3 py-2 tabular-nums'
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-unanswered">
      <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">مكالمات صادرة لم يُرد عليها</h3>
      <Explain className="px-4 pb-1" hint="مكالمات اتصلنا بيها والعميل ما ردّش (لا رد، مشغول، فشل) — لكل موظف."
               lines={['محاولات = كل المكالمات الصادرة للأرقام دي، بلا رد = اللي ماتردش منها. أرقام تم الوصول إليها = أرقام رد صاحبها في نفس اليوم، ولم يُوصل إليها = أرقام ما ردّتش خلال اليوم.',
                       'متوسط المحاولات = كام اتصال لنفس الرقم في اليوم لحد أول رد.']}
               example="اتصلنا بنفس الرقم 3 مرات في يوم، والتالتة ردّ ← تم الوصول بعد 3 محاولات" />
      <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-3 py-2 text-right">الموظف</th><th className={cell}>محاولات</th><th className={cell}>بلا رد</th>
              <th className={cell}>أرقام تم الوصول إليها</th><th className={cell}>لم يُوصل إليها</th><th className={cell}>متوسط المحاولات</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.agent_ext} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 ${rp.className}`}>
                  <td className="px-3 py-2 font-medium text-gray-800">{r.staff_name || r.pbx_name || r.agent_ext}</td>
                  <td className={cell}>{fmt(r.attempts)}</td><td className={cell}>{fmt(r.unanswered)}</td>
                  <td className={cell}>{fmt(r.reached_numbers)}</td><td className={cell}>{fmt(r.not_reached)}</td>
                  <td className={cell}>{fmt(r.avg_attempts_to_reach, 2)}</td>
                </tr>
              )
            })}
            {rows.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">لا بيانات</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function MissedTab({ params, ready }) {
  const qc = useQueryClient()
  const [onlyOpen, setOnlyOpen] = useState(true)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState({})           // call_id -> {ok, text}
  const [cb, setCb] = useState(null)                 // call_id with the call-back form open
  const [due, setDue] = useState('')
  const [note, setNote] = useState('')

  const common = { enabled: ready, staleTime: 2 * 60_000, placeholderData: keepPreviousData }
  const summary = useQuery({
    queryKey: ['pic-analytics', 'missed', params],
    queryFn: () => picAnalyticsApi.missed(params).then(r => r.data), ...common,
  })
  const rowsQ = useQuery({
    queryKey: ['pic-analytics', 'missed-rows', params, onlyOpen, page],
    queryFn: () => picAnalyticsApi.missedRows({ ...params, only_not_returned: onlyOpen ? 1 : 0, page, page_size: PAGE_SIZE }).then(r => r.data),
    ...common,
  })
  const unans = useQuery({
    queryKey: ['pic-analytics', 'unanswered', params],
    queryFn: () => picAnalyticsApi.unanswered(params).then(r => r.data), ...common,
  })

  const mark = (id, ok, text) => setStatus(s => ({ ...s, [id]: { ok, text } }))
  const dial = useMutation({
    mutationFn: id => picAnalyticsApi.missedDial(id).then(r => r.data),
    onSuccess: (d, id) => mark(id, true, d.detail),
    onError: (e, id) => mark(id, false, errText(e, 'تعذّر الاتصال')),
  })
  const schedule = useMutation({
    mutationFn: ({ id }) => picAnalyticsApi.missedCallback(id, { due: new Date(due).toISOString(), note }).then(r => r.data),
    onSuccess: (d, { id }) => {
      mark(id, true, 'تمت جدولة المعاودة ✓'); setCb(null); setDue(''); setNote('')
      qc.invalidateQueries({ queryKey: ['pic-analytics'] })      // the row shows its call-back marker now
      qc.invalidateQueries({ queryKey: ['callbacks'] })
      qc.invalidateQueries({ queryKey: ['callcenter-dashboard'] })
    },
    onError: (e, { id }) => mark(id, false, errText(e, 'تعذّرت الجدولة')),
  })

  const s = summary.data
  const th = s?.thresholds || rowsQ.data?.thresholds || {}
  const rows = rowsQ.data?.rows || []
  const kb = useGridKeyboard({ rows, getKey })
  const maxQ = Math.max(1, ...(s?.by_queue || []).map(x => x.missed))
  const cell = 'px-3 py-2 tabular-nums'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3" data-tour="pic-analytics-missed-cards">
        <KpiCard label="مكالمات فائتة" value={fmt(s?.missed)} tone="red" />
        <KpiCard label="أرقام فائتة" value={fmt(s?.missed_numbers)} tone="amber" />
        <KpiCard label="تم الرد عليها" value={fmt(s?.returned)} tone="green" />
        <KpiCard label="لم يُرد عليها" value={fmt(s?.not_returned)} tone="red" />
        <KpiCard label="وسيط الدقائق للرد" value={fmt(s?.median_minutes_to_return, 1)} tone="blue" />
      </div>

      <Explain id="ms-cards" hint="الفائتة = مكالمة واردة ما رد عليها حد (تركها في الانتظار، لا رد، مشغول). مكالمات التحويل مش بتتعد."
               lines={[
                 `«تم الرد عليها» = بعدها مكالمة مُجابة بنفس الرقم (واردة أو صادرة) خلال ${th.return_hours ?? '—'} ساعة. «لم يُرد عليها» = مفيش اتصال مُجاب خلال المهلة دي.`,
                 'أرقام فائتة = عدد الأرقام المختلفة (الرقم ممكن يفوت أكتر من مرة). وسيط الدقائق للرد = نص المكالمات اللي اتردّ عليها اتردّ عليها في المدة دي أو أقل.',
                 'قائمة الاتصال تحت = الفائتة اللي لسه محدش كلّم رقمها، والصف بيختفي أول ما حد يكلّمهم.',
               ]}
               example={`اتصل 3 مرات ولا حد رد، وبعد ساعة كلّمناه فرد ← الفائتة اتردّ عليها (ضمن ${th.return_hours ?? '—'} ساعة)`} />
      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-4" data-tour="pic-analytics-missed-heatmap">
          <h3 className="text-sm font-bold text-gray-700">الفائتة حسب اليوم والساعة</h3>
          <Explain className="mb-2" id="ms-heatmap" hint="كل خانة = عدد المكالمات الفائتة في يوم وساعة معيّنين (السبت أول الأسبوع). الأحمر الأغمق = أكتر. بيوضح أنهي أوقات بنخسر فيها مكالمات." />
          <Heatmap cells={s?.heatmap} />
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h3 className="text-sm font-bold text-gray-700">حسب الطابور</h3>
          <Explain className="mb-2" hint="الطابور = خط الاستقبال اللي دخلت عليه المكالمة الفائتة." />
          {(s?.by_queue || []).map(x => (
            <div key={x.queue || '—'} className="flex items-center gap-2 py-1 text-xs">
              <span className="w-24 truncate text-gray-600" title={x.queue}>{x.queue || '—'}</span>
              <div className="flex-1 h-2 bg-gray-100 rounded"><div className="h-2 rounded bg-red-400" style={{ width: `${Math.round(x.missed / maxQ * 100)}%` }} /></div>
              <span className="tabular-nums w-10 text-left">{fmt(x.missed)}</span>
            </div>
          ))}
          {!(s?.by_queue || []).length && <p className="text-xs text-gray-400">لا بيانات</p>}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-missed-rows">
        <div className="flex items-center justify-between px-4 pt-3 gap-3 flex-wrap">
          <h3 className="text-sm font-bold text-gray-700">قائمة الاتصال</h3>
          <label className="text-xs text-gray-600 flex items-center gap-1.5">
            <input type="checkbox" checked={onlyOpen} onChange={e => { setOnlyOpen(e.target.checked); setPage(1) }} />
            غير المُعاد الاتصال بها فقط
          </label>
        </div>
        <Explain id="ms-rows" className="px-4 pt-1"
                 hint="كل صف = مكالمة فائتة واحدة، مربوطة بالعميل (لو الرقم معروف) وقيمته وهل اشترى بعدها."
                 lines={[`«اشترى خلال ${th.purchase_days ?? '—'} أيام» = فيه فاتورة لنفس العميل بعد المكالمة في المدة دي. «تم الرد» = أول مكالمة مُجابة بنفس الرقم بعدها، وكام دقيقة بعد.`,
                         '«اتصل» بيرنّ تليفونك أنت وبيوصّلك بالعميل. «جدولة معاودة» بتسجّل موعد في قايمة المعاودات.']} />
        {onlyOpen && <p className="text-xs text-gray-400 px-4 pt-1">الأرقام المصنّفة (موظف، مورد…) لا تظهر هنا — تجدها في تبويب «أرقام جديدة» ← الأرقام المصنّفة.</p>}
        <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="px-3 py-2 text-right">وقت المكالمة</th><th className="px-3 py-2 text-right">الرقم</th>
                <th className="px-3 py-2 text-right">العميل</th><th className={cell}>الشريحة</th>
                <th className={cell}>إجمالي صافي</th><th className={cell}>آخر شراء</th>
                <th className={cell}>{`اشترى خلال ${th.purchase_days ?? '—'} أيام`}</th><th className={cell}>تم الرد</th><th className="px-3 py-2 text-right">إجراء</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const rp = kb.rowProps(r)
                const st = status[r.call_id]
                return (
                  <tr key={r.call_id} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 align-top ${rp.className}`}>
                    <td className="px-3 py-2 whitespace-nowrap">{fmtDateTime(r.call_at)}</td>
                    <td className="px-3 py-2 tabular-nums" dir="ltr">{r.customer_number || '—'}</td>
                    <td className="px-3 py-2">
                      {r.customer_name || (r.shared_pics?.length > 1 ? 'رقم مشترك' : '—')}
                      {r.pic_excluded && <span className="ms-1 text-gray-400">(مستبعد)</span>}
                    </td>
                    <td className={cell}>{r.segment || '—'}</td>
                    <td className={cell}>{fmt(r.lifetime_net)}</td>
                    <td className={cell}>{r.last_purchase ? String(r.last_purchase).slice(0, 10) : '—'}</td>
                    <td className={cell}>{r.pic_excluded ? 'مستبعد' : r.pic ? (r.bought_within_7d ? 'نعم' : 'لا') : '—'}</td>
                    <td className={cell}>{r.returned_at ? `${fmtDateTime(r.returned_at)} (${fmt(r.minutes_to_return, 0)}د)` : '—'}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1.5 flex-wrap">
                        <button className="btn-secondary text-xs py-1" disabled={dial.isPending && dial.variables === r.call_id}
                                onClick={() => dial.mutate(r.call_id)}>📞 اتصل</button>
                        {r.callback_pending
                          ? <span className="text-xs text-amber-700 py-1">🔔 معاودة مجدولة {fmtDateTime(r.callback_pending.due)}</span>
                          : <button className="btn-secondary text-xs py-1" onClick={() => setCb(cb === r.call_id ? null : r.call_id)}>🔔 جدولة معاودة</button>}
                      </div>
                      {cb === r.call_id && (
                        <div className="mt-2 flex gap-1.5 flex-wrap items-center">
                          <input type="datetime-local" className="input text-xs py-1" value={due} onChange={e => setDue(e.target.value)} />
                          <input className="input text-xs py-1" maxLength={500} placeholder="ملاحظة (اختياري)" value={note} onChange={e => setNote(e.target.value)} />
                          <button className="btn-primary text-xs py-1" disabled={!due || schedule.isPending}
                                  onClick={() => schedule.mutate({ id: r.call_id })}>حفظ</button>
                        </div>
                      )}
                      {st && <p className={`mt-1 text-xs ${st.ok ? 'text-green-700' : 'text-red-700'}`}>{st.text}</p>}
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={9} className="px-3 py-6 text-center text-gray-400">لا مكالمات فائتة</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager count={rowsQ.data?.count || 0} page={page} onPage={setPage} noun="مكالمة" />
      </div>

      <Unanswered rows={unans.data?.rows || []} />
    </div>
  )
}
