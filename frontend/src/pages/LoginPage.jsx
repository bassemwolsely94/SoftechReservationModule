import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import useAuthStore from '../store/authStore'
import { authApi } from '../api/client'
import TwoFactorSetup from '../components/TwoFactorSetup'
import BrandMark from '../components/BrandMark'

// Phone-sized screen → send users to the lean mobile web surface (/m) instead of
// the desktop app, which uses a hover-driven sidebar that doesn't work on touch.
function isPhoneViewport() {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(max-width: 768px)').matches
}

function targetAfterAuth(role) {
  if (role === 'delivery') return '/rider'
  return isPhoneViewport() ? '/m' : '/dashboard'
}

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login, setSession } = useAuthStore()
  const navigate = useNavigate()

  // 'credentials' → 'verify' (enter TOTP) | 'setup' (forced enrollment)
  const [step, setStep]         = useState('credentials')
  const [mfaToken, setMfaToken] = useState('')
  const [code, setCode]         = useState('')
  const [remember, setRemember] = useState(false)

  const finish = (user) => navigate(targetAfterAuth(user?.role))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(username, password)
      if (res.mfa === 'verify')      { setMfaToken(res.mfaToken); setStep('verify') }
      else if (res.mfa === 'setup')  { setMfaToken(res.mfaToken); setStep('setup') }
      else                           { finish(res.user) }
    } catch (err) {
      setError(err.response?.data?.error || 'حدث خطأ في تسجيل الدخول')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await authApi.verify2fa(mfaToken, code.trim(), remember)
      finish(setSession(data))
    } catch (err) {
      setError(err.response?.data?.error || 'رمز التحقق غير صحيح')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-700 via-brand-600 to-brand-800 font-cairo" dir="rtl">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-white rounded-2xl shadow-xl mb-4">
            <BrandMark size={52} />
          </div>
          <h1 className="text-white text-2xl font-bold">صيدليات الرزيقي</h1>
          <p className="text-brand-200 text-sm mt-1">منصة العمليات الداخلية</p>
        </div>

        {/* Form */}
        <div className="bg-white rounded-2xl shadow-2xl p-8">
          <h2 className="text-gray-800 font-bold text-lg mb-6 text-center">
            {step === 'verify' ? 'التحقق بخطوتين' : step === 'setup' ? 'تأمين الحساب' : 'تسجيل الدخول'}
          </h2>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4 animate-fade-in">
              {error}
            </div>
          )}

          {step === 'credentials' && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">اسم المستخدم</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="input-field"
                placeholder="أدخل اسم المستخدم"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="label">كلمة المرور</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="input-field pl-10"
                  placeholder="أدخل كلمة المرور"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                  tabIndex={-1}
                  title={showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                >
                  {showPassword ? (
                    /* Eye-off icon */
                    <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 3l18 18M10.477 10.477A3 3 0 0013.5 13.5M6.5 6.5A9.77 9.77 0 003 12c1.636 3.604 5.18 6 9 6a9.77 9.77 0 004.5-1.1M9 9a3 3 0 014.24 4.24M17.5 17.5A9.77 9.77 0 0021 12c-1.636-3.604-5.18-6-9-6a9.77 9.77 0 00-2.5.33" />
                    </svg>
                  ) : (
                    /* Eye icon */
                    <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.477 0 8.268 2.943 9.542 7-1.274 4.057-5.065 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full mt-2 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? 'جارٍ الدخول...' : 'دخول'}
            </button>
          </form>
          )}

          {step === 'verify' && (
            <form onSubmit={handleVerify} className="space-y-4">
              <p className="text-sm text-gray-500 text-center">
                أدخل الرمز المكوّن من 6 أرقام من تطبيق المصادقة، أو أحد رموز الاسترجاع.
              </p>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={e => setCode(e.target.value)}
                className="input-field text-center text-2xl tracking-[0.4em] font-mono"
                placeholder="000000"
                dir="ltr"
                autoFocus
              />
              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
                الوثوق بهذا الجهاز لمدة 30 يوماً
              </label>
              <button
                type="submit"
                disabled={loading}
                className="btn-primary w-full disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? 'جارٍ التحقق...' : 'تحقق'}
              </button>
              <button
                type="button"
                onClick={() => { setStep('credentials'); setCode(''); setError('') }}
                className="text-xs text-gray-400 hover:text-gray-600 w-full"
              >
                ← الرجوع
              </button>
            </form>
          )}

          {step === 'setup' && (
            <>
              <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4 text-center">
                دورك يتطلب تفعيل المصادقة الثنائية قبل المتابعة.
              </p>
              <TwoFactorSetup
                mfaToken={mfaToken}
                onComplete={(data) => { if (data?.access) finish(setSession(data)) }}
              />
            </>
          )}
        </div>

        <p className="text-center text-brand-200 text-xs mt-6">
          ElRezeiky Pharmacy Operations Platform v1.0
        </p>
      </div>
    </div>
  )
}
