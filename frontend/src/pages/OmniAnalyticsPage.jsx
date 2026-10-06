/**
 * OmniAnalyticsPage.jsx — CEP Phase 5 (doc 15)
 *
 * Cross-channel analytics: volume by channel/day, first-response time,
 * conversation→reservation conversion, status split, per-agent activity.
 * Pure SVG/CSS bars (no charting dependency in this project).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { omniApi } from '../api/client'

const CHANNEL_META = {
  whatsapp:  { icon: '💬', label: 'واتساب',    color: '#22c55e' },
  voice:     { icon: '☎️', label: 'مكالمات',   color: '#6366f1' },
  messenger: { icon: '🟦', label: 'ماسنجر',    color: '#3b82f6' },
  instagram: { icon: '📸', label: 'إنستجرام',  color: '#ec4899' },
  telegram:  { icon: '✈️', label: 'تيليجرام',  color: '#0ea5e9' },
}

const STATUS_LABEL = {
  open: 'مفتوحة', pending: 'بانتظار رد', snoozed: 'مؤجلة',
  resolved: 'محلولة', closed: 'مغلقة',
}

const fmtDuration = (s) => {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)} ث`
  if (s < 3600) return `${Math.round(s / 60)} د`
  return `${(s / 3600).toFixed(1)} س`
}

function Card({ title, children }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h2 className="font-bold text-gray-700 text-sm mb-3">{title}</h2>
      {children}
    </div>
  )
}

function DayBars({ data }) {
  const max = Math.max(1, ...data.map(d => d.total))
  return (
    <div className="flex items-end gap-1 h-32" dir="ltr">
      {data.map(d => (
        <div key={d.day} className="flex-1 flex flex-col items-center justify-end group">
          <div className="w-full bg-indigo-400 hover:bg-indigo-600 rounded-t transition-colors"
               style={{ height: `${(d.total / max) * 100}%` }}
               title={`${d.day}: ${d.total}`} />
        </div>
      ))}
    </div>
  )
}

export default function OmniAnalyticsPage() {
  const [days, setDays] = useState(30)

  const { data, isLoading, error } = useQuery({
    queryKey: ['omni-analytics', days],
    queryFn: () => omniApi.analytics({ days }).then(r => r.data),
  })

  if (error?.response?.status === 403) {
    return <p className="text-center text-gray-400 py-20" dir="rtl">🔒 لوحة المشرفين فقط</p>
  }
  if (isLoading || !data) {
    return <p className="text-center text-gray-400 py-20" dir="rtl">جاري التحميل...</p>
  }

  const channelMax = Math.max(1, ...data.by_channel.map(c => c.total))
  const conv = data.conversion

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5" dir="rtl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">📈 تحليلات التواصل</h1>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
                className="border border-gray-200 rounded px-3 py-1.5 text-sm">
          <option value={7}>آخر 7 أيام</option>
          <option value={30}>آخر 30 يوم</option>
          <option value={90}>آخر 90 يوم</option>
        </select>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-indigo-600">{conv.conversations}</p>
          <p className="text-xs text-gray-400 mt-1">محادثات</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-green-600">{conv.to_reservation}</p>
          <p className="text-xs text-gray-400 mt-1">تحوّلت لحجز</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-gray-800">{(conv.rate * 100).toFixed(1)}%</p>
          <p className="text-xs text-gray-400 mt-1">نسبة التحويل</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-gray-800">{fmtDuration(data.first_response_seconds)}</p>
          <p className="text-xs text-gray-400 mt-1">متوسط أول رد</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* By channel */}
        <Card title="الحجم حسب القناة">
          {data.by_channel.length === 0 ? (
            <p className="text-sm text-gray-400 py-4 text-center">لا توجد بيانات</p>
          ) : (
            <div className="space-y-2">
              {data.by_channel.map(c => {
                const m = CHANNEL_META[c.channel] || { icon: '💠', label: c.channel, color: '#94a3b8' }
                return (
                  <div key={c.channel} className="flex items-center gap-2">
                    <span className="w-20 text-xs text-gray-600 shrink-0">{m.icon} {m.label}</span>
                    <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden" dir="ltr">
                      <div className="h-full rounded-full flex items-center justify-end px-1.5"
                           style={{ width: `${(c.total / channelMax) * 100}%`, backgroundColor: m.color }}>
                        <span className="text-[10px] text-white font-medium">{c.total}</span>
                      </div>
                    </div>
                    <span className="text-xs text-gray-400 w-16 shrink-0">وارد {c.inbound}</span>
                  </div>
                )
              })}
            </div>
          )}
        </Card>

        {/* Status split */}
        <Card title="حالات المحادثات">
          {data.status_split.length === 0 ? (
            <p className="text-sm text-gray-400 py-4 text-center">لا توجد بيانات</p>
          ) : (
            <div className="space-y-2">
              {data.status_split.map(s => (
                <div key={s.status} className="flex items-center justify-between text-sm">
                  <span className="text-gray-600">{STATUS_LABEL[s.status] || s.status}</span>
                  <span className="font-bold text-gray-800">{s.n}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Volume by day */}
      <Card title="الحجم اليومي (وارد)">
        {data.by_day.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">لا توجد بيانات</p>
        ) : (
          <DayBars data={data.by_day} />
        )}
      </Card>

      {/* Per-agent */}
      <Card title="نشاط الموظفين (ردود صادرة)">
        {data.by_agent.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">لا توجد بيانات</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
            {data.by_agent.map(a => (
              <div key={a.actor} className="flex items-center justify-between text-sm px-2 py-1 rounded hover:bg-gray-50">
                <span className="text-gray-700 truncate">{a.agent_name}</span>
                <span className="font-bold text-indigo-600">{a.replies}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
