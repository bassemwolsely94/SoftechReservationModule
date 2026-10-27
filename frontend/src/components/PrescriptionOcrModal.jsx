/**
 * PrescriptionOcrModal — modern data entry: read a prescription image and turn it into
 * CONFIRMED cart lines. Image → Gemini drug-name reading → catalog candidates (reuses the
 * shortage OCR + matching flywheel). Nothing is auto-added: the cashier confirms each item
 * (pharmacy safety wins, rule 4/10), and each confirm teaches the alias for next time.
 */
import { useRef, useState } from 'react'
import api from '../api/client'

export default function PrescriptionOcrModal({ onAdd, onClose }) {
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState(null)
  const [err, setErr] = useState('')
  const [added, setAdded] = useState({})      // lineIdx → softech_id confirmed
  const [sampleId, setSampleId] = useState(null)   // corpus sample this read produced
  const [recording, setRecording] = useState(false)
  const fileRef = useRef(null)
  const mediaRef = useRef(null)
  const chunksRef = useRef([])

  const post = async (fd, url, emptyMsg) => {
    setBusy(true); setErr(''); setLines(null); setAdded({}); setSampleId(null)
    try {
      const { data } = await api.post(url, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setLines(data.lines || [])
      setSampleId(data.sample_id || null)
      if (!(data.lines || []).length) setErr(data.detail || emptyMsg)
    } catch (e) {
      setErr(e?.response?.data?.detail || 'تعذّرت المعالجة.')
    } finally { setBusy(false) }
  }

  const run = (file) => {
    if (!file) return
    const fd = new FormData(); fd.append('image', file)
    post(fd, '/pos-orders/prescription-ocr/', 'لم تُقرأ أي أصناف — جرّب صورة أوضح.')
  }

  const startRec = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      chunksRef.current = []
      mr.ondataavailable = e => e.data.size && chunksRef.current.push(e.data)
      mr.onstop = () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' })
        const fd = new FormData(); fd.append('audio', blob, 'voice.webm')
        post(fd, '/pos-orders/voice-entry/', 'لم أفهم الأصناف — جرّب النطق بوضوح.')
      }
      mediaRef.current = mr; mr.start(); setRecording(true)
    } catch { setErr('تعذّر الوصول للميكروفون — تأكد من الإذن.') }
  }
  const stopRec = () => { try { mediaRef.current?.stop() } catch { /* noop */ } setRecording(false) }

  const confirm = (li, cand, rawName) => {
    onAdd(cand.softech_id)
    setAdded(a => ({ ...a, [li]: cand.softech_id }))
    // teach the flywheel + label the corpus sample so it resolves instantly next time; the
    // machine's FIRST suggestion goes along so a replaced one is learned as rejected
    const suggested = lines?.[li]?.candidates?.[0]?.item_id
    api.post('/pos-orders/prescription-ocr/teach/',
             { raw_name: rawName, item_id: cand.item_id, sample_id: sampleId,
               suggested_item_id: suggested && suggested !== cand.item_id ? suggested : null }).catch(() => {})
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-auto" onClick={onClose}>
      <div dir="rtl" className="bg-white rounded-xl shadow-xl w-full max-w-2xl mt-8" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="font-bold text-gray-800 text-sm">📷🎤 إدخال ذكي — روشتة أو صوت · أكّد كل صنف قبل الإضافة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-lg">✕</button>
        </div>

        <div className="p-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
                   onChange={e => run(e.target.files?.[0] || null)} />
            <button onClick={() => fileRef.current?.click()} disabled={busy || recording}
                    className="px-3 py-2 rounded text-white text-sm font-semibold disabled:opacity-50" style={{ background: '#022871' }}>
              📷 صورة الروشتة
            </button>
            {!recording ? (
              <button onClick={startRec} disabled={busy}
                      className="px-3 py-2 rounded text-white text-sm font-semibold disabled:opacity-50" style={{ background: '#0b7a5b' }}>
                🎤 تسجيل صوتي
              </button>
            ) : (
              <button onClick={stopRec}
                      className="px-3 py-2 rounded text-white text-sm font-semibold animate-pulse" style={{ background: '#d81f1f' }}>
                ⏹ إيقاف التسجيل
              </button>
            )}
            {busy && <span className="text-[11px] text-gray-500">… جارٍ المعالجة</span>}
            {lines && !busy && <span className="text-[11px] text-gray-500">{lines.length} سطر — انقر المطابقة الصحيحة لإضافتها</span>}
          </div>

          {err && <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">{err}</div>}

          {lines && lines.map((ln, li) => {
            const rawName = ((ln.readings?.[0] || '') + ' ' + (ln.strength || '')).trim()
            const isAdded = added[li]
            return (
              <div key={li} className={`rounded-lg border p-2 ${isAdded ? 'border-emerald-300 bg-emerald-50/50' : 'border-gray-200 bg-gray-50'}`}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-gray-700">
                    ✍️ {ln.readings?.join(' / ') || '—'}
                    {ln.strength && <span className="text-gray-400"> · {ln.strength}</span>}
                    {ln.qty != null && <span className="text-gray-400"> · ×{ln.qty}</span>}
                  </span>
                  {isAdded && <span className="text-[11px] text-emerald-700 font-semibold">✓ أُضيف</span>}
                </div>
                {!isAdded && (
                  <div className="flex flex-wrap gap-1.5">
                    {(ln.candidates || []).length === 0 && <span className="text-[11px] text-gray-400">لا مطابقة — أضِفه يدويًا من البحث.</span>}
                    {(ln.candidates || []).map(c => (
                      <button key={c.item_id} onClick={() => confirm(li, c, rawName)}
                              title={`ثقة ${(c.score * 100).toFixed(0)}%${c.learned ? ' · مُتعلَّم' : ''}`}
                              className="text-[11px] rounded px-2 py-1 border bg-white border-indigo-200 text-indigo-700 hover:bg-indigo-50 flex items-center gap-1">
                        <span className="truncate max-w-[200px]">{c.name}</span>
                        <span className="text-gray-400">{Number(c.pack_price).toFixed(0)}</span>
                        {c.learned && <span title="مُتعلَّم سابقًا">🧠</span>}
                        {c.engines?.length > 1 && <span title={`اتفاق ${c.engines.join(' + ')}`} className="text-emerald-600">🤝{c.engines.length}</span>}
                        <span className="text-[9px] text-gray-400">{(c.score * 100).toFixed(0)}%</span>
                        <span className="font-bold">+</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )
          })}

          <div className="text-[10px] text-gray-400 pt-1">
            لا يُضاف أي صنف تلقائيًا — الاختيار لك. كل تأكيد يُحسّن دقة القراءة لاحقًا.
          </div>
        </div>
      </div>
    </div>
  )
}
