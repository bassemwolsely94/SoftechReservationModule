/**
 * CallPopBanner — POS 3.0 Wave 7 (omnichannel screen-pop).
 *
 * Read-only surfacing of an EXISTING module (apps/pbx) inside the POS transaction: when a live
 * INBOUND call is ringing at the current user's OWN extension, it pops the caller and EVERY customer
 * (PIC) registered with that phone — the agent picks the right one — or offers a new customer with
 * the phone prefilled. Users without an extension (branch salesmen) never see it.
 * Calls come from `/pbx/live/?fresh=1`, which returns nothing while the AMI bridge is down and drops
 * calls older than 12 h (a call whose hang-up never arrived must not stick on screen).
 * It never places, answers, or ends a call and never sends anything outbound.
 *
 * Props: { onLoadCustomer({id,name,phone,softech_pic}), onNewCustomer(phone) }.
 */
import { useEffect, useState } from 'react'
import api, { customersApi } from '../api/client'
import { Icon, Badge } from '../pos/design'

const ACTIVE_STATES = new Set(['ringing', 'answered', 'queued', 'on_hold', 'transferred'])
const pick = (c) => ({ id: c.id, name: c.name, phone: c.phone, softech_pic: c.softech_pic })

export default function CallPopBanner({ onLoadCustomer, onNewCustomer }) {
  const [myExt, setMyExt] = useState('')
  const [sessions, setSessions] = useState([])
  const [dismissed, setDismissed] = useState(() => new Set())
  const [matches, setMatches] = useState({ callId: null, rows: null })   // customers with the caller's phone

  // my extension (once) — no extension = not a call-center terminal = no screen-pop
  useEffect(() => {
    let alive = true
    api.get('/pbx/my-extension/')
      .then(({ data }) => { if (alive) setMyExt(String(data.extension || '')) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // poll live sessions only on a call-center terminal
  useEffect(() => {
    if (!myExt) return
    let alive = true
    const poll = () => api.get('/pbx/live/', { params: { fresh: 1 } })
      .then(({ data }) => { if (alive) setSessions(Array.isArray(data) ? data : []) })
      .catch(() => {})
    poll()
    const t = setInterval(poll, 6000)
    return () => { alive = false; clearInterval(t) }
  }, [myExt])

  const call = sessions.find(s =>
    s.direction === 'inbound' && ACTIVE_STATES.has(s.state) && !dismissed.has(s.id)
    && String(s.destination_ext) === myExt)

  // every customer on the caller's phone, looked up once per call
  const callId = call?.id
  const number = call?.caller_number
  useEffect(() => {
    if (!callId || !number) return
    let alive = true
    setMatches({ callId, rows: null })
    customersApi.recognize(number)
      .then(({ data }) => { if (alive) setMatches({ callId, rows: data?.matches || [] }) })
      .catch(() => { if (alive) setMatches({ callId, rows: [] }) })
    return () => { alive = false }
  }, [callId, number])

  if (!call) return null
  const rows = matches.callId === call.id ? matches.rows : null
  const who = call.caller_name || call.customer_name || call.caller_number || 'مكالمة واردة'

  return (
    <div dir="rtl" className="flex items-center gap-2 flex-wrap px-3 py-1.5 bg-sky-50 border-b border-sky-200 text-sm">
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-sky-500" />
      </span>
      <Icon name="phone" size={16} className="text-sky-700" />
      <span className="font-semibold text-sky-900">مكالمة واردة:</span>
      <span className="text-sky-900">{who}</span>
      {call.caller_number && who !== call.caller_number &&
        <span className="text-xs text-sky-600" dir="ltr">{call.caller_number}</span>}
      <span className="text-xs text-sky-500">{call.state_display || call.state}</span>

      {rows == null && call.caller_number && <span className="text-xs text-sky-500">جارٍ البحث عن العميل…</span>}
      {rows && rows.length > 0 && (
        <span className="flex items-center gap-1 flex-wrap">
          <span className="text-xs text-sky-700">{rows.length > 1 ? `${rows.length} عملاء بهذا الرقم — اختر:` : 'عميل:'}</span>
          {rows.map(c => (
            <button key={c.id} type="button" onClick={() => onLoadCustomer?.(pick(c))}
                    title="تحميل كعميل (PIC) للأمر"
                    className="px-2 py-0.5 rounded-full border border-sky-300 bg-white text-xs text-sky-900 hover:bg-sky-100 flex items-center gap-1">
              <Icon name="usercheck" size={12} />
              <span className="font-semibold">{c.name}</span>
              <span className="text-sky-500" dir="ltr">{c.softech_pic || 'بدون PIC'}</span>
            </button>
          ))}
        </span>
      )}
      {rows && rows.length === 0 && <Badge tone="neutral" label="لا يوجد عميل بهذا الرقم" size="xs" />}

      <div className="mr-auto flex items-center gap-1.5">
        {rows && call.caller_number && (
          <button type="button" onClick={() => onNewCustomer?.(call.caller_number)}
                  className="px-2.5 py-1 rounded bg-sky-600 text-white text-xs flex items-center gap-1">
            <Icon name="plus" size={13} /> عميل جديد بهذا الرقم
          </button>
        )}
        <button onClick={() => setDismissed(d => new Set(d).add(call.id))}
                title="إخفاء" className="text-sky-400 hover:text-sky-700"><Icon name="x" size={15} /></button>
      </div>
    </div>
  )
}
