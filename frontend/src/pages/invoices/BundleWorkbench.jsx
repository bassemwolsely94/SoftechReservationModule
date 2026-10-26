import { useState, useEffect, useCallback, useRef } from 'react'
import { invoicesApi, branchesApi } from '../../api/client'
import BranchSelect from '../../components/BranchSelect'
import VendorTemplateEditor from './VendorTemplateEditor'

/**
 * Multi-invoice PDF bundle review workbench.
 *
 * Upload one distributor PDF → it is split into the separate invoices it
 * contains → review each detected invoice (opens the normal invoice detail,
 * which shows the scanned page beside the SofTech grid). The split is advisory
 * and fully shown (split_summary) so the operator can verify every boundary.
 */

const BATCH_STATUS = {
  pending:    { label: 'في الانتظار',        cls: 'bg-gray-100 text-gray-600' },
  processing: { label: 'جارٍ التقسيم…',       cls: 'bg-amber-100 text-amber-700 animate-pulse' },
  ready:      { label: 'جاهزة للمراجعة',      cls: 'bg-green-100 text-green-700' },
  failed:     { label: 'فشل التقسيم',          cls: 'bg-red-100 text-red-700' },
}

// document-robustness / OCR review flags → Arabic labels
const FLAG_LABELS = {
  blank_pages:    '📄 تم تجاهل صفحات فارغة',
  rotated_pages:  '🔄 تم تصحيح صفحات مقلوبة',
  no_lines:       '⚠ لم تُستخرج أصناف',
  few_lines:      '⚠ أصناف قليلة',
  low_recall:     '✂ قد تكون ناقصة/مقصوصة',
  low_confidence: '✍ جودة منخفضة (خط يد؟)',
  no_totals:      '✂ لا توجد إجماليات',
}
function FlagChips({ flags }) {
  if (!flags || !flags.length) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {flags.map(f => (
        <span key={f} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
          {FLAG_LABELS[f] || f}
        </span>
      ))}
    </div>
  )
}

function UploadBundle({ branches, onClose, onCreated }) {
  const [form, setForm] = useState({ branch: '', vendor: '', doc_kind: 'purchase', ocr_engine: '' })
  const [vendors, setVendors] = useState([])
  const [file, setFile] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { invoicesApi.listVendors({ main: 1 }).then(r => setVendors(r.data.results || r.data)).catch(() => {}) }, [])

  const submit = async () => {
    if (!form.branch) { setError('اختر الفرع'); return }
    if (!file) { setError('اختر ملف PDF'); return }
    setSaving(true); setError('')
    try {
      const fd = new FormData()
      fd.append('branch', form.branch)
      if (form.vendor) fd.append('vendor', form.vendor)
      fd.append('doc_kind', form.doc_kind)
      if (form.ocr_engine) fd.append('ocr_engine', form.ocr_engine)
      fd.append('source_file', file)
      const r = await invoicesApi.createBatch(fd)
      onCreated(r.data.id)
    } catch (e) {
      setError(e.response?.data?.detail || 'فشل رفع الحزمة')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="font-bold text-gray-900 mb-4">رفع حزمة فواتير (PDF متعدد)</div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500">الفرع</label>
            <BranchSelect size="sm" value={form.branch} onChange={v => setForm(f => ({ ...f, branch: v }))}
              branches={branches} allLabel="— اختر —" className="w-full" />
          </div>
          <div>
            <label className="text-xs text-gray-500">المورد (اختياري — يحسّن المطابقة والقالب)</label>
            <select value={form.vendor} onChange={e => setForm(f => ({ ...f, vendor: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm">
              <option value="">— غير محدد —</option>
              {vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs text-gray-500">نوع المستند</label>
              <select value={form.doc_kind} onChange={e => setForm(f => ({ ...f, doc_kind: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm">
                <option value="purchase">شراء</option>
                <option value="return">مرتجع</option>
              </select>
            </div>
            <div className="flex-1">
              <label className="text-xs text-gray-500">محرك القراءة</label>
              <select value={form.ocr_engine} onChange={e => setForm(f => ({ ...f, ocr_engine: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm">
                <option value="">تلقائي</option>
                <option value="gemini">Gemini (مدفوع)</option>
                <option value="easyocr">easyOCR (مجاني)</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500">ملف PDF (قد يحتوي عدة فواتير)</label>
            <input type="file" accept="application/pdf,image/*" onChange={e => setFile(e.target.files[0])}
              className="w-full text-sm mt-1" />
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
        <div className="flex gap-2 mt-5">
          <button onClick={submit} disabled={saving}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? 'جارٍ الرفع والتقسيم…' : 'رفع وتقسيم'}
          </button>
          <button onClick={onClose} className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-xl font-medium hover:bg-gray-200 text-sm">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

function BundleDetail({ batchId, onBack, onOpenInvoice }) {
  const [batch, setBatch] = useState(null)
  const [reprocessing, setReprocessing] = useState(false)
  const [editTemplate, setEditTemplate] = useState(false)
  const pollRef = useRef(null)

  const load = useCallback(async () => {
    const r = await invoicesApi.getBatch(batchId)
    setBatch(r.data)
    return r.data
  }, [batchId])

  useEffect(() => {
    load()
    pollRef.current = setInterval(async () => {
      const b = await load()
      if (b && b.status !== 'processing' && b.status !== 'pending') clearInterval(pollRef.current)
    }, 3000)
    return () => clearInterval(pollRef.current)
  }, [load])

  const reprocess = async () => {
    setReprocessing(true)
    try { await invoicesApi.reprocessBatch(batchId); load() }
    catch (e) { alert(e.response?.data?.detail || 'تعذّرت إعادة التقسيم') }
    finally { setReprocessing(false) }
  }

  if (!batch) return <div className="p-6 text-gray-400 animate-pulse">جاري التحميل…</div>
  const st = BATCH_STATUS[batch.status] || {}
  const invByPages = Object.fromEntries((batch.invoices || []).map(i => [JSON.stringify(i.source_pages || []), i]))

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-gray-400 hover:text-gray-700">→ رجوع</button>
          <div>
            <div className="font-bold text-gray-900">حزمة #{batch.id} — {batch.vendor_name || 'مورد غير محدد'}</div>
            <div className="text-xs text-gray-500">{batch.branch_name} · {batch.page_count} صفحة · {batch.detected_count} فاتورة مكتشفة</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${st.cls}`}>{st.label}</span>
          {batch.vendor && (
            <button onClick={() => setEditTemplate(true)}
              className="text-xs px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200">
              ⚙ قالب المورد
            </button>
          )}
          {batch.status !== 'processing' && (
            <button onClick={reprocess} disabled={reprocessing}
              className="text-xs px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 disabled:opacity-50">
              {reprocessing ? '…' : '↻ إعادة التقسيم'}
            </button>
          )}
        </div>
      </div>

      {editTemplate && batch.vendor && (
        <VendorTemplateEditor
          vendorId={batch.vendor}
          sampleImageUrl={(batch.invoices || [])[0]?.source_image_url}
          onClose={() => setEditTemplate(false)}
          onSaved={load} />
      )}

      {batch.status === 'processing' && batch.detected_count > 0 && (
        <div className="mx-4 mt-3">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>جارٍ المعالجة…</span>
            <span>{batch.processed_count} / {batch.detected_count}</span>
          </div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-brand-500 rounded-full transition-all"
              style={{ width: `${Math.round((batch.processed_count / Math.max(1, batch.detected_count)) * 100)}%` }} />
          </div>
        </div>
      )}
      {batch.error && <div className="m-4 text-sm text-red-700 bg-red-50 px-4 py-3 rounded-xl">{batch.error}</div>}
      {batch.flags && batch.flags.length > 0 && (
        <div className="mx-4 mt-3"><FlagChips flags={batch.flags} /></div>
      )}

      <div className="flex-1 overflow-auto p-6">
        <div className="text-sm font-medium text-gray-700 mb-3">الفواتير المكتشفة ({batch.detected_count})</div>
        {(batch.split_summary || []).length === 0 ? (
          <div className="text-gray-400 text-sm">{batch.status === 'processing' ? 'جارٍ التقسيم…' : 'لا توجد فواتير'}</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {batch.split_summary.map((seg, i) => {
              const inv = invByPages[JSON.stringify(seg.pages ? seg.pages.map(p => p + 1) : [])] ||
                          invByPages[JSON.stringify(seg.page_numbers || [])]
              return (
                <div key={i} data-tour="invoices-main-bundle-invoice" role="button" tabIndex={0}
                  onClick={() => inv && onOpenInvoice(inv.id)}
                  onKeyDown={e => { if (e.key === 'Enter' && inv) onOpenInvoice(inv.id) }}
                  className={`bg-white rounded-2xl border p-4 text-right transition-all ${inv ? 'cursor-pointer hover:border-brand-300 hover:shadow-md' : 'opacity-60'} border-gray-200`}>
                  <div className="flex items-center justify-between">
                    <div className="font-mono text-sm text-gray-900">{seg.doc_number || '—'}</div>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${seg.confidence === 'high' ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
                      {seg.confidence === 'high' ? 'ثقة عالية' : 'راجع الحدود'}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">{seg.doc_type || ''} {seg.date && `· ${seg.date}`}</div>
                  <div className="text-[11px] text-gray-400 mt-2">
                    صفحات: {(seg.page_numbers || []).join('، ')}
                    {inv && <span className="mr-2 text-green-600">· {inv.line_count} سطر</span>}
                  </div>
                  {inv && <FlagChips flags={inv.ocr_flags} />}
                  {inv && (
                    <div className="mt-2 text-[11px] text-brand-600">فتح للمراجعة ←</div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default function BundleWorkbench({ branches, onOpenInvoice }) {
  const [batches, setBatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)
  const [activeBatch, setActiveBatch] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { const r = await invoicesApi.listBatches(); setBatches(r.data.results || r.data) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (activeBatch) {
    return <BundleDetail batchId={activeBatch} onBack={() => { setActiveBatch(null); load() }}
                         onOpenInvoice={onOpenInvoice} />
  }

  return (
    <div className="flex-1 overflow-auto p-6" dir="rtl">
      {showUpload && (
        <UploadBundle branches={branches} onClose={() => setShowUpload(false)}
          onCreated={(id) => { setShowUpload(false); setActiveBatch(id); load() }} />
      )}

      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-gray-500">ارفع ملف PDF يحتوي عدة فواتير؛ يقسّمه النظام تلقائياً إلى فواتير منفصلة للمراجعة.</div>
        <button data-tour="invoices-main-bundle-new" onClick={() => setShowUpload(true)}
          className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">+ حزمة جديدة</button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">جاري التحميل…</div>
      ) : batches.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-5xl mb-4">📑</div>
          <div className="text-gray-500 font-medium mb-2">لا توجد حزم</div>
          <button onClick={() => setShowUpload(true)}
            className="mt-4 px-5 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">+ حزمة جديدة</button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {batches.map(b => {
            const st = BATCH_STATUS[b.status] || {}
            return (
              <div key={b.id} role="button" tabIndex={0}
                onClick={() => setActiveBatch(b.id)}
                onKeyDown={e => { if (e.key === 'Enter') setActiveBatch(b.id) }}
                className="bg-white rounded-2xl border border-gray-200 p-5 text-right cursor-pointer hover:border-brand-300 hover:shadow-md transition-all">
                <div className="flex items-start justify-between mb-2">
                  <div className="font-bold text-gray-900 text-sm">{b.vendor_name || 'مورد غير محدد'}</div>
                  <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${st.cls}`}>{st.label}</span>
                </div>
                <div className="text-xs text-gray-400">{b.branch_name}</div>
                <div className="flex items-center gap-4 text-xs text-gray-500 mt-3">
                  <span>{b.page_count} صفحة</span>
                  <span className="text-brand-600">{b.detected_count} فاتورة</span>
                  {b.invoice_count > 0 && <span className="text-green-600">{b.invoice_count} أُنشئت</span>}
                </div>
                <div className="mt-2 text-xs text-gray-400">{new Date(b.created_at).toLocaleDateString('en-US')}</div>
                {b.error && <div className="mt-2 text-[11px] text-red-600 truncate" title={b.error}>⚠ {b.error}</div>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
