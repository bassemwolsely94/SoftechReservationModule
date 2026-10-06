/**
 * MobileVoucherRedeemPage.jsx — voucher redemption at POS on a phone
 * (route: /m/vouchers).
 *
 * Flow: pick voucher → enter customer phone + order amount → send OTP →
 * customer reads/receives the code → verify → redemption document.
 * Reuses the existing voucher OTP endpoints (never stores plain OTP).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { vouchersApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'

export default function MobileVoucherRedeemPage() {
  const [voucher, setVoucher] = useState(null)
  const [step, setStep]   = useState('list')   // list → form → otp → done
  const [phone, setPhone] = useState('')
  const [amount, setAmount] = useState('')
  const [itemIds, setItemIds] = useState([])   // selected applicable items (TD-M006)
  const [code, setCode]   = useState('')
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')
  const [otpInfo, setOtpInfo] = useState(null)
  const [doc, setDoc]     = useState(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-vouchers'],
    queryFn: () => vouchersApi.list({ status: 'active' }).then(r => r.data),
    enabled: step === 'list',
  })
  const vouchers = Array.isArray(data) ? data : (data?.results || [])

  function pick(v) { setVoucher(v); setStep('form'); setError(''); setPhone(''); setAmount(''); setItemIds([]); setCode(''); setOtpInfo(null); setDoc(null) }
  function reset() { setVoucher(null); setStep('list'); setError('') }

  const restrictedItems = voucher?.applicable_items_detail || []

  async function sendOtp() {
    if (!phone.trim()) { setError('رقم الهاتف مطلوب'); return }
    if (restrictedItems.length && itemIds.length === 0) {
      setError('هذه القسيمة مقصورة على أصناف محددة — اختر صنفاً واحداً على الأقل'); return
    }
    setBusy(true); setError('')
    try {
      const { data } = await vouchersApi.generateOtp(voucher.id, {
        phone: phone.trim(), order_amount: amount || undefined,
        item_ids: itemIds.length ? itemIds : undefined,
      })
      setOtpInfo(data); setStep('otp')
    } catch (e) { setError(e.response?.data?.detail || e.response?.data?.error || 'تعذّر إرسال الرمز') }
    finally { setBusy(false) }
  }

  async function verify() {
    if (code.trim().length < 4) { setError('أدخل الرمز'); return }
    setBusy(true); setError('')
    try {
      const { data } = await vouchersApi.verifyOtp(voucher.id, {
        code: code.trim(), phone: phone.trim(), order_amount: amount || undefined,
        item_ids: itemIds.length ? itemIds : undefined,
      })
      setDoc(data); setStep('done')
    } catch (e) { setError(e.response?.data?.detail || e.response?.data?.error || 'رمز غير صحيح') }
    finally { setBusy(false) }
  }

  // ── Step: voucher list ──
  if (step === 'list') {
    return (
      <div className="p-3 space-y-3">
        <h1 className="text-base font-bold text-gray-900">صرف قسيمة</h1>
        {isLoading ? <MobileLoading />
          : isError ? <MobileError text="تعذّر تحميل القسائم" onRetry={refetch} />
          : vouchers.length === 0 ? <MobileEmpty icon="🎫" text="لا توجد قسائم فعّالة" />
          : (
            <div className="space-y-2.5">
              {vouchers.map(v => (
                <button key={v.id} onClick={() => pick(v)}
                  className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50">
                  <div className="font-bold text-sm text-gray-900">{v.name || v.title || `قسيمة #${v.id}`}</div>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {v.code && <span className="text-[11px] font-mono text-gray-600 bg-gray-100 px-2 py-0.5 rounded">{v.code}</span>}
                    {(v.discount_display || v.value || v.discount_value) &&
                      <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
                        {v.discount_display || `${v.value || v.discount_value}`}
                      </span>}
                  </div>
                </button>
              ))}
            </div>
          )}
      </div>
    )
  }

  // ── Step: success ──
  if (step === 'done') {
    return (
      <div className="p-3 space-y-4">
        <div className="bg-white rounded-2xl border border-gray-200 p-6 text-center space-y-2">
          <div className="text-4xl">✅</div>
          <h2 className="font-bold text-gray-800">تم التحقق وإنشاء مستند الصرف</h2>
          {doc?.document_number && <p className="text-sm text-gray-500">مستند: <span className="font-mono">{doc.document_number}</span></p>}
          {doc?.expires_at && <p className="text-xs text-gray-400">صالح حتى: {doc.expires_at}</p>}
        </div>
        <button onClick={reset} className="btn-primary w-full">صرف قسيمة أخرى</button>
      </div>
    )
  }

  // ── Steps: form + otp ──
  return (
    <div className="p-3 space-y-3">
      <button onClick={reset} className="text-sm text-gray-500">→ الرجوع للقسائم</button>
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="font-bold text-sm text-gray-900">{voucher.name || voucher.title || `قسيمة #${voucher.id}`}</div>
      </div>

      {step === 'form' && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3">
          <div>
            <label className="label">هاتف العميل *</label>
            <input className="input-field w-full" dir="ltr" inputMode="tel" type="tel" placeholder="01xxxxxxxxx"
              value={phone} onChange={e => setPhone(e.target.value)} />
          </div>
          <div>
            <label className="label">قيمة الطلب (اختياري)</label>
            <input className="input-field w-full" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} />
          </div>
          {restrictedItems.length > 0 && (
            <div>
              <label className="label">الأصناف المؤهلة في الطلب *</label>
              <div className="space-y-1.5">
                {restrictedItems.map(it => {
                  const on = itemIds.includes(it.id)
                  return (
                    <button type="button" key={it.id}
                      onClick={() => setItemIds(prev => on ? prev.filter(x => x !== it.id) : [...prev, it.id])}
                      className={`w-full text-right px-3 py-2 rounded-xl border text-sm transition-colors ${
                        on ? 'bg-brand-50 border-brand-300 text-brand-700 font-medium'
                           : 'border-gray-200 text-gray-600 active:bg-gray-50'}`}>
                      {on ? '✓ ' : ''}{it.name}
                    </button>
                  )
                })}
              </div>
              <p className="text-[11px] text-gray-400 mt-1">قسيمة مقصورة على أصناف محددة — أكّد وجودها في الطلب.</p>
            </div>
          )}
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button onClick={sendOtp} disabled={busy} className="btn-primary w-full py-3 disabled:opacity-50">
            {busy ? 'جارٍ الإرسال...' : 'إرسال رمز التحقق'}
          </button>
        </div>
      )}

      {step === 'otp' && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3">
          <p className="text-sm text-gray-500 text-center">أُرسل رمز للعميل على {phone}. أدخله للتأكيد.</p>
          {otpInfo?.whatsapp_url && (
            <a href={otpInfo.whatsapp_url} target="_blank" rel="noreferrer"
              className="block text-center text-sm bg-green-50 text-green-700 border border-green-200 rounded-xl py-2 font-medium">💬 إرسال عبر واتساب</a>
          )}
          <input className="input-field w-full text-center text-2xl tracking-[0.4em] font-mono" dir="ltr"
            inputMode="numeric" placeholder="------" value={code} onChange={e => setCode(e.target.value)} />
          {error && <div className="text-sm text-red-600 text-center">{error}</div>}
          <button onClick={verify} disabled={busy} className="btn-primary w-full py-3 disabled:opacity-50">
            {busy ? 'جارٍ التحقق...' : 'تحقق وصرف'}
          </button>
          <button onClick={() => { setStep('form'); setError('') }} className="text-xs text-gray-400 w-full">← تغيير الرقم</button>
        </div>
      )}
    </div>
  )
}
