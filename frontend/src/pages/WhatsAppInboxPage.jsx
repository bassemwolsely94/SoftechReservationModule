/**
 * WhatsAppInboxPage.jsx
 *
 * WhatsApp Business inbox — left panel: conversation list, right panel: message thread.
 *  - Shows all WAConversation records
 *  - Loads WAMessage thread per conversation
 *  - Send text (only within 24h window) or template (always)
 *  - Window indicator: green = open, red = closed
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { whatsappApi } from '../api/client'

// ── helpers ───────────────────────────────────────────────────────────────────
const fmtDt = (dt) => {
  if (!dt) return ''
  const d = new Date(dt)
  const now = new Date()
  const diffH = (now - d) / 3_600_000
  if (diffH < 24) return d.toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('ar-EG', { month: 'short', day: 'numeric' })
}

const STATUS_COLOR = {
  pending:   'text-gray-400',
  sent:      'text-blue-400',
  delivered: 'text-blue-600',
  read:      'text-green-600',
  failed:    'text-red-500',
}

const Tick = ({ status }) => {
  const icons = { pending: '○', sent: '✓', delivered: '✓✓', read: '✓✓', failed: '✗' }
  return (
    <span className={`text-xs ${STATUS_COLOR[status] || 'text-gray-400'}`}>
      {icons[status] || ''}
    </span>
  )
}


// ── Conversation Row ──────────────────────────────────────────────────────────
function ConversationRow({ conv, selected, onClick }) {
  const windowOpen = conv.window_open
  return (
    <button
      onClick={() => onClick(conv)}
      className={`w-full text-right px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors
        ${selected ? 'bg-green-50 border-r-2 border-r-green-500' : ''}`}
      dir="rtl"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-gray-800 text-sm truncate">
            {conv.customer_name || conv.wa_id}
          </p>
          <p className="text-xs text-gray-400 truncate mt-0.5">{conv.wa_id}</p>
        </div>
        <div className="flex flex-col items-end shrink-0">
          <span className="text-xs text-gray-400">{fmtDt(conv.last_message_at)}</span>
          <span className={`mt-1 w-2 h-2 rounded-full ${windowOpen ? 'bg-green-400' : 'bg-red-400'}`}
                title={windowOpen ? 'نافذة مفتوحة' : 'نافذة مغلقة'} />
        </div>
      </div>
    </button>
  )
}


// ── Message Bubble ────────────────────────────────────────────────────────────
function Bubble({ msg }) {
  const out = msg.direction === 'outbound'
  return (
    <div className={`flex ${out ? 'justify-start' : 'justify-end'} mb-2`} dir="rtl">
      <div className={`max-w-xs md:max-w-sm px-3 py-2 rounded-2xl text-sm shadow-sm
        ${out ? 'bg-white border border-gray-200 text-gray-800 rounded-tl-none'
               : 'bg-green-500 text-white rounded-tr-none'}`}>
        <p className="whitespace-pre-wrap break-words">{msg.body || msg.caption || '[رسالة وسائط]'}</p>
        <div className={`flex items-center gap-1 mt-1 ${out ? 'justify-end' : 'justify-start'}`}>
          <span className={`text-xs ${out ? 'text-gray-400' : 'text-green-100'}`}>
            {fmtDt(msg.sent_at || msg.received_at || msg.created_at)}
          </span>
          {out && <Tick status={msg.status} />}
        </div>
      </div>
    </div>
  )
}


// ── Message Thread ────────────────────────────────────────────────────────────
function MessageThread({ conv }) {
  const [text, setText] = useState('')
  const [templateMode, setTemplateMode] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const qc = useQueryClient()

  const { data: msgData, isLoading } = useQuery({
    queryKey: ['wa-messages', conv.id],
    queryFn: () => whatsappApi.messages(conv.id).then(r => r.data),
    refetchInterval: 10_000,
  })

  const { data: tplData } = useQuery({
    queryKey: ['wa-templates'],
    queryFn: () => whatsappApi.templates().then(r => r.data),
  })

  const sendText = useMutation({
    mutationFn: () => whatsappApi.sendText(conv.id, { body: text }),
    onSuccess: () => {
      setText('')
      qc.invalidateQueries({ queryKey: ['wa-messages', conv.id] })
    },
  })

  const sendTemplate = useMutation({
    mutationFn: () => whatsappApi.sendTemplate(conv.id, {
      template_name: selectedTemplate,
      language: 'ar',
      variables: [],
    }),
    onSuccess: () => {
      setSelectedTemplate('')
      setTemplateMode(false)
      qc.invalidateQueries({ queryKey: ['wa-messages', conv.id] })
    },
  })

  const messages = msgData?.results || msgData || []
  const templates = tplData?.results || tplData || []
  const windowOpen = conv.window_open

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {/* Conversation header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <div>
          <p className="font-bold text-gray-800">{conv.customer_name || conv.wa_id}</p>
          <p className="text-xs text-gray-500">{conv.wa_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium
            ${windowOpen ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
            {windowOpen ? 'نافذة مفتوحة' : 'نافذة مغلقة'}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
        {isLoading ? (
          <p className="text-center text-gray-400 pt-10">جاري التحميل...</p>
        ) : messages.length === 0 ? (
          <p className="text-center text-gray-400 pt-10">لا توجد رسائل</p>
        ) : (
          messages.map((m) => <Bubble key={m.id} msg={m} />)
        )}
      </div>

      {/* Compose */}
      <div className="border-t border-gray-200 bg-white p-3">
        {!windowOpen && !templateMode && (
          <div className="mb-2 bg-yellow-50 border border-yellow-200 rounded px-3 py-2 text-xs text-yellow-700">
            نافذة الـ 24 ساعة مغلقة — يمكنك إرسال قوالب معتمدة فقط.
            <button className="mr-2 text-yellow-900 underline" onClick={() => setTemplateMode(true)}>
              إرسال قالب
            </button>
          </div>
        )}

        {templateMode ? (
          <div className="space-y-2">
            <select
              value={selectedTemplate}
              onChange={e => setSelectedTemplate(e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm"
            >
              <option value="">اختر قالباً...</option>
              {templates.map(t => (
                <option key={t.id} value={t.name}>{t.name}</option>
              ))}
            </select>
            <div className="flex gap-2">
              <button
                onClick={() => sendTemplate.mutate()}
                disabled={!selectedTemplate || sendTemplate.isPending}
                className="flex-1 bg-green-600 text-white rounded px-3 py-2 text-sm disabled:opacity-50"
              >
                {sendTemplate.isPending ? 'جاري الإرسال...' : 'إرسال القالب'}
              </button>
              <button onClick={() => setTemplateMode(false)} className="px-3 py-2 text-sm text-gray-500">
                إلغاء
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <input
              value={text}
              onChange={e => setText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && windowOpen && text.trim() && sendText.mutate()}
              placeholder={windowOpen ? 'اكتب رسالة...' : 'النافذة مغلقة'}
              disabled={!windowOpen}
              className="flex-1 border border-gray-200 rounded-full px-4 py-2 text-sm disabled:bg-gray-50 disabled:text-gray-400 focus:outline-none focus:border-green-400"
            />
            <button
              onClick={() => sendText.mutate()}
              disabled={!windowOpen || !text.trim() || sendText.isPending}
              className="w-9 h-9 bg-green-600 text-white rounded-full flex items-center justify-center text-sm disabled:opacity-40"
            >
              ↑
            </button>
            {windowOpen && (
              <button
                onClick={() => setTemplateMode(true)}
                className="text-xs text-gray-400 hover:text-gray-600 px-1"
                title="إرسال قالب"
              >
                📋
              </button>
            )}
          </div>
        )}
        {(sendText.isError || sendTemplate.isError) && (
          <p className="text-red-500 text-xs mt-1">فشل الإرسال — حاول مجدداً</p>
        )}
      </div>
    </div>
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────
export default function WhatsAppInboxPage() {
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['wa-conversations', search],
    queryFn: () => whatsappApi.conversations({ q: search || undefined }).then(r => r.data),
    refetchInterval: 15_000,
  })

  const conversations = data?.results || data || []

  return (
    <div className="flex h-full" dir="rtl">
      {/* Left: conversation list */}
      <div className="w-80 shrink-0 border-l border-gray-200 flex flex-col bg-white">
        <div className="px-3 py-3 border-b border-gray-100">
          <h1 className="font-bold text-gray-800 mb-2 text-lg">صندوق واتساب</h1>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="بحث برقم أو اسم..."
            className="w-full border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-green-400"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <p className="text-center text-gray-400 py-10 text-sm">جاري التحميل...</p>
          ) : conversations.length === 0 ? (
            <p className="text-center text-gray-400 py-10 text-sm">لا توجد محادثات</p>
          ) : (
            conversations.map((c) => (
              <ConversationRow
                key={c.id}
                conv={c}
                selected={selected?.id === c.id}
                onClick={setSelected}
              />
            ))
          )}
        </div>
      </div>

      {/* Right: thread */}
      <div className="flex-1 min-w-0">
        {selected ? (
          <MessageThread conv={selected} />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p className="text-4xl mb-2">💬</p>
              <p>اختر محادثة للبدء</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
