/**
 * ExclusionsPanel — management only: the PICs left out of the analytics (doc 33 §15).
 * Inline and calm (no modal): the active list with «إرجاع», an add form (PIC code + required reason)
 * and a lazily loaded «اقتراحات» list whose «استبعاد» button pre-fills the form (the reason is still
 * required — nothing is ever excluded automatically). The server enforces everything and audits each change.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { picAnalyticsApi } from '../../api/client'
import { fmt, fmtDate } from './KpiCards'

export default function ExclusionsPanel({ params, ready }) {
  const qc = useQueryClient()
  const reasonRef = useRef(null)
  const [pic, setPic] = useState('')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  const [showSug, setShowSug] = useState(false)
  const list = useQuery({ queryKey: ['pic-analytics', 'exclusions'], queryFn: () => picAnalyticsApi.exclusions().then(r => r.data.rows) })
  const sug = useQuery({
    queryKey: ['pic-analytics', 'exclusion-suggestions', params],
    queryFn: () => picAnalyticsApi.exclusionSuggestions({ from: params.from, to: params.to, branch: params.branch }).then(r => r.data.rows),
    enabled: showSug && ready,
  })
  const done = () => { setErr(''); qc.invalidateQueries({ queryKey: ['pic-analytics'] }) }      // every figure changes
  const fail = e => setErr(e?.response?.data?.detail || 'تعذّر تنفيذ العملية')
  const add = useMutation({
    mutationFn: () => picAnalyticsApi.exclude({ pic: pic.trim(), reason: reason.trim() }),
    onSuccess: () => { setPic(''); setReason(''); done() }, onError: fail,
  })
  const back = useMutation({ mutationFn: id => picAnalyticsApi.include(id), onSuccess: done, onError: fail })
  const rows = list.data || []
  const prefill = p => { setPic(p); setErr(''); setTimeout(() => reasonRef.current?.focus(), 0) }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3" data-tour="pic-analytics-exclusions">
      <div>
        <h3 className="text-sm font-bold text-gray-700">العملاء المستبعدون من التحليل</h3>
        <p className="text-xs text-gray-400">
          حسابات ليست عملاء أفراد (حساب جاري، كود طبيب، رقم هاتف وهمي…) تُحذف من كل الأعداد والمتوسطات والترتيب، وتظهر مبيعاتها في سطر «عملاء مستبعدون» فقط.
        </p>
      </div>
      {err && <p className="text-xs text-red-600">{err}</p>}
      <div className="space-y-1">
        {rows.length === 0 && <p className="text-xs text-gray-400">لا يوجد عملاء مستبعدون</p>}
        {rows.map(x => (
          <div key={x.id} className="flex items-center justify-between gap-3 text-xs border-b border-gray-100 py-1.5">
            <span>
              <b className="tabular-nums">{x.pic}</b> · {x.customer_name || '—'} — {x.reason}
              <span className="text-gray-400"> · {x.added_by || '—'} · {fmtDate(x.added_at)} · آخر 12 شهر: {fmt(x.net_12m)} ({fmt(x.visits_12m)} زيارة)</span>
            </span>
            <button className="text-brand-700 hover:underline shrink-0" disabled={back.isPending} onClick={() => back.mutate(x.id)}>إرجاع</button>
          </div>
        ))}
      </div>
      <form className="flex gap-2 flex-wrap items-center" onSubmit={e => { e.preventDefault(); if (pic.trim() && reason.trim()) add.mutate() }}>
        <input className="input-field text-xs py-1.5 w-32" placeholder="كود PIC" value={pic} maxLength={30} onChange={e => setPic(e.target.value)} />
        <input ref={reasonRef} className="input-field text-xs py-1.5 flex-1 min-w-[12rem] max-w-md" placeholder="سبب الاستبعاد (مطلوب)"
               value={reason} maxLength={255} onChange={e => setReason(e.target.value)} />
        <button className="btn-secondary text-xs py-1.5" disabled={add.isPending || !pic.trim() || !reason.trim()}>استبعاد</button>
        <button type="button" className="text-xs text-brand-700 hover:underline" onClick={() => setShowSug(s => !s)}>
          {showSug ? 'إخفاء الاقتراحات' : 'اقتراحات'}
        </button>
      </form>
      {showSug && (
        <div className="space-y-1">
          {sug.isLoading && <p className="text-xs text-gray-400">… جارٍ التحميل</p>}
          {sug.data?.length === 0 && <p className="text-xs text-gray-400">لا اقتراحات في هذه الفترة</p>}
          {(sug.data || []).map(s => (
            <div key={s.pic} className="flex items-center justify-between gap-3 text-xs py-1 border-b border-gray-50">
              <span>
                <b className="tabular-nums">{s.pic}</b> · {s.customer_name || '—'}
                <span className="text-gray-400"> · {s.rule_labels.join('، ')} · {fmt(s.visits)} زيارة · {fmt(s.net)}</span>
              </span>
              <button className="btn-secondary text-xs py-0.5 shrink-0" onClick={() => prefill(s.pic)}>استبعاد</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
