/**
 * OmniWallboardPage.jsx — CEP Phase 2 (doc 15)
 *
 * Supervisor live wallboard: active calls (with listen/whisper), per-queue
 * stats today, agent states, WhatsApp load, conversation backlog.
 * Polls /api/omni/wallboard/ every 5 seconds.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { omniApi, pbxApi } from '../api/client'

const STATE_META = {
  ringing:     { label: 'يرن',        cls: 'bg-yellow-100 text-yellow-700' },
  queued:      { label: 'في الانتظار', cls: 'bg-orange-100 text-orange-700' },
  answered:    { label: 'جارية',      cls: 'bg-green-100 text-green-700' },
  on_hold:     { label: 'معلّقة',     cls: 'bg-blue-100 text-blue-700' },
  transferred: { label: 'محوَّلة',    cls: 'bg-purple-100 text-purple-700' },
}

const mmss = (s) => {
  const secs = Math.max(0, Math.floor(s || 0))
  return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
}

function Kpi({ label, value, accent = 'text-gray-800' }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
      <p className={`text-2xl font-bold ${accent}`}>{value ?? 0}</p>
      <p className="text-xs text-gray-400 mt-1">{label}</p>
    </div>
  )
}

export default function OmniWallboardPage() {
  const [spyMsg, setSpyMsg] = useState(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['omni-wallboard'],
    queryFn: () => omniApi.wallboard().then(r => r.data),
    refetchInterval: 5_000,
  })

  const spy = async (targetExt, mode) => {
    setSpyMsg(null)
    try {
      const r = await pbxApi.spy({ target_ext: targetExt, mode })
      setSpyMsg({ ok: true, text: r.data.detail })
    } catch (e) {
      setSpyMsg({ ok: false, text: e.response?.data?.detail || 'فشل تنفيذ المراقبة' })
    }
  }

  if (error?.response?.status === 403) {
    return <p className="text-center text-gray-400 py-20" dir="rtl">🔒 لوحة المشرفين فقط</p>
  }
  if (isLoading || !data) {
    return <p className="text-center text-gray-400 py-20" dir="rtl">جاري التحميل...</p>
  }

  const { live_calls, queues, today, agents, accounts, conversations } = data
  const onlineAgents = agents.filter(a => a.registered).length

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5" dir="rtl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-800">📊 لوحة المشرف الحية</h1>
        <span className="text-xs text-gray-400">تحديث كل 5 ثوانٍ</span>
      </div>

      {spyMsg && (
        <div className={`rounded-lg border px-4 py-2 text-sm flex items-center justify-between
          ${spyMsg.ok ? 'bg-green-50 border-green-200 text-green-800'
                       : 'bg-red-50 border-red-200 text-red-700'}`}>
          <span>{spyMsg.ok ? '✅' : '❌'} {spyMsg.text}</span>
          <button onClick={() => setSpyMsg(null)} className="text-gray-400">✕</button>
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Kpi label="مكالمات جارية" value={live_calls.length} accent="text-green-600" />
        <Kpi label="مكالمات اليوم" value={today.total} />
        <Kpi label="مُجابة" value={today.answered} accent="text-green-600" />
        <Kpi label="مهجورة" value={today.abandoned} accent="text-red-600" />
        <Kpi label="متوسط الانتظار" value={mmss(today.avg_wait)} />
        <Kpi label="عمال متصلون" value={`${onlineAgents}/${agents.length}`} />
        <Kpi label="محادثات نشطة" value={conversations.active} accent="text-indigo-600" />
        <Kpi label="غير مُسندة" value={conversations.unassigned}
             accent={conversations.unassigned > 0 ? 'text-orange-600' : 'text-gray-800'} />
      </div>

      {/* Live calls */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-bold text-gray-700 text-sm">☎️ المكالمات الحية</h2>
          <span className="text-xs text-gray-400">
            واتساب: {accounts.connected}/{accounts.total} متصل ·
            غير مقروء {conversations.wa_unread}
          </span>
        </div>
        {live_calls.length === 0 ? (
          <p className="text-center text-gray-400 py-8 text-sm">لا توجد مكالمات جارية</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-100">
                <th className="text-right px-4 py-2">المتصل</th>
                <th className="text-right px-2 py-2">الحالة</th>
                <th className="text-right px-2 py-2">القائمة</th>
                <th className="text-right px-2 py-2">العامل</th>
                <th className="text-right px-2 py-2">المدة</th>
                <th className="text-left px-4 py-2">مراقبة</th>
              </tr>
            </thead>
            <tbody>
              {live_calls.map(c => {
                const st = STATE_META[c.state] || {}
                return (
                  <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-4 py-2">
                      <p className="text-gray-800">{c.customer_name || c.caller}</p>
                      {c.customer_name && <p className="text-xs text-gray-400" dir="ltr">{c.caller}</p>}
                    </td>
                    <td className="px-2 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${st.cls || ''}`}>
                        {st.label || c.state}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-gray-500 text-xs">{c.queue || '—'}</td>
                    <td className="px-2 py-2 text-gray-600 text-xs">
                      {c.agent_name || c.agent_ext || '—'}
                    </td>
                    <td className="px-2 py-2 text-gray-600 tabular-nums">{mmss(c.seconds)}</td>
                    <td className="px-4 py-2 text-left whitespace-nowrap">
                      {c.state === 'answered' && c.agent_ext ? (
                        <>
                          <button onClick={() => spy(c.agent_ext, 'listen')}
                                  className="text-xs text-gray-500 hover:text-indigo-600 ml-2"
                                  title="استماع صامت">🎧 استماع</button>
                          <button onClick={() => spy(c.agent_ext, 'whisper')}
                                  className="text-xs text-gray-500 hover:text-indigo-600"
                                  title="همس للعامل دون سماع العميل">🗣️ همس</button>
                        </>
                      ) : <span className="text-xs text-gray-300">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Queues today */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <h2 className="font-bold text-gray-700 text-sm px-4 py-2.5 border-b border-gray-100">
            📋 القوائم اليوم
          </h2>
          {queues.length === 0 ? (
            <p className="text-center text-gray-400 py-8 text-sm">لا توجد بيانات قوائم اليوم</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 border-b border-gray-100">
                  <th className="text-right px-4 py-2">القائمة</th>
                  <th className="text-center px-2 py-2">الكل</th>
                  <th className="text-center px-2 py-2">مُجابة</th>
                  <th className="text-center px-2 py-2">مهجورة</th>
                  <th className="text-center px-2 py-2">م. انتظار</th>
                  <th className="text-center px-2 py-2">م. حديث</th>
                </tr>
              </thead>
              <tbody>
                {queues.map(q => (
                  <tr key={q.queue__name} className="border-b border-gray-50">
                    <td className="px-4 py-2 text-gray-800">{q.queue__name}</td>
                    <td className="text-center px-2 py-2 tabular-nums">{q.total}</td>
                    <td className="text-center px-2 py-2 tabular-nums text-green-600">{q.answered}</td>
                    <td className="text-center px-2 py-2 tabular-nums text-red-600">{q.abandoned}</td>
                    <td className="text-center px-2 py-2 tabular-nums">{mmss(q.avg_wait)}</td>
                    <td className="text-center px-2 py-2 tabular-nums">{mmss(q.avg_talk)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Agents */}
        <div className="bg-white rounded-lg border border-gray-200">
          <h2 className="font-bold text-gray-700 text-sm px-4 py-2.5 border-b border-gray-100">
            👥 العمال
          </h2>
          {agents.length === 0 ? (
            <p className="text-center text-gray-400 py-8 text-sm">
              لا توجد تحويلات من نوع عامل — شغّل sync_pbx_extensions
            </p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 p-3">
              {agents.map(a => (
                <div key={a.extension}
                     className={`rounded border px-3 py-2 text-xs
                       ${a.on_call ? 'bg-green-50 border-green-200'
                         : a.registered ? 'bg-white border-gray-200'
                         : 'bg-gray-50 border-gray-200 opacity-60'}`}>
                  <p className="font-medium text-gray-800 truncate">{a.name}</p>
                  <p className="text-gray-400 mt-0.5">
                    <span dir="ltr">ext {a.extension}</span>
                    {' · '}
                    {a.on_call ? '📞 في مكالمة' : a.registered ? '🟢 متاح' : '⚪ غير مسجل'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
