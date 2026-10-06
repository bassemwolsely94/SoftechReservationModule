/**
 * PbxLivePage.jsx
 *
 * Real-time PBX dashboard for call-center agents.
 *  - Top row: live active calls (ringing / in-progress / queued)
 *  - Bottom: recent call log (completed sessions)
 *  - WebSocket /ws/pbx/agent/?token=<jwt> pushes incoming_call / call_ended events
 *
 * Customer context card appears on incoming call:
 *   name, phone, segment, last purchases, open vouchers, open cases, loyalty balance
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { pbxApi } from '../api/client'

// ── helpers ───────────────────────────────────────────────────────────────────
const fmtDuration = (seconds) => {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

const fmtDt = (dt) => {
  if (!dt) return '—'
  return new Date(dt).toLocaleString('ar-EG', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const STATE_META = {
  ringing:   { label: 'رنين',      color: 'bg-yellow-100 text-yellow-800', pulse: true },
  answered:  { label: 'متصل',      color: 'bg-green-100 text-green-800',   pulse: true },
  completed: { label: 'مكتمل',     color: 'bg-gray-100 text-gray-600',     pulse: false },
  abandoned: { label: 'مهجور',     color: 'bg-red-100 text-red-700',       pulse: false },
  no_answer: { label: 'لا رد',     color: 'bg-orange-100 text-orange-700', pulse: false },
  busy:      { label: 'مشغول',     color: 'bg-pink-100 text-pink-700',     pulse: false },
}

const StateBadge = ({ state }) => {
  const m = STATE_META[state] || { label: state, color: 'bg-gray-100 text-gray-600', pulse: false }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>
      {m.pulse && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
      {m.label}
    </span>
  )
}


// ── Customer Context Card ─────────────────────────────────────────────────────
function CustomerCard({ customer, onClose }) {
  if (!customer) return null
  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-2xl border-l border-gray-200 z-50 flex flex-col overflow-hidden" dir="rtl">
      <div className="flex items-center justify-between px-4 py-3 bg-green-600 text-white">
        <div>
          <p className="font-bold text-lg">{customer.name || 'عميل غير معروف'}</p>
          <p className="text-green-100 text-sm">{customer.phone}</p>
        </div>
        <button onClick={onClose} className="text-white hover:text-green-200 text-xl font-bold">×</button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Segment & Loyalty */}
        <div className="flex gap-2">
          {customer.segment && (
            <span className="px-2 py-1 bg-blue-50 text-blue-700 rounded text-xs">{customer.segment}</span>
          )}
          {customer.loyalty && (
            <span className="px-2 py-1 bg-purple-50 text-purple-700 rounded text-xs">
              {customer.loyalty.tier} — {(customer.loyalty.points || 0).toLocaleString()} نقطة
              {customer.loyalty.supplemental > 0 && (
                <span className="text-blue-500"> +{customer.loyalty.supplemental}</span>
              )}
            </span>
          )}
        </div>

        {/* Last Purchases */}
        {customer.last_purchases?.length > 0 && (
          <section>
            <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">آخر المشتريات</h4>
            <div className="space-y-1">
              {customer.last_purchases.map((p, i) => (
                <div key={i} className="flex justify-between text-sm bg-gray-50 rounded px-2 py-1">
                  <span className="text-gray-500 text-xs">{p.invoice_date}</span>
                  <span className="font-medium">{Number(p.total_amount).toLocaleString()} ج.م</span>
                  <span className="text-gray-500 text-xs">{p.branch__name_ar || '—'}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Open Vouchers */}
        {customer.open_vouchers?.length > 0 && (
          <section>
            <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">قسائم نشطة</h4>
            <div className="space-y-1">
              {customer.open_vouchers.map((v, i) => (
                <div key={i} className="flex justify-between text-sm bg-green-50 rounded px-2 py-1">
                  <span className="font-mono text-xs text-gray-600">{v.voucher_number}</span>
                  <span className="font-semibold text-green-700">{Number(v.balance).toLocaleString()} ج.م</span>
                  <span className="text-gray-400 text-xs">{v.expiry_date}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Open Cases */}
        {customer.open_cases?.length > 0 && (
          <section>
            <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">حالات مفتوحة</h4>
            <div className="space-y-1">
              {customer.open_cases.map((c) => (
                <div key={c.id} className="text-sm bg-yellow-50 rounded px-2 py-1">
                  <p className="font-medium text-gray-800">{c.title}</p>
                  <p className="text-xs text-gray-500">{c.status} · {c.priority}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        {!customer.last_purchases?.length && !customer.open_vouchers?.length && !customer.open_cases?.length && (
          <p className="text-center text-gray-400 py-8">لا توجد بيانات سابقة</p>
        )}
      </div>
    </div>
  )
}


// ── Live Session Card ─────────────────────────────────────────────────────────
function LiveSessionCard({ session, onClick }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const start = session.started_at ? new Date(session.started_at) : new Date()
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [session.started_at])

  return (
    <button
      onClick={() => onClick(session)}
      className="w-full text-right bg-white border border-gray-200 rounded-lg p-3 hover:border-green-400 hover:shadow-md transition-all"
      dir="rtl"
    >
      <div className="flex items-center justify-between mb-1">
        <StateBadge state={session.state} />
        <span className="text-sm font-mono text-gray-500">{fmtDuration(elapsed)}</span>
      </div>
      <p className="font-semibold text-gray-800 text-sm">
        {session.customer_name || session.caller_number || 'رقم مجهول'}
      </p>
      <p className="text-xs text-gray-500">{session.caller_number}</p>
      <p className="text-xs text-gray-400 mt-1">
        {session.queue_name || '—'} · {session.agent_name || 'غير موزَّع'}
      </p>
    </button>
  )
}


// ── Session History Row ───────────────────────────────────────────────────────
function SessionRow({ s }) {
  return (
    <tr className="hover:bg-gray-50 text-sm" dir="rtl">
      <td className="px-3 py-2 font-mono text-xs text-gray-500">{s.unique_id?.slice(-6)}</td>
      <td className="px-3 py-2">{s.caller_number || '—'}</td>
      <td className="px-3 py-2 text-gray-700">{s.customer_name || '—'}</td>
      <td className="px-3 py-2">{s.queue_name || '—'}</td>
      <td className="px-3 py-2">{s.agent_name || '—'}</td>
      <td className="px-3 py-2"><StateBadge state={s.state} /></td>
      <td className="px-3 py-2 text-gray-500">{fmtDuration(s.wait_seconds)}</td>
      <td className="px-3 py-2 text-gray-500">{fmtDuration(s.talk_seconds)}</td>
      <td className="px-3 py-2 text-gray-400 text-xs">{fmtDt(s.started_at)}</td>
    </tr>
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────
export default function PbxLivePage() {
  const [activeSessions, setActiveSessions] = useState([])
  const [wsStatus, setWsStatus] = useState('connecting')
  const [customerCard, setCustomerCard] = useState(null)  // { customer, session_id }
  const wsRef = useRef(null)
  const qc = useQueryClient()

  // Recent sessions (last 50)
  const { data: historyData } = useQuery({
    queryKey: ['pbx-sessions'],
    queryFn: () => pbxApi.sessions({ limit: 50 }).then(r => r.data),
    refetchInterval: 30_000,
  })

  // Initial live sessions
  const { data: liveData } = useQuery({
    queryKey: ['pbx-live'],
    queryFn: () => pbxApi.live().then(r => r.data),
    refetchInterval: 15_000,
  })

  useEffect(() => {
    // Normalize API sessions: map `id` → `session_id` so they match WS-pushed shape
    const raw = liveData?.sessions || liveData || []
    if (Array.isArray(raw)) {
      setActiveSessions(raw.map(s => ({ ...s, session_id: s.session_id ?? s.id })))
    }
  }, [liveData])

  // WebSocket
  useEffect(() => {
    const token = localStorage.getItem('access_token') || ''
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host  = window.location.host
    const ws = new WebSocket(`${proto}://${host}/ws/pbx/agent/?token=${token}`)
    wsRef.current = ws

    ws.onopen  = () => setWsStatus('connected')
    ws.onclose = () => setWsStatus('disconnected')
    ws.onerror = () => setWsStatus('error')

    ws.onmessage = (evt) => {
      const data = JSON.parse(evt.data)

      if (data.type === 'incoming_call') {
        setActiveSessions(prev => {
          const exists = prev.find(s => s.session_id === data.session_id || s.id === data.session_id)
          if (exists) return prev
          return [{
            session_id: data.session_id,
            unique_id: data.unique_id,
            state: 'ringing',
            caller_number: data.caller_id,
            queue_name: data.queue,
            started_at: data.started_at,
            customer_name: data.customer?.name,
            _customer: data.customer,
          }, ...prev]
        })
        // Show customer card
        if (data.customer) {
          setCustomerCard({ customer: data.customer, session_id: data.session_id })
        }
        qc.invalidateQueries({ queryKey: ['pbx-live'] })
      }

      if (data.type === 'call_ended') {
        setActiveSessions(prev => prev.filter(s =>
          s.session_id !== data.session_id && s.id !== data.session_id
        ))
        qc.invalidateQueries({ queryKey: ['pbx-sessions'] })
        qc.invalidateQueries({ queryKey: ['pbx-live'] })
      }

      if (data.type === 'call_answered') {
        setActiveSessions(prev => prev.map(s =>
          s.session_id === data.session_id ? { ...s, state: 'answered', agent_name: data.agent } : s
        ))
      }
    }

    return () => ws.close()
  }, [])

  const handleCardSession = (session) => {
    if (session._customer) {
      setCustomerCard({ customer: session._customer, session_id: session.session_id })
    }
  }

  const sessions = historyData?.results || historyData || []

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
        <h1 className="text-xl font-bold text-gray-800">لوحة المكالمات الحية</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className={`w-2 h-2 rounded-full ${
            wsStatus === 'connected' ? 'bg-green-500' :
            wsStatus === 'connecting' ? 'bg-yellow-400 animate-pulse' : 'bg-red-500'
          }`} />
          <span className="text-gray-500">
            {wsStatus === 'connected' ? 'متصل' : wsStatus === 'connecting' ? 'جاري الاتصال...' : 'غير متصل'}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Active calls */}
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">
            مكالمات نشطة ({activeSessions.length})
          </h2>
          {activeSessions.length === 0 ? (
            <div className="bg-gray-50 rounded-lg p-8 text-center text-gray-400">
              لا توجد مكالمات نشطة حالياً
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {activeSessions.map((s) => (
                <LiveSessionCard key={s.session_id || s.unique_id} session={s} onClick={handleCardSession} />
              ))}
            </div>
          )}
        </section>

        {/* Recent history */}
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">سجل المكالمات الأخيرة</h2>
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-gray-500 text-xs uppercase">
                  <th className="px-3 py-2 text-right">ID</th>
                  <th className="px-3 py-2 text-right">رقم المتصل</th>
                  <th className="px-3 py-2 text-right">العميل</th>
                  <th className="px-3 py-2 text-right">الطابور</th>
                  <th className="px-3 py-2 text-right">الموظف</th>
                  <th className="px-3 py-2 text-right">الحالة</th>
                  <th className="px-3 py-2 text-right">انتظار</th>
                  <th className="px-3 py-2 text-right">مكالمة</th>
                  <th className="px-3 py-2 text-right">الوقت</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {sessions.map((s) => <SessionRow key={s.id} s={s} />)}
                {sessions.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-gray-400">لا توجد مكالمات مسجَّلة</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Customer context slide-in */}
      {customerCard && (
        <CustomerCard
          customer={customerCard.customer}
          onClose={() => setCustomerCard(null)}
        />
      )}
    </div>
  )
}
