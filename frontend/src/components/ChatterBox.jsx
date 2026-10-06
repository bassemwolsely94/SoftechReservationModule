/**
 * ChatterBox.jsx
 *
 * Threaded comment / chatter component that can be embedded on any record detail page.
 * Uses useChatterSocket for real-time delivery.
 *
 * Usage:
 *   <ChatterBox modelName="reservation" recordId={42} />
 *   <ChatterBox modelName="transfer"    recordId={7}  />
 *
 * Features:
 *   - Real-time via WebSocket (falls back to 10s REST polling)
 *   - @mention hint in placeholder
 *   - Shift+Enter for newlines, Enter to send
 *   - Auto-scroll to latest message
 *   - Connection status indicator
 *   - Voice note recording + file attachment upload (TD-H001)
 */
import { useState, useRef, useEffect } from 'react'
import { useChatterSocket } from '../hooks/useChatterSocket'
import VoiceNoteRecorder from './VoiceNoteRecorder'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

function timeAgo(dt) {
  try {
    return toLatinDigits(formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }))
  } catch { return '' }
}

function Avatar({ initials, colorIndex = 0 }) {
  const COLORS = [
    'bg-brand-100 text-brand-700',
    'bg-green-100 text-green-700',
    'bg-orange-100 text-orange-700',
    'bg-purple-100 text-purple-700',
    'bg-pink-100 text-pink-700',
    'bg-teal-100 text-teal-700',
  ]
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center
      text-xs font-bold flex-shrink-0 ${COLORS[colorIndex % COLORS.length]}`}>
      {(initials || '??').toUpperCase().slice(0, 2)}
    </div>
  )
}

function VoiceRenderer({ voiceUrl }) {
  if (!voiceUrl) return null
  return (
    <div className="mt-1.5">
      <audio
        src={voiceUrl}
        controls
        className="w-full h-8 rounded"
        style={{ direction: 'ltr' }}
        preload="metadata"
      />
    </div>
  )
}

function AttachmentRenderer({ fileType, attachmentUrl }) {
  if (!attachmentUrl) return null

  if (fileType === 'voice') {
    return (
      <div className="mt-1.5">
        <audio
          src={attachmentUrl}
          controls
          className="w-full h-8 rounded"
          style={{ direction: 'ltr' }}
          preload="metadata"
        />
      </div>
    )
  }

  if (fileType === 'image') {
    return (
      <div className="mt-1.5">
        <a href={attachmentUrl} target="_blank" rel="noopener noreferrer">
          <img
            src={attachmentUrl}
            alt="مرفق"
            className="max-w-[220px] max-h-[160px] rounded-lg border border-gray-200 object-cover hover:opacity-90 transition-opacity"
          />
        </a>
      </div>
    )
  }

  if (fileType === 'doc') {
    return (
      <a
        href={attachmentUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1.5 flex items-center gap-1.5 text-xs text-brand-600 hover:underline"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        عرض المرفق
      </a>
    )
  }

  return null
}

function MessageBubble({ msg }) {
  const colorIndex = (msg.author || 0) % 6
  return (
    <div className="flex gap-2.5 group" dir="rtl">
      <Avatar initials={msg.author_avatar || '?'} colorIndex={colorIndex} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-0.5">
          <span className="text-xs font-semibold text-gray-700">{msg.author_name || 'مجهول'}</span>
          <span className="text-xs text-gray-400">{msg.time_ago || timeAgo(msg.created_at)}</span>
        </div>
        <div className="bg-gray-50 rounded-xl rounded-tr-sm px-3 py-2 text-sm text-gray-800
          whitespace-pre-wrap break-words leading-relaxed border border-gray-100">
          {/* Highlight @mentions */}
          {msg.message && msg.message.split(/(@[\w؀-ۿ]+)/g).map((part, i) =>
            part.startsWith('@')
              ? <span key={i} className="text-brand-600 font-medium">{part}</span>
              : part
          )}
          {/* Attachment: image / doc (or legacy voice via attachment) */}
          <AttachmentRenderer fileType={msg.file_type} attachmentUrl={msg.attachment_url} />
          {/* Dedicated voice note — may appear alongside an image attachment */}
          <VoiceRenderer voiceUrl={msg.voice_note_url} />
        </div>
      </div>
    </div>
  )
}

export default function ChatterBox({ modelName, recordId, className = '' }) {
  const [draft, setDraft]           = useState('')
  const [error, setError]           = useState('')
  const [voiceFile, setVoiceFile]   = useState(null)   // File object from VoiceNoteRecorder
  const [imageFile, setImageFile]   = useState(null)   // image/doc File from the picker
  const [showVoice, setShowVoice]   = useState(false)  // toggle recorder panel
  const bottomRef                   = useRef(null)
  const textareaRef                 = useRef(null)
  const fileInputRef                = useRef(null)

  const { messages, isConnected, isPosting, postMessage, postMessageWithAttachment } =
    useChatterSocket(modelName, recordId)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  async function handleSubmit(e) {
    e.preventDefault()
    const text = draft.trim()
    if (!text && !voiceFile && !imageFile) return
    setError('')
    try {
      if (voiceFile || imageFile) {
        await postMessageWithAttachment(text, { attachment: imageFile, voiceNote: voiceFile })
        setVoiceFile(null)
        setImageFile(null)
        setShowVoice(false)
      } else {
        await postMessage(text)
      }
      setDraft('')
      textareaRef.current?.focus()
    } catch {
      setError('فشل إرسال الرسالة — حاول مجدداً')
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  function handleVoiceRecorded(file) {
    setVoiceFile(file)
  }

  function handleVoiceClear() {
    setVoiceFile(null)
  }

  function handleImagePick(e) {
    const f = e.target.files?.[0]
    if (f) setImageFile(f)
    e.target.value = ''   // allow re-picking the same file
  }

  const canSend = (draft.trim() || voiceFile || imageFile) && !isPosting

  return (
    <div className={`flex flex-col bg-white rounded-xl border border-gray-200 ${className}`} dir="rtl">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-700">💬 الدردشة</span>
          <span className="text-xs text-gray-400">({messages.length} رسالة)</span>
        </div>
        {/* WS indicator */}
        <div className="flex items-center gap-1">
          <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-green-400' : 'bg-gray-300'}`} />
          <span className="text-xs text-gray-400">{isConnected ? 'متصل' : 'استطلاع'}</span>
        </div>
      </div>

      {/* ── Messages ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-32 max-h-72">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-8 text-gray-400">
            <div className="text-3xl mb-2">💬</div>
            <p className="text-xs">لا توجد تعليقات بعد</p>
            <p className="text-xs mt-1">اكتب أول تعليق أدناه</p>
          </div>
        ) : (
          messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Voice recorder panel (collapsible) ──────────────────────────── */}
      {showVoice && (
        <div className="border-t border-gray-100 px-3 py-2 bg-gray-50">
          <VoiceNoteRecorder
            onRecorded={handleVoiceRecorded}
            onClear={handleVoiceClear}
            disabled={isPosting}
            maxSeconds={120}
          />
        </div>
      )}

      {/* ── Input ────────────────────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} className="border-t border-gray-100 px-3 py-2">
        {error && (
          <p className="text-xs text-red-500 mb-1.5 px-1">{error}</p>
        )}
        {/* Selected image/doc preview chip — sits above the input row */}
        {imageFile && (
          <div className="flex items-center gap-2 mb-1.5 px-2 py-1 rounded-lg bg-gray-50 border border-gray-200 text-xs text-gray-600">
            <span>📎</span>
            <span className="truncate flex-1">{imageFile.name}</span>
            <button
              type="button"
              onClick={() => setImageFile(null)}
              disabled={isPosting}
              className="text-gray-400 hover:text-red-500 disabled:opacity-50"
              title="إزالة المرفق"
            >✕</button>
          </div>
        )}
        <div className="flex gap-2 items-end">
          {/* Voice note toggle */}
          <button
            type="button"
            onClick={() => { setShowVoice(v => !v); setVoiceFile(null) }}
            disabled={isPosting}
            title="ملاحظة صوتية"
            className={`flex-shrink-0 p-2 rounded-lg border transition-colors disabled:opacity-50
              ${showVoice
                ? 'bg-red-50 border-red-300 text-red-600'
                : 'border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-200'
              }`}
          >
            {/* Microphone icon */}
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M12 3a4 4 0 014 4v4a4 4 0 01-8 0V7a4 4 0 014-4z" />
            </svg>
          </button>

          {/* Image / document attachment */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,application/pdf"
            onChange={handleImagePick}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isPosting}
            title="إرفاق صورة أو مستند"
            className={`flex-shrink-0 p-2 rounded-lg border transition-colors disabled:opacity-50
              ${imageFile
                ? 'bg-brand-50 border-brand-300 text-brand-600'
                : 'border-gray-200 text-gray-400 hover:text-brand-500 hover:border-brand-200'
              }`}
          >
            {/* Paperclip icon */}
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>

          <textarea
            ref={textareaRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={
              voiceFile
                ? 'أضف تعليقاً مع الملاحظة الصوتية (اختياري)...'
                : 'اكتب تعليقاً... استخدم @اسم للإشارة إلى مستخدم'
            }
            disabled={isPosting}
            className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2
              focus:outline-none focus:ring-1 focus:ring-brand-400 resize-none
              text-right disabled:opacity-50 placeholder:text-gray-300"
          />
          <button
            type="submit"
            disabled={!canSend}
            className="flex-shrink-0 bg-brand-600 hover:bg-brand-700 text-white
              text-xs font-semibold px-3 py-2 rounded-lg transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed h-[58px] flex items-center gap-1"
          >
            {isPosting
              ? <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                </svg>
              : voiceFile
                ? <><span>🎙️</span><span>إرسال</span></>
                : 'إرسال'
            }
          </button>
        </div>
        <p className="text-xs text-gray-300 mt-1 px-1">
          {voiceFile
            ? '✅ ملاحظة صوتية جاهزة — اضغط إرسال'
            : 'Enter للإرسال · Shift+Enter لسطر جديد · 🎙️ لتسجيل صوتي'
          }
        </p>
      </form>
    </div>
  )
}
