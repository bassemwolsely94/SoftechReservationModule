/**
 * PaymentTracking.jsx — Module 6: External Payment Tracking
 * Log and reconcile: Cash / Instapay / Vodafone Cash
 */
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { paymentsApi, branchesApi } from '../api/client'
import RefreshButton from '../components/RefreshButton'

const fmt   = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
const today = () => new Date().toISOString().slice(0, 10)
const daysAgo = d => { const dt = new Date(); dt.setDate(dt.getDate() - d); return dt.toISOString().slice(0, 10) }

const METHOD_CONFIG = {
  cash:          { label: 'كاش',          icon: '💵', color: 'bg-green-100 text-green-700',  ring: 'border-green-300' },
  instapay:      { label: 'انستاباي',     icon: '📲', color: 'bg-purple-100 text-purple-700', ring: 'border-purple-300' },
  vodafone_cash: { label: 'فودافون كاش', icon: '📱', color: 'bg-red-100 text-red-700',       ring: 'border-red-300' },
  bank_transfer: { label: 'تحويل بنكي',  icon: '🏦', color: 'bg-blue-100 text-blue-700',    ring: 'border-blue-300' },
  other:         { label: 'أخرى',         icon: '💳', color: 'bg-gray-100 text-gray-600',    ring: 'border-gray-300' },
}

const STATUS_CONFIG = {
  pending:    { label: 'في الانتظار', color: 'bg-gray-100 text-gray-600',   dot: 'bg-gray-400'   },
  confirmed:  { label: 'مؤكد',       color: 'bg-green-100 text-green-700',  dot: 'bg-green-500'  },
  reconciled: { label: 'تمت المطابقة', color: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500'   },
  disputed:   { label: 'متنازع',     color: 'bg-red-100 text-red-700',      dot: 'bg-red-500'    },
  cancelled:  { label: 'ملغي',       color: 'bg-gray-100 text-gray-400',    dot: 'bg-gray-300'   },
}

function MethodBadge({ method }) {
  const c = METHOD_CONFIG[method] || METHOD_CONFIG.other
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${c.color}`}>
      {c.icon} {c.label}
    </span>
  )
}

function StatusBadge({ status }) {
  const s = STATUS_CONFIG[status] || STATUS_CONFIG.pending
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

// ── New Payment Modal ───────────────────────────────────────────────────────────
function NewPaymentModal({ branches, onClose, onDone }) {
  const [form, setForm] = useState({
    method: 'cash',
    amount: '',
    invoice_total: '',
    customer_name: '',
    customer_phone: '',
    softech_invoice_code: '',
    softech_doc_number: '',
    reference_number: '',
    payment_date: today(),
    branch: '',
    notes: '',
    is_partial: false,
    remaining_amount: '',
  })
  const [screenshot, setScreenshot] = useState(null)
  const fileRef = useRef()

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const mut = useMutation({
    mutationFn: async () => {
      const res = await paymentsApi.create({
        ...form,
        amount: Number(form.amount) || 0,
        invoice_total: Number(form.invoice_total) || 0,
        remaining_amount: Number(form.remaining_amount) || 0,
      })
      if (screenshot && res.data?.id) {
        const fd = new FormData()
        fd.append('screenshot', screenshot)
        await paymentsApi.uploadScreenshot(res.data.id, fd)
      }
      return res
    },
    onSuccess: () => { onDone(); onClose() },
  })

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4 overflow-y-auto"
      onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg my-4 p-6"
        onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-800 mb-4">تسجيل دفعة جديدة</h2>

        {/* Method selector */}
        <div className="mb-4">
          <label className="block text-xs text-gray-500 mb-2">طريقة الدفع *</label>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(METHOD_CONFIG).map(([k, c]) => (
              <button key={k}
                onClick={() => set('method', k)}
                className={`px-3 py-2 rounded-lg text-xs font-medium border transition-all ${
                  form.method === k
                    ? `${c.ring} border-2 ${c.color}`
                    : 'border-gray-200 text-gray-500 hover:border-gray-300'
                }`}>
                {c.icon} {c.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">المبلغ المدفوع *</label>
            <input type="number" value={form.amount} onChange={e => set('amount', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">إجمالي الفاتورة</label>
            <input type="number" value={form.invoice_total} onChange={e => set('invoice_total', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">اسم العميل</label>
            <input value={form.customer_name} onChange={e => set('customer_name', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">رقم الهاتف</label>
            <input value={form.customer_phone} onChange={e => set('customer_phone', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">كود الفاتورة (SOFTECH)</label>
            <input value={form.softech_invoice_code} onChange={e => set('softech_invoice_code', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">رقم المستند</label>
            <input value={form.softech_doc_number} onChange={e => set('softech_doc_number', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          {form.method !== 'cash' && (
            <div className="col-span-2">
              <label className="block text-xs text-gray-500 mb-1">رقم المرجع / الإيصال *</label>
              <input value={form.reference_number} onChange={e => set('reference_number', e.target.value)}
                placeholder="رقم عملية انستاباي / فودافون..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
            </div>
          )}
          <div>
            <label className="block text-xs text-gray-500 mb-1">الفرع *</label>
            <select value={form.branch} onChange={e => set('branch', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              <option value="">اختر الفرع</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">تاريخ الدفع</label>
            <input type="date" value={form.payment_date} onChange={e => set('payment_date', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>

          {/* Partial payment toggle */}
          <div className="col-span-2 flex items-center gap-3 py-1">
            <label className="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" checked={form.is_partial}
                onChange={e => set('is_partial', e.target.checked)} className="sr-only peer" />
              <div className="w-9 h-5 bg-gray-200 peer-focus:ring-2 peer-focus:ring-brand-400 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:right-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-brand-600" />
            </label>
            <span className="text-sm text-gray-600">دفعة جزئية</span>
            {form.is_partial && (
              <input type="number" value={form.remaining_amount}
                onChange={e => set('remaining_amount', e.target.value)}
                placeholder="المتبقي"
                className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-24 focus:ring-2 focus:ring-brand-400 focus:outline-none" />
            )}
          </div>

          {/* Screenshot */}
          {form.method !== 'cash' && (
            <div className="col-span-2">
              <label className="block text-xs text-gray-500 mb-1">إيصال / لقطة شاشة</label>
              <div className="flex items-center gap-2">
                <button onClick={() => fileRef.current?.click()}
                  className="px-3 py-2 border border-dashed border-gray-300 rounded-lg text-xs text-gray-500 hover:border-brand-400 transition-colors">
                  📎 اختر صورة
                </button>
                <input ref={fileRef} type="file" accept="image/*" className="hidden"
                  onChange={e => setScreenshot(e.target.files?.[0] || null)} />
                {screenshot && <span className="text-xs text-green-600">✓ {screenshot.name}</span>}
              </div>
            </div>
          )}

          <div className="col-span-2">
            <label className="block text-xs text-gray-500 mb-1">ملاحظات</label>
            <textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none resize-none" />
          </div>
        </div>

        <div className="flex gap-3 mt-5">
          <button onClick={onClose}
            className="flex-1 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors">
            إلغاء
          </button>
          <button
            disabled={!form.amount || !form.branch || mut.isLoading}
            onClick={() => mut.mutate()}
            className="flex-1 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors">
            {mut.isLoading ? 'جارٍ الحفظ…' : 'تسجيل الدفعة'}
          </button>
        </div>
        {mut.isError && <p className="text-xs text-red-500 mt-2 text-center">حدث خطأ أثناء الحفظ</p>}
      </div>
    </div>
  )
}

// ── Payment row ─────────────────────────────────────────────────────────────────
function PaymentRow({ payment, onConfirm, onDispute }) {
  return (
    <div className="px-5 py-4 hover:bg-gray-50/50 transition-colors">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-gray-800 font-mono text-lg">
              {fmt(payment.amount, 2)} <span className="text-sm font-normal text-gray-400">جم</span>
            </span>
            <MethodBadge method={payment.method} />
            <StatusBadge status={payment.status} />
            {payment.is_partial && (
              <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full">جزئي</span>
            )}
          </div>
          <div className="mt-1 text-sm text-gray-600">
            {payment.customer_name || 'عميل غير محدد'}
            {payment.customer_phone && (
              <span className="mr-2 text-xs text-gray-400 font-mono">{payment.customer_phone}</span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 mt-1 text-xs text-gray-400">
            {payment.softech_invoice_code && <span>فاتورة: {payment.softech_invoice_code}</span>}
            {payment.reference_number && <span>مرجع: <span className="font-mono">{payment.reference_number}</span></span>}
            {payment.invoice_total > 0 && (
              <span>إجمالي الفاتورة: <span className="font-mono">{fmt(payment.invoice_total, 2)} جم</span></span>
            )}
            <span>{payment.payment_date}</span>
            {payment.branch_name && <span>🏪 {payment.branch_name}</span>}
          </div>
          {payment.is_partial && payment.remaining_amount > 0 && (
            <div className="mt-1 text-xs text-amber-600">
              المتبقي: <span className="font-mono font-semibold">{fmt(payment.remaining_amount, 2)} جم</span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {payment.status === 'pending' && (
            <>
              <button onClick={() => onConfirm(payment)}
                className="px-3 py-1.5 text-xs bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
                تأكيد ✓
              </button>
              <button onClick={() => onDispute(payment)}
                className="px-3 py-1.5 text-xs bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors">
                اعتراض
              </button>
            </>
          )}
          {payment.status === 'confirmed' && (
            <span className="text-xs text-green-600">
              ✓ تم بواسطة {payment.confirmed_by_name || 'النظام'}
            </span>
          )}
          {payment.screenshot && (
            <a href={payment.screenshot} target="_blank" rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline">
              📷 إيصال
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main ─────────────────────────────────────────────────────────────────────────
export default function PaymentTracking() {
  const qc = useQueryClient()
  const [methodFilter,    setMethodFilter]    = useState('')
  const [statusFilter,    setStatusFilter]    = useState('')
  const [branchFilter,    setBranchFilter]    = useState('')
  const [dateFrom,        setDateFrom]        = useState(daysAgo(7))
  const [dateTo,          setDateTo]          = useState(today())
  const [dateExact,       setDateExact]       = useState('')
  const [hourFrom,        setHourFrom]        = useState('')
  const [hourTo,          setHourTo]          = useState('')
  const [daysOfWeek,      setDaysOfWeek]      = useState([])
  const [search,          setSearch]          = useState('')
  const [showNew,         setShowNew]         = useState(false)
  const [showTimeFilters, setShowTimeFilters] = useState(false)
  const DOW_AR = ['','الأحد','الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت']

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data?.results || r.data || []),
    staleTime: 300_000,
  })

  const { data: summary } = useQuery({
    queryKey: ['payments-summary'],
    queryFn:  () => paymentsApi.summary().then(r => r.data),
    refetchInterval: 30_000,
  })

  const params = {
    ...(methodFilter          ? { method: methodFilter }               : {}),
    ...(statusFilter          ? { status: statusFilter }               : {}),
    ...(branchFilter          ? { branch: branchFilter }               : {}),
    ...(search                ? { search }                             : {}),
    ...(dateExact             ? { date_exact: dateExact }              : { date_from: dateFrom, date_to: dateTo }),
    ...(hourFrom !== ''       ? { hour_from: hourFrom }                : {}),
    ...(hourTo   !== ''       ? { hour_to: hourTo }                    : {}),
    ...(daysOfWeek.length     ? { days_of_week: daysOfWeek.join(',') } : {}),
  }

  const { data: paymentsData, isLoading, isFetching } = useQuery({
    queryKey: ['payments', params],
    queryFn:  () => paymentsApi.list(params).then(r => r.data),
    staleTime: 30_000,
  })

  const payments = paymentsData?.results || paymentsData || []
  const invalidate = () => {
    qc.invalidateQueries(['payments'])
    qc.invalidateQueries(['payments-summary'])
  }

  const confirmMut = useMutation({
    mutationFn: id => paymentsApi.confirm(id),
    onSuccess: invalidate,
  })

  const disputeMut = useMutation({
    mutationFn: ({ id, reason }) => paymentsApi.dispute(id, { reason }),
    onSuccess: invalidate,
  })

  const [disputeTarget, setDisputeTarget] = useState(null)
  const [disputeReason, setDisputeReason] = useState('')

  return (
    <div className="p-6 space-y-6 max-w-screen-xl mx-auto" dir="rtl">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">تتبع المدفوعات</h1>
          <p className="text-sm text-gray-500 mt-0.5">انستاباي — فودافون كاش — كاش — تحويل بنكي</p>
        </div>
        <button onClick={() => setShowNew(true)}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 transition-colors">
          + تسجيل دفعة
        </button>
      </div>

      {/* Summary */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-brand-50 border border-brand-200 rounded-xl p-4">
            <p className="text-xs text-gray-400">إجمالي اليوم</p>
            <p className="text-2xl font-bold text-brand-700 font-mono mt-1">{fmt(summary.total_value_today, 2)} جم</p>
          </div>
          {Object.entries(summary.by_method || {}).map(([method, val]) => {
            const c = METHOD_CONFIG[method] || METHOD_CONFIG.other
            return (
              <div key={method} className="bg-white border border-gray-200 rounded-xl p-4">
                <p className="text-xs text-gray-400 flex items-center gap-1">
                  {c.icon} {c.label}
                </p>
                <p className="text-xl font-bold font-mono text-gray-700 mt-1">{fmt(val, 2)} <span className="text-sm font-normal text-gray-400">جم</span></p>
              </div>
            )
          })}
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <p className="text-xs text-gray-400">في الانتظار</p>
            <p className="text-2xl font-bold text-amber-700 font-mono mt-1">{fmt(summary.total_pending, 2)} جم</p>
          </div>
          <div className="bg-green-50 border border-green-200 rounded-xl p-4">
            <p className="text-xs text-gray-400">مؤكد اليوم</p>
            <p className="text-2xl font-bold text-green-700 font-mono mt-1">{fmt(summary.total_confirmed, 2)} جم</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        {/* Row 1: main filters */}
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-gray-500 mb-1">من</label>
            <input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setDateExact('') }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">إلى</label>
            <input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setDateExact('') }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">طريقة الدفع</label>
            <select value={methodFilter} onChange={e => setMethodFilter(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              <option value="">الكل</option>
              {Object.entries(METHOD_CONFIG).map(([k, c]) => (
                <option key={k} value={k}>{c.icon} {c.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">الحالة</label>
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              <option value="">الكل</option>
              {Object.entries(STATUS_CONFIG).map(([k, c]) => (
                <option key={k} value={k}>{c.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">الفرع</label>
            <select value={branchFilter} onChange={e => setBranchFilter(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none">
              <option value="">الكل</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">بحث</label>
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="اسم / هاتف / مرجع..."
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-400 focus:outline-none min-w-36" />
          </div>
          <button type="button" onClick={() => setShowTimeFilters(v => !v)}
            className={`self-end flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg border transition-colors
              ${showTimeFilters ? 'bg-brand-50 border-brand-400 text-brand-700' : 'bg-white border-gray-300 text-gray-600 hover:border-brand-400'}`}>
            🕐 وقت {showTimeFilters ? '▲' : '▼'}
          </button>
        </div>

        {/* Row 2: time filters */}
        {showTimeFilters && (
          <div className="flex flex-wrap gap-3 items-center pt-2 border-t border-gray-100">
            {[{l:'اليوم',f:today(),t:today()},{l:'أمس',f:daysAgo(1),t:daysAgo(1)},{l:'٧ أيام',f:daysAgo(7),t:today()},{l:'٣٠ يوم',f:daysAgo(30),t:today()}].map(r => (
              <button key={r.l} type="button"
                onClick={() => { setDateFrom(r.f); setDateTo(r.t); setDateExact('') }}
                className={`px-2.5 py-1.5 text-xs rounded-lg border ${dateFrom===r.f && dateTo===r.t && !dateExact ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'}`}>
                {r.l}
              </button>
            ))}
            <span className="text-xs text-gray-400">|</span>
            <span className="text-xs text-gray-500">يوم بعينه:</span>
            <input type="date" value={dateExact} onChange={e => setDateExact(e.target.value)}
              className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none" />
            {dateExact && <button type="button" onClick={() => setDateExact('')} className="text-gray-400 hover:text-red-500 text-xs">✕</button>}
            <span className="text-xs text-gray-400">|</span>
            <span className="text-xs text-gray-500">الساعة:</span>
            <select value={hourFrom} onChange={e => setHourFrom(e.target.value)}
              className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none">
              <option value="">من</option>
              {Array.from({length:24},(_,h)=><option key={h} value={h}>{h}:00</option>)}
            </select>
            <select value={hourTo} onChange={e => setHourTo(e.target.value)}
              className="border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:ring-1 focus:ring-brand-400 focus:outline-none">
              <option value="">إلى</option>
              {Array.from({length:24},(_,h)=><option key={h} value={h}>{h}:59</option>)}
            </select>
            <span className="text-xs text-gray-400">|</span>
            <span className="text-xs text-gray-500">أيام:</span>
            <div className="flex gap-1">
              {[2,3,4,5,6,7,1].map(d => {
                const active = daysOfWeek.includes(String(d))
                return (
                  <button key={d} type="button"
                    onClick={() => setDaysOfWeek(v => active ? v.filter(x=>x!==String(d)) : [...v,String(d)])}
                    className={`px-2 py-1 text-[10px] rounded border ${active ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-200 hover:border-brand-400'}`}>
                    {DOW_AR[d]?.slice(0,3)}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Payments list */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-600">{payments.length} دفعة</span>
          <RefreshButton loading={isFetching} onClick={invalidate} variant="ghost" size="sm">
            تحديث
          </RefreshButton>
        </div>

        {isLoading && <div className="text-center py-12 text-brand-500 animate-pulse">جارٍ التحميل…</div>}

        {!isLoading && !payments.length && (
          <div className="text-center py-16 text-gray-400">
            <span className="text-4xl block mb-3">💳</span>
            لا توجد مدفوعات مطابقة
          </div>
        )}

        <div className="divide-y divide-gray-50">
          {payments.map(p => (
            <PaymentRow
              key={p.id}
              payment={p}
              onConfirm={pay => confirmMut.mutate(pay.id)}
              onDispute={pay => { setDisputeTarget(pay); setDisputeReason('') }}
            />
          ))}
        </div>
      </div>

      {/* Dispute modal */}
      {disputeTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setDisputeTarget(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6"
            onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-red-700 mb-3">تسجيل اعتراض</h2>
            <p className="text-sm text-gray-600 mb-3">
              الدفعة: <strong>{fmt(disputeTarget.amount, 2)} جم</strong> من {disputeTarget.customer_name}
            </p>
            <textarea value={disputeReason} onChange={e => setDisputeReason(e.target.value)}
              rows={3} placeholder="سبب الاعتراض..."
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-red-400 focus:outline-none resize-none mb-4" />
            <div className="flex gap-3">
              <button onClick={() => setDisputeTarget(null)}
                className="flex-1 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
                إلغاء
              </button>
              <button
                disabled={!disputeReason.trim() || disputeMut.isLoading}
                onClick={() => {
                  disputeMut.mutate({ id: disputeTarget.id, reason: disputeReason },
                    { onSuccess: () => setDisputeTarget(null) })
                }}
                className="flex-1 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50">
                {disputeMut.isLoading ? 'جارٍ…' : 'تأكيد الاعتراض'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showNew && (
        <NewPaymentModal
          branches={branches}
          onClose={() => setShowNew(false)}
          onDone={invalidate}
        />
      )}
    </div>
  )
}
