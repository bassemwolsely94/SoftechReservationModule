/**
 * PicTable — the PIC list (doc 33 §6): one row per PIC, server-side sort and paging.
 * Columns that do not exist for the user (GP) are simply absent from the rows; call
 * columns show «—» when the server returns no value.
 */
import { useState } from 'react'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import { fmt, fmtDate, fmtDateTime, fmtDuration } from './KpiCards'

export const PAGE_SIZE = 50
const getKey = r => r.pic
const SORTABLE = { name: 'name', net: 'net', visits: 'visits', last_purchase: 'last_purchase', days_since_last: 'days_since_last' }
const BUCKET = { m1: 'شهري', m2: 'كل شهرين', m3: 'كل 3 شهور', m4_6: '4–6 شهور', m7_12: '7–12 شهر', y1plus: 'سنوي+', '': '—' }
const SEGMENT = { vip: 'VIP', loyal: 'مخلص', regular: 'عادي', at_risk: 'في خطر', dormant: 'نائم', new: 'جديد', churned: 'مفقود' }

export default function PicTable({ data, order, onOrder, page, onPage, branchName, onExclude }) {
  const [open, setOpen] = useState(null)           // the PIC whose inline «استبعاد» reason field is open
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const submit = async (pic) => {
    setBusy(true); setErr('')
    try { await onExclude(pic, reason.trim()); setOpen(null); setReason('') }
    catch (e) { setErr(e?.response?.data?.detail || 'تعذّر الاستبعاد') }
    finally { setBusy(false) }
  }
  const rows = data?.rows || []
  const count = data?.count || 0
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  const hasGp = rows.some(r => 'gp' in r)
  const kb = useGridKeyboard({ rows, getKey })

  const sortBy = (key) => {
    const k = SORTABLE[key]
    if (!k) return
    onOrder(order === `-${k}` ? k : `-${k}`)
  }
  const Th = ({ k, children, title }) => {
    const sk = SORTABLE[k]
    const on = sk && order.replace('-', '') === sk
    return (
      <th title={title} className={`px-2 py-2 whitespace-nowrap ${sk ? 'cursor-pointer select-none hover:text-brand-700' : ''}`}
          onClick={() => sortBy(k)}>
        {children}{on ? (order.startsWith('-') ? ' ▼' : ' ▲') : ''}
      </th>
    )
  }
  const c = 'px-2 py-1.5 tabular-nums whitespace-nowrap'

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="pic-analytics-pics-grid">
      <div {...kb.containerProps} className={`overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <Th k="name">العميل</Th><th className="px-2 py-2">آخر فرع</th><th className="px-2 py-2" title="تصنيف العميل حسب نشاطه (على كل الفروع)">الشريحة</th>
              <Th k="net">صافي</Th>{hasGp && <th className="px-2 py-2">الربح</th>}
              <Th k="visits">زيارات</Th><th className="px-2 py-2">فواتير</th><th className="px-2 py-2">أصناف</th>
              <th className="px-2 py-2" title="صافي المشتريات ÷ الزيارات">سلة</th><th className="px-2 py-2" title="عدد الفئات المختلفة اللي اشتراها">الفئات</th><th className="px-2 py-2" title="عدد القنوات اللي اشترى منها">القنوات</th>
              <th className="px-2 py-2">أول شراء</th><Th k="last_purchase">آخر شراء</Th><Th k="days_since_last" title="الأيام من آخر شراء لحد نهاية الفترة">أيام منذ آخر</Th>
              <th className="px-2 py-2" title="أ: شهور الشراء من آخر 12 · ب: أطول تتابع شهري · ج: دورة الشراء (متوسط الأيام بين زياراته، مجمّع في فئات)">أ/ب/ج</th><th className="px-2 py-2" title="فات على آخر زيارة أكتر من معامل التأخر × دورته المعتادة (محتاج زيارتين على الأقل)">متأخر</th>
              <th className="px-2 py-2" title="عدد مكالماته الواردة في الفترة">وارد</th><th className="px-2 py-2" title="عدد المكالمات الصادرة له في الفترة">صادر</th><th className="px-2 py-2" title="واردة منه لم يرد عليها أحد">فائتة</th>
              <th className="px-2 py-2" title="تاريخ ووقت آخر مكالمة في الفترة">آخر مكالمة</th><th className="px-2 py-2">أيام بين المكالمات</th>
              <th className="px-2 py-2">مدة الحديث</th><th className="px-2 py-2">مكالمة ← شراء</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.pic} {...rp} className={`border-t border-gray-100 hover:bg-gray-50 ${rp.className}`}>
                  <td className="px-2 py-1.5 min-w-[10rem]">
                    <div className="font-medium text-gray-800">{r.name || '—'}</div>
                    <div className="text-gray-400 tabular-nums">{r.pic}{r.phone ? ` · ${r.phone}` : ''}</div>
                    {onExclude && open !== r.pic && (
                      <button title="يخرج العميل من كل الأرقام والترتيب (مبيعاته في سطر «عملاء مستبعدون»)؛ ممكن استرجاعه" className="text-xs text-gray-400 hover:text-red-600 hover:underline"
                              onClick={() => { setOpen(r.pic); setReason(''); setErr('') }}>استبعاد</button>
                    )}
                    {onExclude && open === r.pic && (
                      <div className="flex items-center gap-1 mt-1">
                        <input className="input-field text-xs py-1 w-44" autoFocus maxLength={255} value={reason}
                               placeholder="سبب الاستبعاد (مطلوب)"
                               onChange={e => setReason(e.target.value)}
                               onKeyDown={e => { e.stopPropagation(); if (e.key === 'Enter' && reason.trim()) submit(r.pic); if (e.key === 'Escape') setOpen(null) }} />
                        <button className="btn-secondary text-xs py-1" disabled={busy || !reason.trim()} onClick={() => submit(r.pic)}>تأكيد</button>
                        <button className="text-xs text-gray-400 hover:underline" onClick={() => setOpen(null)}>إلغاء</button>
                      </div>
                    )}
                    {onExclude && open === r.pic && err && <div className="text-xs text-red-600">{err}</div>}
                  </td>
                  <td className={c}>{r.last_branch != null ? branchName(r.last_branch) : '—'}</td>
                  <td className={c}>{SEGMENT[r.segment] || r.segment || '—'}</td>
                  <td className={c}>{fmt(r.net)}</td>
                  {hasGp && <td className={c}>{fmt(r.gp)}</td>}
                  <td className={c}>{fmt(r.visits)}</td><td className={c}>{fmt(r.invoices)}</td>
                  <td className={c}>{fmt(r.units)}</td><td className={c}>{fmt(r.basket_net, 2)}</td>
                  <td className={c}>{(r.categories || []).length}</td><td className={c}>{(r.channels || []).length}</td>
                  <td className={c}>{fmtDate(r.first_purchase)}</td><td className={c}>{fmtDate(r.last_purchase)}</td>
                  <td className={c}>{fmt(r.days_since_last)}</td>
                  <td className={c}>{r.months_a ?? '—'} / {r.streak_b ?? '—'} / {BUCKET[r.cycle_bucket] || '—'}</td>
                  <td className={c}>{r.overdue ? <span className="text-red-600 font-bold">متأخر</span> : '—'}</td>
                  <td className={c}>{r.calls_in ?? '—'}</td><td className={c}>{r.calls_out ?? '—'}</td>
                  <td className={c}>{r.missed ?? '—'}</td><td className={c}>{fmtDateTime(r.last_call)}</td>
                  <td className={c}>{fmt(r.avg_days_between_calls, 1)}</td><td className={c}>{fmtDuration(r.talk_time)}</td>
                  <td className={c}>{r.call_to_purchase ?? '—'}</td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={24} className="px-3 py-6 text-center text-gray-400">لا بيانات</td></tr>
            )}
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
