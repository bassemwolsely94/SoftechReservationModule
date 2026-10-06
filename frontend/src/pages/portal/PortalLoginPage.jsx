/**
 * PortalLoginPage.jsx — customer enters phone → magic link sent via WhatsApp.
 * The confirmation is ALWAYS shown (the API never leaks whether the account exists).
 */
import { useState } from 'react'
import { portalApi } from '../../portal/portalApi'

function Shell({ children }) {
  return (
    <div className="min-h-screen bg-gray-50 font-cairo flex flex-col" dir="rtl">
      <header className="bg-brand-600 text-white px-4 py-3 flex items-center gap-2">
        <div className="w-8 h-8 bg-white/15 rounded-lg flex items-center justify-center"><span className="font-black">ر</span></div>
        <div className="font-bold text-sm">صيدليات الرزيقي — حسابي</div>
      </header>
      <main className="flex-1 p-4 flex items-start justify-center">{children}</main>
    </div>
  )
}

export default function PortalLoginPage() {
  const [phone, setPhone] = useState('')
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!phone.trim() || loading) return
    setLoading(true)
    try {
      await portalApi.requestLink(phone.trim())
      setSent(true)
    } catch {
      setSent(true)  // still show generic confirmation (no existence leak)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Shell>
      <div className="w-full max-w-md mt-8">
        {sent ? (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 text-center space-y-3">
            <div className="text-4xl">📲</div>
            <div className="font-bold text-gray-900">تحقّق من واتساب</div>
            <p className="text-sm text-gray-500 leading-relaxed">
              إذا كان لديك حساب لدينا، فسيصلك رابط الدخول عبر واتساب خلال لحظات.
              الرابط صالح لمدة ١٥ دقيقة.
            </p>
            <button onClick={() => setSent(false)} className="text-sm text-brand-600 font-medium">
              إدخال رقم آخر
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="bg-white rounded-2xl border border-gray-200 p-6 space-y-4">
            <div className="text-center space-y-1">
              <div className="text-4xl">👋</div>
              <div className="font-bold text-gray-900">مرحباً بك</div>
              <p className="text-sm text-gray-500">أدخل رقم هاتفك لإرسال رابط الدخول</p>
            </div>
            <input
              type="tel" inputMode="numeric" dir="ltr" value={phone}
              onChange={e => setPhone(e.target.value)} placeholder="01XXXXXXXXX"
              className="w-full text-center text-lg tracking-wider border border-gray-300 rounded-xl py-3 focus:outline-none focus:ring-2 focus:ring-brand-600"
            />
            <button
              type="submit" disabled={loading || !phone.trim()}
              className="w-full bg-brand-600 text-white rounded-xl py-3 font-bold disabled:opacity-50"
            >
              {loading ? 'جارٍ الإرسال...' : 'إرسال رابط الدخول'}
            </button>
          </form>
        )}
      </div>
    </Shell>
  )
}
