/**
 * ConsentChips — one-tap contact consent (backlog P-05) on the POS customer bar and the customer page.
 *
 * Shows the customer's recorded answer per purpose (✓ yes · ✕ no · ؟ not asked) from
 * /customers/{id}/consent/. One tap records the opposite answer (not asked → yes). The backend owns the rule
 * (apps/customers/consent.py) and the permission (customers edit); this only shows and sends the tap.
 * No modal (rule 11): a failed tap shows a short inline note.
 */
import { useEffect, useState } from 'react'
import { customersApi } from '../api/client'

const LABELS = {
  refill: 'تذكيرات الصرف',
  marketing: 'العروض',
  marketing_health: 'عروض حسب الحالة',
  service: 'رسائل الخدمة',
}

export default function ConsentChips({ customerId, purposes = ['refill', 'marketing'], source = 'counter' }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    if (!customerId) { setData(null); return }
    let alive = true
    customersApi.consent(customerId)
      .then(({ data: d }) => { if (alive) setData(d.purposes) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [customerId])

  if (!data) return null

  const tap = async (purpose) => {
    const current = data[purpose]?.granted
    setBusy(purpose); setNote('')
    try {
      const { data: d } = await customersApi.recordConsent(customerId, purpose, current !== true, source)
      setData(d.purposes)
    } catch (e) {
      setNote(e?.response?.status === 403 ? 'تسجيل الموافقة يحتاج صلاحية تعديل العملاء' : 'تعذّر الحفظ')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1 text-[11px]" data-tour="customer-consent">
      <span className="text-gray-500">موافقة التواصل:</span>
      {purposes.map((p) => {
        const g = data[p]?.granted
        const tone = g === true ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
          : g === false ? 'bg-red-50 border-red-200 text-red-700' : 'bg-white border-gray-200 text-gray-500'
        return (
          <button key={p} type="button" disabled={busy === p} onClick={() => tap(p)}
                  title={`${data[p]?.reason_label || ''} — اضغط لتسجيل ${g === true ? 'الرفض' : 'الموافقة'}`}
                  className={`border rounded px-1.5 py-0.5 ${tone} disabled:opacity-50`}>
            {g === true ? '✓' : g === false ? '✕' : '؟'} {LABELS[p]}
          </button>
        )
      })}
      {note && <span className="text-red-600">{note}</span>}
    </div>
  )
}
