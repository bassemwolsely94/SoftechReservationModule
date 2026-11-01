import { useState, useEffect, useCallback, useRef } from 'react'
import { invoicesApi, branchesApi } from '../api/client'
import BranchSelect from '../components/BranchSelect'
import useGridKeyboard from '../hooks/useGridKeyboard'
import SoftechGrid from './invoices/SoftechGrid'
import BundleWorkbench from './invoices/BundleWorkbench'
import ItemSearchInput from '../components/ItemSearchInput'

// ── Download helper ────────────────────────────────────────────────────────────
function triggerDownload(data, filename, mime) {
  const blob = data instanceof ArrayBuffer ? new Blob([data], { type: mime }) : data
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── constants ─────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  pending:    { label: 'في الانتظار',    color: 'bg-gray-100 text-gray-500',    dot: '⏳' },
  processing: { label: 'جاري المعالجة', color: 'bg-blue-100 text-blue-600',    dot: '🔄' },
  review:     { label: 'قيد المراجعة',  color: 'bg-amber-100 text-amber-700',  dot: '👁' },
  confirmed:  { label: 'مُأكَّدة',      color: 'bg-green-100 text-green-700',  dot: '✅' },
  rejected:   { label: 'مرفوضة',        color: 'bg-red-100 text-red-600',      dot: '❌' },
  queued:     { label: 'بانتظار الترحيل', color: 'bg-sky-100 text-sky-700',    dot: '🕓' },
  pushing:    { label: 'جارٍ الترحيل',   color: 'bg-indigo-100 text-indigo-600', dot: '🔄' },
  finalized:  { label: 'مُرحّلة إلى ERP', color: 'bg-indigo-100 text-indigo-700', dot: '⇪' },
  push_failed:{ label: 'فشل الترحيل',    color: 'bg-red-100 text-red-600',      dot: '⚠' },
}

function scoreColor(s) {
  if (!s) return 'text-gray-300'
  if (s >= 0.8) return 'text-green-600'
  if (s >= 0.5) return 'text-amber-500'
  return 'text-red-400'
}

// ── InvoiceLineRow ────────────────────────────────────────────────────────────

// Learn the vendor-code mapping. If SofTech reports a CHANGE to an existing
// mapping (code moving between items, or an item's code changing), it comes back
// as needs_approval — the user must approve the warning before we override, and
// is then notified of the discrepancy they signed off.
async function learnWithApproval(invoiceId, lineId, onNotify) {
  try {
    const r = await invoicesApi.learnMapping(invoiceId, lineId)
    const link = r?.data?.softech_link
    if (link?.action !== 'needs_approval') return
    const parts = (link.discrepancies || []).map(d =>
      d.type === 'code_changed'
        ? `• سيتغيّر كود المورد لهذا الصنف من "${d.from}" إلى "${d.to}"`
        : `• كود المورد "${d.code}" مرتبط حالياً بصنف آخر (${(d.from_itemcodes || []).join(', ')}) وسيُنقل إلى هذا الصنف`
    ).join('\n')
    const ok = window.confirm(
      `⚠ تم رصد تعارض في ربط كود المورد:\n\n${parts}\n\nهل تعتمد هذا التعديل؟`)
    if (!ok) { onNotify?.('لم يُعتمد تعديل كود المورد', 'error'); return }
    const r2 = await invoicesApi.learnMapping(invoiceId, lineId, { approve_link_change: true })
    if (r2?.data?.softech_link?.committed) {
      onNotify?.('✔ تم اعتماد تعديل كود المورد وتحديثه في SofTech', 'success')
    }
  } catch { /* learning is best-effort; never blocks the confirm */ }
}

function InvoiceLineRow({ line, invoiceId, onUpdated, onDelete, editable, onNotify, kb, openReq }) {
  const [editing,     setEditing]     = useState(false)
  const [draft,       setDraft]       = useState({ ...line })
  const [showMatches, setShowMatches] = useState(false)
  const [matches,     setMatches]     = useState([])
  const [loadingM,    setLoadingM]    = useState(false)
  const [saving,      setSaving]      = useState(false)

  const fetchMatches = async () => {
    // Always re-fetch on open (don't cache): after the name is edited, the
    // auto-suggestions must reflect the NEW name, not a stale list.
    if (showMatches) { setShowMatches(false); return }
    setLoadingM(true)
    try {
      const r = await invoicesApi.lineMatches(invoiceId, line.id)
      setMatches(r.data)
      setShowMatches(true)
    } finally {
      setLoadingM(false)
    }
  }

  // Free-text / item-code search pick (ItemSearchInput → updateLine).
  const pickItem = async (item) => {
    await invoicesApi.updateLine(invoiceId, line.id, { item: item.item_id, is_confirmed: true })
    learnWithApproval(invoiceId, line.id, onNotify)
    setShowMatches(false)
    onUpdated()
  }

  const save = async () => {
    setSaving(true)
    try {
      await invoicesApi.updateLine(invoiceId, line.id, {
        manual_name:  draft.manual_name,
        item:         draft.item,
        quantity:     draft.quantity,
        unit_price:   draft.unit_price,
        discount_pct: draft.discount_pct,
        discount_amt: draft.discount_amt,
        is_confirmed: true,
      })
      // Learn the mapping for future invoices (prompts for approval on a change)
      if (draft.item) {
        learnWithApproval(invoiceId, line.id, onNotify)
      }
      setEditing(false)
      setShowMatches(false)
      onUpdated()
    } finally {
      setSaving(false)
    }
  }

  const selectMatch = async (m) => {
    await invoicesApi.updateLine(invoiceId, line.id, { item: m.item_id, is_confirmed: true })
    // Learn mapping (prompts for approval if this changes an existing code link)
    learnWithApproval(invoiceId, line.id, onNotify)
    setShowMatches(false)
    onUpdated()
  }

  // M (keyboard) toggles this line's match suggestions
  useEffect(() => { if (openReq?.id === line.id) fetchMatches() }, [openReq])   // eslint-disable-line react-hooks/exhaustive-deps

  const total = Number(line.line_total || 0).toFixed(3)

  const needsReview = line.match_review && !line.is_confirmed
  return (
    <div ref={kb?.ref} onMouseDown={kb?.onMouseDown} data-kb-active={kb?.['data-kb-active']}
      className={`border rounded-xl mb-2 overflow-hidden ${kb?.className || ''}
      ${line.is_confirmed ? 'border-green-200 bg-green-50/20' :
        needsReview ? 'border-orange-300 bg-orange-50/40' :
        line.item ? 'border-blue-200 bg-blue-50/10' :
        'border-amber-200 bg-amber-50/10'}`}>

      <div className="flex items-start gap-3 p-3">
        {/* Confirm dot */}
        <div className="mt-0.5 shrink-0">
          {line.is_confirmed
            ? <span className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center text-white text-[10px]">✓</span>
            : needsReview
            ? <span className="w-5 h-5 rounded-full bg-orange-500 flex items-center justify-center text-white text-[10px]" title="مطابقة غير مؤكدة">⚠</span>
            : line.item
            ? <span className="w-5 h-5 rounded-full bg-blue-400 flex items-center justify-center text-white text-[10px]">~</span>
            : <span className="w-5 h-5 rounded-full bg-amber-400 flex items-center justify-center text-white text-[10px]">?</span>}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="grid grid-cols-2 gap-2 mb-2">
              <div className="col-span-2">
                <label className="text-[10px] text-gray-500">الاسم</label>
                <input value={draft.manual_name}
                  onChange={e => setDraft(d => ({ ...d, manual_name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">الكمية</label>
                <input type="number" value={draft.quantity}
                  onChange={e => setDraft(d => ({ ...d, quantity: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">سعر الوحدة</label>
                <input type="number" value={draft.unit_price}
                  onChange={e => setDraft(d => ({ ...d, unit_price: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">خصم %</label>
                <input type="number" step="0.5" value={draft.discount_pct}
                  onChange={e => setDraft(d => ({ ...d, discount_pct: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">خصم مبلغ</label>
                <input type="number" value={draft.discount_amt}
                  onChange={e => setDraft(d => ({ ...d, discount_amt: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
            </div>
          ) : (
            <div>
              <span className="font-medium text-gray-800 text-sm">
                {line.manual_name || line.raw_text}
              </span>
              {line.item_name && (
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span className="text-[11px] text-gray-400">→</span>
                  <span className="text-xs text-gray-700 font-medium">{line.item_name}</span>
                  {line.item_softech_id && (
                    <span className="text-[10px] font-mono text-gray-400 bg-gray-100 px-1 rounded">{line.item_softech_id}</span>
                  )}
                  {line.item_sale_price > 0 && (
                    <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                      {Number(line.item_sale_price).toFixed(2)} ج.م
                    </span>
                  )}
                  {line.match_score && (
                    <span className={`text-[10px] font-medium ${scoreColor(line.match_score)}`}>
                      {Math.round(line.match_score * 100)}%
                    </span>
                  )}
                  {needsReview && (
                    <span className="text-[10px] font-medium bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded"
                      title="الاسم العربي والاسم العلمي أشارا لصنفين مختلفين — تحقق من المطابقة">
                      ⚠ راجع المطابقة
                    </span>
                  )}
                </div>
              )}
              <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                <span>الكمية: <strong>{line.quantity}</strong></span>
                <span>السعر: <strong>{Number(line.unit_price).toFixed(3)}</strong></span>
                {Number(line.discount_pct) > 0 && <span>خصم: <strong>{line.discount_pct}%</strong></span>}
                <span className="font-bold text-gray-700">الإجمالي: {total}</span>
                {line.ocr_confidence != null && (
                  <span
                    title="ثقة استخراج OCR — راجع الأسطر منخفضة الثقة"
                    className={`text-[10px] px-1 rounded ${
                      line.ocr_confidence < 0.6  ? 'bg-red-100 text-red-700'
                      : line.ocr_confidence < 0.85 ? 'bg-amber-100 text-amber-700'
                      : 'text-gray-400'}`}>
                    OCR {Math.round(line.ocr_confidence * 100)}%
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Row actions */}
        {editable && (
          <div className="flex items-center gap-1 shrink-0">
            {editing ? (
              <>
                <button onClick={save} disabled={saving}
                  className="px-2.5 py-1 bg-brand-600 text-white rounded-lg text-xs font-medium">
                  {saving ? '...' : 'حفظ'}
                </button>
                <button onClick={() => { setDraft({ ...line }); setEditing(false) }}
                  className="px-2 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs">إلغاء</button>
              </>
            ) : (
              <>
                <button onClick={() => setEditing(true)}
                  className="text-xs text-gray-400 hover:text-gray-600 px-1.5 py-1 rounded hover:bg-gray-100">✏️</button>
                <button onClick={fetchMatches} disabled={loadingM}
                  className="text-xs text-blue-500 hover:text-blue-700 px-2 py-1 rounded hover:bg-blue-50">
                  {loadingM ? '...' : '🔍'}
                </button>
                <button onClick={() => onDelete(line.id)}
                  className="text-xs text-red-400 hover:text-red-600 px-1.5 py-1 rounded hover:bg-red-50">🗑</button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Match picker */}
      {showMatches && (
        <div className="border-t border-gray-100 bg-white p-3">
          {/* Free-text / item-code search — type a name or a SofTech code to re-match. */}
          <div className="mb-3">
            <div className="text-xs font-semibold text-gray-500 mb-1">ابحث بالاسم أو كود الصنف:</div>
            <ItemSearchInput onSelect={pickItem} placeholder="ابحث بالاسم أو الكود… (مثال: strepsils أو 34192)" />
          </div>
          <div className="text-xs font-semibold text-gray-500 mb-2">اقتراحات تلقائية:</div>
          {matches.length === 0 ? (
            <div className="text-xs text-gray-400">لا توجد اقتراحات — استخدم البحث بالأعلى</div>
          ) : (
            <div className="space-y-1">
              {matches.map(m => (
                <button key={m.item_id} onClick={() => selectMatch(m)}
                  className="w-full text-right flex items-center justify-between px-3 py-2 rounded-lg hover:bg-brand-50 border border-transparent hover:border-brand-200 transition-colors">
                  <div>
                    <span className="text-sm font-medium text-gray-800">{m.item_name}</span>
                    {m.item_scientific && <span className="text-xs text-gray-400 mr-1">({m.item_scientific})</span>}
                    <span className="text-[11px] font-mono text-gray-400 mr-1">[{m.item_softech_id}]</span>
                    {m.item_sale_price > 0 && (
                      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1 rounded mr-1">
                        {Number(m.item_sale_price).toFixed(2)} ج.م
                      </span>
                    )}
                  </div>
                  <span className={`text-xs font-bold ${scoreColor(m.score)}`}>
                    {Math.round(m.score * 100)}%
                  </span>
                </button>
              ))}
            </div>
          )}
          <button onClick={() => setShowMatches(false)} className="mt-2 text-xs text-gray-400 hover:text-gray-600">
            إغلاق
          </button>
        </div>
      )}
    </div>
  )
}

// ── Invoice Detail ────────────────────────────────────────────────────────────

// Raw OCR is JSON for structured reads — pretty-print it; plain text stays as is.
function prettyOcr(raw) {
  const t = (raw || '').trim()
  if (!t.startsWith('{')) return raw
  try { return JSON.stringify(JSON.parse(t), null, 2) } catch { return raw }
}

// SOFTECH supplier link: shows the linked personcode, or a picker when the
// auto-resolver missed it (validation E7 supplier_unlinked blocks the push).
function VendorLink({ inv, editable, onLinked, onNotify }) {
  const [open,    setOpen]    = useState(false)
  const [options, setOptions] = useState(null)
  const [choice,  setChoice]  = useState('')
  const [saving,  setSaving]  = useState(false)
  const linked = !!inv.vendor_personcode
  const locked = ['pushing', 'finalized'].includes(inv.status)

  const start = async () => {
    setOpen(true)
    if (options) return
    try {
      const { data } = await invoicesApi.linkableVendors()
      setOptions(data || [])
    } catch {
      setOptions([])
      onNotify('تعذّر تحميل قائمة الموردين', 'error')
    }
  }

  const save = async () => {
    const opt = (options || []).find(o => `${o.vendor_id ?? ''}|${o.personcode}` === choice)
    if (!opt) return
    setSaving(true)
    try {
      await invoicesApi.linkVendor(inv.id, opt.vendor_id
        ? { vendor: opt.vendor_id }
        : { personcode: opt.personcode, name: opt.name })
      onNotify(`تم ربط المورد ${opt.name} (${opt.personcode})`)
      setOpen(false)
      onLinked()
    } catch (e) {
      onNotify(e?.response?.data?.detail || 'تعذّر ربط المورد', 'error')
    } finally {
      setSaving(false)
    }
  }

  if (open) {
    return (
      <div className="flex items-center gap-1.5">
        <select value={choice} onChange={e => setChoice(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1 text-xs max-w-[16rem] focus:outline-none focus:ring-2 focus:ring-brand-400">
          <option value="">{options ? '— اختر مورد SOFTECH —' : 'جاري التحميل…'}</option>
          {(options || []).map(o => (
            <option key={`${o.vendor_id ?? ''}|${o.personcode}`} value={`${o.vendor_id ?? ''}|${o.personcode}`}>
              {o.name} ({o.personcode}){o.is_main ? ' ★' : ''}
            </option>
          ))}
        </select>
        <button onClick={save} disabled={!choice || saving}
          className="px-2 py-1 bg-brand-600 text-white rounded-lg text-xs disabled:opacity-50">ربط</button>
        <button onClick={() => setOpen(false)}
          className="px-2 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs">إلغاء</button>
      </div>
    )
  }

  return linked ? (
    <span className="text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-700 border border-green-200 flex items-center gap-1">
      SOFTECH: {inv.vendor_name} ({inv.vendor_personcode})
      {editable && !locked && (
        <button onClick={start} className="text-green-800 hover:underline mr-1">تغيير</button>
      )}
    </span>
  ) : (
    <span className="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200 flex items-center gap-1">
      غير مربوط بمورد SOFTECH
      {!locked && (
        <button onClick={start} className="font-medium hover:underline mr-1">ربط المورد</button>
      )}
    </span>
  )
}

function InvoiceDetail({ invoiceId, onBack, onOpen }) {
  const [inv,          setInv]          = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [headerEdit,   setHeaderEdit]   = useState(false)
  const [headerDraft,  setHeaderDraft]  = useState({})
  const [addLine,      setAddLine]      = useState(false)
  const [newLine,      setNewLine]      = useState({ manual_name: '', quantity: 1, unit_price: 0, discount_pct: 0 })
  const [rerunning,    setRerunning]    = useState(false)
  const [toast,        setToast]        = useState(null)
  const [anomalies,    setAnomalies]    = useState(null)   // null = not fetched yet
  const [showAnomalies,setShowAnomalies]= useState(false)
  const [recon,        setRecon]        = useState(null)   // 3-way reconciliation result
  const [poResult,     setPoResult]     = useState(null)   // PO match result / {linked:false}
  const [exporting,    setExporting]    = useState(null)   // 'excel' | 'csv' | null
  const [viewMode,     setViewMode]     = useState('cards') // 'cards' | 'grid'
  const pollRef = useRef(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await invoicesApi.get(invoiceId)
      setInv(r.data)
      setHeaderDraft({
        supplier_name: r.data.supplier_name,
        invoice_number: r.data.invoice_number,
        invoice_date: r.data.invoice_date || '',
        global_discount_pct: r.data.global_discount_pct,
        global_discount_amt: r.data.global_discount_amt,
        notes: r.data.notes,
      })
    } finally {
      setLoading(false)
    }
  }, [invoiceId])

  useEffect(() => { load() }, [load])

  // ── Auto-poll while OCR is processing ─────────────────────────────────────
  useEffect(() => {
    if (!inv) return
    if (inv.status === 'processing') {
      pollRef.current = setInterval(async () => {
        try {
          const r = await invoicesApi.get(invoiceId)
          if (r.data.status !== 'processing') {
            clearInterval(pollRef.current)
            setInv(r.data)
          }
        } catch { clearInterval(pollRef.current) }
      }, 3000)
    } else {
      clearInterval(pollRef.current)
    }
    return () => clearInterval(pollRef.current)
  }, [inv?.status, invoiceId])  // eslint-disable-line

  // ── Anomaly fetch ─────────────────────────────────────────────────────────
  const fetchAnomalies = async () => {
    try {
      const r = await invoicesApi.anomalies(invoiceId)
      setAnomalies(r.data.anomalies || [])
      setShowAnomalies(true)
    } catch { setAnomalies([]) }
  }

  // ── Export helpers ────────────────────────────────────────────────────────
  const handleExportExcel = async () => {
    setExporting('excel')
    try {
      const r = await invoicesApi.exportExcel(invoiceId)
      const supplier = (inv?.supplier_name || 'invoice').replace(/\s+/g, '_')
      triggerDownload(r.data, `invoice_${supplier}.xlsx`,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    } finally { setExporting(null) }
  }

  const handleExportCsv = async () => {
    setExporting('csv')
    try {
      const r = await invoicesApi.exportCsv(invoiceId)
      const supplier = (inv?.supplier_name || 'invoice').replace(/\s+/g, '_')
      triggerDownload(r.data, `invoice_${supplier}.csv`, 'text/csv')
    } finally { setExporting(null) }
  }

  const saveHeader = async () => {
    await invoicesApi.updateHeader(invoiceId, headerDraft)
    setHeaderEdit(false)
    load()
  }

  const handleAddLine = async () => {
    if (!newLine.manual_name.trim()) return
    await invoicesApi.addLine(invoiceId, newLine)
    setNewLine({ manual_name: '', quantity: 1, unit_price: 0, discount_pct: 0 })
    setAddLine(false)
    load()
  }

  // keyboard flow (shared review-grid keys): ↑↓ move · Enter confirm the suggested item and
  // go to the next line · M show the match suggestions. A quiet refresh keeps focus in the list.
  const quietReload = async () => { try { setInv((await invoicesApi.get(invoiceId)).data) } catch { /* next load */ } }
  const [openReq, setOpenReq] = useState(null)
  const kbEditable = ['pending', 'review'].includes(inv?.status)
  const kb = useGridKeyboard({
    rows: inv?.lines || [], getKey: l => l.id, enabled: kbEditable, advanceOnConfirm: true,
    onConfirm: async (l) => {
      if (!l.item || l.is_confirmed) return
      await invoicesApi.updateLine(invoiceId, l.id, { item: l.item, is_confirmed: true })
      learnWithApproval(invoiceId, l.id, showToast)
      quietReload()
    },
    onOpen: l => setOpenReq(r => ({ id: l.id, n: (r?.n || 0) + 1 })),
  })

  const handleDelete = async (lid) => {
    if (!confirm('حذف هذا السطر؟')) return
    await invoicesApi.deleteLine(invoiceId, lid)
    load()
  }

  const handleRerunOcr = async () => {
    setRerunning(true)
    try {
      await invoicesApi.runOcr(invoiceId)
      showToast('تم إعادة تشغيل OCR ✓')
      load()
    } finally {
      setRerunning(false)
    }
  }

  const handleConfirm = async () => {
    await invoicesApi.confirm(invoiceId)
    showToast('تم تأكيد الفاتورة ✓')
    load()
  }

  const [pushing, setPushing]               = useState(false)
  const [preview, setPreview]               = useState(null)   // dry-run plan (opens the modal)
  const [dupInfo, setDupInfo]               = useState(null)   // duplicate check {is_duplicate, ...}
  const [dupChecking, setDupChecking]       = useState(false)
  const [showDupPanel, setShowDupPanel]     = useState(false)
  const [previewVal, setPreviewVal]         = useState(null)   // {ok,errors,warnings} for the same invoice
  const [ackWarnings, setAckWarnings]       = useState(false)  // user accepted the warnings
  const [previewLoading, setPreviewLoading] = useState(false)

  const [confirmingGreen, setConfirmingGreen] = useState(false)
  const confirmGreen = async () => {
    setConfirmingGreen(true)
    try {
      const { data } = await invoicesApi.confirmGreen(invoiceId)
      showToast(data.detail || `تم تأكيد ${data.confirmed} سطراً`, data.still_review ? 'info' : 'success')
      load()
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر التأكيد الجماعي', 'error')
    } finally {
      setConfirmingGreen(false)
    }
  }

  // Standalone thorough duplicate check (also auto-runs inside openPreview before push).
  const runDupCheck = async () => {
    setDupChecking(true)
    setShowDupPanel(true)
    try {
      const { data } = await invoicesApi.duplicateCheck(invoiceId)
      setDupInfo(data)
      if (!data.is_duplicate && !data.likely_duplicate) showToast('✓ لا يوجد تكرار على SofTech')
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر فحص التكرار', 'error')
    } finally {
      setDupChecking(false)
    }
  }

  const openPreview = async () => {
    setPreviewLoading(true)
    try {
      // fetch what-will-be-written (plan) AND the SofTech-rule validation together
      const [p, v] = await Promise.all([
        invoicesApi.pushPreview(invoiceId),
        invoicesApi.validateErp(invoiceId).catch(() => ({ data: null })),
      ])
      if (p.data?.plan) {
        setPreview(p.data.plan)
        setDupInfo(p.data.duplicates || null)
        setPreviewVal(v?.data || null)
        setAckWarnings(false)
      } else {
        showToast('تعذّر بناء المعاينة', 'error')
      }
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر بناء المعاينة', 'error')
    } finally {
      setPreviewLoading(false)
    }
  }

  const [reopening, setReopening] = useState(false)
  const handleReopen = async () => {
    setReopening(true)
    try {
      const { data } = await invoicesApi.reopen(invoiceId)
      showToast(data.detail || 'رجعت الفاتورة للمراجعة', data.status === 'finalized' ? 'error' : 'success')
      setPreview(null); setPreviewVal(null)
      await load()
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر الرجوع للتعديل', 'error')
    } finally {
      setReopening(false)
    }
  }

  const handlePush = async (force = false) => {
    setPushing(true)
    try {
      const { data } = await invoicesApi.push(invoiceId, force)
      if (data?.blocked && data?.validation) {
        const v = data.validation
        if (v.errors?.length) {
          showToast('لا يمكن الترحيل — ' + v.errors.map(e => e.message).join('؛ '), 'error')
        } else if (v.warnings?.length) {
          const ok = window.confirm('⚠ تحذيرات:\n' + v.warnings.map(w => '• ' + w.message).join('\n')
                                    + '\n\nهل تريد الترحيل رغم التحذيرات؟')
          if (ok) { setPushing(false); return handlePush(true) }
        }
        load(); return
      }
      if (data?.wrote_to_softech)        showToast(`تم الترحيل ✓ رقم المستند ${data.docnumber}`)
      else if (data?.already_finalized)  showToast(`مُرحّلة مسبقاً — رقم المستند ${data.docnumber}`)
      else if (data?.mode === 'dry_run') showToast('وضع المعاينة — ترحيل ERP غير مُفعّل بعد (INVOICE_WRITER_ENABLED)', 'error')
      else                               showToast('لم يكتمل الترحيل — راجع حالة الفاتورة', 'error')
      setPreview(null)
      load()
    } catch (e) {
      if (e?.response?.status === 409 && e?.response?.data?.duplicate && !force) {
        const ok = window.confirm((e.response.data.detail || 'فاتورة مكرّرة') + '\n\nهل تريد الترحيل رغم ذلك؟')
        if (ok) { setPushing(false); return handlePush(true) }
      } else {
        showToast(e?.response?.data?.detail || 'فشل الترحيل', 'error')
      }
    } finally {
      setPushing(false)
    }
  }

  const [validating, setValidating] = useState(false)
  const handleValidate = async () => {
    setValidating(true)
    try {
      const { data } = await invoicesApi.validateErp(invoiceId)
      const ne = data.errors?.length || 0, nw = data.warnings?.length || 0, nn = data.notices?.length || 0
      if (ne === 0 && nw === 0 && nn === 0) showToast('✓ لا توجد مخالفات — جاهزة للترحيل')
      else {
        const parts = []
        if (ne) parts.push('أخطاء (تمنع الترحيل):\n' + data.errors.map(e => '• ' + e.message).join('\n'))
        if (nw) parts.push('تحذيرات:\n' + data.warnings.map(w => '• ' + w.message).join('\n'))
        if (nn) parts.push('تنبيهات (لا تمنع الترحيل):\n' + data.notices.map(w => '• ' + w.message).join('\n'))
        window.alert(parts.join('\n\n'))
        showToast(`${ne} خطأ / ${nw} تحذير`, ne ? 'error' : 'success')
      }
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر التحقق', 'error')
    } finally {
      setValidating(false)
    }
  }

  const [reconciling, setReconciling] = useState(false)
  const handleReconcile = async () => {
    setReconciling(true)
    try {
      const { data } = await invoicesApi.reconcile(invoiceId)
      if (!data?.present)      showToast(`المستند #${data?.docnumber} لم يعد موجوداً في SOFTECH — أعد الترحيل`, 'error')
      else if (data?.returned) showToast(`المستند #${data.docnumber} موجود وله مرتجع مورد (doccode 120)`)
      else                     showToast(`تم التحقق ✓ المستند #${data.docnumber} موجود (${data.lines} سطر)`)
      load()
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر التحقق', 'error')
    } finally {
      setReconciling(false)
    }
  }

  const [returning, setReturning] = useState(false)
  const handleCreateReturn = async () => {
    if (!window.confirm('إنشاء مسودة مرتجع مورد لهذه الفاتورة؟ (يمكنك تعديل الكميات قبل الترحيل)')) return
    setReturning(true)
    try {
      const { data } = await invoicesApi.createReturn(invoiceId)
      showToast('تم إنشاء مسودة المرتجع ✓')
      if (data?.id && onOpen) onOpen(data.id)
    } catch (e) {
      showToast(e?.response?.data?.detail || 'تعذّر إنشاء المرتجع', 'error')
    } finally {
      setReturning(false)
    }
  }

  if (loading && !inv) return <div className="flex items-center justify-center h-64 text-gray-400 animate-pulse">جاري التحميل...</div>
  if (!inv) return null

  const stCfg   = STATUS_CONFIG[inv.status] || {}
  const lines   = inv.lines || []
  const editable = ['pending', 'review'].includes(inv.status)
  const confirmed = lines.filter(l => l.is_confirmed).length
  const unmatched = lines.filter(l => !l.item).length

  return (
    <div className="flex flex-col h-full" dir="rtl">

      {toast && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-lg text-sm font-medium
          ${toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
          {toast.msg}
        </div>
      )}

      {/* ── Push-to-ERP preview (dry-run) modal ─────────────────────────────── */}
      {preview && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
             onClick={() => !pushing && setPreview(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[85vh] flex flex-col"
               dir="rtl" onClick={e => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between shrink-0">
              <h3 className="font-bold text-gray-900">
                معاينة الترحيل إلى ERP — {preview.doc_kind === 'return' ? 'مرتجع إلى مورد' : 'شراء من مورد'}
                <span className="text-xs font-mono text-gray-400 mr-2">doccode {preview.doccode}</span>
              </h3>
              <button onClick={() => setPreview(null)} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
            </div>

            <div className="p-6 overflow-auto space-y-4">
              {dupInfo && (dupInfo.is_duplicate || dupInfo.likely_duplicate) && (
                <div className={`rounded-xl px-4 py-3 text-sm ${dupInfo.is_duplicate ? 'bg-red-50 border border-red-300 text-red-800' : 'bg-amber-50 border border-amber-300 text-amber-800'}`}>
                  <div className="font-bold mb-1">{dupInfo.is_duplicate ? '⛔ فاتورة مكرّرة' : '⚠ تكرار محتمل — راجع'}</div>
                  {dupInfo.softech_match && (
                    <div>سبق حفظها في SOFTECH برقم مستند <b className="font-mono">{dupInfo.softech_match.docnumber}</b>
                      {dupInfo.softech_match.docdate ? ` بتاريخ ${String(dupInfo.softech_match.docdate).slice(0,10)}` : ''}
                      {dupInfo.softech_match.docvalue ? ` — الإجمالي ${Number(dupInfo.softech_match.docvalue).toFixed(2)}` : ''}.</div>
                  )}
                  {(dupInfo.pg_duplicates || []).length > 0 && (
                    <div>مُدخلة من قبل في هذا النظام: {dupInfo.pg_duplicates.map(d => `#${d.id} (${d.status})`).join('، ')}.</div>
                  )}
                  {(dupInfo.candidates || []).length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="text-xs font-semibold">مستندات SofTech مشابهة (بعدّة عوامل):</div>
                      {dupInfo.candidates.map(c => (
                        <div key={c.docnumber} className="text-xs bg-white/60 rounded px-2 py-1">
                          <b className="font-mono">#{c.docnumber}</b>
                          <span className={`ms-1.5 px-1 rounded ${c.score >= 0.75 ? 'bg-red-200 text-red-800' : 'bg-amber-200 text-amber-800'}`}>تطابق {Math.round(c.score * 100)}%</span>
                          {c.docvalue != null && <span className="ms-1.5">إجمالي {Number(c.docvalue).toFixed(2)}</span>}
                          {c.item_count ? <span className="ms-1.5">· {c.item_count} صنف</span> : null}
                          {c.save_date && <span className="ms-1.5 text-gray-500">· حُفظت {String(c.save_date).slice(0,10)}</span>}
                          <div className="text-[11px] text-gray-600">{(c.factors || []).join(' · ')}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {dupInfo.softech_error && <div className="text-[11px] text-gray-500 mt-1">تعذّر فحص SofTech بالكامل: {dupInfo.softech_error}</div>}
                  <div className="text-xs mt-1">راجع قبل الترحيل — الترحيل محمي ضد التكرار، وستحتاج «تأكيد» إضافياً للمتابعة.</div>
                </div>
              )}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  ['الفرع', preview.branchcode],
                  ['المورد', `${preview.supplier_name || '—'} (${preview.supplier_code})`],
                  ['رقم فاتورة المورد', preview.invoice_number || '—'],
                  ['الإجمالي', `${Number(preview.doc_value || 0).toFixed(2)} ج.م`],
                ].map(([label, value]) => (
                  <div key={label} className="bg-gray-50 rounded-lg px-3 py-2">
                    <div className="text-[10px] text-gray-500">{label}</div>
                    <div className="text-sm font-medium text-gray-800 truncate" title={String(value)}>{value}</div>
                  </div>
                ))}
              </div>

              <div className="overflow-auto border border-gray-200 rounded-lg">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr className="text-right">
                      <th className="px-2 py-1.5 font-medium">الصنف</th>
                      <th className="px-2 py-1.5 font-medium">الكمية</th>
                      <th className="px-2 py-1.5 font-medium">سعر الشراء</th>
                      <th className="px-2 py-1.5 font-medium">سعر الجمهور</th>
                      <th className="px-2 py-1.5 font-medium">خصم%</th>
                      <th className="px-2 py-1.5 font-medium">الإجمالي</th>
                      <th className="px-2 py-1.5 font-medium">الصلاحية</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(preview.lines || []).map((l, i) => (
                      <tr key={i} className="border-t border-gray-100">
                        <td className="px-2 py-1.5">
                          {l.item_name}
                          <span className="font-mono text-gray-400 mr-1">{l.itemcode}</span>
                        </td>
                        <td className="px-2 py-1.5 font-medium">{l.transqty}</td>
                        <td className="px-2 py-1.5">{Number(l.transprice || 0).toFixed(2)}</td>
                        <td className="px-2 py-1.5">{Number(l.itemsaleprice || 0).toFixed(2)}</td>
                        <td className="px-2 py-1.5">{Number(l.pharmacydiscp || 0)}%</td>
                        <td className="px-2 py-1.5 font-medium">{Number(l.transprice_total || 0).toFixed(2)}</td>
                        <td className="px-2 py-1.5 text-gray-500">{l.itemexpirydate || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <ul className="text-[11px] text-gray-500 list-disc pr-4 space-y-0.5">
                {(preview.notes || []).map((n, i) => <li key={i}>{n}</li>)}
              </ul>

              {/* SofTech-rule validation (credit limit, item allowed, price caps, expiry…) */}
              {previewVal && ((previewVal.errors?.length || previewVal.warnings?.length || previewVal.notices?.length) ? (
                <div className="space-y-2">
                  {previewVal.errors?.length > 0 && (
                    <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                      <div className="text-xs font-bold text-red-700 mb-1">⛔ أخطاء تمنع الترحيل ({previewVal.errors.length})</div>
                      <ul className="text-[11px] text-red-700 list-disc pr-4 space-y-0.5">
                        {previewVal.errors.map((e, i) => <li key={i}>{e.message}</li>)}
                      </ul>
                    </div>
                  )}
                  {previewVal.warnings?.length > 0 && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                      <div className="text-xs font-bold text-amber-700 mb-1">⚠ تحذيرات ({previewVal.warnings.length})</div>
                      <ul className="text-[11px] text-amber-700 list-disc pr-4 space-y-0.5">
                        {previewVal.warnings.map((w, i) => <li key={i}>{w.message}</li>)}
                      </ul>
                      <label className="mt-2 flex items-center gap-2 text-[11px] text-amber-800 cursor-pointer">
                        <input type="checkbox" checked={ackWarnings} onChange={e => setAckWarnings(e.target.checked)} />
                        راجعت التحذيرات وأريد المتابعة
                      </label>
                    </div>
                  )}
                  {/* notices: shown loudly, never block posting (owner decision 2026-10-31) */}
                  {previewVal.notices?.length > 0 && (
                    <div className="rounded-lg border border-rose-300 bg-rose-50 p-3">
                      <div className="text-xs font-bold text-rose-700 mb-1">🔔 تنبيهات — لا تمنع الترحيل ({previewVal.notices.length})</div>
                      <ul className="text-[11px] text-rose-700 list-disc pr-4 space-y-0.5">
                        {previewVal.notices.map((w, i) => <li key={i}>{w.message}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-lg border border-green-200 bg-green-50 p-2 text-xs text-green-700 font-medium">
                  ✓ اجتازت جميع قواعد التحقق — جاهزة للترحيل
                </div>
              ))}
            </div>

            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2 shrink-0">
              <button onClick={() => { setPreview(null); setPreviewVal(null) }} disabled={pushing}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                إلغاء
              </button>
              <button data-tour="invoices-main-push-confirm"
                onClick={() => handlePush((previewVal?.warnings?.length || 0) > 0)}
                disabled={pushing || (previewVal?.errors?.length > 0)
                          || ((previewVal?.warnings?.length > 0) && !ackWarnings)}
                title={previewVal?.errors?.length > 0 ? 'صحّح الأخطاء أولاً' : ''}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed">
                {pushing ? 'جارٍ الترحيل...' : (previewVal?.errors?.length > 0 ? '⛔ يوجد أخطاء' : '⇪ تأكيد الترحيل')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sub-header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <button onClick={onBack} className="text-gray-400 hover:text-gray-600 text-sm">← رجوع</button>
          <div className="h-4 w-px bg-gray-300" />
          <h2 className="font-bold text-gray-900">
            {inv.supplier_name || 'فاتورة جديدة'}
            {inv.invoice_number && <span className="text-gray-400 font-normal mr-2 text-sm">#{inv.invoice_number}</span>}
          </h2>
          <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${stCfg.color}`}>
            {stCfg.dot} {stCfg.label}
          </span>

          <div data-tour="invoices-main-actions" className="mr-auto flex items-center gap-2 flex-wrap">
            {/* Processing spinner */}
            {inv.status === 'processing' && (
              <span className="text-xs text-blue-600 animate-pulse flex items-center gap-1">
                <span className="inline-block w-3 h-3 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
                جاري استخراج النص...
              </span>
            )}

            {/* Anomaly check */}
            {lines.length > 0 && (
              <button onClick={fetchAnomalies}
                className="px-3 py-1.5 border border-amber-300 text-amber-700 bg-amber-50 rounded-lg text-xs font-medium hover:bg-amber-100">
                ⚠ فحص الانحرافات
              </button>
            )}

            {/* 3-way financial reconciliation */}
            {lines.length > 0 && (
              <button onClick={async () => { try { const r = await invoicesApi.reconcile3way(invoiceId); setRecon(r.data) } catch { showToast('تعذّرت المطابقة المالية', 'error') } }}
                className="px-3 py-1.5 border border-indigo-300 text-indigo-700 bg-indigo-50 rounded-lg text-xs font-medium hover:bg-indigo-100">
                ⚖ المطابقة المالية
              </button>
            )}

            {/* PO / goods-received (separate advisory check) */}
            {lines.length > 0 && (
              <button onClick={async () => { try { const r = await invoicesApi.poMatch(invoiceId); setPoResult(r.data) } catch { showToast('تعذّرت مطابقة أمر الشراء', 'error') } }}
                className="px-3 py-1.5 border border-gray-300 text-gray-600 bg-gray-50 rounded-lg text-xs font-medium hover:bg-gray-100">
                🔗 أمر الشراء
              </button>
            )}

            {/* Export buttons */}
            {lines.length > 0 && (
              <>
                <button onClick={handleExportExcel} disabled={exporting === 'excel'}
                  className="px-3 py-1.5 border border-green-300 text-green-700 bg-green-50 rounded-lg text-xs font-medium hover:bg-green-100">
                  {exporting === 'excel' ? '...' : '⬇ Excel'}
                </button>
                <button onClick={handleExportCsv} disabled={exporting === 'csv'}
                  className="px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg text-xs font-medium hover:bg-gray-50">
                  {exporting === 'csv' ? '...' : '⬇ CSV'}
                </button>
              </>
            )}

            {inv.source_image_url && editable && (
              <button data-tour="invoices-main-ocr" onClick={handleRerunOcr} disabled={rerunning}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
                {rerunning ? '...' : '🔄 إعادة OCR'}
              </button>
            )}
            {editable && (
              <button data-tour="invoices-main-confirm" onClick={handleConfirm}
                className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700">
                ✓ تأكيد الفاتورة
              </button>
            )}

            {/* SOFTECH writeback — validate + preview + push */}
            {['review', 'confirmed', 'push_failed', 'queued'].includes(inv.status) && lines.length > 0 && (
              <button data-tour="invoices-main-validate" onClick={handleValidate} disabled={validating}
                title="فحص قواعد SOFTECH (حد الائتمان، الأصناف المسموحة، حدود السعر، الصلاحية…)"
                className="px-3 py-1.5 border border-indigo-300 text-indigo-700 bg-indigo-50 rounded-lg text-sm font-medium hover:bg-indigo-100 disabled:opacity-50">
                {validating ? '...' : '🛡 فحص التحقق'}
              </button>
            )}
            {editable && lines.some(l => l.item && !l.is_confirmed) && (
              <button data-tour="invoices-main-confirm-ready" onClick={confirmGreen} disabled={confirmingGreen}
                title="تأكيد كل السطور الجاهزة (مطابقة ≥85% ولها سعر) دفعة واحدة — تبقى فقط السطور التي تحتاج مراجعة"
                className="px-3 py-1.5 border border-green-300 text-green-700 bg-green-50 rounded-lg text-sm font-medium hover:bg-green-100 disabled:opacity-50">
                {confirmingGreen ? '...' : '✓ تأكيد الجاهزة'}
              </button>
            )}
            {inv.status !== 'finalized' && (
              <button data-tour="invoices-main-dupcheck" onClick={runDupCheck} disabled={dupChecking}
                title="فحص شامل على SofTech: رقم الفاتورة، الإجمالي، الأصناف، عددها، التاريخ وتاريخ الحفظ — قبل الترحيل لتجنّب التكرار"
                className="px-3 py-1.5 border border-rose-300 text-rose-700 bg-rose-50 rounded-lg text-sm font-medium hover:bg-rose-100 disabled:opacity-50">
                {dupChecking ? '...' : '🔎 فحص التكرار'}
              </button>
            )}
            {['confirmed', 'push_failed', 'queued', 'pushing'].includes(inv.status) && !inv.softech_docnumber && (
              <button data-tour="invoices-main-reopen" onClick={handleReopen} disabled={reopening || pushing}
                title="إرجاع الفاتورة للمراجعة لتعديل الجدول أو بيانات الرأس قبل الترحيل — لا يُرحَّل شيء"
                className="px-3 py-1.5 border border-amber-300 text-amber-700 bg-amber-50 rounded-lg text-sm font-medium hover:bg-amber-100 disabled:opacity-50">
                {reopening ? '...' : '↩ رجوع للتعديل'}
              </button>
            )}
            {['confirmed', 'push_failed', 'queued'].includes(inv.status) && (
              <button data-tour="invoices-main-push" onClick={openPreview} disabled={previewLoading || pushing}
                title="معاينة ثم ترحيل الفاتورة إلى SOFTECH كمستند شراء نهائي"
                className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
                {previewLoading ? 'جارٍ التحضير...' : (inv.status === 'push_failed' ? '↻ إعادة الترحيل' : '⇪ ترحيل إلى ERP')}
              </button>
            )}
            {inv.status === 'finalized' && inv.softech_docnumber && (
              <>
                <span className="px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-lg text-xs font-medium"
                  title="رقم المستند في SOFTECH">
                  ✓ مُرحّلة — مستند #{inv.softech_docnumber}
                </span>
                <button data-tour="invoices-main-verify" onClick={handleReconcile} disabled={reconciling}
                  title="التحقق من وجود المستند في SOFTECH"
                  className="px-2.5 py-1 border border-indigo-200 text-indigo-600 rounded-lg text-xs font-medium hover:bg-indigo-50 disabled:opacity-50">
                  {reconciling ? '...' : '🔄 تحقق'}
                </button>
                {inv.doc_kind === 'purchase' && (
                  <button data-tour="invoices-main-return" onClick={handleCreateReturn} disabled={returning}
                    title="إنشاء مرتجع مورد لهذه الفاتورة"
                    className="px-2.5 py-1 border border-orange-200 text-orange-600 rounded-lg text-xs font-medium hover:bg-orange-50 disabled:opacity-50">
                    {returning ? '...' : '↩ إنشاء مرتجع'}
                  </button>
                )}
              </>
            )}
            {inv.doc_kind === 'return' && inv.return_of_docnumber && (
              <span className="px-2.5 py-1 bg-orange-50 text-orange-700 rounded-lg text-xs font-medium"
                title="مرتجع مرتبط بمستند الشراء الأصلي في SOFTECH">
                ↩ مرتجع للمستند #{inv.return_of_docnumber}
              </span>
            )}
            {inv.status === 'push_failed' && inv.erp_error && (
              <span className="text-[11px] text-red-600 max-w-xs truncate" title={inv.erp_error}>
                {inv.erp_error}
              </span>
            )}
          </div>
        </div>

        {/* Header card */}
        <div data-tour="invoices-main-header-card" className="bg-gray-50 rounded-xl p-4 mb-3">
          {headerEdit ? (
            <div className="grid grid-cols-3 gap-3">
              {[
                { key: 'supplier_name', label: 'المورد', type: 'text' },
                { key: 'invoice_number', label: 'رقم الفاتورة', type: 'text' },
                { key: 'invoice_date', label: 'تاريخ الفاتورة', type: 'date' },
                { key: 'global_discount_pct', label: 'خصم عام %', type: 'number' },
                { key: 'global_discount_amt', label: 'خصم عام مبلغ', type: 'number' },
              ].map(f => (
                <div key={f.key}>
                  <label className="text-[10px] text-gray-500 block mb-0.5">{f.label}</label>
                  <input type={f.type} value={headerDraft[f.key] || ''}
                    onChange={e => setHeaderDraft(d => ({ ...d, [f.key]: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-brand-400" />
                </div>
              ))}
              <div className="flex items-end gap-2">
                <button onClick={saveHeader}
                  className="px-3 py-1.5 bg-brand-600 text-white rounded-lg text-xs font-medium">حفظ</button>
                <button onClick={() => setHeaderEdit(false)}
                  className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs">إلغاء</button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-6 flex-wrap text-sm">
              <div className="flex items-center gap-2 flex-wrap">
                <span><span className="text-gray-400 text-xs">المورد: </span><span className="font-medium">{inv.supplier_name || '—'}</span></span>
                <VendorLink inv={inv} editable={editable} onLinked={load} onNotify={showToast} />
              </div>
              <div><span className="text-gray-400 text-xs">الفاتورة: </span>
                {inv.invoice_number
                  ? <span className="font-mono">{inv.invoice_number}</span>
                  : <span className="text-red-600 font-medium" title="لم يُقرأ رقم فاتورة المورد — أدخله من «تعديل»">⚠ غير مقروء</span>}
              </div>
              <div><span className="text-gray-400 text-xs">التاريخ: </span>
                {inv.invoice_date
                  ? <span>{inv.invoice_date}</span>
                  : <span className="text-red-600 font-medium" title="لم يُقرأ تاريخ فاتورة المورد — يُحفظ في SofTech كـ «تاريخ مستند المورد»">⚠ غير مقروء</span>}
              </div>
              <div><span className="text-gray-400 text-xs">الخصم: </span><span>{inv.global_discount_pct}%</span></div>
              <div className="font-bold text-gray-900">
                <span className="text-gray-400 text-xs font-normal">الإجمالي: </span>
                {Number(inv.total_after_discount || 0).toFixed(3)} {inv.currency}
              </div>
              {editable && (
                <button onClick={() => setHeaderEdit(true)}
                  className="text-xs text-brand-600 hover:underline mr-auto">تعديل</button>
              )}
            </div>
          )}
        </div>

        {/* Stats + Add line */}
        <div className="flex items-center gap-5 text-xs text-gray-500">
          <span>{lines.length} سطر</span>
          <span className="text-green-600">{confirmed} مُأكَّد</span>
          <span className="text-amber-600">{unmatched} بدون مطابقة</span>
          {editable && (
            <button onClick={() => setAddLine(s => !s)}
              className="mr-auto px-3 py-1.5 border border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-brand-400 hover:text-brand-600 transition-colors">
              + إضافة سطر يدوي
            </button>
          )}
        </div>

        {/* Add line form */}
        {addLine && editable && (
          <div className="mt-3 p-3 bg-brand-50 border border-brand-200 rounded-xl">
            <div className="flex gap-3 items-end flex-wrap">
              <div>
                <label className="text-[10px] text-gray-500 block mb-0.5">الاسم</label>
                <input value={newLine.manual_name}
                  onChange={e => setNewLine(n => ({ ...n, manual_name: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-0.5">الكمية</label>
                <input type="number" value={newLine.quantity}
                  onChange={e => setNewLine(n => ({ ...n, quantity: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-0.5">السعر</label>
                <input type="number" value={newLine.unit_price}
                  onChange={e => setNewLine(n => ({ ...n, unit_price: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm w-24 focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-0.5">خصم %</label>
                <input type="number" step="0.5" value={newLine.discount_pct}
                  onChange={e => setNewLine(n => ({ ...n, discount_pct: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-brand-400" />
              </div>
              <button onClick={handleAddLine}
                className="px-3 py-1.5 bg-brand-600 text-white rounded-lg text-sm font-medium">إضافة</button>
              <button onClick={() => setAddLine(false)}
                className="px-3 py-1.5 bg-white text-gray-500 rounded-lg text-sm border">إلغاء</button>
            </div>
          </div>
        )}
      </div>

      {/* Lines */}
      <div data-tour="invoices-main-lines" className="flex-1 overflow-auto p-6">

        {/* Anomaly panel */}
        {showAnomalies && anomalies !== null && (
          <div className="mb-5 bg-amber-50 border border-amber-200 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold text-amber-800 text-sm">
                ⚠ تقرير الانحرافات
                {anomalies.length > 0
                  ? <span className="mr-2 bg-amber-200 text-amber-800 text-xs px-2 py-0.5 rounded-full">{anomalies.length} تنبيه</span>
                  : <span className="mr-2 text-green-600 text-xs">✓ لا توجد انحرافات</span>
                }
              </div>
              <button onClick={() => setShowAnomalies(false)} className="text-amber-500 hover:text-amber-700 text-xs">إغلاق</button>
            </div>
            {anomalies.length > 0 && (
              <div className="space-y-1.5">
                {anomalies.map((a, i) => (
                  <div key={i} className={`flex items-start gap-2 text-xs rounded-lg px-3 py-2
                    ${a.severity === 'error'   ? 'bg-red-100 text-red-700 border border-red-200' :
                      a.severity === 'warning' ? 'bg-amber-100 text-amber-700 border border-amber-200' :
                      'bg-blue-50 text-blue-700 border border-blue-200'}`}>
                    <span className="shrink-0 mt-0.5">
                      {a.severity === 'error' ? '🔴' : a.severity === 'warning' ? '🟡' : 'ℹ️'}
                    </span>
                    <span>{a.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 3-way financial reconciliation panel */}
        {recon && (
          <div className="mb-5 bg-indigo-50 border border-indigo-200 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold text-indigo-800 text-sm">⚖ المطابقة المالية (ثلاثية)</div>
              <button onClick={() => setRecon(null)} className="text-indigo-500 hover:text-indigo-700 text-xs">إغلاق</button>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center text-xs mb-3">
              {[['المقروء من الفاتورة', recon.ocr_total], ['إجمالي أسطرنا', recon.reconstructed_total],
                ['المُسجَّل في SOFTECH', recon.softech_total]].map(([lbl, v], i) => (
                <div key={i} className="bg-white rounded-xl p-2 border border-indigo-100">
                  <div className="text-gray-400">{lbl}</div>
                  <div className="font-bold text-gray-800 tabular-nums">{v != null ? Number(v).toFixed(2) : '—'}</div>
                </div>
              ))}
            </div>
            {(recon.flags || []).length === 0
              ? <div className="text-green-600 text-xs">✓ الإجماليات متطابقة</div>
              : <div className="space-y-1">{recon.flags.map((f, i) => (
                  <div key={i} className={`text-xs rounded-lg px-3 py-2 ${f.severity === 'error' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{f.message}</div>
                ))}</div>}
            {!recon.checked_softech && <div className="text-[11px] text-gray-400 mt-2">تعذّر قراءة إجمالي SOFTECH (قد يكون الخادم غير متاح).</div>}
          </div>
        )}

        {/* PO / goods-received advisory match */}
        {poResult && (
          <div className="mb-5 bg-gray-50 border border-gray-200 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold text-gray-700 text-sm">🔗 مطابقة أمر الشراء (استرشادية)</div>
              <button onClick={() => setPoResult(null)} className="text-gray-400 hover:text-gray-600 text-xs">إغلاق</button>
            </div>
            {poResult.linked === false ? (
              <div className="text-xs text-gray-500">لا يوجد أمر شراء مرتبط بهذه الفاتورة. اربط أمر شراء من API/الإدارة لتفعيل المطابقة.</div>
            ) : (
              <>
                <div className="flex gap-3 text-xs mb-2">
                  <span className="text-green-600">مطابق: {poResult.summary?.matched}</span>
                  <span className="text-amber-600">فرق كمية: {poResult.summary?.qty_mismatch}</span>
                  <span className="text-amber-600">فرق سعر: {poResult.summary?.price_mismatch}</span>
                  <span className="text-red-600">ناقص: {poResult.summary?.missing}</span>
                  <span className="text-blue-600">زائد: {poResult.summary?.extra}</span>
                </div>
                <div className="max-h-48 overflow-auto space-y-1">
                  {(poResult.lines || []).filter(l => l.status !== 'ok').map((l, i) => (
                    <div key={i} className="text-xs bg-white rounded-lg px-3 py-1.5 border border-gray-100 flex justify-between">
                      <span>{l.item_name}</span>
                      <span className="tabular-nums text-gray-500">طلب {l.po_qty}→فاتورة {l.inv_qty} · سعر {l.po_price}→{l.inv_price}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* OCR image preview */}
        {inv.source_image_url && (
          <div className="mb-4 flex items-start gap-4">
            <img src={inv.source_image_url} alt="فاتورة"
              className="w-48 h-auto rounded-xl border border-gray-200 shadow-sm object-contain cursor-pointer"
              onClick={() => window.open(inv.source_image_url, '_blank')} />
            {inv.raw_ocr_text && (
              <div dir="ltr" className="flex-1 bg-gray-50 rounded-xl p-3 max-h-48 overflow-auto text-[11px] font-mono text-gray-500 whitespace-pre-wrap text-left border border-gray-200">
                {prettyOcr(inv.raw_ocr_text)}
              </div>
            )}
          </div>
        )}

        {showDupPanel && dupInfo && (
          <div className={`mb-3 rounded-xl px-4 py-3 text-sm ${dupInfo.is_duplicate ? 'bg-red-50 border border-red-300 text-red-800' : dupInfo.likely_duplicate ? 'bg-amber-50 border border-amber-300 text-amber-800' : 'bg-green-50 border border-green-300 text-green-800'}`}>
            <div className="flex items-center justify-between">
              <div className="font-bold">
                {dupInfo.is_duplicate ? '⛔ فاتورة مكرّرة — سبق حفظها' : dupInfo.likely_duplicate ? '⚠ تكرار محتمل — راجع المستندات المشابهة' : '✓ لا يوجد تكرار على SofTech'}
              </div>
              <button onClick={() => setShowDupPanel(false)} className="text-xs opacity-60 hover:opacity-100">إغلاق ✕</button>
            </div>
            {dupInfo.softech_match && (
              <div className="mt-1">سبق حفظها في SOFTECH برقم مستند <b className="font-mono">{dupInfo.softech_match.docnumber}</b>
                {dupInfo.softech_match.docdate ? ` بتاريخ ${String(dupInfo.softech_match.docdate).slice(0,10)}` : ''}
                {dupInfo.softech_match.docvalue ? ` — الإجمالي ${Number(dupInfo.softech_match.docvalue).toFixed(2)}` : ''}.</div>
            )}
            {(dupInfo.pg_duplicates || []).length > 0 && (
              <div className="mt-1">مُدخلة من قبل في هذا النظام: {dupInfo.pg_duplicates.map(d => `#${d.id} (${d.status})`).join('، ')}.</div>
            )}
            {(dupInfo.candidates || []).length > 0 && (
              <div className="mt-2 space-y-1">
                <div className="text-xs font-semibold">مستندات SofTech مشابهة (بعدّة عوامل):</div>
                {dupInfo.candidates.map(c => (
                  <div key={c.docnumber} className="text-xs bg-white/60 rounded px-2 py-1">
                    <b className="font-mono">#{c.docnumber}</b>
                    <span className={`ms-1.5 px-1 rounded ${c.score >= 0.75 ? 'bg-red-200 text-red-800' : 'bg-amber-200 text-amber-800'}`}>تطابق {Math.round(c.score * 100)}%</span>
                    {c.docvalue != null && <span className="ms-1.5">إجمالي {Number(c.docvalue).toFixed(2)}</span>}
                    {c.item_count ? <span className="ms-1.5">· {c.item_count} صنف</span> : null}
                    {c.save_date && <span className="ms-1.5 text-gray-500">· حُفظت {String(c.save_date).slice(0,10)}</span>}
                    <div className="text-[11px] text-gray-600">{(c.factors || []).join(' · ')}</div>
                  </div>
                ))}
              </div>
            )}
            {dupInfo.checked_softech === false && <div className="text-[11px] text-gray-500 mt-1">لم يُفحص SofTech (تحقق من الاتصال/إعدادات المورد).</div>}
            {dupInfo.softech_error && <div className="text-[11px] text-gray-500 mt-1">تعذّر فحص SofTech بالكامل: {dupInfo.softech_error}</div>}
          </div>
        )}

        {lines.length > 0 && (
          <div data-tour="invoices-main-view" className="flex items-center gap-1 mb-3 text-sm">
            <span className="text-gray-400 text-xs ml-1">العرض:</span>
            <button onClick={() => setViewMode('cards')}
              className={`px-2.5 py-1 rounded-lg ${viewMode === 'cards' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600'}`}>
              بطاقات
            </button>
            <button onClick={() => setViewMode('grid')}
              className={`px-2.5 py-1 rounded-lg ${viewMode === 'grid' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600'}`}
              title="جدول مطابق لشاشة SofTech مع تعديل مباشر">
              ⊞ جدول SofTech
            </button>
          </div>
        )}

        {lines.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-4xl mb-3">📄</div>
            <div>لا توجد سطور. أضف يدوياً أو قم برفع صورة للفاتورة.</div>
          </div>
        ) : viewMode === 'grid' ? (
          <SoftechGrid invoiceId={invoiceId} editable={editable} onChanged={load} />
        ) : (
          <div className="max-w-3xl">
            {editable && <div className="text-[11px] text-gray-400 mb-1">⌨ ↑↓ تنقل · Enter تأكيد والتالي · M اقتراحات المطابقة</div>}
            <div {...kb.containerProps}>
            {lines.map(l => (
              <InvoiceLineRow
                key={l.id}
                kb={kb.rowProps(l, { block: true })}
                openReq={openReq}
                line={l}
                invoiceId={invoiceId}
                onUpdated={load}
                onDelete={handleDelete}
                editable={editable}
                onNotify={showToast}
              />
            ))}
            </div>
            {/* Total */}
            <div className="mt-4 flex justify-end">
              <div className="bg-white rounded-xl border border-gray-200 p-4 text-right min-w-48">
                <div className="text-xs text-gray-400 mb-1">الإجمالي قبل الخصم</div>
                <div className="text-sm font-medium text-gray-700">{Number(inv.total_before_discount || 0).toFixed(3)} {inv.currency}</div>
                {(Number(inv.global_discount_pct) > 0 || Number(inv.global_discount_amt) > 0) && (
                  <>
                    <div className="text-xs text-gray-400 mt-2 mb-0.5">الخصم العام</div>
                    <div className="text-sm text-red-500">
                      -{inv.global_discount_pct}% / {Number(inv.global_discount_amt).toFixed(3)}
                    </div>
                  </>
                )}
                <div className="border-t border-gray-200 mt-2 pt-2">
                  <div className="text-xs text-gray-400 mb-0.5">الإجمالي النهائي</div>
                  <div className="text-lg font-bold text-gray-900">{Number(inv.total_after_discount || 0).toFixed(3)} {inv.currency}</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Create Modal ──────────────────────────────────────────────────────────────

function CreateInvoiceModal({ branches, onClose, onCreated }) {
  const fileRef = useRef()
  const [form, setForm] = useState({ branch: '', vendor: '', invoice_number: '' })
  const [vendors, setVendors] = useState([])
  const [file, setFile] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  useEffect(() => { invoicesApi.listVendors({ main: 1 }).then(r => setVendors(r.data.results || r.data)).catch(() => {}) }, [])

  const submit = async () => {
    if (!form.branch) { setError('اختر الفرع'); return }
    setSaving(true); setError(null)
    try {
      const fd = new FormData()
      Object.entries(form).forEach(([k, v]) => v && fd.append(k, v))
      if (file) fd.append('source_image', file)
      const r = await invoicesApi.create(fd)
      onCreated(r.data.id)
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md" dir="rtl">
        <h3 className="font-bold text-gray-900 mb-5">فاتورة مورد جديدة</h3>
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
            <label className="text-xs text-gray-600 block mb-1">المورد</label>
            <select value={form.vendor}
              onChange={e => setForm(f => ({ ...f, vendor: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
              <option value="">— اختر المورد —</option>
              {vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            <div className="text-[11px] text-gray-400 mt-1">يُحسِّن المطابقة ويُفعّل قالب الأعمدة. التاريخ ورقم الفاتورة يُقرآن تلقائياً من الصورة.</div>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">رقم الفاتورة (اختياري)</label>
            <input value={form.invoice_number}
              onChange={e => setForm(f => ({ ...f, invoice_number: e.target.value }))}
              placeholder="يُقرأ من الصورة إن تُرك فارغاً"
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>

          {/* Image upload */}
          <div>
            <label className="text-xs text-gray-600 block mb-1">صورة الفاتورة (OCR)</label>
            <div data-tour="invoices-main-new-upload"
              onClick={() => fileRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-colors
                ${file ? 'border-brand-400 bg-brand-50' : 'border-gray-300 hover:border-brand-300'}`}
            >
              {file ? (
                <div className="text-sm font-medium text-brand-600">✓ {file.name}</div>
              ) : (
                <div className="text-gray-400 text-sm">
                  <div className="text-2xl mb-1">📷</div>
                  انقر لرفع صورة أو PDF للفاتورة
                </div>
              )}
              <input ref={fileRef} type="file" accept="image/*,application/pdf" className="hidden"
                onChange={e => setFile(e.target.files[0] || null)} />
            </div>
            {file && (
              <button onClick={() => setFile(null)}
                className="text-xs text-red-400 hover:text-red-600 mt-1">إزالة الصورة</button>
            )}
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
        <div className="flex gap-2 mt-5">
          <button data-tour="invoices-main-new-create" onClick={submit} disabled={saving}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? (file ? 'جاري الرفع والمعالجة...' : 'جاري الإنشاء...') : 'إنشاء الفاتورة'}
          </button>
          <button onClick={onClose}
            className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-xl font-medium hover:bg-gray-200 text-sm">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

// ── Page Root ─────────────────────────────────────────────────────────────────

export default function InvoicePage() {
  const [invoices,     setInvoices]     = useState([])
  const [branches,     setBranches]     = useState([])
  const [loading,      setLoading]      = useState(true)
  const [showCreate,   setShowCreate]   = useState(false)
  const [activeId,     setActiveId]     = useState(null)
  const [filterBranch, setFilterBranch] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterAttention, setFilterAttention] = useState('')   // '' | '1' | 'clean'
  const [selected,     setSelected]     = useState(() => new Set())  // batch push selection
  const [pushingBatch, setPushingBatch] = useState(false)
  const [batchResult,  setBatchResult]  = useState(null)
  const [tab,          setTab]          = useState('invoices')       // 'invoices' | 'bundles'

  const PUSHABLE = new Set(['confirmed', 'queued', 'push_failed'])
  const toggleSelect = (id) => setSelected(s => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const runBatchPush = async () => {
    const ids = [...selected]
    if (!ids.length) return
    setPushingBatch(true); setBatchResult(null)
    try {
      const r = await invoicesApi.pushBatch(ids)
      setBatchResult(r.data)
      setSelected(new Set())
      loadInvoices()
    } catch (e) {
      setBatchResult({ error: e.response?.data?.detail || 'فشل ترحيل الدفعة' })
    } finally { setPushingBatch(false) }
  }

  const loadInvoices = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterBranch) params.branch = filterBranch
      if (filterStatus) params.status = filterStatus
      if (filterAttention) params.attention = filterAttention
      const r = await invoicesApi.list(params)
      setInvoices(r.data.results || r.data)
    } finally {
      setLoading(false)
    }
  }, [filterBranch, filterStatus, filterAttention])

  useEffect(() => { branchesApi.list().then(r => setBranches(r.data.results || r.data)) }, [])
  useEffect(() => { loadInvoices() }, [loadInvoices])

  if (activeId) {
    return <InvoiceDetail invoiceId={activeId} onBack={() => { setActiveId(null); loadInvoices() }}
                          onOpen={(id) => setActiveId(id)} />
  }

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">

      {showCreate && (
        <CreateInvoiceModal
          branches={branches}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => { setShowCreate(false); setActiveId(id) }}
        />
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🧾</span>
            <div>
              <h1 className="text-xl font-bold text-gray-900">فواتير الموردين</h1>
              <p className="text-sm text-gray-500">رفع وتحليل فواتير الموردين مع مطابقة الأصناف</p>
            </div>
          </div>
          <button data-tour="invoices-main-new" onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
            + فاتورة جديدة
          </button>
        </div>
        {/* Tabs: single invoices vs multi-invoice PDF bundles */}
        <div data-tour="invoices-main-tabs" className="flex gap-2 mt-4">
          <button onClick={() => setTab('invoices')}
            className={`px-4 py-1.5 rounded-xl text-sm font-medium ${tab === 'invoices' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
            🧾 الفواتير
          </button>
          <button onClick={() => setTab('bundles')}
            className={`px-4 py-1.5 rounded-xl text-sm font-medium ${tab === 'bundles' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
            📑 حزم (PDF متعدد)
          </button>
        </div>
        {tab === 'invoices' && (
          <div data-tour="invoices-main-filters" className="flex gap-3 mt-4 flex-wrap">
            <BranchSelect
              size="sm"
              value={filterBranch}
              onChange={setFilterBranch}
              branches={branches}
              allLabel="كل الفروع"
              className="w-52"
            />
            <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
              <option value="">كل الحالات</option>
              {Object.entries(STATUS_CONFIG).map(([v, c]) => <option key={v} value={v}>{c.dot} {c.label}</option>)}
            </select>
            <div className="flex gap-1 bg-gray-100 rounded-xl p-0.5">
              {[['', 'الكل'], ['1', '⚠ تحتاج مراجعة'], ['clean', '✓ نظيفة']].map(([v, lbl]) => (
                <button key={v} onClick={() => setFilterAttention(v)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium ${filterAttention === v ? 'bg-white shadow text-brand-700' : 'text-gray-500'}`}>
                  {lbl}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {tab === 'bundles' && (
        <BundleWorkbench branches={branches} onOpenInvoice={(id) => setActiveId(id)} />
      )}
      {tab === 'invoices' && (<>
      {/* ── invoices list below ── */}

      {/* List */}
      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">جاري التحميل...</div>
        ) : invoices.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">🧾</div>
            <div className="text-gray-500 font-medium mb-2">لا توجد فواتير</div>
            <button onClick={() => setShowCreate(true)}
              className="mt-4 px-5 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
              + فاتورة جديدة
            </button>
          </div>
        ) : (
          <div data-tour="invoices-main-list" className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {invoices.map(inv => {
              const cfg = STATUS_CONFIG[inv.status] || {}
              const matchPct = inv.line_count > 0
                ? Math.round((inv.confirmed_count / inv.line_count) * 100)
                : 0
              return (
                <div key={inv.id} data-tour="invoices-main-card" role="button" tabIndex={0}
                  onClick={() => setActiveId(inv.id)}
                  onKeyDown={e => { if (e.key === 'Enter') setActiveId(inv.id) }}
                  className={`relative bg-white rounded-2xl border p-5 text-right cursor-pointer hover:border-brand-300 hover:shadow-md transition-all ${selected.has(inv.id) ? 'border-brand-500 ring-2 ring-brand-200' : 'border-gray-200'}`}>
                  {PUSHABLE.has(inv.status) && (
                    <label data-tour="invoices-main-batch-select" onClick={e => e.stopPropagation()}
                      className="absolute top-3 left-3 flex items-center cursor-pointer" title="تحديد للترحيل كدفعة">
                      <input type="checkbox" checked={selected.has(inv.id)}
                        onChange={() => toggleSelect(inv.id)} className="w-4 h-4 accent-brand-600" />
                    </label>
                  )}
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="font-bold text-gray-900 text-sm">{inv.supplier_name || 'مورد غير محدد'}</div>
                      <div className="text-xs text-gray-400 mt-0.5">
                        {inv.branch_name}
                        {inv.invoice_number && <span className="mr-2 font-mono">#{inv.invoice_number}</span>}
                      </div>
                    </div>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${cfg.color}`}>
                      {cfg.dot} {cfg.label}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-gray-500 flex-wrap">
                    <span>{inv.line_count} سطر</span>
                    <span className="text-green-600">{inv.confirmed_count} مُأكَّد</span>
                    {inv.attention_count > 0 && (
                      <span className="text-amber-600">⚠ {inv.attention_count} تحتاج مراجعة</span>
                    )}
                    {inv.dup_check?.is_duplicate && (
                      <span className="px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 font-medium"
                        title={`سبق حفظها على SofTech${inv.dup_check.softech_docnumber ? ` (مستند #${inv.dup_check.softech_docnumber})` : ''}`}>
                        ⛔ مكرّرة
                      </span>
                    )}
                    {!inv.dup_check?.is_duplicate && inv.dup_check?.likely_duplicate && (
                      <span className="px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium"
                        title={`تكرار محتمل (تطابق ${Math.round((inv.dup_check.best_score || 0) * 100)}%)`}>
                        ⚠ تكرار محتمل
                      </span>
                    )}
                  </div>
                  {inv.line_count > 0 && (
                    <div className="mt-3 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-green-400 rounded-full" style={{ width: `${matchPct}%` }} />
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="text-xs text-gray-400">
                      {new Date(inv.created_at).toLocaleDateString('en-US')}
                    </span>
                    {inv.status === 'finalized' && inv.softech_docnumber && (
                      <span className="text-[10px] font-mono bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded"
                        title="رقم المستند في SOFTECH">
                        ERP #{inv.softech_docnumber}
                      </span>
                    )}
                    {inv.status === 'push_failed' && (
                      <span className="text-[10px] text-red-600 truncate max-w-[55%]" title={inv.erp_error}>
                        ⚠ {inv.erp_error || 'فشل الترحيل'}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Batch push action bar */}
      {selected.size > 0 && (
        <div className="shrink-0 bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between gap-3">
          <div className="text-sm text-gray-600">
            تم تحديد <b>{selected.size}</b> فاتورة للترحيل
            <button onClick={() => setSelected(new Set())} className="mr-3 text-xs text-gray-400 hover:text-gray-600">إلغاء التحديد</button>
          </div>
          <button data-tour="invoices-main-batch-push" onClick={runBatchPush} disabled={pushingBatch}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700 disabled:opacity-50">
            {pushingBatch ? 'جارٍ الترحيل…' : `⇪ ترحيل المحدد (${selected.size})`}
          </button>
        </div>
      )}

      {/* Batch result panel */}
      {batchResult && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setBatchResult(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col" dir="rtl" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <div className="font-bold text-gray-900">نتيجة ترحيل الدفعة</div>
              <button onClick={() => setBatchResult(null)} className="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            {batchResult.error ? (
              <div className="p-5 text-red-600">{batchResult.error}</div>
            ) : (
              <>
                <div className="px-5 py-3 text-sm flex gap-4 border-b border-gray-100">
                  <span className="text-green-600">نجح: <b>{batchResult.succeeded}</b></span>
                  <span className="text-red-600">فشل: <b>{batchResult.failed}</b></span>
                  <span className="text-gray-500">الإجمالي: {batchResult.total}</span>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-1.5">
                  {batchResult.results.map(r => (
                    <div key={r.id} className={`flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm ${r.ok ? 'bg-green-50' : r.skipped ? 'bg-gray-50' : 'bg-red-50'}`}>
                      <span className="text-gray-700 truncate">#{r.id} {r.supplier || ''}</span>
                      <span className={`text-xs ${r.ok ? 'text-green-700' : r.skipped ? 'text-gray-500' : 'text-red-600'}`}>
                        {r.docnumber ? `ERP #${r.docnumber}` : r.mode === 'dry_run' ? 'معاينة (الترحيل غير مُفعّل)' : r.disabled ? 'الترحيل غير مُفعّل' : (r.error || (r.ok ? 'تم' : 'فشل'))}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
      </>)}
    </div>
  )
}
