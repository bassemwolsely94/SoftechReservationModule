import { useState, useEffect, useCallback } from 'react'
import { stockCountApi, branchesApi, itemsApi } from '../api/client'

// ── helpers ──────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  open:      { label: 'قيد الجرد',  color: 'bg-blue-100 text-blue-700' },
  completed: { label: 'مكتمل',      color: 'bg-green-100 text-green-700' },
  cancelled: { label: 'ملغى',       color: 'bg-gray-100 text-gray-500' },
}

function diffColor(diff) {
  if (diff === null || diff === undefined) return 'text-gray-400'
  const n = Number(diff)
  if (n === 0) return 'text-green-600 font-semibold'
  if (n > 0)   return 'text-blue-600 font-semibold'
  return 'text-red-600 font-semibold'
}

// ── CountLine row ─────────────────────────────────────────────────────────────

function CountLineRow({ line, sessionId, onUpdated, isOpen }) {
  const [editing, setEditing]   = useState(false)
  const [qty,     setQty]       = useState(line.counted_qty ?? '')
  const [notes,   setNotes]     = useState(line.notes ?? '')
  const [saving,  setSaving]    = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      await stockCountApi.updateLine(sessionId, line.id, {
        counted_qty: qty === '' ? null : Number(qty),
        notes,
      })
      onUpdated()
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  const diff = line.counted_qty != null
    ? Number(line.counted_qty) - Number(line.system_qty)
    : null

  return (
    <tr className={`border-b border-gray-100 hover:bg-gray-50 transition-colors
      ${line.has_discrepancy ? 'bg-red-50/30' : ''}`}>
      <td className="px-4 py-2.5">
        <div className="text-sm font-medium text-gray-800">{line.item_name}</div>
        {line.item_scientific && (
          <div className="text-xs text-gray-400 italic">{line.item_scientific}</div>
        )}
        {line.item_softech_id && (
          <div className="text-[11px] font-mono text-gray-400">{line.item_softech_id}</div>
        )}
      </td>
      <td className="px-4 py-2.5 text-center text-sm text-gray-700">{Number(line.system_qty).toFixed(2)}</td>
      <td className="px-4 py-2.5 text-center text-sm text-gray-500">
        {line.erp_transqty != null ? Number(line.erp_transqty).toFixed(2) : '—'}
      </td>
      <td className="px-4 py-2.5 text-center">
        {editing ? (
          <input
            type="number"
            value={qty}
            onChange={e => setQty(e.target.value)}
            className="w-24 border border-brand-400 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:ring-2 focus:ring-brand-400"
            autoFocus
            step="0.001"
          />
        ) : (
          <span className={`text-sm ${line.counted_qty != null ? 'text-gray-800 font-medium' : 'text-gray-300'}`}>
            {line.counted_qty != null ? Number(line.counted_qty).toFixed(2) : '—'}
          </span>
        )}
      </td>
      <td className={`px-4 py-2.5 text-center text-sm ${diffColor(diff)}`}>
        {diff != null
          ? (diff >= 0 ? `+${diff.toFixed(2)}` : diff.toFixed(2))
          : '—'}
      </td>
      <td className="px-4 py-2.5">
        {editing ? (
          <input
            value={notes}
            onChange={e => setNotes(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-brand-400"
            placeholder="ملاحظة..."
          />
        ) : (
          <span className="text-xs text-gray-400">{line.notes || ''}</span>
        )}
      </td>
      {isOpen && (
        <td className="px-3 py-2.5 text-center">
          {editing ? (
            <div className="flex items-center gap-1 justify-center">
              <button onClick={save} disabled={saving}
                className="px-2.5 py-1 bg-brand-600 text-white rounded-lg text-xs font-medium hover:bg-brand-700 disabled:opacity-50">
                {saving ? '...' : 'حفظ'}
              </button>
              <button onClick={() => { setQty(line.counted_qty ?? ''); setNotes(line.notes ?? ''); setEditing(false) }}
                className="px-2.5 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200">
                إلغاء
              </button>
            </div>
          ) : (
            <button onClick={() => setEditing(true)}
              className="px-2.5 py-1 border border-gray-300 text-gray-500 rounded-lg text-xs hover:bg-gray-50">
              تعديل
            </button>
          )}
        </td>
      )}
    </tr>
  )
}

// ── Session Detail ────────────────────────────────────────────────────────────

function SessionDetail({ sessionId, onBack }) {
  const [session,     setSession]     = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [importing,   setImporting]   = useState(false)
  const [erpForm,     setErpForm]     = useState({ doc_code: '', doc_number: '', branch_code: '' })
  const [showImport,  setShowImport]  = useState(false)
  const [addItemQ,    setAddItemQ]    = useState('')
  const [itemResults, setItemResults] = useState([])
  const [searchingItem, setSearchingItem] = useState(false)
  const [completing,  setCompleting]  = useState(false)
  const [toast,       setToast]       = useState(null)
  const [filter,      setFilter]      = useState('all')  // all | discrepancy | uncounted

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await stockCountApi.get(sessionId)
      setSession(res.data)
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  // Item search
  useEffect(() => {
    if (!addItemQ || addItemQ.length < 2) { setItemResults([]); return }
    const t = setTimeout(async () => {
      setSearchingItem(true)
      try {
        const r = await itemsApi.list({ search: addItemQ, page_size: 10 })
        setItemResults(r.data.results || r.data)
      } finally {
        setSearchingItem(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [addItemQ])

  const handleImport = async () => {
    if (!erpForm.doc_code || !erpForm.doc_number) return
    setImporting(true)
    try {
      const r = await stockCountApi.importErp(sessionId, erpForm)
      showToast(`تم استيراد ${r.data._imported} صنف من ERP`)
      setShowImport(false)
      setSession(r.data)
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ في الاستيراد', 'error')
    } finally {
      setImporting(false)
    }
  }

  const handleAddItem = async (item) => {
    try {
      await stockCountApi.addItem(sessionId, { item_id: item.id })
      showToast(`تمت إضافة "${item.name}"`)
      setAddItemQ('')
      setItemResults([])
      load()
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ', 'error')
    }
  }

  const handleComplete = async () => {
    if (!confirm('إغلاق جلسة الجرد؟ لن تتمكن من تعديلها بعد ذلك.')) return
    setCompleting(true)
    try {
      await stockCountApi.complete(sessionId)
      showToast('تم إغلاق الجلسة ✓')
      load()
    } finally {
      setCompleting(false)
    }
  }

  const handleExport = async () => {
    try {
      const r = await stockCountApi.exportCsv(sessionId)
      const url = URL.createObjectURL(new Blob([r.data]))
      const a   = document.createElement('a')
      a.href    = url
      a.download = `stock_count_${sessionId}.csv`
      a.click()
    } catch {
      showToast('خطأ في التصدير', 'error')
    }
  }

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400 animate-pulse">جاري التحميل...</div>
  if (!session) return null

  const isOpen = session.status === 'open'
  const lines  = session.lines || []

  const filteredLines = lines.filter(l => {
    if (filter === 'discrepancy') return l.has_discrepancy
    if (filter === 'uncounted')   return l.counted_qty == null
    return true
  })

  const totalDisc = lines.filter(l => l.has_discrepancy).length
  const uncounted = lines.filter(l => l.counted_qty == null).length
  const statusCfg = STATUS_CONFIG[session.status] || {}

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
        <div className="flex items-center gap-3 mb-3">
          <button onClick={onBack} className="text-gray-400 hover:text-gray-600 text-sm flex items-center gap-1">
            ← رجوع
          </button>
          <div className="h-4 w-px bg-gray-300" />
          <h2 className="font-bold text-gray-900">جرد {session.branch_name} — {session.count_date}</h2>
          <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${statusCfg.color}`}>
            {statusCfg.label}
          </span>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          {/* Stats */}
          <div className="flex gap-4 text-sm">
            <span className="text-gray-500">{lines.length} صنف</span>
            <span className="text-amber-600">{uncounted} لم يُعد</span>
            <span className="text-red-600">{totalDisc} فرق</span>
          </div>
          <div className="mr-auto flex items-center gap-2">
            {isOpen && (
              <>
                {/* Import ERP */}
                <button onClick={() => setShowImport(s => !s)}
                  className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-1.5">
                  📥 استيراد من ERP
                </button>
                {/* Complete */}
                <button onClick={handleComplete} disabled={completing}
                  className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50">
                  {completing ? '...' : '✓ إغلاق الجلسة'}
                </button>
              </>
            )}
            <button onClick={handleExport}
              className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
              📊 تصدير CSV
            </button>
          </div>
        </div>

        {/* Import panel */}
        {showImport && (
          <div className="mt-3 p-4 bg-blue-50 rounded-xl border border-blue-200">
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <label className="text-xs text-gray-600 block mb-1">كود المستند (doccode)</label>
                <input value={erpForm.doc_code}
                  onChange={e => setErpForm(f => ({ ...f, doc_code: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-28 focus:outline-none focus:ring-2 focus:ring-brand-400"
                  placeholder="110" />
              </div>
              <div>
                <label className="text-xs text-gray-600 block mb-1">رقم المستند</label>
                <input value={erpForm.doc_number}
                  onChange={e => setErpForm(f => ({ ...f, doc_number: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-36 focus:outline-none focus:ring-2 focus:ring-brand-400"
                  placeholder="123456" />
              </div>
              <div>
                <label className="text-xs text-gray-600 block mb-1">كود الفرع (اختياري)</label>
                <input value={erpForm.branch_code}
                  onChange={e => setErpForm(f => ({ ...f, branch_code: e.target.value }))}
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-28 focus:outline-none focus:ring-2 focus:ring-brand-400"
                  placeholder="1" />
              </div>
              <button onClick={handleImport} disabled={importing}
                className="px-4 py-1.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                {importing ? 'جاري الاستيراد...' : 'استيراد'}
              </button>
              <button onClick={() => setShowImport(false)}
                className="px-3 py-1.5 bg-white text-gray-500 rounded-lg text-sm border hover:bg-gray-50">
                إلغاء
              </button>
            </div>
          </div>
        )}

        {/* Add item panel */}
        {isOpen && (
          <div className="mt-3 relative">
            <input
              value={addItemQ}
              onChange={e => setAddItemQ(e.target.value)}
              className="w-full max-w-md border border-gray-300 rounded-xl px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              placeholder="🔍 إضافة صنف بالاسم أو الكود..."
            />
            {(itemResults.length > 0 || searchingItem) && (
              <div className="absolute top-full mt-1 w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-lg z-20 max-h-52 overflow-auto">
                {searchingItem && <div className="px-4 py-3 text-sm text-gray-400 animate-pulse">جاري البحث...</div>}
                {itemResults.map(item => (
                  <button key={item.id} onClick={() => handleAddItem(item)}
                    className="w-full text-right px-4 py-2.5 hover:bg-brand-50 text-sm flex items-center justify-between border-b border-gray-50 last:border-0">
                    <div>
                      <span className="font-medium text-gray-800">{item.name}</span>
                      {item.name_scientific && <span className="text-xs text-gray-400 mr-1">({item.name_scientific})</span>}
                    </div>
                    <span className="text-xs font-mono text-gray-400">{item.softech_id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div className="bg-gray-50 border-b border-gray-200 px-6 py-2 flex gap-2">
        {[
          { id: 'all',         label: `الكل (${lines.length})` },
          { id: 'uncounted',   label: `لم يُعد (${uncounted})` },
          { id: 'discrepancy', label: `فروق (${totalDisc})` },
        ].map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
              ${filter === f.id ? 'bg-brand-600 text-white' : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-100'}`}>
            {f.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-right">
          <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
            <tr>
              <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-right">الصنف</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">كمية النظام</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">كمية ERP</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">الكمية المعدودة</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">الفرق</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-right">ملاحظات</th>
              {isOpen && <th className="px-3 py-3 text-xs font-semibold text-gray-500 text-center">إجراء</th>}
            </tr>
          </thead>
          <tbody>
            {filteredLines.length === 0 ? (
              <tr>
                <td colSpan={isOpen ? 7 : 6} className="px-4 py-12 text-center text-gray-400 text-sm">
                  {lines.length === 0
                    ? 'لا توجد سطور. استورد من ERP أو أضف أصنافاً يدوياً.'
                    : 'لا توجد سطور تطابق هذا الفلتر.'}
                </td>
              </tr>
            ) : filteredLines.map(line => (
              <CountLineRow
                key={line.id}
                line={line}
                sessionId={sessionId}
                onUpdated={load}
                isOpen={isOpen}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Session List / Create ─────────────────────────────────────────────────────

function CreateSessionModal({ branches, onClose, onCreated }) {
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({ branch: '', count_date: today, notes: '' })
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const submit = async () => {
    if (!form.branch) { setError('اختر الفرع'); return }
    setSaving(true); setError(null)
    try {
      const r = await stockCountApi.create(form)
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
        <h3 className="font-bold text-gray-900 mb-4">جلسة جرد جديدة</h3>
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
            <label className="text-xs text-gray-600 block mb-1">تاريخ الجرد *</label>
            <input type="date" value={form.count_date}
              onChange={e => setForm(f => ({ ...f, count_date: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">ملاحظات</label>
            <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg border border-red-200">{error}</div>}
        <div className="flex gap-2 mt-5">
          <button onClick={submit} disabled={saving}
            className="flex-1 py-2 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? 'جاري الإنشاء...' : 'إنشاء جلسة'}
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

// ── Page root ─────────────────────────────────────────────────────────────────

export default function StockCountPage() {
  const [sessions,    setSessions]    = useState([])
  const [branches,    setBranches]    = useState([])
  const [loading,     setLoading]     = useState(true)
  const [showCreate,  setShowCreate]  = useState(false)
  const [activeId,    setActiveId]    = useState(null)
  const [filterBranch, setFilterBranch] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  const loadSessions = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterBranch) params.branch = filterBranch
      if (filterStatus) params.status = filterStatus
      const r = await stockCountApi.list(params)
      setSessions(r.data.results || r.data)
    } finally {
      setLoading(false)
    }
  }, [filterBranch, filterStatus])

  useEffect(() => {
    branchesApi.list().then(r => setBranches(r.data.results || r.data))
  }, [])

  useEffect(() => { loadSessions() }, [loadSessions])

  if (activeId) {
    return (
      <SessionDetail
        sessionId={activeId}
        onBack={() => { setActiveId(null); loadSessions() }}
      />
    )
  }

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">

      {showCreate && (
        <CreateSessionModal
          branches={branches}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => { setShowCreate(false); setActiveId(id) }}
        />
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📦</span>
            <div>
              <h1 className="text-xl font-bold text-gray-900">الجرد الفعلي</h1>
              <p className="text-sm text-gray-500">إنشاء وإدارة جلسات الجرد وتتبع الفروق</p>
            </div>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
            + جلسة جرد جديدة
          </button>
        </div>
        {/* Filters */}
        <div className="flex gap-3 mt-4 flex-wrap">
          <select value={filterBranch} onChange={e => setFilterBranch(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
            <option value="">كل الحالات</option>
            <option value="open">قيد الجرد</option>
            <option value="completed">مكتملة</option>
            <option value="cancelled">ملغاة</option>
          </select>
        </div>
      </div>

      {/* Sessions list */}
      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">جاري التحميل...</div>
        ) : sessions.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">📦</div>
            <div className="text-gray-500 font-medium mb-2">لا توجد جلسات جرد</div>
            <div className="text-sm text-gray-400 mb-6">ابدأ بإنشاء جلسة جديدة</div>
            <button onClick={() => setShowCreate(true)}
              className="px-5 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
              + جلسة جديدة
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {sessions.map(s => {
              const cfg = STATUS_CONFIG[s.status] || {}
              return (
                <button key={s.id} onClick={() => setActiveId(s.id)}
                  className="bg-white rounded-2xl border border-gray-200 p-5 text-right hover:border-brand-300 hover:shadow-md transition-all">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="font-bold text-gray-900 text-sm">{s.branch_name}</div>
                      <div className="text-xs text-gray-400 mt-0.5">{s.count_date}</div>
                    </div>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${cfg.color}`}>
                      {cfg.label}
                    </span>
                  </div>
                  <div className="flex gap-4 text-xs text-gray-500">
                    <span>{s.total_lines} صنف</span>
                    {s.discrepancy_count > 0 && (
                      <span className="text-red-500 font-medium">{s.discrepancy_count} فرق</span>
                    )}
                    {s.erp_doc_number && (
                      <span className="font-mono text-gray-400">#{s.erp_doc_number}</span>
                    )}
                  </div>
                  {s.notes && (
                    <div className="mt-2 text-xs text-gray-400 truncate">{s.notes}</div>
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
