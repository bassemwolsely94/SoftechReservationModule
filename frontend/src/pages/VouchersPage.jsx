/**
 * VouchersPage.jsx
 *
 * Full voucher management UI:
 *   Tab 1 — القسائم    : list, create, cancel, assign
 *   Tab 2 — استرداد    : 4-step redemption flow (validate → OTP → verify → document)
 *   Tab 3 — وثائق POS  : look up + mark-used + print + WhatsApp
 *   Tab 4 — تقارير     : usage report
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { vouchersApi } from '../api/client'

// ── Constants ──────────────────────────────────────────────────────────────────
const TYPE_CFG = {
  discount_pct:  { label: 'خصم %',     icon: '🏷️', color: 'bg-blue-50 text-blue-700 border-blue-200' },
  discount_fixed:{ label: 'خصم ثابت',  icon: '💰', color: 'bg-purple-50 text-purple-700 border-purple-200' },
  credit:        { label: 'رصيد نقدي', icon: '💳', color: 'bg-teal-50 text-teal-700 border-teal-200' },
  free_item:     { label: 'صنف مجاني', icon: '🎁', color: 'bg-rose-50 text-rose-700 border-rose-200' },
}
const CAT_CFG = {
  public:     { label: 'عام',            icon: '🌐', color: 'bg-gray-100 text-gray-600' },
  private:    { label: 'خاص',            icon: '🔒', color: 'bg-amber-100 text-amber-700' },
  first_time: { label: 'أول مرة',        icon: '⭐', color: 'bg-green-100 text-green-700' },
  assigned:   { label: 'مخصص بالهاتف',  icon: '📱', color: 'bg-indigo-100 text-indigo-700' },
}
const STATUS_CFG = {
  active:   { label: 'نشط',       color: 'bg-green-100 text-green-700' },
  used:     { label: 'مُستخدَم',  color: 'bg-gray-100 text-gray-500' },
  expired:  { label: 'منتهي',     color: 'bg-red-100 text-red-600' },
  cancelled:{ label: 'ملغى',      color: 'bg-gray-100 text-gray-400' },
}
const DOC_STATUS_CFG = {
  active:   { label: 'نشط',       color: 'bg-green-100 text-green-700', icon: '✅' },
  used:     { label: 'مُستخدَم',  color: 'bg-blue-100 text-blue-700',   icon: '✔️' },
  expired:  { label: 'منتهي',     color: 'bg-red-100 text-red-600',     icon: '⏰' },
  cancelled:{ label: 'ملغى',      color: 'bg-gray-100 text-gray-400',   icon: '🚫' },
}

function valueDisplay(v) {
  if (!v) return '—'
  if (v.voucher_type === 'discount_pct')   return `${v.discount_pct}%`
  if (v.voucher_type === 'discount_fixed') return `${Number(v.discount_amount).toFixed(2)} ج.م`
  if (v.voucher_type === 'credit')         return `${Number(v.credit_amount).toFixed(2)} ج.م`
  if (v.voucher_type === 'free_item')      return v.free_item_name || '—'
  return '—'
}

// ── Reusable UI ───────────────────────────────────────────────────────────────
function Field({ label, children, required }) {
  return (
    <div>
      <label className="text-xs text-gray-600 block mb-1 font-medium">
        {label}{required && <span className="text-red-500 mr-0.5">*</span>}
      </label>
      {children}
    </div>
  )
}
function Input({ className = '', ...props }) {
  return (
    <input
      className={`w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 ${className}`}
      {...props}
    />
  )
}
function Select({ children, className = '', ...props }) {
  return (
    <select
      className={`w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 ${className}`}
      {...props}
    >
      {children}
    </select>
  )
}
function Btn({ children, variant = 'primary', size = 'md', disabled, className = '', ...props }) {
  const base = 'rounded-xl font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
  const variants = {
    primary: 'bg-brand-600 text-white hover:bg-brand-700',
    success: 'bg-green-600 text-white hover:bg-green-700',
    danger:  'bg-red-500 text-white hover:bg-red-600',
    ghost:   'bg-gray-100 text-gray-600 hover:bg-gray-200',
    outline: 'border border-gray-300 text-gray-600 hover:bg-gray-50',
    whatsapp:'bg-green-500 text-white hover:bg-green-600',
  }
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm', lg: 'px-5 py-2.5 text-sm' }
  return (
    <button className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} disabled={disabled} {...props}>
      {children}
    </button>
  )
}
function ErrorBox({ msg }) {
  if (!msg) return null
  return (
    <div className="mt-3 text-xs text-red-700 bg-red-50 border border-red-200 px-3 py-2.5 rounded-xl">
      {msg}
    </div>
  )
}
function Toast({ toast }) {
  if (!toast) return null
  return (
    <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-[9999] px-5 py-3 rounded-xl shadow-lg text-sm font-medium transition-all
      ${toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
      {toast.msg}
    </div>
  )
}

// ── Tab 1: Create Voucher Modal ───────────────────────────────────────────────
function CreateVoucherModal({ onClose, onCreate }) {
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({
    title: '', description: '',
    voucher_category: 'public', voucher_type: 'discount_pct',
    discount_pct: '', discount_amount: '', credit_amount: '',
    max_discount_cap: '', min_order_value: '',
    valid_from: today, valid_until: '',
    max_uses: 1, usage_limit_per_customer: 1,
    usage_limit_per_day: '', notes: '',
  })
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const f = (key) => (e) => setForm(p => ({ ...p, [key]: e.target.value }))

  const submit = async () => {
    if (!form.title.trim()) return setError('العنوان مطلوب')
    if (!form.valid_from)    return setError('تاريخ البدء مطلوب')
    setSaving(true); setError(null)
    try {
      const payload = { ...form }

      // Remove optional blank numeric fields (DRF DecimalField rejects '' as invalid)
      ;['max_discount_cap', 'min_order_value', 'usage_limit_per_day',
        'discount_pct', 'discount_amount', 'credit_amount',
        'free_item', 'max_uses', 'usage_limit_per_customer',
        'validity_days_after_assignment',
      ].forEach(k => {
        if (payload[k] === '' || payload[k] === null || payload[k] === undefined)
          delete payload[k]
      })

      // Remove blank valid_until (optional date)
      if (!payload.valid_until) delete payload.valid_until

      const r = await vouchersApi.create(payload)
      onCreate(r.data)
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'string' ? d : Object.values(d || {}).flat().join(' | '))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h3 className="font-bold text-gray-900 text-base">🎫 إنشاء قسيمة جديدة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Title */}
          <Field label="العنوان" required>
            <Input value={form.title} onChange={f('title')} placeholder="مثال: خصم 10% على الأدوية المزمنة" />
          </Field>

          {/* Category + Type */}
          <div className="grid grid-cols-2 gap-3">
            <Field label="فئة التوزيع" required>
              <Select value={form.voucher_category} onChange={f('voucher_category')}>
                {Object.entries(CAT_CFG).map(([v, c]) => (
                  <option key={v} value={v}>{c.icon} {c.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="آلية الخصم" required>
              <Select value={form.voucher_type} onChange={f('voucher_type')}>
                {Object.entries(TYPE_CFG).map(([v, c]) => (
                  <option key={v} value={v}>{c.icon} {c.label}</option>
                ))}
              </Select>
            </Field>
          </div>

          {/* Type-specific value */}
          {form.voucher_type === 'discount_pct' && (
            <Field label="نسبة الخصم %" required>
              <Input type="number" value={form.discount_pct} onChange={f('discount_pct')} min="0.01" max="100" step="0.01" placeholder="10" />
            </Field>
          )}
          {form.voucher_type === 'discount_fixed' && (
            <Field label="مبلغ الخصم (ج.م)" required>
              <Input type="number" value={form.discount_amount} onChange={f('discount_amount')} min="0.001" step="0.001" placeholder="50.000" />
            </Field>
          )}
          {form.voucher_type === 'credit' && (
            <Field label="قيمة الرصيد (ج.م)" required>
              <Input type="number" value={form.credit_amount} onChange={f('credit_amount')} min="0.001" step="0.001" placeholder="100.000" />
            </Field>
          )}

          {/* Limits row */}
          <div className="grid grid-cols-2 gap-3">
            <Field label="الحد الأدنى للطلب (ج.م)">
              <Input type="number" value={form.min_order_value} onChange={f('min_order_value')} min="0" step="0.001" placeholder="لا يوجد" />
            </Field>
            <Field label="الحد الأقصى للخصم (ج.م)">
              <Input type="number" value={form.max_discount_cap} onChange={f('max_discount_cap')} min="0" step="0.001" placeholder="غير محدود" />
            </Field>
          </div>

          {/* Validity */}
          <div className="grid grid-cols-2 gap-3">
            <Field label="صالح من" required>
              <Input type="date" value={form.valid_from} onChange={f('valid_from')} />
            </Field>
            <Field label="صالح حتى">
              <Input type="date" value={form.valid_until} onChange={f('valid_until')} />
            </Field>
          </div>

          {/* Usage limits */}
          <div className="grid grid-cols-3 gap-3">
            <Field label="الحد الكلي">
              <Input type="number" value={form.max_uses} onChange={f('max_uses')} min="1" />
            </Field>
            <Field label="لكل عميل">
              <Input type="number" value={form.usage_limit_per_customer} onChange={f('usage_limit_per_customer')} min="1" />
            </Field>
            <Field label="يومياً">
              <Input type="number" value={form.usage_limit_per_day} onChange={f('usage_limit_per_day')} min="1" placeholder="∞" />
            </Field>
          </div>

          <Field label="ملاحظات">
            <textarea value={form.notes} onChange={f('notes')} rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </Field>
        </div>

        <div className="px-5 py-4 border-t shrink-0">
          <ErrorBox msg={error} />
          <div className="flex gap-2 mt-3">
            <Btn variant="primary" size="lg" onClick={submit} disabled={saving} className="flex-1">
              {saving ? 'جاري الإنشاء...' : '✓ إنشاء القسيمة'}
            </Btn>
            <Btn variant="ghost" size="lg" onClick={onClose} className="flex-1">إلغاء</Btn>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Tab 1: Assign Modal ───────────────────────────────────────────────────────
function AssignModal({ voucher, onClose, onDone }) {
  const [phone,   setPhone]   = useState('')
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState(null)
  const [success, setSuccess] = useState(false)

  const submit = async () => {
    if (!phone.trim()) return setError('رقم الهاتف مطلوب')
    setSaving(true); setError(null)
    try {
      await vouchersApi.assign(voucher.id, { customer_phone: phone.trim() })
      setSuccess(true)
      setTimeout(() => { onDone(); onClose() }, 1500)
    } catch (e) {
      setError(e.response?.data?.detail || Object.values(e.response?.data || {}).flat().join(' | '))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
        <h3 className="font-bold text-gray-900 mb-1">📱 تخصيص القسيمة</h3>
        <p className="text-xs text-gray-500 mb-4">الكود: <span className="font-mono font-bold">{voucher.code}</span></p>
        {success ? (
          <div className="text-center py-4">
            <div className="text-4xl mb-2">✅</div>
            <div className="font-bold text-green-700">تم التخصيص بنجاح</div>
          </div>
        ) : (
          <>
            <Field label="رقم هاتف العميل" required>
              <Input value={phone} onChange={e => setPhone(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submit()}
                placeholder="01xxxxxxxxx" dir="ltr" />
            </Field>
            <ErrorBox msg={error} />
            <div className="flex gap-2 mt-4">
              <Btn variant="primary" onClick={submit} disabled={saving} className="flex-1">
                {saving ? '...' : 'تخصيص'}
              </Btn>
              <Btn variant="ghost" onClick={onClose} className="flex-1">إلغاء</Btn>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Tab 1: Vouchers List ──────────────────────────────────────────────────────
function VouchersList({ onRedeem }) {
  const [vouchers,     setVouchers]     = useState([])
  const [loading,      setLoading]      = useState(true)
  const [showCreate,   setShowCreate]   = useState(false)
  const [assignTarget, setAssignTarget] = useState(null)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterType,   setFilterType]   = useState('')
  const [filterCat,    setFilterCat]    = useState('')
  const [searchQ,      setSearchQ]      = useState('')
  const [toast,        setToast]        = useState(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type }); setTimeout(() => setToast(null), 3000)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterStatus) params.status   = filterStatus
      if (filterType)   params.type     = filterType
      if (filterCat)    params.category = filterCat
      if (searchQ)      params.search   = searchQ
      const r = await vouchersApi.list(params)
      setVouchers(r.data.results || r.data)
    } finally { setLoading(false) }
  }, [filterStatus, filterType, filterCat, searchQ])

  useEffect(() => { load() }, [load])

  const handleCancel = async (v) => {
    if (!window.confirm(`إلغاء القسيمة "${v.code}"؟`)) return
    try {
      await vouchersApi.cancel(v.id)
      showToast('تم إلغاء القسيمة')
      load()
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ', 'error')
    }
  }

  return (
    <div className="flex flex-col h-full">
      <Toast toast={toast} />

      {showCreate && (
        <CreateVoucherModal
          onClose={() => setShowCreate(false)}
          onCreate={() => { setShowCreate(false); load(); showToast('تم إنشاء القسيمة ✓') }}
        />
      )}

      {assignTarget && (
        <AssignModal
          voucher={assignTarget}
          onClose={() => setAssignTarget(null)}
          onDone={() => showToast('تم تخصيص القسيمة ✓')}
        />
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <input
          value={searchQ} onChange={e => setSearchQ(e.target.value)}
          className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-brand-400"
          placeholder="بحث بالكود أو العنوان..." />
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
          <option value="">كل الحالات</option>
          {Object.entries(STATUS_CFG).map(([v, c]) => <option key={v} value={v}>{c.label}</option>)}
        </select>
        <select value={filterType} onChange={e => setFilterType(e.target.value)}
          className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
          <option value="">كل الأنواع</option>
          {Object.entries(TYPE_CFG).map(([v, c]) => <option key={v} value={v}>{c.icon} {c.label}</option>)}
        </select>
        <select value={filterCat} onChange={e => setFilterCat(e.target.value)}
          className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
          <option value="">كل الفئات</option>
          {Object.entries(CAT_CFG).map(([v, c]) => <option key={v} value={v}>{c.icon} {c.label}</option>)}
        </select>
        <div className="flex-1" />
        <Btn variant="primary" onClick={() => setShowCreate(true)}>+ قسيمة جديدة</Btn>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center text-gray-400 animate-pulse">جاري التحميل...</div>
      ) : vouchers.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
          <div className="text-5xl mb-3">🎫</div>
          <div className="font-medium mb-4">لا توجد قسائم</div>
          <Btn variant="primary" onClick={() => setShowCreate(true)}>+ قسيمة جديدة</Btn>
        </div>
      ) : (
        <div className="flex-1 overflow-auto rounded-xl border border-gray-100">
          <table className="w-full text-right text-sm">
            <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
              <tr>
                {['الكود','العنوان','الفئة','النوع / القيمة','الاستخدام','الصلاحية','الحالة','إجراءات'].map(h => (
                  <th key={h} className="px-3 py-2.5 text-xs font-semibold text-gray-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {vouchers.map(v => {
                const tc = TYPE_CFG[v.voucher_type] || {}
                const cc = CAT_CFG[v.voucher_category] || {}
                const sc = STATUS_CFG[v.status] || {}
                return (
                  <tr key={v.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-3 py-2.5">
                      <span className="font-mono text-xs bg-gray-100 text-gray-700 px-2 py-0.5 rounded">
                        {v.code}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 max-w-[160px]">
                      <div className="text-sm font-medium text-gray-800 truncate">{v.title}</div>
                      {v.customer_name && (
                        <div className="text-xs text-gray-400 truncate">{v.customer_name}</div>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${cc.color}`}>
                        {cc.icon} {cc.label}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${tc.color}`}>
                        {tc.icon} {tc.label}
                      </span>
                      <div className="font-bold text-sm mt-0.5">{valueDisplay(v)}</div>
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <div className="text-sm font-semibold text-gray-700">{v.times_used} / {v.max_uses}</div>
                      <div className="w-full bg-gray-100 rounded-full h-1 mt-1">
                        <div
                          className="bg-brand-500 h-1 rounded-full"
                          style={{ width: `${Math.min(100, (v.times_used / v.max_uses) * 100)}%` }}
                        />
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-gray-500">
                      <div>{v.valid_from}</div>
                      {v.valid_until && <div className="text-gray-400">→ {v.valid_until}</div>}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${sc.color}`}>
                        {sc.label}
                      </span>
                      {v.is_expired && !v.is_exhausted && (
                        <div className="text-xs text-red-400 mt-0.5">منتهية الصلاحية</div>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5 justify-end flex-wrap">
                        {v.status === 'active' && (
                          <>
                            <Btn size="sm" variant="primary" onClick={() => onRedeem(v)}>
                              استرداد
                            </Btn>
                            {v.voucher_category === 'assigned' && (
                              <Btn size="sm" variant="outline" onClick={() => setAssignTarget(v)}>
                                📱 تخصيص
                              </Btn>
                            )}
                            <Btn size="sm" variant="danger" onClick={() => handleCancel(v)}>
                              إلغاء
                            </Btn>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Tab 2: Redemption Flow ────────────────────────────────────────────────────

/**
 * 4-step redemption:
 *   step 1 — enter phone (+ optional order amount) → validate eligibility
 *   step 2 — validated: show discount preview → generate OTP
 *   step 3 — OTP sent: show wa.me button + code entry field → verify
 *   step 4 — success: show redemption document with reference code
 */
function RedemptionFlow({ voucher, onClose }) {
  const [step,         setStep]         = useState(1)   // 1 | 2 | 3 | 4
  const [phone,        setPhone]        = useState('')
  const [orderAmount,  setOrderAmount]  = useState('')
  const [otpCode,      setOtpCode]      = useState('')
  const [otpId,        setOtpId]        = useState(null)
  const [otpExpiry,    setOtpExpiry]    = useState(null)
  const [waUrl,        setWaUrl]        = useState('')
  const [qrCode,       setQrCode]       = useState(null)   // base64 PNG from backend
  const [otpMode,      setOtpMode]      = useState('qr')   // 'qr' | 'whatsapp'
  const [eligibility,  setEligibility]  = useState(null)  // {eligible, discount_amount, reason}
  const [document,     setDocument]     = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState(null)
  const [timeLeft,     setTimeLeft]     = useState(null)
  const timerRef = useRef(null)

  // Countdown timer for OTP expiry
  useEffect(() => {
    if (step === 3 && otpExpiry) {
      const tick = () => {
        const secs = Math.max(0, Math.round((new Date(otpExpiry) - Date.now()) / 1000))
        setTimeLeft(secs)
        if (secs === 0) clearInterval(timerRef.current)
      }
      tick()
      timerRef.current = setInterval(tick, 1000)
    }
    return () => clearInterval(timerRef.current)
  }, [step, otpExpiry])

  // Step 1 → validate eligibility
  const handleValidate = async () => {
    if (!phone.trim()) return setError('رقم الهاتف مطلوب')
    setLoading(true); setError(null)
    try {
      const r = await vouchersApi.validateEligibility(voucher.id, {
        phone: phone.trim(),
        order_amount: orderAmount || undefined,
      })
      setEligibility(r.data)
      setStep(2)
    } catch (e) {
      const d = e.response?.data
      if (d?.eligible === false) {
        setEligibility(d)
        setStep(2)
      } else {
        setError(d?.detail || 'خطأ في التحقق من الأهلية')
      }
    } finally { setLoading(false) }
  }

  // Step 2 → send OTP
  const handleSendOtp = async () => {
    setLoading(true); setError(null)
    try {
      const r = await vouchersApi.generateOtp(voucher.id, {
        phone: phone.trim(),
        order_amount: orderAmount || undefined,
      })
      setOtpId(r.data.otp_id)
      setOtpExpiry(r.data.expires_at)
      setWaUrl(r.data.whatsapp_url)
      setQrCode(r.data.qr_code || null)
      setStep(3)
    } catch (e) {
      setError(e.response?.data?.detail || 'خطأ في إرسال OTP')
    } finally { setLoading(false) }
  }

  // Step 3 → verify OTP
  const handleVerify = async () => {
    if (otpCode.length !== 6) return setError('الرمز يجب أن يكون 6 أرقام')
    setLoading(true); setError(null)
    try {
      const r = await vouchersApi.verifyOtp(voucher.id, {
        code: otpCode,
        phone: phone.trim(),
        order_amount: orderAmount || undefined,
      })
      setDocument(r.data.document)
      setStep(4)
    } catch (e) {
      setError(e.response?.data?.detail || 'رمز OTP غير صحيح')
    } finally { setLoading(false) }
  }

  // Resend OTP
  const handleResend = async () => {
    setOtpCode(''); setError(null)
    setLoading(true)
    try {
      const r = await vouchersApi.generateOtp(voucher.id, {
        phone: phone.trim(),
        order_amount: orderAmount || undefined,
      })
      setOtpId(r.data.otp_id)
      setOtpExpiry(r.data.expires_at)
      setWaUrl(r.data.whatsapp_url)
      setQrCode(r.data.qr_code || null)
    } catch (e) {
      setError(e.response?.data?.detail || 'خطأ في إعادة الإرسال')
    } finally { setLoading(false) }
  }

  const tc = TYPE_CFG[voucher.voucher_type] || {}

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        {/* Header */}
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="font-bold text-gray-900 text-sm">استرداد القسيمة</h3>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-xs px-2 py-0.5 rounded-full border ${tc.color}`}>
                {tc.icon} {tc.label}
              </span>
              <span className="font-mono text-xs text-gray-500">{voucher.code}</span>
              <span className="text-xs font-bold text-gray-800">{valueDisplay(voucher)}</span>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>

        {/* Step indicator */}
        <div className="px-5 pt-4 flex items-center gap-1">
          {[1,2,3,4].map(s => (
            <div key={s} className="flex items-center flex-1">
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold
                ${step > s ? 'bg-green-500 text-white' : step === s ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-400'}`}>
                {step > s ? '✓' : s}
              </div>
              {s < 4 && <div className={`flex-1 h-0.5 mx-1 ${step > s ? 'bg-green-400' : 'bg-gray-100'}`} />}
            </div>
          ))}
        </div>
        <div className="px-5 pb-1 flex justify-between text-xs text-gray-400 mt-1">
          <span>الهاتف</span><span>التحقق</span><span>OTP</span><span>الوثيقة</span>
        </div>

        {/* Body */}
        <div className="px-5 py-4">

          {/* ─ Step 1: Phone + amount ─ */}
          {step === 1 && (
            <div className="space-y-4">
              <Field label="رقم هاتف العميل" required>
                <Input
                  value={phone} onChange={e => setPhone(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleValidate()}
                  placeholder="01xxxxxxxxx" dir="ltr"
                  className="text-lg font-mono tracking-widest text-center"
                />
              </Field>
              <Field label="قيمة الطلب (ج.م) — اختياري">
                <Input
                  type="number" value={orderAmount}
                  onChange={e => setOrderAmount(e.target.value)}
                  placeholder="لحساب الخصم تلقائياً" min="0" step="0.01" />
              </Field>
              <ErrorBox msg={error} />
              <Btn variant="primary" size="lg" onClick={handleValidate}
                disabled={loading || !phone} className="w-full">
                {loading ? '...' : '🔍 تحقق من الأهلية'}
              </Btn>
            </div>
          )}

          {/* ─ Step 2: Eligibility result ─ */}
          {step === 2 && eligibility && (
            <div className="space-y-4">
              {eligibility.eligible ? (
                <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
                  <div className="text-2xl mb-1">✅</div>
                  <div className="font-bold text-green-700">العميل مؤهل للاسترداد</div>
                  <div className="text-xs text-gray-500 mt-1 font-mono">{phone}</div>
                  {eligibility.discount_amount > 0 && (
                    <div className="mt-2 inline-flex items-center gap-1 bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full text-sm font-bold">
                      💰 خصم متوقع: {Number(eligibility.discount_amount).toFixed(2)} ج.م
                    </div>
                  )}
                  {eligibility.min_order_value && (
                    <div className="text-xs text-gray-400 mt-1">
                      الحد الأدنى للطلب: {Number(eligibility.min_order_value).toFixed(2)} ج.م
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
                  <div className="text-2xl mb-1">❌</div>
                  <div className="font-bold text-red-700">العميل غير مؤهل</div>
                  <div className="text-xs text-red-600 mt-1">{eligibility.reason}</div>
                </div>
              )}

              <ErrorBox msg={error} />

              <div className="flex gap-2">
                <Btn variant="ghost" onClick={() => { setStep(1); setEligibility(null); setError(null) }} className="flex-1">
                  ← تعديل الهاتف
                </Btn>
                {eligibility.eligible && (
                  <Btn variant="primary" size="lg" onClick={handleSendOtp}
                    disabled={loading} className="flex-1">
                    {loading ? '...' : '📤 إرسال OTP عبر واتساب'}
                  </Btn>
                )}
              </div>
            </div>
          )}

          {/* ─ Step 3: OTP delivery + verification ─ */}
          {step === 3 && (
            <div className="space-y-3">

              {/* Mode switcher */}
              <div className="flex rounded-xl overflow-hidden border border-gray-200 text-xs font-medium">
                <button
                  onClick={() => setOtpMode('qr')}
                  className={`flex-1 py-2 transition-colors ${otpMode === 'qr'
                    ? 'bg-brand-600 text-white'
                    : 'bg-white text-gray-500 hover:bg-gray-50'}`}
                >
                  📷 QR كود — في الصيدلية
                </button>
                <button
                  onClick={() => setOtpMode('whatsapp')}
                  className={`flex-1 py-2 transition-colors ${otpMode === 'whatsapp'
                    ? 'bg-green-600 text-white'
                    : 'bg-white text-gray-500 hover:bg-gray-50'}`}
                >
                  💬 واتساب — عن بُعد
                </button>
              </div>

              {/* ── QR mode ── */}
              {otpMode === 'qr' && (
                <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
                  <p className="text-xs text-gray-500 mb-3 font-medium">
                    اعرض هذا الـ QR للعميل ليمسحه بكاميرا هاتفه
                    <br/>
                    <span className="text-brand-600">لا يظهر الرمز على شاشتك — الأرقام على هاتفه فقط</span>
                  </p>
                  {qrCode ? (
                    <img
                      src={`data:image/png;base64,${qrCode}`}
                      alt="OTP QR Code"
                      className="w-48 h-48 mx-auto rounded-lg shadow-md border-4 border-white"
                    />
                  ) : (
                    <div className="w-48 h-48 mx-auto bg-gray-200 rounded-lg flex items-center justify-center text-gray-400 text-xs">
                      لا يوجد QR
                    </div>
                  )}
                  {timeLeft !== null && (
                    <div className={`mt-3 text-sm font-mono font-bold ${timeLeft < 60 ? 'text-red-600' : 'text-gray-600'}`}>
                      ⏱ {Math.floor(timeLeft/60)}:{String(timeLeft%60).padStart(2,'0')}
                      <span className="text-xs font-normal text-gray-400 mr-1">متبقية</span>
                    </div>
                  )}
                  <p className="text-xs text-gray-400 mt-2">
                    العميل يفتح الكاميرا ← يمسح الكود ← يرى الرقم ← يُخبرك به
                  </p>
                </div>
              )}

              {/* ── WhatsApp mode ── */}
              {otpMode === 'whatsapp' && (
                <div className="bg-green-50 border border-green-200 rounded-xl p-4">
                  <p className="text-xs text-green-700 font-medium text-center mb-3">
                    اضغط لفتح واتساب وإرسال الرمز للعميل عن بُعد
                  </p>
                  <a
                    href={waUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-2 w-full py-3 bg-green-500 text-white rounded-xl font-bold hover:bg-green-600 transition-colors"
                  >
                    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
                    </svg>
                    📤 فتح واتساب وإرسال الرمز
                  </a>
                  {timeLeft !== null && (
                    <div className={`text-center mt-2 text-xs font-mono font-bold ${timeLeft < 60 ? 'text-red-600' : 'text-green-600'}`}>
                      ⏱ {Math.floor(timeLeft/60)}:{String(timeLeft%60).padStart(2,'0')} متبقية
                    </div>
                  )}
                </div>
              )}

              {/* OTP entry — same for both modes */}
              <Field label="أدخل الرمز الذي أعطاه العميل" required>
                <input
                  value={otpCode}
                  onChange={e => setOtpCode(e.target.value.replace(/\D/g,'').slice(0,6))}
                  onKeyDown={e => e.key === 'Enter' && otpCode.length === 6 && handleVerify()}
                  className="w-full border-2 border-gray-300 focus:border-brand-500 rounded-xl px-4 py-3 text-center text-2xl font-mono tracking-[0.5em] focus:outline-none"
                  placeholder="- - - - - -"
                  maxLength={6}
                  dir="ltr"
                />
              </Field>

              <ErrorBox msg={error} />

              <div className="flex gap-2">
                <Btn variant="ghost" size="sm" onClick={handleResend} disabled={loading} className="flex-1">
                  🔄 رمز جديد
                </Btn>
                <Btn variant="success" size="lg" onClick={handleVerify}
                  disabled={loading || otpCode.length !== 6} className="flex-1">
                  {loading ? '...' : '✓ تحقق من الرمز'}
                </Btn>
              </div>
            </div>
          )}

          {/* ─ Step 4: Document created ─ */}
          {step === 4 && document && (
            <div className="space-y-4">
              <div className="text-center">
                <div className="text-5xl mb-2">🎉</div>
                <div className="font-bold text-green-700 text-lg">تم التحقق بنجاح!</div>
                <div className="text-xs text-gray-500 mt-1">وثيقة الاسترداد جاهزة للـ POS</div>
              </div>

              {/* Reference code — the key info */}
              <div className="bg-gray-900 text-white rounded-2xl p-5 text-center">
                <div className="text-xs text-gray-400 mb-1">كود المرجع — يُعطى لكاشير POS</div>
                <div className="text-3xl font-mono font-black tracking-widest text-yellow-400">
                  {document.reference_code}
                </div>
                <div className="text-xs text-gray-400 mt-2">
                  صالح لـ {document.minutes_left} دقيقة
                </div>
              </div>

              {/* Discount summary */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 text-center">
                  <div className="text-xs text-gray-500 mb-1">الخصم</div>
                  <div className="font-bold text-emerald-700 text-lg">
                    {document.discount_applied
                      ? `${Number(document.discount_applied).toFixed(2)} ج.م`
                      : valueDisplay(voucher)}
                  </div>
                </div>
                <div className="bg-gray-50 border border-gray-200 rounded-xl p-3 text-center">
                  <div className="text-xs text-gray-500 mb-1">العميل</div>
                  <div className="font-mono text-gray-700 text-sm">
                    {document.customer_phone_masked}
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-2">
                <Btn variant="outline" size="sm" className="flex-1"
                  onClick={async () => {
                    try {
                      const r = await vouchersApi.documentPrint(document.reference_code)
                      const d = r.data
                      const fmt = (n, dp = 2) => n != null ? Number(n).toFixed(dp) : '—'
                      const win = window.open('', '_blank', 'width=420,height=600')
                      win.document.write(`<!DOCTYPE html><html dir="rtl"><head>
<meta charset="utf-8"/>
<title>وثيقة استرداد — ${d.reference_code}</title>
<style>
  body{font-family:Arial,sans-serif;margin:0;padding:20px;color:#111;font-size:13px}
  h2{text-align:center;font-size:16px;margin:0 0 4px}
  .sub{text-align:center;color:#666;font-size:11px;margin-bottom:16px}
  .refbox{background:#111;color:#FFD700;font-family:monospace;font-size:22px;
    font-weight:900;text-align:center;letter-spacing:4px;padding:14px;border-radius:8px;margin:12px 0}
  table{width:100%;border-collapse:collapse;margin:12px 0}
  td{padding:5px 4px;border-bottom:1px solid #eee;font-size:12px}
  td:first-child{color:#888;width:45%}
  td:last-child{font-weight:600;text-align:left}
  .total{background:#f0fdf4;font-weight:900;font-size:15px}
  .footer{text-align:center;font-size:10px;color:#aaa;margin-top:16px}
  @media print{body{padding:0}.no-print{display:none}}
</style></head><body>
<h2>🎫 وثيقة استرداد قسيمة</h2>
<div class="sub">ElRezeiky Pharmacy — نظام القسائم</div>
<div class="refbox">${d.reference_code}</div>
<table>
  <tr><td>القسيمة</td><td dir="ltr">${d.voucher_code}</td></tr>
  <tr><td>العنوان</td><td>${d.voucher_title}</td></tr>
  <tr><td>نوع الخصم</td><td>${d.discount_value}</td></tr>
  ${d.discount_applied != null ? `<tr class="total"><td>الخصم المطبق</td><td>${fmt(d.discount_applied)} ج.م</td></tr>` : ''}
  ${d.order_amount    != null ? `<tr><td>قيمة الطلب</td><td>${fmt(d.order_amount)} ج.م</td></tr>` : ''}
  <tr><td>العميل</td><td dir="ltr">${d.customer_phone}</td></tr>
  <tr><td>الفرع</td><td>${d.branch_name}</td></tr>
  <tr><td>الموظف</td><td>${d.employee_name}</td></tr>
  <tr><td>الحالة</td><td>${d.status_label}</td></tr>
  ${d.used_at ? `<tr><td>وقت الاستخدام</td><td>${new Date(d.used_at).toLocaleString('ar-EG')}</td></tr>` : ''}
  <tr><td>طُبع بواسطة</td><td>${d.printed_by}</td></tr>
</table>
<div class="footer">طُبع في: ${new Date().toLocaleString('ar-EG')}</div>
<script>window.onload=function(){window.print()}<\/script>
</body></html>`)
                      win.document.close()
                    } catch { alert('خطأ في جلب بيانات الوثيقة') }
                  }}>
                  🖨️ طباعة
                </Btn>
                <Btn variant="whatsapp" size="sm" className="flex-1"
                  onClick={async () => {
                    try {
                      const r = await vouchersApi.documentWhatsapp(document.reference_code)
                      const text = encodeURIComponent(r.data.message_text || '')
                      window.open(`https://wa.me/?text=${text}`, '_blank', 'noopener,noreferrer')
                    } catch {}
                  }}>
                  📱 واتساب
                </Btn>
              </div>

              <Btn variant="ghost" size="lg" onClick={onClose} className="w-full">
                إغلاق
              </Btn>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Tab 3: POS Documents ──────────────────────────────────────────────────────
function DocumentsTab() {
  const [refCode,   setRefCode]   = useState('')
  const [doc,       setDoc]       = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [markLoading, setMarkLoading] = useState(false)
  const [error,     setError]     = useState(null)
  const [success,   setSuccess]   = useState(null)

  const lookup = async () => {
    const code = refCode.trim().toUpperCase()
    if (!code) return
    setLoading(true); setError(null); setDoc(null); setSuccess(null)
    try {
      const r = await vouchersApi.getDocument(code)
      setDoc(r.data)
    } catch (e) {
      setError(e.response?.status === 404
        ? 'الوثيقة غير موجودة'
        : e.response?.data?.detail || 'خطأ في البحث')
    } finally { setLoading(false) }
  }

  const markUsed = async () => {
    if (!doc) return
    setMarkLoading(true); setError(null)
    try {
      const r = await vouchersApi.markDocumentUsed(doc.reference_code, {})
      setSuccess(r.data)
      setDoc(prev => ({ ...prev, status: 'used' }))
    } catch (e) {
      setError(e.response?.data?.detail || 'خطأ في تفعيل الوثيقة')
    } finally { setMarkLoading(false) }
  }

  const sc = doc ? (DOC_STATUS_CFG[doc.status] || {}) : {}

  return (
    <div className="max-w-xl mx-auto space-y-4" dir="rtl">
      <h2 className="text-base font-bold text-gray-800">🏪 التحقق من وثيقة POS</h2>

      {/* Lookup */}
      <div className="flex gap-2">
        <input
          value={refCode}
          onChange={e => setRefCode(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && lookup()}
          className="flex-1 border-2 border-gray-300 focus:border-brand-500 rounded-xl px-4 py-2.5 text-lg font-mono tracking-widest text-center focus:outline-none"
          placeholder="REF-XXXXXXXX"
          dir="ltr"
        />
        <Btn variant="primary" size="lg" onClick={lookup} disabled={loading}>
          {loading ? '...' : '🔍 بحث'}
        </Btn>
      </div>

      <ErrorBox msg={error} />

      {/* Document card */}
      {doc && (
        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
          {/* Status banner */}
          <div className={`px-4 py-3 flex items-center justify-between ${
            doc.status === 'active'   ? 'bg-green-50 border-b border-green-200'  :
            doc.status === 'used'     ? 'bg-blue-50 border-b border-blue-200'    :
            doc.status === 'expired'  ? 'bg-red-50 border-b border-red-200'      :
            'bg-gray-50 border-b border-gray-200'
          }`}>
            <div className="flex items-center gap-2">
              <span className="text-xl">{sc.icon}</span>
              <span className={`font-bold text-sm ${
                doc.status === 'active' ? 'text-green-700' :
                doc.status === 'used'   ? 'text-blue-700'  :
                'text-gray-700'
              }`}>{sc.label}</span>
              {doc.status === 'active' && doc.minutes_left > 0 && (
                <span className="text-xs text-green-600 font-mono">
                  ({doc.minutes_left} دقيقة متبقية)
                </span>
              )}
            </div>
            <span className="font-mono text-sm font-bold text-gray-700">{doc.reference_code}</span>
          </div>

          <div className="p-4 space-y-3">
            {/* Voucher info */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-xs text-gray-400 mb-0.5">القسيمة</div>
                <div className="font-mono text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded inline-block">
                  {doc.voucher_code}
                </div>
                <div className="text-sm font-semibold text-gray-800 mt-0.5">{doc.voucher_title}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400 mb-0.5">الخصم</div>
                <div className="text-xl font-black text-emerald-700">
                  {doc.discount_applied
                    ? `${Number(doc.discount_applied).toFixed(2)} ج.م`
                    : doc.value_display || '—'}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs text-gray-600 border-t border-gray-100 pt-3">
              <div><span className="text-gray-400">العميل: </span>{doc.customer_phone_masked}</div>
              <div><span className="text-gray-400">الفرع: </span>{doc.branch_name || '—'}</div>
              <div><span className="text-gray-400">الموظف: </span>{doc.employee_name || '—'}</div>
              <div>
                <span className="text-gray-400">أُنشئت: </span>
                {new Date(doc.generated_at).toLocaleTimeString('ar-EG', { hour:'2-digit', minute:'2-digit' })}
              </div>
            </div>
          </div>

          {/* Actions */}
          {doc.status === 'active' && (
            <div className="px-4 pb-4 flex gap-2">
              {success ? (
                <div className="flex-1 text-center py-3 bg-green-50 rounded-xl text-green-700 font-bold text-sm">
                  ✅ تم تفعيل الوثيقة — خصم: {Number(success.discount_applied).toFixed(2)} ج.م
                </div>
              ) : (
                <Btn variant="success" size="lg" onClick={markUsed}
                  disabled={markLoading} className="flex-1">
                  {markLoading ? '...' : '✅ تفعيل الوثيقة (POS)'}
                </Btn>
              )}
              <Btn variant="outline" size="md"
                onClick={async () => {
                  try {
                    const r = await vouchersApi.documentWhatsapp(doc.reference_code)
                    const text = encodeURIComponent(r.data.message_text || '')
                    window.open(`https://wa.me/?text=${text}`, '_blank', 'noopener,noreferrer')
                  } catch {}
                }}>
                📱
              </Btn>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Tab 4: Report ─────────────────────────────────────────────────────────────
function ReportTab() {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [dateFrom,  setDateFrom]  = useState('')
  const [dateTo,    setDateTo]    = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const params = {}
      if (dateFrom) params.date_from = dateFrom
      if (dateTo)   params.date_to   = dateTo
      const r = await vouchersApi.report(params)
      setData(r.data)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const fmt = (n, dp = 2) => Number(n || 0).toLocaleString('ar-EG', {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  })

  return (
    <div className="space-y-6" dir="rtl">
      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Field label="من تاريخ">
          <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        </Field>
        <Field label="إلى تاريخ">
          <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
        </Field>
        <div className="pt-5">
          <Btn variant="primary" onClick={load} disabled={loading}>
            {loading ? '...' : '📊 تحديث التقرير'}
          </Btn>
        </div>
      </div>

      {loading && (
        <div className="text-center py-10 text-gray-400 animate-pulse">جاري التحميل...</div>
      )}

      {data && !loading && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-white border border-gray-100 rounded-2xl p-4 text-center shadow-sm">
              <div className="text-3xl font-black text-brand-700">{data.summary?.total_redemptions || 0}</div>
              <div className="text-xs text-gray-500 mt-1">إجمالي الاستردادات</div>
            </div>
            <div className="bg-white border border-gray-100 rounded-2xl p-4 text-center shadow-sm">
              <div className="text-3xl font-black text-emerald-700">
                {fmt(data.summary?.total_discount)}
              </div>
              <div className="text-xs text-gray-500 mt-1">إجمالي الخصومات (ج.م)</div>
            </div>
            <div className="bg-white border border-gray-100 rounded-2xl p-4 text-center shadow-sm">
              <div className="text-3xl font-black text-orange-600">{data.expired_unused || 0}</div>
              <div className="text-xs text-gray-500 mt-1">قسائم منتهية غير مستخدمة</div>
            </div>
          </div>

          {/* Top vouchers */}
          {data.top_vouchers?.length > 0 && (
            <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm">
              <h3 className="font-bold text-gray-700 text-sm mb-3">🏆 أكثر القسائم استخداماً</h3>
              <div className="divide-y divide-gray-50">
                {data.top_vouchers.map((v, i) => (
                  <div key={i} className="flex items-center justify-between py-2 text-sm">
                    <div>
                      <span className="font-mono text-xs text-gray-500 ml-2">{v.voucher__code}</span>
                      <span className="text-gray-800">{v.voucher__title}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-gray-500">{v.count} مرة</span>
                      <span className="font-bold text-emerald-700">{fmt(v.total)} ج.م</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* By employee */}
          {data.by_employee?.length > 0 && (
            <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm">
              <h3 className="font-bold text-gray-700 text-sm mb-3">👤 نشاط الموظفين</h3>
              <div className="divide-y divide-gray-50">
                {data.by_employee.map((e, i) => (
                  <div key={i} className="flex items-center justify-between py-2 text-sm">
                    <span className="text-gray-800">{e.redeemed_by__full_name || '—'}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-gray-500">{e.count} استرداد</span>
                      <span className="font-bold text-emerald-700">{fmt(e.total)} ج.م</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Page Root ─────────────────────────────────────────────────────────────────
export default function VouchersPage() {
  const [activeTab,    setActiveTab]    = useState('vouchers')
  const [redeemTarget, setRedeemTarget] = useState(null)

  const tabs = [
    { key: 'vouchers',  label: '🎫 القسائم' },
    { key: 'redeem',    label: '💳 استرداد' },
    { key: 'documents', label: '🏪 وثائق POS' },
    { key: 'report',    label: '📊 تقارير' },
  ]

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">
      {/* Redemption flow modal */}
      {redeemTarget && (
        <RedemptionFlow
          voucher={redeemTarget}
          onClose={() => setRedeemTarget(null)}
        />
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-2xl">🎫</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">نظام القسائم والخصومات</h1>
            <p className="text-sm text-gray-500">
              إنشاء وإدارة القسائم — التحقق بـ OTP — وثائق POS
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors
                ${activeTab === t.key
                  ? 'bg-brand-600 text-white'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'vouchers' && (
          <VouchersList
            onRedeem={(v) => {
              setRedeemTarget(v)
              setActiveTab('vouchers')
            }}
          />
        )}
        {activeTab === 'redeem' && (
          <div className="max-w-xl mx-auto" dir="rtl">
            <h2 className="text-base font-bold text-gray-800 mb-4">استرداد قسيمة</h2>
            <p className="text-sm text-gray-500 mb-6">
              ابحث عن القسيمة في تبويب "القسائم" ثم اضغط "استرداد"،
              أو استخدم البحث السريع بالكود أدناه.
            </p>
            <QuickLookupRedeem onFound={setRedeemTarget} />
          </div>
        )}
        {activeTab === 'documents' && <DocumentsTab />}
        {activeTab === 'report'    && <ReportTab />}
      </div>
    </div>
  )
}

// ── Quick lookup + redeem from "Redeem" tab ───────────────────────────────────
function QuickLookupRedeem({ onFound }) {
  const [code,    setCode]    = useState('')
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const lookup = async () => {
    const c = code.trim().toUpperCase()
    if (!c) return
    setLoading(true); setError(null)
    try {
      const r = await vouchersApi.lookup(c)
      if (r.data.status !== 'active') {
        setError(`القسيمة ${r.data.status_label || 'غير نشطة'}`)
        return
      }
      onFound(r.data)
    } catch (e) {
      setError(e.response?.data?.detail || 'القسيمة غير موجودة')
    } finally { setLoading(false) }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5">
      <Field label="كود القسيمة" required>
        <input
          value={code}
          onChange={e => setCode(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && lookup()}
          className="w-full border-2 border-gray-300 focus:border-brand-500 rounded-xl px-4 py-3 text-lg font-mono tracking-widest text-center focus:outline-none"
          placeholder="VCH-XXXXXXXX"
          dir="ltr"
        />
      </Field>
      <ErrorBox msg={error} />
      <Btn variant="primary" size="lg" onClick={lookup} disabled={loading} className="w-full mt-4">
        {loading ? '...' : '🔍 بحث واسترداد'}
      </Btn>
    </div>
  )
}
