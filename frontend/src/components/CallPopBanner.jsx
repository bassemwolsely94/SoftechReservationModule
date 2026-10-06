/**
 * CallPopBanner — POS 3.0 Wave 7 (omnichannel screen-pop).
 *
 * Read-only surfacing of an EXISTING module (apps/pbx) inside the POS transaction: when there is a
 * live INBOUND call — preferring one ringing at the current user's own extension — it pops the caller
 * and any matched customer, with one click to load that customer into the order (reusing the normal
 * customer-set flow). It only READS `/pbx/live/` + `/pbx/my-extension/` and loads a customer via the
 * existing customersApi; it never places, answers, or ends a call and never sends anything outbound.
 *
 * Props: { onLoadCustomer(customerObj) } — wired by the POS to its setCustomer.
 */
import { useEffect, useState, useCallback } from 'react'
import api, { customersApi } from '../api/client'
import { Icon, Badge } from '../pos/design'

const ACTIVE_STATES = new Set(['ringing', 'answered', 'queued', 'on_hold', 'transferred'])

export default function CallPopBanner({ onLoadCustomer }) {
  const [myExt, setMyExt] = useState('')
  const [sessions, setSessions] = useState([])
  const [dismissed, setDismissed] = useState(() => new Set())
  const [loading, setLoading] = useState(false)

  // my extension (once) — used to prefer the call ringing at THIS terminal
  useEffect(() => {
    let alive = true
    api.get('/pbx/my-extension/')
      .then(({ data }) => { if (alive) setMyExt(String(data.extension || '')) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // poll live sessions (lightweight; the PBX board uses the same endpoint)
  useEffect(() => {
    let alive = true
    const poll = () => api.get('/pbx/live/')
      .then(({ data }) => { if (alive) setSessions(Array.isArray(data) ? data : []) })
      .catch(() => {})
    poll()
    const t = setInterval(poll, 6000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const inbound = sessions.filter(s =>
    s.direction === 'inbound' && ACTIVE_STATES.has(s.state) && !dismissed.has(s.id))
  const mine = myExt ? inbound.filter(s => String(s.destination_ext) === myExt) : []
  const call = (mine.length ? mine : inbound)[0]

  const loadCustomer = useCallback(async () => {
    if (!call) return
    setLoading(true)
    try {
      if (call.customer) {
        const { data } = await customersApi.get(call.customer)
        onLoadCustomer?.(data)
      } else if (call.caller_number) {
        const { data } = await customersApi.recognize(call.caller_number)
        const hit = (data?.results || data || [])[0]
        if (hit) onLoadCustomer?.(hit)
      }
    } catch { /* leave the banner; the user can retry or search manually */ }
    finally { setLoading(false) }
  }, [call, onLoadCustomer])

  if (!call) return null
  const who = call.caller_name || call.customer_name || call.caller_number || 'مكالمة واردة'
  const canLoad = !!(call.customer || call.caller_number)

  return (
    <div dir="rtl" className="flex items-center gap-2 px-3 py-1.5 bg-sky-50 border-b border-sky-200 text-sm">
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-sky-500" />
      </span>
      <Icon name="phone" size={16} className="text-sky-700" />
      <span className="font-semibold text-sky-900">مكالمة واردة:</span>
      <span className="text-sky-900">{who}</span>
      {call.caller_number && who !== call.caller_number &&
        <span className="text-xs text-sky-600" dir="ltr">{call.caller_number}</span>}
      {call.customer_name
        ? <Badge tone="ok" icon="usercheck" label={`عميل: ${call.customer_name}`} size="xs" />
        : <Badge tone="neutral" label="عميل غير معروف" size="xs" />}
      <span className="text-xs text-sky-500">{call.state_display || call.state}</span>
      <div className="mr-auto flex items-center gap-1.5">
        {canLoad && (
          <button onClick={loadCustomer} disabled={loading}
                  className="px-2.5 py-1 rounded bg-sky-600 text-white text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name="usercheck" size={13} /> {loading ? 'جارٍ التحميل…' : (call.customer ? 'تحميل العميل' : 'بحث بالرقم')}
          </button>
        )}
        <button onClick={() => setDismissed(d => new Set(d).add(call.id))}
                title="إخفاء" className="text-sky-400 hover:text-sky-700"><Icon name="x" size={15} /></button>
      </div>
    </div>
  )
}
