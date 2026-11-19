import { useEffect, useRef, useState } from 'react'
import useAuthStore from '../store/authStore'
import { authApi } from '../api/client'
import { loginUrlFor, setReloginHandler } from '../api/sessionExpiry'

// Full audit FE-12: when the session expires mid-work, the same user signs in again here, over
// the page — the page underneath stays mounted, so an unsaved form, a POS basket or a claim being
// edited is kept, and the request that hit the expiry is retried once they are back.
//
// Only the same account can continue (the username is fixed). An account that has to enrol 2FA
// first, or a user who chooses another account, goes to the full login page, which returns to
// this page afterwards (?next=).
// The server's own words when it gives them; "too many tries" and "no connection" are not a wrong
// password, so they are never reported as one.
function loginError(err, fallback) {
  const data = err?.response?.data
  if (data?.error) return data.error
  if (err?.response?.status === 429) return 'محاولات دخول كثيرة — انتظر دقيقة ثم حاول مرة أخرى'
  if (!err?.response) return 'لا يوجد اتصال بالسيرفر — حاول مرة أخرى'
  if (typeof data?.detail === 'string' && data.detail.length <= 160) return data.detail
  return fallback
}

export default function SessionExpiredOverlay() {
  const user = useAuthStore(s => s.user)
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const setSession = useAuthStore(s => s.setSession)

  const [open, setOpen] = useState(false)
  const [step, setStep] = useState('credentials')   // 'credentials' → 'verify' (TOTP)
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [mfaToken, setMfaToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef(null)                      // { promise, resolve, reject } shared by every waiter
  const returnFocus = useRef(null)

  useEffect(() => {
    if (!isAuthenticated || !user?.username) return undefined
    return setReloginHandler(() => {
      if (!pending.current) {
        let resolve, reject
        const promise = new Promise((res, rej) => { resolve = res; reject = rej })
        pending.current = { promise, resolve, reject }
        returnFocus.current = document.activeElement      // the field the user was typing in
        setStep('credentials'); setPassword(''); setCode(''); setError(''); setOpen(true)
      }
      return pending.current.promise
    })
  }, [isAuthenticated, user?.username])

  if (!open) return null

  const settle = (ok) => {
    const p = pending.current
    pending.current = null
    setOpen(false); setPassword(''); setCode(''); setMfaToken('')
    if (ok) p?.resolve(); else p?.reject(new Error('relogin cancelled'))
    const el = returnFocus.current
    returnFocus.current = null
    if (ok && el?.isConnected && typeof el.focus === 'function') setTimeout(() => el.focus(), 0)
  }

  const toLoginPage = () => {
    settle(false)
    window.location.href = loginUrlFor()
  }

  const finish = (data) => {
    // Same person only: anything else must not inherit this page or its pending requests.
    const same = (a, b) => String(a || '').toLowerCase() === String(b || '').toLowerCase()
    if (!data?.user || !same(data.user.username, user.username)) { toLoginPage(); return }
    setSession(data)
    settle(true)
  }

  const submitPassword = async (e) => {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      const { data } = await authApi.login(user.username, password)
      if (data.mfa_required) { setMfaToken(data.mfa_token); setStep('verify') }
      else if (data.mfa_setup_required) toLoginPage()
      else finish(data)
    } catch (err) {
      setError(loginError(err, 'كلمة المرور غير صحيحة'))
    } finally {
      setBusy(false)
    }
  }

  const submitCode = async (e) => {
    e.preventDefault()
    setError(''); setBusy(true)
    try {
      const { data } = await authApi.verify2fa(mfaToken, code.trim(), false)
      finish(data)
    } catch (err) {
      setError(loginError(err, 'رمز التحقق غير صحيح'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 p-4 font-cairo" dir="rtl"
         role="dialog" aria-modal="true" aria-labelledby="session-expired-title" data-testid="session-expired">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl dark:bg-gray-800">
        <h2 id="session-expired-title" className="text-lg font-bold text-gray-800 dark:text-gray-100">انتهت الجلسة</h2>
        <p className="mt-1 mb-4 text-sm text-gray-500 dark:text-gray-400">
          سجّل الدخول مرة أخرى لتكمل من حيث توقفت — ما على الصفحة محفوظ كما هو.
        </p>

        {error && (
          <div role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}

        {step === 'credentials' ? (
          <form onSubmit={submitPassword} className="space-y-3">
            <div>
              <label className="label" htmlFor="relogin-user">اسم المستخدم</label>
              <input id="relogin-user" className="input-field bg-gray-50" value={user.username} readOnly tabIndex={-1} />
            </div>
            <div>
              <label className="label" htmlFor="relogin-password">كلمة المرور</label>
              <input id="relogin-password" type="password" className="input-field" value={password} autoFocus required
                     autoComplete="current-password" onChange={e => setPassword(e.target.value)} />
            </div>
            <button type="submit" disabled={busy} className="btn-primary w-full disabled:opacity-60">
              {busy ? 'جارٍ الدخول...' : 'دخول ومتابعة'}
            </button>
          </form>
        ) : (
          <form onSubmit={submitCode} className="space-y-3">
            <label className="label" htmlFor="relogin-code">رمز التحقق (6 أرقام) أو رمز استرجاع</label>
            <input id="relogin-code" type="text" inputMode="numeric" autoComplete="one-time-code" dir="ltr" autoFocus
                   className="input-field text-center font-mono text-xl tracking-[0.3em]" value={code}
                   onChange={e => setCode(e.target.value)} />
            <button type="submit" disabled={busy} className="btn-primary w-full disabled:opacity-60">
              {busy ? 'جارٍ التحقق...' : 'تحقق ومتابعة'}
            </button>
          </form>
        )}

        <button type="button" onClick={toLoginPage}
                className="mt-3 w-full text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
          الدخول بحساب آخر (صفحة الدخول)
        </button>
      </div>
    </div>
  )
}
