/**
 * QrScanner.jsx — lightweight camera QR scanner (modal) using the native
 * BarcodeDetector API. No external library. Falls back gracefully where the API
 * isn't supported (notably iOS Safari) — the caller should offer manual entry.
 *
 * Props: onScan(text) — called once with the decoded value; onClose().
 */
import { useEffect, useRef, useState } from 'react'

export default function QrScanner({ onScan, onClose }) {
  const videoRef = useRef(null)
  const rafRef   = useRef(null)
  const streamRef = useRef(null)
  const [error, setError] = useState('')
  const supported = typeof window !== 'undefined' && 'BarcodeDetector' in window

  useEffect(() => {
    let cancelled = false
    if (!supported) { setError('المسح غير مدعوم في هذا المتصفح — استخدم البحث اليدوي'); return }

    const detector = new window.BarcodeDetector({ formats: ['qr_code'] })

    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return }
        streamRef.current = stream
        const v = videoRef.current
        v.srcObject = stream
        await v.play()
        scan(detector)
      } catch {
        setError('تعذّر فتح الكاميرا — تحقق من الإذن')
      }
    }

    async function scan(detector) {
      if (cancelled || !videoRef.current) return
      try {
        const codes = await detector.detect(videoRef.current)
        if (codes && codes.length) {
          const val = codes[0].rawValue
          stop()
          onScan(val)
          return
        }
      } catch { /* transient frame error — keep trying */ }
      rafRef.current = requestAnimationFrame(() => scan(detector))
    }

    function stop() {
      cancelled = true
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop())
    }

    start()
    return stop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="fixed inset-0 bg-black/80 z-50 flex flex-col items-center justify-center p-4" dir="rtl">
      {error ? (
        <div className="bg-white rounded-2xl p-5 max-w-xs text-center space-y-3">
          <div className="text-3xl">📷</div>
          <div className="text-sm text-gray-600">{error}</div>
          <button onClick={onClose} className="btn-primary w-full">حسناً</button>
        </div>
      ) : (
        <>
          <div className="relative w-full max-w-xs aspect-square rounded-2xl overflow-hidden border-2 border-white/60">
            <video ref={videoRef} className="w-full h-full object-cover" playsInline muted />
            <div className="absolute inset-8 border-2 border-brand-400 rounded-xl pointer-events-none" />
          </div>
          <p className="text-white text-sm mt-4">وجّه الكاميرا نحو رمز العميل</p>
          <button onClick={onClose} className="mt-4 bg-white/15 text-white rounded-xl px-6 py-2 text-sm">إلغاء</button>
        </>
      )}
    </div>
  )
}
