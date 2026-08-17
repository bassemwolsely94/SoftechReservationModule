/**
 * OmniInboxPage.jsx — CEP Phase 0 (doc 15)
 *
 * Unified omnichannel inbox: one customer, many channels, ONE timeline.
 *  - Right: conversation list (all channels) with filters
 *  - Middle: unified timeline — messages, calls, ERP events interleaved
 *  - Left: Customer 360 side panel + conversation controls
 *
 * Reply routes to WhatsApp (Phase 0). Calls are click-through to /pbx/live.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { omniApi, customersApi } from '../api/client'

// ── helpers ───────────────────────────────────────────────────────────────────
const fmtDt = (dt) => {
  if (!dt) return ''
  const d = new Date(dt)
  const now = new Date()
  const diffH = (now - d) / 3_600_000
  if (diffH < 24) return d.toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('ar-EG', { month: 'short', day: 'numeric' })
}

const CHANNEL_META = {
  whatsapp:  { icon: '💬', label: 'واتساب' },
  voice:     { icon: '☎️', label: 'مكالمات' },
  messenger: { icon: '🟦', label: 'ماسنجر' },
  instagram: { icon: '📸', label: 'إنستجرام' },
  telegram:  { icon: '✈️', label: 'تيليجرام' },
}

const STATUS_META = {
  open:     { label: 'مفتوحة',     cls: 'bg-green-100 text-green-700' },
  pending:  { label: 'بانتظار رد', cls: 'bg-yellow-100 text-yellow-700' },
  snoozed:  { label: 'مؤجلة',      cls: 'bg-gray-100 text-gray-600' },
  resolved: { label: 'محلولة',     cls: 'bg-blue-100 text-blue-700' },
  closed:   { label: 'مغلقة',      cls: 'bg-gray-200 text-gray-500' },
}

const EVENT_ICON = {
  call: '☎️', call_missed: '📵', note: '📝', assignment: '👤',
  status_change: '🔖', erp_reservation: '📋', erp_delivery: '🚚',
  erp_invoice: '🧾', erp_case: '⚠️', erp_demand: '🔍', erp_payment: '💰',
  ai_insight: '✨', automation_action: '⚙️', sla_breach: '⏰',
}

// ── Conversation Row ──────────────────────────────────────────────────────────
function ConversationRow({ conv, selected, onClick }) {
  const ch = CHANNEL_META[conv.created_from_channel] || { icon: '💠' }
  const st = STATUS_META[conv.status] || {}
  return (
    <button
      onClick={() => onClick(conv)}
      className={`w-full text-right px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors
        ${selected ? 'bg-indigo-50 border-r-2 border-r-indigo-500' : ''}`}
      dir="rtl"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-gray-800 text-sm truncate">
            <span className="ml-1">{ch.icon}</span>
            {conv.customer_name || conv.contact_phone || 'مجهول'}
          </p>
          <p className="text-xs text-gray-400 truncate mt-0.5">{conv.last_event_preview}</p>
        </div>
        <div className="flex flex-col items-end shrink-0 gap-1">
          <span className="text-xs text-gray-400">{fmtDt(conv.last_activity_at)}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${st.cls || ''}`}>{st.label || conv.status}</span>
        </div>
      </div>
    </button>
  )
}

// ── Timeline items ────────────────────────────────────────────────────────────
function MessageBubble({ ev }) {
  const out = ev.event_type === 'message_out'
  return (
    <div className={`flex ${out ? 'justify-start' : 'justify-end'} mb-2`} dir="rtl">
      <div className={`max-w-xs md:max-w-md px-3 py-2 rounded-2xl text-sm shadow-sm
        ${out ? 'bg-white border border-gray-200 text-gray-800 rounded-tl-none'
               : 'bg-indigo-500 text-white rounded-tr-none'}`}>
        <p className="whitespace-pre-wrap break-words">{ev.summary || '[رسالة]'}</p>
        <div className={`flex items-center gap-1 mt-1 ${out ? 'justify-end' : 'justify-start'}`}>
          <span className={`text-xs ${out ? 'text-gray-400' : 'text-indigo-100'}`}>
            {fmtDt(ev.occurred_at)}
          </span>
          {out && ev.actor_name && (
            <span className="text-xs text-gray-400">· {ev.actor_name}</span>
          )}
        </div>
      </div>
    </div>
  )
}

function SystemEvent({ ev, onTranscribe, transcribing }) {
  const icon = EVENT_ICON[ev.event_type] || '💠'
  const isCall = ev.event_type === 'call' || ev.event_type === 'call_missed'
  const isTranscript = ev.event_type === 'ai_insight' && ev.payload?.kind === 'transcript'

  // Full-width card for AI transcripts (they carry real text, not a chip)
  if (isTranscript) {
    return (
      <div className="flex justify-center mb-2" dir="rtl">
        <div className="max-w-md w-full bg-purple-50 border border-purple-200 rounded-lg px-3 py-2 text-xs text-purple-900">
          <p className="font-bold mb-1">✨ {ev.summary.startsWith('📝') ? 'تفريغ صوتي' : 'تحليل ذكي'}
            <span className="font-normal text-purple-400 mr-2">{fmtDt(ev.occurred_at)}</span>
          </p>
          <p className="whitespace-pre-wrap break-words leading-relaxed">
            {ev.payload?.text || ev.summary}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center mb-2" dir="rtl">
      <div className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border
        ${ev.event_type === 'call_missed' ? 'bg-red-50 border-red-200 text-red-700'
          : ev.event_type.startsWith('erp_') ? 'bg-blue-50 border-blue-200 text-blue-700'
          : ev.event_type === 'ai_insight' ? 'bg-purple-50 border-purple-200 text-purple-700'
          : 'bg-gray-50 border-gray-200 text-gray-600'}`}>
        <span>{icon}</span>
        <span>{ev.summary}</span>
        <span className="text-gray-400">{fmtDt(ev.occurred_at)}</span>
        {isCall && ev.recording && onTranscribe && (
          <button onClick={() => onTranscribe(ev)} disabled={transcribing === ev.id}
                  className="text-purple-600 hover:text-purple-800 disabled:opacity-50"
                  title="تفريغ نصي بالذكاء الاصطناعي">
            {transcribing === ev.id ? '⏳' : '📝'}
          </button>
        )}
      </div>
      {isCall && ev.recording && (
        <audio controls preload="none" src={ev.recording}
               className="mt-1 h-8" style={{ maxWidth: '260px' }} />
      )}
    </div>
  )
}

// ── Timeline pane ─────────────────────────────────────────────────────────────
function TimelinePane({ conv }) {
  const [text, setText] = useState('')
  const [transcribing, setTranscribing] = useState(null)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['omni-timeline', conv.id],
    queryFn: () => omniApi.timeline(conv.id).then(r => r.data),
    refetchInterval: 10_000,
  })

  const transcribe = async (ev) => {
    setTranscribing(ev.id)
    try {
      await omniApi.transcribe(ev.id)
      // Result arrives as a new ai_insight event via polling
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['omni-timeline', conv.id] })
        setTranscribing(null)
      }, 8000)
    } catch {
      setTranscribing(null)
    }
  }

  const reply = useMutation({
    mutationFn: () => omniApi.reply(conv.id, { body: text }),
    onSuccess: () => {
      setText('')
      qc.invalidateQueries({ queryKey: ['omni-timeline', conv.id] })
      qc.invalidateQueries({ queryKey: ['omni-conversations'] })
    },
  })

  const events = data?.results || data || []
  const wa = conv.wa_thread
  const social = conv.social_thread
  // Reply routes to whichever messaging channel is available (WA preferred)
  const replyChannel = wa ? 'whatsapp' : social?.channel
  const windowOpen = wa ? wa.window_open : social ? social.window_open : false
  const canReply = Boolean(replyChannel) && windowOpen
  const channelLabel = wa ? 'واتساب'
    : social ? (CHANNEL_META[social.channel]?.label || social.channel) : ''

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <div>
          <p className="font-bold text-gray-800">
            {conv.customer_name || conv.contact_phone || 'مجهول'}
          </p>
          <p className="text-xs text-gray-500">
            {conv.contact_phone || social?.display_name}
            {wa && <span className="mr-2">💬 {wa.wa_id}</span>}
            {!wa && social && (
              <span className="mr-2">
                {CHANNEL_META[social.channel]?.icon} {CHANNEL_META[social.channel]?.label}
              </span>
            )}
          </p>
        </div>
        {replyChannel && (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium
            ${windowOpen ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
            {windowOpen ? `نافذة ${channelLabel} مفتوحة` : `نافذة ${channelLabel} مغلقة`}
          </span>
        )}
      </div>

      {/* Unified timeline */}
      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {isLoading ? (
          <p className="text-center text-gray-400 pt-10">جاري التحميل...</p>
        ) : events.length === 0 ? (
          <p className="text-center text-gray-400 pt-10">لا توجد أحداث</p>
        ) : (
          events.map((ev) =>
            ev.event_type === 'message_in' || ev.event_type === 'message_out'
              ? <MessageBubble key={ev.id} ev={ev} />
              : <SystemEvent key={ev.id} ev={ev}
                             onTranscribe={transcribe} transcribing={transcribing} />
          )
        )}
      </div>

      {/* AI assist */}
      <AIAssistBar conv={conv} onUseReply={setText} />

      {/* Reply — routes to WhatsApp or social channel (Phases 0/3) */}
      <div className="border-t border-gray-200 bg-white p-3">
        {!replyChannel ? (
          <p className="text-xs text-gray-400 text-center py-1">
            لا توجد قناة رسائل لهذه المحادثة — للاتصال استخدم{' '}
            <Link to="/pbx/live" className="text-indigo-600 underline">المكالمات الحية</Link>
          </p>
        ) : (
          <>
            {!canReply && (
              <div className="mb-2 bg-yellow-50 border border-yellow-200 rounded px-3 py-2 text-xs text-yellow-700">
                نافذة الـ 24 ساعة مغلقة لقناة {channelLabel}.
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={text}
                onChange={e => setText(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && canReply && text.trim() && reply.mutate()}
                placeholder={canReply ? `اكتب رداً عبر ${channelLabel}...` : 'النافذة مغلقة'}
                disabled={!canReply}
                className="flex-1 border border-gray-200 rounded-full px-4 py-2 text-sm disabled:bg-gray-50 disabled:text-gray-400 focus:outline-none focus:border-indigo-400"
              />
              <button
                onClick={() => reply.mutate()}
                disabled={!canReply || !text.trim() || reply.isPending}
                className="w-9 h-9 bg-indigo-600 text-white rounded-full flex items-center justify-center text-sm disabled:opacity-40"
              >
                ↑
              </button>
            </div>
            {reply.isError && (
              <p className="text-red-500 text-xs mt-1">
                {reply.error?.response?.data?.detail || 'فشل الإرسال — حاول مجدداً'}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── AI assist bar ─────────────────────────────────────────────────────────────
function AIAssistBar({ conv, onUseReply }) {
  const [open, setOpen] = useState(false)
  const assist = useMutation({
    mutationFn: () => omniApi.aiAssist(conv.id).then(r => r.data),
  })

  const run = () => {
    setOpen(true)
    assist.mutate()
  }

  const r = assist.data
  return (
    <div className="border-t border-purple-100 bg-purple-50/40" dir="rtl">
      <button onClick={open ? () => setOpen(false) : run}
              className="w-full flex items-center justify-between px-3 py-1.5 text-xs text-purple-700 hover:bg-purple-50">
        <span className="font-medium">✨ مساعد الذكاء الاصطناعي</span>
        <span>{assist.isPending ? '⏳ يحلل...' : open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-3 pb-2 space-y-2">
          {assist.isPending ? (
            <p className="text-xs text-gray-400 py-2">جاري تحليل المحادثة...</p>
          ) : assist.isError ? (
            <p className="text-xs text-red-500 py-1">
              {assist.error?.response?.data?.detail || 'تعذّر التحليل'}
            </p>
          ) : r ? (
            <>
              {r.summary && (
                <p className="text-xs text-gray-600 bg-white rounded p-2 border border-purple-100">
                  <span className="font-bold text-purple-700">الملخص: </span>{r.summary}
                  {r.intent && <span className="mr-2 text-purple-400">· {r.intent}</span>}
                  {r.urgency && <span className="mr-1 text-purple-400">· إلحاح {r.urgency}/5</span>}
                </p>
              )}
              <div className="space-y-1">
                <p className="text-[11px] text-gray-400">ردود مقترحة (اضغط للاستخدام):</p>
                {(r.suggested_replies || []).map((s, i) => (
                  <button key={i} onClick={() => onUseReply(s)}
                          className="block w-full text-right text-xs bg-white hover:bg-purple-100 border border-purple-100 rounded px-2 py-1.5 text-gray-700 transition-colors">
                    {s}
                  </button>
                ))}
              </div>
              <button onClick={run} className="text-[11px] text-purple-500 hover:underline">
                ↻ إعادة التحليل
              </button>
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}

// ── Customer 360 side panel ───────────────────────────────────────────────────
function Customer360Panel({ conv, onUpdate }) {
  const qc = useQueryClient()

  const { data: customer } = useQuery({
    queryKey: ['omni-customer', conv.customer],
    queryFn: () => customersApi.get(conv.customer).then(r => r.data),
    enabled: Boolean(conv.customer),
  })

  const { data: reservations } = useQuery({
    queryKey: ['omni-cust-reservations', conv.customer],
    queryFn: () => customersApi.reservations(conv.customer).then(r => r.data),
    enabled: Boolean(conv.customer),
  })

  const update = useMutation({
    mutationFn: (data) => omniApi.update(conv.id, data),
    onSuccess: (resp) => {
      qc.invalidateQueries({ queryKey: ['omni-conversations'] })
      qc.invalidateQueries({ queryKey: ['omni-timeline', conv.id] })
      onUpdate?.(resp.data)
    },
  })

  const resList = reservations?.results || reservations || []

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4" dir="rtl">
      {/* Conversation controls */}
      <div className="bg-white rounded-lg border border-gray-200 p-3 space-y-2">
        <p className="text-xs font-bold text-gray-500">إدارة المحادثة</p>
        <select
          value={conv.status}
          onChange={e => update.mutate({ status: e.target.value })}
          className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm"
        >
          {Object.entries(STATUS_META).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        <p className="text-xs text-gray-500">
          موكلة إلى: <span className="font-medium">{conv.assigned_to_name || 'غير مسندة'}</span>
        </p>
      </div>

      {/* Customer 360 */}
      {conv.customer ? (
        <div className="bg-white rounded-lg border border-gray-200 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold text-gray-500">العميل 360</p>
            <Link to={`/customers/${conv.customer}`} className="text-xs text-indigo-600 underline">
              الملف الكامل ←
            </Link>
          </div>
          <p className="font-bold text-gray-800">{customer?.name || conv.customer_name}</p>
          <p className="text-sm text-gray-500 ltr text-left" dir="ltr">{customer?.phone || conv.customer_phone}</p>
          {customer?.segment && (
            <span className="inline-block text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full">
              {customer.segment}
            </span>
          )}
          {resList.length > 0 && (
            <div className="pt-2 border-t border-gray-100">
              <p className="text-xs font-bold text-gray-500 mb-1">آخر الحجوزات</p>
              {resList.slice(0, 5).map(r => (
                <Link key={r.id} to={`/reservations/${r.id}`}
                      className="block text-xs text-gray-600 hover:text-indigo-600 py-0.5 truncate">
                  📋 #{r.id} — {r.item_label || r.manual_item_name || r.status}
                </Link>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-dashed border-gray-300 p-3 text-center">
          <p className="text-xs text-gray-400">جهة اتصال غير معرَّفة</p>
          <p className="text-sm text-gray-600 mt-1" dir="ltr">{conv.contact_phone}</p>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
const FILTERS = [
  { key: 'active',   label: 'النشطة' },
  { key: '',         label: 'الكل' },
  { key: 'resolved', label: 'المحلولة' },
  { key: 'closed',   label: 'المغلقة' },
]

export default function OmniInboxPage() {
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('active')
  const [mineOnly, setMineOnly] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['omni-conversations', search, statusFilter, mineOnly],
    queryFn: () => omniApi.conversations({
      q: search || undefined,
      status: statusFilter || undefined,
      assigned_to_me: mineOnly || undefined,
    }).then(r => r.data),
    refetchInterval: 15_000,
  })

  const conversations = data?.results || data || []
  // Keep the selected conversation fresh from the polled list
  const current = conversations.find(c => c.id === selected?.id) || selected

  return (
    <div className="flex h-full" dir="rtl">
      {/* Right: conversation list */}
      <div className="w-80 shrink-0 border-l border-gray-200 flex flex-col bg-white">
        <div className="px-3 py-3 border-b border-gray-100">
          <h1 className="font-bold text-gray-800 mb-2 text-lg">📥 الصندوق الموحد</h1>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="بحث باسم أو رقم..."
            className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-indigo-400"
          />
          <div className="flex items-center gap-1 mt-2 text-xs">
            {FILTERS.map(f => (
              <button key={f.key}
                onClick={() => setStatusFilter(f.key)}
                className={`px-2 py-1 rounded-full transition-colors
                  ${statusFilter === f.key ? 'bg-indigo-100 text-indigo-700 font-medium' : 'text-gray-500 hover:bg-gray-100'}`}>
                {f.label}
              </button>
            ))}
            <button
              onClick={() => setMineOnly(v => !v)}
              className={`px-2 py-1 rounded-full mr-auto transition-colors
                ${mineOnly ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-100'}`}>
              محادثاتي
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <p className="text-center text-gray-400 py-10 text-sm">جاري التحميل...</p>
          ) : conversations.length === 0 ? (
            <p className="text-center text-gray-400 py-10 text-sm">لا توجد محادثات</p>
          ) : (
            conversations.map((c) => (
              <ConversationRow key={c.id} conv={c}
                selected={current?.id === c.id} onClick={setSelected} />
            ))
          )}
        </div>
      </div>

      {/* Middle: unified timeline */}
      <div className="flex-1 min-w-0 border-l border-gray-200">
        {current ? (
          <TimelinePane conv={current} />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p className="text-4xl mb-2">📥</p>
              <p>اختر محادثة — كل القنوات في مكان واحد</p>
            </div>
          </div>
        )}
      </div>

      {/* Left: Customer 360 */}
      {current && (
        <div className="w-72 shrink-0 bg-gray-50 hidden lg:block">
          <Customer360Panel conv={current} onUpdate={setSelected} />
        </div>
      )}
    </div>
  )
}
