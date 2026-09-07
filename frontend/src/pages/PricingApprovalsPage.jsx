/**
 * PricingApprovalsPage.jsx
 *
 * Approval workflow for item pricing and discount changes.
 *
 * Key rules:
 *   - pack_price (itemsaleprice) is the master price field
 *   - unit_price (unitsaleprice) = pack_price / packqty  — auto-derived, never editable
 *   - pack_price_tax (itemsaleprice_tax) = pack_price × (1 + tax%)  — auto-derived
 *   - Discount fields (pharmacydiscp, additionaldiscp, specialdiscp, posdiscp) are independent
 *   - On approval: the approver's own Softech usercode is stamped on items.usercode
 *     so the change appears in Softech exactly as if that admin performed it manually
 *
 * Roles:
 *   - Any authenticated user: create requests, view own
 *   - admin: view all, approve / reject
 */
import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../api/client'
import ItemSearchWidget from '../components/ItemSearchWidget'
import ReplicationAuditPanel from './pricing/ReplicationAuditPanel'
import SlaPanel from './pricing/SlaPanel'
import ReplicationBadge from './pricing/ReplicationBadge'
import ImportModal from './pricing/ImportModal'
import InsightsPanel from './pricing/InsightsPanel'
import PriceHistoryModal from './pricing/PriceHistoryModal'
import useAuthStore from '../store/authStore'

// ── Field config ──────────────────────────────────────────────────────────────

// User-editable fields (matches USER_EDITABLE_FIELDS in backend models.py)
const EDITABLE_FIELDS = [
  { key: 'pack_price',       label: 'سعر العبوة (بدون ضريبة)', unit: 'جنيه', group: 'price' },
  { key: 'pharmacy_discp',   label: 'خصم الصيدلية',            unit: '%',    group: 'disc'  },
  { key: 'additional_discp', label: 'خصم إضافي',               unit: '%',    group: 'disc'  },
  { key: 'special_discp',    label: 'خصم خاص',                 unit: '%',    group: 'disc'  },
  { key: 'pos_discp',        label: 'خصم POS',                 unit: '%',    group: 'disc'  },
]

// Auto-derived fields — shown in form as computed-only, never submitted in new_values
const DERIVED_FIELDS = [
  { key: 'unit_price',     label: 'سعر الوحدة (محسوب)', unit: 'جنيه', derivedFrom: 'pack_price / عدد الوحدات' },
  { key: 'pack_price_tax', label: 'السعر شامل الضريبة (محسوب)', unit: 'جنيه', derivedFrom: 'pack_price × (1 + ضريبة%)' },
]

const STATUS_STYLES = {
  pending:  'bg-amber-100 text-amber-800 border border-amber-200',
  approved: 'bg-blue-100 text-blue-800 border border-blue-200',
  rejected: 'bg-red-100 text-red-700 border border-red-200',
  executed: 'bg-emerald-100 text-emerald-800 border border-emerald-200',
  failed:   'bg-rose-100 text-rose-800 border border-rose-200',
}

const STATUS_LABELS = {
  pending:  'في الانتظار',
  approved: 'معتمد',
  rejected: 'مرفوض',
  executed: 'منفذ في Softech',
  failed:   'فشل',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(val, dec = 2) {
  const n = parseFloat(val)
  return isNaN(n) ? (val || '—') : n.toFixed(dec)
}

function StatusBadge({ status }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[status] || 'bg-gray-100 text-gray-600'}`}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}

function ChangeSummary({ oldValues, newValues, executedValues }) {
  const display = executedValues && Object.keys(executedValues).length ? executedValues : newValues
  const allFields = [...EDITABLE_FIELDS, ...DERIVED_FIELDS]

  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(display).map(([key, newVal]) => {
        const field = allFields.find(f => f.key === key)
        if (!field) return null
        const oldVal = oldValues?.[key]
        const isDerived = DERIVED_FIELDS.some(f => f.key === key)
        return (
          <span key={key} className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs border ${
            isDerived ? 'bg-slate-50 border-slate-200 text-slate-500' : 'bg-white border-gray-200'
          }`}>
            <span className="text-gray-400">{field.label}:</span>
            <span className="text-red-500 line-through">{fmt(oldVal)}</span>
            <span className="text-gray-300">→</span>
            <span className={`font-semibold ${isDerived ? 'text-slate-600' : 'text-emerald-600'}`}>{fmt(newVal)}</span>
            <span className="text-gray-300">{field.unit}</span>
          </span>
        )
      })}
    </div>
  )
}

// ── Create Request Modal ───────────────────────────────────────────────────────

function CreateModal({ onClose, onCreated }) {
  const [selectedItem, setSelectedItem] = useState(null)
  const [prices, setPrices]             = useState(null)
  const [newValues, setNewValues]       = useState({})
  const [derived, setDerived]           = useState({ unit_price: null, pack_price_tax: null })
  const [reason, setReason]             = useState('')
  const [error, setError]               = useState('')
  const qc = useQueryClient()

  // Load current prices when item selected
  useEffect(() => {
    if (!selectedItem) return
    pricingApprovalsApi.itemPrices(selectedItem.softech_id)
      .then(r => {
        setPrices(r.data)
        setNewValues({})
        setDerived({ unit_price: null, pack_price_tax: null })
      })
      .catch(() => setError('فشل تحميل بيانات الصنف'))
  }, [selectedItem])

  // Recompute derived values when pack_price input changes
  useEffect(() => {
    if (!prices || !newValues.pack_price) {
      setDerived({ unit_price: null, pack_price_tax: null })
      return
    }
    pricingApprovalsApi.preview({
      pack_price:   newValues.pack_price,
      pack_qty:     prices.pack_qty,
      sale_tax_pct: prices.sale_tax_pct,
    }).then(r => setDerived(r.data)).catch(() => {})
  }, [newValues.pack_price, prices])

  const createMutation = useMutation({
    mutationFn: (data) => pricingApprovalsApi.create(data),
    onSuccess: () => { qc.invalidateQueries(['pricing-approvals']); qc.invalidateQueries(['pricing-sla']); onCreated() },
    onError: (err) => {
      const d = err?.response?.data
      setError(d?.new_values?.[0] || d?.detail || JSON.stringify(d) || 'حدث خطأ')
    },
  })

  function handleValueChange(key, val) {
    setNewValues(prev => {
      const next = { ...prev }
      if (val === '' || val === null) delete next[key]
      else next[key] = val
      return next
    })
  }

  function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!selectedItem) return setError('اختر صنفاً')
    if (Object.keys(newValues).length === 0) return setError('أدخل قيمة جديدة لحقل واحد على الأقل')
    if (!reason.trim()) return setError('أدخل سبب التعديل')
    createMutation.mutate({ item: selectedItem.id, new_values: newValues, reason })
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[92vh] overflow-y-auto">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white z-10">
          <h2 className="text-lg font-bold text-gray-900">طلب تعديل سعر / خصم</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-5">
          {/* Item search */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">الصنف *</label>
            <ItemSearchWidget
              selected={selectedItem}
              onSelect={setSelectedItem}
              onClear={() => { setSelectedItem(null); setPrices(null); setNewValues({}) }}
              placeholder="ابحث باسم الصنف أو الكود أو الباركود..."
            />
          </div>

          {prices && (
            <>
              {/* Info bar */}
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-xs text-blue-700 flex gap-3 flex-wrap">
                <span>عدد الوحدات: <strong>{prices.pack_qty}</strong></span>
                <span>نسبة الضريبة: <strong>{fmt(prices.sale_tax_pct)}%</strong></span>
              </div>

              {/* Price group */}
              <div>
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">الأسعار</div>
                <div className="space-y-2.5">
                  {/* pack_price — editable */}
                  <FieldRow
                    field={{ key: 'pack_price', label: 'سعر العبوة (بدون ضريبة)', unit: 'جنيه' }}
                    current={prices.pack_price}
                    value={newValues.pack_price ?? ''}
                    onChange={v => handleValueChange('pack_price', v)}
                  />
                  {/* unit_price — always computed */}
                  <DerivedRow
                    label="سعر الوحدة"
                    unit="جنيه"
                    current={prices.unit_price}
                    computed={derived.unit_price}
                    formula={`سعر العبوة ÷ ${prices.pack_qty} وحدات`}
                  />
                  {/* pack_price_tax — always computed */}
                  <DerivedRow
                    label="السعر شامل الضريبة"
                    unit="جنيه"
                    current={prices.pack_price_tax}
                    computed={derived.pack_price_tax}
                    formula={`سعر العبوة × (1 + ${fmt(prices.sale_tax_pct)}%)`}
                  />
                </div>
              </div>

              {/* Discount group */}
              <div>
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">الخصومات</div>
                <div className="space-y-2.5">
                  {EDITABLE_FIELDS.filter(f => f.group === 'disc').map(field => (
                    <FieldRow
                      key={field.key}
                      field={field}
                      current={prices[field.key]}
                      value={newValues[field.key] ?? ''}
                      onChange={v => handleValueChange(field.key, v)}
                    />
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Reason */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">سبب التعديل *</label>
            <textarea
              value={reason}
              onChange={e => setReason(e.target.value)}
              rows={3}
              placeholder="اكتب سبب طلب التعديل…"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none resize-none"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose}
              className="px-4 py-2 rounded-lg border border-gray-300 text-sm text-gray-600 hover:bg-gray-50">
              إلغاء
            </button>
            <button type="submit" disabled={createMutation.isPending || !prices}
              className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-60">
              {createMutation.isPending ? 'جاري الإرسال…' : 'إرسال الطلب'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function FieldRow({ field, current, value, onChange }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-gray-700 w-40 shrink-0">{field.label}</span>
      <span className="text-xs bg-gray-100 rounded px-2 py-1 w-24 text-center text-gray-500 shrink-0">
        {fmt(current)} {field.unit}
      </span>
      <input
        type="number" step="0.01" min="0"
        placeholder={`جديد ${field.unit}`}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
      />
    </div>
  )
}

function DerivedRow({ label, unit, current, computed, formula }) {
  return (
    <div className="flex items-center gap-3 opacity-80">
      <span className="text-sm text-slate-500 w-40 shrink-0 flex items-center gap-1">
        {label}
        <span className="text-xs bg-slate-100 text-slate-400 rounded px-1">تلقائي</span>
      </span>
      <span className="text-xs bg-gray-100 rounded px-2 py-1 w-24 text-center text-gray-500 shrink-0">
        {fmt(current)} {unit}
      </span>
      <div className="flex-1 border border-dashed border-slate-200 rounded px-2 py-1.5 text-sm bg-slate-50 text-slate-500 flex items-center justify-between gap-2">
        {computed
          ? <span className="font-semibold text-emerald-600">{fmt(computed)} {unit}</span>
          : <span className="text-slate-300 italic">يُحسب تلقائياً</span>
        }
        <span className="text-xs text-slate-400 hidden sm:block">{formula}</span>
      </div>
    </div>
  )
}

// ── Review Modal ──────────────────────────────────────────────────────────────

function ReviewModal({ request, action, approverInfo, onClose, onDone }) {
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const qc = useQueryClient()
  const isApprove = action === 'approve'

  const mutation = useMutation({
    mutationFn: () =>
      isApprove
        ? pricingApprovalsApi.approve(request.id, notes)
        : pricingApprovalsApi.reject(request.id, notes),
    onSuccess: () => {
      qc.invalidateQueries(['pricing-approvals'])
      qc.invalidateQueries(['pricing-sla'])
      qc.invalidateQueries(['branch-health'])
      onDone()
    },
    onError: (err) => {
      const d = err?.response?.data
      setError(d?.detail || JSON.stringify(d) || 'حدث خطأ')
    },
  })

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="p-5 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-900">
            {isApprove ? 'اعتماد الطلب' : 'رفض الطلب'}
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">{request.item_name}</p>
        </div>

        <div className="p-5 space-y-4">
          {/* Change summary — shows new_values + what will auto-derive */}
          <ChangeSummary
            oldValues={request.old_values}
            newValues={request.new_values}
            executedValues={null}
          />

          {/* Derived fields preview */}
          {request.new_values?.pack_price && (
            <div className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded px-3 py-2 space-y-0.5">
              <div className="font-medium text-slate-600 mb-1">سيتم تحديثها تلقائياً:</div>
              <div>• سعر الوحدة = {request.new_values.pack_price} ÷ {request.item_pack_qty} وحدات</div>
              <div>• السعر شامل الضريبة = {request.new_values.pack_price} × (1 + {fmt(request.item_sale_tax_pct)}%)</div>
            </div>
          )}

          {isApprove && (
            <>
              {/* Approver identity */}
              {approverInfo?.is_linked ? (
                <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-sm text-emerald-800 flex items-center gap-2">
                  <span className="text-base">✓</span>
                  <span>
                    سيُنفَّذ باسم مستخدم Softech:
                    <strong className="font-mono mr-1">{approverInfo.erp_username || approverInfo.erp_usercode}</strong>
                    — سيظهر في Softech كأنك أجريته بنفسك
                  </span>
                </div>
              ) : (
                <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">
                  ⚠ حسابك غير مرتبط بمستخدم Softech — لا يمكن الاعتماد. يرجى ربط softech_user_id في إعدادات المستخدم.
                </div>
              )}

              <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-sm text-amber-800">
                التعديل سيُطبَّق فوراً في Softech ويُنشَر تلقائياً على جميع الفروع.
              </div>
            </>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">ملاحظات (اختياري)</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none resize-none"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose}
              className="px-4 py-2 rounded-lg border border-gray-300 text-sm text-gray-600 hover:bg-gray-50">
              إلغاء
            </button>
            <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || (isApprove && !approverInfo?.is_linked)}
              className={`px-5 py-2 rounded-lg text-white text-sm font-medium disabled:opacity-60 ${
                isApprove ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-red-600 hover:bg-red-700'
              }`}
            >
              {mutation.isPending
                ? (isApprove ? 'جاري التنفيذ في Softech…' : 'جاري الرفض…')
                : (isApprove ? 'اعتماد وتنفيذ في Softech' : 'رفض الطلب')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function PricingApprovalsPage() {
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreate, setShowCreate]     = useState(false)
  const [showImport, setShowImport]     = useState(false)
  const [reviewTarget, setReviewTarget] = useState(null)
  const [historyItem, setHistoryItem]   = useState(null)   // { softech_id, name }
  const [tab, setTab]                   = useState('requests')  // requests | sla | replication | insights
  const qc = useQueryClient()

  const rollback = useMutation({
    mutationFn: (id) => pricingApprovalsApi.rollback(id),
    onSuccess: () => { qc.invalidateQueries(['pricing-approvals']); qc.invalidateQueries(['pricing-sla']); setTab('requests'); setStatusFilter('pending') },
  })

  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin' || user?.is_staff

  // Load approver's Softech info (only relevant for admins)
  const { data: approverInfo } = useQuery({
    queryKey: ['approver-info'],
    queryFn:  () => pricingApprovalsApi.approverInfo().then(r => r.data),
    enabled:  isAdmin,
    staleTime: 60000,
  })

  const { data, isLoading, isError } = useQuery({
    queryKey: ['pricing-approvals', statusFilter],
    queryFn:  () => pricingApprovalsApi.list(statusFilter ? { status: statusFilter } : {}).then(r => r.data),
    refetchInterval: 30000,
  })

  const requests = data?.results ?? data ?? []

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">موافقات الأسعار والخصومات</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              طلبات تعديل أسعار وخصومات الأصناف — تُنفَّذ مباشرةً في Softech عند الاعتماد وتُنشَر على جميع الفروع تلقائياً
            </p>
          </div>
          <div className="flex items-center gap-3">
            {isAdmin && approverInfo && !approverInfo.is_linked && (
              <div className="text-xs bg-amber-100 border border-amber-300 text-amber-800 rounded-lg px-3 py-1.5">
                ⚠ ربط حساب Softech مطلوب للاعتماد
              </div>
            )}
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg"
            >
              📄 استيراد ملف
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg"
            >
              <span className="text-lg leading-none">+</span>
              طلب تعديل جديد
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-gray-200">
          {[
            { key: 'requests',    label: 'الطلبات' },
            { key: 'sla',         label: 'متابعة المعلّقة (SLA)' },
            ...(isAdmin ? [
              { key: 'replication', label: 'تدقيق النسخ المتماثل' },
              { key: 'insights',    label: 'لوحات المعلومات' },
            ] : []),
          ].map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'sla' && <SlaPanel onOpen={async (id) => {
          // Fetch the full request so Review works regardless of the list filter
          const local = requests.find(x => x.id === id)
          if (local) { setReviewTarget({ request: local, action: 'approve' }); return }
          try {
            const { data: full } = await pricingApprovalsApi.get(id)
            setReviewTarget({ request: full, action: 'approve' })
          } catch { /* ignore */ }
        }} />}
        {tab === 'replication' && <ReplicationAuditPanel />}
        {tab === 'insights' && <InsightsPanel />}
        {tab === 'requests' && (
        <>

        {/* Status filter */}
        <div className="flex gap-2 flex-wrap">
          {[
            { key: '',         label: 'الكل' },
            { key: 'pending',  label: 'في الانتظار' },
            { key: 'executed', label: 'منفذ' },
            { key: 'rejected', label: 'مرفوض' },
            { key: 'failed',   label: 'فشل' },
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => setStatusFilter(tab.key)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                statusFilter === tab.key
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden shadow-sm">
          {isLoading && <div className="text-center py-12 text-gray-400 text-sm">جاري التحميل…</div>}
          {isError   && <div className="text-center py-12 text-red-500 text-sm">حدث خطأ أثناء التحميل</div>}
          {!isLoading && !isError && requests.length === 0 && (
            <div className="text-center py-16 text-gray-400">
              <div className="text-4xl mb-3">📋</div>
              <div className="text-sm">لا توجد طلبات</div>
            </div>
          )}
          {!isLoading && requests.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-right">
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 w-8">#</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500">الصنف</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500">التعديلات</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500">بواسطة</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500">التاريخ</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500">الحالة</th>
                    {isAdmin && <th className="px-4 py-3 text-xs font-semibold text-gray-500">إجراء</th>}
                  </tr>
                </thead>
                <tbody>
                  {requests.map((req, idx) => (
                    <tr key={req.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-gray-400 text-xs">{idx + 1}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-900 text-sm">{req.item_name}</div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-400 font-mono">{req.item_softech_id}</span>
                          <button
                            onClick={() => setHistoryItem({ softech_id: req.item_softech_id, name: req.item_name })}
                            title="سجل تغييرات السعر"
                            className="text-xs text-blue-500 hover:text-blue-700">🕘 السجل</button>
                        </div>
                      </td>
                      <td className="px-4 py-3 max-w-xs">
                        <ChangeSummary
                          oldValues={req.old_values}
                          newValues={req.new_values}
                          executedValues={req.executed_values}
                        />
                        {req.reason && (
                          <div className="text-xs text-gray-400 mt-1 line-clamp-1">{req.reason}</div>
                        )}
                        {req.review_notes && (
                          <div className="text-xs text-blue-500 mt-0.5 line-clamp-1">ملاحظة: {req.review_notes}</div>
                        )}
                        {req.erp_error && (
                          <div className="text-xs text-red-500 mt-0.5 line-clamp-1">خطأ: {req.erp_error}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-gray-700 text-xs">{req.requested_by_name}</div>
                        {req.erp_username && (
                          <div className="text-xs text-emerald-600 mt-0.5 font-mono">
                            Softech: {req.erp_username}
                          </div>
                        )}
                        {req.reviewed_by_name && !req.erp_username && (
                          <div className="text-xs text-gray-400">راجع: {req.reviewed_by_name}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                        {new Date(req.requested_at).toLocaleDateString('ar-EG', {
                          day: '2-digit', month: 'short', year: 'numeric',
                        })}
                        {req.erp_executed_at && (
                          <div className="text-emerald-600 mt-0.5">
                            نُفِّذ {new Date(req.erp_executed_at).toLocaleTimeString('ar-EG', {
                              hour: '2-digit', minute: '2-digit',
                            })}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={req.status} />
                        {req.status === 'executed' && (
                          <div className="mt-1"><ReplicationBadge requestId={req.id} isAdmin={isAdmin} /></div>
                        )}
                        {req.source === 'rollback' && (
                          <div className="text-xs text-purple-600 mt-0.5">↩ تراجع</div>
                        )}
                      </td>
                      {isAdmin && (
                        <td className="px-4 py-3">
                          {(req.status === 'pending' || req.status === 'failed') && (
                            <div className="flex gap-1.5">
                              <button
                                onClick={() => setReviewTarget({ request: req, action: 'approve' })}
                                className="px-3 py-1 rounded-lg bg-emerald-600 text-white text-xs hover:bg-emerald-700"
                              >
                                اعتماد
                              </button>
                              {req.status === 'pending' && (
                                <button
                                  onClick={() => setReviewTarget({ request: req, action: 'reject' })}
                                  className="px-3 py-1 rounded-lg bg-red-100 text-red-700 text-xs hover:bg-red-200 border border-red-200"
                                >
                                  رفض
                                </button>
                              )}
                            </div>
                          )}
                          {req.status === 'executed' && (
                            <button
                              onClick={() => { if (confirm('إنشاء طلب تراجع إلى القيم السابقة؟')) rollback.mutate(req.id) }}
                              disabled={rollback.isPending}
                              className="px-3 py-1 rounded-lg bg-purple-100 text-purple-700 text-xs hover:bg-purple-200 border border-purple-200 disabled:opacity-60"
                            >
                              ↩ تراجع
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {!isAdmin && (
          <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 text-sm text-blue-700">
            طلباتك تظهر هنا — المدير يراجعها ويوافق عليها. عند الموافقة يُطبَّق التعديل مباشرةً في Softech وينتشر لجميع الفروع.
          </div>
        )}
        </>
        )}
      </div>

      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => setShowCreate(false)}
        />
      )}

      {showImport && <ImportModal onClose={() => setShowImport(false)} />}

      {historyItem && (
        <PriceHistoryModal
          softechId={historyItem.softech_id}
          itemName={historyItem.name}
          onClose={() => setHistoryItem(null)}
        />
      )}

      {reviewTarget && (
        <ReviewModal
          request={reviewTarget.request}
          action={reviewTarget.action}
          approverInfo={approverInfo}
          onClose={() => setReviewTarget(null)}
          onDone={() => setReviewTarget(null)}
        />
      )}
    </div>
  )
}
