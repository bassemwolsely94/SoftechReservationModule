/**
 * OtpDeliveryStatus — did the voucher OTP actually reach the customer's WhatsApp? (delivery checker)
 *
 * Polls GET /vouchers/vouchers/{id}/otp-status/?otp_id= every 3 s until a final answer (delivered, read, failed,
 * not sent, no receipt) or 3 minutes. The backend reads Meta's receipts (apps/whatsapp/delivery.py); this only
 * shows them, so staff know at once to use the QR instead of waiting. Calm, inline, no modal.
 */
import { useEffect, useState } from 'react'
import { vouchersApi } from '../api/client'

const FINAL = ['delivered', 'read', 'failed', 'not_sent', 'no_receipt']
const TONE = {
  delivered: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  read: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
  not_sent: 'bg-amber-50 text-amber-800 border-amber-200',
  no_receipt: 'bg-amber-50 text-amber-800 border-amber-200',
}
const ICON = { pending: '⏳', sent: '✓', delivered: '✓✓', read: '✓✓', failed: '✕', not_sent: '!', no_receipt: '?' }
const HINT = {
  failed: 'استخدم QR أو أعد الإرسال.',
  not_sent: 'واتساب غير متاح — اعرض QR للعميل.',
  no_receipt: 'لم يصل إشعار استلام — اسأل العميل أو اعرض QR.',
}

export default function OtpDeliveryStatus({ voucherId, otpId }) {
  const [s, setS] = useState(null)
  useEffect(() => {
    if (!voucherId || !otpId) return undefined
    let alive = true, timer = null
    const started = Date.now()
    const tick = () => {
      vouchersApi.otpStatus(voucherId, otpId)
        .then(({ data }) => {
          if (!alive) return
          setS(data)
          if (!FINAL.includes(data.state) && Date.now() - started < 180000) timer = setTimeout(tick, 3000)
        })
        .catch(() => { if (alive && Date.now() - started < 180000) timer = setTimeout(tick, 5000) })
    }
    tick()
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [voucherId, otpId])

  if (!s) return null
  return (
    <div data-tour="vouchers-otp-delivery"
         className={`text-xs border rounded-lg px-2.5 py-1.5 ${TONE[s.state] || 'bg-gray-50 text-gray-600 border-gray-200'}`}>
      <span className="font-semibold">{ICON[s.state] || ''} حالة رسالة الرمز: {s.label}</span>
      {s.error && <span> — {s.error}</span>}
      {HINT[s.state] && <span className="block mt-0.5">{HINT[s.state]}</span>}
    </div>
  )
}
