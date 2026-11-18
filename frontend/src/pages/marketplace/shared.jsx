/**
 * pages/marketplace/shared.jsx — small pieces the /marketplace tabs share: the quiet status line,
 * API error text, the page-number pager and the channel list query. Display only — every rule
 * (eligibility, prices, status moves, matching) lives in apps/marketplace.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { marketplaceApi } from '../../api/client'

/** {'detail': …} (HTTP 400) → one Arabic line. A bare machine `code` is never shown to staff. */
export const errText = (e) => {
  const d = e?.response?.data
  if (!d) return 'حدث خطأ — حاول مرة أخرى.'
  if (typeof d === 'string') return 'حدث خطأ — حاول مرة أخرى.'
  if (d.detail) return d.detail
  if (d.code) return 'حدث خطأ — حاول مرة أخرى.'
  const first = Object.entries(d)[0]
  if (first) return `${first[0]}: ${Array.isArray(first[1]) ? first[1].join(' ') : String(first[1])}`
  return 'حدث خطأ — حاول مرة أخرى.'
}

export const rowsOf = (data) => (Array.isArray(data) ? data : (data?.results || []))

export const money = (v) => (v === null || v === undefined || v === '' ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))

export const qtyText = (v) => (v === null || v === undefined || v === '' ? '—' : String(Number(v)))

export const dateTime = (v) => (v ? new Date(v).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' }) : '—')

// One quiet status line instead of popups (calm UI): ok / error, fades after a few seconds.
export function useNotice() {
  const [notice, setNotice] = useState(null)
  useEffect(() => {
    if (!notice) return undefined
    const t = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(t)
  }, [notice])
  const show = { ok: (text) => setNotice({ ok: true, text }), error: (text) => setNotice({ ok: false, text }) }
  const bar = notice && (
    <div role="status" className={`rounded-lg px-3 py-2 text-sm ${notice.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>
      {notice.text}
    </div>
  )
  return [bar, show]
}

/** Prev / next for a DRF PageNumberPagination list. */
export function Pager({ page, setPage, data }) {
  if (!data || (!data.next && !data.previous)) return null
  return (
    <div className="flex items-center justify-center gap-3 py-2 text-sm text-gray-600">
      <button disabled={!data.previous} onClick={() => setPage(page - 1)}
        className="px-3 py-1 rounded border disabled:opacity-40">السابق</button>
      <span>صفحة {page} · {data.count} سجل</span>
      <button disabled={!data.next} onClick={() => setPage(page + 1)}
        className="px-3 py-1 rounded border disabled:opacity-40">التالي</button>
    </div>
  )
}

export function useChannels() {
  return useQuery({
    queryKey: ['marketplace', 'channels'],
    queryFn: () => marketplaceApi.channels().then(r => rowsOf(r.data)),
    staleTime: 60 * 1000,
  })
}

export const STATUS_STYLE = {
  received: 'bg-amber-50 text-amber-800 border-amber-200',
  accepted: 'bg-blue-50 text-blue-700 border-blue-200',
  preparing: 'bg-violet-50 text-violet-700 border-violet-200',
  ready: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  handed_over: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  delivered: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
  cancelled: 'bg-gray-100 text-gray-500 border-gray-200',
}

export const STATUS_LABEL = {
  received: 'جديد', accepted: 'مقبول', rejected: 'مرفوض', preparing: 'جاري التحضير',
  ready: 'جاهز للتسليم', handed_over: 'سُلِّم للمندوب', delivered: 'تم التوصيل', cancelled: 'ملغى',
}

export const PAY_LABEL = { platform_paid: 'مدفوع للمنصة', cash_on_delivery: 'الدفع عند الاستلام' }

export const LISTING_PROBLEM = {
  '': 'جاهز للبيع', not_approved: 'غير معتمد', blocked: 'ممنوع', restricted: 'مقيد (يحتاج مراجعة)', fridge: 'ثلاجة',
}

export const inputCls = 'border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400'
export const btnPrimary = 'px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium disabled:opacity-50'
export const btnQuiet = 'px-3 py-2 rounded-lg border text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50'
