/**
 * MobileNotificationsPage.jsx — notifications inbox (route: /m/notifications).
 *
 * The phone alerts hub. Lists the user's bell notifications, tap to mark read
 * (and follow a linked record when present), plus "mark all read".
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { notificationsApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { enablePush, disablePush, pushStatus, pushSupported } from '../../push'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

function ago(d) {
  try {
    const s = formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })
    return s.replace(/[٠-٩]/g, x => String.fromCharCode(x.charCodeAt(0) - 0x660))
  } catch { return '' }
}

// Best-effort deep link from a notification to its record (mobile route).
function linkFor(n) {
  if (n.reservation) return `/m/reservations/${n.reservation}`
  if (n.link && n.link.startsWith('/m/')) return n.link
  return null
}

// Browser-push opt-in banner. iOS only delivers Web Push to an installed PWA
// (Safari 16.4+), so a plain-tab subscribe may fail there — we surface that.
function PushToggle() {
  const [status, setStatus] = useState('off')  // 'unsupported' | 'denied' | 'on' | 'off'
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { pushStatus().then(setStatus) }, [])

  if (!pushSupported() || status === 'unsupported') return null

  async function turnOn() {
    setBusy(true); setMsg('')
    const res = await enablePush()
    setBusy(false)
    if (res.ok) { setStatus('on'); return }
    if (res.reason === 'denied') {
      setStatus('denied')
      setMsg('تم رفض إذن الإشعارات — فعّله من إعدادات المتصفح')
    } else if (res.reason === 'disabled') {
      setMsg('إشعارات المتصفح غير مُفعّلة على الخادم')
    } else {
      setMsg('تعذّر تفعيل إشعارات المتصفح على هذا الجهاز')
    }
  }

  async function turnOff() {
    setBusy(true)
    await disablePush()
    setBusy(false)
    setStatus('off')
  }

  const isOn = status === 'on'
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-sm font-bold text-gray-900">🔔 إشعارات المتصفح</div>
        <div className="text-[11px] text-gray-500 mt-0.5 leading-snug">
          {status === 'denied'
            ? 'الإذن مرفوض — فعّله من إعدادات المتصفح'
            : 'استقبل التنبيهات حتى عند إغلاق التطبيق'}
          {msg && <span className="block text-red-500 mt-0.5">{msg}</span>}
        </div>
      </div>
      <button
        onClick={isOn ? turnOff : turnOn}
        disabled={busy || status === 'denied'}
        className={`shrink-0 text-xs font-medium rounded-lg px-3 py-1.5 disabled:opacity-50 ${
          isOn ? 'bg-gray-100 text-gray-600' : 'bg-brand-600 text-white'
        }`}
      >
        {busy ? '…' : isOn ? 'إيقاف' : 'تفعيل'}
      </button>
    </div>
  )
}

export default function MobileNotificationsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-notifications'],
    queryFn: () => notificationsApi.list({ limit: 50 }).then(r => r.data),
    refetchInterval: 60_000,
  })

  const rows = Array.isArray(data) ? data : (data?.results || [])

  async function open(n) {
    if (!n.is_read) {
      try { await notificationsApi.markRead(n.id) } catch { /* ignore */ }
      qc.invalidateQueries({ queryKey: ['m-notifications'] })
      qc.invalidateQueries({ queryKey: ['m-notif-unread'] })
    }
    const to = linkFor(n)
    if (to) navigate(to)
  }

  async function markAll() {
    await notificationsApi.markAllRead()
    qc.invalidateQueries({ queryKey: ['m-notifications'] })
    qc.invalidateQueries({ queryKey: ['m-notif-unread'] })
  }

  const unread = rows.filter(n => !n.is_read).length

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-bold text-gray-900">الإشعارات</h1>
        {unread > 0 && (
          <button onClick={markAll} className="text-xs text-brand-600 font-medium">
            تعليم الكل كمقروء
          </button>
        )}
      </div>

      <PushToggle />

      {isLoading ? (
        <MobileLoading />
      ) : isError ? (
        <MobileError text="تعذّر تحميل الإشعارات" onRetry={refetch} />
      ) : rows.length === 0 ? (
        <MobileEmpty icon="🔔" text="لا توجد إشعارات" />
      ) : (
        <div className="space-y-2">
          {rows.map(n => (
            <button
              key={n.id}
              onClick={() => open(n)}
              className={`w-full text-right rounded-2xl border p-4 transition-colors active:bg-gray-50 ${
                n.is_read ? 'bg-white border-gray-200' : 'bg-brand-50/60 border-brand-200'
              }`}
            >
              <div className="flex items-start gap-2">
                {!n.is_read && <span className="w-2 h-2 rounded-full bg-brand-500 mt-1.5 shrink-0" />}
                <div className="min-w-0 flex-1">
                  <div className={`text-sm leading-snug ${n.is_read ? 'text-gray-700' : 'font-bold text-gray-900'}`}>{n.title}</div>
                  {n.body && <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{n.body}</div>}
                  <div className="text-[11px] text-gray-400 mt-1">{ago(n.created_at)}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
