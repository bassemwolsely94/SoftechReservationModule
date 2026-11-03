/**
 * NumbersTab — «أرقام جديدة» (doc 33 §8). Management only. Numbers that called (or were called)
 * with no PIC, plus the conversions (became a PIC / bought). Numbers arrive masked; the server
 * dials and labels by an opaque number id. Labelling a number removes it from the list.
 */
import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { picAnalyticsApi } from '../../api/client'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { errText } from '../../pages/supply/supplyUi'
import { KpiCard, fmt, fmtDate, fmtDateTime, fmtDuration } from './KpiCards'
import { Pager } from './MissedTab'

const LABELS = [['staff', 'موظف'], ['supplier', 'مورد'], ['branch', 'فرع'], ['doctor', 'طبيب'], ['spam', 'مزعج'], ['other', 'أخرى']]
const getKey = r => r.number_id
const getConvKey = r => r.pic

function Conversions({ data }) {
  const rows = data?.rows || []
  const kb = useGridKeyboard({ rows, getKey: getConvKey })
  const cell = 'px-3 py-2 tabular-nums'
  return (
    <div className="space-y-3" data-tour="pic-analytics-conversions">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="أصبحوا عملاء" value={fmt(data?.became_pic)} tone="green" />
        <KpiCard label="أصبحوا عملاء واشتروا" value={fmt(data?.became_pic_and_bought)} tone="brand" />
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">أرقام تحوّلت إلى عملاء</h3>
        <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="px-3 py-2 text-right">العميل</th><th className="px-3 py-2 text-right">الرقم</th>
                <th className={cell}>أول مكالمة</th><th className={cell}>تاريخ التسجيل</th><th className={cell}>اشترى</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const rp = kb.rowProps(r)
                return (
                  <tr key={r.pic} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 ${rp.className}`}>
                    <td className="px-3 py-2 font-medium text-gray-800">{r.customer_name || r.pic}</td>
                    <td className="px-3 py-2 tabular-nums" dir="ltr">{r.number || '—'}</td>
                    <td className={cell}>{fmtDateTime(r.first_call)}</td><td className={cell}>{fmtDate(r.created_at)}</td>
                    <td className={cell}>{r.bought ? 'نعم' : 'لا'}</td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">لا تحوّلات في هذه الفترة</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function NumbersTab({ params, ready }) {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState({})
  const [label, setLabel] = useState({})

  const list = useQuery({
    queryKey: ['pic-analytics', 'numbers', params, page],
    queryFn: () => picAnalyticsApi.numbers({ ...params, page, page_size: 50 }).then(r => r.data),
    enabled: ready, staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })
  const conv = useQuery({
    queryKey: ['pic-analytics', 'conversions', params],
    queryFn: () => picAnalyticsApi.conversions(params).then(r => r.data),
    enabled: ready, staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })
  const mark = (id, ok, text) => setStatus(s => ({ ...s, [id]: { ok, text } }))
  const dial = useMutation({
    mutationFn: id => picAnalyticsApi.numberDial(id).then(r => r.data),
    onSuccess: (d, id) => mark(id, true, d.detail),
    onError: (e, id) => mark(id, false, errText(e, 'تعذّر الاتصال')),
  })
  const doLabel = useMutation({
    mutationFn: ({ id, value }) => picAnalyticsApi.labelNumber({ number_id: id, label: value, note: '' }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pic-analytics'] }),     // the row leaves the list
    onError: (e, { id }) => {
      mark(id, false, errText(e, 'تعذّر التصنيف'))
      setLabel(l => ({ ...l, [id]: '' }))
    },
  })

  const rows = list.data?.rows || []
  const kb = useGridKeyboard({ rows, getKey })
  const cell = 'px-3 py-2 tabular-nums'
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-numbers-grid">
        <h3 className="text-sm font-bold text-gray-700 px-4 pt-3">أرقام لا ترتبط بأي عميل</h3>
        <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="px-3 py-2 text-right">الرقم</th><th className={cell}>النوع</th>
                <th className={cell}>واردة</th><th className={cell}>صادرة</th><th className={cell}>تمت الإجابة</th><th className={cell}>فائتة</th>
                <th className={cell}>أول مكالمة</th><th className={cell}>آخر مكالمة</th><th className="px-3 py-2 text-right">آخر موظف</th>
                <th className={cell}>وقت الحديث</th><th className="px-3 py-2 text-right">إجراء</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const rp = kb.rowProps(r)
                const st = status[r.number_id]
                return (
                  <tr key={r.number_id} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 align-top ${rp.className}`}>
                    <td className="px-3 py-2 tabular-nums" dir="ltr">{r.number || '—'}</td>
                    <td className={cell}>{r.kind === 'mobile' ? 'موبايل' : 'أرضي'}</td>
                    <td className={cell}>{fmt(r.calls_in)}</td><td className={cell}>{fmt(r.calls_out)}</td>
                    <td className={cell}>{fmt(r.answered)}</td><td className={cell}>{fmt(r.missed)}</td>
                    <td className={cell}>{fmtDateTime(r.first_call)}</td><td className={cell}>{fmtDateTime(r.last_call)}</td>
                    <td className="px-3 py-2">{r.last_agent ? (r.last_agent.staff_name || r.last_agent.pbx_name || r.last_agent.agent_ext) : '—'}</td>
                    <td className={cell}>{fmtDuration(r.talk_seconds)}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1.5 flex-wrap items-center">
                        <button className="btn-secondary text-xs py-1" disabled={dial.isPending && dial.variables === r.number_id}
                                onClick={() => dial.mutate(r.number_id)}>📞 اتصل</button>
                        <select className="input text-xs py-1" value={label[r.number_id] || ''}
                                onChange={e => {
                                  const v = e.target.value
                                  setLabel(l => ({ ...l, [r.number_id]: v }))
                                  if (v) doLabel.mutate({ id: r.number_id, value: v })
                                }}>
                          <option value="">ليس عميلاً…</option>
                          {LABELS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
                        </select>
                      </div>
                      {st && <p className={`mt-1 text-xs ${st.ok ? 'text-green-700' : 'text-red-700'}`}>{st.text}</p>}
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={11} className="px-3 py-6 text-center text-gray-400">لا أرقام جديدة</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager count={list.data?.count || 0} page={page} onPage={setPage} noun="رقم" />
      </div>
      <Conversions data={conv.data} />
    </div>
  )
}
