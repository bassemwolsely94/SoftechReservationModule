import { useState } from 'react'
import { pbxApi } from '../../api/client'
import { softPhone } from '../../hooks/useSoftPhone'

/**
 * Click-to-dial: Asterisk rings the user's own extension, then connects to `phone`.
 * Pass only numbers the user is allowed to see (masked numbers render nothing).
 */
export default function DialButton({ phone, className = '', label = '' }) {
  const [state, setState] = useState('idle')   // idle | dialing | ok | error
  const [msg, setMsg] = useState('')
  if (!phone || phone.includes('●')) return null

  async function dial(e) {
    e.stopPropagation()
    // Browser phone registered and free → call from the page; otherwise ring the desk phone
    if (softPhone.call(phone.replace(/[^\d+]/g, ''))) {
      setState('ok'); setMsg('جارٍ الاتصال من المتصفح')
      setTimeout(() => { setState('idle'); setMsg('') }, 3000)
      return
    }
    setState('dialing')
    try {
      const r = await pbxApi.dial({ destination: phone })
      setState('ok')
      setMsg(r.data?.detail || 'سيرن هاتفك الآن')
    } catch (err) {
      setState('error')
      setMsg(err.response?.data?.detail || 'فشل بدء المكالمة')
    }
    setTimeout(() => { setState('idle'); setMsg('') }, 4000)
  }

  return (
    <button type="button" onClick={dial} disabled={state === 'dialing'}
      title={msg || 'اتصال من رقمك الداخلي'}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-colors
        ${state === 'error' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700 hover:bg-green-100'}
        disabled:opacity-60 ${className}`}>
      {state === 'dialing' ? '⏳' : state === 'ok' ? '✅' : state === 'error' ? '⚠️' : '📞'}
      {label && <span>{label}</span>}
      {msg && <span className="max-w-[12rem] truncate">{msg}</span>}
    </button>
  )
}
