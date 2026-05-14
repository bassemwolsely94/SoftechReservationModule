import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reservationsApi, branchesApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'
import VoiceNoteRecorder from '../components/VoiceNoteRecorder'
import PrintReceiptModal from '../components/PrintReceiptModal'
import WhatsAppShareButton from '../components/WhatsAppShareButton'

// ── Status config ─────────────────────────────────────────────────────────────
const COLUMNS = [
  { key: 'pending',   label: 'قيد الانتظار',     color: '#6b7280', bg: '#f9fafb', dot: '#9ca3af' },
  { key: 'available', label: 'المخزون متاح',       color: '#d97706', bg: '#fffbeb', dot: '#f59e0b' },
  { key: 'contacted', label: 'تم التواصل',          color: '#2563eb', bg: '#eff6ff', dot: '#3b82f6' },
  { key: 'confirmed', label: 'مؤكد — قادم',        color: '#7c3aed', bg: '#f5f3ff', dot: '#8b5cf6' },
  { key: 'fulfilled', label: 'تم التسليم',          color: '#059669', bg: '#ecfdf5', dot: '#10b981' },
  { key: 'cancelled', label: 'ملغي / منتهي',       color: '#dc2626', bg: '#fef2f2', dot: '#ef4444' },
]

const PRIORITY_BADGE = {
  normal:  { label: 'عادي',        cls: 'bg-gray-100 text-gray-600' },
  urgent:  { label: 'عاجل 🔴',     cls: 'bg-red-100 text-red-700' },
  chronic: { label: 'مزمن 💊',     cls: 'bg-purple-100 text-purple-700' },
}

const STATUS_TRANSITIONS = {
  pending:   ['available', 'cancelled'],
  available: ['contacted', 'cancelled'],
  contacted: ['confirmed', 'cancelled', 'expired'],
  confirmed: ['fulfilled', 'cancelled'],
  fulfilled: [],
  cancelled: [],
  expired:   [],
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function timeAgo(dt) {
  try { return formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true }) }
  catch { return '' }
}

function formatDate(d) {
  if (!d) return '—'
  try { return format(new Date(d), 'dd/MM/yyyy') } catch { return d }
}

// ── Card component ────────────────────────────────────────────────────────────
function ReservationCard({ reservation, onStatusChange, onOpen, isCCOrAdmin }) {
  const col = COLUMNS.find(c => c.key === reservation.status) || COLUMNS[0]
  const pri = PRIORITY_BADGE[reservation.priority] || PRIORITY_BADGE.normal
  const transitions = STATUS_TRANSITIONS[reservation.status] || []

  return (
    <div
      className="bg-white rounded-xl shadow-sm border border-gray-100 p-3 cursor-pointer hover:shadow-md hover:border-gray-200 transition-all duration-150 select-none"
      onClick={() => onOpen(reservation)}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-gray-900 text-sm leading-tight truncate">
            {reservation.item_name}
          </div>
          {reservation.item_softech_id && (
            <div className="text-xs text-gray-400 font-mono mt-0.5">
              كود: {reservation.item_softech_id}
            </div>
          )}
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap flex-shrink-0 ${pri.cls}`}>
          {pri.label}
        </span>
      </div>

      {/* Customer */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-gray-400 text-xs">👤</span>
        <span className="text-xs text-gray-700 truncate">{reservation.customer_name}</span>
      </div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-gray-400 text-xs">📞</span>
        <span className="text-xs text-gray-600 font-mono" dir="ltr">{reservation.contact_phone}</span>
      </div>

      {/* Branch badge — shown for CC/admin */}
      {isCCOrAdmin && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="text-gray-400 text-xs">🏥</span>
          <span className="text-xs bg-brand-50 text-brand-700 px-1.5 py-0.5 rounded font-medium truncate">
            {reservation.branch_name}
          </span>
        </div>
      )}

      {/* Qty + image indicator */}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-50">
        <span className="text-xs text-gray-500">الكمية: <strong>{reservation.quantity_requested}</strong></span>
        <div className="flex items-center gap-2">
          {reservation.image_url && (
            <span className="text-gray-400 text-xs" title="يحتوي صورة">🖼️</span>
          )}
          <span className="text-xs text-gray-400">{timeAgo(reservation.created_at)}</span>
        </div>
      </div>

      {/* Quick status buttons */}
      {transitions.length > 0 && (
        <div className="flex gap-1 mt-2 flex-wrap" onClick={e => e.stopPropagation()}>
          {transitions.map(s => {
            const tc = COLUMNS.find(c => c.key === s)
            return (
              <button
                key={s}
                onClick={() => onStatusChange(reservation.id, s)}
                style={{ borderColor: tc?.dot, color: tc?.color }}
                className="text-xs border rounded px-2 py-0.5 hover:opacity-80 transition-opacity bg-white"
              >
                → {tc?.label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Column component ──────────────────────────────────────────────────────────
function KanbanColumn({ col, cards, onStatusChange, onOpen, isCCOrAdmin }) {
  return (
    <div className="flex flex-col" style={{ minWidth: 280, maxWidth: 320, flex: '0 0 290px' }}>
      {/* Column header */}
      <div
        className="flex items-center justify-between px-3 py-2.5 rounded-t-xl font-semibold text-sm sticky top-0 z-10"
        style={{ background: col.bg, color: col.color, borderBottom: `2px solid ${col.dot}` }}
      >
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: col.dot }} />
          {col.label}
        </div>
        <span
          className="text-xs font-bold px-2 py-0.5 rounded-full"
          style={{ background: col.dot + '22', color: col.color }}
        >
          {cards.length}
        </span>
      </div>

      {/* Cards */}
      <div
        className="flex flex-col gap-2 p-2 rounded-b-xl overflow-y-auto"
        style={{ background: col.bg + 'cc', minHeight: 100, maxHeight: 'calc(100vh - 220px)' }}
      >
        {cards.length === 0 && (
          <div className="text-center py-8 text-gray-300 text-xs select-none">لا توجد حجوزات</div>
        )}
        {cards.map(r => (
          <ReservationCard
            key={r.id}
            reservation={r}
            onStatusChange={onStatusChange}
            onOpen={onOpen}
            isCCOrAdmin={isCCOrAdmin}
          />
        ))}
      </div>
    </div>
  )
}

// ── Activity icon map — keys must match model ACTIVITY_TYPES choices ──────────
const ACTIVITY_ICONS = {
  note:               '📝',
  call_made:          '📞',
  customer_replied:   '💬',
  stock_checked:      '🔍',
  status_changed:     '🔄',
  transfer_requested: '🔀',
  transfer_replied:   '↩️',
  item_dispensed:     '✅',
  reminder_sent:      '🔔',
  image_attached:     '🖼️',
  assigned:           '👤',
  mention:            '@',
}

function initials(name) {
  return (name || '؟').split(' ').map(w => w[0]).slice(0, 2).join('')
}

// ── Detail Modal ──────────────────────────────────────────────────────────────
function ReservationModal({ reservation, onClose, onStatusChange, onImageUpload, onRefresh }) {
  const [note, setNote] = useState('')
  const [chatMsg, setChatMsg] = useState('')
  const [chatType, setChatType] = useState('note')   // 'note' | 'call_made' | 'customer_replied'
  const [chatSending, setChatSending] = useState(false)
  const [chatAttachment, setChatAttachment] = useState(null)
  const [voiceFile, setVoiceFile] = useState(null)
  const [printOpen, setPrintOpen] = useState(false)
  const fileRef = useRef()
  const chatFileRef = useRef()
  const chatEndRef = useRef()

  // All hooks before any conditional return (rules of hooks)
  const activities = reservation?.activities || []
  const transitions = reservation ? STATUS_TRANSITIONS[reservation.status] || [] : []

  // Auto-scroll chatter to bottom when activities load
  useEffect(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 80)
  }, [activities.length])

  if (!reservation) return null

  async function sendChat() {
    if (!chatMsg.trim() && !chatAttachment && !voiceFile) return
    setChatSending(true)
    try {
      const fd = new FormData()
      fd.append('activity_type', chatType)
      if (chatMsg.trim()) fd.append('message', chatMsg)
      if (chatAttachment) fd.append('attachment', chatAttachment)
      if (voiceFile) fd.append('voice_note', voiceFile)
      await reservationsApi.logActivity(reservation.id, fd)
      setChatMsg('')
      setChatAttachment(null)
      setVoiceFile(null)
      onRefresh?.()
    } catch { /* silent */ } finally { setChatSending(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Print modal — rendered outside the blurred backdrop so it appears on top */}
      {printOpen && (
        <PrintReceiptModal
          type="reservation"
          docId={reservation.id}
          onClose={() => setPrintOpen(false)}
        />
      )}

      {/* Wide 2-column layout: left = info, right = chatter */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl flex flex-col" style={{ maxHeight: '92vh' }}>

        {/* ── Modal header ── */}
        <div className="flex items-center justify-between px-5 py-4 border-b flex-shrink-0">
          <div>
            <h2 className="text-lg font-bold text-gray-900">حجز #{reservation.id}</h2>
            <div className="text-xs text-gray-400 mt-0.5">
              أنشأه: {reservation.created_by_name} — {timeAgo(reservation.created_at)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Print */}
            <button
              onClick={() => setPrintOpen(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
              title="طباعة الإيصال"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
              </svg>
              طباعة
            </button>
            {/* WhatsApp */}
            <WhatsAppShareButton type="reservation" docId={reservation.id} size="sm" />
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none p-1 mr-1">✕</button>
          </div>
        </div>

        {/* ── Body: left info + right chatter ── */}
        <div className="flex flex-1 overflow-hidden min-h-0">

          {/* ── LEFT: reservation details ─────────────────────────── */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4 border-l border-gray-100">

            {/* Item + Customer */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-gray-50 rounded-xl p-3">
                <div className="text-xs text-gray-400 mb-1">الصنف</div>
                <div className="font-semibold text-gray-900 text-sm leading-snug">{reservation.item_name}</div>
                {reservation.item_scientific && (
                  <div className="text-xs text-gray-500 italic mt-0.5">{reservation.item_scientific}</div>
                )}
                <div className="text-xs text-blue-500 font-mono mt-1">كود: {reservation.item_softech_id || '—'}</div>
                <div className="text-xs text-gray-500 mt-1">الكمية: <strong>{reservation.quantity_requested}</strong></div>
                {reservation.item_sale_price != null && (
                  <div className="mt-1.5 inline-flex items-center gap-1 bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-lg text-xs font-bold">
                    💰 {Number(reservation.item_sale_price).toLocaleString('ar-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م
                  </div>
                )}
              </div>
              <div className="bg-gray-50 rounded-xl p-3">
                <div className="text-xs text-gray-400 mb-1">العميل</div>
                <div className="font-semibold text-gray-900 text-sm">{reservation.customer_name}</div>
                <div className="text-xs text-gray-600 font-mono mt-0.5" dir="ltr">{reservation.contact_phone}</div>
                <div className="text-xs text-gray-500 mt-1">الفرع: <strong>{reservation.branch_name}</strong></div>
              </div>
            </div>

            {/* Status + Priority badges */}
            <div className="flex items-center gap-2 flex-wrap">
              {(() => {
                const col = COLUMNS.find(c => c.key === reservation.status)
                return (
                  <span className="text-sm font-semibold px-3 py-1 rounded-full"
                    style={{ background: col?.bg, color: col?.color, border: `1px solid ${col?.dot}` }}>
                    {col?.label}
                  </span>
                )
              })()}
              <span className={`text-xs px-2 py-1 rounded-full font-medium ${PRIORITY_BADGE[reservation.priority]?.cls}`}>
                {PRIORITY_BADGE[reservation.priority]?.label}
              </span>
              {reservation.follow_up_date && (
                <span className="text-xs text-orange-600 bg-orange-50 px-2 py-1 rounded-full">
                  📅 متابعة: {formatDate(reservation.follow_up_date)}
                </span>
              )}
            </div>

            {/* Channel */}
            <div className="flex items-center gap-3">
              <div className="text-xs text-gray-500 font-semibold flex-shrink-0">قناة الطلب:</div>
              <select
                value={reservation.channel || 'pickup'}
                onChange={async e => {
                  try {
                    await reservationsApi.update(reservation.id, { channel: e.target.value })
                    onRefresh()
                  } catch {}
                }}
                className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:border-brand-400 cursor-pointer">
                <option value="pickup">🏪 استلام من الفرع</option>
                <option value="home_delivery">🚚 توصيل للمنزل</option>
                <option value="insurance">🏥 تأمين</option>
                <option value="inquiry">❓ استفسار</option>
              </select>
            </div>

            {/* Notes */}
            {reservation.notes && (
              <div className="bg-yellow-50 border border-yellow-100 rounded-xl p-3">
                <div className="text-xs text-yellow-700 font-medium mb-1">ملاحظات</div>
                <div className="text-sm text-gray-700">{reservation.notes}</div>
              </div>
            )}

            {/* Image */}
            {reservation.image_url && (
              <img src={reservation.image_url} alt="مرفق"
                className="rounded-xl max-h-40 border object-contain w-full cursor-pointer"
                onClick={() => window.open(reservation.image_url, '_blank')} />
            )}

            {/* Upload image */}
            <div>
              <input type="file" accept="image/*" ref={fileRef} className="hidden"
                onChange={e => onImageUpload(reservation.id, e.target.files[0])} />
              <button onClick={() => fileRef.current?.click()}
                className="text-xs text-blue-600 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-50 transition-colors">
                📎 {reservation.image_url ? 'استبدال الصورة' : 'إرفاق صورة / روشتة'}
              </button>
            </div>

            {/* ── Status change ── */}
            {transitions.length > 0 && (
              <div className="border-t border-gray-100 pt-3">
                <div className="text-xs text-gray-500 font-semibold mb-2">تغيير الحالة</div>
                <textarea value={note} onChange={e => setNote(e.target.value)}
                  placeholder="ملاحظة على تغيير الحالة (اختياري)..."
                  rows={2} className="w-full text-sm border border-gray-200 rounded-lg p-2 mb-2 resize-none focus:outline-none focus:border-blue-300" />
                <div className="flex gap-2 flex-wrap">
                  {transitions.map(s => {
                    const tc = COLUMNS.find(c => c.key === s)
                    return (
                      <button key={s}
                        onClick={() => { onStatusChange(reservation.id, s, note); onClose() }}
                        style={{ background: tc?.dot, color: 'white' }}
                        className="text-sm px-4 py-1.5 rounded-lg font-medium hover:opacity-90 transition-opacity">
                        {tc?.label}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Status history (compact) */}
            {reservation.status_logs?.length > 0 && (
              <div className="border-t border-gray-100 pt-3">
                <div className="text-xs text-gray-500 font-semibold mb-2">سجل الحالة</div>
                <div className="space-y-1.5">
                  {reservation.status_logs.map(log => {
                    const nc = COLUMNS.find(c => c.key === log.new_status)
                    return (
                      <div key={log.id} className="flex items-start gap-2 text-xs">
                        <span className="mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0"
                          style={{ background: nc?.dot || '#9ca3af' }} />
                        <div className="text-gray-500">
                          <span className="font-medium text-gray-700">{log.new_status_label}</span>
                          <span className="mx-1">·</span>
                          <span>{log.changed_by_name}</span>
                          <span className="mx-1">·</span>
                          <span className="text-gray-400">{format(new Date(log.changed_at), 'dd/MM HH:mm')}</span>
                          {log.note && <span className="text-gray-400 mr-1">"{log.note}"</span>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* ── RIGHT: Chatter panel ──────────────────────────────── */}
          <div className="w-80 flex-shrink-0 flex flex-col bg-gray-50/50">

            <div className="px-4 py-3 border-b border-gray-100 flex-shrink-0">
              <div className="text-sm font-bold text-gray-700 flex items-center gap-2">
                💬 المحادثة
                {activities.length > 0 && (
                  <span className="text-xs bg-brand-100 text-brand-700 px-1.5 py-0.5 rounded-full font-semibold">
                    {activities.length}
                  </span>
                )}
              </div>
            </div>

            {/* Messages feed */}
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
              {activities.length === 0 && (
                <div className="text-center py-10 text-gray-400">
                  <div className="text-2xl mb-2">💬</div>
                  <div className="text-xs">لا توجد رسائل بعد</div>
                </div>
              )}

              {activities.map(act => {
                const isSystem = act.activity_type === 'status_changed'
                const icon = ACTIVITY_ICONS[act.activity_type] || '📝'

                if (isSystem) return (
                  <div key={act.id} className="flex items-start gap-2">
                    <div className="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center text-xs flex-shrink-0 mt-0.5">
                      {icon}
                    </div>
                    <div className="flex-1">
                      <div className="text-xs text-gray-500 bg-gray-100 rounded-lg px-2.5 py-1.5 leading-relaxed">
                        {act.message}
                      </div>
                      <div className="text-xs text-gray-300 mt-0.5 px-1">{timeAgo(act.created_at)}</div>
                      {act.attachment_url && (
                        <img src={act.attachment_url} alt="مرفق"
                          className="mt-1 rounded-lg max-h-24 object-contain border cursor-pointer"
                          onClick={() => window.open(act.attachment_url, '_blank')} />
                      )}
                    </div>
                  </div>
                )

                return (
                  <div key={act.id} className="flex items-start gap-2">
                    <div className="w-7 h-7 rounded-full bg-brand-600 flex items-center justify-center text-white text-xs font-bold flex-shrink-0 mt-0.5">
                      {initials(act.created_by_name)}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className="text-xs font-semibold text-gray-800">{act.created_by_name}</span>
                        {act.created_by_branch && (
                          <span className="text-xs text-gray-400 bg-gray-100 px-1 py-0.5 rounded">{act.created_by_branch}</span>
                        )}
                        <span className="text-xs mr-auto">{icon}</span>
                      </div>
                      <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-3 py-2 shadow-sm">
                        <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">{act.message}</p>
                      </div>
                      {act.attachment_url && (
                        <img src={act.attachment_url} alt="مرفق"
                          className="mt-1.5 rounded-lg max-h-32 object-contain border cursor-pointer w-full"
                          onClick={() => window.open(act.attachment_url, '_blank')} />
                      )}
                      {act.voice_note_url && (
                        <div className="mt-1.5">
                          <div className="flex items-center gap-1 text-xs text-gray-400 mb-1">
                            <span>🎙️</span><span>ملاحظة صوتية</span>
                          </div>
                          <audio
                            src={act.voice_note_url}
                            controls
                            className="w-full h-8"
                            style={{ direction: 'ltr' }}
                          />
                        </div>
                      )}
                      <div className="text-xs text-gray-300 mt-0.5 px-1">{timeAgo(act.created_at)}</div>
                    </div>
                  </div>
                )
              })}
              <div ref={chatEndRef} />
            </div>

            {/* ── Compose ── */}
            <div className="px-3 pb-3 pt-2 border-t border-gray-100 flex-shrink-0">
              {/* Type selector */}
              <div className="flex gap-1 mb-1.5">
                {[
                  { v: 'note',      label: '📝 ملاحظة' },
                  { v: 'call_made', label: '📞 مكالمة' },
                  { v: 'customer_replied', label: '💬 رد العميل' },
                ].map(t => (
                  <button key={t.v} onClick={() => setChatType(t.v)}
                    className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors ${
                      chatType === t.v ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}>
                    {t.label}
                  </button>
                ))}
              </div>

              <textarea rows={2} value={chatMsg} onChange={e => setChatMsg(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) sendChat() }}
                placeholder="اكتب ملاحظة أو سجّل مكالمة... (Ctrl+Enter)"
                className="w-full text-xs border border-gray-200 rounded-lg p-2 resize-none focus:outline-none focus:border-brand-300 bg-white placeholder-gray-300" />

              {/* Voice recorder */}
              <VoiceNoteRecorder
                onRecorded={f => setVoiceFile(f)}
                onClear={() => setVoiceFile(null)}
                disabled={chatSending}
                maxSeconds={120}
              />

              {chatAttachment && (
                <div className="text-xs text-green-600 mt-1 flex items-center gap-1">
                  <span>📎 {chatAttachment.name}</span>
                  <button onClick={() => setChatAttachment(null)} className="text-gray-400 hover:text-red-400">✕</button>
                </div>
              )}

              <div className="flex items-center justify-between mt-1.5">
                <div>
                  <input type="file" accept="image/*" ref={chatFileRef} className="hidden"
                    onChange={e => setChatAttachment(e.target.files[0])} />
                  <button onClick={() => chatFileRef.current?.click()}
                    className="text-xs text-gray-400 hover:text-blue-500 transition-colors">
                    📎 صورة
                  </button>
                </div>
                <button onClick={sendChat} disabled={chatSending || (!chatMsg.trim() && !chatAttachment && !voiceFile)}
                  className="text-xs bg-brand-600 text-white px-3 py-1 rounded-lg disabled:opacity-40 hover:bg-brand-700 transition-colors font-medium">
                  {chatSending ? '...' : 'إرسال'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Item Stock Panel ──────────────────────────────────────────────────────────
function ItemStockPanel({ stocks, branchId }) {
  const [expanded, setExpanded] = useState(false)

  // Find selected-branch entry
  const branchEntry = branchId ? stocks.find(s => s.branch === branchId) : null
  const networkTotal = stocks.reduce((sum, s) => sum + (s.quantity_on_hand || 0), 0)
  const branchesWithStock = stocks.filter(s => s.quantity_on_hand > 0)

  const STATUS = {
    in_stock:     { icon: '✓', label: 'متوفر',          cls: 'border-green-200  bg-green-50  text-green-700' },
    low:          { icon: '⚠', label: 'مخزون منخفض',   cls: 'border-amber-200  bg-amber-50  text-amber-700' },
    out_of_stock: { icon: '✗', label: 'غير متوفر',       cls: 'border-red-200    bg-red-50    text-red-700'   },
  }
  const QTY_CLR = { in_stock: 'text-green-600', low: 'text-amber-600', out_of_stock: 'text-red-500' }

  if (stocks.length === 0) {
    return (
      <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500 flex items-center gap-1.5">
        <span>📦</span>
        <span>لا توجد بيانات مخزون لهذا الصنف — لم تتم المزامنة بعد.</span>
      </div>
    )
  }

  return (
    <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 space-y-1.5 text-xs" dir="rtl">

      {/* ── Selected-branch row ───────────────────────────────── */}
      {branchId ? (
        branchEntry ? (
          <div className={`flex items-center justify-between rounded-md px-2.5 py-1.5 border font-medium ${STATUS[branchEntry.stock_status]?.cls || 'border-gray-200 bg-white text-gray-700'}`}>
            <span className="flex items-center gap-1">
              <span>{STATUS[branchEntry.stock_status]?.icon || '·'}</span>
              <span>{STATUS[branchEntry.stock_status]?.label || branchEntry.stock_status_label}</span>
              <span className="text-xs opacity-75 font-normal">في هذا الفرع</span>
            </span>
            <span className="font-bold text-sm">
              {branchEntry.quantity_on_hand % 1 === 0
                ? branchEntry.quantity_on_hand.toFixed(0)
                : branchEntry.quantity_on_hand.toFixed(1)
              } <span className="text-xs font-normal opacity-75">وحدة</span>
            </span>
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-md px-2.5 py-1.5 border border-red-200 bg-red-50 text-red-700 font-medium">
            <span className="flex items-center gap-1">
              <span>✗</span>
              <span>غير موجود في مخزون هذا الفرع</span>
            </span>
            <span className="font-bold">صفر</span>
          </div>
        )
      ) : null}

      {/* ── Network total ─────────────────────────────────────── */}
      <div className="flex items-center justify-between text-gray-500 px-1">
        <span>
          إجمالي الشبكة
          {branchesWithStock.length > 0 && (
            <span className="text-gray-400 mr-1">({branchesWithStock.length} فرع)</span>
          )}
        </span>
        <span className={`font-semibold ${networkTotal > 0 ? 'text-gray-700' : 'text-red-500'}`}>
          {networkTotal % 1 === 0 ? networkTotal.toFixed(0) : networkTotal.toFixed(1)} وحدة
        </span>
      </div>

      {/* ── Branch breakdown (collapsible) ────────────────────── */}
      {stocks.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setExpanded(e => !e)}
            className="flex items-center gap-1 text-blue-600 hover:text-blue-800 transition-colors text-xs px-1"
          >
            <span>{expanded ? '▲' : '▼'}</span>
            <span>{expanded ? 'إخفاء تفاصيل الفروع' : `توزيع المخزون على ${stocks.length} فرع`}</span>
          </button>

          {expanded && (
            <div className="border border-gray-200 rounded-md overflow-hidden">
              {[...stocks]
                .sort((a, b) => b.quantity_on_hand - a.quantity_on_hand)
                .map(s => (
                  <div
                    key={s.id}
                    className={`flex items-center justify-between px-2.5 py-1 text-xs border-b border-gray-100 last:border-0 ${
                      s.branch === branchId ? 'bg-blue-50 font-semibold' : 'bg-white'
                    }`}
                  >
                    <span className={s.branch === branchId ? 'text-blue-700' : 'text-gray-600'}>
                      {s.branch === branchId && '→ '}
                      {s.branch_name_ar || s.branch_name}
                    </span>
                    <span className={`font-medium tabular-nums ${QTY_CLR[s.stock_status] || 'text-gray-600'}`}>
                      {s.quantity_on_hand % 1 === 0
                        ? s.quantity_on_hand.toFixed(0)
                        : s.quantity_on_hand.toFixed(1)}
                    </span>
                  </div>
                ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}


// ── New Reservation Modal ─────────────────────────────────────────────────────
function NewReservationModal({ onClose, onCreated, branches, userBranchId, isCCOrAdmin }) {
  const [form, setForm] = useState({
    customer_search: '', customer: '',
    item_search: '', item: '', manual_item_name: '',
    branch: userBranchId || '',
    priority: 'normal', quantity_requested: 1,
    contact_phone: '', contact_name: '', notes: '',
    follow_up_date: '', expected_arrival_date: '',
  })
  const [customerResults, setCustomerResults] = useState([])
  const [itemResults, setItemResults] = useState([])
  const [itemSearchDone, setItemSearchDone] = useState(false)    // true after first search completes
  const [selectedItemStock, setSelectedItemStock] = useState(null) // null = not loaded yet
  const [stockLoading, setStockLoading] = useState(false)
  const [image, setImage] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef()

  // Customer search — fetch up to 20 then deduplicate by phone so the same person
  // registered in multiple SOFTECH branches (old 2-digit + new 3-digit PIC) shows once.
  useEffect(() => {
    if (form.customer_search.length < 2) { setCustomerResults([]); return }
    const t = setTimeout(async () => {
      try {
        const { default: api } = await import('../api/client')
        const res = await api.get('/customers/', { params: { search: form.customer_search, limit: 20 } })
        const raw = res.data.results || res.data
        // One entry per phone number. Prefer the record that has a softech_pic.
        const seen = new Map()
        for (const c of raw) {
          const key = c.phone ? c.phone : `__nophone_${c.id}`
          if (!seen.has(key)) {
            seen.set(key, c)
          } else if (!seen.get(key).softech_pic && c.softech_pic) {
            seen.set(key, c)
          }
        }
        setCustomerResults(Array.from(seen.values()).slice(0, 8))
      } catch { setCustomerResults([]) }
    }, 300)
    return () => clearTimeout(t)
  }, [form.customer_search])

  // Item search
  useEffect(() => {
    if (form.item_search.length < 2) {
      setItemResults([])
      setItemSearchDone(false)
      return
    }
    setItemSearchDone(false)
    const t = setTimeout(async () => {
      try {
        const { default: api } = await import('../api/client')
        const res = await api.get('/items/', { params: { search: form.item_search, limit: 8 } })
        setItemResults(res.data.results || res.data)
      } catch { setItemResults([]) }
      finally { setItemSearchDone(true) }
    }, 300)
    return () => clearTimeout(t)
  }, [form.item_search])

  // Stock fetch — runs whenever an item is selected (branch change only re-renders, no refetch needed
  // since the full list is already loaded and we just filter in <ItemStockPanel>)
  useEffect(() => {
    if (!form.item) { setSelectedItemStock(null); return }
    setStockLoading(true)
    itemsApi.stock(form.item)
      .then(res => setSelectedItemStock(res.data))
      .catch(() => setSelectedItemStock([]))
      .finally(() => setStockLoading(false))
  }, [form.item])
  // Note: branch change just passes a different branchId prop to ItemStockPanel,
  // which re-renders immediately with the already-loaded stock data.

  const handleSubmit = async () => {
    // item required — either from catalog search OR typed manually
    if (!form.item && !form.manual_item_name.trim()) {
      setError('يرجى تحديد صنف من نتائج البحث أو إدخال اسمه يدوياً'); return
    }
    if (!form.branch || !form.contact_phone || !form.contact_name) {
      setError('يرجى تعبئة: الفرع، اسم التواصل، ورقم الهاتف'); return
    }
    setSubmitting(true); setError('')
    try {
      const fd = new FormData()
      Object.entries(form).forEach(([k, v]) => {
        if (!['customer_search','item_search'].includes(k) && v !== '') fd.append(k, v)
      })
      if (image) fd.append('image', image)
      const { default: api } = await import('../api/client')
      await api.post('/reservations/', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      onCreated()
      onClose()
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ، يرجى المحاولة مجدداً')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-bold text-gray-900">حجز جديد</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">✕</button>
        </div>
        <div className="p-5 space-y-4">

          {/* Customer search */}
          <div className="relative">
            <label className="text-xs text-gray-500 mb-1 block">
              العميل
              <span className="text-gray-400 font-normal mr-1">(اختياري — ابحث لربط بعميل موجود)</span>
            </label>
            <input
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
              placeholder="ابحث بالاسم أو الهاتف أو كود PIC (مثال: 01HD14)..."
              value={form.customer_search}
              onChange={e => setForm(f => ({ ...f, customer_search: e.target.value, customer: '' }))}
            />
            {form.customer && <div className="text-xs text-green-600 mt-1">✓ تم الاختيار</div>}
            {!form.customer && form.customer_search === '' && (
              <div className="text-xs text-gray-400 mt-1">زبون مباشر (بدون ربط بقاعدة العملاء)</div>
            )}
            {customerResults.length > 0 && !form.customer && (
              <div className="absolute z-20 w-full bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-52 overflow-y-auto">
                {customerResults.map(c => (
                  <div
                    key={c.id}
                    className="px-3 py-2.5 hover:bg-blue-50 cursor-pointer text-sm border-b border-gray-50 last:border-0"
                    onClick={() => {
                      setForm(f => ({ ...f, customer: c.id, customer_search: c.name, contact_phone: c.phone || f.contact_phone, contact_name: c.name }))
                      setCustomerResults([])
                    }}
                  >
                    <div className="font-medium text-gray-900">{c.name}</div>
                    <div className="flex items-center gap-2 mt-0.5" dir="ltr">
                      {c.phone && (
                        <span className="text-xs text-gray-500">{c.phone}</span>
                      )}
                      {c.softech_pic && (
                        <span className="text-xs font-mono bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded">
                          {c.softech_pic}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Item search */}
          <div className="relative">
            <label className="text-xs text-gray-500 mb-1 block">الصنف *</label>
            <input
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
              placeholder="ابحث باسم الدواء أو الكود..."
              value={form.item_search}
              onChange={e => setForm(f => ({
                ...f,
                item_search: e.target.value,
                item: '',
              }))}
            />
            {form.item && <div className="text-xs text-green-600 mt-1">✓ تم الاختيار</div>}

            {/* Search results dropdown */}
            {itemResults.length > 0 && !form.item && (
              <div className="absolute z-20 w-full bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto">
                {itemResults.map(it => (
                  <div
                    key={it.id}
                    className="px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                    onClick={() => {
                      setForm(f => ({ ...f, item: it.id, item_search: it.name, manual_item_name: '' }))
                      setItemResults([])
                      setItemSearchDone(false)
                    }}
                  >
                    <div className="font-medium">{it.name}</div>
                    <div className="text-xs text-gray-400 font-mono">كود: {it.softech_id}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Item not found → manual entry panel */}
            {!form.item && itemSearchDone && itemResults.length === 0 && form.item_search.length >= 2 && (
              <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs space-y-2" dir="rtl">
                <div className="flex items-start gap-2">
                  <span className="text-amber-500 text-sm leading-none mt-0.5 flex-shrink-0">⚠</span>
                  <div>
                    <div className="font-semibold text-amber-800">الصنف غير موجود في النظام</div>
                    <div className="text-amber-700 mt-0.5 leading-relaxed">
                      لم يُضَف هذا الصنف في SOFTECH أو لم تتم مزامنته بعد.
                      يمكنك تسجيل الحجز بإدخال الاسم يدوياً — سيظهر كـ
                      <span className="font-semibold"> «صنف غير مكوَّد» </span>
                      حتى تتم إضافته لاحقاً.
                    </div>
                  </div>
                </div>
                <div>
                  <label className="block text-amber-800 font-semibold mb-1">
                    اسم الصنف يدوياً <span className="text-red-500">*</span>
                  </label>
                  <input
                    className="w-full border border-amber-300 focus:border-amber-500 rounded-lg px-3 py-2 text-sm bg-white text-gray-800 focus:outline-none"
                    placeholder={form.item_search}
                    value={form.manual_item_name}
                    onChange={e => setForm(f => ({ ...f, manual_item_name: e.target.value }))}
                    autoFocus
                  />
                  {form.manual_item_name.trim() && (
                    <div className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                      <span className="text-green-600 font-bold">✓</span>
                      سيُحجز باسم: <span className="font-semibold text-gray-800 mr-1">{form.manual_item_name}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Stock levels after item is selected */}
            {form.item && (
              stockLoading
                ? (
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-400">
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border border-gray-300 border-t-blue-500" />
                    جارٍ تحميل بيانات المخزون...
                  </div>
                )
                : selectedItemStock !== null && (
                  <ItemStockPanel
                    stocks={selectedItemStock}
                    branchId={form.branch ? parseInt(form.branch, 10) : null}
                  />
                )
            )}
          </div>

          {/* Branch (CC/admin only can choose) */}
          {isCCOrAdmin && (
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الفرع *</label>
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.branch}
                onChange={e => setForm(f => ({ ...f, branch: e.target.value }))}
              >
                <option value="">اختر الفرع</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
              </select>
            </div>
          )}

          {/* Contact fields */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">اسم التواصل *</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.contact_name} onChange={e => setForm(f => ({ ...f, contact_name: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">هاتف التواصل *</label>
              <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                dir="ltr" value={form.contact_phone} onChange={e => setForm(f => ({ ...f, contact_phone: e.target.value }))} />
            </div>
          </div>

          {/* Priority + Qty */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الأولوية</label>
              <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
                <option value="normal">عادي</option>
                <option value="urgent">عاجل</option>
                <option value="chronic">مريض مزمن</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الكمية</label>
              <input type="number" min="1" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.quantity_requested} onChange={e => setForm(f => ({ ...f, quantity_requested: e.target.value }))} />
            </div>
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">تاريخ المتابعة</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.follow_up_date} onChange={e => setForm(f => ({ ...f, follow_up_date: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">موعد الوصول المتوقع</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300"
                value={form.expected_arrival_date} onChange={e => setForm(f => ({ ...f, expected_arrival_date: e.target.value }))} />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="text-xs text-gray-500 mb-1 block">ملاحظات</label>
            <textarea rows={2} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-300 resize-none"
              value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
          </div>

          {/* Image */}
          <div>
            <input type="file" accept="image/*" ref={fileRef} className="hidden" onChange={e => setImage(e.target.files[0])} />
            <button onClick={() => fileRef.current?.click()}
              className="text-xs text-blue-600 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-50 transition-colors">
              📎 {image ? `✓ ${image.name}` : 'إرفاق صورة / روشتة (اختياري)'}
            </button>
          </div>

          {error && <div className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</div>}

          <div className="flex gap-2 pt-1">
            <button onClick={handleSubmit} disabled={submitting}
              className="flex-1 bg-brand-600 text-white rounded-lg py-2.5 text-sm font-semibold hover:bg-brand-700 disabled:opacity-50 transition-colors">
              {submitting ? 'جاري الحفظ...' : 'إنشاء الحجز'}
            </button>
            <button onClick={onClose} className="px-4 py-2.5 border border-gray-200 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors">
              إلغاء
            </button>
         </div>
        </div>
      </div>
    </div>
  )
}

// ── List View ─────────────────────────────────────────────────────────────────
function ReservationListView({ reservations, onOpen, isCCOrAdmin }) {
  const [sortKey, setSortKey] = useState('created_at')
  const [sortDir, setSortDir] = useState('desc')

  const toggleSort = key => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = [...reservations].sort((a, b) => {
    let va = a[sortKey] ?? ''
    let vb = b[sortKey] ?? ''
    if (typeof va === 'string') va = va.toLowerCase()
    if (typeof vb === 'string') vb = vb.toLowerCase()
    if (va < vb) return sortDir === 'asc' ? -1 : 1
    if (va > vb) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  const SortIcon = ({ k }) => sortKey === k
    ? <span className="text-brand-500 mr-0.5">{sortDir === 'asc' ? '↑' : '↓'}</span>
    : <span className="text-gray-300 mr-0.5">↕</span>

  const Th = ({ k, children, cls = '' }) => (
    <th
      className={`px-3 py-2.5 text-right text-xs font-semibold text-gray-500 whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none ${cls}`}
      onClick={() => toggleSort(k)}
    >
      {children}<SortIcon k={k} />
    </th>
  )

  if (sorted.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm py-16">
        لا توجد حجوزات حسب الفلاتر المحددة.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto" dir="rtl">
      <table className="w-full text-sm border-collapse">
        <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
          <tr>
            <Th k="id">#</Th>
            <Th k="item_name">الصنف</Th>
            <Th k="customer_name">العميل</Th>
            <Th k="contact_phone">الهاتف</Th>
            {isCCOrAdmin && <Th k="branch_name">الفرع</Th>}
            <Th k="status">الحالة</Th>
            <Th k="priority">الأولوية</Th>
            <Th k="quantity_requested" cls="w-16">الكمية</Th>
            <Th k="follow_up_date">المتابعة</Th>
            <Th k="created_at">تاريخ الإنشاء</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => {
            const col = COLUMNS.find(c => c.key === r.status) || COLUMNS[0]
            const pri = PRIORITY_BADGE[r.priority] || PRIORITY_BADGE.normal
            return (
              <tr
                key={r.id}
                className="hover:bg-blue-50/40 cursor-pointer transition-colors"
                onClick={() => onOpen(r)}
              >
                <td className="px-3 py-2.5 text-gray-400 font-mono text-xs">#{r.id}</td>
                <td className="px-3 py-2.5 max-w-[200px]">
                  <div className="font-medium text-gray-900 truncate">{r.item_name}</div>
                  {r.item_softech_id && (
                    <div className="text-xs text-gray-400 font-mono">كود: {r.item_softech_id}</div>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <div className="text-gray-800 truncate max-w-[140px]">{r.customer_name}</div>
                </td>
                <td className="px-3 py-2.5 text-xs font-mono text-gray-600" dir="ltr">{r.contact_phone}</td>
                {isCCOrAdmin && (
                  <td className="px-3 py-2.5 text-xs text-brand-700 bg-brand-50/30">
                    {r.branch_name}
                  </td>
                )}
                <td className="px-3 py-2.5">
                  <span
                    className="text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
                    style={{ background: col.bg, color: col.color, border: `1px solid ${col.dot}` }}
                  >
                    {col.label}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${pri.cls}`}>
                    {pri.label}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-center text-gray-700 font-medium">{r.quantity_requested}</td>
                <td className="px-3 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                  {r.follow_up_date
                    ? <span className="text-orange-600">{formatDate(r.follow_up_date)}</span>
                    : <span className="text-gray-300">—</span>}
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-400 whitespace-nowrap">{timeAgo(r.created_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


// ── Main Kanban Page ──────────────────────────────────────────────────────────
export default function ReservationsKanban() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const isCCOrAdmin = user?.role === 'admin' || user?.role === 'call_center'

  const [viewMode, setViewMode] = useState('kanban')   // 'kanban' | 'list'
  const [filterBranch, setFilterBranch] = useState('')
  const [filterPriority, setFilterPriority] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [openModal, setOpenModal] = useState(null)   // reservation object
  const [showNew, setShowNew] = useState(false)
  const [detailData, setDetailData] = useState(null)

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      // API returns paginated {results:[]} or plain []
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
  })

  const reservationsQuery = useQuery({
    queryKey: ['reservations-kanban', filterBranch, filterPriority, filterStatus, search, dateFrom, dateTo],
    queryFn: () => reservationsApi.list({
      branch:    filterBranch    || undefined,
      priority:  filterPriority  || undefined,
      status:    filterStatus    || undefined,
      search:    search          || undefined,
      date_from: dateFrom        || undefined,
      date_to:   dateTo          || undefined,
      page_size: 500,
    }).then(r => r.data.results || r.data),
    refetchInterval: 30_000,
  })
 
  const rawList = reservationsQuery.data
  const reservationsList = Array.isArray(rawList) ? rawList : []
  const hasData = reservationsList.length > 0
  const isLoading = reservationsQuery.isLoading
  const reservationsError = reservationsQuery.error

  // Status change mutation
  const changeMutation = useMutation({
    mutationFn: ({ id, status, note }) => reservationsApi.changeStatus(id, status, note || ''),
    onSuccess: () => {
      qc.invalidateQueries(['reservations-kanban'])
      if (detailData) {
        reservationsApi.get(detailData.id).then(r => setDetailData(r.data))
      }
    },
  })

  // Image upload mutation
  const imageMutation = useMutation({
    mutationFn: async ({ id, file }) => {
      const fd = new FormData(); fd.append('image', file)
      const { default: api } = await import('../api/client')
      return api.patch(`/reservations/${id}/`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    },
    onSuccess: () => qc.invalidateQueries(['reservations-kanban']),
  })

  // Open detail: fetch full data
  const openDetail = async (r) => {
    try {
      const res = await reservationsApi.get(r.id)
      setDetailData(res.data)
      setOpenModal(r)
    } catch { setOpenModal(r); setDetailData(r) }
  }


  // Group by status, applying filters
  const grouped = COLUMNS.reduce((acc, col) => {
    acc[col.key] = reservationsList.filter(r => {
      if (r.status !== col.key) return false
      if (!isCCOrAdmin && r.branch_id !== user?.branch_id) return false
      return true
    })
    return acc
  }, {})

  // Merged cancelled + expired
  grouped.cancelled = [
    ...(reservationsList.filter(r => r.status === 'cancelled')),
    ...(reservationsList.filter(r => r.status === 'expired')),
  ]

  const totalActive = reservationsList.filter(r => !['fulfilled','cancelled','expired'].includes(r.status)).length


  return (
    <div className="flex flex-col h-full" dir="rtl">

      {/* Top bar */}
      <div className="bg-white border-b">
        {/* Row 1: title + view toggle + new button */}
        <div className="flex items-center gap-3 px-5 py-2.5 flex-wrap">
          <div>
            <h1 className="text-lg font-bold text-gray-900">لوحة الحجوزات</h1>
            <p className="text-xs text-gray-400">{totalActive} حجز نشط · {reservationsList.length} إجمالي</p>
          </div>

          <div className="flex-1" />

          {/* View mode toggle */}
          <div className="flex items-center rounded-lg border border-gray-200 overflow-hidden text-sm">
            <button
              onClick={() => setViewMode('kanban')}
              className={`px-3 py-1.5 transition-colors ${viewMode === 'kanban' ? 'bg-brand-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              title="عرض كانبان"
            >
              ⬛ كانبان
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`px-3 py-1.5 border-r border-gray-200 transition-colors ${viewMode === 'list' ? 'bg-brand-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
              title="عرض قائمة"
            >
              ☰ قائمة
            </button>
          </div>

          <button
            onClick={() => setShowNew(true)}
            className="bg-brand-600 text-white px-4 py-1.5 rounded-lg text-sm font-semibold hover:bg-brand-700 transition-colors whitespace-nowrap"
          >
            + حجز جديد
          </button>
        </div>

        {/* Row 2: filters */}
        <div className="flex items-center gap-2 px-5 pb-2.5 flex-wrap">
          {/* Search */}
          <input
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-44 focus:outline-none focus:border-blue-300"
            placeholder="بحث..."
            aria-label="بحث في الحجوزات"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          {/* Branch filter (CC/admin only) */}
          {isCCOrAdmin && (
            <select
              aria-label="تصفية حسب الفرع"
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
              value={filterBranch}
              onChange={e => setFilterBranch(e.target.value)}
            >
              <option value="">كل الفروع</option>
              {branches.map(b => (
                <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
              ))}
            </select>
          )}

          {/* Priority filter */}
          <select
            aria-label="تصفية حسب الأولوية"
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
            value={filterPriority}
            onChange={e => setFilterPriority(e.target.value)}
          >
            <option value="">كل الأولويات</option>
            <option value="urgent">عاجل</option>
            <option value="chronic">مزمن</option>
            <option value="normal">عادي</option>
          </select>

          {/* Status filter (more useful in list mode) */}
          <select
            aria-label="تصفية حسب الحالة"
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-blue-300"
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
          >
            <option value="">كل الحالات</option>
            {COLUMNS.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>

          {/* Date range */}
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <span>من</span>
            <input
              type="date"
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-blue-300"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
            />
            <span>إلى</span>
            <input
              type="date"
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-blue-300"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
            />
            {(dateFrom || dateTo) && (
              <button
                onClick={() => { setDateFrom(''); setDateTo('') }}
                className="text-gray-400 hover:text-gray-600 transition-colors text-base leading-none"
                title="مسح التواريخ"
              >✕</button>
            )}
          </div>
        </div>
      </div>

      {/* Content area */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm" role="status" aria-live="polite">
          جاري تحميل الحجوزات...
        </div>
      ) : reservationsError ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-sm">
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3">حدث خطأ أثناء تحميل الحجوزات.</div>
          <button className="px-3 py-1.5 rounded-lg border border-red-300 text-red-700 hover:bg-red-50" onClick={() => reservationsQuery.refetch()}>
            إعادة المحاولة
          </button>
        </div>
      ) : viewMode === 'list' ? (
        <ReservationListView
          reservations={reservationsList}
          onOpen={openDetail}
          isCCOrAdmin={isCCOrAdmin}
        />
      ) : (
        /* Kanban board */
        <div className="flex-1 overflow-x-auto">
          <div className="flex gap-3 p-4 h-full" style={{ width: 'max-content', minWidth: '100%' }}>
            {!hasData ? (
              <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
                لا توجد حجوزات حالياً حسب الفلاتر المحددة.
              </div>
            ) : (
              COLUMNS.map(col => (
                <KanbanColumn
                  key={col.key}
                  col={col}
                  cards={grouped[col.key] || []}
                  onStatusChange={(id, status, note) => changeMutation.mutate({ id, status, note })}
                  onOpen={openDetail}
                  isCCOrAdmin={isCCOrAdmin}
                />
              ))
            )}
          </div>
        </div>
      )}

      {/* Detail modal */}
      {openModal && (
        <ReservationModal
          reservation={detailData || openModal}
          onClose={() => { setOpenModal(null); setDetailData(null) }}
          onStatusChange={(id, status, note) => changeMutation.mutate({ id, status, note })}
          onImageUpload={(id, file) => imageMutation.mutate({ id, file })}
          onRefresh={() => openModal && reservationsApi.get(openModal.id).then(r => setDetailData(r.data))}
        />
      )}

      {/* New reservation modal */}
      {showNew && (
        <NewReservationModal
          onClose={() => setShowNew(false)}
          onCreated={() => qc.invalidateQueries(['reservations-kanban'])}
          branches={branches}
          userBranchId={user?.branch_id}
          isCCOrAdmin={isCCOrAdmin}
        />
      )}
    </div>
  )
}
