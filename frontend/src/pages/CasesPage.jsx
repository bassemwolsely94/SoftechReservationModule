/**
 * CasesPage.jsx  —  /callcenter/cases
 * Customer Case Management: list, filter, state machine, CSAT, case notes
 */
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { callCenterApi, customersApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s =>
  s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_META = {
  open:      { label: '🆕 مفتوحة',       cls: 'bg-blue-100 text-blue-800'    },
  working:   { label: '⚙️ قيد المعالجة', cls: 'bg-indigo-100 text-indigo-800'},
  waiting:   { label: '⏳ انتظار',        cls: 'bg-yellow-100 text-yellow-800'},
  escalated: { label: '🔴 مُصعَّدة',      cls: 'bg-red-100 text-red-800'      },
  resolved:  { label: '✅ محلولة',        cls: 'bg-green-100 text-green-800'  },
  closed:    { label: '🔒 مغلقة',         cls: 'bg-gray-100 text-gray-700'    },
}

const PRIORITY_META = {
  low:    { label: 'منخفضة',  cls: 'text-gray-500' },
  normal: { label: 'عادية',   cls: 'text-blue-600' },
  high:   { label: 'مرتفعة', cls: 'text-orange-600' },
  urgent: { label: 'عاجلة 🔴', cls: 'text-red-600 font-bold' },
}

const CATEGORY_OPTIONS = [
  { value: '', label: 'كل التصنيفات' },
  { value: 'complaint',  label: '⚠️ شكوى' },
  { value: 'inquiry',    label: '❓ استفسار' },
  { value: 'request',    label: '📋 طلب' },
  { value: 'lost_sale',  label: '❌ بيعة مفقودة' },
  { value: 'delivery',   label: '🚚 توصيل' },
  { value: 'support',    label: '🛠️ دعم' },
  { value: 'refund',     label: '↩️ إرجاع/استبدال' },
  { value: 'other',      label: '💬 أخرى' },
]

const STATUS_OPTIONS = [
  { value: '',         label: 'كل الحالات' },
  { value: 'open',     label: '🆕 مفتوحة' },
  { value: 'working',  label: '⚙️ قيد المعالجة' },
  { value: 'waiting',  label: '⏳ انتظار' },
  { value: 'escalated',label: '🔴 مُصعَّدة' },
  { value: 'resolved', label: '✅ محلولة' },
  { value: 'closed',   label: '🔒 مغلقة' },
]

// ─── CaseDetail Panel ────────────────────────────────────────────────────────

function CaseDetailPanel({ caseId, onClose, onStateChange }) {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [noteText, setNoteText]       = useState('')
  const [resolveText, setResolveText] = useState('')
  const [showResolve, setShowResolve] = useState(false)
  const [csatScore, setCsatScore]     = useState('')
  // Attachments
  const [attachFile, setAttachFile]   = useState(null)
  const [attachType, setAttachType]   = useState('image')
  // Voice recorder
  const [recording, setRecording]     = useState(false)
  const [recorderReady, setRecorderReady] = useState(false)
  const mediaRecRef  = useRef(null)
  const chunksRef    = useRef([])
  // @mention
  const [mentionQ, setMentionQ]       = useState('')  // text after '@'
  const [showMention, setShowMention] = useState(false)
  const noteRef = useRef(null)
  const [posting, setPosting]         = useState(false)

  const { data: cas, isLoading } = useQuery({
    queryKey: ['case-detail', caseId],
    queryFn:  () => callCenterApi.cases.get(caseId).then(r => r.data),
    staleTime: 10_000,
  })

  const { data: agentsData } = useQuery({
    queryKey: ['cc-agents'],
    queryFn:  () => callCenterApi.agents().then(r => r.data),
    staleTime: 300_000,
    enabled: showMention,
  })

  const agents = agentsData || []
  const filteredAgents = mentionQ
    ? agents.filter(a =>
        a.username.toLowerCase().includes(mentionQ.toLowerCase()) ||
        a.name.toLowerCase().includes(mentionQ.toLowerCase())
      )
    : agents

  // ── Mention handling ─────────────────────────────────────────────────────────
  function handleNoteChange(e) {
    const val = e.target.value
    setNoteText(val)
    const lastAt = val.lastIndexOf('@')
    if (lastAt >= 0 && lastAt === val.length - 1) {
      setMentionQ('')
      setShowMention(true)
    } else if (lastAt >= 0 && !val.slice(lastAt).includes(' ')) {
      setMentionQ(val.slice(lastAt + 1))
      setShowMention(true)
    } else {
      setShowMention(false)
      setMentionQ('')
    }
  }

  function insertMention(username) {
    const lastAt = noteText.lastIndexOf('@')
    const newText = noteText.slice(0, lastAt) + '@' + username + ' '
    setNoteText(newText)
    setShowMention(false)
    setMentionQ('')
    noteRef.current?.focus()
  }

  // ── Voice recorder ───────────────────────────────────────────────────────────
  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        const file = new File([blob], `voice_${Date.now()}.webm`, { type: 'audio/webm' })
        setAttachFile(file)
        setAttachType('voice')
        stream.getTracks().forEach(t => t.stop())
      }
      mediaRecRef.current = rec
      rec.start()
      setRecording(true)
      setRecorderReady(true)
    } catch {
      alert('لا يمكن الوصول للميكروفون')
    }
  }

  function stopRecording() {
    mediaRecRef.current?.stop()
    setRecording(false)
  }

  // ── Post note ────────────────────────────────────────────────────────────────
  async function addNote() {
    if (!noteText.trim() && !attachFile) return
    setPosting(true)
    try {
      let payload
      if (attachFile) {
        payload = new FormData()
        payload.append('message', noteText)
        payload.append('attachment', attachFile, attachFile.name)
        payload.append('attachment_type', attachType)
      } else {
        payload = new FormData()
        payload.append('message', noteText)
      }
      await callCenterApi.cases.addNote(caseId, payload)
      setNoteText('')
      setAttachFile(null)
      setAttachType('image')
      setRecorderReady(false)
      qc.invalidateQueries({ queryKey: ['case-detail', caseId] })
      onStateChange?.()
    } catch (e) {
      alert(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setPosting(false)
    }
  }

  async function doAction(action, body = {}) {
    try {
      await action(caseId, body)
      qc.invalidateQueries({ queryKey: ['case-detail', caseId] })
      qc.invalidateQueries({ queryKey: ['cases-list'] })
      onStateChange?.()
    } catch (e) {
      alert(e.response?.data?.detail || 'حدث خطأ')
    }
  }

  async function resolve() {
    if (!resolveText.trim()) { alert('وصف الحل مطلوب'); return }
    await doAction(callCenterApi.cases.resolve, { resolution: resolveText })
    setShowResolve(false)
    setResolveText('')
  }

  async function submitCsat() {
    if (!csatScore) return
    await doAction(callCenterApi.cases.csat, { score: csatScore })
    setCsatScore('')
  }

  if (isLoading || !cas) return (
    <div className="h-full flex items-center justify-center">
      <div className="text-gray-400 animate-pulse">تحميل...</div>
    </div>
  )

  const sm = STATUS_META[cas.status] || { label: cas.status, cls: 'bg-gray-100' }
  const pm = PRIORITY_META[cas.priority] || {}
  const canEdit = ['admin', 'supervisor', 'call_center', 'quality_manager'].includes(user?.role)

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {/* Panel header */}
      <div className="flex items-start justify-between p-4 border-b border-gray-100">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-gray-400">{cas.case_number}</span>
            <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${sm.cls}`}>{sm.label}</span>
            <span className={`text-xs ${pm.cls}`}>{pm.label}</span>
          </div>
          <div className="font-black text-gray-900 mt-1">{cas.title}</div>
          <div className="text-sm text-gray-500 mt-0.5">
            {cas.customer_name} · {cas.branch_name || '—'}
            {cas.age_hours && ` · منذ ${cas.age_hours}س`}
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">

        {cas.description && (
          <div className="bg-gray-50 rounded-xl p-3 text-sm text-gray-700">{cas.description}</div>
        )}

        {cas.resolution && (
          <div className="bg-green-50 rounded-xl p-3">
            <div className="text-xs font-bold text-green-700 mb-1">✅ الحل</div>
            <div className="text-sm text-green-800">{cas.resolution}</div>
            {cas.root_cause && <div className="text-xs text-green-600 mt-1">السبب الجذري: {cas.root_cause}</div>}
          </div>
        )}

        {cas.csat_score && (
          <div className="bg-yellow-50 rounded-xl p-3 flex items-center gap-2">
            <span className="text-yellow-700 font-bold">تقييم العميل:</span>
            <span className="text-2xl">{'⭐'.repeat(cas.csat_score)}</span>
            {cas.csat_note && <span className="text-xs text-gray-500">{cas.csat_note}</span>}
          </div>
        )}

        {cas.is_sla_breached && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-xs text-red-700 font-bold">
            🔴 تم تجاوز موعد SLA
          </div>
        )}

        {/* Events timeline */}
        <div>
          <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">سجل الأحداث</div>
          <div className="space-y-3">
            {cas.events?.map(ev => (
              <div key={ev.id} className="flex gap-2 text-sm">
                <div className="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center
                  text-xs shrink-0 mt-0.5">
                  {ev.event_type === 'note' ? '📝' : ev.event_type === 'call' ? '📞'
                    : ev.event_type === 'status' ? '🔄' : '⚙️'}
                </div>
                <div className="flex-1 min-w-0">
                  {ev.message && (
                    <div className="text-gray-700 text-sm">
                      {ev.message.split(/(@\w+)/g).map((part, i) =>
                        part.startsWith('@')
                          ? <span key={i} className="text-brand-600 font-semibold">{part}</span>
                          : part
                      )}
                    </div>
                  )}
                  {/* Attachment */}
                  {ev.attachment_url && (
                    <div className="mt-1.5">
                      {ev.attachment_type === 'voice' ? (
                        <audio controls src={ev.attachment_url}
                          className="h-8 w-full max-w-xs" />
                      ) : ev.attachment_type === 'image' ? (
                        <a href={ev.attachment_url} target="_blank" rel="noopener noreferrer">
                          <img src={ev.attachment_url} alt="مرفق"
                            className="max-h-32 rounded-lg border border-gray-200 object-cover" />
                        </a>
                      ) : (
                        <a href={ev.attachment_url} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline
                            bg-gray-50 border border-gray-200 rounded-lg px-2 py-1">
                          📄 فتح المرفق
                        </a>
                      )}
                    </div>
                  )}
                  <div className="text-xs text-gray-400 mt-0.5">
                    {ev.created_by_name || 'نظام'} ·{' '}
                    {ev.created_at
                      ? toLatinDigits(format(new Date(ev.created_at), 'd MMM HH:mm', { locale: ar }))
                      : ''}
                  </div>
                </div>
              </div>
            ))}
            {!cas.events?.length && (
              <div className="text-xs text-gray-400 text-center py-2">لا توجد أحداث</div>
            )}
          </div>
        </div>
      </div>

      {/* Footer actions */}
      {canEdit && (
        <div className="border-t border-gray-100 p-4 space-y-3">

          {/* Attachment preview */}
          {attachFile && (
            <div className="flex items-center gap-2 bg-blue-50 border border-blue-200 rounded-xl px-3 py-2">
              <span className="text-lg">{attachType === 'voice' ? '🎙️' : attachType === 'image' ? '🖼️' : '📄'}</span>
              <span className="text-xs text-blue-800 font-semibold truncate flex-1">{attachFile.name}</span>
              <button onClick={() => { setAttachFile(null); setRecorderReady(false) }}
                className="text-blue-400 hover:text-blue-700 text-xs">✕</button>
            </div>
          )}

          {/* Note input row with @mention */}
          <div className="relative">
            <div className="flex gap-1.5">
              <div className="flex-1 relative">
                <textarea
                  ref={noteRef}
                  rows={2}
                  className="input-field text-sm resize-none w-full"
                  placeholder="أضف ملاحظة... (اكتب @ للذكر)"
                  value={noteText}
                  onChange={handleNoteChange}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey && !showMention) {
                      e.preventDefault(); addNote()
                    }
                    if (e.key === 'Escape') setShowMention(false)
                  }}
                />
                {/* @mention dropdown */}
                {showMention && filteredAgents.length > 0 && (
                  <div className="absolute bottom-full mb-1 right-0 left-0 z-50
                    bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden max-h-48 overflow-y-auto">
                    {filteredAgents.slice(0, 8).map(a => (
                      <button key={a.id}
                        onMouseDown={e => { e.preventDefault(); insertMention(a.username) }}
                        className="w-full text-right px-3 py-2 hover:bg-brand-50 flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-brand-100 flex items-center justify-center
                          text-brand-700 text-xs font-bold shrink-0">
                          {a.name[0]}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-bold text-gray-900 truncate">{a.name}</div>
                          <div className="text-xs text-gray-400">@{a.username}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Attachment + voice buttons */}
              <div className="flex flex-col gap-1">
                {/* Image/file picker */}
                <label className="btn-secondary text-xs px-2 py-1.5 cursor-pointer text-center"
                  title="إرفاق صورة أو مستند">
                  📎
                  <input type="file" className="hidden"
                    accept="image/*,.pdf,.doc,.docx"
                    onChange={e => {
                      const f = e.target.files?.[0]
                      if (!f) return
                      setAttachFile(f)
                      setAttachType(f.type.startsWith('image/') ? 'image' : 'document')
                      e.target.value = ''
                    }} />
                </label>

                {/* Voice recorder */}
                <button
                  onClick={recording ? stopRecording : startRecording}
                  title={recording ? 'إيقاف التسجيل' : 'تسجيل صوتي'}
                  className={`btn-secondary text-xs px-2 py-1.5 ${recording ? 'text-red-600 animate-pulse' : ''}`}>
                  🎙️
                </button>

                {/* Send */}
                <button onClick={addNote}
                  disabled={(!noteText.trim() && !attachFile) || posting}
                  className="btn-primary text-xs px-2 py-1.5 disabled:opacity-40">
                  {posting ? '⏳' : '➤'}
                </button>
              </div>
            </div>
          </div>

          {/* State machine buttons */}
          <div className="flex gap-2 flex-wrap">
            {cas.status === 'open' && (
              <button onClick={() => doAction(callCenterApi.cases.assign, { staff_id: user?.staff_id || user?.id })}
                className="btn-secondary text-xs py-1.5 px-2">
                ⚙️ بدء المعالجة
              </button>
            )}
            {['open','working','waiting'].includes(cas.status) && !showResolve && (
              <button onClick={() => setShowResolve(true)}
                className="btn-secondary text-xs py-1.5 px-2">
                ✅ حل الحالة
              </button>
            )}
            {cas.status === 'resolved' && (
              <button onClick={() => doAction(callCenterApi.cases.close)}
                className="btn-secondary text-xs py-1.5 px-2">
                🔒 إغلاق
              </button>
            )}
            {cas.status === 'resolved' && !cas.csat_score && (
              <div className="flex items-center gap-1">
                <select className="input-field text-xs py-1.5 w-24" value={csatScore}
                  onChange={e => setCsatScore(e.target.value)}>
                  <option value="">CSAT</option>
                  {[1,2,3,4,5].map(n => <option key={n} value={n}>{n} ⭐</option>)}
                </select>
                <button onClick={submitCsat} disabled={!csatScore}
                  className="btn-secondary text-xs py-1.5 px-2 disabled:opacity-40">➤</button>
              </div>
            )}
          </div>

          {showResolve && (
            <div className="space-y-2">
              <textarea rows={2} className="input-field resize-none text-sm"
                placeholder="اشرح طريقة الحل..."
                value={resolveText}
                onChange={e => setResolveText(e.target.value)} />
              <div className="flex gap-2">
                <button onClick={() => setShowResolve(false)} className="btn-secondary text-xs">إلغاء</button>
                <button onClick={resolve} disabled={!resolveText.trim()}
                  className="btn-primary text-xs disabled:opacity-40">✅ تأكيد الحل</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Standalone Case Creation Modal ──────────────────────────────────────────

function StandaloneCaseModal({ onClose, onCreated }) {
  const [phone, setPhone]   = useState('')
  const [customers, setCustomers] = useState([])
  const [selectedCustomer, setSelectedCustomer] = useState(null)
  const [searching, setSearching] = useState(false)
  const [form, setForm] = useState({
    category: 'inquiry', priority: 'normal', title: '', description: '',
  })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function searchCustomer() {
    if (!phone.trim()) return
    setSearching(true); setCustomers([]); setSelectedCustomer(null); setErr('')
    try {
      const { data } = await customersApi.list({ search: phone.trim(), page_size: 8 })
      const list = data?.results || data || []
      setCustomers(list)
      if (list.length === 1) setSelectedCustomer(list[0])
      if (list.length === 0) setErr('لم يتم العثور على عملاء بهذا الرقم أو الاسم')
    } catch { setErr('حدث خطأ أثناء البحث') }
    finally { setSearching(false) }
  }

  async function submit() {
    if (!selectedCustomer) { setErr('اختر العميل أولاً'); return }
    if (!form.title.trim()) { setErr('عنوان الحالة مطلوب'); return }
    setLoading(true); setErr('')
    try {
      const { data } = await callCenterApi.cases.create({
        ...form, customer: selectedCustomer.id,
      })
      onCreated(data)
    } catch (e) {
      setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'حدث خطأ')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-black text-gray-900">🗂️ فتح حالة جديدة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="p-5 space-y-4">

          {/* Customer lookup */}
          <div>
            <label className="label text-xs">بحث عن العميل (رقم هاتف أو اسم)</label>
            <div className="flex gap-2">
              <input className="input-field text-sm flex-1" placeholder="010xxxxxxxx أو اسم العميل..."
                value={phone}
                onChange={e => setPhone(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchCustomer()} />
              <button onClick={searchCustomer} disabled={searching || !phone.trim()}
                className="btn-secondary text-sm disabled:opacity-40">
                {searching ? '⏳' : '🔍'}
              </button>
            </div>
            {customers.length > 1 && (
              <div className="mt-2 space-y-1 max-h-36 overflow-y-auto">
                {customers.map(c => (
                  <button key={c.id}
                    onClick={() => setSelectedCustomer(c)}
                    className={`w-full text-right px-3 py-2 rounded-lg text-sm transition-all
                      ${selectedCustomer?.id === c.id
                        ? 'bg-brand-100 border border-brand-300 text-brand-800'
                        : 'bg-gray-50 hover:bg-gray-100 border border-gray-200 text-gray-700'}`}>
                    <span className="font-semibold">{c.name}</span>
                    <span className="text-gray-400 mr-2 text-xs font-mono">{c.phone}</span>
                  </button>
                ))}
              </div>
            )}
            {selectedCustomer && (
              <div className="mt-2 flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-3 py-2 text-sm">
                <span className="text-green-700 font-bold">✓ {selectedCustomer.name}</span>
                <span className="text-gray-400 text-xs font-mono">{selectedCustomer.phone}</span>
                <button onClick={() => { setSelectedCustomer(null); setCustomers([]) }}
                  className="text-gray-400 hover:text-red-500 mr-auto text-xs">تغيير</button>
              </div>
            )}
          </div>

          {/* Case fields */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label text-xs">التصنيف</label>
              <select className="input-field text-sm" value={form.category}
                onChange={e => setForm(p => ({ ...p, category: e.target.value }))}>
                {[
                  ['complaint','⚠️ شكوى'],['inquiry','❓ استفسار'],['request','📋 طلب'],
                  ['lost_sale','❌ بيعة مفقودة'],['delivery','🚚 توصيل'],
                  ['support','🛠️ دعم'],['refund','↩️ إرجاع'],['other','💬 أخرى'],
                ].map(([v,l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="label text-xs">الأولوية</label>
              <select className="input-field text-sm" value={form.priority}
                onChange={e => setForm(p => ({ ...p, priority: e.target.value }))}>
                <option value="low">منخفضة</option>
                <option value="normal">عادية</option>
                <option value="high">مرتفعة</option>
                <option value="urgent">عاجلة 🔴</option>
              </select>
            </div>
          </div>
          <div>
            <label className="label text-xs">عنوان الحالة *</label>
            <input className="input-field text-sm" placeholder="اكتب عنواناً موجزاً..."
              value={form.title}
              onChange={e => setForm(p => ({ ...p, title: e.target.value }))} />
          </div>
          <div>
            <label className="label text-xs">الوصف</label>
            <textarea rows={3} className="input-field resize-none text-sm"
              value={form.description}
              onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
          </div>

          {err && <p className="text-red-600 text-xs font-semibold">{err}</p>}
        </div>
        <div className="p-5 border-t border-gray-100 flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">إلغاء</button>
          <button onClick={submit} disabled={loading || !selectedCustomer}
            className="btn-primary text-sm disabled:opacity-50">
            {loading ? '...' : '🗂️ فتح الحالة'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CasesPage() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const [filters, setFilters] = useState({
    status: '', category: '', search: '', ordering: '-created_at',
  })
  const [selectedCase, setSelectedCase] = useState(null)
  const [showCreate, setShowCreate]     = useState(false)
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 20

  const queryParams = {
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== '')),
    page, page_size: PAGE_SIZE,
  }

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['cases-list', queryParams],
    queryFn:  () => callCenterApi.cases.list(queryParams).then(r => r.data),
    staleTime: 15_000,
    keepPreviousData: true,
  })

  const cases   = data?.results || data || []
  const total   = data?.count || cases.length
  const hasNext = data?.next
  const hasPrev = data?.previous

  function setFilter(k, v) {
    setFilters(p => ({ ...p, [k]: v }))
    setPage(1)
  }

  const canCreate = ['admin', 'supervisor', 'call_center', 'quality_manager'].includes(user?.role)

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-lg font-black text-gray-900">🗂️ إدارة الحالات</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              {total} حالة · {isFetching && <span className="text-brand-500">تحديث...</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {canCreate && (
              <button onClick={() => setShowCreate(true)}
                className="btn-primary text-sm">
                + حالة جديدة
              </button>
            )}
            <Link to="/callcenter" className="btn-secondary text-sm">← مركز الاتصال</Link>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-5">
        <div className="flex gap-5">

          {/* ── List panel ── */}
          <div className={`flex-1 min-w-0 ${selectedCase ? 'hidden md:block md:max-w-xl' : ''}`}>

            {/* Filters */}
            <div className="card mb-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <input className="input-field text-sm col-span-2 md:col-span-1"
                  placeholder="بحث..."
                  value={filters.search}
                  onChange={e => setFilter('search', e.target.value)} />
                <select className="input-field text-sm" value={filters.status}
                  onChange={e => setFilter('status', e.target.value)}>
                  {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <select className="input-field text-sm" value={filters.category}
                  onChange={e => setFilter('category', e.target.value)}>
                  {CATEGORY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <select className="input-field text-sm" value={filters.ordering}
                  onChange={e => setFilter('ordering', e.target.value)}>
                  <option value="-created_at">الأحدث أولاً</option>
                  <option value="created_at">الأقدم أولاً</option>
                  <option value="-sla_due">SLA أقرب</option>
                  <option value="priority">الأولوية</option>
                </select>
              </div>
            </div>

            {/* Cases list */}
            {isLoading ? (
              <div className="space-y-2 animate-pulse">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-20 bg-gray-100 rounded-xl" />
                ))}
              </div>
            ) : cases.length === 0 ? (
              <div className="card text-center py-12">
                <div className="text-4xl mb-3">🗂️</div>
                <div className="text-gray-500 font-semibold">
                  {filters.search || filters.status || filters.category
                    ? 'لا توجد حالات تطابق هذا البحث'
                    : 'لا توجد حالات بعد'}
                </div>
                {canCreate && !filters.search && !filters.status && !filters.category && (
                  <button onClick={() => setShowCreate(true)}
                    className="btn-primary text-sm mt-4">
                    🗂️ افتح أول حالة
                  </button>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                {cases.map(c => {
                  const sm = STATUS_META[c.status] || { label: c.status, cls: 'bg-gray-100' }
                  const pm = PRIORITY_META[c.priority] || {}
                  const isSelected = selectedCase === c.id
                  return (
                    <div key={c.id}
                      onClick={() => setSelectedCase(isSelected ? null : c.id)}
                      className={`card cursor-pointer transition-all hover:shadow-md
                        ${isSelected ? 'ring-2 ring-brand-400' : ''}
                        ${c.is_sla_breached ? 'border-red-200' : ''}`}>
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono text-xs text-gray-400">{c.case_number}</span>
                            <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${sm.cls}`}>
                              {sm.label}
                            </span>
                            {c.is_sla_breached && (
                              <span className="text-xs text-red-600 font-bold">⏰ SLA!</span>
                            )}
                          </div>
                          <div className="font-bold text-gray-900 text-sm mt-1 truncate">{c.title}</div>
                          <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500 flex-wrap">
                            <span>👤 {c.customer_name}</span>
                            {c.branch_name && <span>🏥 {c.branch_name}</span>}
                            {c.assigned_to_name && <span>→ {c.assigned_to_name}</span>}
                            <span className={pm.cls}>{pm.label}</span>
                            {c.age_hours != null && <span>⏱️ {c.age_hours}س</span>}
                          </div>
                        </div>
                        {c.csat_score && (
                          <span className="text-sm text-yellow-500 shrink-0">
                            {'⭐'.repeat(c.csat_score)}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Pagination */}
            {(hasPrev || hasNext) && (
              <div className="flex justify-center gap-3 mt-4">
                <button disabled={!hasPrev} onClick={() => setPage(p => p - 1)}
                  className="btn-secondary text-sm disabled:opacity-40">
                  ← السابق
                </button>
                <span className="text-sm text-gray-500 self-center">صفحة {page}</span>
                <button disabled={!hasNext} onClick={() => setPage(p => p + 1)}
                  className="btn-secondary text-sm disabled:opacity-40">
                  التالي →
                </button>
              </div>
            )}
          </div>

          {/* ── Detail panel ── */}
          {selectedCase && (
            <div className="w-full md:w-96 shrink-0">
              <div className="card h-[calc(100vh-180px)] flex flex-col p-0 overflow-hidden">
                <CaseDetailPanel
                  caseId={selectedCase}
                  onClose={() => setSelectedCase(null)}
                  onStateChange={() => qc.invalidateQueries({ queryKey: ['cases-list'] })}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Standalone case creation modal */}
      {showCreate && (
        <StandaloneCaseModal
          onClose={() => setShowCreate(false)}
          onCreated={newCase => {
            setShowCreate(false)
            qc.invalidateQueries({ queryKey: ['cases-list'] })
            setSelectedCase(newCase.id)
          }}
        />
      )}
    </div>
  )
}
