/**
 * NewReservationPage.jsx
 *
 * Full-page reservation creation form.
 * Accessed via: /reservations/new
 *
 * Changes vs. original:
 *  ✓ Customer chip: shows name (bold) + phone + PIC code badge
 *  ✓ Item search: uses shared ItemSearchWidget (barcode scanner compatible)
 *  ✓ Item selected card: shows name, itemcode, barcode, public price, stock qty
 *  ✓ All dropdowns (priority, order_source, fulfillment_method) loaded from
 *    /api/config/dropdowns/ — admin can add/edit/reorder options via settings
 *  ✓ Stock panel retained below item card
 */
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { reservationsApi, branchesApi, itemsApi, configApi } from '../api/client'
import useAuthStore from '../store/authStore'
import BranchSelect from '../components/BranchSelect'
import ItemSearchWidget from '../components/ItemSearchWidget'
import CustomerSearchWidget from '../components/CustomerSearchWidget'
import ChannelContactField from '../components/ChannelContactField'
import api from '../api/client'

// ── Stock panel ────────────────────────────────────────────────────────────────

function ItemStockPanel({ stocks, branchId }) {
  const [expanded, setExpanded] = useState(false)

  const branchEntry      = branchId ? stocks.find(s => s.branch === branchId) : null
  const networkTotal     = stocks.reduce((sum, s) => sum + (s.quantity_on_hand || 0), 0)
  const branchesWithStock = stocks.filter(s => s.quantity_on_hand > 0)

  const STATUS = {
    in_stock:     { icon: '✓', label: 'متوفر',        cls: 'border-green-200 bg-green-50 text-green-700' },
    low_stock:    { icon: '⚠', label: 'مخزون منخفض', cls: 'border-amber-200 bg-amber-50 text-amber-700' },
    out_of_stock: { icon: '✗', label: 'غير متوفر',    cls: 'border-red-200   bg-red-50   text-red-700'   },
  }

  if (!stocks || stocks.length === 0) {
    return (
      <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500 flex items-center gap-1.5">
        <span>📦</span><span>لا توجد بيانات مخزون — لم تتم المزامنة بعد.</span>
      </div>
    )
  }

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 space-y-1.5 text-xs" dir="rtl">
      {branchId ? (
        branchEntry ? (
          <div className={`flex items-center justify-between rounded-md px-2.5 py-1.5 border font-medium ${STATUS[branchEntry.stock_status]?.cls || 'border-gray-200 bg-white text-gray-700'}`}>
            <span className="flex items-center gap-1">
              <span>{STATUS[branchEntry.stock_status]?.icon}</span>
              <span>{STATUS[branchEntry.stock_status]?.label}</span>
              <span className="opacity-75 font-normal"> في هذا الفرع</span>
            </span>
            <span className="font-bold text-sm">{branchEntry.quantity_on_hand} وحدة</span>
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-md px-2.5 py-1.5 border border-red-200 bg-red-50 text-red-700 font-medium">
            <span>✗ غير موجود في مخزون هذا الفرع</span>
            <span className="font-bold">صفر</span>
          </div>
        )
      ) : (
        <div className="flex items-center justify-between text-gray-600">
          <span>إجمالي الشبكة</span>
          <span className="font-bold">{networkTotal} وحدة</span>
        </div>
      )}

      {branchesWithStock.length > 0 && (
        <button type="button" onClick={() => setExpanded(e => !e)}
          className="text-blue-500 hover:text-blue-700 text-xs font-medium">
          {expanded ? '▲ إخفاء كل الفروع' : `▼ عرض ${branchesWithStock.length} فروع بمخزون`}
        </button>
      )}

      {expanded && (
        <div className="space-y-1 pt-1 border-t border-gray-200">
          {stocks.map(s => (
            <div key={s.branch} className="flex items-center justify-between">
              <span className="text-gray-600">{s.branch_name_ar || s.branch_name}</span>
              <span className={`font-bold ${
                s.stock_status === 'in_stock' ? 'text-green-600' :
                s.stock_status === 'low_stock' ? 'text-amber-600' : 'text-red-500'
              }`}>{s.quantity_on_hand}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Extra line row — has its own stock fetch, mirrors primary item card ────────

function ExtraLineRow({ line, idx, branchId, onSelect, onClear, onUpdate, onRemove }) {
  // Fetch stock for this line's item whenever it changes
  const { data: stocks = [], isFetching: stockLoading } = useQuery({
    queryKey: ['extra-line-stock', line.item?.id],
    queryFn: () => api.get(`/items/${line.item.id}/stock/`).then(r => r.data),
    enabled: !!line.item?.id,
    staleTime: 60_000,
  })

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-3 space-y-2">

      {/* ── Item picker ── */}
      {line.item ? (
        /* Full selected-item card — identical to primary item */
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0 space-y-1">
            {/* Name */}
            <div className="font-bold text-sm text-gray-900 leading-snug">{line.item.name}</div>
            {line.item.name_scientific && (
              <div className="text-xs text-gray-500 italic">{line.item.name_scientific}</div>
            )}
            {/* Code + Barcode + Price + Stock badges */}
            <div className="flex flex-wrap items-center gap-1.5 mt-1">
              <span className="inline-flex items-center gap-1 text-[11px] font-mono font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">
                كود: {line.item.softech_id}
              </span>
              {(line.item.all_barcodes?.[0] || line.item.barcode) && (
                <span className="inline-flex items-center gap-1 text-[11px] font-mono text-gray-600 bg-gray-100 border border-gray-200 px-2 py-0.5 rounded">
                  {line.item.all_barcodes?.[0] || line.item.barcode}
                </span>
              )}
              {parseFloat(line.item.pack_price) > 0 && (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
                  💰 {parseFloat(line.item.pack_price).toFixed(2)} ج.م
                </span>
              )}
              {line.item.total_stock !== undefined && (
                <span className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded border ${
                  Number(line.item.total_stock) > 10 ? 'text-green-700 bg-green-50 border-green-200' :
                  Number(line.item.total_stock) > 0  ? 'text-amber-700 bg-amber-50 border-amber-200' :
                                                       'text-red-700 bg-red-50 border-red-200'
                }`}>
                  📦 {Number(line.item.total_stock) > 0 ? `${line.item.total_stock} وحدة` : 'نفد من المخزون'}
                </span>
              )}
            </div>
          </div>
          <button type="button" onClick={() => onClear(idx)}
            className="flex-shrink-0 text-xs text-gray-400 hover:text-red-500 transition-colors mt-0.5 font-medium">
            ✕ تغيير
          </button>
        </div>
      ) : line.manualMode ? (
        /* Manual text fallback */
        <div className="flex items-center gap-2">
          <input
            className="input-field flex-1 text-sm"
            placeholder="اسم الصنف يدوياً..."
            value={line.manual_item_name}
            onChange={e => onUpdate(idx, 'manual_item_name', e.target.value)}
            autoFocus
          />
          <button type="button" onClick={() => onUpdate(idx, 'manualMode', false)}
            className="text-xs text-brand-600 hover:underline shrink-0 whitespace-nowrap">🔍 بحث</button>
        </div>
      ) : (
        /* Catalog search */
        <div className="space-y-1">
          <ItemSearchWidget
            selected={null}
            onSelect={item => onSelect(idx, item)}
            onClear={() => {}}
            placeholder="ابحث في الكتالوج..."
          />
          <button type="button" onClick={() => onUpdate(idx, 'manualMode', true)}
            className="text-[11px] text-gray-400 hover:text-gray-600">✏️ اكتب الاسم يدوياً</button>
        </div>
      )}

      {/* ── Stock panel (branch-aware) — only when item selected ── */}
      {line.item && (
        stockLoading ? (
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border border-gray-300 border-t-brand-500" />
            جارٍ تحميل المخزون...
          </div>
        ) : stocks.length > 0 ? (
          <ItemStockPanel stocks={stocks} branchId={branchId} />
        ) : null
      )}

      {/* ── Qty + remove ── */}
      <div className="flex items-center gap-2 pt-1">
        <label className="text-xs text-gray-500 shrink-0">الكمية:</label>
        <input
          type="number" min="1"
          className="input-field w-20 text-sm"
          value={line.quantity_requested}
          onChange={e => onUpdate(idx, 'quantity_requested', Number(e.target.value))}
        />
        <div className="flex-1" />
        <button type="button" onClick={() => onRemove(idx)}
          className="text-xs text-gray-400 hover:text-red-500">🗑 حذف</button>
      </div>
    </div>
  )
}

// ── Dropdown select loaded from config API ─────────────────────────────────────

function ConfigSelect({ dropdownKey, options, value, onChange, placeholder = '— اختر —', className = '' }) {
  const active = options.filter(o => o.is_active)
  return (
    <select className={`input-field ${className}`} value={value} onChange={e => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {active.map(o => (
        <option key={o.value} value={o.value}>
          {o.icon ? `${o.icon} ` : ''}{o.label}
        </option>
      ))}
    </select>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function NewReservationPage() {
  const navigate    = useNavigate()
  const qc          = useQueryClient()
  const { user }    = useAuthStore()
  const isCCOrAdmin = user?.role === 'admin' || user?.role === 'call_center'
  const fileRef     = useRef()

  // ── Form state ──────────────────────────────────────────────────────────────
  const [form, setForm] = useState({
    customer:              '',
    item:                  '',
    manual_item_name:      '',
    branch:                user?.branch_id ? String(user.branch_id) : '',
    priority:              'normal',
    quantity_requested:    1,
    contact_phone:         '',
    contact_name:          '',
    channel:               '',
    contract_subtype:      '',
    notes:                 '',
    follow_up_date:        '',
    expected_arrival_date: '',
    order_source:          '',
    fulfillment_method:    '',
  })
  const upd = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const [selectedCustomer, setSelectedCustomer] = useState(null)
  const [selectedItem, setSelectedItem]         = useState(null)   // full item object
  const [selectedItemStock, setSelectedItemStock] = useState(null)
  const [stockLoading, setStockLoading]         = useState(false)
  const [image, setImage]     = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]     = useState('')
  // Extra item lines (basket)
  const [extraLines, setExtraLines] = useState([])
  // Duplicate detection
  const [duplicateData, setDuplicateData] = useState(null)

  // ── Branches ────────────────────────────────────────────────────────────────
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
  })

  // ── Dropdown options from config API ─────────────────────────────────────────
  const { data: allDropdowns = {} } = useQuery({
    queryKey: ['config-dropdowns-grouped'],
    queryFn: () => configApi.groupedDropdowns().then(r => r.data),
    staleTime: 5 * 60_000,   // cache 5 min — admin changes are rare
  })
  const priorityOptions         = allDropdowns['reservation_priority']        || []
  const orderSourceOptions      = allDropdowns['reservation_order_source']    || []
  const fulfillmentOptions      = allDropdowns['reservation_fulfillment_method'] || []

  // Fallbacks for empty DB (first run before seed_config):
  const PRIORITY_FALLBACK = [
    { value: 'normal',  label: 'عادي',      icon: '⚪', is_active: true },
    { value: 'urgent',  label: 'عاجل',      icon: '🔴', is_active: true },
    { value: 'chronic', label: 'مريض مزمن', icon: '💊', is_active: true },
  ]
  const ORDER_SOURCE_FALLBACK = [
    { value: 'cc_whatsapp',     label: 'كول سنتر — واتساب', icon: '💬', is_active: true },
    { value: 'cc_call',         label: 'كول سنتر — مكالمة', icon: '📞', is_active: true },
    { value: 'branch_whatsapp', label: 'الفرع — واتساب',    icon: '🏪', is_active: true },
    { value: 'branch_call',     label: 'الفرع — مكالمة',    icon: '☎️', is_active: true },
    { value: 'online',          label: 'طلب إلكتروني',       icon: '🌐', is_active: true },
  ]
  const FULFILLMENT_FALLBACK = [
    { value: 'pickup',   label: 'استلام من الفرع', icon: '🏪', is_active: true },
    { value: 'delivery', label: 'توصيل للمنزل',   icon: '🚚', is_active: true },
  ]

  const resolvedPriority     = priorityOptions.length     ? priorityOptions     : PRIORITY_FALLBACK
  const resolvedOrderSource  = orderSourceOptions.length  ? orderSourceOptions  : ORDER_SOURCE_FALLBACK
  const resolvedFulfillment  = fulfillmentOptions.length  ? fulfillmentOptions  : FULFILLMENT_FALLBACK

  // ── Stock fetch when item is selected ─────────────────────────────────────────
  useEffect(() => {
    if (!form.item) { setSelectedItemStock(null); return }
    setStockLoading(true)
    itemsApi.stock(form.item)
      .then(res => setSelectedItemStock(res.data))
      .catch(() => setSelectedItemStock([]))
      .finally(() => setStockLoading(false))
  }, [form.item])

  // ── Handlers ─────────────────────────────────────────────────────────────────

  function handleCustomerSelect(c) {
    setSelectedCustomer(c)
    if (!c) {
      setForm(f => ({ ...f, customer: '' }))
      return
    }
    setForm(f => ({
      ...f,
      customer:      c.id || '',
      contact_name:  c.name,
      contact_phone: c.phone || f.contact_phone,
    }))
  }

  function handleItemSelect(item) {
    setSelectedItem(item)
    setForm(f => ({ ...f, item: item.id, manual_item_name: '' }))
  }

  function handleItemClear() {
    setSelectedItem(null)
    setSelectedItemStock(null)
    setForm(f => ({ ...f, item: '', manual_item_name: '' }))
  }

  // ── Submit ───────────────────────────────────────────────────────────────────
  const handleSubmit = async (force = false) => {
    if (!form.item && !form.manual_item_name.trim()) {
      setError('يرجى تحديد صنف من نتائج البحث أو إدخال اسمه يدوياً'); return
    }
    if (!form.branch || !form.contact_phone || !form.contact_name) {
      setError('يرجى تعبئة: الفرع، اسم التواصل، ورقم الهاتف'); return
    }
    setSubmitting(true); setError('')
    try {
      const fd = new FormData()
      Object.entries(form).forEach(([k, v]) => {
        if (v !== '') fd.append(k, v)
      })
      if (image) fd.append('image', image)
      const api = await import('../api/client').then(m => m.default)
      const url = force ? '/reservations/?force=true' : '/reservations/'
      const res = await api.post(url, fd, { headers: { 'Content-Type': 'multipart/form-data' } })

      // After creating header, bulk-create extra lines
      if (extraLines.length > 0 && res.data.id) {
        const linesApi = await import('../api/client').then(m => m.reservationsApi)
        for (const line of extraLines) {
          try {
            // Send item FK if selected from catalog, else fall back to manual name
            const payload = {
              quantity_requested: line.quantity_requested,
              ...(line.item ? { item: line.item.id } : { manual_item_name: line.manual_item_name }),
            }
            if (payload.item || payload.manual_item_name?.trim()) {
              await linesApi.addLine(res.data.id, payload)
            }
          } catch { /* non-fatal */ }
        }
      }

      qc.invalidateQueries(['reservations-kanban'])
      navigate(`/reservations/${res.data.id}`)
    } catch (e) {
      if (e.response?.status === 409 && e.response?.data?.duplicate) {
        // Duplicate found — show warning modal
        setDuplicateData(e.response.data)
        setSubmitting(false)
        return
      }
      const errData = e.response?.data
      let errMsg = 'حدث خطأ، يرجى المحاولة مجدداً'
      if (errData) {
        if (typeof errData === 'string') {
          errMsg = errData
        } else if (errData.detail) {
          errMsg = errData.detail
        } else {
          // DRF field errors: { field: ["msg", ...], ... }
          const parts = Object.entries(errData).map(([field, msgs]) => {
            const msgStr = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
            return `${field}: ${msgStr}`
          })
          if (parts.length) errMsg = parts.join(' | ')
        }
      }
      console.error('[NewReservation] 400 body:', errData)
      setError(errMsg)
      setSubmitting(false)
    }
  }

  // ── Extra lines helpers ───────────────────────────────────────────────────────
  function addExtraLine() {
    // item: catalog FK | null, manualMode: fallback text entry
    setExtraLines(prev => [...prev, { item: null, manual_item_name: '', quantity_requested: 1, manualMode: false }])
  }
  function updateExtraLine(idx, field, value) {
    setExtraLines(prev => prev.map((l, i) => i === idx ? { ...l, [field]: value } : l))
  }
  function removeExtraLine(idx) {
    setExtraLines(prev => prev.filter((_, i) => i !== idx))
  }
  function selectExtraLineItem(idx, item) {
    setExtraLines(prev => prev.map((l, i) =>
      i === idx ? { ...l, item, manual_item_name: '', manualMode: false } : l
    ))
  }
  function clearExtraLineItem(idx) {
    setExtraLines(prev => prev.map((l, i) =>
      i === idx ? { ...l, item: null, manual_item_name: '', manualMode: false } : l
    ))
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Duplicate warning modal */}
      {duplicateData && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full mx-4 p-6" dir="rtl">
            <div className="text-2xl text-center mb-2">⚠️</div>
            <h3 className="font-bold text-gray-800 text-base mb-2 text-center">حجز مكرر محتمل</h3>
            <p className="text-sm text-gray-600 mb-4 text-center">{duplicateData.detail}</p>
            <div className="mb-4 space-y-1.5">
              {duplicateData.duplicates?.map(d => (
                <a
                  key={d.id}
                  href={`/reservations/${d.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between px-3 py-2 rounded-xl bg-amber-50 border border-amber-200 text-sm text-amber-800 hover:bg-amber-100 transition-colors"
                >
                  <span>حجز #{d.id}</span>
                  <span className="text-xs font-semibold">{d.status_label}</span>
                </a>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setDuplicateData(null)}
                className="btn-secondary flex-1 text-sm"
              >
                إلغاء
              </button>
              <button
                onClick={() => { setDuplicateData(null); handleSubmit(true) }}
                className="btn-primary flex-1 text-sm"
              >
                إنشاء على أي حال
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Page header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-10">
        <div className="flex items-center gap-3 max-w-2xl mx-auto">
          <button
            onClick={() => navigate('/reservations')}
            className="w-9 h-9 flex items-center justify-center rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors text-lg"
          >←</button>
          <div>
            <h1 className="text-lg font-bold text-gray-900">حجز جديد</h1>
            <p className="text-xs text-gray-400">أدخل تفاصيل طلب الحجز</p>
          </div>
        </div>
      </div>

      {/* Form body */}
      <div className="max-w-2xl mx-auto px-6 py-6 space-y-5">

        {/* ── Customer section ─────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <span className="text-brand-600">👤</span> العميل
            <span className="text-xs text-gray-400 font-normal">(اختياري)</span>
          </h2>
          <CustomerSearchWidget
            selected={selectedCustomer}
            onSelect={handleCustomerSelect}
            allowManual={false}
          />
        </div>

        {/* ── Item search ─────────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <span className="text-brand-600">💊</span> الصنف *
          </h2>

          <ItemSearchWidget
            selected={selectedItem}
            onSelect={handleItemSelect}
            onClear={handleItemClear}
            placeholder="ابحث باسم الصنف أو الكود أو الباركود (بالماسح الضوئي أو يدوياً)..."
          />

          {/* Item not found → manual entry */}
          {!selectedItem && !form.item && (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm space-y-2">
              <div className="flex items-start gap-2">
                <span className="text-amber-500 mt-0.5 flex-shrink-0">⚠</span>
                <div>
                  <div className="font-semibold text-amber-800 text-sm">الصنف غير موجود في SOFTECH؟</div>
                  <div className="text-xs text-amber-700 mt-0.5">
                    يمكنك تسجيل الحجز بإدخال الاسم يدوياً — سيظهر كـ «صنف غير مكوَّد».
                  </div>
                </div>
              </div>
              <input
                className="input-field w-full border-amber-300 text-sm"
                placeholder="اكتب اسم الصنف يدوياً..."
                value={form.manual_item_name}
                onChange={e => upd('manual_item_name', e.target.value)}
              />
              {form.manual_item_name.trim() && (
                <div className="text-xs text-amber-700">
                  ✓ سيُحجز باسم: <strong className="text-gray-800">{form.manual_item_name}</strong>
                </div>
              )}
            </div>
          )}

          {/* Stock panel (branch-aware) */}
          {selectedItem && (
            stockLoading ? (
              <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-400">
                <span className="inline-block h-3 w-3 animate-spin rounded-full border border-gray-300 border-t-brand-500" />
                جارٍ تحميل بيانات المخزون...
              </div>
            ) : selectedItemStock !== null && (
              <ItemStockPanel
                stocks={selectedItemStock}
                branchId={form.branch ? parseInt(form.branch, 10) : null}
              />
            )
          )}

          {/* Quantity — shown as soon as an item (or manual name) is entered */}
          {(selectedItem || form.manual_item_name.trim()) && (
            <div className="mt-3 flex items-center gap-3">
              <label className="text-sm font-medium text-gray-700 shrink-0">الكمية المطلوبة:</label>
              <input
                type="number" min="1"
                className="input-field w-24 text-sm"
                value={form.quantity_requested}
                onChange={e => upd('quantity_requested', e.target.value)}
              />
            </div>
          )}
        </div>

        {/* ── Extra lines (basket) ──────────────────────────────────────────── */}
        {(form.item || form.manual_item_name.trim()) && (
          <div className="bg-white rounded-2xl border border-gray-200 p-5">
            <h2 className="font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <span className="text-brand-600">📦</span> أصناف إضافية
              <span className="text-xs text-gray-400 font-normal">(اختياري — لإضافة أكثر من صنف)</span>
            </h2>

            {extraLines.length > 0 && (
              <div className="space-y-3 mb-3">
                {extraLines.map((line, idx) => (
                  <ExtraLineRow
                    key={idx}
                    line={line}
                    idx={idx}
                    branchId={form.branch ? parseInt(form.branch, 10) : null}
                    onSelect={selectExtraLineItem}
                    onClear={clearExtraLineItem}
                    onUpdate={updateExtraLine}
                    onRemove={removeExtraLine}
                  />
                ))}
              </div>
            )}

            <button
              type="button"
              onClick={addExtraLine}
              className="text-sm text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
            >
              <span className="text-lg leading-none">+</span> إضافة صنف آخر
            </button>
          </div>
        )}

        {/* ── Core details ──────────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
          <h2 className="font-semibold text-gray-700 flex items-center gap-2">
            <span className="text-brand-600">📋</span> تفاصيل الحجز
          </h2>

          {/* Branch */}
          {isCCOrAdmin ? (
            <div>
              <label className="label">الفرع *</label>
              <BranchSelect
                value={form.branch}
                onChange={v => upd('branch', v)}
                branches={branches}
                placeholder="اختر الفرع..."
                className="w-full"
              />
            </div>
          ) : (
            <div>
              <label className="label">الفرع</label>
              <div className="input-field bg-gray-50 text-gray-600 cursor-not-allowed">
                {branches.find(b => String(b.id) === String(form.branch))?.name_ar || 'فرعك الحالي'}
              </div>
            </div>
          )}

          {/* ── قناة الطلب — Softech POS-aligned 2-level selector ── */}
          <div className="space-y-2">
            <label className="label">قناة الطلب (نوع POS)</label>

            {/* Level 1 — POS type */}
            <div className="grid grid-cols-3 gap-2">
              {[
                { value: 'cash_sales',     icon: '💵', label: 'بيع نقدي', sub: 'كاش (F2)' },
                { value: 'home_delivery',  icon: '🚚', label: 'توصيل',    sub: 'Home Delivery (F3)' },
                { value: 'contract_sales', icon: '📋', label: 'كنتراكت',  sub: 'Contract Sales (F4)' },
              ].map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    upd('channel', opt.value)
                    // clear sub-channel when switching POS type
                    if (opt.value !== 'contract_sales') upd('contract_subtype', '')
                  }}
                  className={`flex flex-col items-center justify-center gap-0.5 px-2 py-2.5 rounded-xl border-2 text-xs font-semibold transition-all ${
                    form.channel === opt.value
                      ? 'border-brand-500 bg-brand-50 text-brand-700'
                      : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <span className="text-xl leading-none">{opt.icon}</span>
                  <span>{opt.label}</span>
                  <span className={`text-[10px] font-normal ${form.channel === opt.value ? 'text-brand-500' : 'text-gray-400'}`}>{opt.sub}</span>
                </button>
              ))}
            </div>

            {/* Level 2 — Contract sub-channel (only when contract_sales selected) */}
            {form.channel === 'contract_sales' && (
              <div className="bg-gray-50 border border-gray-200 rounded-xl p-3 space-y-1.5">
                <p className="text-[11px] font-semibold text-gray-500 mb-2">نوع العميل / القناة</p>
                <div className="grid grid-cols-2 gap-1.5">
                  {[
                    { value: 'taakodat',         label: 'تعاقدات / آجل',                    icon: '📄' },
                    { value: 'loyal_customer',   label: 'عميل دائم',                        icon: '⭐' },
                    { value: 'health_insurance', label: 'تأمين صحي',                        icon: '🏥' },
                    { value: 'compensation',     label: 'تعويضات الشركات',                  icon: '🏢' },
                    { value: 'electronic',       label: 'إيصال إلكتروني بالبطاقة الشخصية', icon: '💳' },
                    { value: 'vip',              label: 'Vip',                              icon: '👑' },
                    { value: 'camac',            label: 'تعاقد - سداد أجل - خصم يدوى',    icon: '🏦' },
                    { value: 'clearing',         label: 'مقاصات',                           icon: '🔄' },
                    { value: 'donation',         label: 'تبرعات',                           icon: '🎁' },
                    { value: 'internal',         label: 'موظفين شركة الرزيقى',              icon: '🏠' },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => upd('contract_subtype', opt.value)}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs text-right transition-all ${
                        form.contract_subtype === opt.value
                          ? 'border-brand-400 bg-brand-50 text-brand-700 font-semibold'
                          : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      <span className="text-base leading-none flex-shrink-0">{opt.icon}</span>
                      <span className="leading-tight">{opt.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Contact */}
          <div className="grid grid-cols-2 gap-4">
            <ChannelContactField
              channel={form.channel}
              contractSubtype={form.contract_subtype}
              value={form.contact_name}
              onChange={v => upd('contact_name', v)}
              required
            />
            <div>
              <label className="label">هاتف التواصل *</label>
              <input className="input-field" dir="ltr" value={form.contact_phone}
                onChange={e => upd('contact_phone', e.target.value)} />
            </div>
          </div>

          {/* Priority */}
          <div>
            <label className="label flex items-center justify-between">
              <span>الأولوية</span>
              <a href="/settings/dropdowns?key=reservation_priority"
                className="text-[10px] text-gray-400 hover:text-brand-500 transition-colors"
                title="إدارة الخيارات" target="_blank" rel="noreferrer">
                ⚙ تخصيص
              </a>
            </label>
            <ConfigSelect
              dropdownKey="reservation_priority"
              options={resolvedPriority}
              value={form.priority}
              onChange={v => upd('priority', v)}
              placeholder="— اختر الأولوية —"
            />
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">تاريخ المتابعة</label>
              <input type="date" className="input-field" value={form.follow_up_date}
                onChange={e => upd('follow_up_date', e.target.value)} />
            </div>
            <div>
              <label className="label">موعد الوصول المتوقع</label>
              <input type="date" className="input-field" value={form.expected_arrival_date}
                onChange={e => upd('expected_arrival_date', e.target.value)} />
            </div>
          </div>

          {/* Order source + Fulfillment — from config API */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label flex items-center justify-between">
                <span>مصدر الطلب</span>
                <a href="/settings/dropdowns?key=reservation_order_source"
                  className="text-[10px] text-gray-400 hover:text-brand-500 transition-colors"
                  target="_blank" rel="noreferrer">⚙ تخصيص</a>
              </label>
              <ConfigSelect
                dropdownKey="reservation_order_source"
                options={resolvedOrderSource}
                value={form.order_source}
                onChange={v => upd('order_source', v)}
              />
            </div>
            <div>
              <label className="label flex items-center justify-between">
                <span>طريقة التسليم</span>
                <a href="/settings/dropdowns?key=reservation_fulfillment_method"
                  className="text-[10px] text-gray-400 hover:text-brand-500 transition-colors"
                  target="_blank" rel="noreferrer">⚙ تخصيص</a>
              </label>
              <ConfigSelect
                dropdownKey="reservation_fulfillment_method"
                options={resolvedFulfillment}
                value={form.fulfillment_method}
                onChange={v => upd('fulfillment_method', v)}
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="label">ملاحظات</label>
            <textarea rows={3} className="input-field resize-none" value={form.notes}
              onChange={e => upd('notes', e.target.value)}
              placeholder="أي تفاصيل إضافية..." />
          </div>

          {/* Image upload */}
          <div>
            <input type="file" accept="image/*" ref={fileRef} className="hidden"
              onChange={e => setImage(e.target.files[0])} />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex items-center gap-2 text-sm text-blue-600 border border-blue-200 px-4 py-2 rounded-xl hover:bg-blue-50 transition-colors"
            >
              <span>📎</span>
              {image ? `✓ ${image.name}` : 'إرفاق صورة / روشتة (اختياري)'}
            </button>
            {image && (
              <button className="text-xs text-red-400 mt-1 hover:text-red-600"
                onClick={() => setImage(null)}>
                ✕ إزالة الصورة
              </button>
            )}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-2xl px-5 py-3">
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pb-8">
          <button onClick={() => navigate('/reservations')} className="btn-secondary px-6">
            إلغاء
          </button>
          <button
            onClick={() => handleSubmit(false)}
            disabled={submitting}
            className="btn-primary flex-1 disabled:opacity-50 py-3 text-base"
          >
            {submitting ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                جارٍ الحفظ...
              </span>
            ) : `✅ إنشاء الحجز${extraLines.length > 0 ? ` (${extraLines.length + 1} أصناف)` : ''}`}
          </button>
        </div>

      </div>
    </div>
  )
}
