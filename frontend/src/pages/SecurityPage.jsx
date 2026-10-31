/**
 * SecurityPage.jsx — self-service account security (route: /security, all roles).
 *
 * Lets any user enroll in / manage TOTP two-factor authentication during the
 * opt-in grace period. Approval roles (admin/supervisor/purchasing) will be
 * forced to enroll at login once enforcement is switched on.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi } from '../api/client'
import useAuthStore from '../store/authStore'
import TwoFactorSetup from '../components/TwoFactorSetup'

function ForgetDevices() {
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  async function forget() {
    setBusy(true)
    try {
      await authApi.forgetDevices()
      useAuthStore.getState().clearDeviceToken()
      setDone(true)
    } finally { setBusy(false) }
  }
  return (
    <div className="space-y-2 mt-4" dir="rtl">
      <p className="text-sm text-gray-500">لو فقدت جهازاً سبق أن اخترت «تذكّر هذا الجهاز» عليه، ألغِ كل الأجهزة المحفوظة؛ سيُطلب الرمز في الدخول التالي على كل جهاز.</p>
      <button data-tour="general-security-forget-devices" onClick={forget} disabled={busy}
        className="border border-gray-300 hover:bg-gray-50 text-gray-700 rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50">
        {done ? '✓ تم إلغاء الأجهزة المحفوظة' : 'إلغاء كل الأجهزة المحفوظة'}
      </button>
    </div>
  )
}

function DisableForm({ onDone }) {
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true); setError('')
    try {
      await authApi.disable2fa(password, code.trim())
      onDone()
    } catch (e) {
      setError(e.response?.data?.error || 'تعذّر الإيقاف')
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3" dir="rtl" data-tour="general-security-disable">
      <p className="text-sm text-gray-500">لإيقاف المصادقة الثنائية أدخل كلمة المرور ورمزاً حالياً.</p>
      <input type="password" className="input-field w-full" placeholder="كلمة المرور"
        value={password} onChange={e => setPassword(e.target.value)} />
      <input type="text" inputMode="numeric" className="input-field w-full font-mono" dir="ltr"
        placeholder="رمز المصادقة أو رمز استرجاع" value={code} onChange={e => setCode(e.target.value)} />
      {error && <div className="text-sm text-red-600">{error}</div>}
      <button data-tour="general-security-disable" onClick={submit} disabled={busy}
        className="bg-red-500 hover:bg-red-600 text-white rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50">
        {busy ? 'جارٍ الإيقاف...' : 'إيقاف المصادقة الثنائية'}
      </button>
    </div>
  )
}

export default function SecurityPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [enrolling, setEnrolling] = useState(false)

  const { data: st, isLoading } = useQuery({
    queryKey: ['2fa-status'],
    queryFn: () => authApi.status2fa().then(r => r.data),
  })

  const refresh = () => { qc.invalidateQueries({ queryKey: ['2fa-status'] }); setEnrolling(false) }

  return (
    <div className="max-w-xl mx-auto px-6 py-6" dir="rtl">
      <h1 className="text-lg font-bold text-gray-900 mb-1" data-tour="general-security-header">أمان الحساب</h1>
      <p className="text-sm text-gray-400 mb-6">المصادقة الثنائية (TOTP) لحماية الدخول من خارج الصيدلية.</p>

      <div className="bg-white rounded-2xl border border-gray-200 p-6" data-tour="general-security-status">
        {isLoading ? (
          <div className="text-sm text-gray-400 text-center py-6">جارٍ التحميل...</div>
        ) : enrolling ? (
          <TwoFactorSetup onComplete={refresh} onCancel={() => setEnrolling(false)} />
        ) : st?.enabled ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-green-700">
              <span className="text-xl">🔒</span>
              <span className="font-semibold">المصادقة الثنائية مفعّلة</span>
            </div>
            <div data-tour="general-security-codes-left" className="text-sm text-gray-500">
              رموز الاسترجاع المتبقية: <strong>{st.backup_codes_left}</strong>
            </div>
            <hr className="border-gray-100" />
            <DisableForm onDone={refresh} />
            <hr className="border-gray-100" />
            <ForgetDevices />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-gray-600">
              <span className="text-xl">🔓</span>
              <span className="font-semibold">المصادقة الثنائية غير مفعّلة</span>
            </div>
            {st?.required_for_role && (
              <p data-tour="general-security-required" className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                دورك ({user?.role_label || user?.role}) سيتطلب المصادقة الثنائية عند تفعيل الإلزام.
                {st.enforcement_on ? ' الإلزام مفعّل حالياً.' : ' يُفضّل تفعيلها الآن.'}
              </p>
            )}
            <button onClick={() => setEnrolling(true)} className="btn-primary" data-tour="general-security-enable">
              تفعيل المصادقة الثنائية
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
