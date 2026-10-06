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
    <div className="space-y-3" dir="rtl">
      <p className="text-sm text-gray-500">لإيقاف المصادقة الثنائية أدخل كلمة المرور ورمزاً حالياً.</p>
      <input type="password" className="input-field w-full" placeholder="كلمة المرور"
        value={password} onChange={e => setPassword(e.target.value)} />
      <input type="text" inputMode="numeric" className="input-field w-full font-mono" dir="ltr"
        placeholder="رمز المصادقة أو رمز استرجاع" value={code} onChange={e => setCode(e.target.value)} />
      {error && <div className="text-sm text-red-600">{error}</div>}
      <button onClick={submit} disabled={busy}
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
      <h1 className="text-lg font-bold text-gray-900 mb-1">أمان الحساب</h1>
      <p className="text-sm text-gray-400 mb-6">المصادقة الثنائية (TOTP) لحماية الدخول من خارج الصيدلية.</p>

      <div className="bg-white rounded-2xl border border-gray-200 p-6">
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
            <div className="text-sm text-gray-500">
              رموز الاسترجاع المتبقية: <strong>{st.backup_codes_left}</strong>
            </div>
            <hr className="border-gray-100" />
            <DisableForm onDone={refresh} />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-gray-600">
              <span className="text-xl">🔓</span>
              <span className="font-semibold">المصادقة الثنائية غير مفعّلة</span>
            </div>
            {st?.required_for_role && (
              <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                دورك ({user?.role_label || user?.role}) سيتطلب المصادقة الثنائية عند تفعيل الإلزام.
                {st.enforcement_on ? ' الإلزام مفعّل حالياً.' : ' يُفضّل تفعيلها الآن.'}
              </p>
            )}
            <button onClick={() => setEnrolling(true)} className="btn-primary">
              تفعيل المصادقة الثنائية
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
