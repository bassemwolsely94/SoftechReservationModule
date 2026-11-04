/**
 * MissedSalesPage — «مبيعات فائتة» (Project 3).
 *
 * Items a KNOWN customer had on our POS cart but did not buy. Suggestions only: «تأكيد كحجز»
 * opens the normal new-reservation form prefilled (the server confirms the suggestion when the
 * reservation is saved); «رفض» needs a reason. Branch staff see their branch; call center and
 * management see all. Server decides everything — this page only shows and sends.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { missedSalesApi } from '../api/client'
import SortTh from '../components/SortTh'
import useServerSort from '../hooks/useServerSort'
import useHelpTab from '../help/useHelpTab'

const STATUS_TABS = [
  { key: 'new',       label: 'جديدة' },
  { key: 'confirmed', label: 'تم تأكيدها' },
  { key: 'rejected',  label: 'مرفوضة' },
  { key: 'expired',   label: 'انتهت' },
]
const REASONS = [
  { value: 'not_wanted',       label: 'العميل لا يريده' },
  { value: 'price_check',      label: 'سؤال عن السعر فقط' },
  { value: 'wrong_item',       label: 'صنف خطأ / تصحيح كاشير' },
  { value: 'bought_elsewhere', label: 'اشتراه من مكان آخر' },
  { value: 'other',            label: 'سبب آخر' },
]
const SORTABLE = ['seen_at', 'value', 'qty', 'item_name', 'customer__name', 'branch__name', 'decided_at']

const money = v => Number(v || 0).toLocaleString('ar-EG', { maximumFractionDigits: 2 })
const when = v => (v ? format(parseISO(v), 'dd/MM HH:mm') : '—')

function RejectRow({ row, onDone }) {
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function submit() {
    setBusy(true); setErr('')
    try {
      await missedSalesApi.reject(row.id, reason, note)
      onDone()
    } catch (e) {
      const d = e?.response?.data || {}
      setErr(d.detail || d.reason || d.note || 'تعذر الرفض')
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2 pt-2">
      <select data-tour="missed-sales-reject-reason" value={reason} onChange={e => setReason(e.target.value)}
              className="input-field text-sm py-1 w-auto">
        <option value="">— سبب الرفض —</option>
        {REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
      </select>
      <input value={note} onChange={e => setNote(e.target.value)} maxLength={255}
             placeholder={reason === 'other' ? 'اكتب السبب (مطلوب)' : 'ملاحظة (اختياري)'}
             className="input-field text-sm py-1 flex-1 min-w-[10rem]" />
      <button type="button" onClick={submit} disabled={busy || !reason || (reason === 'other' && !note.trim())}
              className="btn-secondary text-sm py-1 disabled:opacity-50">تأكيد الرفض</button>
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  )
}

export default function MissedSalesPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [status, setStatus] = useState('new')
  const [ordering, setOrdering] = useState('-seen_at')
  const [page, setPage] = useState(1)
  const [rejecting, setRejecting] = useState(null)
  useHelpTab(status)
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) },
                                        { allowed: SORTABLE, defaultOrdering: '-seen_at' })

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['missed-sales', status, ordering, page],
    queryFn: () => missedSalesApi.list({ status, ordering, page }).then(r => r.data),
    keepPreviousData: true,
  })
  const rows = data?.results || []
  const disabled = error?.response?.status === 503

  function afterReject() {
    setRejecting(null)
    qc.invalidateQueries({ queryKey: ['missed-sales'] })
  }

  return (
    <div className="p-4 max-w-6xl mx-auto space-y-4" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">مبيعات فائتة</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            أصناف اختارها عميل معروف على الكاشير ولم يشترها. أكّد الطلب الحقيقي كحجز، أو ارفضه مع السبب.
          </p>
        </div>
        <button data-tour="missed-sales-refresh" type="button" onClick={() => refetch()} disabled={isFetching}
                className="btn-secondary text-sm">{isFetching ? '⏳' : '↻'} تحديث</button>
      </div>

      <div data-tour="missed-sales-status" className="flex flex-wrap gap-2">
        {STATUS_TABS.map(t => (
          <button key={t.key} type="button" onClick={() => { setStatus(t.key); setPage(1); setRejecting(null) }}
                  className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                    status === t.key
                      ? 'bg-navy-600 text-white border-navy-600'
                      : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {disabled && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-6 text-center text-gray-500">
          الميزة غير مفعّلة بعد.
        </div>
      )}
      {isError && !disabled && (
        <div className="text-center py-8 text-red-600">
          تعذر التحميل — <button type="button" onClick={() => refetch()} className="underline">إعادة المحاولة</button>
        </div>
      )}
      {isLoading && <div className="text-center py-8 text-gray-400">جاري التحميل…</div>}

      {!isLoading && !isError && (
        <div data-tour="missed-sales-table" className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-300 text-right">
              <tr>
                <SortTh className="px-3 py-2" {...headerProps('seen_at', 'date')}>الوقت</SortTh>
                <SortTh className="px-3 py-2" {...headerProps('customer__name')}>العميل</SortTh>
                <SortTh className="px-3 py-2" {...headerProps('item_name')}>الصنف</SortTh>
                <SortTh className="px-3 py-2" {...headerProps('qty', 'number')}>الكمية</SortTh>
                <SortTh className="px-3 py-2" {...headerProps('value', 'number')}>القيمة</SortTh>
                <SortTh className="px-3 py-2" {...headerProps('branch__name')}>الفرع</SortTh>
                <th className="px-3 py-2">اشترى في نفس السلة</th>
                <th className="px-3 py-2">{status === 'new' ? 'الإجراء' : 'القرار'}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-gray-400">لا توجد اقتراحات هنا</td></tr>
              )}
              {rows.map(r => (
                <tr key={r.id} className="border-t border-gray-100 dark:border-gray-800 align-top">
                  <td className="px-3 py-2 whitespace-nowrap">{when(r.seen_at)}
                    {r.selected_by_name && <div className="text-xs text-gray-400">{r.selected_by_name}</div>}</td>
                  <td className="px-3 py-2">
                    <div className="font-medium text-gray-900 dark:text-gray-100">{r.customer_name}</div>
                    <div className="text-xs text-gray-400 ltr text-right">{r.customer_phone} · {r.customer_pic}</div>
                  </td>
                  <td className="px-3 py-2">{r.item_name}<div className="text-xs text-gray-400">{r.item_code}</div></td>
                  <td className="px-3 py-2">{Number(r.qty)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{money(r.value)}</td>
                  <td className="px-3 py-2">{r.branch_name}</td>
                  <td className="px-3 py-2 text-xs text-gray-500 max-w-[14rem]">
                    {r.bought_in_cart?.length ? r.bought_in_cart.join('، ') : '—'}
                  </td>
                  <td className="px-3 py-2 min-w-[12rem]">
                    {r.status === 'new' ? (
                      <>
                        <div className="flex gap-2">
                          <button data-tour="missed-sales-confirm" type="button"
                                  onClick={() => navigate(`/reservations/new?missed_sale=${r.id}`)}
                                  className="btn-primary text-sm py-1">تأكيد كحجز</button>
                          <button data-tour="missed-sales-reject" type="button"
                                  onClick={() => setRejecting(rejecting === r.id ? null : r.id)}
                                  className="btn-secondary text-sm py-1">رفض</button>
                        </div>
                        {rejecting === r.id && <RejectRow row={r} onDone={afterReject} />}
                      </>
                    ) : (
                      <div className="text-xs text-gray-500 space-y-0.5">
                        <div>{r.status_label}{r.reject_reason_label ? ` — ${r.reject_reason_label}` : ''}</div>
                        {r.reject_note && <div>{r.reject_note}</div>}
                        {r.decided_by_name && <div>{r.decided_by_name} · {when(r.decided_at)}</div>}
                        {r.reservation && (
                          <button type="button" onClick={() => navigate(`/reservations/${r.reservation}`)}
                                  className="underline text-brand-700">الحجز #{r.reservation}</button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(data?.next || data?.previous) && (
        <div className="flex justify-center gap-3 text-sm">
          <button type="button" disabled={!data?.previous} onClick={() => setPage(p => p - 1)} className="btn-secondary disabled:opacity-40">السابق</button>
          <span className="py-1.5 text-gray-500">صفحة {page}</span>
          <button type="button" disabled={!data?.next} onClick={() => setPage(p => p + 1)} className="btn-secondary disabled:opacity-40">التالي</button>
        </div>
      )}
    </div>
  )
}
