/**
 * CounselCardPublicPage — /c/:token, the customer's private counselling card (no login).
 * Shows only pharmacist-approved text; withdrawn sheets show a notice instead of text.
 */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import GuidanceBlock from '../counselling/GuidanceBlock'

export default function CounselCardPublicPage() {
  const { token } = useParams()
  const [optedOut, setOptedOut] = useState(false)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['counsel-card', token],
    queryFn: async () => {
      const r = await fetch(`/api/public/counsel/${encodeURIComponent(token)}/`)
      if (!r.ok) throw new Error(String(r.status))
      return r.json()
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  const optOut = async () => {
    const r = await fetch(`/api/public/counsel/${encodeURIComponent(token)}/opt-out/`, { method: 'POST' })
    if (r.ok) setOptedOut(true)
  }

  return (
    <div dir="rtl" className="min-h-screen bg-gray-50 px-4 py-6">
      <div className="max-w-lg mx-auto space-y-4">
        <div className="text-center">
          <div className="text-lg font-bold" style={{ color: '#022871' }}>صيدليات الرزيقي</div>
          <div className="text-sm text-gray-500">إرشادات استخدام مشترياتك</div>
        </div>
        {isLoading && <div className="text-center text-gray-400 py-10">جارٍ التحميل…</div>}
        {isError && <div className="rounded-xl bg-white border p-6 text-center text-gray-600">الرابط غير صالح أو منتهي الصلاحية</div>}
        {data && (
          <>
            {data.first_name && <div className="text-gray-800">مرحباً {data.first_name}،</div>}
            {data.items.map((it, i) => (
              <div key={i} className="rounded-xl bg-white border p-4 space-y-2">
                <div className="font-bold text-gray-900">{it.name}</div>
                {it.withdrawn
                  ? <div className="text-sm text-amber-800 bg-amber-50 rounded-lg p-2">تم سحب هذه الإرشادات — راجع الصيدلي</div>
                  : <>
                      {it.updated && <div className="text-xs text-sky-800 bg-sky-50 rounded px-2 py-1 w-fit">تم تحديث هذه الإرشادات</div>}
                      <GuidanceBlock content={it.content} />
                    </>}
              </div>
            ))}
            <div className="text-xs text-gray-500 leading-relaxed">
              هذه الإرشادات عامة؛ اتبع تعليمات طبيبك أو الصيدلي.
              {data.branch_name && <> للاستفسار: {data.branch_name}{data.branch_phone && <> — <a href={`tel:${data.branch_phone}`} className="underline" dir="ltr">{data.branch_phone}</a></>}</>}
            </div>
            <div className="text-center">
              {optedOut
                ? <span className="text-xs text-gray-500">تم إيقاف رسائل الإرشادات</span>
                : <button type="button" onClick={optOut} className="text-xs text-gray-400 underline">إيقاف رسائل الإرشادات</button>}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
