/**
 * InsuranceClaimsPage.jsx
 * مطالبات التأمين — Insurance Claims list
 *
 * Features:
 *   - Advanced filters: client, subclient, date range, status, year
 *   - Multi-select rows with bulk actions
 *   - "Discover from Softech" panel: query Softech by date range → pick & import
 *   - Quick status badge + print button per row
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'

// ── Helpers ────────────────────────────────────────────────────────────────────
const fmt = (n) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })
const fmtPlain = (n) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })

const STATUS_CFG = {
  draft:          { label: 'مسودة',          color: 'bg-gray-100 text-gray-600' },
  ready:          { label: 'جاهزة للطباعة',  color: 'bg-blue-100 text-blue-700' },
  submitted:      { label: 'مُقدَّمة',       color: 'bg-amber-100 text-amber-700' },
  under_review:   { label: 'قيد المراجعة',  color: 'bg-purple-100 text-purple-700' },
  partially_paid: { label: 'مدفوعة جزئياً', color: 'bg-teal-100 text-teal-700' },
  paid:           { label: 'مدفوعة',         color: 'bg-green-100 text-green-700' },
  rejected:       { label: 'مرفوضة',         color: 'bg-red-100 text-red-600' },
  cancelled:      { label: 'ملغاة',           color: 'bg-gray-100 text-gray-400' },
}

function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || { label: status, color: 'bg-gray-100 text-gray-500' }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap ${cfg.color}`}>
      {cfg.label}
    </span>
  )
}

function Btn({ children, onClick, variant = 'primary', size = 'md', className = '', disabled }) {
  const base = 'inline-flex items-center gap-1.5 rounded font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
  const sizes = { sm: 'px-2.5 py-1 text-xs', md: 'px-4 py-2 text-sm', lg: 'px-5 py-2.5 text-base' }
  const variants = {
    primary:   'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
    success:   'bg-green-600 text-white hover:bg-green-700',
    danger:    'bg-red-600 text-white hover:bg-red-700',
    ghost:     'text-gray-600 hover:text-gray-900 hover:bg-gray-100',
  }
  return (
    <button onClick={onClick} disabled={disabled}
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}>
      {children}
    </button>
  )
}

// ── Discover from Softech panel ────────────────────────────────────────────────
function DiscoverPanel({ clients, subclients, onImported, onClose }) {
  const [dateFrom, setDateFrom]     = useState('')
  const [dateTo, setDateTo]         = useState('')
  const [clientId, setClientId]     = useState('')
  const [subClientId, setSubClientId] = useState('')
  const [loading, setLoading]       = useState(false)
  const [results, setResults]       = useState(null)
  const [selected, setSelected]     = useState(new Set())
  const [importing, setImporting]   = useState(false)
  const [importLog, setImportLog]   = useState([])

  const filteredSubs = subclients.filter(sc =>
    !clientId || String(sc.client_id) === String(clientId)
  )

  const discover = async () => {
    if (!dateFrom || !dateTo) return
    setLoading(true); setResults(null); setSelected(new Set()); setImportLog([])
    try {
      const params = { date_from: dateFrom, date_to: dateTo }
      if (subClientId) params.subclient_id = subClientId
      // If a specific client is chosen but not subclient, pass client filter via subclient lookup
      const { data } = await insuranceApi.discoverMotalbas(params)
      setResults(data.results || [])
    } catch (e) {
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  const toggleSelect = (key) =>
    setSelected(prev => {
      const s = new Set(prev)
      s.has(key) ? s.delete(key) : s.add(key)
      return s
    })

  const toggleAll = () => {
    const importable = (results || []).filter(r => r.status === 'not_imported' && r.configured)
    if (selected.size === importable.length)
      setSelected(new Set())
    else
      setSelected(new Set(importable.map(r => `${r.subclient_id}__${r.motalbano}`)))
  }

  const importSelected = async () => {
    if (!selected.size) return
    const items = (results || [])
      .filter(r => selected.has(`${r.subclient_id}__${r.motalbano}`))
      .map(r => ({ subclient_id: r.subclient_id, motalbano: r.motalbano }))

    setImporting(true); setImportLog([])
    try {
      const { data } = await insuranceApi.bulkImport(items)
      setImportLog(data.results || [])
      // Refresh discovery results to mark newly imported ones
      const imported = new Set(
        (data.results || [])
          .filter(r => r.status === 'imported')
          .map(r => String(r.motalbano))
      )
      setResults(prev => (prev || []).map(r =>
        imported.has(String(r.motalbano))
          ? { ...r, status: 'imported' }
          : r
      ))
      setSelected(new Set())
      onImported()
    } finally {
      setImporting(false)
    }
  }

  const importableCount = (results || []).filter(r => r.status === 'not_imported' && r.configured).length
  const notImportedCount = importableCount

  const inp = 'border border-gray-300 rounded px-3 py-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-10 pb-10 overflow-auto">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl mx-4 flex flex-col max-h-[88vh]" dir="rtl">
        {/* Header */}
        <div className="flex justify-between items-center px-6 py-4 border-b border-gray-200 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-gray-800">استيعراض المطالبات من سوفتك</h2>
            <p className="text-xs text-gray-500 mt-0.5">اكتشاف المطالبات الجاهزة في سوفتك ضمن نطاق تاريخ معين</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        {/* Filter bar */}
        <div className="px-6 py-4 border-b border-gray-100 bg-gray-50 shrink-0">
          <div className="flex gap-3 flex-wrap items-end">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">من تاريخ الفترة *</label>
              <input type="date" className={inp} style={{width:160}} value={dateFrom}
                onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">إلى تاريخ الفترة *</label>
              <input type="date" className={inp} style={{width:160}} value={dateTo}
                onChange={e => setDateTo(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">العميل</label>
              <select className={inp} style={{width:200}} value={clientId}
                onChange={e => { setClientId(e.target.value); setSubClientId('') }}>
                <option value="">كل العملاء</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name_short || c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">الفئة</label>
              <select className={inp} style={{width:200}} value={subClientId}
                onChange={e => setSubClientId(e.target.value)}>
                <option value="">كل الفئات</option>
                {filteredSubs.map(sc => <option key={sc.id} value={sc.id}>{sc.name}</option>)}
              </select>
            </div>
            <Btn onClick={discover} disabled={loading || !dateFrom || !dateTo} size="md">
              {loading ? 'جارٍ البحث...' : '🔍 بحث في سوفتك'}
            </Btn>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {results === null && !loading && (
            <div className="text-center py-16 text-gray-400">
              <p className="text-4xl mb-3">🔍</p>
              <p className="text-sm">أدخل نطاق التاريخ ثم اضغط بحث لاستعراض المطالبات المتاحة</p>
            </div>
          )}

          {loading && (
            <div className="text-center py-16 text-gray-400">
              <p className="text-2xl mb-2">⏳</p>
              <p className="text-sm">جارٍ الاستعلام من سوفتك...</p>
            </div>
          )}

          {results !== null && !loading && results.length === 0 && (
            <div className="text-center py-16 text-gray-400">
              <p className="text-sm">لا توجد مطالبات في هذه الفترة</p>
            </div>
          )}

          {results !== null && !loading && results.length > 0 && (
            <>
              {/* Toolbar */}
              <div className="flex justify-between items-center mb-3">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-600">
                    {results.length} مطالبة
                    {notImportedCount > 0 && (
                      <span className="text-amber-600 mr-2">({notImportedCount} غير مستوردة)</span>
                    )}
                  </span>
                  {notImportedCount > 0 && (
                    <button onClick={toggleAll}
                      className="text-xs text-blue-600 hover:underline">
                      {selected.size === notImportedCount ? 'إلغاء تحديد الكل' : 'تحديد الكل غير المستورد'}
                    </button>
                  )}
                </div>
                {selected.size > 0 && (
                  <Btn onClick={importSelected} disabled={importing} variant="success" size="sm">
                    {importing
                      ? 'جارٍ الاستيراد...'
                      : `⬇ استيراد ${selected.size} مطالبة`}
                  </Btn>
                )}
              </div>

              {/* Import log */}
              {importLog.length > 0 && (
                <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded text-xs">
                  {importLog.map((r, i) => (
                    <div key={i} className={r.status === 'error' ? 'text-red-600' : 'text-green-700'}>
                      {r.status === 'imported'
                        ? `✓ مطالبة ${r.motalbano} → ${r.claim_number} (${r.rx_count} روشتة)`
                        : r.status === 'already_imported'
                        ? `— مطالبة ${r.motalbano} مستوردة مسبقاً`
                        : `✗ مطالبة ${r.motalbano}: ${r.error}`}
                    </div>
                  ))}
                </div>
              )}

              {/* Unconfigured warning */}
              {results.some(r => !r.configured) && (
                <div className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
                  <strong>ملاحظة:</strong> بعض المطالبات تخص عملاء لم يتم إعدادهم بعد (كود سوفتك غير مرتبط بفئة).
                  يرجى إضافة العميل والفئة من صفحة{' '}
                  <button className="underline font-medium" onClick={onClose}>إدارة العملاء والعقود</button>
                  {' '}ثم أعد البحث.
                </div>
              )}

              {/* Results table */}
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="w-8 px-2 py-2"></th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">رقم المطالبة</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">العميل / كود</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الفئة</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الفترة</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الروشتات</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500">الإجمالى</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الحالة</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {results.map(r => {
                    const key = `${r.subclient_id}__${r.motalbano}`
                    const isImported  = r.status === 'imported'
                    const isConfigured = r.configured
                    const isSelected  = selected.has(key)
                    const canSelect   = !isImported && isConfigured
                    return (
                      <tr key={key}
                        className={`${isImported ? 'bg-green-50/40' : !isConfigured ? 'bg-amber-50/40 opacity-70' : 'hover:bg-blue-50/30'} cursor-pointer`}
                        onClick={() => canSelect && toggleSelect(key)}>
                        <td className="px-2 py-2 text-center">
                          {canSelect && (
                            <input type="checkbox" checked={isSelected} onChange={() => toggleSelect(key)}
                              className="rounded" onClick={e => e.stopPropagation()} />
                          )}
                          {isImported && <span className="text-green-500 text-xs">✓</span>}
                          {!isConfigured && !isImported && (
                            <span className="text-amber-500 text-xs" title="عميل غير مُعدّ">!</span>
                          )}
                        </td>
                        <td className="px-3 py-2 font-mono text-blue-700 font-semibold">#{r.motalbano}</td>
                        <td className="px-3 py-2">
                          {isConfigured ? (
                            <span className="font-medium text-gray-800">{r.client_name_short}</span>
                          ) : (
                            <div>
                              {r.softech_personname
                                ? <span className="font-medium text-gray-700">{r.softech_personname}</span>
                                : <span className="text-amber-700">عميل غير معروف</span>}
                              <span className="text-amber-600 font-mono text-xs block">كود: {r.personcode}</span>
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-gray-600 text-xs">
                          {r.subclient_name || <span className="text-amber-600">غير مُعدّ</span>}
                        </td>
                        <td className="px-3 py-2 text-gray-500 text-xs whitespace-nowrap">
                          {r.motfromdate} → {r.mottodate}
                        </td>
                        <td className="px-3 py-2 text-center">{r.rxcount}</td>
                        <td className="px-3 py-2 text-left font-mono text-gray-700 text-xs">
                          {fmtPlain(r.docvaluetotal)}
                        </td>
                        <td className="px-3 py-2">
                          {isImported ? (
                            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full whitespace-nowrap">
                              {r.existing_claim?.claim_number || 'مستوردة'}
                            </span>
                          ) : !isConfigured ? (
                            <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full whitespace-nowrap">
                              يحتاج إعداد
                            </span>
                          ) : (
                            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full whitespace-nowrap">
                              جاهزة للاستيراد
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-100 bg-gray-50 shrink-0 flex justify-end">
          <Btn variant="secondary" onClick={onClose}>إغلاق</Btn>
        </div>
      </div>
    </div>
  )
}

// ── Import single motalba modal ────────────────────────────────────────────────
function ImportModal({ subclients, onClose, onCreated }) {
  const [form, setForm] = useState({
    subclient_id: '', contract_id: '', period_from: '',
    period_to: '', softech_motalba_no: '', notes: '',
  })
  const [contracts, setContracts] = useState([])
  const [motalbas, setMotalbas]   = useState([])
  const [loadingMot, setLoadingMot] = useState(false)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))

  useEffect(() => {
    if (!form.subclient_id) { setContracts([]); setMotalbas([]); return }
    insuranceApi.contracts({ subclient_id: form.subclient_id })
      .then(r => setContracts(r.data.results || r.data))
  }, [form.subclient_id])

  const loadMotalbas = () => {
    if (!form.subclient_id) return
    setLoadingMot(true)
    insuranceApi.listMotalbas(form.subclient_id)
      .then(r => { setMotalbas(Array.isArray(r.data) ? r.data : []); setLoadingMot(false) })
      .catch(() => setLoadingMot(false))
  }

  const pickMotalba = (m) => {
    set('softech_motalba_no', String(m.motalbano))
    set('period_from', m.motfromdate || form.period_from)
    set('period_to',   m.mottodate   || form.period_to)
    setMotalbas([])
  }

  const submit = async () => {
    if (!form.subclient_id) { setError('يرجى اختيار الفئة'); return }
    if (!form.softech_motalba_no && (!form.period_from || !form.period_to)) {
      setError('أدخل رقم المطالبة أو الفترة الزمنية'); return
    }
    setLoading(true); setError(null)
    try {
      const { data } = await insuranceApi.createAndImport({
        subclient_id:       Number(form.subclient_id),
        contract_id:        form.contract_id ? Number(form.contract_id) : null,
        period_from:        form.period_from || '2000-01-01',
        period_to:          form.period_to   || '2099-12-31',
        softech_motalba_no: form.softech_motalba_no,
        notes:              form.notes,
      })
      onCreated(data.claim)
    } catch (e) {
      setError(e.response?.data?.error || 'حدث خطأ')
    } finally { setLoading(false) }
  }

  const inp = 'w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
  const lbl = 'block text-xs font-medium text-gray-600 mb-1'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl mx-4 p-6" dir="rtl">
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-bold text-gray-800">استيراد مطالبة</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>
        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded">{error}</div>}

        <div className="space-y-4">
          <div>
            <label className={lbl}>الفئة / العميل *</label>
            <select className={inp} value={form.subclient_id}
              onChange={e => { set('subclient_id', e.target.value); setMotalbas([]) }}>
              <option value="">اختر الفئة...</option>
              {subclients.map(sc => (
                <option key={sc.id} value={sc.id}>{sc.client_name} — {sc.name}</option>
              ))}
            </select>
          </div>

          {form.subclient_id && (
            <div className="border border-blue-200 rounded-lg p-3 bg-blue-50">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs font-semibold text-blue-800">المطالبات المتاحة في سوفتك</span>
                <Btn onClick={loadMotalbas} disabled={loadingMot} size="sm" variant="secondary">
                  {loadingMot ? 'جارٍ التحميل...' : 'عرض المطالبات'}
                </Btn>
              </div>
              {motalbas.length > 0 && (
                <div className="max-h-44 overflow-y-auto border border-gray-200 rounded bg-white mb-2">
                  {motalbas.map(m => (
                    <button key={m.motalbano} onClick={() => pickMotalba(m)}
                      className={`w-full text-right px-3 py-2 text-xs hover:bg-blue-50 border-b border-gray-100 flex justify-between items-center ${
                        String(m.motalbano) === form.softech_motalba_no ? 'bg-blue-100' : ''
                      }`}>
                      <div>
                        <span className="font-mono font-bold text-blue-700 ml-2">#{m.motalbano}</span>
                        <span className="text-gray-500">{m.motfromdate} → {m.mottodate}</span>
                      </div>
                      <div>
                        <span className="text-gray-500 ml-2">{m.rxcount} روشتة</span>
                        <span className="font-mono text-gray-800">{fmtPlain(m.docvaluetotal)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
              <div>
                <label className={lbl}>أو أدخل رقم المطالبة يدوياً</label>
                <input className={inp} value={form.softech_motalba_no}
                  onChange={e => set('softech_motalba_no', e.target.value)}
                  placeholder="رقم المطالبة في سوفتك..." />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>من تاريخ</label>
              <input type="date" className={inp} value={form.period_from}
                onChange={e => set('period_from', e.target.value)} />
            </div>
            <div>
              <label className={lbl}>إلى تاريخ</label>
              <input type="date" className={inp} value={form.period_to}
                onChange={e => set('period_to', e.target.value)} />
            </div>
          </div>

          {contracts.length > 0 && (
            <div>
              <label className={lbl}>العقد (لنسب الخصم)</label>
              <select className={inp} value={form.contract_id}
                onChange={e => set('contract_id', e.target.value)}>
                <option value="">بدون عقد محدد</option>
                {contracts.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.name || `من ${c.effective_from}`} — محلى {c.local_discount_pct}% | مستورد {c.imported_discount_pct}%
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className={lbl}>ملاحظات</label>
            <textarea className={inp} rows={2} value={form.notes}
              onChange={e => set('notes', e.target.value)} />
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <Btn onClick={submit} disabled={loading || !form.subclient_id} className="flex-1">
            {loading ? 'جارٍ الاستيراد...' : 'استيراد وإنشاء المطالبة'}
          </Btn>
          <Btn variant="secondary" onClick={onClose}>إلغاء</Btn>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function InsuranceClaimsPage() {
  const navigate = useNavigate()
  const [claims, setClaims]           = useState([])
  const [loading, setLoading]         = useState(true)
  const [showImport, setShowImport]   = useState(false)
  const [showDiscover, setShowDiscover] = useState(false)
  const [clients, setClients]         = useState([])
  const [subclients, setSubclients]   = useState([])
  const [selected, setSelected]       = useState(new Set())
  const [syncing, setSyncing]         = useState(false)
  const [cacheStats, setCacheStats]   = useState(null)

  // ── Filters ──────────────────────────────────────────────────────────────────
  const [filters, setFilters] = useState({
    status:       '',
    year:         '',
    client_id:    '',
    subclient_id: '',
    date_from:    '',
    date_to:      '',
    search:       '',
  })
  const setF = (k, v) => setFilters(p => ({ ...p, [k]: v }))

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filters.status)       params.status       = filters.status
      if (filters.year)         params.year         = filters.year
      if (filters.client_id)    params.client_id    = filters.client_id
      if (filters.subclient_id) params.subclient_id = filters.subclient_id
      const { data } = await insuranceApi.claims(params)
      setClaims(data.results || data)
    } finally { setLoading(false) }
  }, [filters.status, filters.year, filters.client_id, filters.subclient_id])

  useEffect(() => { load() }, [load])

  // Load cache stats on mount
  useEffect(() => {
    insuranceApi.cacheStats().then(r => setCacheStats(r.data)).catch(() => {})
  }, [])

  async function runSync() {
    setSyncing(true)
    try {
      const { data } = await insuranceApi.syncCache()
      if (data.status === 'ok') {
        const m = data.motalba?.upserted ?? 0
        const c = data.companiesitems?.upserted ?? 0
        alert(`تمت المزامنة بنجاح\nمطالبات: ${m} صف\nبيانات مرضى: ${c} صف`)
        const r = await insuranceApi.cacheStats()
        setCacheStats(r.data)
      } else {
        alert('فشلت المزامنة: ' + (data.error || 'خطأ غير متوقع'))
      }
    } catch (e) {
      alert('فشلت المزامنة: ' + (e?.response?.data?.error || e?.message || 'خطأ'))
    } finally { setSyncing(false) }
  }

  useEffect(() => {
    insuranceApi.clients({}).then(r => setClients(r.data.results || r.data))
    insuranceApi.subclients({}).then(r => {
      const list = r.data.results || r.data
      setSubclients(list)
    })
  }, [])

  // ── Client-side sub-filters (date range, search) ──────────────────────────
  const filteredClaims = useMemo(() => {
    let list = claims
    if (filters.search) {
      const q = filters.search.toLowerCase()
      list = list.filter(c =>
        c.claim_number?.toLowerCase().includes(q) ||
        c.client_name?.includes(filters.search) ||
        c.subclient_name?.includes(filters.search) ||
        c.softech_motalba_no?.includes(filters.search)
      )
    }
    if (filters.date_from) {
      list = list.filter(c => c.period_from >= filters.date_from)
    }
    if (filters.date_to) {
      list = list.filter(c => c.period_to <= filters.date_to)
    }
    return list
  }, [claims, filters.search, filters.date_from, filters.date_to])

  const filteredSubclients = useMemo(() =>
    subclients.filter(sc => !filters.client_id || String(sc.client_id) === String(filters.client_id)),
    [subclients, filters.client_id]
  )

  // ── Selection helpers ──────────────────────────────────────────────────────
  const toggleSelect = (id) =>
    setSelected(prev => {
      const s = new Set(prev)
      s.has(id) ? s.delete(id) : s.add(id)
      return s
    })

  const toggleAll = () =>
    setSelected(prev =>
      prev.size === filteredClaims.length
        ? new Set()
        : new Set(filteredClaims.map(c => c.id))
    )

  const allSelected = filteredClaims.length > 0 && selected.size === filteredClaims.length

  // ── KPIs ───────────────────────────────────────────────────────────────────
  const totalNet     = filteredClaims.reduce((s, c) => s + Number(c.final_net_after || 0), 0)
  const totalPaid    = filteredClaims.reduce((s, c) => s + Number(c.total_paid || 0), 0)
  const totalBalance = filteredClaims.reduce((s, c) => s + Number(c.balance || 0), 0)

  const years = Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - i)

  const inp = 'border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      {/* Page header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">مطالبات التأمين</h1>
            <p className="text-sm text-gray-500 mt-0.5">إدارة مطالبات التعاقدات والتأمين الصحي</p>
          </div>
          <div className="flex gap-2 items-center">
            {cacheStats && (
              <span className="text-xs text-gray-400 ml-1" title={
                `مطالبات: ${cacheStats.motalba?.rows || 0} صف\n` +
                `بيانات مرضى: ${cacheStats.companiesitems?.rows || 0} صف\n` +
                `آخر مزامنة: ${cacheStats.motalba?.last_synced ? new Date(cacheStats.motalba.last_synced).toLocaleString('en-GB') : 'لم تتم'}`
              }>
                💾 {(cacheStats.motalba?.rows || 0).toLocaleString('en-US')} / {(cacheStats.companiesitems?.rows || 0).toLocaleString('en-US')}
              </span>
            )}
            <Btn variant="secondary" onClick={runSync} size="sm" disabled={syncing}>
              {syncing ? '⏳ جارٍ المزامنة...' : '🔄 مزامنة بيانات سوفتك'}
            </Btn>
            <Btn variant="secondary" onClick={() => navigate('/insurance/clients')} size="sm">
              ⚙ إدارة العملاء والعقود
            </Btn>
            <Btn variant="secondary" onClick={() => navigate('/insurance/print-profiles')} size="sm">
              🖨 تخصيص الطباعة
            </Btn>
            <Btn variant="secondary" onClick={() => navigate('/insurance/item-overrides')} size="sm">
              🏷 تصويب تصنيف الأصناف
            </Btn>
            <Btn variant="secondary" onClick={() => setShowDiscover(true)} size="sm">
              🔍 استعراض من سوفتك
            </Btn>
            <Btn onClick={() => setShowImport(true)} size="sm">
              + استيراد مطالبة
            </Btn>
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-3 gap-4 px-6 py-4">
        {[
          { label: 'إجمالى المطالبات المعروضة', value: fmt(totalNet), sub: `${filteredClaims.length} مطالبة`, color: 'text-blue-700' },
          { label: 'المُحصَّل', value: fmt(totalPaid), color: 'text-green-700' },
          { label: 'الرصيد المتبقي', value: fmt(totalBalance), color: totalBalance > 0 ? 'text-amber-700' : 'text-gray-500' },
        ].map(kpi => (
          <div key={kpi.label} className="bg-white rounded-lg border border-gray-200 p-4">
            <p className="text-xs text-gray-500">{kpi.label}</p>
            <p className={`text-xl font-bold mt-1 ${kpi.color}`}>{kpi.value}</p>
            {kpi.sub && <p className="text-xs text-gray-400 mt-0.5">{kpi.sub}</p>}
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="px-6 pb-3 space-y-2">
        {/* Row 1: dropdowns */}
        <div className="flex gap-2 flex-wrap items-center">
          <select className={inp} value={filters.status} onChange={e => setF('status', e.target.value)}>
            <option value="">كل الحالات</option>
            {Object.entries(STATUS_CFG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>

          <select className={inp} value={filters.year} onChange={e => setF('year', e.target.value)}>
            <option value="">كل السنوات</option>
            {years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>

          <select className={inp} value={filters.client_id}
            onChange={e => { setF('client_id', e.target.value); setF('subclient_id', '') }}>
            <option value="">كل العملاء</option>
            {clients.map(c => <option key={c.id} value={c.id}>{c.name_short || c.name}</option>)}
          </select>

          <select className={inp} value={filters.subclient_id}
            onChange={e => setF('subclient_id', e.target.value)}>
            <option value="">كل الفئات</option>
            {filteredSubclients.map(sc => <option key={sc.id} value={sc.id}>{sc.name}</option>)}
          </select>

          <Btn variant="secondary" size="sm" onClick={load}>تحديث</Btn>

          {(filters.status || filters.year || filters.client_id || filters.subclient_id ||
            filters.date_from || filters.date_to || filters.search) && (
            <Btn variant="ghost" size="sm"
              onClick={() => setFilters({ status:'', year:'', client_id:'', subclient_id:'', date_from:'', date_to:'', search:'' })}>
              × مسح الفلاتر
            </Btn>
          )}
        </div>

        {/* Row 2: date range + search */}
        <div className="flex gap-2 flex-wrap items-center">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">من:</span>
            <input type="date" className={inp} value={filters.date_from}
              onChange={e => setF('date_from', e.target.value)} />
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">إلى:</span>
            <input type="date" className={inp} value={filters.date_to}
              onChange={e => setF('date_to', e.target.value)} />
          </div>
          <input className={`${inp} w-64`} placeholder="بحث: رقم مطالبة، عميل، رقم سوفتك..."
            value={filters.search} onChange={e => setF('search', e.target.value)} />
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="mx-6 mb-3 px-4 py-2.5 bg-blue-600 text-white rounded-lg flex items-center justify-between">
          <span className="text-sm font-medium">تم تحديد {selected.size} مطالبة</span>
          <div className="flex gap-2">
            <button onClick={() => setSelected(new Set())}
              className="text-xs text-blue-200 hover:text-white">إلغاء التحديد</button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="px-6 pb-8">
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="py-20 text-center text-gray-400">جارٍ التحميل...</div>
          ) : filteredClaims.length === 0 ? (
            <div className="py-20 text-center">
              <p className="text-gray-400 text-lg mb-3">لا توجد مطالبات</p>
              <div className="flex gap-3 justify-center">
                <Btn variant="secondary" onClick={() => setShowDiscover(true)}>
                  🔍 استعراض من سوفتك
                </Btn>
                <Btn onClick={() => setShowImport(true)}>+ استيراد مطالبة</Btn>
              </div>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="w-8 px-3 py-3">
                    <input type="checkbox" checked={allSelected} onChange={toggleAll} className="rounded" />
                  </th>
                  {['رقم المطالبة', 'العميل', 'الفئة', 'الفترة', 'الروشتات',
                    'الإجمالى', 'الخصم', 'الصافى', 'المُحصَّل', 'الرصيد', 'الحالة', ''].map(h => (
                    <th key={h} className="text-right px-3 py-3 text-xs font-semibold text-gray-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredClaims.map(claim => (
                  <tr key={claim.id}
                    className={`hover:bg-gray-50/70 cursor-pointer ${selected.has(claim.id) ? 'bg-blue-50' : ''}`}
                    onClick={() => navigate(`/insurance/claims/${claim.id}`)}>
                    <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={selected.has(claim.id)}
                        onChange={() => toggleSelect(claim.id)} className="rounded" />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="font-mono text-xs text-blue-700 font-semibold">{claim.claim_number}</div>
                      {claim.softech_motalba_no && (
                        <div className="text-xs text-gray-400">سوفتك #{claim.softech_motalba_no}</div>
                      )}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-gray-800">{claim.client_name}</td>
                    <td className="px-3 py-2.5 text-gray-600 text-xs">{claim.subclient_name}</td>
                    <td className="px-3 py-2.5 text-gray-500 text-xs whitespace-nowrap">
                      {claim.period_from} <span className="text-gray-300 mx-0.5">—</span> {claim.period_to}
                    </td>
                    <td className="px-3 py-2.5 text-center text-gray-700">{claim.final_rx_count}</td>
                    <td className="px-3 py-2.5 text-left font-mono text-gray-700 text-xs">{fmt(claim.final_gross_before)}</td>
                    <td className="px-3 py-2.5 text-left font-mono text-red-600 text-xs">{fmt(claim.final_total_discount)}</td>
                    <td className="px-3 py-2.5 text-left font-mono font-semibold text-gray-900 text-xs">{fmt(claim.final_net_after)}</td>
                    <td className="px-3 py-2.5 text-left font-mono text-green-700 text-xs">{fmt(claim.total_paid)}</td>
                    <td className="px-3 py-2.5 text-left font-mono text-amber-700 text-xs">{fmt(claim.balance)}</td>
                    <td className="px-3 py-2.5"><StatusBadge status={claim.status} /></td>
                    <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => navigate(`/insurance/claims/${claim.id}/print`)}
                        className="text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-0.5 whitespace-nowrap">
                        طباعة
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {filteredClaims.length > 0 && (
          <p className="text-xs text-gray-400 mt-2 text-left">
            {filteredClaims.length} مطالبة معروضة
            {filteredClaims.length !== claims.length && ` (من إجمالى ${claims.length})`}
          </p>
        )}
      </div>

      {/* Modals */}
      {showImport && (
        <ImportModal
          subclients={subclients}
          onClose={() => setShowImport(false)}
          onCreated={(claim) => { setShowImport(false); navigate(`/insurance/claims/${claim.id}`) }}
        />
      )}

      {showDiscover && (
        <DiscoverPanel
          clients={clients}
          subclients={subclients}
          onClose={() => setShowDiscover(false)}
          onImported={() => load()}
        />
      )}
    </div>
  )
}
