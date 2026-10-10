/**
 * InsuranceClaimDetailPage.jsx
 * Claim detail: prescriptions, adjustments, supplements, manual Rx, payments, deductions.
 *
 * Tabs:
 *   - الروشتات    : Prescription list with adjust/exclude actions
 *   - الملاحق     : Supplements (before/within/after)
 *   - إضافة يدوية : Manually add external prescriptions
 *   - التحصيل     : Payments & deductions
 *   - المراجعة    : Audit — drill into items per prescription
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useParams, useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'
import DataTable from '../components/DataTable'
import { wildcardMatch } from '../utils/wildcard'
import useGridKeyboard from '../hooks/useGridKeyboard'
import useHelpTab from '../help/useHelpTab'

const fmt = (n) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })
const toLatinDigits = (s) => s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

const STATUS_LABELS = {
  draft: 'مسودة', ready: 'جاهزة للطباعة', submitted: 'مُقدَّمة',
  under_review: 'قيد المراجعة', partially_paid: 'مدفوعة جزئياً',
  paid: 'مدفوعة', rejected: 'مرفوضة', cancelled: 'ملغاة',
}

function Btn({ children, onClick, variant = 'primary', size = 'sm', className = '', disabled }) {
  const v = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
    success: 'bg-green-600 text-white hover:bg-green-700',
    danger: 'bg-red-50 border border-red-200 text-red-600 hover:bg-red-100',
    warning: 'bg-amber-50 border border-amber-200 text-amber-700 hover:bg-amber-100',
  }
  const s = { sm: 'px-2.5 py-1 text-xs', md: 'px-4 py-2 text-sm' }
  return (
    <button onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-1 rounded font-medium transition-colors disabled:opacity-50 ${s[size]} ${v[variant]} ${className}`}>
      {children}
    </button>
  )
}

// ── Prescription Row ───────────────────────────────────────────────────────────
/**
 * PatientNameAutocomplete — suggests full patient names from the same insurer's
 * history (exact ID-card spelling preserved).  Debounced; keyboard-navigable.
 * Picking a suggestion fills the EXACT stored spelling. onCommit fires on Enter/pick.
 */
const _sugCache = new Map()   // module-level tiny cache: `${claimId}|${q}` → results

function PatientNameAutocomplete({ claimId, value, onChange, onCommit, className, autoFocus }) {
  const [sugs, setSugs]   = useState([])
  const [open, setOpen]   = useState(false)
  const [hi, setHi]       = useState(-1)
  const [loading, setLoading] = useState(false)
  const [rect, setRect]   = useState(null)
  const inputRef = useRef(null)
  const reqId    = useRef(0)

  const measure = () => {
    const el = inputRef.current
    if (el) setRect(el.getBoundingClientRect())
  }

  useEffect(() => {
    const q = (value ?? '').trim()
    if (q.length < 2) { setSugs([]); setOpen(false); return }
    const key = `${claimId}|${q}`
    if (_sugCache.has(key)) {
      const filtered = _sugCache.get(key).filter(s => s.name !== q)
      setSugs(filtered); setHi(-1); if (filtered.length) { measure(); setOpen(true) } else setOpen(false)
      return
    }
    const my = ++reqId.current
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const { data } = await insuranceApi.patientNameSuggest(claimId, q)
        _sugCache.set(key, data || [])
        if (my !== reqId.current) return           // a newer keystroke superseded this
        const filtered = (data || []).filter(s => s.name !== q)
        setSugs(filtered); setHi(-1)
        if (filtered.length) { measure(); setOpen(true) } else setOpen(false)
      } catch { if (my === reqId.current) { setSugs([]); setOpen(false) } }
      finally { if (my === reqId.current) setLoading(false) }
    }, 140)
    return () => clearTimeout(t)
  }, [value, claimId])

  // keep the portal glued to the input while open
  useEffect(() => {
    if (!open) return
    const onScroll = () => measure()
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => { window.removeEventListener('scroll', onScroll, true); window.removeEventListener('resize', onScroll) }
  }, [open])

  const pick = (s) => { onChange(s.name); setOpen(false); setSugs([]); onCommit && onCommit(s.name) }

  return (
    <span className="relative inline-block">
      <input
        ref={inputRef}
        value={value ?? ''}
        autoFocus={autoFocus}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => {
          if (open && sugs.length) {
            if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(h + 1, sugs.length - 1)); return }
            if (e.key === 'ArrowUp')   { e.preventDefault(); setHi(h => Math.max(h - 1, -1)); return }
            if (e.key === 'Enter' && hi >= 0) { e.preventDefault(); pick(sugs[hi]); return }
            if (e.key === 'Escape')    { setOpen(false); return }
          }
          if (e.key === 'Enter') onCommit && onCommit(value)
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onFocus={() => { if (sugs.length) { measure(); setOpen(true) } }}
        className={className} />
      {open && rect && createPortal(
        <div
          style={{ position: 'fixed', top: rect.bottom + 2, right: window.innerWidth - rect.right, width: Math.max(rect.width, 240), zIndex: 9999 }}
          className="max-h-64 overflow-auto bg-white border border-gray-200 rounded-lg shadow-xl text-right">
          {sugs.map((s, i) => (
            <button key={s.name + i} type="button"
              onMouseDown={e => { e.preventDefault(); pick(s) }}
              className={`w-full text-right px-3 py-1.5 text-sm flex items-center justify-between gap-2 ${i === hi ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="font-medium text-gray-800 truncate">{s.name}</span>
                {s.kind === 'complete' && <span className="text-[9px] bg-emerald-100 text-emerald-700 rounded px-1 py-0.5 shrink-0">إكمال</span>}
                {s.kind === 'spelling' && <span className="text-[9px] bg-sky-100 text-sky-700 rounded px-1 py-0.5 shrink-0">تصحيح إملائي</span>}
              </span>
              <span className="text-[10px] text-gray-400 shrink-0" dir="ltr">
                {s.count}× {s.last ? '· ' + s.last : ''}
              </span>
            </button>
          ))}
          {loading && <div className="px-3 py-1 text-[11px] text-gray-400">…</div>}
        </div>,
        document.body)}
    </span>
  )
}

function RxRow({ rx, claimId, discPcts, onRefresh, sug, selected, onToggleSelect }) {
  const [showAdjust, setShowAdjust] = useState(false)
  const [showLines, setShowLines]   = useState(false)
  const [lines, setLines]           = useState(rx.lines || null)
  const [linesLoading, setLinesLoading] = useState(false)
  const [editLines, setEditLines]   = useState(false)   // unlock line editing (also unlocks the patient name)
  const [lineEdits, setLineEdits]   = useState({})      // lineId → {item_code, quantity, unit_price, lookup}
  const [savingLine, setSavingLine] = useState(null)
  const [nameDraft, setNameDraft]   = useState(null)    // patient-name edit buffer (null = not touched)
  const [savingName, setSavingName] = useState(false)
  const [editingName, setEditingName] = useState(false) // name-only edit, INDEPENDENT of the line lock

  const saveName = async (override) => {
    // `override` (from a picked suggestion) beats the async-stale nameDraft.
    // Guard: ignore a non-string arg (e.g. a click event) so it can't crash.
    const src = (typeof override === 'string') ? override : nameDraft
    const v = (src ?? '').trim()
    if (v === '' || v === (rx.patient_name || '')) { setNameDraft(null); setEditingName(false); return }
    setSavingName(true)
    try {
      await insuranceApi.updatePatientName(claimId, rx.id, v)
      setNameDraft(null); setEditingName(false); onRefresh()
    } finally { setSavingName(false) }
  }

  const revertName = async () => {
    setSavingName(true)
    try {
      await insuranceApi.revertPatientName(claimId, rx.id)
      setNameDraft(null); setEditingName(false); onRefresh()
    } finally { setSavingName(false) }
  }

  const reloadLines = async () => {
    const { data } = await insuranceApi.prescriptionLines(claimId, rx.id)
    setLines(data)
  }
  const lookupNewItem = async (lineId, code) => {
    if (!code) return
    try {
      const { data } = await insuranceApi.itemOverrideLookup(code)
      setLineEdits(s => ({ ...s, [lineId]: { ...s[lineId], lookup: data,
        unit_price: (s[lineId]?.unit_price ?? (data.found ? data.pack_price : '')) } }))
    } catch { setLineEdits(s => ({ ...s, [lineId]: { ...s[lineId], lookup: { found: false } } })) }
  }
  const saveLine = async (lineId) => {
    const e = lineEdits[lineId] || {}
    const payload = {}
    if (e.item_code && e.item_code.trim()) payload.item_code = e.item_code.trim()
    if (e.quantity !== undefined && e.quantity !== '') payload.quantity = e.quantity
    if (e.unit_price !== undefined && e.unit_price !== '') payload.unit_price = e.unit_price
    if (Object.keys(payload).length === 0) return
    if (!window.confirm('⚠️ تعديل بند مصروف يدوياً (تغيير الصنف/الكمية/السعر) سيغيّر إجمالى المطالبة. متابعة؟')) return
    setSavingLine(lineId)
    try {
      await insuranceApi.editLine(claimId, rx.id, lineId, payload)
      setLineEdits(s => { const n = { ...s }; delete n[lineId]; return n })
      await reloadLines(); onRefresh()
    } finally { setSavingLine(null) }
  }
  const resetLine = async (lineId) => {
    if (!window.confirm('استرجاع البند إلى قيمه الأصلية؟')) return
    setSavingLine(lineId)
    try {
      await insuranceApi.resetLine(claimId, rx.id, lineId)
      await reloadLines(); onRefresh()
    } finally { setSavingLine(null) }
  }
  const [adjForm, setAdjForm]       = useState({
    local_before: '', imported_before: '', tarsia_before: '', net_override: '', reason: '',
  })
  const [saving, setSaving] = useState(false)

  const isExcluded = rx.is_excluded
  const isAdjusted = rx.is_adjusted

  const net  = rx.effective_net_after ?? rx.net_after
  const local = rx.effective_local_before ?? rx.local_before
  const imported = rx.effective_imported_before ?? rx.imported_before

  async function saveAdjust() {
    setSaving(true)
    try {
      const payload = { reason: adjForm.reason }
      if (adjForm.local_before !== '')    payload.local_before    = adjForm.local_before
      if (adjForm.imported_before !== '') payload.imported_before = adjForm.imported_before
      if (adjForm.tarsia_before !== '')   payload.tarsia_before   = adjForm.tarsia_before
      if (adjForm.net_override !== '')    payload.net_override    = adjForm.net_override
      await insuranceApi.adjustRx(claimId, rx.id, payload)
      setShowAdjust(false)
      onRefresh()
    } finally { setSaving(false) }
  }

  async function removeAdjust() {
    await insuranceApi.removeAdjustment(claimId, rx.id)
    onRefresh()
  }

  async function toggleExclude() {
    try {
      if (isExcluded) {
        await insuranceApi.includeRx(claimId, rx.id)
      } else {
        const reason = window.prompt('سبب الاستثناء (اختياري):') ?? ''
        if (reason === null) return  // user cancelled
        await insuranceApi.excludeRx(claimId, rx.id, { reason })
      }
      await onRefresh()
    } catch (e) {
      alert('حدث خطأ: ' + (e?.response?.data?.error || e?.message || 'خطأ غير متوقع'))
    }
  }

  const mismatch = rx.softech_mismatch && !isExcluded
  return (
    <>
      <tr className={`border-b border-gray-100 text-sm ${isExcluded ? 'opacity-40 line-through' : ''} ${mismatch ? 'bg-amber-50' : ''} ${selected ? 'bg-blue-50/60' : ''}`}>
        <td className="px-2 py-2 text-center">
          {onToggleSelect && <input type="checkbox" checked={!!selected} onChange={onToggleSelect} />}
        </td>
        <td className="px-3 py-2 text-gray-400 text-xs">{rx.sequence}</td>
        <td className="px-3 py-2 text-xs text-gray-500">
          {rx.softech_docdate}
        </td>
        <td className="px-3 py-2 text-xs font-mono text-gray-500">{rx.softech_docnumber || '—'}</td>
        <td className="px-3 py-2 text-xs text-center text-gray-500">{rx.softech_branchcode || '—'}</td>
        <td className="px-3 py-2 font-medium text-gray-800">
          {mismatch && (
            <span title={`صافينا ${fmt(net)} مقابل سوفتك ${fmt(rx.softech_net)} (فرق ${rx.softech_net_diff > 0 ? '+' : ''}${fmt(rx.softech_net_diff)})`}
              className="text-amber-500 ml-1">⚑</span>
          )}
          {rx.is_manual && (
            <span title="روشتة مضافة يدوياً (تفصيلية)"
              className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded ml-1">يدوي</span>
          )}
          {(editLines || editingName) ? (
            <span className="inline-flex items-center gap-1">
              <PatientNameAutocomplete
                claimId={claimId}
                value={nameDraft ?? rx.patient_name ?? ''}
                onChange={setNameDraft}
                onCommit={(v) => saveName(v)}
                autoFocus={editingName}
                className="border border-blue-300 rounded px-2 py-0.5 text-sm w-52" />
              <button onClick={() => saveName()} disabled={savingName}
                className="text-[11px] bg-blue-600 text-white rounded px-1.5 py-0.5 disabled:opacity-50">
                {savingName ? '…' : 'حفظ الاسم'}
              </button>
              {editingName && !editLines && (
                <button onClick={() => { setNameDraft(null); setEditingName(false) }} disabled={savingName}
                  className="text-[11px] text-gray-400 hover:text-gray-600">إلغاء</button>
              )}
              {rx.softech_patient_name && rx.patient_name !== rx.softech_patient_name && (
                <button onClick={revertName} disabled={savingName}
                  title={`استرجاع اسم سوفتك الأصلي: ${rx.softech_patient_name}`}
                  className="text-[11px] bg-amber-50 border border-amber-200 text-amber-700 rounded px-1.5 py-0.5 disabled:opacity-50">
                  ↩ اسم سوفتك
                </button>
              )}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 group flex-wrap">
              <span>{rx.patient_name || '—'}</span>
              <button onClick={() => { setNameDraft(rx.patient_name || ''); setEditingName(true) }}
                title="تعديل الاسم (بدون فتح قفل البنود)"
                className="text-[11px] text-gray-300 hover:text-blue-600">✎</button>
              {sug && sug.type === 'complete' && (
                <button onClick={() => saveName(sug.suggestion)} disabled={savingName}
                  title={`إكمال الاسم رباعياً من السجل — اضغط للتطبيق (قابل للتراجع):\n${sug.suggestion}`}
                  className="text-[10px] bg-emerald-50 border border-emerald-200 text-emerald-700 rounded px-1.5 py-0.5 hover:bg-emerald-100 disabled:opacity-50">
                  ⇢ إكمال: {sug.suggestion}
                </button>
              )}
              {sug && sug.type === 'spelling' && (
                <button onClick={() => saveName(sug.suggestion)} disabled={savingName}
                  title={`تصحيح إملائى مقترح — اضغط للتطبيق (قابل للتراجع):\n${sug.suggestion}`}
                  className="text-[10px] bg-sky-50 border border-sky-200 text-sky-700 rounded px-1.5 py-0.5 hover:bg-sky-100 disabled:opacity-50">
                  ✎ {sug.suggestion}
                </button>
              )}
              {rx.softech_patient_name && rx.patient_name !== rx.softech_patient_name && (
                <button onClick={revertName} disabled={savingName}
                  title={`استرجاع اسم سوفتك الأصلي: ${rx.softech_patient_name}`}
                  className="text-[10px] bg-amber-50 border border-amber-200 text-amber-700 rounded px-1 py-0.5 disabled:opacity-50">
                  ↩
                </button>
              )}
            </span>
          )}
        </td>
        <td className="px-3 py-2 text-left font-mono text-gray-600">{fmt(local)}</td>
        <td className="px-3 py-2 text-left font-mono text-gray-600">{fmt(imported)}</td>
        <td className="px-3 py-2 text-left font-mono text-gray-600">{fmt(rx.effective_tarsia_before ?? rx.tarsia_before)}</td>
        <td className="px-3 py-2 text-left font-mono">{fmt(rx.gross_before)}</td>
        <td className="px-3 py-2 text-left font-mono font-semibold text-gray-900">
          {fmt(net)}
          {mismatch && (
            <span className="block text-[10px] font-normal text-amber-600">
              سوفتك {fmt(rx.softech_net)}
            </span>
          )}
        </td>
        <td className="px-3 py-2">
          {isAdjusted && <span className="text-xs bg-amber-100 text-amber-700 px-1.5 rounded">معدَّل</span>}
        </td>
        <td className="px-3 py-2">
          <div className="flex gap-1">
            <Btn onClick={async () => {
              if (!showLines && !lines) {
                setLinesLoading(true)
                try {
                  const { data } = await insuranceApi.prescriptionLines(claimId, rx.id)
                  setLines(data)
                } finally { setLinesLoading(false) }
              }
              setShowLines(s => !s)
            }} variant="secondary">
              {linesLoading ? '...' : showLines ? '▲' : '▼'} بنود
            </Btn>
            <Btn onClick={() => {
              setAdjForm({
                local_before:    Number(local).toFixed(2),
                imported_before: Number(imported).toFixed(2),
                tarsia_before:   Number(rx.effective_tarsia_before ?? rx.tarsia_before).toFixed(2),
                net_override:    '',
                reason: '',
              })
              setShowAdjust(true)
            }} variant="warning">تعديل</Btn>
            {isAdjusted && <Btn onClick={removeAdjust} variant="secondary">× إزالة التعديل</Btn>}
            <Btn onClick={toggleExclude} variant={isExcluded ? 'secondary' : 'danger'}>
              {isExcluded ? 'إعادة إدراج' : 'استثناء'}
            </Btn>
            {rx.is_manual && (
              <Btn variant="danger" onClick={async () => {
                if (!window.confirm('حذف هذه الروشتة المضافة يدوياً نهائياً؟')) return
                await insuranceApi.deleteManualPrescription(claimId, rx.id)
                onRefresh()
              }}>حذف يدوي</Btn>
            )}
          </div>
        </td>
      </tr>

      {/* Item lines drill-down */}
      {showLines && lines && (
        <tr>
          <td colSpan={12} className="bg-gray-50 px-6 py-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500">
                بنود الروشتة ({lines.length})
                {lines.filter(l => l.variance?.has_variance).length > 0 && (
                  <span className="text-amber-600 mr-2" title="أصناف بها فرق عن الكتالوج الحالى — عرض فقط، لا يظهر فى المستندات المصدَّرة">
                    · ⚠️ {lines.filter(l => l.variance?.has_variance).length} صنف يختلف عن الكتالوج
                  </span>
                )}
                {lines.filter(l => l.variance?.softech_class_mismatch).length > 0 && (
                  <span className="text-orange-600 mr-2" title="أصناف تصنيفنا لها يختلف عن تصنيف سوفتك الخام">
                    · ⚑ {lines.filter(l => l.variance?.softech_class_mismatch).length} صنف تصنيفه يخالف سوفتك
                  </span>
                )}
                {lines.filter(l => l.variance?.value_discrepancy).length > 0 && (
                  <span className="text-rose-600 mr-2" title="أصناف إجمالى قيمتها محسوب من كمية مُقرَّبة (٣ خانات) وقد يختلف عن سوفتك — راجعها">
                    · 💰 {lines.filter(l => l.variance?.value_discrepancy).length} صنف قيمته قد تخالف سوفتك
                  </span>
                )}
              </span>
              <button onClick={() => setEditLines(v => !v)}
                className={`text-xs rounded px-2 py-1 border ${editLines
                  ? 'bg-red-50 text-red-700 border-red-200'
                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}>
                {editLines ? '🔒 قفل التعديل' : '🔓 تفعيل تعديل البنود'}
              </button>
            </div>
            {mismatch && (
              <div className="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800 leading-relaxed">
                ⚑ صافى هذه الروشتة يختلف عن سوفتك بمقدار{' '}
                <b className="font-mono">{rx.softech_net_diff > 0 ? '+' : ''}{fmt(rx.softech_net_diff)}</b>{' '}
                (صافينا {fmt(net)} مقابل سوفتك {fmt(rx.softech_net)}).
                {lines.some(l => l.variance?.discount_discrepancy)
                  ? ' السبب أصناف بعينها 💸 طبّق سوفتك عليها خصماً يخالف نسبة الفئة الموحّدة — راجع البنود المعلَّمة أدناه. عرض فقط — لا يؤثر على التصدير.'
                  : lines.some(l => l.variance?.softech_class_mismatch)
                  ? ' الأصناف المعلَّمة ⚑ تصنيفها لدينا يخالف سوفتك — راجعها.'
                  : lines.some(l => l.variance?.softech_line_net != null)
                  ? ' لا يوجد بند مفرد يفسّر الفرق (فروق تقريب متراكمة). عرض فقط — لا يؤثر على التصدير.'
                  : ' الفرق ناتج عن خصم سوفتك على مستوى الصنف — شغّل «تحديث صافى سوفتك للبنود» لتحديد الصنف المسبّب بدقة.'}
              </div>
            )}
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b">
                  <th className="text-right pb-1">الكود</th>
                  <th className="text-right pb-1">الصنف</th>
                  <th className="text-right pb-1">التصنيف</th>
                  <th className="text-left pb-1">الكمية</th>
                  {editLines && <th className="text-left pb-1">السعر</th>}
                  <th className="text-left pb-1">الإجمالى</th>
                  <th className="text-left pb-1">الخصم</th>
                  <th className="text-left pb-1">الصافى</th>
                  {editLines && <th className="text-left pb-1"></th>}
                </tr>
              </thead>
              <tbody>
                {lines.map(l => {
                  const e = lineEdits[l.id] || {}
                  const catBadge = (cat) => (
                    <span className={`px-1.5 rounded text-xs ${
                      cat === 'local' ? 'bg-blue-50 text-blue-700' :
                      cat === 'imported' ? 'bg-purple-50 text-purple-700' : 'bg-teal-50 text-teal-700'}`}>
                      {cat === 'local' ? 'محلى' : cat === 'imported' ? 'مستورد' : 'ترسية'}
                    </span>
                  )
                  const setE = (patch) => setLineEdits(s => ({ ...s, [l.id]: { ...s[l.id], ...patch } }))
                  const v = l.variance
                  const hasDrift = v && v.has_variance                 // frozen vs current catalog
                  const hasSoftClass = v && v.softech_class_mismatch   // our class ≠ SOFTECH raw
                  const flagged = hasDrift || hasSoftClass
                  const driftTip = hasDrift ? [
                    v.cat_changed && `التصنيف: ${l.item_category_display || l.item_category} ← ${v.current_category_label}`,
                    v.price_changed && `السعر الحالى: ${fmt(v.current_unit_price)}`,
                    `فرق الصافى: ${v.net_delta > 0 ? '+' : ''}${fmt(v.net_delta)}`,
                  ].filter(Boolean).join(' · ') : ''
                  const hasValueDisc = v && v.value_discrepancy       // gross computed from rounded qty
                  const hasDiscDisc = v && v.discount_discrepancy    // our net ≠ SOFTECH's own line net
                  if (!editLines) {
                    return (
                      <tr key={l.id} className={`border-b border-gray-100 ${flagged || hasValueDisc || hasDiscDisc ? 'bg-amber-50' : ''}`}>
                        <td className="py-1 font-mono text-gray-500 text-[11px]">{l.softech_itemcode}</td>
                        <td className="py-1 text-gray-700">
                          {hasDrift && (
                            <span title={`صنف به فرق عن الكتالوج الحالى (عرض فقط — لا يؤثر على التصدير) — ${driftTip}`}
                              className="text-amber-500 ml-1">⚠️</span>
                          )}
                          {hasSoftClass && (
                            <span title={`تصنيفنا (${l.item_category_display || l.item_category}) يختلف عن تصنيف سوفتك الخام (${v.softech_raw_category_label}) — سبب محتمل لاختلاف الصافى عن سوفتك`}
                              className="text-orange-600 ml-1">⚑</span>
                          )}
                          {hasValueDisc && (
                            <span title="إجمالى هذا البند محسوب من كمية مُقرَّبة (٣ خانات) وقد يختلف عن قيمة سوفتك الحقيقية — راجعه واعتمده من تبويب مراجعة الفروق"
                              className="text-rose-600 ml-1">💰</span>
                          )}
                          {hasDiscDisc && (
                            <span title={`خصم سوفتك لهذا الصنف يختلف عن نسبة الفئة — صافينا ${fmt(l.net_amount)} مقابل سوفتك ${fmt(v.softech_line_net)} (فرق ${v.softech_net_diff > 0 ? '+' : ''}${fmt(v.softech_net_diff)}). هذا البند هو سبب اختلاف صافى الروشتة عن سوفتك.`}
                              className="text-rose-700 ml-1 font-bold">💸</span>
                          )}
                          {l.item_name}
                          {l.is_manually_edited && <span className="text-[10px] bg-purple-100 text-purple-700 px-1 rounded mr-1">مُعدَّل</span>}
                        </td>
                        <td className="py-1">
                          {catBadge(l.item_category)}
                          {hasDrift && v.cat_changed && (
                            <span className="text-[10px] text-amber-600 mr-1" title={`التصنيف الحالى فى الكتالوج: ${v.current_category_label}`}>
                              → {v.current_category_label}
                            </span>
                          )}
                          {hasSoftClass && (
                            <span className="text-[10px] text-orange-600 mr-1" title="تصنيف سوفتك الخام">
                              (سوفتك: {v.softech_raw_category_label})
                            </span>
                          )}
                        </td>
                        <td className="py-1 text-left">{l.quantity}</td>
                        <td className="py-1 text-left font-mono">{fmt(l.line_total)}</td>
                        <td className="py-1 text-left font-mono text-red-600">{fmt(l.discount_amt)} ({l.discount_pct}%)</td>
                        <td className="py-1 text-left font-mono font-semibold">{fmt(l.net_amount)}</td>
                      </tr>
                    )
                  }
                  return (
                    <tr key={l.id} className="border-b border-gray-100">
                      <td className="py-1">
                        <div className="flex gap-1 items-center">
                          <input value={e.item_code ?? l.softech_itemcode} placeholder="كود جديد"
                            onChange={ev => setE({ item_code: ev.target.value })}
                            className="w-20 border border-gray-300 rounded px-1 py-0.5 font-mono" />
                          <button onClick={() => lookupNewItem(l.id, (e.item_code ?? l.softech_itemcode).trim())}
                            className="text-blue-600 hover:underline">بحث</button>
                        </div>
                        {e.lookup && (e.lookup.found
                          ? <div className="text-[10px] text-gray-500">{e.lookup.item_name} · {fmt(e.lookup.pack_price)}</div>
                          : <div className="text-[10px] text-amber-600">غير موجود</div>)}
                      </td>
                      <td className="py-1 text-gray-700">{e.lookup?.found ? e.lookup.item_name : l.item_name}</td>
                      <td className="py-1">{catBadge(e.lookup?.found ? e.lookup.current_category : l.item_category)}</td>
                      <td className="py-1 text-left">
                        <input type="number" step="0.001" value={e.quantity ?? l.quantity}
                          onChange={ev => setE({ quantity: ev.target.value })}
                          className="w-16 border border-gray-300 rounded px-1 py-0.5 text-left" />
                      </td>
                      <td className="py-1 text-left">
                        <input type="number" step="0.001" value={e.unit_price ?? l.unit_price}
                          onChange={ev => setE({ unit_price: ev.target.value })}
                          className="w-20 border border-gray-300 rounded px-1 py-0.5 text-left" />
                      </td>
                      <td className="py-1 text-left font-mono">{fmt(l.line_total)}</td>
                      <td className="py-1 text-left font-mono text-red-600">{fmt(l.discount_amt)}</td>
                      <td className="py-1 text-left font-mono font-semibold">{fmt(l.net_amount)}</td>
                      <td className="py-1 text-left">
                        <div className="flex gap-1">
                          <button onClick={() => saveLine(l.id)} disabled={savingLine === l.id}
                            className="bg-blue-600 text-white rounded px-2 py-0.5 hover:bg-blue-700 disabled:opacity-50">
                            {savingLine === l.id ? '…' : 'حفظ'}
                          </button>
                          {l.is_manually_edited && (
                            <button onClick={() => resetLine(l.id)} disabled={savingLine === l.id}
                              className="text-gray-500 hover:text-gray-800">استرجاع</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {editLines && (
              <p className="text-[11px] text-amber-700 mt-2">
                ⚠️ وضع التعديل مُفعَّل — تغيير الكود يستبدل الصنف بسعره وتصنيفه الجديد من الكتالوج. غيّر الكمية أو السعر ثم اضغط حفظ. القيم الأصلية محفوظة (استرجاع).
              </p>
            )}
          </td>
        </tr>
      )}

      {/* Adjust Modal */}
      {showAdjust && (
        <tr>
          <td colSpan={12}>
            <div className="bg-amber-50 border-y border-amber-200 px-6 py-4">
              <p className="text-sm font-semibold text-amber-800 mb-3">تعديل قيم الروشتة</p>
              <div className="grid grid-cols-4 gap-3 mb-3">
                {[
                  ['محلى قبل الخصم', 'local_before'],
                  ['مستورد قبل الخصم', 'imported_before'],
                  ['ترسية قبل الخصم', 'tarsia_before'],
                  ['صافى الفاتورة (تجاوز مباشر)', 'net_override'],
                ].map(([label, key]) => (
                  <div key={key}>
                    <label className="text-xs text-gray-600 mb-1 block">{label}</label>
                    <input type="number" step="any"
                      className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                      value={adjForm[key]}
                      onChange={e => setAdjForm(p => ({ ...p, [key]: e.target.value }))} />
                  </div>
                ))}
              </div>
              <div className="mb-3">
                <label className="text-xs text-gray-600 mb-1 block">سبب التعديل *</label>
                <input type="text"
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                  value={adjForm.reason}
                  onChange={e => setAdjForm(p => ({ ...p, reason: e.target.value }))} />
              </div>
              <div className="flex gap-2">
                <Btn onClick={saveAdjust} disabled={saving || !adjForm.reason} variant="primary" size="md">
                  {saving ? 'جارٍ الحفظ...' : 'حفظ التعديل'}
                </Btn>
                <Btn onClick={() => setShowAdjust(false)} variant="secondary" size="md">إلغاء</Btn>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Manual Rx row (shown inside the الروشتات list, blue-flagged) ────────────────
// Manual receipts are aggregate values (no itemised lines), so their actions are
// confirmation-gated and clearly distinguished from real prescriptions.
function ManualRxRow({ mrx, claimId, onRefresh, onManage }) {
  const [showLines, setShowLines] = useState(false)
  const [showEdit, setShowEdit]   = useState(false)
  const [saving, setSaving]       = useState(false)
  const [form, setForm] = useState({ local_before: '', imported_before: '', tarsia_before: '', net_override: '' })

  const excluded = mrx.is_excluded

  const openEdit = () => {
    if (!window.confirm('⚠️ هذه روشتة مُضافة يدوياً. تعديل قيمها يدوياً سيغيّر إجمالى المطالبة. هل تريد المتابعة؟')) return
    setForm({
      local_before:    Number(mrx.local_before).toFixed(2),
      imported_before: Number(mrx.imported_before).toFixed(2),
      tarsia_before:   Number(mrx.tarsia_before).toFixed(2),
      net_override:    '',
    })
    setShowEdit(true)
  }

  async function save() {
    setSaving(true)
    try {
      const payload = {
        local_before: form.local_before, imported_before: form.imported_before,
        tarsia_before: form.tarsia_before,
      }
      if (form.net_override !== '') payload.net_override = form.net_override
      await insuranceApi.updateManualRx(claimId, mrx.id, payload)
      setShowEdit(false); onRefresh()
    } finally { setSaving(false) }
  }

  async function toggleExclude() {
    const msg = excluded
      ? 'إعادة إدراج هذه الروشتة اليدوية في المطالبة؟'
      : '⚠️ استثناء روشتة يدوية — ستُحذف قيمتها من إجمالى المطالبة (يمكن إعادة إدراجها). متابعة؟'
    if (!window.confirm(msg)) return
    await insuranceApi.updateManualRx(claimId, mrx.id, { is_excluded: !excluded })
    onRefresh()
  }

  async function revertName() {
    await insuranceApi.updateManualRx(claimId, mrx.id, { revert: true })
    onRefresh()
  }

  return (
    <>
      <tr className={`border-b border-blue-100 text-sm bg-blue-50/60 ${excluded ? 'opacity-40 line-through' : ''}`}>
        <td className="px-2 py-2"></td>
        <td className="px-3 py-2 text-blue-400 text-xs">—</td>
        <td className="px-3 py-2 text-xs text-gray-500">{mrx.print_date || mrx.softech_docdate || '—'}</td>
        <td className="px-3 py-2 text-xs font-mono text-gray-500">{mrx.softech_docnumber || '—'}</td>
        <td className="px-3 py-2 text-xs text-center text-gray-500">{mrx.softech_branchcode || '—'}</td>
        <td className="px-3 py-2 font-medium text-gray-800">
          <span className="text-[10px] bg-blue-600 text-white rounded px-1.5 py-0.5 ml-1">يدوي</span>
          {mrx.patient_name || '—'}
          {mrx.is_manually_edited && <span className="text-[10px] bg-purple-100 text-purple-700 px-1.5 rounded mr-1">مُعدَّلة يدوياً</span>}
          {mrx.softech_patient_name && mrx.patient_name !== mrx.softech_patient_name && (
            <button onClick={revertName}
              title={`استرجاع اسم سوفتك الأصلي: ${mrx.softech_patient_name}`}
              className="text-[10px] bg-amber-50 border border-amber-200 text-amber-700 rounded px-1.5 py-0.5 mr-1">
              ↩ اسم سوفتك
            </button>
          )}
        </td>
        <td className="px-3 py-2 text-left font-mono text-gray-600">{fmt(mrx.local_before)}</td>
        <td className="px-3 py-2 text-left font-mono text-gray-600">{fmt(mrx.imported_before)}</td>
        <td className="px-3 py-2 text-left font-mono text-gray-600">{fmt(mrx.tarsia_before)}</td>
        <td className="px-3 py-2 text-left font-mono">{fmt(mrx.gross_before)}</td>
        <td className="px-3 py-2 text-left font-mono font-semibold text-gray-900">{fmt(mrx.net_after)}</td>
        <td className="px-3 py-2">
          <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 rounded">إضافة يدوية</span>
        </td>
        <td className="px-3 py-2">
          <div className="flex gap-1">
            <Btn onClick={() => setShowLines(s => !s)} variant="secondary">{showLines ? '▲' : '▼'} بنود</Btn>
            <Btn onClick={openEdit} variant="warning">تعديل</Btn>
            <Btn onClick={onManage} variant="secondary">إدارة</Btn>
            <Btn onClick={toggleExclude} variant={excluded ? 'secondary' : 'danger'}>
              {excluded ? 'إعادة إدراج' : 'استثناء'}
            </Btn>
          </div>
        </td>
      </tr>

      {/* "بنود" — manual receipts have no itemised lines; show the aggregate split */}
      {showLines && (
        <tr>
          <td colSpan={12} className="bg-blue-50/40 px-6 py-3">
            <p className="text-xs text-blue-800 mb-2">
              ℹ️ روشتة مُضافة يدوياً — قيم مُجمّعة بلا بنود مفصّلة. التفصيل حسب التصنيف:
            </p>
            <div className="grid grid-cols-3 gap-3 max-w-lg text-xs">
              {[['محلى', mrx.local_before, mrx.local_discount],
                ['مستورد', mrx.imported_before, mrx.imported_discount],
                ['ترسية', mrx.tarsia_before, mrx.tarsia_discount]].map(([lbl, before, disc]) => (
                <div key={lbl} className="bg-white rounded border border-blue-100 p-2">
                  <div className="text-gray-500">{lbl}</div>
                  <div className="font-mono">قبل الخصم: {fmt(before)}</div>
                  <div className="font-mono text-red-600">الخصم: {fmt(disc)}</div>
                </div>
              ))}
            </div>
            <div className="mt-2 text-xs font-mono text-gray-700">
              الإجمالى {fmt(mrx.gross_before)} · إجمالى الخصم {fmt(mrx.total_discount)} · الصافى {fmt(mrx.net_after)}
            </div>
          </td>
        </tr>
      )}

      {/* Inline edit form */}
      {showEdit && (
        <tr>
          <td colSpan={12} className="bg-blue-50 px-6 py-3">
            <p className="text-xs font-semibold text-blue-900 mb-2">تعديل روشتة يدوية — عدّل التصنيف أو حدّد صافياً مباشرة</p>
            <div className="grid grid-cols-4 gap-3 max-w-2xl">
              {[['محلى قبل الخصم', 'local_before'], ['مستورد قبل الخصم', 'imported_before'],
                ['ترسية قبل الخصم', 'tarsia_before'], ['صافى مباشر (اختياري)', 'net_override']].map(([lbl, key]) => (
                <div key={key}>
                  <label className="block text-xs text-gray-600 mb-1">{lbl}</label>
                  <input type="number" step="any" value={form[key]}
                    onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                </div>
              ))}
            </div>
            <p className="text-[11px] text-gray-500 mt-1">
              إن تركت "الصافى المباشر" فارغاً يُحتسب تلقائياً: محلى×{'(1−'}نسبة المحلى{')'} + مستورد×… (معادلة Power Query).
            </p>
            <div className="flex gap-2 mt-2">
              <Btn onClick={save} disabled={saving} variant="primary" size="md">{saving ? 'جارٍ الحفظ…' : 'حفظ التعديل'}</Btn>
              <Btn onClick={() => setShowEdit(false)} variant="secondary" size="md">إلغاء</Btn>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Supplement row (بنود / تعديل / استثناء, confirmation-gated) ─────────────────
// Supplements are aggregate blocks (no itemised lines), like manual receipts.
function SupplementRow({ sup, claimId, supTypeLabel, rates, onChanged, onDelete }) {
  const [showLines, setShowLines] = useState(false)
  const [showEdit, setShowEdit]   = useState(false)
  const [saving, setSaving]       = useState(false)
  const [form, setForm] = useState({ label: '', local_before: '', imported_before: '', tarsia_before: '' })
  const excluded = sup.is_excluded

  const openEdit = () => {
    if (!window.confirm('⚠️ هذا ملحق مُدخَل يدوياً. تعديل قيمه سيغيّر إجمالى المطالبة. هل تريد المتابعة؟')) return
    setForm({
      label: sup.label || '',
      local_before:    Number(sup.local_before).toFixed(2),
      imported_before: Number(sup.imported_before).toFixed(2),
      tarsia_before:   Number(sup.tarsia_before).toFixed(2),
    })
    setShowEdit(true)
  }

  async function save() {
    setSaving(true)
    try {
      await insuranceApi.updateSupplement(claimId, sup.id, {
        label: form.label,
        local_before: form.local_before, imported_before: form.imported_before, tarsia_before: form.tarsia_before,
      })
      setShowEdit(false); onChanged()
    } finally { setSaving(false) }
  }

  async function toggleExclude() {
    const msg = excluded
      ? 'إعادة إدراج هذا الملحق في المطالبة؟'
      : '⚠️ استثناء ملحق — ستُحذف قيمته من إجمالى المطالبة (يمكن إعادة إدراجه). متابعة؟'
    if (!window.confirm(msg)) return
    await insuranceApi.updateSupplement(claimId, sup.id, { is_excluded: !excluded })
    onChanged()
  }

  const previewNet = (() => {
    const g = Number(form.local_before||0) + Number(form.imported_before||0) + Number(form.tarsia_before||0)
    const d = (Number(form.local_before||0)*rates.local + Number(form.imported_before||0)*rates.imported + Number(form.tarsia_before||0)*rates.tarsia) / 100
    return g - d
  })()

  return (
    <div className={`bg-white border rounded-lg ${excluded ? 'border-gray-200 opacity-50' : 'border-blue-200'}`}>
      <div className="p-3 flex justify-between items-center">
        <div className={excluded ? 'line-through' : ''}>
          <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 rounded mr-2">
            {supTypeLabel[sup.supplement_type] || sup.supplement_type}
          </span>
          <span className="font-medium text-gray-800">{sup.label}</span>
          {sup.print_date && <span className="text-xs text-gray-400 mr-2">{sup.print_date}</span>}
          {sup.is_manually_edited && <span className="text-[10px] bg-purple-100 text-purple-700 px-1.5 rounded mr-1">مُعدَّل يدوياً</span>}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-mono text-gray-600">{fmt(sup.gross_before)} → <span className="font-semibold">{fmt(sup.net_after)}</span></span>
          <Btn variant="secondary" onClick={() => setShowLines(s => !s)}>{showLines ? '▲' : '▼'} بنود</Btn>
          <Btn variant="warning" onClick={openEdit}>تعديل</Btn>
          <Btn variant={excluded ? 'secondary' : 'danger'} onClick={toggleExclude}>
            {excluded ? 'إعادة إدراج' : 'استثناء'}
          </Btn>
          <Btn variant="danger" onClick={onDelete}>حذف</Btn>
        </div>
      </div>

      {showLines && (
        <div className="border-t border-blue-100 bg-blue-50/40 px-4 py-3">
          <p className="text-xs text-blue-800 mb-2">ℹ️ ملحق مُجمّع بلا بنود مفصّلة. التفصيل حسب التصنيف:</p>
          <div className="grid grid-cols-3 gap-3 max-w-lg text-xs">
            {[['محلى', sup.local_before, sup.local_discount],
              ['مستورد', sup.imported_before, sup.imported_discount],
              ['ترسية', sup.tarsia_before, sup.tarsia_discount]].map(([lbl, before, disc]) => (
              <div key={lbl} className="bg-white rounded border border-blue-100 p-2">
                <div className="text-gray-500">{lbl}</div>
                <div className="font-mono">قبل الخصم: {fmt(before)}</div>
                <div className="font-mono text-red-600">الخصم: {fmt(disc)}</div>
              </div>
            ))}
          </div>
          <div className="mt-2 text-xs font-mono text-gray-700">
            عدد الروشتات {sup.rx_count} · الإجمالى {fmt(sup.gross_before)} · إجمالى الخصم {fmt(sup.total_discount)} · الصافى {fmt(sup.net_after)}
          </div>
        </div>
      )}

      {showEdit && (
        <div className="border-t border-blue-100 bg-blue-50 px-4 py-3">
          <p className="text-xs font-semibold text-blue-900 mb-2">تعديل ملحق — الصافى يُحتسب تلقائياً من التصنيف</p>
          <div className="grid grid-cols-4 gap-3 max-w-3xl">
            <div>
              <label className="block text-xs text-gray-600 mb-1">التسمية</label>
              <input value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>
            {[['محلى قبل الخصم', 'local_before'], ['مستورد قبل الخصم', 'imported_before'], ['ترسية قبل الخصم', 'tarsia_before']].map(([lbl, key]) => (
              <div key={key}>
                <label className="block text-xs text-gray-600 mb-1">{lbl}</label>
                <input type="number" step="any" value={form[key]}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
            ))}
          </div>
          <p className="text-[11px] text-gray-500 mt-1">
            الصافى المتوقع: <span className="font-mono">{fmt(previewNet)}</span> (محلى {rates.local}% · مستورد {rates.imported}% · ترسية {rates.tarsia}%)
          </p>
          <div className="flex gap-2 mt-2">
            <Btn onClick={save} disabled={saving} variant="primary" size="md">{saving ? 'جارٍ الحفظ…' : 'حفظ التعديل'}</Btn>
            <Btn onClick={() => setShowEdit(false)} variant="secondary" size="md">إلغاء</Btn>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Supplements Tab ────────────────────────────────────────────────────────────
function SupplementsTab({ claimId, claim, onRefresh }) {
  const [sups, setSups]     = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm]     = useState({
    supplement_type: 'before_claim',
    label: 'ملحق يوميات',
    print_date: '',
    rx_count: 1,
    local_before: 0, imported_before: 0, tarsia_before: 0,
    notes: '',
  })
  const [addError, setAddError] = useState(null)

  const load = () => insuranceApi.supplements(claimId).then(r => setSups(r.data))

  useEffect(() => { load() }, [claimId])

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))

  // Live preview of computed totals (server recomputes identically from rates)
  const rates = {
    local:    Number(claim?.applied_local_disc_pct || 0),
    imported: Number(claim?.applied_imported_disc_pct || 0),
    tarsia:   Number(claim?.applied_tarsia_disc_pct || 0),
  }
  const previewGross = Number(form.local_before||0) + Number(form.imported_before||0) + Number(form.tarsia_before||0)
  const previewDisc  = (Number(form.local_before||0)*rates.local + Number(form.imported_before||0)*rates.imported + Number(form.tarsia_before||0)*rates.tarsia) / 100
  const previewNet   = previewGross - previewDisc

  const addSup = async () => {
    setAddError(null)
    // within_claim must have a print_date; before/after send null (computed at edges)
    if (form.supplement_type === 'within_claim' && !form.print_date) {
      setAddError('حدد تاريخ اليوم الذي سيُطبع تحته الملحق')
      return
    }
    try {
      await insuranceApi.addSupplement(claimId, {
        ...form,
        print_date: form.print_date || null,
      })
      setShowAdd(false)
      setForm({
        supplement_type: 'before_claim', label: 'ملحق يوميات', print_date: '',
        rx_count: 1, local_before: 0, imported_before: 0, tarsia_before: 0, notes: '',
      })
      load(); onRefresh()
    } catch (e) {
      setAddError(e.response?.data?.error || JSON.stringify(e.response?.data) || 'تعذّر حفظ الملحق')
    }
  }

  const delSup = async (id) => {
    await insuranceApi.deleteSupplement(claimId, id)
    load()
    onRefresh()
  }

  const supTypeLabel = {
    before_claim: 'ملحق سابق', within_claim: 'ملحق يوم',
    after_claim: 'ملحق لاحق', standalone: 'ملحق مستقل',
  }

  const inp = 'w-full border border-gray-300 rounded px-2 py-1.5 text-sm'

  return (
    <div className="p-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold text-gray-700">الملاحق ({sups.length})</h3>
        <Btn onClick={() => setShowAdd(!showAdd)} size="md">+ إضافة ملحق</Btn>
      </div>

      {showAdd && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div>
              <label className="text-xs text-gray-600 mb-1 block">نوع الملحق</label>
              <select className={inp} value={form.supplement_type} onChange={e => set('supplement_type', e.target.value)}>
                {Object.entries(supTypeLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">التسمية</label>
              <input className={inp} value={form.label} onChange={e => set('label', e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">تاريخ الطباعة</label>
              <input type="date" className={inp} value={form.print_date} onChange={e => set('print_date', e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-4 gap-3 mb-3">
            {[
              ['محلى قبل الخصم', 'local_before'], ['مستورد قبل الخصم', 'imported_before'],
              ['ترسية قبل الخصم', 'tarsia_before'], ['عدد الروشتات', 'rx_count'],
            ].map(([label, key]) => (
              <div key={key}>
                <label className="text-xs text-gray-600 mb-1 block">{label}</label>
                <input type="number" step="any" className={inp}
                  value={form[key]} onChange={e => set(key, e.target.value)} />
              </div>
            ))}
          </div>
          {/* Computed preview — gross/discount/net derived from contract rates */}
          <div className="flex gap-6 mb-3 text-sm bg-white border border-gray-200 rounded px-3 py-2">
            <span className="text-gray-500">الإجمالى: <span className="font-mono text-gray-800">{fmt(previewGross)}</span></span>
            <span className="text-gray-500">الخصم: <span className="font-mono text-red-600">{fmt(previewDisc)}</span></span>
            <span className="text-gray-500">الصافى: <span className="font-mono font-semibold text-gray-900">{fmt(previewNet)}</span></span>
            <span className="text-xs text-gray-400 self-center">
              (يُحتسب تلقائياً: محلى {rates.local}% · مستورد {rates.imported}% · ترسية {rates.tarsia}%)
            </span>
          </div>
          {addError && <p className="text-red-600 text-sm mb-2">{addError}</p>}
          <div className="flex gap-2">
            <Btn onClick={addSup} size="md">حفظ الملحق</Btn>
            <Btn onClick={() => setShowAdd(false)} variant="secondary" size="md">إلغاء</Btn>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {sups.map(s => (
          <SupplementRow key={s.id} sup={s} claimId={claimId}
            supTypeLabel={supTypeLabel} rates={rates}
            onChanged={() => { load(); onRefresh() }}
            onDelete={() => delSup(s.id)} />
        ))}
        {sups.length === 0 && <p className="text-gray-400 text-sm text-center py-8">لا توجد ملاحق</p>}
      </div>
    </div>
  )
}

// ── Manual Rx Tab ──────────────────────────────────────────────────────────────
function ManualRxTab({ claimId, claim, onRefresh }) {
  const [manualRx, setManualRx] = useState([])
  const [docnumber, setDocnumber] = useState('')
  const [lookupResult, setLookupResult] = useState(null)
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lookupError, setLookupError] = useState(null)
  const [addError, setAddError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [override, setOverride] = useState('')   // '' = automatic
  const [printDate, setPrintDate] = useState('')
  const [mode, setMode] = useState('simple')     // 'simple' totals-only | 'detailed' full prescription
  const [patientName, setPatientName] = useState('')  // editable, autocomplete-backed (exact ID-card spelling)

  const load = () => {
    insuranceApi.claimDetail(claimId).then(r => setManualRx(r.data.manual_rx || []))
  }
  useEffect(() => { load() }, [claimId])

  const lookup = async () => {
    if (!docnumber) return
    setLookupLoading(true); setLookupError(null); setLookupResult(null); setAddError(null)
    try {
      const { data } = await insuranceApi.lookupRx(claimId, docnumber)
      setLookupResult(data)
      setPatientName(data.patient_name || '')
      setOverride(''); setPrintDate('')
    } catch (e) {
      setLookupError(e.response?.data?.error || 'لم يتم العثور على الفاتورة')
    } finally { setLookupLoading(false) }
  }

  // Auto-placement preview: where will this Rx land, based on its date?
  const autoPlacement = (() => {
    if (!lookupResult?.softech_docdate || !claim) return null
    const d = lookupResult.softech_docdate
    if (claim.period_from && d < claim.period_from)
      return { kind: 'before', text: `ملحق سابق (قبل ${claim.period_from})` }
    if (claim.period_to && d > claim.period_to)
      return { kind: 'after', text: `ملحق لاحق (بعد ${claim.period_to})` }
    return { kind: 'date', text: `ضمن يوم ${d}` }
  })()

  const addRx = async () => {
    setAdding(true); setAddError(null)
    try {
      await insuranceApi.addManualRx(claimId, {
        softech_docnumber: docnumber,
        branchcode: lookupResult?.softech_branchcode || '',
        position: override || undefined,          // undefined → server auto-derives
        print_date: override === 'date' ? (printDate || lookupResult?.softech_docdate) : null,
        mode,                                     // 'simple' totals-only | 'detailed' full prescription
        patient_name: (patientName || '').trim() || undefined,  // override → exact ID-card spelling
        reason: '',
      })
      setDocnumber(''); setLookupResult(null); setOverride(''); setPrintDate(''); setPatientName('')
      load(); onRefresh()
    } catch (e) {
      setAddError(e.response?.data?.error || 'تعذّرت الإضافة')
    } finally { setAdding(false) }
  }

  const removeRx = async (id) => {
    await insuranceApi.removeManualRx(claimId, id)
    load(); onRefresh()
  }

  const posLabels = { before: 'ملحق سابق', after: 'ملحق لاحق', date: 'يوم محدد' }

  return (
    <div className="p-4">
      <h3 className="font-semibold text-gray-700 mb-1">إضافة روشتة يدوياً من سوفتك</h3>
      <p className="text-xs text-gray-500 mb-4">
        أدخل رقم فاتورة تأمينية — حتى لو كانت تخص كود عميل آخر. تُوضع تلقائياً في يوم
        صرفها داخل المطالبة، أو كملحق سابق/لاحق إذا كان تاريخها خارج فترة المطالبة.
      </p>

      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4">
        <div className="flex gap-3 mb-3">
          <div className="flex-1">
            <label className="text-xs text-gray-600 mb-1 block">رقم الفاتورة في سوفتك</label>
            <input type="text"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={docnumber} onChange={e => setDocnumber(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && lookup()}
              placeholder="أدخل رقم الفاتورة..." />
          </div>
          <div className="self-end">
            <Btn onClick={lookup} disabled={lookupLoading} size="md">
              {lookupLoading ? 'جارٍ البحث...' : 'بحث'}
            </Btn>
          </div>
        </div>

        {lookupError && <p className="text-red-600 text-sm">{lookupError}</p>}

        {lookupResult && (
          <div className="bg-white border border-gray-200 rounded p-3 mt-2">
            {lookupResult.original_client_warning && (
              <div className="mb-2 p-2 bg-amber-50 border border-amber-200 text-amber-700 text-xs rounded">
                ⚠️ {lookupResult.original_client_warning}
              </div>
            )}
            <div className="grid grid-cols-3 gap-3 text-sm mb-3">
              <div className="col-span-3 flex items-center gap-2">
                <span className="text-gray-500 text-xs shrink-0">المريض:</span>
                <PatientNameAutocomplete
                  claimId={claimId}
                  value={patientName}
                  onChange={setPatientName}
                  className="border border-gray-300 rounded px-2 py-1 text-sm w-64" />
                <span className="text-[10px] text-gray-400">اكتب الاسم رباعياً كما فى البطاقة تماماً</span>
              </div>
              <div><span className="text-gray-500 text-xs">التاريخ:</span> {lookupResult.softech_docdate}</div>
              <div><span className="text-gray-500 text-xs">الصافى:</span> <span className="font-mono font-semibold">{fmt(lookupResult.net_after)}</span></div>
              <div><span className="text-gray-500 text-xs">محلى:</span> {fmt(lookupResult.local_before)}</div>
              <div><span className="text-gray-500 text-xs">مستورد:</span> {fmt(lookupResult.imported_before)}</div>
              <div><span className="text-gray-500 text-xs">الفرع:</span> {lookupResult.softech_branchcode}</div>
            </div>

            {/* Add mode: totals-only vs full item detail */}
            <div className="mb-3">
              <label className="text-xs text-gray-600 mb-1 block">طريقة الإضافة</label>
              <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden text-xs">
                <button type="button" onClick={() => setMode('simple')}
                  className={`px-3 py-1.5 ${mode === 'simple' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                  إجمالى فقط
                </button>
                <button type="button" onClick={() => setMode('detailed')}
                  className={`px-3 py-1.5 border-r border-gray-300 ${mode === 'detailed' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                  تفصيلى بالأصناف
                </button>
              </div>
              <p className="text-[11px] text-gray-500 mt-1">
                {mode === 'detailed'
                  ? `📋 ستُضاف كروشتة كاملة (${lookupResult.lines?.length ?? '؟'} صنف) تظهر في «الروشتات» و«أصناف المطالبة» و«فحص الفروقات» و«فصل الأسماء»، ويمكن تعديل أصنافها بندًا بندًا (🔓 تفعيل تعديل البنود).`
                  : 'ℹ️ ستُضاف بإجمالياتها فقط (محلى/مستورد/ترسية) كما كان سابقاً.'}
              </p>
            </div>

            {/* Auto-placement preview */}
            {autoPlacement && override === '' && (
              <div className="mb-3 p-2 bg-blue-50 border border-blue-200 text-blue-700 text-xs rounded">
                📍 سيتم وضعها تلقائياً: <strong>{autoPlacement.text}</strong>
              </div>
            )}

            <div className="flex gap-3 items-end flex-wrap">
              <div>
                <label className="text-xs text-gray-600 mb-1 block">الموضع</label>
                <select className="border border-gray-300 rounded px-2 py-1.5 text-sm"
                  value={override} onChange={e => setOverride(e.target.value)}>
                  <option value="">تلقائي (حسب التاريخ)</option>
                  {Object.entries(posLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              {override === 'date' && (
                <div>
                  <label className="text-xs text-gray-600 mb-1 block">تاريخ الطباعة</label>
                  <input type="date"
                    className="border border-gray-300 rounded px-2 py-1.5 text-sm"
                    value={printDate || lookupResult.softech_docdate || ''}
                    onChange={e => setPrintDate(e.target.value)} />
                </div>
              )}
              <Btn onClick={addRx} variant="success" size="md" disabled={adding}>
                {adding ? 'جارٍ الإضافة...' : 'إضافة للمطالبة'}
              </Btn>
            </div>
            {addError && <p className="text-red-600 text-sm mt-2">{addError}</p>}
          </div>
        )}
      </div>

      {(() => {
        const detailed = (claim?.prescriptions || []).filter(p => p.is_manual)
        const total = manualRx.length + detailed.length
        return (
          <div className="space-y-2">
            {detailed.length > 0 && (
              <div className="text-xs font-semibold text-gray-600 mb-1">
                إضافات تفصيلية (كروشتة كاملة) — {detailed.length} · تُعدَّل وتُحذف من تبويب «الروشتات»
              </div>
            )}
            {detailed.map(rx => (
              <div key={`d${rx.id}`} className="bg-indigo-50/50 border border-indigo-200 rounded-lg p-3 flex justify-between items-center">
                <div>
                  <span className="text-[10px] bg-indigo-600 text-white px-1.5 py-0.5 rounded mr-2">تفصيلى</span>
                  <span className="font-mono text-xs text-gray-500 mr-2">#{rx.softech_docnumber}</span>
                  <span className="font-medium text-gray-800">{rx.patient_name || '—'}</span>
                  <span className="text-xs text-gray-400 mr-2">{rx.softech_docdate} · فرع {rx.softech_branchcode}</span>
                </div>
                <span className="font-mono text-sm font-semibold">{fmt(rx.net_after)}</span>
              </div>
            ))}
            {manualRx.length > 0 && detailed.length > 0 && (
              <div className="text-xs font-semibold text-gray-600 mt-3 mb-1">إضافات بالإجمالى فقط — {manualRx.length}</div>
            )}
            {manualRx.map(mrx => (
              <div key={mrx.id} className="bg-white border border-gray-200 rounded-lg p-3 flex justify-between items-center">
                <div>
                  <span className="text-xs bg-purple-50 text-purple-700 px-2 rounded mr-2">
                    {posLabels[mrx.position] || mrx.position}
                    {mrx.position === 'date' && mrx.print_date ? ` ${mrx.print_date}` : ''}
                  </span>
                  <span className="font-mono text-xs text-gray-500 mr-2">#{mrx.softech_docnumber}</span>
                  <span className="font-medium text-gray-800">{mrx.patient_name || '—'}</span>
                  <span className="text-xs text-gray-400 mr-2">{mrx.softech_docdate}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold">{fmt(mrx.net_after)}</span>
                  <Btn variant="danger" onClick={() => removeRx(mrx.id)}>حذف</Btn>
                </div>
              </div>
            ))}
            {total === 0 && <p className="text-gray-400 text-sm text-center py-6">لا توجد روشتات مضافة يدوياً</p>}
          </div>
        )
      })()}
    </div>
  )
}

// ── Payments Tab ───────────────────────────────────────────────────────────────
function PaymentsTab({ claim, onRefresh }) {
  const [payments, setPayments]     = useState(claim.payments || [])
  const [deductions, setDeductions] = useState(claim.deductions || [])
  const [form, setForm]             = useState({ payment_date: '', amount: '', reference: '', notes: '' })
  const [dedForm, setDedForm]       = useState({ reason_code: 'other', reason_detail: '', amount: '', item_name: '' })

  const totalPaid     = payments.reduce((s, p) => s + Number(p.amount), 0)
  const totalDeducted = deductions.reduce((s, d) => s + Number(d.amount), 0)
  const balance       = Number(claim.final_net_after) - totalPaid - totalDeducted

  const addPayment = async () => {
    await insuranceApi.addPayment(claim.id, form)
    const { data } = await insuranceApi.claimDetail(claim.id)
    setPayments(data.payments || [])
    setForm({ payment_date: '', amount: '', reference: '', notes: '' })
    onRefresh()
  }

  const addDeduction = async () => {
    await insuranceApi.addDeduction(claim.id, dedForm)
    const { data } = await insuranceApi.claimDetail(claim.id)
    setDeductions(data.deductions || [])
    setDedForm({ reason_code: 'other', reason_detail: '', amount: '', item_name: '' })
    onRefresh()
  }

  const inp = 'w-full border border-gray-300 rounded px-2 py-1.5 text-sm'

  return (
    <div className="p-4 grid grid-cols-2 gap-6">
      {/* Payments */}
      <div>
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold text-gray-700">التحصيلات</h3>
          <span className="text-sm font-mono font-semibold text-green-700">{fmt(totalPaid)} ج.م</span>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-3 space-y-2">
          <input type="date" className={inp} value={form.payment_date} onChange={e => setForm(p => ({...p, payment_date: e.target.value}))} />
          <input type="number" step="any" placeholder="المبلغ" className={inp} value={form.amount} onChange={e => setForm(p => ({...p, amount: e.target.value}))} />
          <input placeholder="رقم التحويل / الشيك" className={inp} value={form.reference} onChange={e => setForm(p => ({...p, reference: e.target.value}))} />
          <Btn onClick={addPayment} disabled={!form.payment_date || !form.amount} size="md">+ تسجيل دفعة</Btn>
        </div>
        {payments.map(p => (
          <div key={p.id} className="border-b border-gray-100 py-2 flex justify-between text-sm">
            <div>
              <span className="font-mono text-green-700 font-semibold">{fmt(p.amount)}</span>
              <span className="text-gray-400 text-xs mr-2">{p.payment_date}</span>
              {p.reference && <span className="text-gray-400 text-xs mr-1">#{p.reference}</span>}
            </div>
          </div>
        ))}
      </div>

      {/* Deductions */}
      <div>
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold text-gray-700">الخصومات / المرفوضات</h3>
          <span className="text-sm font-mono font-semibold text-red-600">{fmt(totalDeducted)} ج.م</span>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-3 space-y-2">
          <select className={inp} value={dedForm.reason_code} onChange={e => setDedForm(p => ({...p, reason_code: e.target.value}))}>
            <option value="not_covered">صنف غير مشمول</option>
            <option value="duplicate">روشتة مكررة</option>
            <option value="over_limit">تجاوز الحد المسموح</option>
            <option value="missing_docs">وثائق ناقصة</option>
            <option value="classification">خطأ في التصنيف</option>
            <option value="other">أخرى</option>
          </select>
          <input placeholder="الصنف المرفوض (اختياري)" className={inp} value={dedForm.item_name} onChange={e => setDedForm(p => ({...p, item_name: e.target.value}))} />
          <input placeholder="التفاصيل" className={inp} value={dedForm.reason_detail} onChange={e => setDedForm(p => ({...p, reason_detail: e.target.value}))} />
          <input type="number" step="any" placeholder="قيمة الخصم" className={inp} value={dedForm.amount} onChange={e => setDedForm(p => ({...p, amount: e.target.value}))} />
          <Btn onClick={addDeduction} disabled={!dedForm.amount} variant="danger" size="md">+ تسجيل خصم</Btn>
        </div>
        {deductions.map(d => (
          <div key={d.id} className="border-b border-gray-100 py-2 flex justify-between text-sm">
            <div>
              <span className="font-mono text-red-600 font-semibold">{fmt(d.amount)}</span>
              <span className="text-gray-500 text-xs mr-2">{d.reason_detail || d.reason_display}</span>
            </div>
          </div>
        ))}
        <div className="mt-4 pt-3 border-t border-gray-200">
          <div className="flex justify-between text-sm font-semibold">
            <span>الرصيد المتبقي:</span>
            <span className={balance > 0 ? 'text-amber-700' : 'text-green-700'}>{fmt(balance)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Billing Groups Tab ───────────────────────────────────────────────────────
// Split a claim into sub-categories (sub-personcodes) and export each separately.
function BillingGroupsTab({ claim, claimId, onRefresh }) {
  const [groups, setGroups]   = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [exporting, setExporting] = useState(null)
  const [assignTarget, setAssignTarget] = useState(null)  // group id for rx-assign panel
  const [selectedRx, setSelectedRx] = useState(new Set())
  const [form, setForm] = useState({
    code: '', name: '', description: '',
    filter_relative_degree: '', filter_dept_name: '',
    filter_hi_type_code: '', filter_patient_no_prefix: '',
  })

  const inp = 'w-full border border-gray-300 rounded px-3 py-1.5 text-sm'

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await insuranceApi.billingGroups(claimId)
      setGroups(data.results || data)
    } finally { setLoading(false) }
  }, [claimId])

  useEffect(() => { load() }, [load])

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))

  async function addGroup() {
    if (!form.code || !form.name) { alert('الكود والاسم مطلوبان'); return }
    await insuranceApi.createBillingGroup({ ...form, claim: claimId })
    setForm({ code: '', name: '', description: '', filter_relative_degree: '',
              filter_dept_name: '', filter_hi_type_code: '', filter_patient_no_prefix: '' })
    setShowAdd(false)
    load()
  }

  async function delGroup(id) {
    if (!window.confirm('حذف فئة الفوترة؟ سيتم إلغاء تخصيص روشتاتها.')) return
    await insuranceApi.deleteBillingGroup(id)
    load(); onRefresh()
  }

  async function autoAssign(id) {
    const { data } = await insuranceApi.autoAssignGroup(id)
    alert(`تم تخصيص ${data.assigned} روشتة تلقائياً حسب الفلاتر`)
    load(); onRefresh()
  }

  async function exportGroup(id, name) {
    setExporting(id)
    try {
      const { data } = await insuranceApi.exportGroup(id, 'all')
      const blob = new Blob([data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url  = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href  = url
      link.download = `مطالبة_${claim?.claim_number || claimId}_${name}.xlsx`
      document.body.appendChild(link); link.click(); document.body.removeChild(link)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      alert('فشل التصدير: ' + (e?.message || 'خطأ'))
    } finally { setExporting(null) }
  }

  async function saveAssignment() {
    if (!assignTarget || selectedRx.size === 0) return
    const keys = Array.from(selectedRx)
    const rxIds     = keys.filter(k => k.startsWith('p')).map(k => Number(k.slice(1)))
    const manualIds = keys.filter(k => k.startsWith('m')).map(k => Number(k.slice(1)))
    const supIds    = keys.filter(k => k.startsWith('s')).map(k => Number(k.slice(1)))
    await insuranceApi.assignRxToGroup(assignTarget, rxIds, manualIds, supIds)
    setAssignTarget(null); setSelectedRx(new Set())
    load(); onRefresh()
  }

  const degreeOptions = ['', 'للعضو', 'للزوجة', 'للزوج', 'للأبناء', 'للوالدين']
  const allRx = claim?.prescriptions || []
  const allManual = claim?.manual_rx || []
  const allSup = (claim?.supplements || []).filter(s => s.supplement_type !== 'standalone')
  const unassignedRx     = allRx.filter(r => !r.billing_group)
  const unassignedManual = allManual.filter(m => !m.billing_group)
  const unassignedSup    = allSup.filter(s => !s.billing_group)
  const unassignedCount  = unassignedRx.length + unassignedManual.length + unassignedSup.length
  const totalNet = groups.reduce((s, g) => s + Number(g.net_after || 0), 0)

  return (
    <div className="p-4">
      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="font-semibold text-gray-700">فئات الفوترة (تقسيم المطالبة)</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            قسّم المطالبة إلى فئات فرعية، خصّص الروشتات لكل فئة، ثم صدّر فاتورة منفصلة لكل فئة.
            <span className="text-amber-600 mr-2">غير مخصص: {unassignedCount} روشتة</span>
          </p>
        </div>
        <Btn onClick={() => setShowAdd(!showAdd)} size="md">+ فئة جديدة</Btn>
      </div>

      {showAdd && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4">
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div>
              <label className="text-xs text-gray-600 mb-1 block">كود الفئة *</label>
              <input className={inp} value={form.code} onChange={e => set('code', e.target.value)} placeholder="مثال: CASH, INS" />
            </div>
            <div className="col-span-2">
              <label className="text-xs text-gray-600 mb-1 block">اسم الفئة *</label>
              <input className={inp} value={form.name} onChange={e => set('name', e.target.value)} placeholder="مثال: نقدي، تأمين صحي" />
            </div>
          </div>
          <p className="text-xs font-semibold text-gray-500 mb-2">قواعد التخصيص التلقائي (اختياري):</p>
          <div className="grid grid-cols-4 gap-3 mb-3">
            <div>
              <label className="text-xs text-gray-600 mb-1 block">درجة القرابة</label>
              <select className={inp} value={form.filter_relative_degree} onChange={e => set('filter_relative_degree', e.target.value)}>
                {degreeOptions.map(d => <option key={d} value={d}>{d || '— أي —'}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">الإدارة</label>
              <input className={inp} value={form.filter_dept_name} onChange={e => set('filter_dept_name', e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">نوع التأمين</label>
              <input className={inp} value={form.filter_hi_type_code} onChange={e => set('filter_hi_type_code', e.target.value)} maxLength={1} />
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">بادئة رقم المريض</label>
              <input className={inp} value={form.filter_patient_no_prefix} onChange={e => set('filter_patient_no_prefix', e.target.value)} />
            </div>
          </div>
          <div className="flex gap-2">
            <Btn onClick={addGroup} size="md">حفظ الفئة</Btn>
            <Btn onClick={() => setShowAdd(false)} variant="secondary" size="md">إلغاء</Btn>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-gray-400 text-sm text-center py-8">جارٍ التحميل...</p>
      ) : groups.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-8">لا توجد فئات فوترة — أنشئ فئة لتقسيم المطالبة</p>
      ) : (
        <div className="space-y-2">
          {groups.map(g => (
            <div key={g.id} className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-semibold text-purple-700 bg-purple-50 px-2 py-0.5 rounded">{g.code}</span>
                    <span className="font-medium text-gray-800">{g.name}</span>
                  </div>
                  {(g.filter_relative_degree || g.filter_dept_name || g.filter_hi_type_code || g.filter_patient_no_prefix) && (
                    <p className="text-xs text-gray-400 mt-1">
                      فلاتر: {[
                        g.filter_relative_degree && `قرابة=${g.filter_relative_degree}`,
                        g.filter_dept_name && `إدارة=${g.filter_dept_name}`,
                        g.filter_hi_type_code && `تأمين=${g.filter_hi_type_code}`,
                        g.filter_patient_no_prefix && `بادئة=${g.filter_patient_no_prefix}`,
                      ].filter(Boolean).join(' ، ')}
                    </p>
                  )}
                  <div className="flex gap-4 mt-2 text-sm">
                    <span className="text-gray-500">{g.rx_count} روشتة</span>
                    <span className="font-mono text-gray-600">إجمالى {fmt(g.gross_before)}</span>
                    <span className="font-mono text-red-600">خصم {fmt(g.total_discount)}</span>
                    <span className="font-mono font-semibold text-gray-900">صافى {fmt(g.net_after)}</span>
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <div className="flex gap-1.5">
                    <Btn onClick={() => autoAssign(g.id)} variant="secondary">تخصيص تلقائي</Btn>
                    <Btn onClick={() => { setAssignTarget(g.id); setSelectedRx(new Set()) }} variant="secondary">تخصيص يدوي</Btn>
                  </div>
                  <div className="flex gap-1.5">
                    <Btn onClick={() => exportGroup(g.id, g.code)} variant="success" disabled={exporting === g.id}>
                      {exporting === g.id ? 'جارٍ...' : 'تصدير فاتورة'}
                    </Btn>
                    <Btn onClick={() => delGroup(g.id)} variant="danger">حذف</Btn>
                  </div>
                </div>
              </div>

              {/* Manual assignment panel */}
              {assignTarget === g.id && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <div className="flex justify-between items-center mb-2">
                    <p className="text-xs font-semibold text-gray-600">اختر الروشتات غير المخصصة لإضافتها لهذه الفئة ({selectedRx.size} محدد)</p>
                    <div className="flex gap-1.5">
                      <Btn onClick={saveAssignment} disabled={selectedRx.size === 0}>إضافة المحدد</Btn>
                      <Btn onClick={() => setAssignTarget(null)} variant="secondary">إغلاق</Btn>
                    </div>
                  </div>
                  <div className="max-h-64 overflow-y-auto border border-gray-100 rounded">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 sticky top-0">
                        <tr className="text-gray-500">
                          <th className="px-2 py-1 w-6"></th>
                          <th className="px-2 py-1 text-right font-semibold">رقم الفاتورة</th>
                          <th className="px-2 py-1 text-right font-semibold">التاريخ</th>
                          <th className="px-2 py-1 text-right font-semibold">اسم المريض</th>
                          <th className="px-2 py-1 text-right font-semibold"></th>
                          <th className="px-2 py-1 text-left font-semibold">الصافى</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          ...unassignedRx.map(rx => ({ key: 'p' + rx.id, doc: rx.softech_docnumber, date: rx.softech_docdate, name: rx.patient_name, extra: rx.relative_degree || '', net: rx.net_after, kind: 'rx' })),
                          ...unassignedManual.map(m => ({ key: 'm' + m.id, doc: m.softech_docnumber, date: m.softech_docdate, name: m.patient_name, net: m.net_after, kind: 'manual' })),
                          ...unassignedSup.map(s => ({ key: 's' + s.id, doc: s.supplement_number || '', date: s.print_date || null, name: s.label, net: s.net_after, kind: 'sup' })),
                        ].map(row => (
                          <tr key={row.key} className="border-b border-gray-50 hover:bg-gray-50">
                            <td className="px-2 py-1">
                              <input type="checkbox" checked={selectedRx.has(row.key)}
                                onChange={e => {
                                  const s = new Set(selectedRx)
                                  e.target.checked ? s.add(row.key) : s.delete(row.key)
                                  setSelectedRx(s)
                                }} />
                            </td>
                            <td className="px-2 py-1 text-gray-400">{row.doc}</td>
                            <td className="px-2 py-1 text-gray-500 whitespace-nowrap">{row.date || '—'}</td>
                            <td className="px-2 py-1">{row.name || '—'}</td>
                            <td className="px-2 py-1">
                              {row.kind === 'manual'
                                ? <span className="text-[10px] bg-blue-100 text-blue-700 rounded px-1 py-0.5">يدوي</span>
                                : row.kind === 'sup'
                                ? <span className="text-[10px] bg-green-100 text-green-700 rounded px-1 py-0.5">ملحق</span>
                                : <span className="text-gray-400">{row.extra}</span>}
                            </td>
                            <td className="px-2 py-1 font-mono">{fmt(row.net)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {unassignedCount === 0 && <p className="text-gray-400 text-center py-4">كل الروشتات مخصصة</p>}
                  </div>
                </div>
              )}
            </div>
          ))}
          <div className="flex justify-end pt-2 text-sm font-semibold text-gray-700">
            إجمالى صافى الفئات: <span className="font-mono mr-2">{fmt(totalNet)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function InsuranceClaimDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const [claim, setClaim]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab]       = useState('prescriptions')
  useHelpTab(tab)
  const [rxFilter, setRxFilter] = useState('')
  const [rxSortKey, setRxSortKey] = useState('sequence')
  const [rxSortDir, setRxSortDir] = useState('asc')
  const [nameFilterMode, setNameFilterMode] = useState('')   // '' | 'complete' | 'spelling'
  const [selRx, setSelRx] = useState(new Set())              // bulk-select prescription ids
  const [bulkBusy, setBulkBusy] = useState(false)
  const [showWizard, setShowWizard] = useState(false)
  const [showResync, setShowResync] = useState(false)
  // Item-name search across prescriptions (backend lookup — lines aren't in the payload)
  const [itemMatchIds, setItemMatchIds]   = useState(null)   // Set of rx ids, or null
  const [itemMatchInfo, setItemMatchInfo] = useState([])
  // Name-completion/spelling suggestions per prescription (for the grid markers)
  const [nameSug, setNameSug] = useState({})   // rx_id → {type, suggestion, ...}

  const loadNameSug = useCallback(() => {
    insuranceApi.nameSuggestions(id)
      .then(r => {
        const m = {}
        for (const row of (r.data.rows || [])) m[row.rx_id] = row
        setNameSug(m)
      })
      .catch(() => setNameSug({}))
  }, [id])

  const load = useCallback(async () => {
    const { data } = await insuranceApi.claimDetail(id)
    setClaim(data)
    setLoading(false)
    loadNameSug()
  }, [id, loadNameSug])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const q = rxFilter.trim()
    if (q.length < 2) { setItemMatchIds(null); setItemMatchInfo([]); return }
    let cancelled = false
    const t = setTimeout(() => {
      insuranceApi.prescriptionsByItem(id, q)
        .then(r => { if (!cancelled) {
          setItemMatchIds(new Set(r.data.prescription_ids || []))
          setItemMatchInfo(r.data.matched_items || [])
        } })
        .catch(() => { if (!cancelled) { setItemMatchIds(null); setItemMatchInfo([]) } })
    }, 300)
    return () => { cancelled = true; clearTimeout(t) }
  }, [rxFilter, id])

  if (loading) return <div className="p-8 text-center text-gray-400">جارٍ التحميل...</div>
  if (!claim)  return <div className="p-8 text-center text-red-500">المطالبة غير موجودة</div>

  const tabs = [
    { id: 'prescriptions', label: `الروشتات (${claim.final_rx_count})` },
    { id: 'items',         label: 'أصناف المطالبة' },
    { id: 'billing',       label: `فئات الفوترة (${claim.billing_groups?.length || 0})` },
    { id: 'supplements',   label: `الملاحق (${claim.supplements?.length || 0})` },
    { id: 'manual',        label: `إضافة يدوية (${(claim.manual_rx?.length || 0) + (claim.prescriptions?.filter(p => p.is_manual).length || 0)})` },
    { id: 'payments',      label: 'التحصيل' },
    { id: 'pivot',         label: 'تحليل البيانات' },
    { id: 'separation',    label: 'فصل الأسماء' },
    { id: 'name_review',   label: 'مراجعة الأسماء' },
    { id: 'discrepancy',   label: 'فحص الفروقات' },
    { id: 'revision',      label: 'مراجعة الفروق' },
    { id: 'softech_reprice', label: 'تعديلات سوفتك' },
    { id: 'readiness',     label: 'الجاهزية للإصدار' },
    { id: 'activity',      label: 'سجل النشاط' },
  ]

  // name-suggestion counts (for the grid banner + optional filter)
  const completeCount = Object.values(nameSug).filter(s => s.type === 'complete').length
  const spellingCount = Object.values(nameSug).filter(s => s.type === 'spelling').length

  const filteredRx = (claim.prescriptions || []).filter(rx =>
    (!rxFilter ||
      wildcardMatch(rx.patient_name, rxFilter) ||
      rx.softech_docnumber?.includes(rxFilter) ||
      (itemMatchIds && itemMatchIds.has(rx.id)))
    && (!nameFilterMode || nameSug[rx.id]?.type === nameFilterMode)
  )
  const filteredManual = (claim.manual_rx || []).filter(m =>
    !nameFilterMode && (
      !rxFilter ||
      wildcardMatch(m.patient_name, rxFilter) ||
      m.softech_docnumber?.includes(rxFilter))
  )

  // ── Sortable الروشتات grid (real + manual share these field names) ──────────
  const RX_TEXT_KEYS = new Set(['softech_docdate', 'softech_docnumber', 'softech_branchcode', 'patient_name'])
  const rxSortVal = (r, key) => {
    if (key === 'net_after') return Number(r.effective_net_after ?? r.net_after) || 0
    if (RX_TEXT_KEYS.has(key)) return (r[key] ?? '').toString()
    return Number(r[key]) || 0
  }
  const rxCmp = (a, b) => {
    const av = rxSortVal(a, rxSortKey), bv = rxSortVal(b, rxSortKey)
    let c
    if (RX_TEXT_KEYS.has(rxSortKey)) c = av.localeCompare(bv, 'ar-EG')
    else c = av - bv
    return rxSortDir === 'asc' ? c : -c
  }
  const sortedRx     = [...filteredRx].sort(rxCmp)
  const sortedManual = [...filteredManual].sort(rxCmp)

  // ── bulk select + exclude (prescriptions only) ──────────────────────────────
  const visibleRxIds = sortedRx.map(r => r.id)
  const allVisibleSelected = visibleRxIds.length > 0 && visibleRxIds.every(i => selRx.has(i))
  const toggleSelRx = (rxId) => setSelRx(s => { const n = new Set(s); n.has(rxId) ? n.delete(rxId) : n.add(rxId); return n })
  const toggleSelectAll = () => setSelRx(s => {
    if (visibleRxIds.every(i => s.has(i))) { const n = new Set(s); visibleRxIds.forEach(i => n.delete(i)); return n }
    return new Set([...s, ...visibleRxIds])
  })
  const bulkExcludeSelected = async () => {
    const ids = [...selRx]
    if (!ids.length) return
    const reason = window.prompt(`سبب استثناء ${ids.length} روشتة (اختيارى):`, '')
    if (reason === null) return
    if (!window.confirm(`استثناء ${ids.length} روشتة من المطالبة؟ (يمكن إعادة إدراجها لاحقاً)`)) return
    setBulkBusy(true)
    try {
      await insuranceApi.bulkExclude(id, ids, reason || 'استبعاد جماعى')
      setSelRx(new Set())
      await load()
    } catch (e) {
      alert(e?.response?.data?.error || 'تعذّر الاستبعاد الجماعى')
    } finally { setBulkBusy(false) }
  }
  const rxSortBy = (key, isText) => {
    if (rxSortKey === key) setRxSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setRxSortKey(key); setRxSortDir(isText ? 'asc' : 'desc') }
  }

  const discPcts = {
    local:    claim.applied_local_disc_pct,
    imported: claim.applied_imported_disc_pct,
    tarsia:   claim.applied_tarsia_disc_pct,
  }

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center gap-3 mb-2">
          <button onClick={() => navigate('/insurance')} className="text-blue-600 text-sm hover:underline">
            ← مطالبات التأمين
          </button>
          <span className="text-gray-300">/</span>
          <span className="font-mono text-sm text-gray-700">{claim.claim_number}</span>
        </div>
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{claim.client_name} — {claim.subclient_name}</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {claim.period_from} إلى {claim.period_to}
            </p>
          </div>
          <div className="flex gap-2 items-center">
            {claim.is_locked && (
              <span className="px-2 py-1 bg-gray-200 text-gray-600 text-xs rounded">🔒 مقفلة</span>
            )}
            {!claim.is_locked && (
              <button
                onClick={() => setShowResync(true)}
                title="جلب تعديلات سوفتك الجديدة (إضافة/حذف/تغيير) دون المساس بالتعديلات المحلية"
                className="px-4 py-2 bg-amber-500 text-white text-sm rounded hover:bg-amber-600">
                🔄 مزامنة سوفتك
              </button>
            )}
            <button data-tour="insurance-claim-issue"
              onClick={() => setShowWizard(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
              إصدار المطالبة
            </button>
            <button data-tour="insurance-claim-print"
              onClick={() => navigate(`/insurance/claims/${id}/print`)}
              className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700">
              طباعة / تصدير
            </button>
          </div>
        </div>

        {/* KPI strip */}
        <div className="flex gap-6 mt-4 pt-4 border-t border-gray-100" data-tour="insurance-claim-kpis">
          {[
            { label: 'عدد الروشتات', value: claim.final_rx_count },
            { label: 'محلى', value: fmt(claim.final_local_before) },
            { label: 'مستورد', value: fmt(claim.final_imported_before) },
            { label: 'الإجمالى', value: fmt(claim.final_gross_before) },
            { label: 'الخصم', value: fmt(claim.final_total_discount), cls: 'text-red-600' },
            { label: 'الصافى', value: fmt(claim.final_net_after), cls: 'text-gray-900 font-bold text-lg' },
          ].map(k => (
            <div key={k.label}>
              <p className="text-xs text-gray-500">{k.label}</p>
              <p className={`font-mono mt-0.5 ${k.cls || 'text-gray-700'}`}>{k.value}</p>
            </div>
          ))}
          <div>
            <p className="text-xs text-gray-500">نسب الخصم</p>
            <p className="text-xs text-gray-600 mt-0.5">
              محلى {claim.applied_local_disc_pct}% | مستورد {claim.applied_imported_disc_pct}% | ترسية {claim.applied_tarsia_disc_pct}%
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white border-b border-gray-200 px-6">
        <div className="flex gap-1" data-tour="insurance-claim-tabs">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {tab === 'prescriptions' && (
        <div className="px-6 py-4">
          <div className="mb-3 flex gap-3 items-center">
            <input data-tour="insurance-claim-rx-search"
              className="border border-gray-300 rounded px-3 py-1.5 text-sm w-72"
              placeholder="بحث باسم المريض أو رقم الفاتورة أو اسم الصنف..."
              value={rxFilter}
              onChange={e => setRxFilter(e.target.value)}
            />
            <span className="text-sm text-gray-500">{filteredRx.length + filteredManual.length} روشتة</span>
            {filteredManual.length > 0 && (
              <span className="text-xs bg-blue-100 text-blue-700 rounded px-2 py-0.5">
                منها {filteredManual.length} يدوية
              </span>
            )}
            {itemMatchIds && itemMatchInfo.length > 0 && (
              <span className="text-xs bg-emerald-100 text-emerald-700 rounded px-2 py-0.5"
                title={itemMatchInfo.map(m => `${m.code} — ${m.name}`).join('\n')}>
                🔎 صنف: {itemMatchIds.size} روشتة تحتوي «{itemMatchInfo[0].name}»
                {itemMatchInfo.length > 1 ? ` +${itemMatchInfo.length - 1}` : ''}
              </span>
            )}
          </div>

          {/* Name-completion hint banner — high-visibility, filterable */}
          {(completeCount > 0 || spellingCount > 0) && (
            <div className="mb-3 flex items-center gap-2 flex-wrap bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
              <span className="text-sm">🟢</span>
              {completeCount > 0 && (
                <button onClick={() => setNameFilterMode(m => m === 'complete' ? '' : 'complete')}
                  className={`text-xs font-semibold rounded px-2.5 py-1 border ${nameFilterMode === 'complete'
                    ? 'bg-emerald-600 text-white border-emerald-600'
                    : 'bg-white text-emerald-700 border-emerald-300 hover:bg-emerald-100'}`}>
                  ⇢ {completeCount} اسم يمكن إكمالها رباعياً {nameFilterMode === 'complete' ? '(عرض الكل)' : '(عرضها فقط)'}
                </button>
              )}
              {spellingCount > 0 && (
                <button onClick={() => setNameFilterMode(m => m === 'spelling' ? '' : 'spelling')}
                  className={`text-xs font-semibold rounded px-2.5 py-1 border ${nameFilterMode === 'spelling'
                    ? 'bg-sky-600 text-white border-sky-600'
                    : 'bg-white text-sky-700 border-sky-300 hover:bg-sky-100'}`}>
                  ✎ {spellingCount} تصحيح إملائى {nameFilterMode === 'spelling' ? '(عرض الكل)' : '(عرضها فقط)'}
                </button>
              )}
              <span className="text-[11px] text-emerald-800">
                اضغط الاقتراح بجوار الاسم لتطبيقه (قابل للتراجع)، أو راجعها دفعة واحدة من
              </span>
              <button onClick={() => setTab('name_review')}
                className="text-[11px] font-semibold text-emerald-700 underline hover:text-emerald-900">
                تبويب «مراجعة الأسماء»
              </button>
            </div>
          )}
          {selRx.size > 0 && (
            <div className="mb-3 flex items-center gap-3 flex-wrap bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
              <span className="text-sm text-blue-800 font-medium">{selRx.size} روشتة محددة</span>
              <button onClick={bulkExcludeSelected} disabled={bulkBusy}
                className="text-xs px-3 py-1 rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">
                {bulkBusy ? '…' : `استثناء المحدد (${selRx.size})`}
              </button>
              <button onClick={() => setSelRx(new Set())} className="text-xs text-gray-500 hover:text-gray-700">إلغاء التحديد</button>
            </div>
          )}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" data-tour="insurance-claim-rx-table">
            <div className="overflow-y-auto overflow-x-auto" style={{ maxHeight: 'calc(100vh - 300px)' }}>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
                  <tr>
                    <th className="px-2 py-2 w-8 text-center">
                      <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAll}
                        title="تحديد كل الروشتات الظاهرة" />
                    </th>
                    {[
                      ['م', 'sequence', false, 'center'],
                      ['التاريخ', 'softech_docdate', true],
                      ['رقم الفاتورة', 'softech_docnumber', true],
                      ['الفرع', 'softech_branchcode', true, 'center'],
                      ['اسم المريض', 'patient_name', true],
                      ['محلى', 'local_before', false, 'left'],
                      ['مستورد', 'imported_before', false, 'left'],
                      ['ترسية', 'tarsia_before', false, 'left'],
                      ['الإجمالى', 'gross_before', false, 'left'],
                      ['الصافى', 'net_after', false, 'left'],
                    ].map(([label, key, isText, align]) => {
                      const active = rxSortKey === key
                      return (
                        <th key={key}
                          onClick={() => rxSortBy(key, isText)}
                          className={`px-3 py-2 text-xs font-semibold whitespace-nowrap cursor-pointer select-none hover:bg-gray-100 ${
                            align === 'left' ? 'text-left' : align === 'center' ? 'text-center' : 'text-right'
                          } ${active ? 'text-blue-700' : 'text-gray-500'}`}>
                          {label}
                          <span className={`ml-0.5 ${active ? 'text-blue-600' : 'text-gray-300'}`}>
                            {active ? (rxSortDir === 'asc' ? '▲' : '▼') : '↕'}
                          </span>
                        </th>
                      )
                    })}
                    <th className="px-3 py-2"></th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRx.map(rx => (
                    <RxRow key={rx.id} rx={rx} claimId={id} discPcts={discPcts} onRefresh={load} sug={nameSug[rx.id]}
                      selected={selRx.has(rx.id)} onToggleSelect={() => toggleSelRx(rx.id)} />
                  ))}
                  {sortedManual.map(m => (
                    <ManualRxRow key={`m${m.id}`} mrx={m} claimId={id} onRefresh={load} onManage={() => setTab('manual')} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === 'items' && (
        <ClaimItemsTab claimId={id} claim={claim} onRefresh={load} />
      )}

      {tab === 'billing' && (
        <BillingGroupsTab claim={claim} claimId={id} onRefresh={load} />
      )}

      {tab === 'supplements' && (
        <SupplementsTab claimId={id} claim={claim} onRefresh={load} />
      )}

      {tab === 'manual' && (
        <ManualRxTab claimId={id} claim={claim} onRefresh={load} />
      )}

      {tab === 'payments' && (
        <PaymentsTab claim={claim} onRefresh={load} />
      )}

      {tab === 'pivot' && (
        <PivotTab claimId={id} />
      )}

      {tab === 'discrepancy' && (
        <DiscrepancyTab claimId={id} onRefresh={load} />
      )}

      {tab === 'revision' && (
        <RevisionTab claimId={id} />
      )}

      {tab === 'separation' && (
        <SeparationTab claimId={id} onRefresh={load} />
      )}

      {tab === 'name_review' && (
        <NameReviewTab claimId={id} onRefresh={load} />
      )}

      {tab === 'softech_reprice' && (
        <SoftechRepriceTab claimId={id} claim={claim} />
      )}

      {tab === 'readiness' && (
        <ReadinessTab claimId={id} />
      )}

      {tab === 'activity' && (
        <ActivityTab claimId={id} />
      )}

      {showWizard && (
        <IssuanceWizard claim={claim} onClose={() => setShowWizard(false)} onRefresh={load} />
      )}
      {showResync && (
        <ResyncModal claimId={id} claim={claim} onClose={() => setShowResync(false)} onRefresh={load} />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// RE-SYNC MODAL — surgical import of SOFTECH delta (new / removed / changed)
// ═══════════════════════════════════════════════════════════════════════════════
function ResyncModal({ claimId, claim, onClose, onRefresh }) {
  const [pv, setPv]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]     = useState(null)
  const [approved, setApproved] = useState(new Set())   // changed rx_ids to re-freeze
  const [busy, setBusy]   = useState(false)
  const [done, setDone]   = useState(null)
  const [runs, setRuns]   = useState([])
  const [motalbaNo, setMotalbaNo] = useState(claim?.softech_motalba_no || '')

  const loadRuns = () => insuranceApi.resyncRuns(claimId).then(r => setRuns(r.data)).catch(() => {})

  const runPreview = (mno) => {
    if (!mno) { setErr('أدخل رقم مطالبة سوفتك لجلب بياناتها.'); return }
    setLoading(true); setErr(null); setPv(null)
    insuranceApi.resyncPreview(claimId, mno)
      .then(r => setPv(r.data))
      .catch(e => setErr(e.response?.data?.error || 'تعذّرت المزامنة'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadRuns()
    if (claim?.softech_motalba_no) runPreview(claim.softech_motalba_no)
  }, [claimId])   // eslint-disable-line

  const revertRun = async (runId) => {
    if (!window.confirm('التراجع عن هذه المزامنة؟ ستُحذف الروشتات المُضافة، ويُلغى استثناء المحذوفة، وتُستعاد الروشتات المُعاد تجميدها.')) return
    setBusy(true); setErr(null)
    try {
      await insuranceApi.resyncRevert(claimId, runId)
      loadRuns(); onRefresh && onRefresh()
    } catch (e) {
      setErr(e.response?.data?.error || 'تعذّر التراجع')
    } finally { setBusy(false) }
  }

  const toggle = (id) => setApproved(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const apply = async () => {
    if (!window.confirm('تطبيق المزامنة؟ ستُضاف الروشتات الجديدة، وتُستثنى المحذوفة، وتُعاد الروشتات المتغيّرة المحددة فقط. التعديلات المحلية الأخرى لن تُمس.')) return
    setBusy(true); setErr(null)
    try {
      const { data } = await insuranceApi.resyncApply(claimId, { confirm: true, approved_change_ids: [...approved], motalba_no: motalbaNo || undefined })
      setDone(data); onRefresh && onRefresh()
    } catch (e) {
      setErr(e.response?.data?.error || 'تعذّر التطبيق')
    } finally { setBusy(false) }
  }

  const c = pv?.counts
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-bold text-gray-800">🔄 مزامنة تعديلات سوفتك {pv?.motalba_no ? `— مطالبة ${pv.motalba_no}` : ''}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        <div className="p-5 overflow-y-auto">
          {/* motalba number — editable when the claim has none stored, or to override */}
          {!done && (
            <div className="flex items-end gap-2 mb-3 flex-wrap">
              <label className="text-xs text-gray-600">رقم مطالبة سوفتك
                <input className="block mt-0.5 border border-gray-300 rounded px-3 py-1.5 text-sm w-36"
                  value={motalbaNo} onChange={e => setMotalbaNo(e.target.value)}
                  placeholder="مثال: 82" onKeyDown={e => e.key === 'Enter' && runPreview(motalbaNo.trim())} />
              </label>
              <button onClick={() => runPreview(motalbaNo.trim())} disabled={loading || !motalbaNo.trim()}
                className="px-3 py-1.5 bg-gray-800 text-white text-sm rounded disabled:opacity-50">جلب ومقارنة</button>
              {!claim?.softech_motalba_no && (
                <span className="text-[11px] text-amber-600">هذه المطالبة ليس لها رقم مطالبة سوفتك محفوظ — أدخله ليُحفظ عند التطبيق.</span>
              )}
            </div>
          )}
          {loading && <div className="text-sm text-gray-400 py-8 text-center">جارٍ مقارنة الحالة الحالية فى سوفتك…</div>}
          {err && <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3 mb-3">{err}</div>}
          {done && (
            <div className="text-sm text-green-700 bg-green-50 border border-green-200 rounded p-3 mb-3">
              ✓ تمت المزامنة: أُضيفت {done.added} · استُثنيت {done.removed} · أُعيد تجميد {done.changed}.
              {done.reprice_flags?.length > 0 && (
                <div className="mt-1 text-amber-700">
                  ⚠️ روشتات محذوفة لها تعديل سعر مُطبَّق — راجع استرجاع السعر من «تعديلات سوفتك»:
                  {done.reprice_flags.map(f => ` #${f.docnumber}`).join('،')}
                </div>
              )}
            </div>
          )}
          {pv && !done && (
            <>
              <div className="flex gap-2 flex-wrap mb-4 text-xs">
                <span className="rounded px-2 py-1 bg-emerald-100 text-emerald-800">جديدة {c.new}</span>
                <span className="rounded px-2 py-1 bg-red-100 text-red-700">محذوفة {c.removed}</span>
                <span className="rounded px-2 py-1 bg-amber-100 text-amber-800">متغيّرة {c.changed}</span>
                <span className="rounded px-2 py-1 bg-gray-100 text-gray-600">بدون تغيير {c.unchanged}</span>
                <span className="rounded px-2 py-1 bg-blue-100 text-blue-700" title="إضافات يدوية من مطالبات أخرى — لن تُمس">محمية (يدوية) {c.protected_manual}</span>
              </div>
              {c.new + c.removed + c.changed === 0 && (
                <div className="text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded p-4 text-center">
                  ✓ لا توجد تعديلات جديدة فى سوفتك — كل شىء متطابق.
                </div>
              )}
              {c.new > 0 && (
                <Section title={`روشتات جديدة (${c.new}) — ستُضاف`}>
                  {pv.new.map(x => (
                    <div key={x.docnumber} className="text-xs flex justify-between border-b border-gray-100 py-1">
                      <span><span className="font-mono">#{x.docnumber}</span> · فرع {x.branch} · {x.date}</span>
                      <span className="font-mono text-gray-600">{fmt(x.net)}</span>
                    </div>
                  ))}
                </Section>
              )}
              {c.removed > 0 && (
                <Section title={`روشتات محذوفة من سوفتك (${c.removed}) — ستُستثنى (قابل للتراجع)`}>
                  {pv.removed.map(x => (
                    <div key={x.docnumber} className="text-xs flex justify-between border-b border-gray-100 py-1">
                      <span><span className="font-mono">#{x.docnumber}</span> · {x.patient}
                        {x.has_reprice && <span className="text-amber-700"> · ⚠️ لها تعديل سعر — راجع الاسترجاع</span>}
                        {x.already_excluded && <span className="text-gray-400"> · مستثناة بالفعل</span>}
                      </span>
                      <span className="font-mono text-gray-600">{fmt(x.net)}</span>
                    </div>
                  ))}
                </Section>
              )}
              {c.changed > 0 && (
                <Section title={`روشتات تغيّرت فى سوفتك (${c.changed}) — حدد ما تريد إعادة تجميده`}>
                  <p className="text-[11px] text-gray-500 mb-1">إعادة التجميد تعتمد بيانات سوفتك الحالية وتلغى التعديلات المحلية على هذه الروشتة فقط.</p>
                  {pv.changed.map(x => (
                    <label key={x.rx_id} className="text-xs flex items-center gap-2 border-b border-gray-100 py-1 cursor-pointer">
                      <input type="checkbox" checked={approved.has(x.rx_id)} onChange={() => toggle(x.rx_id)} />
                      <span className="flex-1"><span className="font-mono">#{x.docnumber}</span> · {x.patient}</span>
                      <span className="font-mono text-gray-500">صافينا {fmt(x.our_net)} → سوفتك {fmt(x.softech_net)}
                        <span className={x.diff >= 0 ? 'text-emerald-600' : 'text-red-600'}> ({x.diff >= 0 ? '+' : ''}{fmt(x.diff)})</span>
                      </span>
                    </label>
                  ))}
                </Section>
              )}
            </>
          )}

          {/* Previous re-sync runs — revert */}
          {runs.length > 0 && (
            <div className="mt-4 border-t border-gray-200 pt-3">
              <div className="text-xs font-semibold text-gray-700 mb-1">سجل عمليات المزامنة</div>
              {runs.map(r => (
                <div key={r.id} className="text-xs flex items-center justify-between border-b border-gray-100 py-1.5">
                  <span>
                    #{r.id} · {toLatinDigits(new Date(r.applied_at).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' }))}
                    {' · '}<span className="text-emerald-700">+{r.added}</span>
                    {' / '}<span className="text-red-600">{r.removed}</span>
                    {' / '}<span className="text-amber-700">~{r.changed}</span>
                    {r.status === 'reverted' && <span className="text-gray-400"> · مُتراجَع</span>}
                  </span>
                  {r.status === 'applied' && (
                    <button onClick={() => revertRun(r.id)} disabled={busy}
                      className="text-[11px] text-red-500 hover:text-red-700 disabled:opacity-50">↩ تراجع</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        {pv && !done && (c.new + c.removed + c.changed > 0) && (
          <div className="px-5 py-3 border-t border-gray-200 flex justify-end gap-2">
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 rounded border border-gray-300">إلغاء</button>
            <button onClick={apply} disabled={busy}
              className="px-4 py-2 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50">
              {busy ? 'جارٍ التطبيق…' : `تطبيق المزامنة (${c.new} إضافة · ${c.removed} استثناء · ${approved.size} إعادة تجميد)`}
            </button>
          </div>
        )}
        {done && (
          <div className="px-5 py-3 border-t border-gray-200 flex justify-end">
            <button onClick={onClose} className="px-4 py-2 text-sm bg-gray-800 text-white rounded">إغلاق</button>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="mb-4">
      <div className="text-xs font-semibold text-gray-700 mb-1">{title}</div>
      <div className="border border-gray-200 rounded p-2 max-h-52 overflow-y-auto">{children}</div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════════
// ISSUANCE WIZARD — guided اصدار مطالبة: readiness → review → generate → submit
// Orchestrates existing endpoints (readiness, omissions, discrepancy/apply,
// submission package, cover letter, change-status). No duplicated logic.
// ═══════════════════════════════════════════════════════════════════════════════

function IssuanceWizard({ claim, onClose, onRefresh }) {
  const claimId = claim.id
  const [step, setStep] = useState(1)
  const [readiness, setReadiness] = useState(null)
  const [omissions, setOmissions] = useState(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  // Step 1: load readiness + omissions
  useEffect(() => {
    if (step === 1) {
      setLoading(true)
      Promise.all([
        insuranceApi.readiness(claimId).then(r => r.data).catch(() => null),
        insuranceApi.omissions(claimId).then(r => r.data).catch(() => null),
      ]).then(([rd, om]) => { setReadiness(rd); setOmissions(om) })
        .finally(() => setLoading(false))
    }
  }, [step, claimId])

  const dl = async (apiCall, fname) => {
    setBusy(true)
    try {
      const { data } = await apiCall()
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a'); a.href = url; a.download = fname
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } finally { setBusy(false) }
  }

  const submitClaim = async () => {
    setBusy(true)
    try {
      await insuranceApi.changeStatus(claimId, { status: 'submitted' })
      setDone(true)
      onRefresh && onRefresh()
    } catch (e) {
      alert(e.response?.data?.error || 'تعذّر تقديم المطالبة')
    } finally { setBusy(false) }
  }

  const steps = ['الجاهزية', 'المراجعة', 'التوليد', 'الإصدار']
  const canProceedFrom1 = readiness?.can_issue

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header + stepper */}
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-bold text-gray-800">إصدار المطالبة — {claim.claim_number}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        <div className="px-5 py-3 flex gap-2 border-b border-gray-100">
          {steps.map((s, i) => (
            <div key={s} className={`flex items-center gap-1.5 text-xs ${
              step === i + 1 ? 'text-blue-700 font-bold' : step > i + 1 ? 'text-green-600' : 'text-gray-400'}`}>
              <span className={`w-5 h-5 rounded-full grid place-items-center text-[10px] ${
                step === i + 1 ? 'bg-blue-100' : step > i + 1 ? 'bg-green-100' : 'bg-gray-100'}`}>
                {step > i + 1 ? '✓' : i + 1}
              </span>
              {s}
            </div>
          ))}
        </div>

        <div className="p-5 overflow-y-auto flex-1">
          {loading && <div className="text-sm text-gray-400">جارٍ التحميل…</div>}

          {/* STEP 1 — Readiness */}
          {step === 1 && !loading && readiness && (
            <div>
              <div className={`rounded-xl border p-3 mb-3 ${readiness.can_issue ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
                <p className={`font-bold ${readiness.can_issue ? 'text-green-700' : 'text-red-700'}`}>
                  {readiness.can_issue ? '✓ جاهزة للإصدار' : '✕ يوجد أخطاء تمنع الإصدار'}
                  <span className="text-sm font-normal text-gray-500"> · درجة {readiness.health_score}</span>
                </p>
              </div>
              <div className="space-y-1.5">
                {readiness.checks.filter(c => c.severity !== 'ok').map(c => {
                  const cfg = SEV_CFG[c.severity] || SEV_CFG.info
                  return (
                    <div key={c.key} className={`rounded-lg border p-2 text-sm ${cfg.cls}`}>
                      <span className="font-medium">{cfg.icon} {c.label}</span>
                      {c.count > 0 && <span className="text-xs"> ({c.count})</span>}
                      {c.detail && <p className="text-xs text-gray-600 mt-0.5">{c.detail}</p>}
                    </div>
                  )
                })}
                {readiness.checks.every(c => c.severity === 'ok') && (
                  <p className="text-sm text-green-600">كل الفحوصات سليمة ✓</p>
                )}
              </div>
            </div>
          )}

          {/* STEP 2 — Review (omissions) */}
          {step === 2 && (
            <div>
              <p className="font-semibold text-gray-700 mb-2">النواقص (فواتير لم تُدرج)</p>
              {!omissions?.can_check ? (
                <p className="text-sm text-gray-500">{omissions?.reason || 'تعذّر الفحص'}</p>
              ) : omissions.missing_count === 0 ? (
                <p className="text-sm text-green-600">✓ كل فواتير المطالبة في سوفتك مُدرجة ({omissions.imported}/{omissions.motalba_docs}).</p>
              ) : (
                <div>
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-2 text-sm text-amber-700">
                    ⚠️ {omissions.missing_count} فاتورة غير مُدرجة بقيمة {fmt(omissions.value_missing)} ج.م —
                    راجعها قبل الإصدار حتى لا تفقد إيراداً.
                  </div>
                  <div className="flex flex-wrap gap-1 max-h-40 overflow-y-auto">
                    {omissions.missing.slice(0, 60).map((m, i) => (
                      <span key={i} className="text-[11px] font-mono bg-gray-50 border border-gray-200 rounded px-1.5 py-0.5">
                        #{m.docnumber} · {fmt(m.value)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* STEP 3 — Generate */}
          {step === 3 && (
            <div className="space-y-3">
              <p className="font-semibold text-gray-700">توليد مستندات المطالبة</p>
              <button disabled={busy}
                onClick={() => dl(() => insuranceApi.submissionPackage(claimId), `مطالبة_${claim.claim_number}.zip`)}
                className="w-full px-4 py-3 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
                📦 تنزيل حزمة التقديم كاملة (Excel + خطاب التقديم)
              </button>
              <div className="flex gap-2">
                <button disabled={busy}
                  onClick={() => dl(() => insuranceApi.coverLetter(claimId), `خطاب_${claim.claim_number}.docx`)}
                  className="flex-1 px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200 disabled:opacity-50">
                  📄 خطاب التقديم (Word)
                </button>
                <button disabled={busy}
                  onClick={() => dl(() => insuranceApi.exportExcel(claimId, 'all'), `جداول_${claim.claim_number}.xlsx`)}
                  className="flex-1 px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200 disabled:opacity-50">
                  📊 الجداول (Excel)
                </button>
              </div>
            </div>
          )}

          {/* STEP 4 — Submit */}
          {step === 4 && (
            <div className="text-center py-4">
              {done ? (
                <div>
                  <p className="text-4xl mb-2">✅</p>
                  <p className="font-bold text-green-700">تم تقديم المطالبة وقفلها</p>
                  <p className="text-sm text-gray-500 mt-1">أي تعديل لاحق يتم عبر ملحق.</p>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-gray-600 mb-3">
                    سيتم تغيير حالة المطالبة إلى «مُقدَّمة» وقفلها لمنع التعديل العرضي.
                    التعديلات اللاحقة تتم عبر ملحق.
                  </p>
                  <button disabled={busy} onClick={submitClaim}
                    className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
                    {busy ? 'جارٍ التقديم…' : 'تأكيد التقديم والقفل'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer nav */}
        <div className="px-5 py-3 border-t border-gray-200 flex justify-between">
          <button onClick={() => setStep(s => Math.max(1, s - 1))} disabled={step === 1 || done}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 disabled:opacity-30">السابق</button>
          {done ? (
            <button onClick={onClose} className="px-4 py-2 bg-green-600 text-white text-sm rounded">إغلاق</button>
          ) : step < 4 ? (
            <button
              onClick={() => setStep(s => s + 1)}
              disabled={step === 1 && !canProceedFrom1}
              title={step === 1 && !canProceedFrom1 ? 'أصلح الأخطاء أولاً' : ''}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-40">
              التالي
            </button>
          ) : <span />}
        </div>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════════
// READINESS TAB — pre-flight validation before issuing (اصدار مطالبة)
// ═══════════════════════════════════════════════════════════════════════════════

const SEV_CFG = {
  error:   { cls: 'bg-red-50 border-red-200 text-red-700',       icon: '✕', badge: 'bg-red-100 text-red-700' },
  warning: { cls: 'bg-amber-50 border-amber-200 text-amber-700', icon: '!', badge: 'bg-amber-100 text-amber-700' },
  info:    { cls: 'bg-blue-50 border-blue-200 text-blue-700',    icon: 'i', badge: 'bg-blue-100 text-blue-700' },
  ok:      { cls: 'bg-green-50 border-green-200 text-green-700', icon: '✓', badge: 'bg-green-100 text-green-700' },
}

// ── Name separation tab — flag prescriptions matching a separation list ────────
function SeparationTab({ claimId, onRefresh }) {
  const [data, setData]   = useState(null)
  const [listId, setListId] = useState('')
  const [loading, setLoad]  = useState(true)
  const [sel, setSel]       = useState(new Set())
  const [busy, setBusy]     = useState(false)
  const [msg, setMsg]       = useState(null)
  const [sortKey, setSortKey] = useState('match_type')
  const [sortDir, setSortDir] = useState('asc')
  const navigate = useNavigate()

  const sortBy = (k) => {
    if (sortKey === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('asc') }
  }

  const load = (lid) => {
    setLoad(true)
    insuranceApi.separationMatches(claimId, lid || '')
      .then(r => {
        setData(r.data)
        // pre-select the confident (full) non-excluded matches
        setSel(new Set(r.data.matches.filter(m => m.match_type === 'full' && !m.is_excluded).map(m => m.prescription_id)))
      })
      .finally(() => setLoad(false))
  }
  useEffect(() => { load(listId) }, [claimId, listId])   // eslint-disable-line

  const toggle = (id) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const errText = (e, fallback) => {
    if (!e.response) return 'تعذّر الاتصال بالسيرفر — تأكد أن السيرفر يعمل ثم أعد المحاولة'
    return e.response.data?.error || e.response.data?.detail || `${fallback} (خطأ ${e.response.status})`
  }

  const setReviewed = async (ids, reviewed) => {
    if (!ids.length) return
    setMsg(null)
    try {
      await insuranceApi.markReviewed(claimId, ids, reviewed)
      setData(d => ({
        ...d,
        matches: d.matches.map(m => ids.includes(m.prescription_id) ? { ...m, reviewed } : m),
        reviewed_count: d.matches.filter(m => ids.includes(m.prescription_id) ? reviewed : m.reviewed).length,
      }))
      setMsg(`تم تعليم ${ids.length} روشتة كمُراجَعة`)
    } catch (e) { setMsg(errText(e, 'تعذّر تعليم المراجعة')) }
  }

  const doExclude = async () => {
    const ids = [...sel]
    if (!ids.length) return
    if (!window.confirm(`استبعاد ${ids.length} روشتة من هذه المطالبة (لفصلها إلى مطالبة أخرى)؟ يمكن التراجع بإعادة إدراجها.`)) return
    setBusy(true); setMsg(null)
    try {
      const { data: res } = await insuranceApi.bulkExclude(claimId, ids, 'فصل — قائمة الأسماء')
      setMsg(`تم استبعاد ${res.excluded} روشتة · الصافى الآن ${fmt(res.claim_net_after)}`)
      setSel(new Set()); load(listId); onRefresh && onRefresh()
    } catch (e) { setMsg(errText(e, 'تعذّر الاستبعاد')) } finally { setBusy(false) }
  }

  if (loading) return <div className="px-6 py-6 text-sm text-gray-400">جارٍ فحص الأسماء…</div>
  if (!data)   return null

  const NUMERIC = new Set(['gross_before', 'net_after', 'score'])
  const sortVal = (m) => {
    if (sortKey === 'match_type') return m.match_type === 'full' ? 0 : 1   // full first
    if (sortKey === 'reviewed')   return m.reviewed ? 1 : 0
    const v = m[sortKey]
    return NUMERIC.has(sortKey) ? Number(v || 0) : (v || '').toString()
  }
  const sortedMatches = [...data.matches].sort((a, b) => {
    const va = sortVal(a), vb = sortVal(b)
    let c = typeof va === 'number' ? va - vb : va.localeCompare(vb, 'ar')
    return sortDir === 'asc' ? c : -c
  })

  const SortTh = ({ k, children, align = 'right' }) => (
    <th onClick={() => sortBy(k)}
      className={`text-${align} px-2 py-2 font-semibold cursor-pointer select-none whitespace-nowrap ${sortKey === k ? 'text-blue-600' : ''}`}>
      {children}{sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  )

  return (
    <div className="px-6 py-4">
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <span className="text-sm font-semibold text-gray-700">فصل الأسماء</span>
        <select value={listId} onChange={e => setListId(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm">
          <option value="">كل القوائم المُفعَّلة</option>
          {data.lists.map(l => <option key={l.id} value={l.id}>{l.label} ({l.name_count})</option>)}
        </select>
        <span className="text-sm text-gray-500">{data.match_count} مطابقة من {data.checked_names} اسم</span>
        <span className={`text-xs rounded px-2 py-0.5 ${data.reviewed_count >= data.match_count && data.match_count > 0
          ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
          روجِع {data.reviewed_count} / {data.match_count}
        </span>
        <button onClick={() => navigate('/insurance/separation-lists')}
          className="text-xs text-blue-600 hover:underline mr-auto">⚙ إدارة قوائم الأسماء</button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        الروشتات التي يطابق اسم مريضها اسماً في قائمة الفصل. راجع واختر ثم استبعدها من هذه المطالبة لإضافتها لاحقاً إلى مطالبتها الصحيحة.
        <span className="text-green-700"> المطابقة الكاملة مُحدَّدة تلقائياً</span>، والجزئية تحتاج مراجعتك.
      </p>
      {msg && <div className="mb-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">{msg}</div>}

      <div className="mb-3 flex gap-2">
        <button onClick={doExclude} disabled={busy || sel.size === 0}
          className="px-3 py-2 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50">
          {busy ? 'جارٍ…' : `استبعاد المحدد (${sel.size})`}
        </button>
        <button onClick={() => setReviewed([...sel], true)} disabled={sel.size === 0}
          className="px-3 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50">
          تعليم المحدد كمُراجَع ({sel.size})
        </button>
        <button onClick={() => setReviewed(data.matches.map(m => m.prescription_id), true)}
          className="px-3 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-50">
          تعليم الكل كمُراجَع
        </button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200 text-gray-500">
            <tr>
              <th className="px-2 py-2 w-8"></th>
              <SortTh k="patient_name">اسم المريض (بالروشتة)</SortTh>
              <SortTh k="matched_name">الاسم في القائمة</SortTh>
              <SortTh k="match_type" align="center">المطابقة</SortTh>
              <SortTh k="reviewed" align="center">روجعت</SortTh>
              <SortTh k="docnumber">رقم الفاتورة</SortTh>
              <SortTh k="docdate">التاريخ</SortTh>
              <SortTh k="branch" align="center">الفرع</SortTh>
              <SortTh k="national_id">الرقم القومي/المالي</SortTh>
              <SortTh k="list_label">القائمة</SortTh>
              <SortTh k="gross_before" align="left">الإجمالى</SortTh>
              <SortTh k="net_after" align="left">الصافى</SortTh>
              <th className="text-center px-2 py-2 font-semibold">الحالة</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sortedMatches.map(m => (
              <tr key={m.prescription_id} className={`hover:bg-gray-50 ${m.is_excluded ? 'opacity-50' : ''}`}>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={sel.has(m.prescription_id)}
                    disabled={m.is_excluded}
                    onChange={() => toggle(m.prescription_id)} />
                </td>
                <td className="px-2 py-1.5 font-medium text-gray-800">
                  {m.patient_name}
                  {m.dept_name && <span className="block text-[10px] text-gray-400">{m.dept_name}</span>}
                </td>
                <td className="px-2 py-1.5 text-gray-600">{m.matched_name}</td>
                <td className="px-2 py-1.5 text-center">
                  <span className={`text-[10px] rounded px-1.5 py-0.5 ${m.match_type === 'full'
                    ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                    {m.match_type === 'full' ? 'كاملة' : 'جزئية'}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={!!m.reviewed}
                    onChange={e => setReviewed([m.prescription_id], e.target.checked)}
                    className="accent-green-600" title="تم مراجعة هذه الروشتة" />
                </td>
                <td className="px-2 py-1.5 font-mono text-xs">{m.docnumber || '—'}</td>
                <td className="px-2 py-1.5 text-xs text-gray-600">{m.docdate || '—'}</td>
                <td className="px-2 py-1.5 text-center text-xs">{m.branch || '—'}</td>
                <td className="px-2 py-1.5 font-mono text-xs">{m.national_id || <span className="text-gray-300">—</span>}</td>
                <td className="px-2 py-1.5 text-xs text-gray-500">{m.list_label}</td>
                <td className="px-2 py-1.5 text-left font-mono text-gray-600">{fmt(m.gross_before)}</td>
                <td className="px-2 py-1.5 text-left font-mono">{fmt(m.net_after)}</td>
                <td className="px-2 py-1.5 text-center text-xs">
                  {m.is_excluded ? <span className="text-red-600">مُستبعدة</span> : <span className="text-gray-400">—</span>}
                </td>
              </tr>
            ))}
            {data.matches.length === 0 && (
              <tr><td colSpan={13} className="px-3 py-8 text-center text-gray-400">لا مطابقات في هذه المطالبة.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Activity / audit-log tab ───────────────────────────────────────────────
const _AUDIT_TONE = {
  status_change: 'bg-blue-50 text-blue-700',   apply_master: 'bg-indigo-50 text-indigo-700',
  apply_overrides: 'bg-indigo-50 text-indigo-700', apply_review: 'bg-purple-50 text-purple-700',
  revert_apply: 'bg-gray-100 text-gray-600',   line_edit: 'bg-amber-50 text-amber-700',
  line_reset: 'bg-gray-100 text-gray-600',     patient_edit: 'bg-amber-50 text-amber-700',
  rx_adjust: 'bg-amber-50 text-amber-700',     rx_exclude: 'bg-red-50 text-red-700',
  manual_add: 'bg-emerald-50 text-emerald-700', manual_delete: 'bg-red-50 text-red-700',
  supplement: 'bg-teal-50 text-teal-700',      payment: 'bg-green-50 text-green-700',
  deduction: 'bg-orange-50 text-orange-700',   billing_group: 'bg-sky-50 text-sky-700',
  bulk_exclude: 'bg-red-50 text-red-700',      other: 'bg-gray-100 text-gray-600',
}

// ── Name review: bulk-fix incomplete / misspelled patient names ────────────────
function NameReviewTab({ claimId, onRefresh }) {
  const [rows, setRows]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [sel, setSel]       = useState({})     // rx_id → chosen name
  const [busy, setBusy]     = useState(false)
  const [msg, setMsg]       = useState(null)

  const load = () => {
    setLoading(true)
    insuranceApi.nameSuggestions(claimId)
      .then(r => {
        setRows(r.data.rows || [])
        // preselect confident (non-ambiguous) suggestions
        const pre = {}
        for (const row of (r.data.rows || [])) {
          if (row.suggestion && row.type !== 'ambiguous') pre[row.rx_id] = row.suggestion
        }
        setSel(pre)
      })
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [claimId])   // eslint-disable-line

  const toggle = (row) => setSel(s => {
    const n = { ...s }
    if (n[row.rx_id] != null) delete n[row.rx_id]
    else n[row.rx_id] = row.suggestion || (row.options && row.options[0]) || ''
    return n
  })
  const setChoice = (rxId, name) => setSel(s => ({ ...s, [rxId]: name }))

  const applySel = async () => {
    const choices = {}
    for (const [k, v] of Object.entries(sel)) if (v && v.trim()) choices[k] = v.trim()
    if (!Object.keys(choices).length) return
    if (!window.confirm(`تطبيق ${Object.keys(choices).length} اسم؟ (الاسم حقل طباعة فقط — لا يؤثر على الإجماليات، وقابل للتراجع لكل روشتة).`)) return
    setBusy(true); setMsg(null)
    try {
      const { data } = await insuranceApi.applyNameSuggestions(claimId, choices)
      setMsg(`تم تطبيق ${data.applied} اسم.`)
      load(); onRefresh && onRefresh()
    } catch (e) {
      setMsg(e.response?.data?.error || 'تعذّر التطبيق')
    } finally { setBusy(false) }
  }

  const revertOne = async (rxId) => {
    setBusy(true)
    try { await insuranceApi.revertPatientName(claimId, rxId); load(); onRefresh && onRefresh() }
    finally { setBusy(false) }
  }

  const typeBadge = (t) => t === 'complete'
    ? <span className="text-[10px] bg-emerald-100 text-emerald-700 rounded px-1.5 py-0.5">إكمال</span>
    : t === 'spelling'
    ? <span className="text-[10px] bg-sky-100 text-sky-700 rounded px-1.5 py-0.5">تصحيح إملائي</span>
    : <span className="text-[10px] bg-amber-100 text-amber-700 rounded px-1.5 py-0.5">متعدد — اختر يدوياً</span>

  if (loading) return <div className="px-6 py-6 text-sm text-gray-400">جارٍ فحص الأسماء…</div>

  const selCount = Object.values(sel).filter(v => v && v.trim()).length

  return (
    <div className="px-6 py-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="font-semibold text-gray-800">مراجعة أسماء المرضى</h3>
          <p className="text-xs text-gray-500">
            اقتراحات آمنة من سجل نفس الجهة: إكمال الاسم رباعياً أو تصحيح الإملاء. الاسم حقل طباعة فقط
            (لا يؤثر على الإجماليات) وقابل للتراجع. الأسماء متعددة الاحتمالات تُترك للاختيار اليدوى تفادياً لأى خطأ.
          </p>
        </div>
        <button onClick={applySel} disabled={busy || selCount === 0}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded disabled:opacity-40">
          تطبيق المحدد ({selCount})
        </button>
      </div>
      {msg && <div className="mb-2 text-sm text-blue-700">{msg}</div>}
      {rows.length === 0 ? (
        <div className="text-sm text-green-600 bg-green-50 border border-green-200 rounded-lg p-4">
          ✓ لا توجد أسماء تحتاج إلى تصحيح أو إكمال حسب السجل التاريخى.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-gray-500 text-xs border-b border-gray-200">
            <tr>
              <th className="py-2 w-8"></th>
              <th className="text-right">التاريخ</th>
              <th className="text-right">الإيصال</th>
              <th className="text-right">الاسم الحالى</th>
              <th className="text-right">الاقتراح</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => {
              const chosen = sel[row.rx_id]
              const checked = chosen != null
              return (
                <tr key={row.rx_id} className="border-b border-gray-100">
                  <td className="py-2 text-center">
                    <input type="checkbox" checked={checked} onChange={() => toggle(row)} />
                  </td>
                  <td className="text-xs text-gray-500 whitespace-nowrap">{row.date}</td>
                  <td className="text-xs font-mono text-gray-500">#{row.docnumber}</td>
                  <td className="text-gray-800">{row.current_name}</td>
                  <td>
                    <div className="flex items-center gap-2 flex-wrap">
                      {typeBadge(row.type)}
                      {row.type === 'ambiguous' ? (
                        <select value={chosen ?? ''} onChange={e => setChoice(row.rx_id, e.target.value)}
                          className="border border-gray-300 rounded px-2 py-1 text-xs">
                          <option value="">— اختر —</option>
                          {(row.options || []).map(o => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : (
                        <span className="font-medium text-gray-900">{row.suggestion}</span>
                      )}
                      {row.count ? <span className="text-[10px] text-gray-400" dir="ltr">{row.count}×</span> : null}
                    </div>
                  </td>
                  <td className="text-left">
                    {row.softech_name && row.current_name !== row.softech_name && (
                      <button onClick={() => revertOne(row.rx_id)} disabled={busy}
                        title={`استرجاع اسم سوفتك: ${row.softech_name}`}
                        className="text-[11px] bg-amber-50 border border-amber-200 text-amber-700 rounded px-1.5 py-0.5">
                        ↩ سوفتك
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ActivityTab({ claimId }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter]   = useState('')

  const load = () => {
    setLoading(true)
    insuranceApi.auditLog(claimId, filter ? { action: filter } : {})
      .then(r => setData(r.data)).catch(() => setData({ events: [], count: 0 }))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [claimId, filter])

  const events = data?.events || []
  // distinct actions present (for the filter chips)
  const [allActions, setAllActions] = useState([])
  useEffect(() => {
    if (!filter && data?.events) {
      const seen = {}
      data.events.forEach(e => { seen[e.action] = e.action_label })
      setAllActions(Object.entries(seen))
    }
  }, [data, filter])

  const fmtDelta = (b, a) => {
    if (b?.net != null && a?.net != null) {
      const d = Number(a.net) - Number(b.net)
      return <span className={d > 0.005 ? 'text-green-600' : d < -0.005 ? 'text-red-600' : 'text-gray-400'}>
        {' '}({fmt(b.net)} → {fmt(a.net)}{Math.abs(d) > 0.005 ? `, ${d > 0 ? '+' : ''}${fmt(d)}` : ''})
      </span>
    }
    return null
  }

  return (
    <div className="px-6 py-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-700">
          سجل النشاط {data ? <span className="text-gray-400 font-normal">({data.count} حدث)</span> : ''}
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => setFilter('')}
            className={`text-xs px-2 py-1 rounded border ${filter === '' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300'}`}>الكل</button>
          {allActions.map(([a, label]) => (
            <button key={a} onClick={() => setFilter(a)}
              className={`text-xs px-2 py-1 rounded border ${filter === a ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}>{label}</button>
          ))}
          <button onClick={load} className="text-xs px-2 py-1 rounded border bg-white text-gray-500 border-gray-300 hover:bg-gray-50">↻ تحديث</button>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm text-center py-10">جارٍ التحميل…</p>
      ) : events.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-10">لا يوجد نشاط مُسجَّل بعد.</p>
      ) : (
        <ol className="relative border-r-2 border-gray-100 pr-4 space-y-0">
          {events.map(e => (
            <li key={e.id} className="relative pb-4">
              <span className="absolute -right-[9px] top-1.5 w-3 h-3 rounded-full bg-white border-2 border-gray-300" />
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[11px] rounded px-1.5 py-0.5 ${_AUDIT_TONE[e.action] || _AUDIT_TONE.other}`}>{e.action_label}</span>
                <span className="text-xs text-gray-400 font-mono">
                  {toLatinDigits(new Date(e.at).toLocaleString('ar-EG'))}
                </span>
                {e.actor && <span className="text-xs text-gray-500">— {e.actor}</span>}
              </div>
              <div className="text-sm text-gray-800 mt-0.5">
                {e.summary}{fmtDelta(e.before, e.after)}
              </div>
              {e.reason && <div className="text-xs text-gray-500 mt-0.5">السبب: {e.reason}</div>}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

// ── Revision tab: sortable/filterable flagged lines + manual sign-off ─────────
const _FLAG_META = {
  value:         { icon: '💰', label: 'فرق قيمة', cls: 'bg-rose-50 text-rose-700',
                   tip: 'الإجمالى محسوب من كمية مُقرَّبة (٣ خانات) وقد يخالف قيمة سوفتك الحقيقية' },
  discount:      { icon: '💸', label: 'خصم سوفتك', cls: 'bg-rose-100 text-rose-800',
                   tip: 'خصم سوفتك لهذا الصنف يخالف نسبة الفئة — هذا البند سبب اختلاف صافى الروشتة عن سوفتك' },
  drift:         { icon: '⚠️', label: 'فرق كتالوج', cls: 'bg-amber-50 text-amber-700',
                   tip: 'التصنيف/السعر الحالى فى الكتالوج يختلف عن اللقطة المجمَّدة' },
  softech_class: { icon: '⚑', label: 'تصنيف سوفتك', cls: 'bg-orange-50 text-orange-700',
                   tip: 'تصنيفنا للصنف يخالف تصنيف سوفتك الخام' },
}

function RevisionTab({ claimId }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(null)
  const [flagFilter, setFlagFilter] = useState('')     // '', 'value', 'drift', 'softech_class'
  const [statusFilter, setStatusFilter] = useState('') // '', 'pending', 'approved'
  const [q, setQ]             = useState('')
  const [sort, setSort]       = useState({ key: 'net_amount', dir: 'desc' })
  const [noteDraft, setNoteDraft] = useState({})

  const load = () => {
    setLoading(true)
    insuranceApi.flaggedLines(claimId)
      .then(r => setData(r.data)).catch(() => setData({ lines: [], count: 0 }))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [claimId])

  const review = async (row, approved) => {
    setSaving(row.line_id)
    try {
      await insuranceApi.reviewLine(claimId, row.prescription_id, row.line_id,
        { approved, note: noteDraft[row.line_id] ?? row.review_note ?? '' })
      await load()
    } finally { setSaving(null) }
  }

  const rows = (data?.lines || [])
    .filter(r => !flagFilter || r.flags.includes(flagFilter))
    .filter(r => !statusFilter
      || (statusFilter === 'pending' && !r.review_approved)
      || (statusFilter === 'approved' && r.review_approved))
    .filter(r => !q || wildcardMatch(r.item_name, q) || (r.itemcode || '').includes(q)
      || wildcardMatch(r.patient_name, q) || String(r.docnumber || '').includes(q))
  const sorted = [...rows].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key]
    const cmp = (typeof av === 'number' && typeof bv === 'number')
      ? av - bv : String(av ?? '').localeCompare(String(bv ?? ''), 'ar')
    return sort.dir === 'asc' ? cmp : -cmp
  })
  // keyboard flow (shared review-grid keys): Enter approves the line and moves on, Space
  // toggles approve / un-approve
  const kb = useGridKeyboard({
    rows: sorted, getKey: r => r.line_id, advanceOnConfirm: true,
    onConfirm: r => { if (!r.review_approved && saving == null) review(r, true) },
    onToggle: r => { if (saving == null) review(r, !r.review_approved) },
  })
  const th = (key, label, extra = '') => (
    <th onClick={() => setSort(s => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}
      className={`pb-1 cursor-pointer select-none hover:text-gray-700 ${extra}`}>
      {label}{sort.key === key ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
    </th>
  )

  if (loading && !data) return <div className="px-6 py-6 text-sm text-gray-400">جارٍ تحميل البنود المُعلَّمة…</div>

  const chip = (val, cur, set, label) => (
    <button onClick={() => set(cur === val ? '' : val)}
      className={`text-xs px-2 py-1 rounded border ${cur === val
        ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}>{label}</button>
  )

  return (
    <div className="px-6 py-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <h3 className="text-sm font-semibold text-gray-700">
          مراجعة الفروق {data ? <span className="text-gray-400 font-normal">
            ({data.count} بند مُعلَّم · {data.pending_count} بانتظار الاعتماد · 💰 {data.value_count} فرق قيمة)</span> : ''}
        </h3>
        <button onClick={load} className="text-xs px-2 py-1 rounded border bg-white text-gray-500 border-gray-300 hover:bg-gray-50">↻ تحديث</button>
      </div>
      <p className="text-[11px] text-gray-400 mb-3 leading-relaxed">
        كل بند به علامة فرق (💰 قيمة قد تخالف سوفتك · ⚠️ فرق عن الكتالوج · ⚑ تصنيف يخالف سوفتك). المراجعة والاعتماد
        تسجيليان فقط ولا يغيّران القيم المجمَّدة أو المستندات المصدَّرة — الهدف توثيق أنك راجعت الفرق ووافقت عليه قبل التسليم.
      </p>

      <div className="flex items-center gap-2 flex-wrap mb-3">
        <span className="text-xs text-gray-400">النوع:</span>
        {chip('value', flagFilter, setFlagFilter, '💰 قيمة')}
        {chip('drift', flagFilter, setFlagFilter, '⚠️ كتالوج')}
        {chip('softech_class', flagFilter, setFlagFilter, '⚑ تصنيف')}
        <span className="text-xs text-gray-400 mr-2">الحالة:</span>
        {chip('pending', statusFilter, setStatusFilter, 'بانتظار الاعتماد')}
        {chip('approved', statusFilter, setStatusFilter, 'معتمَد')}
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالصنف/الكود/المريض/الروشتة…"
          className="border border-gray-300 rounded px-2 py-1 text-xs w-56 mr-2" />
        <span className="text-[11px] text-gray-400 mr-auto">⌨ ↑↓ تنقل · Enter اعتماد والتالي · مسافة اعتماد/إلغاء</span>
      </div>

      {sorted.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-10">
          {data?.count ? 'لا توجد بنود مطابقة للتصفية.' : 'لا توجد بنود بها فروق تحتاج مراجعة. 🎉'}
        </p>
      ) : (
        <div {...kb.containerProps} className={`overflow-x-auto border border-gray-200 rounded-lg ${kb.containerProps.className}`}>
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500 border-b">
              <tr>
                <th className="text-right pb-1 pt-2 px-2">العلامات</th>
                {th('itemcode', 'الكود', 'text-right px-2')}
                {th('item_name', 'الصنف', 'text-right px-2')}
                {th('patient_name', 'المريض', 'text-right px-2')}
                {th('docnumber', 'الروشتة', 'text-right px-2')}
                {th('branchcode', 'الفرع', 'text-center px-2')}
                {th('docdate', 'التاريخ', 'text-right px-2')}
                {th('quantity', 'الكمية', 'text-left px-2')}
                {th('line_total', 'الإجمالى', 'text-left px-2')}
                {th('net_amount', 'الصافى', 'text-left px-2')}
                <th className="text-center pb-1 pt-2 px-2">الاعتماد</th>
                <th className="text-right pb-1 pt-2 px-2">ملاحظة المراجعة</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map(r => (
                <tr key={r.line_id} {...kb.rowProps(r)}
                  className={`${r.review_approved ? 'bg-green-50/40' : ''} ${kb.rowProps(r).className}`}>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    {r.flags.map(f => (
                      <span key={f} title={_FLAG_META[f]?.tip}
                        className={`inline-block text-[10px] rounded px-1 ml-0.5 ${_FLAG_META[f]?.cls}`}>
                        {_FLAG_META[f]?.icon}
                      </span>
                    ))}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-gray-500">{r.itemcode}</td>
                  <td className="px-2 py-1.5 text-gray-800">{r.item_name}</td>
                  <td className="px-2 py-1.5 text-gray-600">{r.patient_name || '—'}</td>
                  <td className="px-2 py-1.5 font-mono text-gray-500">{r.docnumber}</td>
                  <td className="px-2 py-1.5 text-center font-mono text-gray-600">{r.branchcode}</td>
                  <td className="px-2 py-1.5 font-mono text-gray-500 whitespace-nowrap">{r.docdate || '—'}</td>
                  <td className="px-2 py-1.5 text-left font-mono">{r.quantity}</td>
                  <td className="px-2 py-1.5 text-left font-mono">{fmt(r.line_total)}</td>
                  <td className="px-2 py-1.5 text-left font-mono font-semibold">{fmt(r.net_amount)}</td>
                  <td className="px-2 py-1.5 text-center whitespace-nowrap">
                    {r.review_approved ? (
                      <div className="flex flex-col items-center gap-0.5">
                        <button onClick={() => review(r, false)} disabled={saving === r.line_id}
                          className="text-[11px] text-green-700 bg-green-100 rounded px-2 py-0.5 hover:bg-green-200 disabled:opacity-50">
                          ✓ معتمَد
                        </button>
                        {r.reviewed_by && <span className="text-[9px] text-gray-400">{r.reviewed_by}</span>}
                      </div>
                    ) : (
                      <button onClick={() => review(r, true)} disabled={saving === r.line_id}
                        className="text-[11px] bg-blue-600 text-white rounded px-2 py-0.5 hover:bg-blue-700 disabled:opacity-50">
                        {saving === r.line_id ? '…' : 'اعتماد'}
                      </button>
                    )}
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      value={noteDraft[r.line_id] ?? r.review_note ?? ''}
                      onChange={e => setNoteDraft(s => ({ ...s, [r.line_id]: e.target.value }))}
                      onBlur={e => { if ((e.target.value || '') !== (r.review_note || '')) review(r, r.review_approved) }}
                      placeholder="سبب الاعتماد / ملاحظة…"
                      className="border border-gray-200 rounded px-2 py-0.5 text-[11px] w-full min-w-[140px]" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// SOFTECH RE-PRICE TAB — preview a receipt price edit on HQ+branch, gated apply,
// rebalance the contract client's running balance, and revert. WRITES are disabled
// unless the backend flag INSURANCE_SOFTECH_WRITE_ENABLED is on.
// ═══════════════════════════════════════════════════════════════════════════════
// ── Temporary SOFTECH receipt-date edit (for the 7-day reprint window) ─────────
function SoftechDateEditCard({ claimId, claim, inp }) {
  const [docno, setDocno]   = useState('')
  const [branch, setBranch] = useState('')
  const [newDate, setNewDate] = useState('')
  const [pv, setPv]         = useState(null)
  const [runs, setRuns]     = useState([])
  const [busy, setBusy]     = useState(false)
  const [msg, setMsg]       = useState(null)

  const loadRuns = () => insuranceApi.dateEditRuns(claimId).then(r => setRuns(r.data)).catch(() => {})
  useEffect(() => { loadRuns() }, [claimId])   // eslint-disable-line

  const preview = async () => {
    if (!docno.trim() || !branch.trim()) return
    setBusy(true); setMsg(null); setPv(null)
    try {
      const { data } = await insuranceApi.dateEditPreview(claimId, { docno: docno.trim(), branch: branch.trim(), new_date: newDate })
      setPv(data)
    } catch (e) { setMsg({ err: e.response?.data?.error || 'تعذّرت المعاينة' }) }
    finally { setBusy(false) }
  }
  const apply = async () => {
    if (!newDate) { setMsg({ err: 'اختر التاريخ الجديد' }); return }
    if (!window.confirm(`تغيير التاريخ المطبوع للإيصال #${docno} إلى ${newDate} على HQ والفرع؟ (مؤقت — استرجعه بعد الطباعة).`)) return
    setBusy(true); setMsg(null)
    try {
      const { data } = await insuranceApi.dateEditApply(claimId, { docno: docno.trim(), branch: branch.trim(), new_date: newDate, confirm: true })
      setMsg({ ok: `تم توحيد التاريخ (الإيصال + المطالبة): ${data.old_date} → ${data.new_date}. اطبع الإيصال الآن ثم استرجع تاريخ الإيصال من السجل بالأسفل (يبقى تاريخ المطالبة مصححاً).` })
      setPv(null); loadRuns()
    } catch (e) { setMsg({ err: e.response?.data?.error || 'تعذّر التطبيق' }) }
    finally { setBusy(false) }
  }
  const revert = async (runId) => {
    if (!window.confirm('استرجاع التاريخ الأصلى للإيصال؟')) return
    setBusy(true); setMsg(null)
    try { await insuranceApi.dateEditRevert(claimId, runId); setMsg({ ok: 'تم استرجاع التاريخ الأصلى.' }); loadRuns() }
    catch (e) { setMsg({ err: e.response?.data?.error || 'تعذّر الاسترجاع' }) }
    finally { setBusy(false) }
  }

  return (
    <div className="bg-white border border-purple-200 rounded-xl p-4">
      <div className="text-sm font-medium text-purple-800 mb-1">📅 تعديل تاريخ الإيصال (مؤقت — للطباعة ثم الاسترجاع)</div>
      <p className="text-[11px] text-gray-500 mb-3">
        عند إعادة إدخال روشتة مُرتجعة كفاتورة جديدة تأخذ تاريخ اليوم، اضبط التاريخ المطبوع ليقع ضمن ٧ أيام من تاريخ الروشتة الفعلى،
        اطبع النسخة الجديدة، ثم استرجع تاريخ الإيصال الأصلى.
        <br/>عند التطبيق: يُوحَّد التاريخ على <b>الإيصال (HQ + الفرع)</b> و<b>المطالبة (motalba)</b>.
        عند الاسترجاع: يُعاد <b>تاريخ الإيصال فقط</b> — بينما يبقى تاريخ المطالبة على القيمة المصححة. (لا يُمَس وقت المعاملة.)
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-500">رقم الإيصال<input className={`${inp} w-32 block mt-0.5`} value={docno} onChange={e => setDocno(e.target.value)} /></label>
        <label className="text-xs text-gray-500">الفرع<input className={`${inp} w-24 block mt-0.5`} value={branch} onChange={e => setBranch(e.target.value)} /></label>
        <label className="text-xs text-gray-500">التاريخ الجديد<input type="date" className={`${inp} w-40 block mt-0.5`} value={newDate} onChange={e => setNewDate(e.target.value)} /></label>
        <button onClick={preview} disabled={busy || !docno.trim() || !branch.trim()} className="px-3 py-1.5 bg-gray-800 text-white text-sm rounded disabled:opacity-50">معاينة</button>
        <button onClick={apply} disabled={busy || !newDate || claim?.status !== 'draft'} className="px-3 py-1.5 bg-purple-600 text-white text-sm rounded disabled:opacity-50">تطبيق التاريخ</button>
      </div>
      {pv && (
        <div className="mt-2 text-xs text-gray-700">
          التاريخ الحالى: <span className="font-mono">{pv.current_date}</span> → الجديد: <span className="font-mono">{pv.new_date || '—'}</span>
          {' · '}الفرع {pv.branch_reachable ? <span className="text-green-600">متصل</span> : <span className="text-red-600">غير متاح</span>}
          {!pv.write_enabled && <span className="text-amber-600"> · الكتابة معطّلة</span>}
        </div>
      )}
      {msg?.ok && <div className="mt-2 text-xs text-green-700">{msg.ok}</div>}
      {msg?.err && <div className="mt-2 text-xs text-red-600">{msg.err}</div>}
      {runs.length > 0 && (
        <div className="mt-3 border-t border-gray-100 pt-2">
          <div className="text-xs font-medium text-gray-600 mb-1">سجل تعديلات التاريخ</div>
          {runs.map(r => (
            <div key={r.id} className="text-xs flex items-center justify-between border-b border-gray-100 py-1">
              <span><span className="font-mono">#{r.docnumber}</span> فرع {r.branch} · {r.old_date} → {r.new_date}
                {r.status === 'reverted' && <span className="text-gray-400"> · مُسترجَع</span>}
                {r.status === 'failed' && <span className="text-red-500"> · فشل</span>}
              </span>
              {r.status === 'applied' && (
                <button onClick={() => revert(r.id)} disabled={busy} className="text-[11px] text-red-500 hover:text-red-700">↩ استرجاع التاريخ</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SoftechRepriceTab({ claimId, claim }) {
  const [docno, setDocno]   = useState('')
  const [branch, setBranch] = useState('')
  const [rows, setRows]     = useState([{ itemcode: '', price: '' }])
  const [pv, setPv]         = useState(null)
  const [busy, setBusy]     = useState(false)
  const [msg, setMsg]       = useState(null)
  const [runs, setRuns]     = useState([])
  const [recLines, setRecLines] = useState(null)   // fetched receipt lines to pick from
  // item-code → multi-receipt batch
  const [bCode, setBCode]   = useState('')
  const [bList, setBList]   = useState(null)        // {receipts:[...]}
  const [bSel, setBSel]     = useState(new Set())
  const [bPrice, setBPrice] = useState('')
  const [bRes, setBRes]     = useState(null)

  const loadRuns = () => insuranceApi.repriceRuns(claimId).then(r => setRuns(r.data)).catch(() => {})
  useEffect(() => { loadRuns() }, [claimId])   // eslint-disable-line

  const exportRuns = async (status) => {
    try {
      const { data: blob } = await insuranceApi.repriceRunsExport(claimId, status)
      const url = URL.createObjectURL(new Blob([blob], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }))
      const a = document.createElement('a')
      a.href = url
      a.download = status === 'failed' ? `تعديلات_سوفتك_فاشلة_${claimId}.xlsx` : `تعديلات_سوفتك_${claimId}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch { /* noop */ }
  }

  const fetchLines = async () => {
    if (!docno.trim() || !branch.trim()) return
    setBusy(true); setMsg(null); setRecLines(null)
    try {
      const { data } = await insuranceApi.repriceReceiptLines(claimId, docno.trim(), branch.trim())
      setRecLines(data.lines || [])
    } catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّر جلب البنود' }) }
    finally { setBusy(false) }
  }
  const pickLine = (l) => {
    setRows(rs => {
      const empty = rs.findIndex(r => !r.itemcode.trim())
      if (empty >= 0) return rs.map((r, i) => i === empty ? { ...r, itemcode: l.itemcode } : r)
      return [...rs, { itemcode: l.itemcode, price: '' }]
    })
  }

  const searchItem = async () => {
    if (!bCode.trim()) return
    setBusy(true); setMsg(null); setBList(null); setBRes(null)
    try {
      const { data } = await insuranceApi.repriceItemReceipts(claimId, bCode.trim())
      setBList(data)
      setBSel(new Set((data.receipts || []).map(r => `${r.docno}__${r.branch}`)))
    } catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّر البحث' }) }
    finally { setBusy(false) }
  }
  const applyBatch = async () => {
    const receipts = (bList?.receipts || []).filter(r => bSel.has(`${r.docno}__${r.branch}`))
    if (!receipts.length || bPrice === '') return
    if (!window.confirm(`تطبيق سعر ${bPrice} للصنف ${bList.itemcode} على ${receipts.length} إيصال؟ كل إيصال عملية مستقلة قابلة للتراجع.`)) return
    setBusy(true); setMsg(null)
    try {
      const { data } = await insuranceApi.repriceApplyBatch(claimId, {
        itemcode: bList.itemcode, new_price: bPrice,
        receipts: receipts.map(r => ({ docno: r.docno, branch: r.branch })), confirm: true })
      setBRes(data)
      setMsg({ ok: `تم تطبيق ${data.applied} من ${receipts.length}${data.failed ? ` (فشل ${data.failed})` : ''}.` })
      loadRuns()
    } catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّر التطبيق الدفعى' }) }
    finally { setBusy(false) }
  }

  const pricesObj = () => Object.fromEntries(
    rows.filter(r => r.itemcode.trim() && r.price !== '').map(r => [r.itemcode.trim(), r.price]))

  const doPreview = async () => {
    setBusy(true); setMsg(null); setPv(null)
    try {
      const { data } = await insuranceApi.repricePreview(claimId, { docnumber: docno.trim(), branch: branch.trim(), prices: pricesObj() })
      setPv(data)
    } catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّرت المعاينة' }) }
    finally { setBusy(false) }
  }

  const doApply = async () => {
    if (!window.confirm(`تأكيد الكتابة إلى سوفتك (HQ + الفرع) للإيصال #${docno}؟`)) return
    setBusy(true); setMsg(null)
    try {
      const { data } = await insuranceApi.repriceApply(claimId, { docnumber: docno.trim(), branch: branch.trim(), prices: pricesObj(), confirm: true })
      setMsg({ ok: `تم التطبيق (عملية #${data.run_id}). صافى Δ ${data.net_delta}. إعادة ضبط الرصيد اختيارية من سجل العمليات بالأسفل.` })
      loadRuns()
    } catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّر التطبيق' }) }
    finally { setBusy(false) }
  }

  const doRebalance = async (run) => {
    // read-only footprint first
    let foot
    try { foot = (await insuranceApi.repriceRebalance(claimId, run.id, {})).data } catch { /* ignore */ }
    const n = foot?.affected ?? '؟'
    if (foot && foot.is_ledger === false) {
      setMsg({ err: `هذا الحساب لا يحمل رصيداً تراكمياً دفترياً (فحص ${foot.ledger_checked} عملية) — إعادة الضبط محظورة لتجنّب إفساد قيمة غير دفترية.` })
      return
    }
    if (!window.confirm(`إعادة ضبط الرصيد التراكمى لعميل التعاقد ${run.cust_branch_code} (رصيد ${foot?.edit_balance ?? '—'}): سيُزاح ${n} صف على HQ فقط (ترتيب الرصيد) بمقدار صافى Δ ${run.net_delta}. القيمة داخلية (رصيد ائتمان) ولا تظهر على الإيصال المطبوع. متابعة؟`)) return
    setBusy(true); setMsg(null)
    try {
      const { data } = await insuranceApi.repriceRebalance(claimId, run.id, { confirm: true })
      setMsg({ ok: `أُعيد ضبط ${data.updated} صف.` })
      loadRuns()
    } catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّرت إعادة الضبط' }) }
    finally { setBusy(false) }
  }

  const doRevert = async (run) => {
    if (!window.confirm(`التراجع عن العملية #${run.id}؟`)) return
    setBusy(true); setMsg(null)
    try { await insuranceApi.repriceRevert(claimId, run.id); setMsg({ ok: 'تم التراجع.' }); loadRuns() }
    catch (e) { setMsg({ err: e?.response?.data?.detail || 'تعذّر التراجع' }) }
    finally { setBusy(false) }
  }

  const inp = 'border border-gray-300 rounded px-2 py-1.5 text-sm'
  const canApply = pv && pv.write_enabled && pv.branch_consistency?.reachable && claim?.status === 'draft'

  return (
    <div className="space-y-4" dir="rtl">
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
        تعديل سعر إيصال داخل سوفتك (stktrans + stktransm + branchesales) على HQ والفرع، ليتطابق الإيصال المطبوع مع المطالبة بعد إعادة التسعير.
        الكتابة معطّلة افتراضياً — المعاينة متاحة دائماً، والتطبيق يتطلب تفعيل العلم بالسيرفر + مطالبة مسودة + فرع متصل.
      </div>

      <SoftechDateEditCard claimId={claimId} claim={claim} inp={inp} />


      {/* ─── (1) Receipt-driven: fetch a receipt's lines and pick an item ─── */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="text-sm font-medium text-gray-700 mb-2">١) تعديل بإيصال — اكتب رقم الإيصال والفرع، اجلب البنود، اختر الصنف واكتب السعر</div>
        <div className="flex flex-wrap items-end gap-2 mb-3">
          <label className="text-xs text-gray-500">رقم الإيصال<input className={`${inp} w-32 block mt-0.5`} value={docno}
            onChange={e => setDocno(e.target.value)} onKeyDown={e => e.key === 'Enter' && fetchLines()} /></label>
          <label className="text-xs text-gray-500">الفرع<input className={`${inp} w-24 block mt-0.5`} value={branch}
            onChange={e => setBranch(e.target.value)} onKeyDown={e => e.key === 'Enter' && fetchLines()} /></label>
          <button onClick={fetchLines} disabled={busy || !docno.trim() || !branch.trim()}
            className="px-3 py-1.5 bg-sky-600 text-white text-sm rounded hover:bg-sky-700 disabled:opacity-50">جلب البنود</button>
        </div>
        {recLines && (
          <div className="mb-3 border border-gray-100 rounded-lg overflow-hidden">
            {recLines.length === 0 ? <div className="text-xs text-gray-400 p-2">لا توجد بنود لهذا الإيصال.</div> : (
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500"><tr>
                  <th className="text-right px-2 py-1">الكود</th><th className="text-right px-2 py-1">الصنف</th>
                  <th className="text-left px-2 py-1">كمية</th><th className="text-left px-2 py-1">السعر الحالى</th><th></th></tr></thead>
                <tbody>
                  {recLines.map((l, i) => (
                    <tr key={i} className="border-t border-gray-100 hover:bg-sky-50/40">
                      <td className="px-2 py-1 font-mono text-gray-500">{l.itemcode}</td>
                      <td className="px-2 py-1 text-gray-800">{l.item_name}</td>
                      <td className="px-2 py-1 text-left font-mono">{l.qty}</td>
                      <td className="px-2 py-1 text-left font-mono">{fmt(l.itemsaleprice)}</td>
                      <td className="px-2 py-1 text-left"><button onClick={() => pickLine(l)} className="text-sky-600 text-xs hover:underline">اختيار ←</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        <table className="text-sm mb-2">
          <thead><tr className="text-xs text-gray-500"><th className="text-right px-2">كود الصنف</th><th className="text-right px-2">السعر الجديد</th><th></th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="px-2 py-1"><input className={`${inp} w-32`} value={r.itemcode} onChange={e => setRows(rs => rs.map((x, j) => j === i ? { ...x, itemcode: e.target.value } : x))} /></td>
                <td className="px-2 py-1"><input type="number" step="any" className={`${inp} w-28 text-left`} value={r.price} onChange={e => setRows(rs => rs.map((x, j) => j === i ? { ...x, price: e.target.value } : x))} /></td>
                <td className="px-2 py-1">{rows.length > 1 && <button onClick={() => setRows(rs => rs.filter((_, j) => j !== i))} className="text-red-500 text-xs">حذف</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex gap-2">
          <button onClick={() => setRows(rs => [...rs, { itemcode: '', price: '' }])} className="text-xs text-blue-600">+ صنف</button>
          <button onClick={doPreview} disabled={busy || !docno.trim() || !branch.trim()} className="px-3 py-1.5 bg-gray-800 text-white text-sm rounded disabled:opacity-50">معاينة (قراءة فقط)</button>
        </div>
      </div>

      {/* ─── (2) Item-driven: batch re-price one item across many receipts ─── */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="text-sm font-medium text-gray-700 mb-2">٢) تعديل صنف عبر عدة إيصالات — اكتب كود الصنف لعرض كل إيصالاته فى هذه المطالبة وتحديثها دفعة واحدة</div>
        <div className="flex flex-wrap items-end gap-2 mb-2">
          <label className="text-xs text-gray-500">كود الصنف<input className={`${inp} w-36 block mt-0.5`} value={bCode}
            onChange={e => setBCode(e.target.value)} onKeyDown={e => e.key === 'Enter' && searchItem()} /></label>
          <button onClick={searchItem} disabled={busy || !bCode.trim()}
            className="px-3 py-1.5 bg-sky-600 text-white text-sm rounded hover:bg-sky-700 disabled:opacity-50">بحث</button>
          {bList && bList.receipts.length > 0 && <>
            <label className="text-xs text-gray-500">السعر الجديد<input type="number" step="any" className={`${inp} w-28 block mt-0.5 text-left`} value={bPrice} onChange={e => setBPrice(e.target.value)} /></label>
            <button onClick={applyBatch} disabled={busy || bSel.size === 0 || bPrice === '' || claim?.status !== 'draft'}
              className="px-4 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-40"
              title={claim?.status !== 'draft' ? 'المطالبة ليست مسودة' : ''}>
              تطبيق دفعة على {bSel.size} إيصال
            </button>
          </>}
        </div>
        {bList && (bList.receipts.length === 0
          ? <div className="text-xs text-gray-400">لا توجد إيصالات بهذا الصنف فى هذه المطالبة.</div>
          : (
          <div className="border border-gray-100 rounded-lg overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-gray-500"><tr>
                <th className="px-2 py-1"><input type="checkbox" checked={bSel.size === bList.receipts.length}
                  onChange={() => setBSel(s => s.size === bList.receipts.length ? new Set() : new Set(bList.receipts.map(r => `${r.docno}__${r.branch}`)))} /></th>
                <th className="text-right px-2 py-1">الإيصال</th><th className="text-center px-2 py-1">الفرع</th>
                <th className="text-right px-2 py-1">التاريخ</th><th className="text-right px-2 py-1">المريض</th>
                <th className="text-left px-2 py-1">السعر المجمّد</th><th className="text-left px-2 py-1">كمية</th><th className="px-2 py-1"></th></tr></thead>
              <tbody>
                {bList.receipts.map((r, i) => {
                  const key = `${r.docno}__${r.branch}`
                  const res = bRes?.results?.find(x => String(x.docno) === String(r.docno) && String(x.branch) === String(r.branch))
                  return (
                    <tr key={i} className="border-t border-gray-100">
                      <td className="px-2 py-1 text-center"><input type="checkbox" checked={bSel.has(key)}
                        onChange={() => setBSel(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })} /></td>
                      <td className="px-2 py-1 font-mono text-gray-600">#{r.docno}</td>
                      <td className="px-2 py-1 text-center font-mono">{r.branch}</td>
                      <td className="px-2 py-1 font-mono text-gray-500 whitespace-nowrap">{r.docdate || '—'}</td>
                      <td className="px-2 py-1 text-gray-700">{r.patient || '—'}</td>
                      <td className="px-2 py-1 text-left font-mono">{fmt(r.unit_price)}</td>
                      <td className="px-2 py-1 text-left font-mono">{r.quantity}</td>
                      <td className="px-2 py-1 text-left">{res && (res.ok
                        ? <span className="text-green-600">✓ #{res.run_id} (Δ{res.net_delta})</span>
                        : <span className="text-red-500" title={res.error}>✕ فشل</span>)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {msg && <div className={`text-sm rounded-lg p-2 ${msg.err ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>{msg.err || msg.ok}</div>}

      {/* Preview result */}
      {pv && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 text-sm space-y-3">
          <div className="flex flex-wrap gap-3 text-xs">
            <span className={`px-2 py-0.5 rounded ${pv.write_enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>الكتابة {pv.write_enabled ? 'مُفعّلة' : 'معطّلة'}</span>
            <span className={`px-2 py-0.5 rounded ${pv.branch_consistency?.reachable ? (pv.branch_consistency.consistent ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700') : 'bg-amber-100 text-amber-700'}`}>
              الفرع {pv.branch_consistency?.reachable ? (pv.branch_consistency.consistent ? 'متصل ومتطابق' : 'متصل لكن غير متطابق') : 'غير متصل'}
            </span>
            <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700">عميل التعاقد {pv.cust_branch_code || '—'}</span>
          </div>
          {pv.lines.map((l, i) => (
            <div key={i} className="border-b border-gray-100 pb-2">
              <div className="font-medium">صنف {l.itemcode} <span className="text-xs text-gray-400">(ض {l.vat_rate}%, كمية {l.transqty})</span></div>
              {Object.entries(l.changes).map(([f, ch]) => (
                <div key={f} className="text-xs text-gray-600 flex gap-2"><span className="w-40">{f}</span><span className="font-mono">{ch.old} → <b className="text-gray-900">{ch.new}</b></span></div>
              ))}
            </div>
          ))}
          <div className="text-xs text-gray-700 grid grid-cols-2 gap-1 max-w-md">
            {Object.entries(pv.header).map(([f, ch]) => <div key={f}><span className="text-gray-400">{f}</span> {ch.old} → <b>{ch.new}</b></div>)}
            <div><span className="text-gray-400">docvalue2 (تكلفة)</span> {pv.docvalue2_cost} (ثابت)</div>
            <div><span className="text-gray-400">التحصيل الجديد</span> {pv.tender_new}</div>
            <div><span className="text-gray-400">صافى Δ</span> <b>{pv.net_delta}</b></div>
            {pv.motalba_rows > 0 && <div className="text-blue-700">سيُحدَّث «المطلوب سداده» فى {pv.motalba_rows} مطالبة (سوفتك) ليطابق الصافى الجديد</div>}
            <div className="text-gray-500">إعادة ضبط الرصيد التراكمى اختيارية (من سجل العمليات بعد التطبيق)</div>
          </div>
          <button onClick={doApply} disabled={busy || !canApply}
            className="px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-40"
            title={!canApply ? 'التطبيق محظور (الكتابة معطّلة / الفرع غير متصل / المطالبة ليست مسودة)' : ''}>
            تطبيق على سوفتك (HQ + الفرع)
          </button>
        </div>
      )}

      {/* Runs history */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="font-medium text-gray-800 text-sm">
            سجل تعديلات سوفتك ({runs.length})
            {runs.some(r => r.status === 'failed') &&
              <span className="text-red-500 font-normal"> · {runs.filter(r => r.status === 'failed').length} فشل</span>}
          </div>
          {runs.length > 0 && (
            <div className="flex gap-2">
              <button onClick={() => exportRuns()} className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50">
                📥 تصدير السجل
              </button>
              {runs.some(r => r.status === 'failed') &&
                <button onClick={() => exportRuns('failed')} className="text-xs px-2 py-1 rounded border border-red-300 text-red-600 hover:bg-red-50">
                  📥 تصدير الفاشلة فقط
                </button>}
            </div>
          )}
        </div>
        {runs.length === 0 ? <div className="text-xs text-gray-400">لا توجد عمليات.</div> : (
          <table className="w-full text-xs">
            <thead className="text-gray-500"><tr><th className="text-right py-1">التاريخ</th><th>الإيصال</th><th>الفرع</th><th>الحالة</th><th>صافى Δ</th><th>عميل التعاقد</th><th></th></tr></thead>
            <tbody>
              {runs.map(r => {
                const statusLabel = { preview: 'معاينة', applied: 'مُطبَّق', reverted: 'مُتراجَع', failed: 'فشل' }[r.status] || r.status
                const statusCls = r.status === 'failed' ? 'text-red-600 font-semibold'
                  : r.status === 'applied' ? 'text-green-600' : 'text-gray-500'
                return (
                <tr key={r.id} className={`border-t border-gray-100 ${r.status === 'failed' ? 'bg-red-50/60' : ''}`}>
                  <td className="py-1 text-center whitespace-nowrap" dir="ltr">
                    {r.applied_at ? toLatinDigits(new Date(r.applied_at).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' })) : '—'}
                  </td>
                  <td className="font-mono">#{r.docnumber}</td>
                  <td className="text-center">{r.branch}</td>
                  <td className={`text-center ${statusCls}`} title={r.status === 'failed' ? (r.error || '') : ''}>{statusLabel}</td>
                  <td className="text-center font-mono">{r.net_delta}</td>
                  <td className="text-center">{r.cust_branch_code}</td>
                  <td className="text-left space-x-1 space-x-reverse">
                    {r.status === 'applied' && <>
                      <button onClick={() => doRebalance(r)} disabled={busy || r.rebalanced} className="text-sky-600 disabled:text-gray-300"
                        title="اختيارى وتقريبى — يصحّح رصيد الائتمان الداخلى فقط (لا يظهر على الإيصال المطبوع)">
                        {r.rebalanced ? '✓ أُعيد الضبط' : 'إعادة ضبط الرصيد (اختيارى)'}</button>
                      <button onClick={() => doRevert(r)} disabled={busy} className="text-red-500">تراجع</button>
                    </>}
                  </td>
                </tr>
              )})}
            </tbody>
          </table>
        )}
        {runs.some(r => r.status === 'failed') && (
          <div className="mt-3 border-t border-red-100 pt-2">
            <div className="text-[11px] font-semibold text-red-600 mb-1">التعديلات الفاشلة (سبب الفشل)</div>
            {runs.filter(r => r.status === 'failed').map(r => (
              <div key={`e-${r.id}`} className="text-[11px] text-red-700 mb-0.5">
                <span className="font-mono">#{r.docnumber}</span> / فرع {r.branch}: {r.error || '—'}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ReadinessTab({ claimId }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)

  const run = () => {
    setLoading(true)
    insuranceApi.readiness(claimId)
      .then(r => setData(r.data))
      .finally(() => setLoading(false))
  }
  useEffect(() => { run() }, [claimId])

  if (loading) return <div className="px-6 py-6 text-sm text-gray-400">جارٍ فحص الجاهزية…</div>
  if (!data)   return null

  const scoreColor = data.health_score >= 90 ? 'text-green-600'
                   : data.health_score >= 60 ? 'text-amber-600' : 'text-red-600'

  // Sort: errors → warnings → info → ok
  const order = { error: 0, warning: 1, info: 2, ok: 3 }
  const checks = [...data.checks].sort((a, b) => order[a.severity] - order[b.severity])

  return (
    <div className="px-6 py-4">
      {/* Gate banner */}
      <div className={`rounded-xl border p-4 mb-4 flex items-center justify-between flex-wrap gap-3 ${
        data.can_issue ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
        <div className="flex items-center gap-4">
          <div className="text-center">
            <p className="text-xs text-gray-500">درجة الجاهزية</p>
            <p className={`text-2xl font-bold font-mono ${scoreColor}`}>{data.health_score}</p>
          </div>
          <div>
            <p className={`font-bold ${data.can_issue ? 'text-green-700' : 'text-red-700'}`}>
              {data.can_issue ? '✓ المطالبة جاهزة للإصدار' : '✕ لا يمكن الإصدار — يوجد ما يجب إصلاحه'}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              {data.summary.errors} خطأ · {data.summary.warnings} تحذير · {data.summary.rx_active} روشتة
            </p>
          </div>
        </div>
        <button onClick={run} className="px-3 py-2 bg-white border border-gray-300 text-sm rounded hover:bg-gray-50">
          إعادة الفحص
        </button>
      </div>

      {/* Checks */}
      <div className="space-y-2">
        {checks.map(c => {
          const cfg = SEV_CFG[c.severity] || SEV_CFG.info
          return (
            <div key={c.key} className={`rounded-lg border p-3 ${cfg.cls}`}>
              <div className="flex items-center gap-2">
                <span className={`w-5 h-5 rounded-full grid place-items-center text-xs font-bold ${cfg.badge}`}>
                  {cfg.icon}
                </span>
                <span className="font-medium text-gray-800">{c.label}</span>
                {c.count > 0 && (
                  <span className={`text-xs px-1.5 rounded ${cfg.badge}`}>{c.count}</span>
                )}
              </div>
              {c.detail && <p className="text-xs text-gray-600 mt-1 mr-7">{c.detail}</p>}

              {/* Short patient-name check: tier badges + per-branch breakdown */}
              {c.key === 'short_patient_names' && c.branches && (
                <div className="mt-2 mr-7 space-y-2">
                  <div className="flex flex-wrap gap-1.5 items-center">
                    <span className="text-[11px] rounded px-1.5 py-0.5 bg-red-100 text-red-700 font-medium" title="اسم فردى — أعلى خطورة">فردى {c.tiers?.['فردى'] || 0}</span>
                    <span className="text-[11px] rounded px-1.5 py-0.5 bg-orange-100 text-orange-700 font-medium" title="اسم ثنائى — خطورة عالية">ثنائى {c.tiers?.['ثنائى'] || 0}</span>
                    <span className="text-[11px] rounded px-1.5 py-0.5 bg-amber-100 text-amber-700 font-medium" title="اسم ثلاثى — تحذير أخف">ثلاثى {c.tiers?.['ثلاثى'] || 0}</span>
                    {c.completable > 0 && (
                      <span className="text-[11px] rounded px-2 py-0.5 bg-emerald-100 text-emerald-800 font-semibold border border-emerald-300"
                        title="عدد الأسماء التى يمكن إكمالها رباعياً تلقائياً من السجل — من تبويب «مراجعة الأسماء» أو مباشرة من شبكة الروشتات">
                        ⇢ قابل للإكمال {c.completable}
                      </span>
                    )}
                  </div>
                  <details>
                    <summary className="text-[11px] text-gray-600 cursor-pointer select-none hover:text-gray-800">
                      التوزيع حسب الفرع ({c.branches.length} فرع)
                    </summary>
                    <div className="overflow-x-auto mt-1">
                      <table className="text-[11px] border border-gray-200 rounded">
                        <thead className="bg-gray-50 text-gray-500">
                          <tr>
                            <th className="text-right px-2 py-1">الفرع</th>
                            <th className="text-left px-2 py-1">غير رباعية</th>
                            <th className="text-left px-2 py-1">من إجمالى</th>
                            <th className="text-left px-2 py-1 text-red-600">فردى</th>
                            <th className="text-left px-2 py-1 text-orange-600">ثنائى</th>
                            <th className="text-left px-2 py-1 text-amber-600">ثلاثى</th>
                          </tr>
                        </thead>
                        <tbody>
                          {c.branches.map(b => (
                            <tr key={b.branch} className="border-t border-gray-100">
                              <td className="px-2 py-1 font-mono">{b.branch}</td>
                              <td className="px-2 py-1 text-left font-semibold">{b.failed}</td>
                              <td className="px-2 py-1 text-left text-gray-500">{b.total}</td>
                              <td className="px-2 py-1 text-left">{b['فردى'] || 0}</td>
                              <td className="px-2 py-1 text-left">{b['ثنائى'] || 0}</td>
                              <td className="px-2 py-1 text-left">{b['ثلاثى'] || 0}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                  <details>
                    <summary className="text-[11px] text-gray-600 cursor-pointer select-none hover:text-gray-800">
                      عرض الروشتات ({c.count})
                    </summary>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {c.items.slice(0, 200).map((it, i) => (
                        <span key={i} title={`${it.tokens} مقاطع · فرع ${it.branch}${it.completion ? ' · إكمال مقترح: ' + it.completion : ''}`}
                          className={`text-[11px] rounded px-1.5 py-0.5 border ${
                            it.completion
                              ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                              : it.tier_severity === 'high'
                              ? (it.tokens === 1 ? 'bg-red-50 text-red-700 border-red-200'
                                                 : 'bg-orange-50 text-orange-700 border-orange-200')
                              : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
                          <span className="font-mono">#{it.docnumber}</span> {it.patient}
                          {it.completion
                            ? <span className="text-emerald-600"> ⇢ {it.completion}</span>
                            : <span className="opacity-60"> · {it.tier}</span>}
                        </span>
                      ))}
                      {c.count > 200 && <span className="text-[11px] text-gray-500">+{c.count - 200}…</span>}
                    </div>
                  </details>
                </div>
              )}

              {c.key !== 'short_patient_names' && c.items?.length > 0 && (() => {
                const isItemCodes = !!c.items[0]?.item_code
                return (
                  <details className="mt-1 mr-7">
                    <summary className="text-[11px] text-gray-600 cursor-pointer select-none hover:text-gray-800">
                      {isItemCodes ? `عرض الأصناف (${c.items.length})` : `عرض القائمة (${c.items.length})`}
                    </summary>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {c.items.slice(0, 50).map((it, i) => (
                        <span key={i} className="text-[11px] bg-white/60 border border-current/20 rounded px-1.5 py-0.5">
                          {isItemCodes
                            ? <><span className="font-mono">{it.item_code}</span> — {it.item_name}
                                {it.category_label ? <span className="text-gray-500"> · {it.category_label}</span> : null}
                                {it.lines > 1 ? <span className="text-gray-400"> ×{it.lines}</span> : null}</>
                            : <span className="font-mono">#{it.docnumber}{it.claim ? ` → ${it.claim}` : ''}{it.patient ? ` (${it.patient})` : ''}</span>}
                        </span>
                      ))}
                      {c.items.length > 50 && <span className="text-[11px] text-gray-500">+{c.items.length - 50}…</span>}
                    </div>
                  </details>
                )
              })()}
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════════
// CLAIM ITEMS TAB — one row per dispensed item, with discount, all revisable
// ═══════════════════════════════════════════════════════════════════════════════

const CAT_BADGE = {
  local:    'bg-green-100 text-green-700',
  imported: 'bg-amber-100 text-amber-700',
  tarsia:   'bg-purple-100 text-purple-700',
}
function ItemCat({ category, label }) {
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${CAT_BADGE[category] || 'bg-gray-100 text-gray-600'}`}>{label}</span>
}

function ClaimItemsTab({ claimId, claim, onRefresh }) {
  const [data, setData]     = useState(null)
  const [loading, setLoad]  = useState(true)
  const [q, setQ]           = useState('')
  const [matchMode, setMatchMode] = useState('contains')  // contains | begins | ends
  const [searchIn, setSearchIn]   = useState('both')      // both | code | name
  const [catFilter, setCat] = useState('')     // '', local, imported, tarsia, mixed
  const [sort, setSort]     = useState('gross')
  const [sortDir, setSortDir] = useState('desc')
  const sortByCol = (k) => {
    if (sort === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSort(k); setSortDir(k === 'item_code' || k === 'item_name' || k === 'origin' || k === 'contract_classif' || k === 'category' ? 'asc' : 'desc') }
  }
  const [sel, setSel]       = useState({})     // item_code -> chosen category
  const [busy, setBusy]     = useState(null)
  const [msg, setMsg]       = useState(null)

  const load = () => {
    setLoad(true)
    insuranceApi.claimItems(claimId).then(r => setData(r.data)).finally(() => setLoad(false))
  }
  useEffect(() => { load() }, [claimId])   // eslint-disable-line

  const apply = async (code) => {
    const cat = sel[code]
    if (!cat) return
    if (!window.confirm(`تعيين التصنيف "${{ local: 'محلى', imported: 'مستورد', tarsia: 'ترسية' }[cat]}" لكل بنود الصنف ${code} في هذه المطالبة؟`)) return
    setBusy(code); setMsg(null)
    try {
      const { data: res } = await insuranceApi.applyReviewDecision(claimId, code, cat)
      setMsg(`تم تصنيف ${code}: ${res.lines_updated} بند · الصافى ${fmt(res.net_before)} → ${fmt(res.net_after)} (${res.net_delta > 0 ? '+' : ''}${fmt(res.net_delta)})`)
      load(); onRefresh && onRefresh()
    } catch (e) {
      setMsg(e.response?.data?.error || 'تعذّر تطبيق التصنيف')
    } finally { setBusy(null) }
  }

  if (loading) return <div className="px-6 py-6 text-sm text-gray-400">جارٍ تحميل الأصناف…</div>
  if (!data)   return null

  let items = data.items
  if (q.trim()) {
    const s = q.trim().toLowerCase()
    const contains = (v) => {
      v = (v || '').toString().toLowerCase()
      if (matchMode === 'begins') return v.startsWith(s)
      if (matchMode === 'ends')   return v.endsWith(s)
      return v.includes(s)   // 'contains' and 'notcontains' both use includes
    }
    // any in-scope field matches (code and/or name)
    const anyMatch = (it) =>
      (searchIn !== 'name' && contains(it.item_code)) ||
      (searchIn !== 'code' && contains(it.item_name))
    items = matchMode === 'notcontains'
      ? items.filter(it => !anyMatch(it))   // keep rows that do NOT contain the term
      : items.filter(anyMatch)
  }
  if (catFilter === 'mixed') items = items.filter(it => it.is_mixed)
  else if (catFilter)        items = items.filter(it => it.category === catFilter)
  const TEXT_COLS = new Set(['item_code', 'item_name', 'origin', 'contract_classif', 'category'])
  items = [...items].sort((a, b) => {
    let c
    if (TEXT_COLS.has(sort)) c = (a[sort] || '').toString().localeCompare((b[sort] || '').toString(), 'ar')
    else c = (Number(a[sort]) || 0) - (Number(b[sort]) || 0)
    return sortDir === 'asc' ? c : -c
  })

  const SortTh = ({ k, children, align = 'right' }) => (
    <th onClick={() => sortByCol(k)}
      className={`text-${align} px-2 py-2 font-semibold cursor-pointer select-none whitespace-nowrap ${sort === k ? 'text-blue-600' : 'text-gray-500'}`}>
      {children}{sort === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  )

  return (
    <div className="px-6 py-4">
      <div className="flex items-center gap-2 flex-wrap mb-3">
        <select value={matchMode} onChange={e => setMatchMode(e.target.value)}
          title="طريقة المطابقة" className="border border-gray-300 rounded px-2 py-2 text-sm">
          <option value="contains">يحتوي على</option>
          <option value="notcontains">لا يحتوي على</option>
          <option value="begins">يبدأ بـ</option>
          <option value="ends">ينتهي بـ</option>
        </select>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بكود أو اسم الصنف…"
          className="border border-gray-300 rounded px-3 py-2 text-sm w-56" />
        <select value={searchIn} onChange={e => setSearchIn(e.target.value)}
          title="نطاق البحث" className="border border-gray-300 rounded px-2 py-2 text-sm">
          <option value="both">الكود + الاسم</option>
          <option value="code">الكود فقط</option>
          <option value="name">الاسم فقط</option>
        </select>
        {q.trim() && (
          <button onClick={() => setQ('')} title="مسح البحث"
            className="text-gray-400 hover:text-gray-700 text-sm px-1">✕</button>
        )}
        <select value={catFilter} onChange={e => setCat(e.target.value)}
          className="border border-gray-300 rounded px-2 py-2 text-sm">
          <option value="">كل التصنيفات</option>
          <option value="local">محلى</option>
          <option value="imported">مستورد</option>
          <option value="tarsia">ترسية</option>
          <option value="mixed">مختلط (منشأ مزدوج)</option>
        </select>
        <span className="text-sm text-gray-500">{items.length} صنف من {data.item_count}</span>
        <span className="text-xs text-gray-400 mr-auto">
          نسب الخصم — محلى {data.rates.local}% · مستورد {data.rates.imported}% · ترسية {data.rates.tarsia}%
        </span>
      </div>
      {msg && <div className="mb-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">{msg}</div>}

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-right px-2 py-2 text-gray-500 font-semibold">م</th>
              <SortTh k="item_code">الكود</SortTh>
              <SortTh k="item_name">الصنف</SortTh>
              <SortTh k="origin">المنشأ</SortTh>
              <SortTh k="contract_classif">تصنيف التعاقدات</SortTh>
              <SortTh k="basic_discount" align="left">خصم أساسى</SortTh>
              <SortTh k="line_count" align="center">عدد بنود الصرف</SortTh>
              <SortTh k="gross" align="left">الإجمالى</SortTh>
              <SortTh k="discount_pct" align="left">نسبة الخصم</SortTh>
              <SortTh k="discount" align="left">قيمة الخصم</SortTh>
              <SortTh k="net" align="left">الصافى</SortTh>
              <SortTh k="category">التصنيف</SortTh>
              <th className="text-right px-2 py-2 text-gray-500 font-semibold">تعديل التصنيف لهذه المطالبة</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((it, i) => {
              const sv = sel[it.item_code] || it.category || 'local'
              const catalogMismatch = it.catalog_category && !it.is_mixed && it.catalog_category !== it.category
              return (
                <tr key={it.item_code} className="hover:bg-gray-50">
                  <td className="px-2 py-1.5 text-gray-400">{i + 1}</td>
                  <td className="px-2 py-1.5 font-mono text-xs">
                    {it.item_code}
                    {it.on_force  && <span title="على قائمة الفرض" className="ml-1">🔒</span>}
                    {it.on_review && <span title="على قائمة المراجعة (منشأ مزدوج)" className="ml-1">🔀</span>}
                  </td>
                  <td className="px-2 py-1.5">{it.item_name}</td>
                  <td className="px-2 py-1.5 text-xs text-gray-600">{it.origin || <span className="text-gray-300">—</span>}</td>
                  <td className="px-2 py-1.5 text-xs text-gray-600">
                    {it.contract_classif
                      ? <span title={`كود: ${it.contract_classif_code}`}>{it.contract_classif}</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-left text-gray-600">{it.basic_discount != null ? `${it.basic_discount}%` : '—'}</td>
                  <td className="px-2 py-1.5 text-center text-gray-500">{it.line_count}</td>
                  <td className="px-2 py-1.5 text-left">{fmt(it.gross)}</td>
                  <td className="px-2 py-1.5 text-left text-gray-500">{it.discount_pct}%</td>
                  <td className="px-2 py-1.5 text-left">{fmt(it.discount)}</td>
                  <td className="px-2 py-1.5 text-left font-medium">{fmt(it.net)}</td>
                  <td className="px-2 py-1.5">
                    {it.is_mixed
                      ? <span className="text-xs">
                          {it.categories.map(c => <span key={c.category} className="ml-1"><ItemCat category={c.category} label={`${c.label} ×${c.count}`} /></span>)}
                        </span>
                      : <ItemCat category={it.category} label={it.category_label} />}
                    {catalogMismatch && (
                      <span title={`تصنيف الكتالوج الحالى: ${it.catalog_label}`}
                        className="ml-1 text-[10px] text-amber-600">⚠ كتالوج: {it.catalog_label}</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-1">
                      <select value={sv} onChange={e => setSel(s => ({ ...s, [it.item_code]: e.target.value }))}
                        className="border border-gray-300 rounded px-2 py-1 text-xs">
                        <option value="local">محلى</option>
                        <option value="imported">مستورد</option>
                        <option value="tarsia">ترسية</option>
                      </select>
                      <button onClick={() => apply(it.item_code)} disabled={busy === it.item_code}
                        className="px-2.5 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50">
                        {busy === it.item_code ? '…' : 'تطبيق'}
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {items.length === 0 && (
              <tr><td colSpan={13} className="px-3 py-8 text-center text-gray-400">لا أصناف مطابقة.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════════
// VALUE DISCREPANCY TAB
// Compares the frozen snapshot classification against current item master data
// and shows where category / discount / net drifted. Reuses <DataTable>.
// ═══════════════════════════════════════════════════════════════════════════════

function DiscrepancyTab({ claimId, onRefresh }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [exporting, setExporting] = useState(false)
  const [applying, setApplying]   = useState(false)
  const [applyMsg, setApplyMsg]   = useState(null)
  const [applyPrice, setApplyPrice]       = useState(true)
  const [applyCategory, setApplyCategory] = useState(true)
  const [selLines, setSelLines] = useState(() => new Set())   // chosen line_ids (empty = all)

  const [history, setHistory] = useState([])
  const loadHistory = () => insuranceApi.applyHistory(claimId).then(r => setHistory(r.data)).catch(() => {})

  const [ovPreview, setOvPreview] = useState(null)   // overrides-preview result
  const [ovApplying, setOvApplying] = useState(false)
  const [ovMsg, setOvMsg] = useState(null)
  const loadOverrides = () => insuranceApi.overridesPreview(claimId)
    .then(r => setOvPreview(r.data)).catch(() => setOvPreview(null))

  // Dual-origin (review) items — decide category per motalba
  const [reviewItems, setReviewItems] = useState([])
  const [reviewSel, setReviewSel] = useState({})   // item_code -> chosen category
  const [reviewBusy, setReviewBusy] = useState(null)
  const [reviewMsg, setReviewMsg] = useState(null)
  const loadReview = () => insuranceApi.reviewItems(claimId)
    .then(r => setReviewItems(r.data.items || [])).catch(() => setReviewItems([]))

  const applyReview = async (code, cat) => {
    // `cat` is the EFFECTIVE selection (the dropdown shows a computed default even
    // when reviewSel[code] is still empty) — never read reviewSel here or the
    // button silently no-ops when the user leaves the default untouched.
    if (!cat) return
    setReviewBusy(code); setReviewMsg(null)
    try {
      const { data: res } = await insuranceApi.applyReviewDecision(claimId, code, cat)
      setReviewMsg(`تم تصنيف ${code}: ${res.lines_updated} بند · الصافى ${fmt(res.net_before)} → ${fmt(res.net_after)} (${res.net_delta > 0 ? '+' : ''}${fmt(res.net_delta)})`)
      await reload(); await loadHistory(); await loadReview()
      onRefresh && onRefresh()
    } catch (e) {
      setReviewMsg(e.response?.data?.error || 'تعذّر تطبيق التصنيف')
    } finally { setReviewBusy(null) }
  }

  const applyOverrides = async () => {
    if (!window.confirm('سيتم تطبيق تصويبات تصنيف الأصناف على هذه المطالبة (قابل للتراجع). متابعة؟')) return
    setOvApplying(true); setOvMsg(null)
    try {
      const { data: res } = await insuranceApi.applyOverrides(claimId)
      setOvMsg(`تم تصويب ${res.lines_updated} بند في ${res.prescriptions_updated} روشتة · `
        + `الصافى ${fmt(res.net_before)} → ${fmt(res.net_after)} (${res.net_delta > 0 ? '+' : ''}${fmt(res.net_delta)})`)
      await reload(); await loadHistory(); await loadOverrides()
      onRefresh && onRefresh()
    } catch (e) {
      setOvMsg(e.response?.data?.error || 'تعذّر تطبيق التصويبات')
    } finally { setOvApplying(false) }
  }

  const reload = () => {
    setLoading(true); setError(null)
    return insuranceApi.discrepancy(claimId)
      .then(r => setData(r.data))
      .catch(e => setError(e.response?.data?.error || 'تعذّر حساب الفروقات'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { reload(); loadHistory(); loadOverrides(); loadReview() }, [claimId])

  const revertRun = async (runId) => {
    if (!window.confirm('سيتم استرجاع القيم الأصلية لهذه العملية. متابعة؟')) return
    try {
      await insuranceApi.revertApplyRun(claimId, runId)
      await reload(); await loadHistory()
      onRefresh && onRefresh()
    } catch (e) {
      alert(e.response?.data?.error || 'تعذّر التراجع')
    }
  }

  const exportExcel = async () => {
    setExporting(true)
    try {
      const { data: blob } = await insuranceApi.discrepancyExport(claimId)
      const url = URL.createObjectURL(new Blob([blob], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }))
      const a = document.createElement('a')
      a.href = url; a.download = `فروقات_${claimId}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } finally { setExporting(false) }
  }

  const applyMaster = async () => {
    if (!applyPrice && !applyCategory) return
    const ids = selLines.size ? [...selLines] : null
    const scope = ids ? `${ids.length} بند محدد` : 'كل البنود المتغيّرة'
    const what = [applyCategory && 'التصنيف', applyPrice && 'الأسعار'].filter(Boolean).join(' و')
    if (!window.confirm(`سيتم تحديث ${scope} لتطابق ${what} الحالية في الكتالوج. هذا الإجراء يعدّل قيم المطالبة المجمّدة (قابل للتراجع). متابعة؟`)) return
    setApplying(true); setApplyMsg(null)
    try {
      const { data: res } = await insuranceApi.applyCurrentMaster(claimId, {
        apply_price: applyPrice, apply_category: applyCategory,
        ...(ids ? { line_ids: ids } : {}),
      })
      let msg = `تم التحديث: ${res.lines_updated} بند في ${res.prescriptions_updated} روشتة · `
        + `الصافى ${fmt(res.net_before)} → ${fmt(res.net_after)} (${res.net_delta > 0 ? '+' : ''}${fmt(res.net_delta)})`
      if (res.skipped_count) {
        const codes = (res.skipped || []).slice(0, 8)
          .map(s => `${s.itemcode || s.line_id} (${s.error})`).join('، ')
        msg += ` · ⚠️ تم تخطّى ${res.skipped_count} بند لتعذّر معالجته: ${codes}`
          + (res.skipped_count > 8 ? ' …' : '')
      }
      setApplyMsg(msg)
      setSelLines(new Set())
      await reload(); await loadHistory()
      onRefresh && onRefresh()
    } catch (e) {
      setApplyMsg(e.response?.data?.error || 'تعذّر تطبيق التحديث')
    } finally { setApplying(false) }
  }

  if (loading) return <div className="px-6 py-6 text-sm text-gray-400">جارٍ فحص الفروقات…</div>
  if (error)   return <div className="px-6 py-6 text-sm text-red-600">{error}</div>
  if (!data)   return null

  const s = data.summary
  const hasDrift = s.changed_lines > 0

  const deltaCls = v => v > 0.005 ? 'text-green-600' : v < -0.005 ? 'text-red-600' : 'text-gray-400'

  const driftLines = data.lines || []
  const allLineIds = driftLines.map(l => l.line_id).filter(Boolean)
  const allSelected = allLineIds.length > 0 && allLineIds.every(id => selLines.has(id))
  const toggleLine = (id) => setSelLines(prev => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const toggleAll = () => setSelLines(prev =>
    allLineIds.every(id => prev.has(id)) ? new Set() : new Set(allLineIds))

  const columns = [
    { key: '_sel', sortable: false, width: 40, align: 'center',
      label: (
        <input type="checkbox" checked={allSelected} onChange={toggleAll}
          onClick={e => e.stopPropagation()} title="تحديد الكل" />
      ),
      render: (_v, r) => (
        <input type="checkbox" checked={selLines.has(r.line_id)}
          onChange={() => toggleLine(r.line_id)} disabled={!r.line_id} />
      ) },
    { key: 'docnumber', label: 'الفاتورة', type: 'text', width: 80,
      render: (v) => <span className="font-mono text-xs">#{v}</span> },
    { key: 'branchcode', label: 'الفرع', type: 'text', width: 55, align: 'center',
      render: (v) => <span className="font-mono text-xs text-gray-600">{v}</span> },
    { key: 'itemcode', label: 'الكود', type: 'text', width: 70,
      render: (v) => <span className="font-mono text-xs text-gray-500">{v}</span> },
    { key: 'item_name', label: 'الصنف', type: 'text', width: 180 },
    { key: 'quantity', label: 'كمية', type: 'number', width: 60, align: 'center' },
    { key: 'frozen_unit_price', label: 'سعر مجمّد', type: 'number', width: 95, align: 'left',
      render: v => fmt(v) },
    { key: 'current_unit_price', label: 'سعر حالي', type: 'number', width: 95, align: 'left',
      render: (v, r) => (
        <span className={Math.abs((r.price_delta)||0) > 0.001 ? 'font-bold text-amber-700' : ''}>{fmt(v)}</span>
      ) },
    { key: 'frozen_category_label',  label: 'تصنيف مجمّد', type: 'text', width: 95 },
    { key: 'current_category_label', label: 'تصنيف حالي', type: 'text', width: 95,
      render: (v, r) => (
        <span className={r.frozen_category !== r.current_category
          ? 'font-bold text-amber-700' : ''}>{v}</span>
      ) },
    { key: 'frozen_net',  label: 'صافى مجمّد', type: 'number', width: 100, align: 'left',
      render: v => fmt(v) },
    { key: 'current_net', label: 'صافى حالي', type: 'number', width: 100, align: 'left',
      render: v => fmt(v) },
    { key: 'net_delta', label: 'الفرق', type: 'number', width: 100, align: 'left',
      cellClass: 'font-bold',
      render: v => <span className={deltaCls(v)}>{v > 0 ? '+' : ''}{fmt(v)}</span> },
  ]

  return (
    <div className="px-6 py-4">
      {/* Item-classification corrections (تصويبات) — apply active overrides */}
      {ovPreview && ovPreview.affected_lines > 0 && (
        <div className="mb-4 rounded-lg border border-indigo-200 bg-indigo-50/60 p-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-sm text-indigo-900">
              🏷 <b>تصويبات تصنيف الأصناف:</b> {ovPreview.affected_lines} بند في {ovPreview.affected_rx} روشتة
              سيُعاد تصنيفها · الأثر على الصافى{' '}
              <span className={ovPreview.net_delta < 0 ? 'text-red-600 font-bold' : 'text-green-600 font-bold'}>
                {ovPreview.net_delta > 0 ? '+' : ''}{fmt(ovPreview.net_delta)}
              </span>{' '}
              ({fmt(ovPreview.net_before)} → {fmt(ovPreview.net_projected)})
            </div>
            <button onClick={applyOverrides} disabled={ovApplying}
              className="px-3 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50">
              {ovApplying ? 'جارٍ التطبيق…' : 'تطبيق التصويبات'}
            </button>
          </div>
          {ovMsg && <div className="mt-2 text-xs text-indigo-800">{ovMsg}</div>}
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-indigo-700">
                <tr>
                  {['الفاتورة', 'الصنف', 'من', 'إلى', 'الإجمالى', 'فرق الصافى'].map((h, i) => (
                    <th key={i} className="text-right px-2 py-1 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ovPreview.lines.slice(0, 50).map((l, i) => (
                  <tr key={i} className="border-t border-indigo-100">
                    <td className="px-2 py-1 font-mono">#{l.docnumber}</td>
                    <td className="px-2 py-1">{l.item_name || l.item_code}</td>
                    <td className="px-2 py-1 text-amber-700">{l.from_label}</td>
                    <td className="px-2 py-1 text-green-700 font-medium">{l.to_label}</td>
                    <td className="px-2 py-1 text-left">{fmt(l.line_total)}</td>
                    <td className="px-2 py-1 text-left text-red-600">{l.net_delta > 0 ? '+' : ''}{fmt(l.net_delta)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {ovPreview && ovPreview.affected_lines === 0 && ovMsg && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-2 text-xs text-green-800">{ovMsg}</div>
      )}

      {/* Dual-origin items — decide classification PER MOTALBA */}
      {reviewItems.length > 0 && (
        <div className="mb-4 rounded-lg border border-purple-200 bg-purple-50/50 p-3">
          <div className="text-sm text-purple-900 mb-2">
            🔀 <b>أصناف مزدوجة المنشأ — قرار يدوي لهذه المطالبة:</b>{' '}
            هذه الأصناف قد تكون محلى أو مستورد حسب المنشأ المصروف. حدّد التصنيف الصحيح لكل صنف في هذه المطالبة.
          </div>
          {reviewMsg && <div className="mb-2 text-xs text-purple-800">{reviewMsg}</div>}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-purple-700">
                <tr>
                  {['كود', 'الصنف', 'عدد البنود', 'الإجمالى', 'التصنيف الحالى', 'التصنيف لهذه المطالبة', ''].map((h, i) => (
                    <th key={i} className="text-right px-2 py-1 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reviewItems.map(it => {
                  const sel = reviewSel[it.item_code]
                    || (it.current_categories.length === 1 ? it.current_categories[0].category : it.suggested) || 'local'
                  return (
                    <tr key={it.item_code} className="border-t border-purple-100">
                      <td className="px-2 py-1 font-mono">{it.item_code}</td>
                      <td className="px-2 py-1">{it.item_name}</td>
                      <td className="px-2 py-1 text-center">{it.line_count}</td>
                      <td className="px-2 py-1 text-left">{fmt(it.total_value)}</td>
                      <td className="px-2 py-1">
                        {it.current_categories.map(c => (
                          <span key={c.category} className={`inline-block rounded px-1.5 py-0.5 ml-1 ${
                            c.category === 'imported' ? 'bg-amber-100 text-amber-700'
                            : c.category === 'tarsia' ? 'bg-purple-100 text-purple-700'
                            : 'bg-green-100 text-green-700'}`}>
                            {c.label}{it.is_mixed ? ` ×${c.count}` : ''}
                          </span>
                        ))}
                      </td>
                      <td className="px-2 py-1">
                        <select value={sel}
                          onChange={e => setReviewSel(s => ({ ...s, [it.item_code]: e.target.value }))}
                          className="border border-gray-300 rounded px-2 py-1 text-xs">
                          <option value="local">محلى</option>
                          <option value="imported">مستورد</option>
                          <option value="tarsia">ترسية</option>
                        </select>
                      </td>
                      <td className="px-2 py-1">
                        <button onClick={() => applyReview(it.item_code, sel)} disabled={reviewBusy === it.item_code}
                          className="px-2.5 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50">
                          {reviewBusy === it.item_code ? '…' : 'تطبيق'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Action bar */}
      <div className="flex items-center gap-3 flex-wrap mb-4">
        <button onClick={exportExcel} disabled={exporting}
          className="px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200 disabled:opacity-50">
          {exporting ? 'جارٍ التصدير…' : 'تصدير Excel'}
        </button>
        <div className="h-6 w-px bg-gray-200" />
        <span className="text-xs text-gray-500">طبّق:</span>
        <label className="text-sm text-gray-600 flex items-center gap-1">
          <input type="checkbox" checked={applyCategory} onChange={e => setApplyCategory(e.target.checked)} />
          التصنيف
        </label>
        <label className="text-sm text-gray-600 flex items-center gap-1">
          <input type="checkbox" checked={applyPrice} onChange={e => setApplyPrice(e.target.checked)} />
          الأسعار
        </label>
        <div className="h-6 w-px bg-gray-200" />
        <span className={`text-xs ${selLines.size ? 'text-blue-700 font-medium' : 'text-gray-400'}`}>
          {selLines.size ? `${selLines.size} بند محدد` : 'لم يُحدَّد بند (سيُطبَّق على الكل)'}
        </span>
        {selLines.size > 0 && (
          <button onClick={() => setSelLines(new Set())}
            className="text-xs text-gray-500 underline hover:text-gray-700">مسح التحديد</button>
        )}
        <button onClick={applyMaster} disabled={applying || !hasDrift || (!applyPrice && !applyCategory)}
          className="px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
          {applying ? 'جارٍ التطبيق…'
            : selLines.size ? `تطبيق على المحدد (${selLines.size})`
            : 'تطبيق بيانات الكتالوج على الكل'}
        </button>
        {applyMsg && <span className="text-xs text-gray-600">{applyMsg}</span>}
      </div>
      <p className="text-[11px] text-gray-400 -mt-2 mb-4">
        حدِّد خانتَي «التصنيف»/«الأسعار» لتطبيق أحدهما أو كليهما، وحدِّد صفوفاً بعينها من الجدول لتطبيق التصويب على جزء من البنود فقط.
      </p>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        {[
          { label: 'بنود متغيّرة', value: s.changed_lines, sub: `من ${s.total_lines} بند`,
            cls: hasDrift ? 'text-amber-700' : 'text-green-600' },
          { label: 'تغيّر تصنيف', value: s.category_changes, cls: s.category_changes ? 'text-amber-700' : 'text-gray-400' },
          { label: 'تغيّر سعر', value: s.price_changes, cls: s.price_changes ? 'text-amber-700' : 'text-gray-400' },
          { label: 'فرق الخصم', value: fmt(s.discount_delta), cls: deltaCls(s.discount_delta) },
          { label: 'فرق الصافى الكلي', value: `${s.net_delta > 0 ? '+' : ''}${fmt(s.net_delta)}`,
            cls: deltaCls(s.net_delta), big: true },
        ].map(c => (
          <div key={c.label} className="bg-white border border-gray-200 rounded-xl p-3">
            <p className="text-xs text-gray-500">{c.label}</p>
            <p className={`font-mono mt-1 ${c.big ? 'text-lg font-bold' : 'font-semibold'} ${c.cls || 'text-gray-800'}`}>
              {c.value}
            </p>
            {c.sub && <p className="text-[11px] text-gray-400 mt-0.5">{c.sub}</p>}
          </div>
        ))}
      </div>

      {s.items_not_found > 0 && (
        <div className="mb-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          ⚠️ {s.items_not_found} صنف غير موجود في الكتالوج الحالي — تم الإبقاء على قيمته المجمّدة.
        </div>
      )}

      {/* SOFTECH gross reconciliation — prescriptions whose gross disagrees with SOFTECH */}
      {data.softech_reconciliation?.can_check && (
        <div className="mb-4">
          {data.softech_reconciliation.mismatch_count === 0 ? (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 text-sm text-green-700">
              ✓ صافى كل الروشتات مطابق لسوفتك.
            </div>
          ) : (
            <div className="bg-amber-50 border border-amber-300 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <p className="font-bold text-amber-800 text-sm">
                  ⚑ روشتات صافيها يختلف عن سوفتك (سلوك Power Query)
                </p>
                <span className="text-xs font-mono text-amber-700">
                  صافينا {fmt(data.softech_reconciliation.our_gross)} مقابل سوفتك {fmt(data.softech_reconciliation.softech_gross)}
                  <span className="font-bold"> ({data.softech_reconciliation.gross_delta > 0 ? '+' : ''}{fmt(data.softech_reconciliation.gross_delta)})</span>
                </span>
              </div>
              <p className="text-xs text-amber-700 mb-3">
                نطبّق معادلة Power Query (محلى×0.83 + مستورد×0.94) وليس صافى سوفتك، لذا الاختلاف متوقع في {data.softech_reconciliation.mismatch_count} روشتة.
                راجع الروشتات التالية وقرّر: احتفظ بقيمة Power Query (تجاوز) أو صحّح التصنيف يدوياً (تبويب البنود / تعديل الروشتة).
              </p>
              <div className="overflow-x-auto rounded-lg border border-amber-200 bg-white">
                <table className="w-full text-xs">
                  <thead className="bg-amber-100/60 text-amber-900">
                    <tr>
                      <th className="text-right px-3 py-2">الفاتورة</th>
                      <th className="text-right px-3 py-2">المريض</th>
                      <th className="text-right px-3 py-2">التاريخ</th>
                      <th className="text-left px-3 py-2">صافينا</th>
                      <th className="text-left px-3 py-2">صافى سوفتك</th>
                      <th className="text-left px-3 py-2">الفرق</th>
                      <th className="text-right px-3 py-2">ملاحظة</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-amber-100">
                    {data.softech_reconciliation.prescriptions.map((r) => (
                      <tr key={r.prescription_id} className="hover:bg-amber-50/50">
                        <td className="px-3 py-2 font-mono">#{r.docnumber}</td>
                        <td className="px-3 py-2">{r.patient_name || '—'}</td>
                        <td className="px-3 py-2 text-gray-500">{r.docdate || '—'}</td>
                        <td className="px-3 py-2 text-left font-mono">{fmt(r.our_gross)}</td>
                        <td className="px-3 py-2 text-left font-mono">{fmt(r.softech_gross)}</td>
                        <td className="px-3 py-2 text-left font-mono font-bold text-amber-700">
                          {r.diff > 0 ? '+' : ''}{fmt(r.diff)}
                        </td>
                        <td className="px-3 py-2 text-gray-600">{r.hint}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {!hasDrift ? (
        <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-6 text-center text-green-700 text-sm">
          ✓ لا توجد فروقات — تصنيف جميع الأصناف مطابق لبيانات الكتالوج الحالية.
        </div>
      ) : (
        <>
          {/* Category moves summary */}
          {data.category_moves.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-3 mb-4">
              <p className="text-sm font-semibold text-gray-700 mb-2">حركات التصنيف</p>
              <div className="flex flex-wrap gap-2">
                {data.category_moves.map((m, i) => (
                  <div key={i} className="text-xs bg-gray-50 border border-gray-200 rounded-lg px-3 py-1.5">
                    <span className="font-medium">{m.from_label}</span>
                    <span className="text-gray-400 mx-1">→</span>
                    <span className="font-bold text-amber-700">{m.to_label}</span>
                    <span className="text-gray-400 mx-2">·</span>
                    <span>{m.count} بند</span>
                    <span className="text-gray-400 mx-2">·</span>
                    <span className={deltaCls(m.net_delta)}>
                      {m.net_delta > 0 ? '+' : ''}{fmt(m.net_delta)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <DataTable
            columns={columns}
            rows={data.lines}
            rowKey={(r, i) => `${r.prescription_id}-${r.itemcode}-${i}`}
            emptyLabel="لا توجد فروقات"
            maxHeight="calc(100vh - 460px)"
          />
        </>
      )}

      {/* Apply history + undo */}
      {history.length > 0 && (
        <div className="mt-5">
          <p className="text-sm font-semibold text-gray-700 mb-2">سجل تطبيق بيانات الكتالوج</p>
          <div className="space-y-1.5">
            {history.map(run => (
              <div key={run.id}
                className={`flex items-center justify-between gap-3 px-3 py-2 rounded-lg border text-sm ${
                  run.reverted ? 'bg-gray-50 border-gray-200 opacity-70'
                               : 'bg-white border-gray-200'}`}>
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-xs text-gray-400 font-mono">
                    {toLatinDigits(new Date(run.applied_at).toLocaleString('ar-EG'))}
                  </span>
                  <span className="text-gray-700">
                    {run.lines_updated} بند · {run.prescriptions_updated} روشتة
                  </span>
                  <span className="text-xs text-gray-500">
                    {[run.apply_category && 'تصنيف', run.apply_price && 'سعر'].filter(Boolean).join(' + ')}
                  </span>
                  <span className={`text-[11px] rounded px-1.5 py-0.5 shrink-0 ${
                    run.scoped ? 'bg-blue-50 text-blue-700 border border-blue-200'
                               : 'bg-gray-100 text-gray-500'}`}
                    title={run.scoped ? `طُبِّق على ${run.scope_count} بند محدد من الجدول` : 'طُبِّق على كل البنود المتغيّرة'}>
                    {run.scoped ? `محدد · ${run.scope_count} بند` : 'الكل'}
                  </span>
                  <span className={`font-mono text-xs ${deltaCls(run.net_delta)}`}>
                    {run.net_delta > 0 ? '+' : ''}{fmt(run.net_delta)}
                  </span>
                  {run.applied_by && <span className="text-xs text-gray-400">— {run.applied_by}</span>}
                </div>
                {run.reverted ? (
                  <span className="text-xs text-gray-500 shrink-0">
                    تم التراجع{run.reverted_by ? ` — ${run.reverted_by}` : ''}
                  </span>
                ) : (
                  <button onClick={() => revertRun(run.id)}
                    className="px-3 py-1 bg-amber-100 text-amber-700 text-xs rounded hover:bg-amber-200 shrink-0">
                    تراجع
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════════
// PIVOT / CROSS-TAB ANALYSIS TAB
// Reuses the shared <DataTable> component and the /pivot backend endpoint.
// No charting lib needed — table-based summary + cross-tab.
// ═══════════════════════════════════════════════════════════════════════════════

// Multi-select dimension picker: chips (in order) + an "add" dropdown
function DimPicker({ label, selected, available, onChange, accent = 'blue' }) {
  const remaining = available.filter(d => !selected.includes(d.key))
  const labelOf = (k) => available.find(d => d.key === k)?.label || k
  const chip = accent === 'purple' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
  return (
    <div className="min-w-[220px]">
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <div className="flex flex-wrap items-center gap-1 border border-gray-300 rounded px-2 py-1.5 min-h-[38px]">
        {selected.map((k, i) => (
          <span key={k} className={`inline-flex items-center gap-1 text-xs rounded px-1.5 py-0.5 ${chip}`}>
            {i > 0 && <span className="text-gray-400">›</span>}
            {labelOf(k)}
            <button onClick={() => onChange(selected.filter(x => x !== k))}
              className="text-current/70 hover:text-red-600 font-bold">×</button>
          </span>
        ))}
        {remaining.length > 0 && (
          <select value="" onChange={e => e.target.value && onChange([...selected, e.target.value])}
            className="text-xs border-0 bg-transparent focus:outline-none text-gray-500 cursor-pointer">
            <option value="">{selected.length ? '+ إضافة' : '— اختر —'}</option>
            {remaining.map(d => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
        )}
      </div>
    </div>
  )
}

function PivotTab({ claimId }) {
  const [source,  setSource]  = useState('prescriptions')
  const [config,  setConfig]  = useState({ dimensions: [], measures: [] })
  const [rowDims, setRowDims] = useState(['relative'])   // multiple row groupings
  const [colDims, setColDims] = useState([])             // multiple column groupings
  const [measure, setMeasure] = useState('net')
  const [result,  setResult]  = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    insuranceApi.pivotConfig(source)
      .then(r => {
        setConfig(r.data)
        const dims = r.data.dimensions.map(d => d.key)
        const meas = r.data.measures.map(m => m.key)
        setRowDims(prev => { const f = prev.filter(k => dims.includes(k)); return f.length ? f : [dims[0]].filter(Boolean) })
        setColDims(prev => prev.filter(k => dims.includes(k)))
        if (!meas.includes(measure)) setMeasure(meas[0] || '')
      })
      .catch(() => setConfig({ dimensions: [], measures: [] }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source])

  const [exporting, setExporting] = useState(false)
  const [templates, setTemplates] = useState([])
  const loadTemplates = () => insuranceApi.pivotTemplates().then(r => setTemplates(r.data.results || r.data)).catch(() => {})
  useEffect(() => { loadTemplates() }, [])

  const applyTemplate = (t) => {
    if (!t) return
    setSource(t.source)
    setRowDims((t.row_dim || '').split(',').filter(Boolean))
    setColDims((t.col_dim || '').split(',').filter(Boolean))
    setMeasure(t.measure)
  }
  const saveTemplate = async () => {
    const name = window.prompt('اسم القالب؟')
    if (!name) return
    await insuranceApi.savePivotTemplate({ name, source, row_dim: rowDims.join(','), col_dim: colDims.join(','), measure })
    loadTemplates()
  }

  const run = useCallback(() => {
    if (!rowDims.length && !colDims.length) { setResult(null); return }
    setLoading(true); setError(null)
    insuranceApi.pivot({ source, rows: rowDims.join(','), cols: colDims.join(','), measure, claim_id: claimId })
      .then(r => setResult(r.data))
      .catch(e => setError(e.response?.data?.error || 'تعذّر تنفيذ التحليل'))
      .finally(() => setLoading(false))
  }, [source, rowDims, colDims, measure, claimId])

  useEffect(() => { run() }, [run])

  async function exportExcel() {
    setExporting(true)
    try {
      const { data } = await insuranceApi.pivotExport({
        source, rows: rowDims.join(','), cols: colDims.join(','), measure, claim_id: claimId,
      })
      const blob = new Blob([data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url  = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `تحليل_${claimId}.xlsx`
      document.body.appendChild(link); link.click(); document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch { setError('تعذّر تصدير الملف') } finally { setExporting(false) }
  }

  // Build DataTable columns + rows from the multi-dim result
  const { columns, tableRows } = (() => {
    if (!result) return { columns: [], tableRows: [] }
    const rd = result.row_dims || []
    const cols = rd.map((d, i) => ({
      key: `d${i}`, label: d.label, type: 'text', align: 'right', width: 180,
    }))
    const hasCols = (result.columns || []).length > 0
    if (hasCols) {
      result.columns.forEach(c => cols.push({
        key: c.key, label: c.labels.join(' / '), type: 'number', align: 'left', width: 130, render: v => fmt(v),
      }))
      cols.push({ key: '_total', label: 'الإجمالى', type: 'number', align: 'left', width: 140,
        cellClass: 'font-bold bg-gray-50', render: v => fmt(v) })
    } else {
      cols.push({ key: '_total', label: result.measure_label, type: 'number', align: 'left', width: 160, render: v => fmt(v) })
    }
    const tableRows = (result.rows || []).map(r => {
      const o = { _total: r._total }
      ;(r.dims || []).forEach((dv, i) => { o[`d${i}`] = dv })
      if (hasCols) Object.assign(o, r.values || {})
      return o
    })
    return { columns: cols, tableRows }
  })()

  const sel = 'border border-gray-300 rounded px-2 py-1.5 text-sm'

  return (
    <div className="px-6 py-4">
      <div className="flex flex-wrap gap-3 items-end mb-4 bg-white rounded-xl border border-gray-200 p-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">المصدر</label>
          <select className={sel} value={source} onChange={e => setSource(e.target.value)}>
            <option value="prescriptions">الروشتات</option>
            <option value="lines">بنود الأصناف</option>
          </select>
        </div>
        <DimPicker label="تجميع الصفوف (يمكن اختيار أكثر من بُعد)" selected={rowDims}
          available={config.dimensions} onChange={setRowDims} accent="blue" />
        <DimPicker label="تجميع الأعمدة (اختياري، متعدد)" selected={colDims}
          available={config.dimensions.filter(d => !rowDims.includes(d.key))} onChange={setColDims} accent="purple" />
        <div>
          <label className="block text-xs text-gray-500 mb-1">المقياس</label>
          <select className={sel} value={measure} onChange={e => setMeasure(e.target.value)}>
            {config.measures.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">قالب محفوظ</label>
          <div className="flex items-center gap-1">
            <select className={sel} value=""
              onChange={e => { const t = templates.find(x => String(x.id) === e.target.value); if (t) applyTemplate(t) }}>
              <option value="">— اختر —</option>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <button onClick={saveTemplate} title="حفظ الإعداد الحالي كقالب"
              className="px-2 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">💾</button>
          </div>
        </div>
        {result && (
          <div className="mr-auto flex items-center gap-4">
            <div className="text-left">
              <p className="text-xs text-gray-500">الإجمالى الكلي</p>
              <p className="font-mono font-bold text-lg text-gray-900">{fmt(result.grand_total)}</p>
            </div>
            <button onClick={exportExcel} disabled={exporting || !result.rows?.length}
              className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50">
              {exporting ? 'جارٍ التصدير…' : 'تصدير Excel'}
            </button>
          </div>
        )}
      </div>

      {error && <div className="text-sm text-red-600 mb-3">{error}</div>}
      {loading && <div className="text-sm text-gray-400 mb-3">جارٍ التحليل…</div>}

      {result && (
        <>
          <DataTable
            columns={columns}
            rows={tableRows}
            rowKey={(r, i) => `${r.d0 || ''}-${i}`}
            emptyLabel="لا توجد بيانات للتحليل"
            maxHeight="calc(100vh - 360px)"
            defaultSort={{ key: '_total', dir: 'desc' }}
          />
          {(result.columns?.length > 0) && (
            <div className="mt-2 bg-gray-50 border border-gray-200 rounded-lg px-4 py-2 text-xs text-gray-600 flex flex-wrap gap-4">
              <span className="font-semibold">إجماليات الأعمدة:</span>
              {result.columns.map(c => (
                <span key={c.key}>{c.labels.join(' / ')}: <span className="font-mono">{fmt(result.totals[c.key])}</span></span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
