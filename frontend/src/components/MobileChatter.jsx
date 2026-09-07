/**
 * MobileChatter.jsx — compact chatter thread + text composer for mobile detail
 * screens. The parent passes a normalized message list and an async onSend(text);
 * used by the reservation and transfer detail pages (each maps its own
 * activities/messages shape into { id, text, who, when }).
 */
import { useState } from 'react'
import { format } from 'date-fns'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

export default function MobileChatter({ messages = [], onSend, title = '💬 المحادثة', readOnly = false }) {
  const [text, setText]   = useState('')
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')

  async function send() {
    const t = text.trim()
    if (!t) return
    setBusy(true); setError('')
    try {
      await onSend(t)
      setText('')
    } catch {
      setError('تعذّر الإرسال')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4">
      <h2 className="font-semibold text-gray-700 text-sm mb-2.5">{title}</h2>

      {messages.length === 0 ? (
        <div className="text-xs text-gray-400 py-2">لا توجد رسائل بعد</div>
      ) : (
        <div className="space-y-2.5 mb-3">
          {messages.map(m => (
            <div key={m.id} className="flex gap-2.5 text-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-400 mt-1.5 shrink-0" />
              <div className="min-w-0">
                <div className="text-gray-700 break-words">{m.text}</div>
                <div className="text-gray-400 mt-0.5">
                  {m.who || 'النظام'}{m.when ? ` · ${toLatin(format(new Date(m.when), 'yyyy/MM/dd HH:mm'))}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!readOnly && (
        <div className="flex gap-2">
          <input
            className="input-field flex-1 text-sm"
            placeholder="اكتب ملاحظة..."
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') send() }}
          />
          <button onClick={send} disabled={busy || !text.trim()}
            className="btn-primary text-sm py-2 px-4 disabled:opacity-50">
            {busy ? '...' : 'إرسال'}
          </button>
        </div>
      )}
      {error && <div className="text-xs text-red-600 mt-1.5">{error}</div>}
    </div>
  )
}
