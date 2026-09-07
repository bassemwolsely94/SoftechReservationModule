/**
 * ShortagePage.jsx — v2
 *
 * Full shortage & out-of-stock management:
 *  • Manual entry with wildcard autocomplete
 *  • Voice input  (Web Speech API, Arabic + English)
 *  • OCR upload   (image → backend pytesseract → text lines)
 *  • Bulk text paste
 *  • Top-3 fuzzy match modal (user must confirm every match)
 *  • Per-item source badges (manual / voice / ocr / bulk)
 *  • Internal stock check with transfer suggestions
 *  • Export: CSV + Excel (single list)
 *  • Aggregated view across all open lists + Excel download
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { shortageApi, branchesApi, invoicesApi } from '../api/client'
import BranchSelect from '../components/BranchSelect'
import ItemSearchWidget from '../components/ItemSearchWidget'
import ItemSearchInput from '../components/ItemSearchInput'
import { createWorker } from 'tesseract.js'

// ─── OCR helpers ──────────────────────────────────────────────────────────────

/**
 * Preprocess an image File/Blob before feeding it to Tesseract:
 *  1. Scale up 2× (Tesseract works much better with larger images)
 *  2. Convert to grayscale
 *  3. Apply contrast stretch (darken shadows, brighten highlights)
 * Returns a PNG Blob.
 */
async function preprocessImageForOcr(file) {
  return new Promise((resolve) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      // ── Step 1: draw original ──────────────────────────────────────────
      const c1 = document.createElement('canvas')
      c1.width  = img.width
      c1.height = img.height
      const ctx1 = c1.getContext('2d')
      ctx1.drawImage(img, 0, 0)

      // ── Step 2: grayscale + contrast boost ────────────────────────────
      const id = ctx1.getImageData(0, 0, c1.width, c1.height)
      const d  = id.data
      for (let i = 0; i < d.length; i += 4) {
        const gray = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]
        // Push values away from mid-grey: darker → black, lighter → white
        const boosted = gray < 128
          ? Math.max(0,   gray * 0.7)         // darken shadows
          : Math.min(255, 255 - (255 - gray) * 0.7)  // brighten highlights
        d[i] = d[i + 1] = d[i + 2] = boosted  // grayscale
        // d[i + 3] alpha unchanged
      }
      ctx1.putImageData(id, 0, 0)

      // ── Step 3: scale up 2× (bilinear off → sharper edges) ────────────
      const c2 = document.createElement('canvas')
      c2.width  = c1.width  * 2
      c2.height = c1.height * 2
      const ctx2 = c2.getContext('2d')
      ctx2.imageSmoothingEnabled = false
      ctx2.drawImage(c1, 0, 0, c2.width, c2.height)

      c2.toBlob(blob => {
        URL.revokeObjectURL(url)
        resolve(blob)
      }, 'image/png')
    }
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file) }
    img.src = url
  })
}

/**
 * Post-process raw Tesseract output into clean candidate lines.
 * Rejects:
 *  • Lines < 3 chars
 *  • Lines with no consecutive letter sequence (e.g. "a e T y")
 *  • Lines where >55% of tokens are single characters (OCR noise)
 *  • Lines that are pure numbers / punctuation
 */
function cleanOcrLines(rawText) {
  return rawText
    .split('\n')
    .map(l => l
      .replace(/[|_\[\]{}\\^~`]+/g, '')  // strip common OCR artifacts
      .replace(/\s{2,}/g, ' ')
      .trim()
    )
    .filter(l => l.length >= 3)
    // Must contain at least one run of 2+ consecutive letters (Latin or Arabic)
    .filter(l => /[a-zA-Zء-ي]{2,}/.test(l))
    // Reject pure-digit / pure-punctuation lines
    .filter(l => !/^[\d\s\-_.,;:|/\\()]+$/.test(l))
    // Reject "isolated letter noise": if >55% of space-split tokens are 1 char, skip
    .filter(l => {
      const tokens = l.split(/\s+/).filter(Boolean)
      if (tokens.length < 2) return true   // single-word lines are fine
      const singles = tokens.filter(t => t.length === 1).length
      return singles / tokens.length < 0.55
    })
}

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  open:      { label: 'مفتوحة',  color: 'bg-blue-100 text-blue-700',   dot: 'bg-blue-500' },
  submitted: { label: 'مُرسَلة', color: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500' },
  resolved:  { label: 'محلولة',  color: 'bg-green-100 text-green-700', dot: 'bg-green-500' },
}

const SOURCE_BADGES = {
  manual: { label: 'يدوي',       bg: 'bg-gray-100 text-gray-500' },
  voice:  { label: '🎤 صوتي',   bg: 'bg-purple-100 text-purple-600' },
  ocr:    { label: '📷 OCR',    bg: 'bg-blue-100 text-blue-600' },
  bulk:   { label: '📋 نصي',    bg: 'bg-teal-100 text-teal-600' },
}

const INPUT_TABS = ['manual', 'voice', 'ocr', 'bulk']
const INPUT_TAB_LABELS = {
  manual: '✍️ يدوي',
  voice:  '🎤 صوتي',
  ocr:    '📷 صورة',
  bulk:   '📋 نص',
}

// Top-10 main distributors (SofTech personcode → label) for single-supplier POs
const MAIN_SUPPLIERS = [
  ['565', 'PharmaOverseas'], ['260', 'Ibn Sina'], ['4327', 'Egy Drug Zaytoun'],
  ['786', 'Egy Drug Sherif'], ['30', 'Ramco'], ['746', 'Sofico'],
  ['124', 'Akhnaton'], ['156', 'MEC'], ['13', 'Chemipharm'], ['16', 'EIPICO'],
]

function scoreColor(s) {
  if (!s) return 'text-gray-400'
  if (s >= 0.80) return 'text-emerald-600'
  if (s >= 0.55) return 'text-amber-600'
  return 'text-red-500'
}

function ScoreDot({ score }) {
  const pct = score ? Math.round(score * 100) : 0
  return (
    <span className={`text-[10px] font-bold tabular-nums ${scoreColor(score)}`}>
      {pct}%
    </span>
  )
}

function SourceBadge({ source }) {
  const cfg = SOURCE_BADGES[source] || SOURCE_BADGES.manual
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${cfg.bg}`}>
      {cfg.label}
    </span>
  )
}

function Toast({ msg, type }) {
  if (!msg) return null
  return (
    <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-xl text-sm font-medium
      ${type === 'error' ? 'bg-red-600 text-white' : 'bg-emerald-600 text-white'}`}>
      {msg}
    </div>
  )
}

// ─── Match Modal (top-3, user must confirm) ───────────────────────────────────

function MatchModal({ item, listId, onConfirm, onClose }) {
  const [matches,  setMatches]  = useState([])
  const [loading,  setLoading]  = useState(true)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    shortageApi.itemMatches(listId, item.id, { params: { top: 8 } })
      .then(r => { setMatches(r.data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [listId, item.id])

  const confirm = async () => {
    if (!selected) return
    await shortageApi.updateItem(listId, item.id, {
      item: selected.item_id,
      match_score: selected.score,
      is_confirmed: true,
    })
    onConfirm()
  }

  const markUnmatched = async () => {
    await shortageApi.updateItem(listId, item.id, { is_unmatched: true, item: null })
    onConfirm()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg" dir="rtl">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-start justify-between">
          <div>
            <div className="font-bold text-gray-900">اختيار الصنف المطابق</div>
            <div className="text-xs text-gray-500 mt-0.5">
              البحث عن: <span className="font-medium text-gray-700">"{item.raw_name}"</span>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        {/* Candidates */}
        <div className="p-4 space-y-2 max-h-[28rem] overflow-y-auto">
          {loading ? (
            <div className="text-center py-8 text-gray-400 animate-pulse">جاري البحث...</div>
          ) : matches.length === 0 ? (
            <div className="text-center py-8 text-gray-400">
              <div className="text-3xl mb-2">🔍</div>
              <div>لا توجد نتائج مطابقة</div>
            </div>
          ) : (
            matches.map((m, i) => (
              <button
                key={m.item_id}
                onClick={() => setSelected(m)}
                className={`w-full text-right px-4 py-3 rounded-xl border-2 transition-all
                  ${selected?.item_id === m.item_id
                    ? 'border-brand-500 bg-brand-50'
                    : 'border-gray-200 hover:border-brand-300 hover:bg-gray-50'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-gray-900 text-sm leading-tight">{m.item_name}</div>
                    {m.item_scientific && (
                      <div className="text-xs text-gray-400 mt-0.5 italic">{m.item_scientific}</div>
                    )}
                    <div className="flex items-center gap-2 mt-1">
                      <span className="font-mono text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{m.item_softech_id}</span>
                      {m.item_sale_price > 0 && (
                        <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                          {Number(m.item_sale_price).toFixed(2)} ج.م
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-center shrink-0">
                    <div className={`text-lg font-bold tabular-nums ${scoreColor(m.score)}`}>
                      {Math.round(m.score * 100)}%
                    </div>
                    <div className="text-[9px] text-gray-400">تطابق</div>
                    {i === 0 && <span className="text-[9px] bg-amber-100 text-amber-600 px-1 rounded mt-0.5">الأفضل</span>}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Actions */}
        <div className="px-4 pb-4 pt-2 border-t border-gray-100 flex items-center gap-2">
          <button
            onClick={confirm}
            disabled={!selected}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm
              hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ✓ تأكيد الاختيار
          </button>
          <button
            onClick={markUnmatched}
            className="px-4 py-2.5 border border-gray-300 text-gray-600 rounded-xl text-sm hover:bg-gray-50"
          >
            ✕ غير مطابق
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Stock Check Panel ────────────────────────────────────────────────────────

function StockCheckPanel({ listId, onClose }) {
  const [data,    setData]    = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    shortageApi.stockCheck(listId)
      .then(r => { setData(r.data); setLoading(false) })
      .catch(e => { setError(e.response?.data?.detail || 'خطأ'); setLoading(false) })
  }, [listId])

  const transferable = data.filter(d => d.transfer_possible)
  const noStock      = data.filter(d => !d.transfer_possible && d.available_branches.length === 0)
  const partial      = data.filter(d => !d.transfer_possible && d.available_branches.length > 0)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col" dir="rtl">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div>
            <div className="font-bold text-gray-900">فحص المخزون الداخلي</div>
            <div className="text-xs text-gray-500 mt-0.5">{data.length} صنف مُأكَّد</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center text-gray-400 animate-pulse p-8">
            جاري فحص المخزون...
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center text-red-500 p-8">{error}</div>
        ) : data.length === 0 ? (
          <div className="flex-1 flex items-center justify-center p-8 text-center text-gray-400">
            <div>
              <div className="text-3xl mb-2">ℹ️</div>
              <div>لا توجد أصناف مُأكَّدة للفحص</div>
              <div className="text-xs mt-1">تأكد من تأكيد الأصناف أولاً</div>
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-4">
            {/* Summary */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[
                { label: 'يمكن تحويله', count: transferable.length, color: 'bg-emerald-50 border-emerald-200 text-emerald-700' },
                { label: 'جزئياً متاح', count: partial.length,      color: 'bg-amber-50 border-amber-200 text-amber-700' },
                { label: 'غير متاح',    count: noStock.length,       color: 'bg-red-50 border-red-200 text-red-600' },
              ].map(s => (
                <div key={s.label} className={`border rounded-xl p-3 text-center ${s.color}`}>
                  <div className="text-2xl font-bold">{s.count}</div>
                  <div className="text-xs font-medium mt-0.5">{s.label}</div>
                </div>
              ))}
            </div>

            {/* Transfer suggestions */}
            {transferable.length > 0 && (
              <div className="mb-4">
                <div className="text-xs font-bold text-emerald-700 mb-2 flex items-center gap-1">
                  <span className="w-2 h-2 bg-emerald-500 rounded-full inline-block" />
                  متاح للتحويل ({transferable.length})
                </div>
                <div className="space-y-2">
                  {transferable.map(item => (
                    <div key={item.shortage_item_id}
                      className="bg-emerald-50 border border-emerald-200 rounded-xl p-3">
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="font-medium text-gray-900 text-sm">{item.item_name}</div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            مطلوب: <strong>{item.needed_qty}</strong> — متاح: <strong>{item.total_available}</strong>
                          </div>
                        </div>
                        <span className="text-xs font-mono text-gray-400">{item.item_code}</span>
                      </div>
                      <div className="mt-2 space-y-1">
                        {item.available_branches.map(b => (
                          <div key={b.branch_id}
                            className="flex items-center justify-between text-xs bg-white rounded-lg px-3 py-1.5 border border-emerald-100">
                            <span className="text-emerald-700 font-medium">{b.suggestion}</span>
                            <span className="text-gray-500">{b.branch_name}: {b.qty_on_hand}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Partial */}
            {partial.length > 0 && (
              <div className="mb-4">
                <div className="text-xs font-bold text-amber-700 mb-2 flex items-center gap-1">
                  <span className="w-2 h-2 bg-amber-500 rounded-full inline-block" />
                  متاح جزئياً ({partial.length})
                </div>
                <div className="space-y-2">
                  {partial.map(item => (
                    <div key={item.shortage_item_id}
                      className="bg-amber-50 border border-amber-200 rounded-xl p-3">
                      <div className="flex items-start justify-between">
                        <div className="font-medium text-gray-900 text-sm">{item.item_name}</div>
                        <span className="text-xs text-gray-400">{item.item_code}</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        مطلوب: {item.needed_qty} — إجمالي متاح: {item.total_available}
                      </div>
                      <div className="mt-1.5 space-y-1">
                        {item.available_branches.map(b => (
                          <div key={b.branch_id} className="text-xs text-amber-700">
                            {b.suggestion}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* No stock */}
            {noStock.length > 0 && (
              <div>
                <div className="text-xs font-bold text-red-600 mb-2 flex items-center gap-1">
                  <span className="w-2 h-2 bg-red-500 rounded-full inline-block" />
                  يحتاج شراء ({noStock.length})
                </div>
                <div className="space-y-1.5">
                  {noStock.map(item => (
                    <div key={item.shortage_item_id}
                      className="bg-red-50 border border-red-200 rounded-xl px-3 py-2 flex items-center justify-between">
                      <span className="text-sm text-gray-800">{item.item_name}</span>
                      <span className="text-xs text-gray-500">كمية: {item.needed_qty}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="px-4 py-3 border-t border-gray-100 shrink-0">
          <button onClick={onClose}
            className="w-full py-2 bg-gray-100 text-gray-600 rounded-xl text-sm font-medium hover:bg-gray-200">
            إغلاق
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Lines Review Modal (used for both OCR and Voice) ────────────────────────
// title: 'OCR' | 'Voice' header label
// lines: string[] — one item per line to review and optionally adjust qty

function OcrReviewModal({ lines, onImport, onClose, title = 'OCR', candidates = null }) {
  const [selected, setSelected] = useState(() => new Set(lines.map((_, i) => i)))
  const [qtys,     setQtys]     = useState(() => Object.fromEntries(lines.map((_, i) => [i, 1])))
  // Inline corrections: overrides[i] = { item_id, item_softech_id, item_name }
  const [overrides,  setOverrides]  = useState({})
  const [pickingFor, setPickingFor] = useState(null)   // line index whose picker is open
  const isOcr = candidates != null

  const reviewCount = (candidates || []).filter(c => c?.needs_review).length

  const toggle = (i) => setSelected(s => {
    const ns = new Set(s)
    ns.has(i) ? ns.delete(i) : ns.add(i)
    return ns
  })

  const setOverride = (i, item) => {
    setOverrides(o => ({ ...o, [i]: {
      item_id:         item.item_id ?? null,
      item_softech_id: item.softech_id || '',
      item_name:       item.name,
    }}))
    setSelected(s => new Set(s).add(i))   // picking implies keep this line
    setPickingFor(null)
  }
  const clearOverride = (i) => setOverrides(o => { const n = { ...o }; delete n[i]; return n })

  const handleImport = () => {
    // Preserve original indices so qtys map correctly even when lines have duplicates
    const toImport = lines
      .map((line, i) => ({ line, i }))
      .filter(({ i }) => selected.has(i))
      .map(({ line, i }) => {
        const qty = qtys[i] || 1
        const raw = qty > 1 ? `${line} ${qty}` : line
        const ov  = overrides[i]
        // A hand-picked line carries its item so the server confirms + learns it.
        return ov ? { raw, item_id: ov.item_id, item_softech_id: ov.item_softech_id } : raw
      })
    onImport(toImport)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col" dir="rtl">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div>
            <div className="font-bold text-gray-900">مراجعة {title === 'voice' ? '🎤 النص الصوتي' : '📷 نص OCR'}</div>
            <div className="text-xs text-gray-500">
              {lines.length} صنف — اختر ما تريد إضافته وعدّل الكميات
              {reviewCount > 0 && (
                <span className="text-amber-600 font-medium"> • ⚠ {reviewCount} بحاجة لمراجعة</span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-1.5">
          {lines.map((line, i) => {
            const cand   = candidates?.[i]
            const match  = cand?.match
            const ov     = overrides[i]
            const review = cand?.needs_review && !ov
            const pct    = match ? Math.round(match.score * 100) : null
            const picking = pickingFor === i
            return (
            <div
              key={i}
              onClick={() => toggle(i)}
              className={`px-3 py-2.5 rounded-xl border cursor-pointer transition-all
                ${selected.has(i)
                  ? (review ? 'border-amber-400 bg-amber-50' : 'border-brand-400 bg-brand-50')
                  : (review ? 'border-amber-300 bg-amber-50/40' : 'border-gray-200 bg-white hover:border-gray-300')}`}
            >
              <div className="flex items-start gap-3">
                <div className={`w-4 h-4 mt-0.5 rounded border-2 flex items-center justify-center shrink-0
                  ${selected.has(i) ? 'border-brand-500 bg-brand-500' : 'border-gray-300'}`}>
                  {selected.has(i) && <span className="text-white text-[10px] leading-none">✓</span>}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    {review && <span title="بحاجة لمراجعة">⚠️</span>}
                    <span className="text-sm text-gray-800">{line}</span>
                    {review && cand?.review_reason && (
                      <span className="text-[10px] font-medium bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded">
                        {cand.review_reason}
                      </span>
                    )}
                  </div>
                  {(cand || ov) && (
                    <div className="mt-1 flex items-center gap-1.5 flex-wrap text-xs">
                      {ov ? (
                        <>
                          <span className="text-gray-400">↳</span>
                          <span className="truncate max-w-[16rem] text-emerald-700 font-medium">{ov.item_name}</span>
                          <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">✏️ تم التصحيح</span>
                        </>
                      ) : match ? (
                        <>
                          <span className="text-gray-400">↳</span>
                          <span className={`truncate max-w-[16rem] ${review ? 'text-amber-700' : 'text-emerald-700'}`}>
                            {match.item_name}
                          </span>
                          {match.learned && (
                            <span className="px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 font-medium" title="مطابقة مُتعلَّمة سابقاً">
                              ✨ متعلّم
                            </span>
                          )}
                          <span className={`px-1.5 py-0.5 rounded font-medium
                            ${pct >= 85 ? 'bg-emerald-100 text-emerald-700'
                              : pct >= 55 ? 'bg-amber-100 text-amber-700'
                              : 'bg-red-100 text-red-600'}`}>
                            {pct}%
                          </span>
                        </>
                      ) : (
                        <span className="text-red-500">لا توجد مطابقة</span>
                      )}
                      {/* Inline correct / pick control (OCR mode only) */}
                      {isOcr && (
                        <button
                          onClick={e => { e.stopPropagation(); setPickingFor(picking ? null : i) }}
                          className="text-brand-600 hover:text-brand-700 font-medium"
                        >
                          {picking ? 'إغلاق' : ov ? 'تغيير' : match ? '✏️ تصحيح' : '🔍 اختر صنف'}
                        </button>
                      )}
                      {ov && (
                        <button
                          onClick={e => { e.stopPropagation(); clearOverride(i) }}
                          className="text-gray-400 hover:text-gray-600"
                        >
                          استرجاع
                        </button>
                      )}
                    </div>
                  )}
                </div>
                {selected.has(i) && (
                  <input
                    type="number" min="1" max="9999"
                    value={qtys[i] || 1}
                    onChange={e => setQtys(q => ({ ...q, [i]: Number(e.target.value) }))}
                    onClick={e => e.stopPropagation()}
                    className="w-16 border border-gray-300 rounded-lg px-2 py-0.5 text-xs text-center shrink-0"
                  />
                )}
              </div>
              {/* Inline item search picker */}
              {picking && (
                <div className="mt-2 pr-7" onClick={e => e.stopPropagation()}>
                  <ItemSearchInput
                    onSelect={item => setOverride(i, item)}
                    placeholder="ابحث واختر الصنف الصحيح..."
                  />
                </div>
              )}
            </div>
          )})}
        </div>

        <div className="px-4 py-3 border-t border-gray-100 flex gap-2 shrink-0">
          <button
            onClick={handleImport}
            disabled={selected.size === 0}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-xl text-sm font-medium
              hover:bg-brand-700 disabled:opacity-40"
          >
            استيراد {selected.size} صنف
          </button>
          <button onClick={onClose}
            className="px-4 py-2.5 border border-gray-300 text-gray-600 rounded-xl text-sm">
            إلغاء
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Voice Input Component ────────────────────────────────────────────────────
// onReview(lines) is called when user is ready to review the split items.

function VoiceInput({ onReview }) {
  const [listening,  setListening]  = useState(false)
  const [transcript, setTranscript] = useState('')
  const [supported,  setSupported]  = useState(true)
  const [interim,    setInterim]    = useState('')  // live partial result
  const recogRef = useRef(null)

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { setSupported(false); return }

    const recognition = new SR()
    // Accept both Arabic and English — let the browser pick best
    recognition.lang       = 'ar'
    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    recognition.onresult = (e) => {
      let final = ''
      let interim = ''
      for (let i = 0; i < e.results.length; i++) {
        if (e.results[i].isFinal) final   += e.results[i][0].transcript + '، '
        else                       interim += e.results[i][0].transcript
      }
      setTranscript(final)
      setInterim(interim)
    }
    recognition.onend  = () => { setListening(false); setInterim('') }
    recognition.onerror = () => { setListening(false); setInterim('') }
    recogRef.current = recognition
  }, [])

  const toggle = () => {
    if (!recogRef.current) return
    if (listening) {
      recogRef.current.stop()
    } else {
      setTranscript('')
      setInterim('')
      recogRef.current.start()
      setListening(true)
    }
  }

  const handleReview = () => {
    const full = transcript.trim()
    if (!full) return
    // Split on Arabic comma، English comma, newline, or 2+ spaces
    const lines = full
      .split(/[،,\n]+|\s{2,}/)
      .map(l => l.trim())
      .filter(l => l.length >= 2)
    if (!lines.length) return
    onReview(lines)
    setTranscript('')
    setInterim('')
  }

  if (!supported) {
    return (
      <div className="text-center py-8 text-gray-400">
        <div className="text-3xl mb-2">⚠️</div>
        <div className="text-sm">المتصفح لا يدعم الإدخال الصوتي</div>
        <div className="text-xs mt-1">استخدم Chrome أو Edge</div>
      </div>
    )
  }

  // Split preview for the user to see BEFORE confirming
  const previewLines = transcript.trim()
    ? transcript.trim().split(/[،,\n]+|\s{2,}/).map(l => l.trim()).filter(l => l.length >= 2)
    : []

  return (
    <div className="space-y-4">
      {/* Record button */}
      <div className="flex flex-col items-center gap-3">
        <button
          onClick={toggle}
          className={`w-20 h-20 rounded-full flex items-center justify-center text-3xl shadow-lg
            transition-all duration-200
            ${listening
              ? 'bg-red-500 text-white scale-110 shadow-red-200 animate-pulse'
              : 'bg-brand-600 text-white hover:bg-brand-700 hover:scale-105'}`}
        >
          {listening ? '⏹' : '🎤'}
        </button>
        <div className="text-sm font-medium text-gray-700">
          {listening
            ? 'جاري الاستماع... اضغط للإيقاف'
            : 'اضغط للتسجيل (عربي + إنجليزي)'}
        </div>
        {/* Live interim result */}
        {interim && (
          <div className="text-xs text-gray-400 italic text-center max-w-xs">{interim}</div>
        )}
      </div>

      {/* Detected items preview */}
      {previewLines.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-1.5 flex items-center gap-1">
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full inline-block" />
            {previewLines.length} صنف مكتشف — راجع قبل الإضافة:
          </div>
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-2 space-y-1 max-h-36 overflow-y-auto">
            {previewLines.map((line, i) => (
              <div key={i} className="text-xs text-gray-700 px-2 py-1 bg-white rounded-lg border border-gray-100">
                {i + 1}. {line}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Review + import button */}
      <button
        onClick={handleReview}
        disabled={previewLines.length === 0}
        className="w-full py-2.5 bg-brand-600 text-white rounded-xl text-sm font-medium
          hover:bg-brand-700 disabled:opacity-40 flex items-center justify-center gap-2"
      >
        {previewLines.length > 0
          ? `مراجعة وإضافة ${previewLines.length} صنف`
          : 'سجّل صوتك أولاً'}
      </button>
      <div className="text-xs text-gray-400 text-center">
        💡 افصل بين الأصناف بفاصلة أو توقف قصير أثناء الكلام
      </div>
    </div>
  )
}

// ─── Item Row ─────────────────────────────────────────────────────────────────

function ShortageItemRow({ item: si, listId, onUpdated, onDelete, isOpen }) {
  const [showMatch, setShowMatch] = useState(false)
  const [editing,   setEditing]   = useState(false)
  const [qty,       setQty]       = useState(si.quantity_needed)
  const [rawName,   setRawName]   = useState(si.raw_name)
  const [saving,    setSaving]    = useState(false)

  const needsReview = !si.is_confirmed && !si.is_unmatched

  const save = async () => {
    setSaving(true)
    try {
      await shortageApi.updateItem(listId, si.id, { raw_name: rawName, quantity_needed: qty })
      setEditing(false)
      onUpdated()
    } finally {
      setSaving(false)
    }
  }

  const borderClass = si.is_unmatched
    ? 'border-gray-200 bg-gray-50'
    : si.is_confirmed
    ? 'border-emerald-200 bg-emerald-50/30'
    : si.item_name
    ? 'border-blue-200 bg-blue-50/20'
    : 'border-amber-200 bg-amber-50/20'

  return (
    <>
      {showMatch && (
        <MatchModal
          item={si}
          listId={listId}
          onConfirm={() => { setShowMatch(false); onUpdated() }}
          onClose={() => setShowMatch(false)}
        />
      )}

      <div className={`border rounded-xl mb-1.5 overflow-hidden transition-all ${borderClass}`}>
        <div className="flex items-start gap-3 px-3 py-2.5">
          {/* Status indicator */}
          <div className="mt-0.5 shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] text-white font-bold
            ${si.is_unmatched ? 'bg-gray-400' : si.is_confirmed ? 'bg-emerald-500' : si.item_name ? 'bg-blue-400' : 'bg-amber-400'}">
            {si.is_unmatched ? '✕' : si.is_confirmed ? '✓' : si.item_name ? '~' : '?'}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            {editing ? (
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  value={rawName}
                  onChange={e => setRawName(e.target.value)}
                  className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-brand-400"
                />
                <input
                  type="number" value={qty}
                  onChange={e => setQty(e.target.value)}
                  className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-brand-400"
                />
                <button onClick={save} disabled={saving}
                  className="px-2.5 py-1 bg-brand-600 text-white rounded-lg text-xs font-medium">
                  {saving ? '...' : 'حفظ'}
                </button>
                <button onClick={() => setEditing(false)}
                  className="px-2.5 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs">إلغاء</button>
              </div>
            ) : (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-gray-800 text-sm">{si.raw_name}</span>
                <span className="text-xs text-gray-400">× {si.quantity_needed}</span>
                <SourceBadge source={si.source} />
              </div>
            )}

            {si.item_name && !editing && (
              <div className="mt-0.5 flex items-center gap-1.5 flex-wrap">
                <span className="text-xs text-gray-400">→</span>
                <span className="text-xs font-medium text-gray-700">{si.item_name}</span>
                {si.item_softech_id && (
                  <span className="text-[10px] font-mono text-gray-400 bg-gray-100 px-1 py-0.5 rounded">{si.item_softech_id}</span>
                )}
                {si.item_sale_price > 0 && (
                  <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1 py-0.5 rounded">
                    {Number(si.item_sale_price).toFixed(2)} ج.م
                  </span>
                )}
                <ScoreDot score={si.match_score} />
              </div>
            )}
          </div>

          {/* Actions */}
          {isOpen && !editing && (
            <div className="flex items-center gap-1 shrink-0">
              {needsReview && (
                <button
                  onClick={() => setShowMatch(true)}
                  className="text-xs text-brand-600 hover:text-brand-800 px-2 py-1 rounded hover:bg-brand-50 font-medium"
                >
                  🔍 تطابق
                </button>
              )}
              <button onClick={() => setEditing(true)}
                className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 rounded hover:bg-gray-100">
                ✏️
              </button>
              <button onClick={() => onDelete(si.id)}
                className="text-xs text-red-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50">
                🗑
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ─── Shortage Detail (inside a list) ─────────────────────────────────────────

function ShortageDetail({ listId, onBack }) {
  const [sl,          setSl]          = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [activeTab,   setActiveTab]   = useState('manual')
  const [manualInputMode, setManualInputMode] = useState('text')   // 'text' | 'catalog'
  const [catalogItem,     setCatalogItem]     = useState(null)     // selected catalog item
  const [singleInput, setSingleInput] = useState({ raw_name: '', quantity_needed: 1 })
  const [bulkText,    setBulkText]    = useState('')
  const [submitting,  setSubmitting]  = useState(false)
  const [toast,       setToast]       = useState(null)
  const [showStock,   setShowStock]   = useState(false)
  // Official/main distributors (is_main) for the supplier-PO picker — dynamic
  const [mainSuppliers, setMainSuppliers] = useState([])
  useEffect(() => {
    invoicesApi.mainVendors()
      .then(r => setMainSuppliers(r.data || []))
      .catch(() => setMainSuppliers(MAIN_SUPPLIERS.map(([personcode, name]) => ({ personcode, name }))))
  }, [])

  // OCR state
  const [ocrFile,      setOcrFile]      = useState(null)
  const [ocrPreview,   setOcrPreview]   = useState(null)
  const [ocrLines,     setOcrLines]     = useState(null)
  const [ocrCandidates,setOcrCandidates]= useState(null)  // per-line {text,match,needs_review}
  const [ocrLoading,   setOcrLoading]   = useState(false)
  const [ocrProgress,  setOcrProgress]  = useState(0)     // 0-100 %
  const [showOcrReview,setShowOcrReview]= useState(false) // show review modal after OCR
  // 'eng'     = English-only  (best for handwritten drug names in Latin script)
  // 'ara+eng' = Arabic+English (best for printed Arabic lists)
  const [ocrLang,      setOcrLang]      = useState('eng')
  const [voiceLines,   setVoiceLines]   = useState(null)  // voice split preview
  const [showVoiceReview, setShowVoiceReview] = useState(false)
  const fileInputRef = useRef()

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await shortageApi.get(listId)
      setSl(r.data)
    } finally {
      setLoading(false)
    }
  }, [listId])

  useEffect(() => { load() }, [load])

  // ── Manual add (free text) ───────────────────────────────────────────────────
  const handleAddSingle = async () => {
    if (!singleInput.raw_name.trim()) return
    setSubmitting(true)
    try {
      await shortageApi.addItem(listId, { ...singleInput, source: 'manual' })
      setSingleInput({ raw_name: '', quantity_needed: 1 })
      load()
      showToast('تمت الإضافة ✓')
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Catalog add (pre-confirmed item from picker) ────────────────────────────
  const handleAddFromCatalog = async () => {
    if (!catalogItem) return
    setSubmitting(true)
    try {
      await shortageApi.addItem(listId, {
        raw_name:        catalogItem.name,
        quantity_needed: singleInput.quantity_needed,
        item:            catalogItem.id,   // pre-links catalog item → skips fuzzy matching
        source:          'manual',
      })
      setCatalogItem(null)
      setSingleInput(f => ({ ...f, quantity_needed: 1 }))
      load()
      showToast('تمت الإضافة من الكتالوج ✓')
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Bulk text import ────────────────────────────────────────────────────────
  const handleBulkImport = async (customLines = null, src = 'bulk') => {
    const lines = customLines || bulkText.split('\n').filter(l => l.trim())
    if (!lines.length) return
    setSubmitting(true)
    try {
      const r = await shortageApi.bulkImport(listId, { lines, source: src })
      if (!customLines) setBulkText('')
      load()
      showToast(`تم استيراد ${r.data.created} صنف${r.data.skipped ? ` (${r.data.skipped} مكرر)` : ''} ✓`)
    } catch (e) {
      showToast('خطأ في الاستيراد', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Voice ────────────────────────────────────────────────────────────────────
  // Called by VoiceInput when the user is ready to review the split lines.
  const handleVoiceReview = (lines) => {
    setVoiceLines(lines)
    setShowVoiceReview(true)
  }

  // ── OCR (client-side Tesseract.js — no server binary needed) ─────────────────
  const handleOcrFileSelect = (e) => {
    const file = e.target.files[0]
    if (!file) return
    setOcrFile(file)
    setOcrLines(null)
    setShowOcrReview(false)
    setOcrProgress(0)
    const url = URL.createObjectURL(file)
    setOcrPreview(url)
  }

  const handleOcrExtract = async () => {
    if (!ocrFile) return
    setOcrLoading(true)
    setOcrProgress(0)
    try {
      // ── Send image to server for OCR ───────────────────────────────────────
      // Server tries: (1) Claude Vision API — excellent for handwriting
      //               (2) pytesseract — printed text fallback
      // Progress simulation while waiting for server response
      const ticker = setInterval(() => {
        setOcrProgress(p => p < 85 ? p + 5 : p)
      }, 400)

      const fd = new FormData()
      fd.append('image', ocrFile)
      const r = await shortageApi.ocrExtract(listId, fd)

      clearInterval(ticker)
      setOcrProgress(100)

      const { lines = [], engine = '', candidates = null, review_count = 0 } = r.data
      if (!lines.length) {
        showToast('لم يتم استخراج نص — حاول صورة أوضح', 'error')
        return
      }

      const engineLabel = engine.startsWith('gemini')  ? 'Gemini ✨'   :
                          engine === 'easyocr'  ? 'EasyOCR 🧠'  :
                          engine === 'pytesseract' ? 'Tesseract' : engine
      setOcrLines(lines)
      setOcrCandidates(candidates)
      setShowOcrReview(true)
      const reviewMsg = review_count > 0 ? ` — ${review_count} بحاجة لمراجعة` : ''
      showToast(`استُخرج ${lines.length} سطر (${engineLabel})${reviewMsg} ✓`)
    } catch (err) {
      const msg = err.response?.data?.detail || 'فشل OCR — حاول مرة أخرى'
      showToast(msg, 'error')
      // If server has no OCR engine, tell user to add API key
      if (err.response?.status === 503) {
        console.warn('OCR 503:', err.response.data)
      }
    } finally {
      setOcrLoading(false)
      setOcrProgress(0)
    }
  }

  // ── Status / export ──────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!window.confirm('إرسال القائمة للمراجعة؟')) return
    await shortageApi.submit(listId)
    load(); showToast('تم إرسال القائمة ✓')
  }

  const handleExportCsv = async () => {
    try {
      const r = await shortageApi.exportCsv(listId)
      const url = URL.createObjectURL(new Blob(['﻿' + r.data], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a'); a.href = url; a.download = `shortage_${listId}.csv`; a.click()
    } catch { showToast('خطأ في التصدير', 'error') }
  }

  const _downloadXlsx = (data, filename) => {
    const url = URL.createObjectURL(new Blob([data], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  }

  const handleExportExcel = async () => {
    try {
      const r = await shortageApi.exportExcel(listId)
      _downloadXlsx(r.data, `shortage_${listId}.xlsx`)
    } catch { showToast('خطأ في التصدير', 'error') }
  }

  const handleExportMatrix = async () => {
    try {
      showToast('جارٍ تجهيز مصفوفة الموردين والأسعار...')
      const r = await shortageApi.exportSupplierMatrix(listId)
      _downloadXlsx(r.data, `shortage_${listId}_suppliers.xlsx`)
    } catch { showToast('خطأ في تصدير مصفوفة الموردين', 'error') }
  }

  const handleExportPo = async (code, name) => {
    if (!code) return
    try {
      showToast(`جارٍ تجهيز أمر شراء — ${name}...`)
      const r = await shortageApi.exportSupplierPo(listId, code, name)
      _downloadXlsx(r.data, `po_${listId}_${code}.xlsx`)
    } catch { showToast('خطأ في تصدير أمر الشراء', 'error') }
  }

  const handleDelete = async (iid) => {
    if (!window.confirm('حذف هذا الصنف؟')) return
    await shortageApi.deleteItem(listId, iid)
    load()
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-400 animate-pulse">جاري التحميل...</div>
  )
  if (!sl) return null

  const isOpen    = sl.status === 'open'
  const items     = sl.items || []
  const confirmed = items.filter(i => i.is_confirmed).length
  const unmatched = items.filter(i => i.is_unmatched).length
  const pending   = items.filter(i => !i.is_confirmed && !i.is_unmatched).length
  const statusCfg = STATUS_CONFIG[sl.status] || {}

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}
      {showStock && <StockCheckPanel listId={listId} onClose={() => setShowStock(false)} />}

      {/* OCR Review Modal — shows the server's auto-match per line + review flags */}
      {showOcrReview && ocrLines && (
        <OcrReviewModal
          title="ocr"
          lines={ocrLines}
          candidates={ocrCandidates}
          onImport={(lines) => {
            setShowOcrReview(false)
            setOcrLines(null); setOcrCandidates(null)
            handleBulkImport(lines, 'ocr')
          }}
          onClose={() => { setShowOcrReview(false); setOcrLines(null); setOcrCandidates(null) }}
        />
      )}

      {/* Voice Review Modal — shown after user stops recording */}
      {showVoiceReview && voiceLines && (
        <OcrReviewModal
          title="voice"
          lines={voiceLines}
          onImport={(lines) => {
            setShowVoiceReview(false)
            setVoiceLines(null)
            handleBulkImport(lines, 'voice')
          }}
          onClose={() => { setShowVoiceReview(false); setVoiceLines(null) }}
        />
      )}

      {/* Sub-header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <button onClick={onBack} className="text-gray-400 hover:text-gray-600 text-sm flex items-center gap-1">
            ← رجوع
          </button>
          <div className="h-4 w-px bg-gray-200" />
          <h2 className="font-bold text-gray-900">{sl.title || `نواقص ${sl.branch_name}`}</h2>
          <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${statusCfg.color}`}>
            {statusCfg.label}
          </span>
          <div className="mr-auto flex items-center gap-2 flex-wrap">
            {confirmed > 0 && (
              <button onClick={() => setShowStock(true)}
                className="px-3 py-1.5 bg-teal-500 text-white rounded-lg text-sm font-medium hover:bg-teal-600 flex items-center gap-1">
                🔄 فحص المخزون
              </button>
            )}
            {isOpen && (
              <button onClick={handleSubmit}
                className="px-3 py-1.5 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600">
                📤 إرسال
              </button>
            )}
            <div className="flex border border-gray-300 rounded-lg overflow-hidden text-sm">
              <button onClick={handleExportCsv}
                className="px-2.5 py-1.5 text-gray-600 hover:bg-gray-50 border-l border-gray-300">
                CSV
              </button>
              <button onClick={handleExportExcel}
                className="px-2.5 py-1.5 text-gray-600 hover:bg-gray-50 border-l border-gray-300">
                📊 Excel
              </button>
              <button onClick={handleExportMatrix} title="مصفوفة الموردين: كود كل مورد رئيسي + آخر شراء وأقل سعر"
                className="px-2.5 py-1.5 text-gray-600 hover:bg-gray-50">
                🧮 الموردون
              </button>
            </div>
            {/* Single-supplier purchase order (that supplier's own item codes) */}
            <select
              defaultValue=""
              onChange={e => { const s = mainSuppliers.find(x => x.personcode === e.target.value); if (s) handleExportPo(s.personcode, s.name); e.target.value = '' }}
              className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 text-gray-600 bg-white"
              title="تنزيل أمر شراء بأكواد مورد رئيسي محدد">
              <option value="">⬇ أمر شراء لمورد…</option>
              {mainSuppliers.map(s => (
                <option key={s.personcode} value={s.personcode}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Stats bar */}
        <div className="flex gap-5 text-xs text-gray-500 mb-4">
          <span className="font-medium text-gray-700">{items.length} صنف</span>
          <span className="text-emerald-600 font-medium">✓ {confirmed} مُأكَّد</span>
          <span className="text-amber-600 font-medium">⏳ {pending} بانتظار</span>
          {unmatched > 0 && <span className="text-gray-400">✕ {unmatched} غير مطابق</span>}
          {items.length > 0 && (
            <div className="flex-1 flex items-center gap-2 max-w-xs">
              <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-emerald-400 rounded-full transition-all"
                  style={{ width: `${Math.round((confirmed / items.length) * 100)}%` }} />
              </div>
              <span className="font-medium text-gray-600 tabular-nums">
                {Math.round((confirmed / items.length) * 100)}%
              </span>
            </div>
          )}
        </div>

        {/* Input tabs */}
        {isOpen && (
          <div>
            <div className="flex gap-1.5 mb-3">
              {INPUT_TABS.map(tab => (
                <button key={tab} onClick={() => setActiveTab(tab)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors
                    ${activeTab === tab
                      ? 'bg-brand-600 text-white border-brand-600'
                      : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
                  {INPUT_TAB_LABELS[tab]}
                </button>
              ))}
            </div>

            {/* ── Manual ── */}
            {activeTab === 'manual' && (
              <div className="space-y-3">
                {/* Input mode toggle */}
                <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
                  <button
                    onClick={() => { setManualInputMode('text'); setCatalogItem(null) }}
                    className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                      manualInputMode === 'text'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    ✏️ كتابة يدوية
                  </button>
                  <button
                    onClick={() => setManualInputMode('catalog')}
                    className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                      manualInputMode === 'catalog'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    🔍 اختيار من الكتالوج
                  </button>
                </div>

                {manualInputMode === 'text' ? (
                  /* ── Free-text entry (original behaviour) ── */
                  <div className="flex items-end gap-3 flex-wrap">
                    <div>
                      <label className="text-xs text-gray-500 block mb-1">اسم الصنف *</label>
                      <input
                        value={singleInput.raw_name}
                        onChange={e => setSingleInput(f => ({ ...f, raw_name: e.target.value }))}
                        onKeyDown={e => e.key === 'Enter' && handleAddSingle()}
                        className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-64
                          focus:outline-none focus:ring-2 focus:ring-brand-400"
                        placeholder="مثال: أموكسيسيلين 500مج"
                        autoFocus
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 block mb-1">الكمية</label>
                      <input
                        type="number" value={singleInput.quantity_needed}
                        onChange={e => setSingleInput(f => ({ ...f, quantity_needed: e.target.value }))}
                        className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-20
                          focus:outline-none focus:ring-2 focus:ring-brand-400"
                      />
                    </div>
                    <button onClick={handleAddSingle} disabled={submitting}
                      className="px-4 py-1.5 bg-brand-600 text-white rounded-xl text-sm font-medium
                        hover:bg-brand-700 disabled:opacity-50">
                      {submitting ? '...' : '+ إضافة'}
                    </button>
                  </div>
                ) : (
                  /* ── Catalog picker — pre-confirms match, skips fuzzy step ── */
                  <div className="space-y-3">
                    <ItemSearchWidget
                      selected={catalogItem}
                      onSelect={item => setCatalogItem(item)}
                      onClear={() => setCatalogItem(null)}
                      placeholder="ابحث باسم الصنف أو الكود أو الباركود..."
                    />
                    {catalogItem && (
                      <div className="flex items-center gap-3">
                        <div>
                          <label className="text-xs text-gray-500 block mb-1">الكمية</label>
                          <input
                            type="number" value={singleInput.quantity_needed}
                            onChange={e => setSingleInput(f => ({ ...f, quantity_needed: e.target.value }))}
                            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-20
                              focus:outline-none focus:ring-2 focus:ring-brand-400"
                          />
                        </div>
                        <button
                          onClick={handleAddFromCatalog}
                          disabled={submitting}
                          className="px-4 py-2 bg-brand-600 text-white rounded-xl text-sm font-medium
                            hover:bg-brand-700 disabled:opacity-50 self-end"
                        >
                          {submitting ? '...' : '+ إضافة (مُأكَّد)'}
                        </button>
                      </div>
                    )}
                    <p className="text-xs text-gray-400">
                      ✔ الأصناف المضافة من الكتالوج مُطابَقة تلقائياً وتظهر كمؤكدة فوراً
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* ── Voice ── */}
            {activeTab === 'voice' && (
              <div className="max-w-sm">
                <VoiceInput onReview={handleVoiceReview} />
              </div>
            )}

            {/* ── OCR (client-side Tesseract.js) ── */}
            {activeTab === 'ocr' && (
              <div className="space-y-3">
                <div className="flex items-center gap-3 flex-wrap">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="px-4 py-2 border-2 border-dashed border-gray-300 rounded-xl text-sm text-gray-600
                      hover:border-brand-400 hover:text-brand-600 transition-colors"
                  >
                    📷 اختر صورة (مطبوعة أو مكتوبة بخط اليد)
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file" accept="image/*"
                    onChange={handleOcrFileSelect}
                    className="hidden"
                  />
                  {ocrFile && (
                    <span className="text-xs text-gray-500 truncate max-w-xs">{ocrFile.name}</span>
                  )}
                </div>

                {ocrPreview && (
                  <div className="flex items-start gap-4">
                    <img src={ocrPreview} alt="OCR preview"
                      className="w-32 h-24 object-cover rounded-xl border border-gray-200 shrink-0" />
                    <div className="space-y-2 flex-1">
                      <button
                        onClick={handleOcrExtract}
                        disabled={ocrLoading}
                        className="px-4 py-2 bg-brand-600 text-white rounded-xl text-sm font-medium
                          hover:bg-brand-700 disabled:opacity-50 flex items-center gap-2 w-full justify-center"
                      >
                        {ocrLoading ? (
                          <><span className="animate-spin inline-block">⟳</span> قراءة النص...</>
                        ) : (
                          '📖 قراءة النص'
                        )}
                      </button>
                      {/* Progress bar during OCR */}
                      {ocrLoading && ocrProgress > 0 && (
                        <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="bg-brand-500 h-1.5 rounded-full transition-all duration-300"
                            style={{ width: `${ocrProgress}%` }}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                )}
                <div className="text-xs text-gray-400 space-y-0.5">
                  <div>يدعم الخط اليد والقوائم المطبوعة • عربي + إنجليزي • JPG, PNG</div>
                  <div className="text-brand-600 font-medium">✨ يعمل بالذكاء الاصطناعي (EasyOCR / Gemini)</div>
                </div>
              </div>
            )}

            {/* ── Bulk text ── */}
            {activeTab === 'bulk' && (
              <div>
                <div className="text-xs text-gray-500 mb-1">
                  كل صنف في سطر: <code className="bg-gray-100 px-1 rounded">اسم الصنف [الكمية]</code>
                </div>
                <textarea
                  value={bulkText}
                  onChange={e => setBulkText(e.target.value)}
                  rows={4}
                  className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none
                    focus:outline-none focus:ring-2 focus:ring-brand-400 font-mono"
                  placeholder={'أموكسيسيلين 500 ملج 10\nباراسيتامول 5\nميترونيدازول 3'}
                />
                <button
                  onClick={() => handleBulkImport()}
                  disabled={submitting || !bulkText.trim()}
                  className="mt-2 px-4 py-1.5 bg-brand-600 text-white rounded-xl text-sm font-medium
                    hover:bg-brand-700 disabled:opacity-50"
                >
                  {submitting ? 'جاري...' : 'استيراد'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Items list */}
      <div className="flex-1 overflow-auto p-6">
        {items.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-4xl mb-3">📋</div>
            <div>أضف أصنافاً باستخدام أي من طرق الإدخال أعلاه</div>
          </div>
        ) : (
          <div className="max-w-3xl">
            {/* Group: pending review first */}
            {pending > 0 && (
              <div className="mb-1 text-xs font-semibold text-amber-600 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 bg-amber-500 rounded-full" />
                بانتظار التأكيد ({pending})
              </div>
            )}
            {items
              .filter(i => !i.is_confirmed && !i.is_unmatched)
              .map(si => (
                <ShortageItemRow
                  key={si.id} item={si} listId={listId}
                  onUpdated={load} onDelete={handleDelete} isOpen={isOpen}
                />
              ))}

            {confirmed > 0 && (
              <div className="mt-3 mb-1 text-xs font-semibold text-emerald-600 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                مُأكَّد ({confirmed})
              </div>
            )}
            {items.filter(i => i.is_confirmed).map(si => (
              <ShortageItemRow
                key={si.id} item={si} listId={listId}
                onUpdated={load} onDelete={handleDelete} isOpen={isOpen}
              />
            ))}

            {unmatched > 0 && (
              <div className="mt-3 mb-1 text-xs font-semibold text-gray-400 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full" />
                غير مطابق ({unmatched})
              </div>
            )}
            {items.filter(i => i.is_unmatched).map(si => (
              <ShortageItemRow
                key={si.id} item={si} listId={listId}
                onUpdated={load} onDelete={handleDelete} isOpen={isOpen}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Aggregate View ───────────────────────────────────────────────────────────

function AggregateView({ branches, onClose }) {
  const [data,       setData]       = useState([])
  const [loading,    setLoading]    = useState(false)
  const [branchIds,  setBranchIds]  = useState([])
  const [statusF,    setStatusF]    = useState('open')
  const [dateFrom,   setDateFrom]   = useState('')
  const [dateTo,     setDateTo]     = useState('')
  const [exporting,  setExporting]  = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const params = {}
      if (branchIds.length) params.branch_ids = branchIds.join(',')
      if (statusF) params.status = statusF
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const r = await shortageApi.aggregate(params)
      setData(r.data.results || [])
    } finally {
      setLoading(false)
    }
  }

  const handleExcel = async () => {
    setExporting(true)
    try {
      const params = {}
      if (branchIds.length) params.branch_ids = branchIds.join(',')
      if (statusF) params.status = statusF
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const r = await shortageApi.exportAggregated(params)
      const url = URL.createObjectURL(new Blob([r.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }))
      const a = document.createElement('a')
      a.href = url
      a.download = `shortage_aggregate_${new Date().toISOString().slice(0,10)}.xlsx`
      a.click()
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="flex flex-col h-full" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center gap-3 mb-4">
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm">← رجوع</button>
          <div className="h-4 w-px bg-gray-200" />
          <h2 className="font-bold text-gray-900">العرض المجمع للنواقص</h2>
        </div>
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <label className="text-xs text-gray-500 block mb-1">الحالة</label>
            <select value={statusF} onChange={e => setStatusF(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
              <option value="">الكل</option>
              <option value="open">مفتوحة</option>
              <option value="submitted">مُرسَلة</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">من تاريخ</label>
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">إلى تاريخ</label>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
          <button onClick={load} disabled={loading}
            className="px-4 py-1.5 bg-brand-600 text-white rounded-xl text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
            {loading ? 'جاري...' : '🔍 تجميع'}
          </button>
          {data.length > 0 && (
            <button onClick={handleExcel} disabled={exporting}
              className="px-4 py-1.5 bg-emerald-600 text-white rounded-xl text-sm font-medium hover:bg-emerald-700 disabled:opacity-50">
              {exporting ? '...' : '📊 تصدير Excel'}
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">جاري التجميع...</div>
        ) : data.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-4xl mb-3">📊</div>
            <div>اضغط "تجميع" لعرض النواقص مجمعةً عبر الفروع</div>
          </div>
        ) : (
          <div className="max-w-4xl">
            <div className="text-xs text-gray-500 mb-3">{data.length} صنف مجمع</div>
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-2.5 text-right font-semibold text-gray-700">الصنف</th>
                    <th className="px-4 py-2.5 text-center font-semibold text-gray-700 w-20">الكمية</th>
                    <th className="px-4 py-2.5 text-right font-semibold text-gray-700">توزيع الفروع</th>
                    <th className="px-4 py-2.5 text-center font-semibold text-gray-700 w-24">المصادر</th>
                    <th className="px-4 py-2.5 text-center font-semibold text-gray-700 w-20">الحالة</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((row, i) => (
                    <tr key={i} className={`border-b border-gray-100 ${i % 2 === 0 ? '' : 'bg-gray-50/50'}`}>
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-gray-900">{row.item_name}</div>
                        {row.item_code && (
                          <div className="text-[10px] font-mono text-gray-400 mt-0.5">{row.item_code}</div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-center font-bold text-gray-800 tabular-nums">
                        {Number(row.total_qty).toFixed(0)}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(row.branches || {}).map(([br, qty]) => (
                            <span key={br} className="text-[10px] bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">
                              {br}: {Number(qty).toFixed(0)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <div className="flex flex-wrap gap-1 justify-center">
                          {(row.sources || []).map(s => <SourceBadge key={s} source={s} />)}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        {row.unmatched ? (
                          <span className="text-[10px] bg-red-100 text-red-600 px-2 py-0.5 rounded-full">غير مطابق</span>
                        ) : row.confirmed ? (
                          <span className="text-[10px] bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full">مُأكَّد</span>
                        ) : (
                          <span className="text-[10px] bg-amber-100 text-amber-600 px-2 py-0.5 rounded-full">جزئي</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Create Modal ─────────────────────────────────────────────────────────────

function CreateModal({ branches, onClose, onCreated }) {
  const [form,   setForm]   = useState({ branch: '', title: '', notes: '' })
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const submit = async () => {
    if (!form.branch) { setError('اختر الفرع'); return }
    setSaving(true); setError(null)
    try {
      const r = await shortageApi.create(form)
      onCreated(r.data.id)
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md">
        <h3 className="font-bold text-gray-900 mb-4">قائمة نواقص جديدة</h3>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-600 block mb-1">الفرع *</label>
            <BranchSelect
              value={form.branch}
              onChange={v => setForm(f => ({ ...f, branch: v }))}
              branches={branches}
              placeholder="اختر الفرع..."
            />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">العنوان (اختياري)</label>
            <input
              value={form.title}
              onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              placeholder="مثال: زيارة المندوب — مايو 2026"
            />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">ملاحظات</label>
            <textarea
              value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
        <div className="flex gap-2 mt-5">
          <button onClick={submit} disabled={saving}
            className="flex-1 py-2 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? '...' : 'إنشاء'}
          </button>
          <button onClick={onClose}
            className="flex-1 py-2 bg-gray-100 text-gray-600 rounded-xl font-medium hover:bg-gray-200 text-sm">
            إلغاء
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Page Root ────────────────────────────────────────────────────────────────

export default function ShortagePage() {
  const [lists,        setLists]        = useState([])
  const [branches,     setBranches]     = useState([])
  const [loading,      setLoading]      = useState(true)
  const [showCreate,   setShowCreate]   = useState(false)
  const [activeId,     setActiveId]     = useState(null)
  const [showAggregate, setShowAggregate] = useState(false)
  const [filterBranch, setFilterBranch] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  const loadLists = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterBranch) params.branch = filterBranch
      if (filterStatus) params.status = filterStatus
      const r = await shortageApi.list(params)
      setLists(r.data.results || r.data)
    } finally {
      setLoading(false)
    }
  }, [filterBranch, filterStatus])

  useEffect(() => {
    branchesApi.list().then(r => setBranches(r.data.results || r.data))
  }, [])

  useEffect(() => { loadLists() }, [loadLists])

  if (activeId) {
    return (
      <ShortageDetail
        listId={activeId}
        onBack={() => { setActiveId(null); loadLists() }}
      />
    )
  }

  if (showAggregate) {
    return (
      <AggregateView
        branches={branches}
        onClose={() => setShowAggregate(false)}
      />
    )
  }

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">

      {showCreate && (
        <CreateModal
          branches={branches}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => { setShowCreate(false); setActiveId(id) }}
        />
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📋</span>
            <div>
              <h1 className="text-xl font-bold text-gray-900">النواقص وخارج المخزون</h1>
              <p className="text-xs text-gray-500">إدخال يدوي · صوتي · OCR · مطابقة ذكية</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAggregate(true)}
              className="px-3 py-2 border border-gray-300 text-gray-600 rounded-xl text-sm font-medium hover:bg-gray-50 flex items-center gap-1.5"
            >
              📊 عرض مجمع
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700"
            >
              + قائمة جديدة
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-3 flex-wrap">
          <BranchSelect
            size="sm"
            value={filterBranch}
            onChange={setFilterBranch}
            branches={branches}
            allLabel="كل الفروع"
            className="w-52"
          />
          <select
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          >
            <option value="">كل الحالات</option>
            <option value="open">مفتوحة</option>
            <option value="submitted">مُرسَلة</option>
            <option value="resolved">محلولة</option>
          </select>
        </div>
      </div>

      {/* Lists grid */}
      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">
            جاري التحميل...
          </div>
        ) : lists.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">📋</div>
            <div className="text-gray-500 font-medium mb-2">لا توجد قوائم نواقص</div>
            <p className="text-sm text-gray-400 mb-4">
              أنشئ قائمة جديدة وأضف الأصناف يدوياً، صوتياً، أو عبر صورة OCR
            </p>
            <button onClick={() => setShowCreate(true)}
              className="px-5 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
              + قائمة جديدة
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {lists.map(sl => {
              const cfg = STATUS_CONFIG[sl.status] || {}
              const matchPct = sl.item_count > 0
                ? Math.round((sl.matched_count / sl.item_count) * 100)
                : 0
              const confirmPct = sl.item_count > 0
                ? Math.round(((sl.confirmed_count || 0) / sl.item_count) * 100)
                : 0

              return (
                <button key={sl.id} onClick={() => setActiveId(sl.id)}
                  className="bg-white rounded-2xl border border-gray-200 p-5 text-right
                    hover:border-brand-300 hover:shadow-md transition-all">
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1 min-w-0">
                      <div className="font-bold text-gray-900 text-sm truncate">
                        {sl.title || `نواقص ${sl.branch_name}`}
                      </div>
                      <div className="text-xs text-gray-400 mt-0.5">
                        {sl.branch_name} — {new Date(sl.created_at).toLocaleDateString('en-US')}
                      </div>
                    </div>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium shrink-0 mr-2 ${cfg.color}`}>
                      {cfg.label}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 text-xs text-gray-500 mb-2.5">
                    <span>{sl.item_count} صنف</span>
                    <span className="text-emerald-600">✓ {sl.confirmed_count || 0}</span>
                    {sl.unmatched_count > 0 && (
                      <span className="text-gray-400">✕ {sl.unmatched_count}</span>
                    )}
                  </div>

                  {/* Progress: confirmed */}
                  {sl.item_count > 0 && (
                    <div>
                      <div className="flex justify-between text-[10px] text-gray-400 mb-0.5">
                        <span>تأكيد</span>
                        <span>{confirmPct}%</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-400 rounded-full transition-all"
                          style={{ width: `${confirmPct}%` }} />
                      </div>
                    </div>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
