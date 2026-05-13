import { useState, useEffect, useCallback } from 'react'
import { shortageApi, branchesApi } from '../api/client'

// ── helpers ──────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  open:      { label: 'مفتوحة',   color: 'bg-blue-100 text-blue-700',   dot: 'bg-blue-500' },
  submitted: { label: 'مُرسَلة', color: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500' },
  resolved:  { label: 'محلولة',  color: 'bg-green-100 text-green-700', dot: 'bg-green-500' },
}

function scoreColor(score) {
  if (!score) return 'text-gray-400'
  if (score >= 0.8) return 'text-green-600'
  if (score >= 0.5) return 'text-amber-600'
  return 'text-red-500'
}

// ── ShortageItemRow ───────────────────────────────────────────────────────────

function ShortageItemRow({ item: si, listId, onUpdated, onDelete, isOpen }) {
  const [showMatches, setShowMatches] = useState(false)
  const [matches,     setMatches]     = useState([])
  const [loadingM,    setLoadingM]    = useState(false)
  const [editing,     setEditing]     = useState(false)
  const [qty,         setQty]         = useState(si.quantity_needed)
  const [rawName,     setRawName]     = useState(si.raw_name)
  const [saving,      setSaving]      = useState(false)

  const loadMatches = async () => {
    if (matches.length > 0) { setShowMatches(s => !s); return }
    setLoadingM(true)
    try {
      const r = await shortageApi.itemMatches(listId, si.id)
      setMatches(r.data)
      setShowMatches(true)
    } finally {
      setLoadingM(false)
    }
  }

  const confirmMatch = async (match) => {
    await shortageApi.updateItem(listId, si.id, { item: match.item_id, is_confirmed: true })
    setShowMatches(false)
    onUpdated()
  }

  const markUnmatched = async () => {
    await shortageApi.updateItem(listId, si.id, { is_unmatched: true, item: null })
    setShowMatches(false)
    onUpdated()
  }

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

  const matchedItem = si.item_name

  return (
    <div className={`border rounded-xl mb-2 overflow-hidden transition-all
      ${si.is_unmatched ? 'border-gray-200 bg-gray-50' :
        si.is_confirmed ? 'border-green-200 bg-green-50/30' :
        matchedItem ? 'border-blue-200 bg-blue-50/20' :
        'border-amber-200 bg-amber-50/20'}`}>

      <div className="flex items-start gap-3 p-3">
        {/* Status dot */}
        <div className="mt-1 shrink-0">
          {si.is_unmatched ? (
            <span title="غير مطابق" className="w-5 h-5 rounded-full bg-gray-400 flex items-center justify-center text-white text-[10px]">✕</span>
          ) : si.is_confirmed ? (
            <span title="مُأكَّد" className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center text-white text-[10px]">✓</span>
          ) : matchedItem ? (
            <span title="مطابق تلقائياً" className="w-5 h-5 rounded-full bg-blue-400 flex items-center justify-center text-white text-[10px]">~</span>
          ) : (
            <span title="بلا مطابقة" className="w-5 h-5 rounded-full bg-amber-400 flex items-center justify-center text-white text-[10px]">?</span>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex items-center gap-2 flex-wrap">
              <input value={rawName} onChange={e => setRawName(e.target.value)}
                className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-brand-400" />
              <input type="number" value={qty} onChange={e => setQty(e.target.value)}
                className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-brand-400" />
              <button onClick={save} disabled={saving}
                className="px-2.5 py-1 bg-brand-600 text-white rounded-lg text-xs font-medium">
                {saving ? '...' : 'حفظ'}
              </button>
              <button onClick={() => setEditing(false)}
                className="px-2.5 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs">إلغاء</button>
            </div>
          ) : (
            <div>
              <span className="font-medium text-gray-800 text-sm">{si.raw_name}</span>
              <span className="text-xs text-gray-400 mr-2">× {si.quantity_needed}</span>
            </div>
          )}

          {/* Matched item */}
          {matchedItem && !editing && (
            <div className="mt-1 flex items-center gap-2">
              <span className="text-xs text-gray-500">→</span>
              <span className="text-xs font-medium text-gray-700">{si.item_name}</span>
              {si.item_softech_id && (
                <span className="text-[10px] font-mono text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{si.item_softech_id}</span>
              )}
              {si.item_sale_price > 0 && (
                <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                  {Number(si.item_sale_price).toFixed(2)} ج.م
                </span>
              )}
              {si.match_score && (
                <span className={`text-[10px] font-medium ${scoreColor(si.match_score)}`}>
                  {Math.round(si.match_score * 100)}%
                </span>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        {isOpen && !editing && (
          <div className="flex items-center gap-1.5 shrink-0">
            <button onClick={() => setEditing(true)}
              className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 rounded hover:bg-gray-100">
              ✏️
            </button>
            <button onClick={loadMatches}
              disabled={loadingM}
              className="text-xs text-blue-500 hover:text-blue-700 px-2 py-1 rounded hover:bg-blue-50 font-medium">
              {loadingM ? '...' : '🔍 تطابق'}
            </button>
            <button onClick={() => onDelete(si.id)}
              className="text-xs text-red-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50">
              🗑
            </button>
          </div>
        )}
      </div>

      {/* Matches dropdown */}
      {showMatches && (
        <div className="border-t border-gray-100 bg-white p-3">
          <div className="text-xs font-semibold text-gray-500 mb-2">اختر الصنف المطابق:</div>
          {matches.length === 0 ? (
            <div className="text-xs text-gray-400">لا توجد نتائج</div>
          ) : (
            <div className="space-y-1.5">
              {matches.map(m => (
                <button key={m.item_id} onClick={() => confirmMatch(m)}
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
                  <span className={`text-xs font-bold ml-3 ${scoreColor(m.score)}`}>
                    {Math.round(m.score * 100)}%
                  </span>
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-2 mt-2 pt-2 border-t border-gray-100">
            <button onClick={markUnmatched}
              className="text-xs text-gray-400 hover:text-gray-600">
              ✕ تعيين كغير مطابق
            </button>
            <button onClick={() => setShowMatches(false)}
              className="text-xs text-gray-400 hover:text-gray-600 mr-auto">
              إغلاق
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Shortage Detail ───────────────────────────────────────────────────────────

function ShortageDetail({ listId, onBack }) {
  const [sl,          setSl]         = useState(null)
  const [loading,     setLoading]    = useState(true)
  const [addMode,     setAddMode]    = useState('single') // single | bulk
  const [singleInput, setSingleInput]= useState({ raw_name: '', quantity_needed: 1, unit: '' })
  const [bulkText,    setBulkText]   = useState('')
  const [submitting,  setSubmitting] = useState(false)
  const [toast,       setToast]      = useState(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
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

  const handleAddSingle = async () => {
    if (!singleInput.raw_name.trim()) return
    setSubmitting(true)
    try {
      await shortageApi.addItem(listId, singleInput)
      setSingleInput({ raw_name: '', quantity_needed: 1, unit: '' })
      load()
      showToast('تمت الإضافة')
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBulkImport = async () => {
    const lines = bulkText.split('\n').filter(l => l.trim())
    if (!lines.length) return
    setSubmitting(true)
    try {
      const r = await shortageApi.bulkImport(listId, { lines })
      setBulkText('')
      load()
      showToast(`تم استيراد ${r.data.created} صنف`)
    } catch (e) {
      showToast('خطأ في الاستيراد', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (iid) => {
    if (!confirm('حذف هذا الصنف؟')) return
    await shortageApi.deleteItem(listId, iid)
    load()
  }

  const handleSubmit = async () => {
    if (!confirm('إرسال القائمة؟')) return
    await shortageApi.submit(listId)
    load()
    showToast('تم إرسال القائمة ✓')
  }

  const handleExport = async () => {
    try {
      const r = await shortageApi.exportCsv(listId)
      const url = URL.createObjectURL(new Blob([r.data]))
      const a = document.createElement('a'); a.href = url; a.download = `shortage_${listId}.csv`; a.click()
    } catch { showToast('خطأ في التصدير', 'error') }
  }

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400 animate-pulse">جاري التحميل...</div>
  if (!sl) return null

  const isOpen    = sl.status === 'open'
  const items     = sl.items || []
  const confirmed = items.filter(i => i.is_confirmed).length
  const unmatched = items.filter(i => i.is_unmatched).length
  const pending   = items.filter(i => !i.is_confirmed && !i.is_unmatched).length
  const statusCfg = STATUS_CONFIG[sl.status] || {}

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
          <h2 className="font-bold text-gray-900">{sl.title || `نواقص ${sl.branch_name}`}</h2>
          <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${statusCfg.color}`}>
            {statusCfg.label}
          </span>
          <div className="mr-auto flex items-center gap-2">
            {isOpen && (
              <button onClick={handleSubmit}
                className="px-3 py-1.5 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600">
                📤 إرسال
              </button>
            )}
            <button onClick={handleExport}
              className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
              📊 CSV
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="flex gap-5 text-xs text-gray-500 mb-4">
          <span>{items.length} صنف</span>
          <span className="text-green-600 font-medium">{confirmed} مُأكَّد</span>
          <span className="text-amber-600 font-medium">{pending} بانتظار</span>
          <span className="text-gray-400">{unmatched} غير مطابق</span>
        </div>

        {/* Add item UI */}
        {isOpen && (
          <div>
            <div className="flex gap-2 mb-3">
              <button onClick={() => setAddMode('single')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors
                  ${addMode === 'single' ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
                + صنف واحد
              </button>
              <button onClick={() => setAddMode('bulk')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors
                  ${addMode === 'bulk' ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
                📋 استيراد قائمة
              </button>
            </div>

            {addMode === 'single' ? (
              <div className="flex items-end gap-3 flex-wrap">
                <div>
                  <label className="text-xs text-gray-500 block mb-1">اسم الصنف *</label>
                  <input value={singleInput.raw_name}
                    onChange={e => setSingleInput(f => ({ ...f, raw_name: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && handleAddSingle()}
                    className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-brand-400"
                    placeholder="مثال: أموكسيسيلين ٥٠٠ مج" />
                </div>
                <div>
                  <label className="text-xs text-gray-500 block mb-1">الكمية</label>
                  <input type="number" value={singleInput.quantity_needed}
                    onChange={e => setSingleInput(f => ({ ...f, quantity_needed: e.target.value }))}
                    className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-20 focus:outline-none focus:ring-2 focus:ring-brand-400" />
                </div>
                <button onClick={handleAddSingle} disabled={submitting}
                  className="px-4 py-1.5 bg-brand-600 text-white rounded-xl text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                  {submitting ? '...' : 'إضافة'}
                </button>
              </div>
            ) : (
              <div>
                <div className="text-xs text-gray-500 mb-1">
                  أدخل كل صنف في سطر منفصل: <code className="bg-gray-100 px-1 rounded">اسم الصنف [الكمية]</code>
                </div>
                <textarea value={bulkText} onChange={e => setBulkText(e.target.value)}
                  rows={5}
                  className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-400 font-mono"
                  placeholder={'أموكسيسيلين 500 ملج 10\nباراسيتامول 5\nميترونيدازول 3'} />
                <button onClick={handleBulkImport} disabled={submitting}
                  className="mt-2 px-4 py-1.5 bg-brand-600 text-white rounded-xl text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                  {submitting ? 'جاري الاستيراد...' : 'استيراد'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Items */}
      <div className="flex-1 overflow-auto p-6">
        {items.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-4xl mb-3">📋</div>
            <div>لا توجد أصناف. أضف أصنافاً أو استورد قائمة.</div>
          </div>
        ) : (
          <div className="max-w-3xl">
            {items.map(si => (
              <ShortageItemRow
                key={si.id}
                item={si}
                listId={listId}
                onUpdated={load}
                onDelete={handleDelete}
                isOpen={isOpen}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Create Modal ──────────────────────────────────────────────────────────────

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
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md" dir="rtl">
        <h3 className="font-bold text-gray-900 mb-4">قائمة نواقص جديدة</h3>
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
            <label className="text-xs text-gray-600 block mb-1">العنوان (اختياري)</label>
            <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              placeholder="مثال: زيارة المندوب — مايو 2026" />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">ملاحظات</label>
            <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
        <div className="flex gap-2 mt-5">
          <button onClick={submit} disabled={saving}
            className="flex-1 py-2 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? '...' : 'إنشاء'}
          </button>
          <button onClick={onClose}
            className="flex-1 py-2 bg-gray-100 text-gray-600 rounded-xl font-medium hover:bg-gray-200 text-sm">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

// ── Page Root ─────────────────────────────────────────────────────────────────

export default function ShortagePage() {
  const [lists,        setLists]        = useState([])
  const [branches,     setBranches]     = useState([])
  const [loading,      setLoading]      = useState(true)
  const [showCreate,   setShowCreate]   = useState(false)
  const [activeId,     setActiveId]     = useState(null)
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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📋</span>
            <div>
              <h1 className="text-xl font-bold text-gray-900">إدخال النواقص</h1>
              <p className="text-sm text-gray-500">إدارة قوائم نواقص الأصناف مع مطابقة ذكية</p>
            </div>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
            + قائمة جديدة
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
            <option value="open">مفتوحة</option>
            <option value="submitted">مُرسَلة</option>
            <option value="resolved">محلولة</option>
          </select>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">جاري التحميل...</div>
        ) : lists.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">📋</div>
            <div className="text-gray-500 font-medium mb-2">لا توجد قوائم نواقص</div>
            <button onClick={() => setShowCreate(true)}
              className="mt-4 px-5 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
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
              return (
                <button key={sl.id} onClick={() => setActiveId(sl.id)}
                  className="bg-white rounded-2xl border border-gray-200 p-5 text-right hover:border-brand-300 hover:shadow-md transition-all">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="font-bold text-gray-900 text-sm">{sl.title || `نواقص ${sl.branch_name}`}</div>
                      <div className="text-xs text-gray-400 mt-0.5">{sl.branch_name} — {new Date(sl.created_at).toLocaleDateString('ar-EG')}</div>
                    </div>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${cfg.color}`}>{cfg.label}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span>{sl.item_count} صنف</span>
                    <span className="text-green-600">{sl.matched_count} مطابق</span>
                    {sl.item_count > 0 && (
                      <span className="font-medium">{matchPct}%</span>
                    )}
                  </div>
                  {/* Match progress bar */}
                  {sl.item_count > 0 && (
                    <div className="mt-3 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-green-400 rounded-full transition-all"
                        style={{ width: `${matchPct}%` }} />
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
