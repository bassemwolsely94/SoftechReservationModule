/**
 * PortalAuthPage.jsx — route /portal/auth/:token.
 * Auto-exchanges the magic-link token for a session token, stores it, then
 * redirects into the portal home. On failure → back to login.
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { portalApi, portalToken } from '../../portal/portalApi'

export default function PortalAuthPage() {
  const { token } = useParams()
  const navigate = useNavigate()
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    portalApi.exchange(token)
      .then(({ data }) => {
        if (!active) return
        portalToken.set(data.session_token)
        navigate('/portal', { replace: true })
      })
      .catch(() => { if (active) setError(true) })
    return () => { active = false }
  }, [token, navigate])

  return (
    <div className="min-h-screen bg-gray-50 font-cairo flex items-center justify-center p-6" dir="rtl">
      {error ? (
        <div className="text-center space-y-3 max-w-sm">
          <div className="text-4xl">⚠️</div>
          <div className="font-bold text-gray-900">الرابط غير صالح أو منتهي الصلاحية</div>
          <button
            onClick={() => navigate('/portal/login', { replace: true })}
            className="text-sm text-brand-600 font-bold"
          >
            طلب رابط جديد
          </button>
        </div>
      ) : (
        <div className="text-center text-gray-400 text-sm animate-pulse">جارٍ تسجيل الدخول...</div>
      )}
    </div>
  )
}
