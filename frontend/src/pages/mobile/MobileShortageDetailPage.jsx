/**
 * MobileShortageDetailPage.jsx — log items into a shortage list (route: /m/shortage/:id).
 *
 * Floor-capture detail: a fast single-item add (stays focused for rapid entry),
 * a "paste list" bulk import, the item list with auto-match status, delete, and
 * submit. All over the existing shortage API; auto-matching happens server-side.
 */
import { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { shortageApi } from '../../api/client'
import { queuedPost } from '../../api/offlineQueue'
import { MobileLoading, MobileError } from '../../components/mobileUi'

const STATUS_CLASS = {
  open: 'bg-orange-100 text-orange-700', submitted: 'bg-blue-100 text-blue-700', resolved: 'bg-green-100 text-green-700',
}
function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

function ItemRow({ it, onDelete }) {
  const matched = !!it.item_name
  return (
    <div className="flex items-start justify-between gap-2 bg-white border border-gray-200 rounded-xl p-3">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-gray-800">{it.raw_name}</div>
        <div className="flex flex-wrap items-center gap-1.5 mt-1">
          <span className="text-[11px] text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">كمية: {toLatin(it.quantity_needed)}</span>
          {matched ? (
            <span className="text-[11px] text-green-700 bg-green-50 border border-green-200 px-1.5 py-0.5 rounded">
              ✓ {it.item_name}{it.match_score ? ` (${Math.round(it.match_score * 100)}%)` : ''}
            </span>
          ) : (
            <span className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded">غير مطابق</span>
          )}
        </div>
      </div>
      <button onClick={() => onDelete(it.id)} className="text-gray-400 hover:text-red-500 text-sm shrink-0">🗑</button>
    </div>
  )
}

export default function MobileShortageDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const nameRef  = useRef(null)

  const { data: sl, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-shortage-detail', id],
    queryFn: () => shortageApi.get(id).then(r => r.data),
  })

  const [name, setName]   = useState('')
  const [qty, setQty]     = useState('1')
  const [adding, setAdding] = useState(false)
  const [msg, setMsg]     = useState('')          // inline feedback (e.g. duplicate)
  const [showBulk, setShowBulk] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [ocrBusy, setOcrBusy]     = useState(false)
  const recognitionRef = useRef(null)
  const fileRef        = useRef(null)

  const SpeechRec = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)

  const refresh = () => qc.invalidateQueries({ queryKey: ['m-shortage-detail', id] })

  // ── Voice capture (Web Speech API → server voice-import) ──
  function startVoice() {
    if (!SpeechRec) { setMsg('التعرف الصوتي غير مدعوم في هذا المتصفح'); return }
    const rec = new SpeechRec()
    rec.lang = 'ar-EG'
    rec.interimResults = false
    rec.continuous = false
    rec.onresult = async (e) => {
      const transcript = Array.from(e.results).map(r => r[0].transcript).join(' ').trim()
      if (!transcript) return
      try {
        const { data } = await shortageApi.voiceImport(id, { transcript })
        setMsg(`أُضيف ${toLatin(data.created)}${data.skipped ? ` · تخطّي ${toLatin(data.skipped)} مكرر` : ''}`)
        await refresh()
      } catch { setMsg('تعذّر الاستيراد الصوتي') }
    }
    rec.onerror = () => { setListening(false); setMsg('تعذّر التعرف الصوتي') }
    rec.onend   = () => setListening(false)
    recognitionRef.current = rec
    setListening(true); setMsg('🎤 جارٍ الاستماع... قل أسماء الأصناف')
    rec.start()
  }
  function stopVoice() { recognitionRef.current?.stop(); setListening(false) }

  // ── Photo OCR (server extracts lines → review in bulk box → import) ──
  async function onPhoto(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setOcrBusy(true); setMsg('📷 جارٍ قراءة الصورة...')
    try {
      const fd = new FormData(); fd.append('image', file)
      const { data } = await shortageApi.ocrExtract(id, fd)
      const lines = (data.lines || []).join('\n')
      if (lines) {
        setBulkText(lines); setShowBulk(true)
        const rev = data.review_count > 0 ? ` — ⚠ ${toLatin(data.review_count)} بحاجة لمراجعة` : ''
        setMsg(`تم استخراج ${toLatin(data.line_count)} سطر${rev} — راجعها ثم استورد`)
      } else {
        setMsg('لم يتم استخراج أصناف من الصورة')
      }
    } catch (err) {
      setMsg(err.response?.status === 503 ? 'محرك OCR غير متاح على الخادم' : 'تعذّرت قراءة الصورة')
    } finally {
      setOcrBusy(false)
      e.target.value = ''
    }
  }

  async function addOne() {
    const raw = name.trim()
    if (!raw) return
    setAdding(true); setMsg('')
    try {
      // queuedPost re-throws HTTP errors (409 duplicate) but queues network failures.
      const res = await queuedPost(`/shortage/lists/${id}/add-item/`,
        { raw_name: raw, quantity_needed: Number(qty) || 1, source: 'manual' },
        { label: 'إضافة صنف ناقص' })
      setName(''); setQty('1')
      if (res.queued) setMsg('📴 سيُضاف عند عودة الاتصال')
      else await refresh()
      setTimeout(() => nameRef.current?.focus(), 30)
    } catch (e) {
      if (e.response?.status === 409) setMsg(e.response.data?.detail || 'الصنف موجود بالفعل')
      else setMsg('تعذّرت الإضافة')
    } finally {
      setAdding(false)
    }
  }

  async function importBulk() {
    const lines = bulkText.split('\n').map(l => l.trim()).filter(Boolean)
    if (lines.length === 0) return
    setBulkBusy(true); setMsg('')
    try {
      const res = await queuedPost(`/shortage/lists/${id}/bulk-import/`,
        { lines, source: 'bulk' }, { label: 'استيراد نواقص' })
      setBulkText(''); setShowBulk(false)
      if (res.queued) {
        setMsg('📴 سيُستورد عند عودة الاتصال')
      } else {
        const data = res.data
        setMsg(`أُضيف ${toLatin(data.created)}${data.skipped ? ` · تخطّي ${toLatin(data.skipped)} مكرر` : ''}`)
        await refresh()
      }
    } catch {
      setMsg('تعذّر الاستيراد')
    } finally {
      setBulkBusy(false)
    }
  }

  async function removeItem(iid) {
    await shortageApi.deleteItem(id, iid)
    refresh()
  }

  async function submitList() {
    await shortageApi.submit(id)
    refresh()
  }

  if (isLoading) return <MobileLoading />
  if (isError || !sl) return <MobileError text="تعذّر تحميل القائمة" onRetry={refetch} />

  const isOpen = sl.status === 'open'
  const items  = sl.items || []

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/shortage')} className="text-sm text-gray-500">→ الرجوع للقوائم</button>

      {/* Header */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="font-bold text-base text-gray-900">{sl.title || `نواقص ${sl.branch_name || ''}`}</h1>
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${STATUS_CLASS[sl.status] || 'bg-gray-100 text-gray-700'}`}>
            {sl.status_label}
          </span>
        </div>
        <div className="text-xs text-gray-500 mt-1">{sl.branch_name} · {toLatin(items.length)} صنف</div>
      </div>

      {/* Quick add (open lists only) */}
      {isOpen && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-2.5">
          <div className="flex gap-2">
            <input
              ref={nameRef}
              className="input-field flex-1"
              placeholder="اسم الصنف الناقص..."
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addOne() }}
              autoFocus
            />
            <input
              type="number" min="1" inputMode="numeric"
              className="input-field w-16 text-center"
              value={qty}
              onChange={e => setQty(e.target.value)}
            />
          </div>
          <div className="flex items-center justify-between">
            <button onClick={() => setShowBulk(v => !v)} className="text-xs text-brand-600 font-medium">
              {showBulk ? '× إخفاء اللصق' : '📋 لصق قائمة'}
            </button>
            <button onClick={addOne} disabled={adding || !name.trim()}
              className="btn-primary text-sm py-2 px-5 disabled:opacity-50">
              {adding ? '...' : '+ إضافة'}
            </button>
          </div>

          {/* Voice + photo capture */}
          <div className="flex gap-2 pt-1">
            {SpeechRec && (
              <button
                onClick={listening ? stopVoice : startVoice}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-medium border transition-colors ${
                  listening ? 'bg-red-500 text-white border-red-500 animate-pulse' : 'border-gray-300 text-gray-600 active:bg-gray-50'
                }`}
              >
                🎤 {listening ? 'إيقاف' : 'صوت'}
              </button>
            )}
            <button
              onClick={() => fileRef.current?.click()}
              disabled={ocrBusy}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-medium border border-gray-300 text-gray-600 active:bg-gray-50 disabled:opacity-50"
            >
              📷 {ocrBusy ? 'قراءة...' : 'صورة'}
            </button>
            <input
              ref={fileRef} type="file" accept="image/*" capture="environment"
              className="hidden" onChange={onPhoto}
            />
          </div>

          {showBulk && (
            <div className="space-y-2 pt-1">
              <textarea
                rows={5} className="input-field w-full resize-none text-sm"
                placeholder={'سطر لكل صنف، مع الكمية اختيارياً:\nبنادول 10\nأموكسيسيلين 5'}
                value={bulkText}
                onChange={e => setBulkText(e.target.value)}
              />
              <button onClick={importBulk} disabled={bulkBusy || !bulkText.trim()}
                className="btn-primary w-full text-sm py-2 disabled:opacity-50">
                {bulkBusy ? 'جارٍ الاستيراد...' : 'استيراد القائمة'}
              </button>
            </div>
          )}

          {msg && <div className="text-xs text-gray-500 text-center pt-1">{msg}</div>}
        </div>
      )}

      {/* Items */}
      {items.length === 0 ? (
        <div className="text-center text-sm text-gray-400 py-8">لا توجد أصناف بعد — ابدأ بالإضافة</div>
      ) : (
        <div className="space-y-2">
          {items.map(it => <ItemRow key={it.id} it={it} onDelete={removeItem} />)}
        </div>
      )}

      {/* Submit */}
      {isOpen && items.length > 0 && (
        <button onClick={submitList} className="btn-primary w-full py-3">
          ✅ إرسال القائمة ({toLatin(items.length)} صنف)
        </button>
      )}
    </div>
  )
}
