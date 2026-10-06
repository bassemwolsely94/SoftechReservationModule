/**
 * MobileAttendancePage.jsx — geofenced clock in/out (route: /m/attendance).
 *
 * Staff tap to check in / out; the browser's GPS is sent and the server computes
 * distance to the branch (within 200 m = on-site). Works without GPS too (records
 * as "unverified"). Reuses apps/hr AttendanceRecord.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { hrApi } from '../../api/client'
import { MobileLoading, MobileError } from '../../components/mobileUi'

function fmtTime(d) {
  try { return new Date(d).toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' }) } catch { return '' }
}
function toLatin(s) { return s == null ? '' : String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) }

function getPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    )
  })
}

function GeofenceTag({ ok, dist }) {
  if (ok === true)  return <span className="text-xs text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded">✓ ضمن نطاق الفرع</span>
  if (ok === false) return <span className="text-xs text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded">⚠ خارج النطاق{dist != null ? ` (${toLatin(dist)}م)` : ''}</span>
  return <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">الموقع غير مُتحقق</span>
}

export default function MobileAttendancePage() {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-attendance'],
    queryFn: () => hrApi.attendanceStatus().then(r => r.data),
  })

  const rec  = data && !data.none ? data : null
  const open = rec && rec.is_open

  async function act(kind) {
    setBusy(true); setError('')
    try {
      const pos = await getPosition()
      const body = pos || {}
      if (kind === 'in') await hrApi.attendanceCheckIn(body)
      else await hrApi.attendanceCheckOut(body)
      await qc.invalidateQueries({ queryKey: ['m-attendance'] })
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر التسجيل')
    } finally { setBusy(false) }
  }

  if (isLoading) return <MobileLoading />
  if (isError) return <MobileError text="تعذّر تحميل الحضور" onRetry={refetch} />

  return (
    <div className="p-3 space-y-3">
      <div className="bg-white rounded-2xl border border-gray-200 p-5 text-center">
        <div className="text-4xl mb-1">{open ? '🟢' : rec ? '✅' : '🕐'}</div>
        <div className="text-sm text-gray-500">
          {open ? 'أنت مسجّل حضور الآن' : rec ? 'أنهيت يومك' : 'لم تسجّل الحضور بعد'}
        </div>
        {rec && (
          <div className="mt-3 text-sm text-gray-700 space-y-1.5">
            <div className="flex items-center justify-center gap-2">
              <span className="text-gray-400">حضور:</span>
              <span className="font-medium">{fmtTime(rec.check_in_at)}</span>
              <GeofenceTag ok={rec.check_in_ok} dist={rec.check_in_distance_m} />
            </div>
            {rec.check_out_at && (
              <div className="flex items-center justify-center gap-2">
                <span className="text-gray-400">انصراف:</span>
                <span className="font-medium">{fmtTime(rec.check_out_at)}</span>
                <GeofenceTag ok={rec.check_out_ok} dist={rec.check_out_distance_m} />
              </div>
            )}
          </div>
        )}
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-2xl px-4 py-3">{error}</div>}

      {!rec || open ? (
        open ? (
          <button onClick={() => act('out')} disabled={busy}
            className="w-full py-4 rounded-2xl bg-red-500 text-white text-base font-bold disabled:opacity-50">
            {busy ? 'جارٍ تحديد الموقع...' : '🚪 تسجيل الانصراف'}
          </button>
        ) : (
          <button onClick={() => act('in')} disabled={busy}
            className="w-full py-4 rounded-2xl bg-brand-600 text-white text-base font-bold disabled:opacity-50">
            {busy ? 'جارٍ تحديد الموقع...' : '📍 تسجيل الحضور'}
          </button>
        )
      ) : (
        <div className="text-center text-xs text-gray-400">تم تسجيل حضورك وانصرافك اليوم</div>
      )}

      <p className="text-center text-[11px] text-gray-400">يتم التحقق من موقعك مقابل موقع فرعك (ضمن ٢٠٠ متر)</p>
    </div>
  )
}
