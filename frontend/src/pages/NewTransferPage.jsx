/**
 * pages/NewTransferPage.jsx
 * Full-page form for creating a new stock transfer request.
 * Extracted from TransfersPage.jsx / CreateRequestModal.
 *
 * Uses shared ItemSearchWidget for barcode-scanner-compatible item search.
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { transfersApi, branchesApi, itemsApi } from '../api/client'
import useAuthStore from '../store/authStore'
import BranchSelect from '../components/BranchSelect'
import ItemSearchWidget from '../components/ItemSearchWidget'

// ── Page ──────────────────────────────────────────────────────────────────────

export default function NewTransferPage() {
  const navigate     = useNavigate()
  const qc           = useQueryClient()
  const { user }     = useAuthStore()
  const userBranchId = user?.branch_id

  const [sourceBranch,      setSourceBranch]      = useState(String(userBranchId || ''))
  const [destinationBranch, setDestinationBranch] = useState('')
  const [notes,             setNotes]             = useState('')
  const [items,             setItems]             = useState([])
  const [itemStocks,        setItemStocks]        = useState({})
  const [submitAndSend,     setSubmitAndSend]     = useState(false)
  const [submitting,        setSubmitting]        = useState(false)
  const [error,             setError]             = useState('')

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  // Pre-fetch stock whenever items change
  useEffect(() => {
    if (items.length === 0) return
    items.forEach(row => {
      if (itemStocks[row.item.id]) return
      itemsApi.stock(row.item.id)
        .then(res => setItemStocks(prev => ({ ...prev, [row.item.id]: res.data || [] })))
        .catch(() => {})
    })
  }, [items]) // eslint-disable-line react-hooks/exhaustive-deps

  function addItem(item) {
    if (items.find(i => i.item.id === item.id)) return
    setItems(prev => [...prev, { item, qty: '', notes: '' }])
    itemsApi.stock(item.id)
      .then(res => setItemStocks(prev => ({ ...prev, [item.id]: res.data || [] })))
      .catch(() => {})
  }
  function updateItem(idx, field, value) {
    setItems(prev => prev.map((row, i) => i === idx ? { ...row, [field]: value } : row))
  }
  function removeItem(idx) { setItems(prev => prev.filter((_, i) => i !== idx)) }

  async function handleSubmit() {
    if (!sourceBranch)      { setError('اختر الفرع الطالب'); return }
    if (!destinationBranch) { setError('اختر الفرع المصدر'); return }
    if (sourceBranch === destinationBranch) { setError('الفرعان لا يمكن أن يكونا نفس الفرع'); return }
    if (items.length === 0) { setError('أضف صنفاً واحداً على الأقل'); return }
    const bad = items.find(i => !i.qty || Number(i.qty) <= 0)
    if (bad) { setError(`أدخل الكمية لـ: ${bad.item.name}`); return }

    setSubmitting(true); setError('')
    try {
      const payload = {
        requesting_branch: Number(sourceBranch),
        supplying_branch:  Number(destinationBranch),
        notes,
        items: items.map(i => ({ item: i.item.id, quantity: i.qty, notes: i.notes || '' })),
      }
      const res = await transfersApi.create(payload)
      const newId = res.data.id
      if (submitAndSend) await transfersApi.submit(newId)
      qc.invalidateQueries(['transfers'])

      if (submitAndSend) {
        navigate(`/transfers/${newId}`)
      } else {
        navigate('/transfers', { state: { savedToast: 'تم حفظ الطلب كمسودة بنجاح' } })
      }
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' — ') : 'حدث خطأ')
    } finally { setSubmitting(false) }
  }

  const stockColor = qty =>
    qty >= 5  ? 'bg-green-100 text-green-700 ring-green-300'
    : qty > 0 ? 'bg-amber-100 text-amber-700 ring-amber-300'
    :           'bg-red-100 text-red-600 ring-red-300'

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Page header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/transfers')}
            className="text-gray-400 hover:text-gray-700 transition-colors text-sm font-medium flex items-center gap-1"
          >
            ← رجوع
          </button>
          <div className="w-px h-5 bg-gray-200" />
          <div>
            <h1 className="text-lg font-black text-gray-900">طلب تحويل مخزون جديد</h1>
            <p className="text-xs text-gray-400 mt-0.5">يمكنك إضافة عدة أصناف · الطلب لا يؤثر على المخزون حتى اعتماده</p>
          </div>
        </div>
      </div>

      {/* Form body */}
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">

        {/* Branches */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
          <h2 className="text-sm font-bold text-gray-700 mb-4">الفروع</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">الفرع الطالب *</label>
              <BranchSelect
                value={sourceBranch}
                onChange={setSourceBranch}
                branches={branches.filter(b => String(b.id) !== destinationBranch)}
                placeholder="اختر الفرع الطالب..."
              />
            </div>
            <div>
              <label className="label">الفرع المصدر (يمتلك المخزون) *</label>
              <BranchSelect
                value={destinationBranch}
                onChange={setDestinationBranch}
                branches={branches.filter(b => String(b.id) !== sourceBranch)}
                placeholder="اختر الفرع المصدر..."
              />
            </div>
          </div>
        </div>

        {/* Items */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
          <h2 className="text-sm font-bold text-gray-700 mb-4">الأصناف المطلوبة</h2>

          {/* Shared ItemSearchWidget — barcode scanner compatible */}
          <ItemSearchWidget
            selected={null}
            onSelect={addItem}
            placeholder="ابحث باسم الصنف أو الكود أو الباركود (ماسح ضوئي متوافق)..."
          />

          {items.length === 0 ? (
            <div className="border-2 border-dashed border-gray-200 rounded-xl py-8 text-center mt-4">
              <div className="text-3xl mb-2">💊</div>
              <div className="text-sm text-gray-400">ابحث عن صنف أعلاه لإضافته</div>
            </div>
          ) : (
            <div className="space-y-2 mt-4">
              <div className="text-xs font-bold text-gray-500 mb-2">الأصناف المضافة ({items.length})</div>
              {items.map((row, idx) => {
                const allBranches   = itemStocks[row.item.id]
                const destId        = Number(destinationBranch)
                const supplyRow     = allBranches?.find(b => b.branch === destId)
                const otherBranches = allBranches?.filter(b => b.branch !== destId && b.quantity_on_hand > 0) || []
                const primaryBarcode = row.item.all_barcodes?.[0] || row.item.barcode || ''
                return (
                  <div key={row.item.id} className="bg-brand-50 border border-brand-100 rounded-xl px-3 pt-2.5 pb-2">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-gray-800 text-sm break-words">{row.item.name}</div>
                        <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                          <span className="text-[11px] text-brand-600 font-mono font-bold">
                            كود: {row.item.softech_id}
                          </span>
                          {primaryBarcode && (
                            <span className="text-[10px] font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                              📦 {primaryBarcode}
                            </span>
                          )}
                          {row.item.pack_price > 0 && (
                            <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                              💰 {Number(row.item.pack_price).toFixed(2)} ج.م
                            </span>
                          )}
                          {row.item.total_stock !== undefined && (
                            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                              row.item.total_stock > 10 ? 'text-green-600 bg-green-50' :
                              row.item.total_stock > 0  ? 'text-amber-600 bg-amber-50' :
                                                          'text-red-500 bg-red-50'
                            }`}>
                              {row.item.total_stock > 0 ? `${row.item.total_stock} وحدة` : 'نفد'}
                            </span>
                          )}
                        </div>
                      </div>
                      <input type="number" min="0.001" step="0.001" placeholder="الكمية"
                        value={row.qty} onChange={e => updateItem(idx, 'qty', e.target.value)}
                        className="w-24 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:border-brand-400" />
                      <input placeholder="ملاحظة"
                        value={row.notes} onChange={e => updateItem(idx, 'notes', e.target.value)}
                        className="w-28 border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand-400" />
                      <button onClick={() => removeItem(idx)} className="text-gray-300 hover:text-red-400 text-xl leading-none flex-shrink-0">✕</button>
                    </div>

                    {/* Stock badges */}
                    {!allBranches ? (
                      <div className="mt-2 flex gap-1.5">
                        {[1,2,3].map(i => <div key={i} className="h-5 w-20 bg-gray-200 rounded animate-pulse" />)}
                      </div>
                    ) : (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        {destinationBranch && (
                          <>
                            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ring-2 ${stockColor(supplyRow?.quantity_on_hand ?? 0)}`}>
                              <span>🏭</span>
                              <span>{supplyRow ? (supplyRow.branch_name_ar || supplyRow.branch_name) : (branches.find(b => b.id === destId)?.name_ar || 'الفرع المصدر')}</span>
                              <span className="font-black text-sm">{supplyRow?.quantity_on_hand ?? 0}</span>
                            </div>
                            {otherBranches.length > 0 && <span className="text-gray-300 text-xs">|</span>}
                          </>
                        )}
                        {otherBranches.map(b => (
                          <div key={b.branch} className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ring-1 ${stockColor(b.quantity_on_hand)}`}>
                            <span>{b.branch_name_ar || b.branch_name}</span>
                            <span className="font-bold">{b.quantity_on_hand}</span>
                          </div>
                        ))}
                        {!destinationBranch && allBranches.filter(b => b.quantity_on_hand > 0).map(b => (
                          <div key={b.branch} className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ring-1 ${stockColor(b.quantity_on_hand)}`}>
                            <span>{b.branch_name_ar || b.branch_name}</span>
                            <span className="font-bold">{b.quantity_on_hand}</span>
                          </div>
                        ))}
                        {allBranches.every(b => b.quantity_on_hand <= 0) && (
                          <span className="text-[11px] text-red-400 font-medium">لا يوجد مخزون في أي فرع</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Notes */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
          <h2 className="text-sm font-bold text-gray-700 mb-3">ملاحظات عامة (اختياري)</h2>
          <textarea rows={3} className="input-field resize-none text-sm"
            placeholder="سبب الطلب، أولوية، تفاصيل إضافية..."
            value={notes} onChange={e => setNotes(e.target.value)} />
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">{error}</div>
        )}

        {/* Submit bar */}
        <div className="flex items-center gap-4 pb-8">
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
            <input type="checkbox" checked={submitAndSend}
              onChange={e => setSubmitAndSend(e.target.checked)} className="rounded" />
            حفظ وتقديم الطلب مباشرةً
          </label>
          <div className="flex-1" />
          <button
            onClick={() => navigate('/transfers')}
            className="btn-secondary text-sm px-5"
          >
            إلغاء
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || items.length === 0}
            className="btn-primary text-sm disabled:opacity-50 px-6"
          >
            {submitting ? 'جارٍ...' : submitAndSend ? '📤 حفظ وتقديم' : '💾 حفظ كمسودة'}
          </button>
        </div>

      </div>
    </div>
  )
}
