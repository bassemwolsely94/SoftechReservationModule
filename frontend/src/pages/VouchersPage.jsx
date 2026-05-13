import { useState, useEffect, useCallback } from 'react'
import { vouchersApi } from '../api/client'

// ── constants ─────────────────────────────────────────────────────────────────

const TYPE_LABELS = {
  discount_pct:  { label: 'خصم %',         icon: '🏷️',  color: 'bg-blue-50 text-blue-700' },
  discount_fixed:{ label: 'خصم ثابت',      icon: '💰',  color: 'bg-purple-50 text-purple-700' },
  credit:        { label: 'رصيد نقدي',     icon: '💳',  color: 'bg-teal-50 text-teal-700' },
  free_item:     { label: 'صنف مجاني',     icon: '🎁',  color: 'bg-rose-50 text-rose-700' },
}
const STATUS_CONFIG = {
  active:   { label: 'نشط',         color: 'bg-green-100 text-green-700' },
  used:     { label: 'مُستخدَم',   color: 'bg-gray-100 text-gray-500' },
  expired:  { label: 'منتهي',       color: 'bg-red-100 text-red-600' },
  cancelled:{ label: 'ملغى',        color: 'bg-gray-100 text-gray-400' },
}

function voucherValue(v) {
  switch (v.voucher_type) {
    case 'discount_pct':   return `${v.discount_pct}%`
    case 'discount_fixed': return `${Number(v.discount_amount).toFixed(2)} ج.م`
    case 'credit':         return `${Number(v.credit_amount).toFixed(2)} ج.م`
    case 'free_item':      return v.free_item_name || '—'
    default: return '—'
  }
}

// ── OTP Redemption Panel ──────────────────────────────────────────────────────

function OtpPanel({ voucher, onClose }) {
  const [phase,  setPhase]  = useState('lookup')  // lookup | sent | verify | success
  const [phone,  setPhone]  = useState('')
  const [code,   setCode]   = useState('')
  const [result, setResult] = useState(null)
  const [loading,setLoading]= useState(false)
  const [error,  setError]  = useState(null)

  const sendOtp = async () => {
    if (!phone) return
    setLoading(true); setError(null)
    try {
      await vouchersApi.generateOtp(voucher.id, phone)
      setPhase('sent')
    } catch (e) {
      setError(e.response?.data?.detail || 'خطأ في إرسال OTP')
    } finally {
      setLoading(false)
    }
  }

  const verify = async () => {
    if (!code) return
    setLoading(true); setError(null)
    try {
      const r = await vouchersApi.verifyOtp(voucher.id, code, phone)
      setResult(r.data)
      setPhase('success')
    } catch (e) {
      setError(e.response?.data?.detail || 'رمز غير صحيح')
    } finally {
      setLoading(false)
    }
  }

  const typeCfg = TYPE_LABELS[voucher.voucher_type] || {}
  const stCfg   = STATUS_CONFIG[voucher.status] || {}

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
        {/* Voucher info */}
        <div className="text-center mb-5">
          <span className="text-3xl">{typeCfg.icon}</span>
          <h3 className="font-bold text-gray-900 mt-1">{voucher.title}</h3>
          <div className={`inline-block mt-1 px-3 py-1 rounded-full text-sm font-bold ${typeCfg.color}`}>
            {voucherValue(voucher)}
          </div>
          <div className="font-mono text-xs text-gray-400 mt-1">{voucher.code}</div>
          <div className={`inline-block mt-1 text-xs px-2 py-0.5 rounded-full ${stCfg.color}`}>
            {stCfg.label}
          </div>
        </div>

        {phase === 'lookup' && (
          <>
            <label className="text-xs text-gray-600 block mb-1">رقم هاتف العميل</label>
            <input
              value={phone}
              onChange={e => setPhone(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendOtp()}
              className="w-full border border-gray-300 rounded-xl px-4 py-2.5 text-center text-lg font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-brand-400"
              placeholder="01xxxxxxxxx"
              dir="ltr"
            />
            {error && <div className="mt-2 text-xs text-red-600 text-center">{error}</div>}
            <button onClick={sendOtp} disabled={loading || !phone}
              className="mt-4 w-full py-3 bg-brand-600 text-white rounded-xl font-bold hover:bg-brand-700 disabled:opacity-50">
              {loading ? '...' : '📤 إرسال رمز OTP'}
            </button>
          </>
        )}

        {phase === 'sent' && (
          <>
            <div className="text-center text-sm text-gray-600 mb-4">
              تم إرسال رمز OTP إلى <span className="font-mono font-bold">{phone}</span>
              <br /><span className="text-xs text-gray-400">صالح لمدة 3 دقائق</span>
            </div>
            <label className="text-xs text-gray-600 block mb-1">أدخل رمز OTP</label>
            <input
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={e => e.key === 'Enter' && code.length === 6 && verify()}
              className="w-full border border-gray-300 rounded-xl px-4 py-3 text-center text-2xl font-mono tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-brand-400"
              placeholder="——————"
              maxLength={6}
              dir="ltr"
            />
            {error && <div className="mt-2 text-xs text-red-600 text-center">{error}</div>}
            <button onClick={verify} disabled={loading || code.length !== 6}
              className="mt-4 w-full py-3 bg-green-600 text-white rounded-xl font-bold hover:bg-green-700 disabled:opacity-50">
              {loading ? '...' : '✓ تحقق من الرمز'}
            </button>
            <button onClick={() => { setCode(''); setError(null); sendOtp() }}
              className="mt-2 w-full py-2 text-xs text-gray-400 hover:text-gray-600">
              إعادة إرسال الرمز
            </button>
          </>
        )}

        {phase === 'success' && (
          <div className="text-center">
            <div className="text-5xl mb-3">✅</div>
            <div className="font-bold text-green-700 text-lg mb-1">تم التحقق بنجاح!</div>
            <div className={`inline-block px-3 py-1.5 rounded-xl text-sm font-bold ${typeCfg.color} mb-3`}>
              {typeCfg.icon} {typeCfg.label}: {voucherValue(result?.voucher || voucher)}
            </div>
            <div className="text-xs text-gray-500">
              الاستخدام: {result?.voucher?.times_used} / {result?.voucher?.max_uses}
            </div>
          </div>
        )}

        <button onClick={onClose}
          className="mt-5 w-full py-2 bg-gray-100 text-gray-600 rounded-xl text-sm hover:bg-gray-200">
          إغلاق
        </button>
      </div>
    </div>
  )
}

// ── Create Form ───────────────────────────────────────────────────────────────

function CreateVoucherModal({ onClose, onCreate }) {
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({
    title: '', description: '', voucher_type: 'discount_pct',
    discount_pct: '', discount_amount: '', credit_amount: '',
    valid_from: today, valid_until: '', max_uses: 1, notes: '',
  })
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const f = (key, val) => setForm(prev => ({ ...prev, [key]: val }))

  const submit = async () => {
    setSaving(true); setError(null)
    try {
      const r = await vouchersApi.create(form)
      onCreate(r.data)
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'string' ? d : Object.values(d || {}).flat().join(' | '))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto" dir="rtl">
        <h3 className="font-bold text-gray-900 mb-5 text-lg">إنشاء قسيمة جديدة</h3>
        <div className="space-y-4">
          <div>
            <label className="text-xs text-gray-600 block mb-1">العنوان *</label>
            <input value={form.title} onChange={e => f('title', e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">النوع *</label>
            <select value={form.voucher_type} onChange={e => f('voucher_type', e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
              {Object.entries(TYPE_LABELS).map(([v, c]) => (
                <option key={v} value={v}>{c.icon} {c.label}</option>
              ))}
            </select>
          </div>

          {/* Type-specific fields */}
          {form.voucher_type === 'discount_pct' && (
            <div>
              <label className="text-xs text-gray-600 block mb-1">نسبة الخصم % *</label>
              <input type="number" value={form.discount_pct} onChange={e => f('discount_pct', e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                min="0" max="100" placeholder="10" />
            </div>
          )}
          {form.voucher_type === 'discount_fixed' && (
            <div>
              <label className="text-xs text-gray-600 block mb-1">مبلغ الخصم (ج.م) *</label>
              <input type="number" value={form.discount_amount} onChange={e => f('discount_amount', e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                min="0" placeholder="50.000" />
            </div>
          )}
          {form.voucher_type === 'credit' && (
            <div>
              <label className="text-xs text-gray-600 block mb-1">قيمة الرصيد (ج.م) *</label>
              <input type="number" value={form.credit_amount} onChange={e => f('credit_amount', e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                min="0" placeholder="100.000" />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">صالح من *</label>
              <input type="date" value={form.valid_from} onChange={e => f('valid_from', e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">صالح حتى</label>
              <input type="date" value={form.valid_until} onChange={e => f('valid_until', e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400" />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">الحد الأقصى للاستخدام</label>
            <input type="number" value={form.max_uses} onChange={e => f('max_uses', e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              min="1" />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">ملاحظات</label>
            <textarea value={form.notes} onChange={e => f('notes', e.target.value)} rows={2}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-400" />
          </div>
        </div>
        {error && <div className="mt-3 text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg border border-red-200">{error}</div>}
        <div className="flex gap-2 mt-5">
          <button onClick={submit} disabled={saving}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-xl font-medium hover:bg-brand-700 disabled:opacity-50 text-sm">
            {saving ? 'جاري الإنشاء...' : 'إنشاء القسيمة'}
          </button>
          <button onClick={onClose}
            className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-xl font-medium hover:bg-gray-200 text-sm">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

// ── Lookup bar ────────────────────────────────────────────────────────────────

function LookupBar({ onFound }) {
  const [code,    setCode]    = useState('')
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const lookup = async () => {
    if (!code.trim()) return
    setLoading(true); setError(null)
    try {
      const r = await vouchersApi.lookup(code.trim().toUpperCase())
      onFound(r.data)
    } catch (e) {
      setError(e.response?.data?.detail || 'القسيمة غير موجودة')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input value={code} onChange={e => setCode(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && lookup()}
        className="border border-gray-300 rounded-xl px-4 py-2 text-sm font-mono w-48 focus:outline-none focus:ring-2 focus:ring-brand-400"
        placeholder="VCH-XXXXXXXX"
        dir="ltr"
      />
      <button onClick={lookup} disabled={loading}
        className="px-3 py-2 bg-gray-800 text-white rounded-xl text-sm font-medium hover:bg-gray-700 disabled:opacity-50">
        {loading ? '...' : '🔍 بحث'}
      </button>
      {error && <span className="text-xs text-red-500">{error}</span>}
    </div>
  )
}

// ── Page Root ─────────────────────────────────────────────────────────────────

export default function VouchersPage() {
  const [vouchers,     setVouchers]     = useState([])
  const [loading,      setLoading]      = useState(true)
  const [showCreate,   setShowCreate]   = useState(false)
  const [otpVoucher,   setOtpVoucher]   = useState(null)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterType,   setFilterType]   = useState('')
  const [searchQ,      setSearchQ]      = useState('')
  const [toast,        setToast]        = useState(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const loadVouchers = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterStatus) params.status = filterStatus
      if (filterType)   params.type   = filterType
      if (searchQ)      params.search = searchQ
      const r = await vouchersApi.list(params)
      setVouchers(r.data.results || r.data)
    } finally {
      setLoading(false)
    }
  }, [filterStatus, filterType, searchQ])

  useEffect(() => { loadVouchers() }, [loadVouchers])

  const handleCancel = async (v) => {
    if (!confirm(`إلغاء القسيمة "${v.code}"؟`)) return
    await vouchersApi.cancel(v.id)
    showToast('تم إلغاء القسيمة')
    loadVouchers()
  }

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">

      {toast && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-lg text-sm font-medium
          ${toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
          {toast.msg}
        </div>
      )}

      {showCreate && (
        <CreateVoucherModal
          onClose={() => setShowCreate(false)}
          onCreate={() => { setShowCreate(false); loadVouchers(); showToast('تم إنشاء القسيمة ✓') }}
        />
      )}

      {otpVoucher && (
        <OtpPanel voucher={otpVoucher} onClose={() => { setOtpVoucher(null); loadVouchers() }} />
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🎫</span>
            <div>
              <h1 className="text-xl font-bold text-gray-900">القسائم والـ OTP</h1>
              <p className="text-sm text-gray-500">إنشاء وإدارة قسائم الخصم مع التحقق بالرمز</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Quick lookup */}
            <LookupBar onFound={v => setOtpVoucher(v)} />
            <button onClick={() => setShowCreate(true)}
              className="px-4 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
              + قسيمة جديدة
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-3 mt-4 flex-wrap items-center">
          <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-brand-400"
            placeholder="بحث بالكود أو العنوان..." />
          <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
            <option value="">كل الحالات</option>
            {Object.entries(STATUS_CONFIG).map(([v, c]) => <option key={v} value={v}>{c.label}</option>)}
          </select>
          <select value={filterType} onChange={e => setFilterType(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400">
            <option value="">كل الأنواع</option>
            {Object.entries(TYPE_LABELS).map(([v, c]) => <option key={v} value={v}>{c.icon} {c.label}</option>)}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 animate-pulse">جاري التحميل...</div>
        ) : vouchers.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">🎫</div>
            <div className="text-gray-500 font-medium mb-2">لا توجد قسائم</div>
            <button onClick={() => setShowCreate(true)}
              className="mt-4 px-5 py-2.5 bg-brand-600 text-white rounded-xl font-medium text-sm hover:bg-brand-700">
              + قسيمة جديدة
            </button>
          </div>
        ) : (
          <table className="w-full text-right">
            <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
              <tr>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500">الكود</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500">العنوان</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500">النوع</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">القيمة</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">الاستخدام</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500">الصلاحية</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">الحالة</th>
                <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-center">إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {vouchers.map(v => {
                const typeCfg = TYPE_LABELS[v.voucher_type] || {}
                const stCfg   = STATUS_CONFIG[v.status] || {}
                return (
                  <tr key={v.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">{v.code}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-gray-800">{v.title}</div>
                      {v.customer_name && <div className="text-xs text-gray-400">{v.customer_name}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${typeCfg.color}`}>
                        {typeCfg.icon} {typeCfg.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center font-bold text-sm">{voucherValue(v)}</td>
                    <td className="px-4 py-3 text-center text-sm text-gray-600">
                      {v.times_used} / {v.max_uses}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {v.valid_from}
                      {v.valid_until && <span className="text-gray-400"> → {v.valid_until}</span>}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${stCfg.color}`}>
                        {stCfg.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 justify-center">
                        {v.status === 'active' && (
                          <button onClick={() => setOtpVoucher(v)}
                            className="px-2.5 py-1 bg-brand-600 text-white rounded-lg text-xs font-medium hover:bg-brand-700">
                            OTP
                          </button>
                        )}
                        {v.status === 'active' && (
                          <button onClick={() => handleCancel(v)}
                            className="px-2.5 py-1 border border-red-300 text-red-500 rounded-lg text-xs hover:bg-red-50">
                            إلغاء
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
