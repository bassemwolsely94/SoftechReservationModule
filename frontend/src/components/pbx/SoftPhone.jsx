import { useEffect, useState } from 'react'
import useSoftPhone, { softPhone } from '../../hooks/useSoftPhone'

const REASONS = {
  not_configured: 'هاتف المتصفح غير مفعّل على السيرفر',
  no_extension:   'لا يوجد رقم داخلي مرتبط بحسابك',
  not_enabled:    'هاتف المتصفح غير مفعّل لرقمك الداخلي',
  no_password:    'لم تُضبط كلمة سر SIP لرقمك الداخلي',
}

function Timer({ since }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const s = Math.max(0, Math.floor((now - since) / 1000))
  return <span className="tabular-nums">{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

/**
 * Compact browser-phone bar. Renders nothing for users without browser-phone access,
 * so desk-phone agents see no change.
 */
export default function SoftPhone({ onIncoming }) {
  const s = useSoftPhone()
  const [transferTo, setTransferTo] = useState('')
  const [showTransfer, setShowTransfer] = useState(false)
  const call = s.call

  useEffect(() => {
    if (call?.direction === 'incoming' && call.status === 'ringing' && onIncoming) onIncoming(call.number)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call?.status, call?.number])

  if (!s.available) {
    return s.reason && s.reason !== 'not_configured' && s.reason !== 'no_extension'
      ? <span className="text-xs text-gray-400" title={REASONS[s.reason]}>🎧 {REASONS[s.reason] || ''}</span>
      : null
  }

  if (!call) {
    return (
      <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${
        s.registered ? 'border-green-200 text-green-700' : 'border-amber-200 text-amber-700'}`}
        title={s.error || ''}>
        <span className={`w-2 h-2 rounded-full ${s.registered ? 'bg-green-500' : 'bg-amber-400 animate-pulse'}`} />
        🎧 {s.registered ? 'هاتف المتصفح جاهز' : (s.error || 'جارٍ التسجيل…')}
      </span>
    )
  }

  const ringing = call.direction === 'incoming' && call.status === 'ringing'
  return (
    <div className={`flex items-center gap-2 flex-wrap rounded-xl px-3 py-1.5 text-sm ${
      ringing ? 'bg-green-600 text-white animate-pulse' : 'bg-gray-900 text-white'}`}>
      <span className="font-mono" dir="ltr">{call.number || '—'}</span>
      <span className="text-xs opacity-80">
        {ringing ? 'مكالمة واردة' : call.status === 'connecting' ? 'جارٍ الاتصال…'
          : call.status === 'held' ? 'انتظار' : call.startedAt ? <Timer since={call.startedAt} /> : ''}
      </span>
      {ringing && (
        <button onClick={softPhone.answer} className="bg-white text-green-700 rounded-lg px-3 py-0.5 font-bold">رد</button>
      )}
      {!ringing && call.status !== 'connecting' && (
        <>
          <button onClick={softPhone.toggleMute} className="rounded-lg px-2 py-0.5 bg-white/15 hover:bg-white/25 text-xs">
            {call.muted ? '🔈 إلغاء الكتم' : '🔇 كتم'}
          </button>
          <button onClick={softPhone.toggleHold} className="rounded-lg px-2 py-0.5 bg-white/15 hover:bg-white/25 text-xs">
            {call.status === 'held' ? '▶ استئناف' : '⏸ انتظار'}
          </button>
          {showTransfer ? (
            <span className="inline-flex gap-1">
              <input value={transferTo} onChange={e => setTransferTo(e.target.value.replace(/[^\d*#]/g, ''))}
                placeholder="رقم داخلي" className="w-20 rounded px-1 text-gray-900 text-xs" dir="ltr" autoFocus />
              <button onClick={() => { softPhone.transfer(transferTo); setShowTransfer(false) }}
                disabled={!transferTo} className="rounded-lg px-2 py-0.5 bg-white/15 text-xs disabled:opacity-50">تحويل</button>
            </span>
          ) : (
            <button onClick={() => setShowTransfer(true)} className="rounded-lg px-2 py-0.5 bg-white/15 hover:bg-white/25 text-xs">↪ تحويل</button>
          )}
        </>
      )}
      <button onClick={softPhone.hangup} className="bg-red-600 hover:bg-red-700 rounded-lg px-3 py-0.5 font-bold text-white">
        {ringing ? 'رفض' : 'إنهاء'}
      </button>
    </div>
  )
}
