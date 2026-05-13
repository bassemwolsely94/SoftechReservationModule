import { useState, useEffect, useCallback, useRef } from 'react'
import { invoicesApi, branchesApi } from '../api/client'

// ── constants ─────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  pending:    { label: 'في الانتظار',    color: 'bg-gray-100 text-gray-500',    dot: '⏳' },
  processing: { label: 'جاري المعالجة', color: 'bg-blue-100 text-blue-600',    dot: '🔄' },
  review:     { label: 'قيد المراجعة',  color: 'bg-amber-100 text-amber-700',  dot: '👁' },
  confirmed:  { label: 'مُأكَّدة',      color: 'bg-green-100 text-green-700',  dot: '✅' },
  rejected:   { label: 'مرفوضة',        color: 'bg-red-100 text-red-600',      dot: '❌' },
}

function scoreColor(s) {
  if (!s) return 'text-gray-300'
  if (s >= 0.8) return 'text-green-600'
  if (s >= 0.5) return 'text-amber-500'
  return 'text-red-400'
}

// ── InvoiceLineRow ────────────────────────────────────────────────────────────

function InvoiceLineRow({ line, invoiceId, onUpdated, onDelete, editable }) {
  const [editing,     setEditing]     = useState(false)
  const [draft,       setDraft]       = useState({ ...line })
  const [showMatches, setShowMatches] = useState(false)
  const [matches,     setMatches]     = useState([])
  const [loadingM,    setLoadingM]    = useState(false)
  const [saving,      setSaving]      = useState(false)

  const fetchMatches = async () => {
    if (matches.length) { setShowMatches(s => !s); return }
    setLoadingM(true)
    try {
      const r = await invoicesApi.lineMatches(invoiceId, line.id)
      setMatches(r.data)
      setShowMatches(true)
    } finally {
      setLoadingM(false)
    }
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
      setEditing(false)
      setShowMatches(false)
      onUpdated()
    } finally {
      setSaving(false)
    }
  }

  const selectMatch = async (m) => {
    await invoicesApi.updateLine(invoiceId, line.id, { item: m.item_id, is_confirmed: true })
    setShowMatches(false)
    onUpdated()
  }

  const total = Number(line.line_total || 0).toFixed(3)

  return (
    <div className={`border rounded-xl mb-2 overflow-hidden
      ${line.is_confirmed ? 'border-green-200 bg-green-50/20' :
        line.item ? 'border-blue-200 bg-blue-50/10' :
        'border-amber-200 bg-amber-50/10'}`}>

      <div className="flex items-start gap-3 p-3">
        {/* Confirm dot */}
        <div className="mt-0.5 shrink-0">
          {line.is_confirmed
            ? <span className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center text-white text-[10px]">✓</span>
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
                <input type="number" value={draft.discount_pct}
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
                </div>
              )}
              <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                <span>الكمية: <strong>{line.quantity}</strong></span>
                <span>السعر: <strong>{Number(line.unit_price).toFixed(3)}</strong></span>
                {Number(line.discount_pct) > 0 && <span>خصم: <strong>{line.discount_pct}%</strong></span>}
                <span className="font-bold text-gray-700">الإجمالي: {total}</span>
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
          <div className="text-xs font-semibold text-gray-500 mb-2">اختر الصنف المطابق:</div>
          {matches.length === 0 ? (
            <div className="text-xs text-gray-400">لا توجد نتائج</div>
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

function InvoiceDetail({ invoiceId, onBack }) {
  const [inv,         setInv]         = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [headerEdit,  setHeaderEdit]  = useState(false)
  const [headerDraft, setHeaderDraft] = useState({})
  const [addLine,     setAddLine]     = useState(false)
  const [newLine,     setNewLine]     = useState({ manual_name: '', quantity: 1, unit_price: 0, discount_pct: 0 })
  const [rerunning,   setRerunning]   = useState(false)
  const [toast,       setToast]       = useState(null)

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

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400 animate-pulse">جاري التحميل...</div>
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

          <div className="mr-auto flex items-center gap-2">
            {inv.source_image_url && editable && (
              <button onClick={handleRerunOcr} disabled={rerunning}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
                {rerunning ? '...' : '🔄 إعادة OCR'}
              </button>
            )}
            {editable && (
              <button onClick={handleConfirm}
                className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700">
                ✓ تأكيد الفاتورة
              </button>
            )}
          </div>
        </div>

        {/* Header card */}
        <div className="bg-gray-50 rounded-xl p-4 mb-3">
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
              <div><span className="text-gray-400 text-xs">المورد: </span><span className="font-medium">{inv.supplier_name || '—'}</span></div>
              <div><span className="text-gray-400 text-xs">الفاتورة: </span><span className="font-mono">{inv.invoice_number || '—'}</span></div>
              <div><span className="text-gray-400 text-xs">التاريخ: </span><span>{inv.invoice_date || '—'}</span></div>
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
                <input type="number" value={newLine.discount_pct}
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
      <div className="flex-1 overflow-auto p-6">
        {/* OCR image preview */}
        {inv.source_image_url && (
          <div className="mb-4 flex items-start gap-4">
            <img src={inv.source_image_url} alt="فاتورة"
              className="w-48 h-auto rounded-xl border border-gray-200 shadow-sm object-contain cursor-pointer"
              onClick={() => window.open(inv.source_image_url, '_blank')} />
            {inv.raw_ocr_text && (
              <div className="flex-1 bg-gray-50 rounded-xl p-3 max-h-48 overflow-auto text-[11px] font-mono text-gray-500 whitespace-pre-wrap border border-gray-200">
                {inv.raw_ocr_text}
              </div>
            )}
          </div>
        )}

        {lines.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-4xl mb-3">📄</div>
            <div>لا توجد سطور. أضف يدوياً أو قم برفع صورة للفاتورة.</div>
          </div>
        ) : (
          <div className="max-w-3xl">
            {lines.map(l => (
              <InvoiceLineRow
                key={l.id}
                line={l}
                invoiceId={invoiceId}
                onUpdated={load}
                onDelete={handleDelete}
                editable={editable}
              />
            ))}
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
  const [form, setForm] = useState({ branch: '', supplier_name: '', invoice_number: '', invoice_date: '' })
  const [file, setFile] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

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
            <select value={form.branch} onChange={e => setForm(f => ({ ...f, branch: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
              <option value="">-- اختر الفرع --</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">اسم المورد</label>
            <input value={form.supplier_name}
              onChange={e => setForm(f => ({ ...f, supplier_name: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              placeholder="مثال: شركة الحكمة" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">رقم الفاتورة</label>
              <input value={form.invoice_number}
                onChange={e => setForm(f => ({ ...f, invoice_number: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">التاريخ</label>
              <input type="date" value={form.invoice_date}
                onChange={e => setForm(f => ({ ...f, invoice_date: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
            </div>
          </div>

          {/* Image upload */}
          <div>
            <label className="text-xs text-gray-600 block mb-1">صورة الفاتورة (OCR)</label>
            <div
              onClick={() => fileRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-colors
                ${file ? 'border-brand-400 bg-brand-50' : 'border-gray-300 hover:border-brand-300'}`}
            >
              {file ? (
                <div className="text-sm font-medium text-brand-600">✓ {file.name}</div>
              ) : (
                <div className="text-gray-400 text-sm">
                  <div className="text-2xl mb-1">📷</div>
                  انقر لرفع صورة الفاتورة
                </div>
              )}
              <input ref={fileRef} type="file" accept="image/*" className="hidden"
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
          <button onClick={submit} disabled={saving}
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

  const loadInvoices = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterBranch) params.branch = filterBranch
      if (filterStatus) params.status = filterStatus
      const r = await invoicesApi.list(params)
      setInvoices(r.data.results || r.data)
    } finally {
      setLoading(false)
    }
  }, [filterBranch, filterStatus])

  useEffect(() => { branchesApi.list().then(r => setBranches(r.data.results || r.data)) }, [])
  useEffect(() => { loadInvoices() }, [loadInvoices])

  if (activeId) {
    return <InvoiceDetail invoiceId={activeId} onBack={() => { setActiveId(null); loadInvoices() }} />
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
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
            + فاتورة جديدة
          </button>
        </div>
        <div className="flex gap-3 mt-4 flex-wrap">
          <select value={filterBranch} onChange={e => setFilterBranch(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
            <option value="">كل الحالات</option>
            {Object.entries(STATUS_CONFIG).map(([v, c]) => <option key={v} value={v}>{c.dot} {c.label}</option>)}
          </select>
        </div>
      </div>

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
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {invoices.map(inv => {
              const cfg = STATUS_CONFIG[inv.status] || {}
              const matchPct = inv.line_count > 0
                ? Math.round((inv.confirmed_count / inv.line_count) * 100)
                : 0
              return (
                <button key={inv.id} onClick={() => setActiveId(inv.id)}
                  className="bg-white rounded-2xl border border-gray-200 p-5 text-right hover:border-brand-300 hover:shadow-md transition-all">
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
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span>{inv.line_count} سطر</span>
                    <span className="text-green-600">{inv.confirmed_count} مُأكَّد</span>
                  </div>
                  {inv.line_count > 0 && (
                    <div className="mt-3 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-green-400 rounded-full" style={{ width: `${matchPct}%` }} />
                    </div>
                  )}
                  <div className="mt-2 text-xs text-gray-400">
                    {new Date(inv.created_at).toLocaleDateString('ar-EG')}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
