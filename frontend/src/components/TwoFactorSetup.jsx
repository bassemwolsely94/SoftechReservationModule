/**
 * TwoFactorSetup.jsx — TOTP enrollment flow (QR → confirm code → backup codes).
 *
 * Used in two places:
 *   • LoginPage, during *forced* enrollment (pass `mfaToken` from the login
 *     response; enabling returns JWTs so the user is logged in immediately).
 *   • SettingsPage, for *voluntary* enrollment (no mfaToken — uses the JWT session).
 *
 * Calls onComplete(data) after enabling. `data` always has `backup_codes`; in the
 * forced-login case it also carries { access, refresh, user }.
 */
import { useState, useEffect } from 'react'
import { authApi } from '../api/client'

export default function TwoFactorSetup({ mfaToken = null, onComplete, onCancel }) {
  const [loading, setLoading] = useState(true)
  const [secret, setSecret]   = useState('')
  const [qr, setQr]           = useState('')
  const [code, setCode]       = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]     = useState('')
  const [backupCodes, setBackupCodes] = useState(null)
  const [pendingData, setPendingData] = useState(null)

  useEffect(() => {
    let alive = true
    authApi.setup2fa(mfaToken)
      .then(r => { if (alive) { setSecret(r.data.secret); setQr(r.data.qr_png) } })
      .catch(() => { if (alive) setError('تعذّر بدء الإعداد، حاول مجدداً') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [mfaToken])

  async function confirm() {
    if (code.trim().length < 6) { setError('أدخل الرمز المكوّن من 6 أرقام'); return }
    setSubmitting(true); setError('')
    try {
      const { data } = await authApi.enable2fa(code.trim(), mfaToken)
      setBackupCodes(data.backup_codes || [])
      setPendingData(data)
    } catch (e) {
      setError(e.response?.data?.error || 'رمز التحقق غير صحيح')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Step 2: show backup codes, then finish ──
  if (backupCodes) {
    return (
      <div className="space-y-4" dir="rtl">
        <div className="text-center">
          <div className="text-3xl mb-1">✅</div>
          <h3 className="font-bold text-gray-800">تم تفعيل المصادقة الثنائية</h3>
          <p className="text-sm text-gray-500 mt-1">احفظ رموز الاسترجاع في مكان آمن — كل رمز يُستخدم مرة واحدة.</p>
        </div>
        <div className="grid grid-cols-2 gap-2 bg-gray-50 border border-gray-200 rounded-xl p-4">
          {backupCodes.map(c => (
            <div key={c} className="font-mono text-sm text-gray-800 text-center bg-white border border-gray-200 rounded py-1.5" dir="ltr">{c}</div>
          ))}
        </div>
        <button
          onClick={() => onComplete?.(pendingData)}
          className="btn-primary w-full"
        >
          حفظت الرموز — متابعة
        </button>
      </div>
    )
  }

  // ── Step 1: QR + confirm ──
  return (
    <div className="space-y-4" dir="rtl">
      <div className="text-center">
        <h3 className="font-bold text-gray-800">إعداد المصادقة الثنائية</h3>
        <p className="text-sm text-gray-500 mt-1">
          امسح رمز QR بتطبيق Google Authenticator (أو أي تطبيق مصادقة) ثم أدخل الرمز.
        </p>
      </div>

      {loading ? (
        <div className="text-center text-sm text-gray-400 py-8">جارٍ التحميل...</div>
      ) : (
        <>
          {qr && (
            <div className="flex justify-center">
              <img src={qr} alt="QR" className="w-44 h-44 border border-gray-200 rounded-xl" />
            </div>
          )}
          {secret && (
            <div className="text-center text-xs text-gray-500">
              أو أدخل المفتاح يدوياً:
              <div className="font-mono text-sm text-gray-700 mt-1 break-all bg-gray-50 border border-gray-200 rounded px-2 py-1" dir="ltr">{secret}</div>
            </div>
          )}
          <div>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={e => { if (e.key === 'Enter') confirm() }}
              placeholder="000000"
              className="input-field w-full text-center text-2xl tracking-[0.4em] font-mono"
              dir="ltr"
              autoFocus
            />
          </div>
          {error && <div className="text-sm text-red-600 text-center">{error}</div>}
          <div className="flex gap-2">
            {onCancel && (
              <button onClick={onCancel} disabled={submitting} className="btn-secondary flex-1">إلغاء</button>
            )}
            <button onClick={confirm} disabled={submitting} className="btn-primary flex-1 disabled:opacity-50">
              {submitting ? 'جارٍ التأكيد...' : 'تأكيد وتفعيل'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
