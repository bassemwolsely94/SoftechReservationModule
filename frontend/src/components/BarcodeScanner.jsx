/**
 * BarcodeScanner.jsx — phone-camera barcode / QR scanner (full-screen overlay).
 *
 * Engine: the browser's native BarcodeDetector when it reads product barcodes (Android Chrome);
 * otherwise the bundled @zxing/browser decoder, loaded on demand (iPhone Safari, desktop Firefox).
 * Nothing is sent anywhere — decoding happens on the phone. Needs HTTPS (or localhost).
 *
 * Props:
 *  onScan(text)  — called with each decoded value
 *  onClose()
 *  continuous    — keep the camera open after a read (same code ignored for 1.5 s); default false
 *  formats       — BarcodeDetector format names; default = product barcodes + QR
 *  hint          — line under the viewfinder
 */
import { useEffect, useRef, useState } from 'react'

export const PRODUCT_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code']

export function cameraAvailable() {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
}

async function nativeDetector(formats) {
  if (typeof window === 'undefined' || !('BarcodeDetector' in window)) return null
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats()
    const wanted = formats.filter(f => supported.includes(f))
    // A detector that can't read the main product barcode is no use for item search.
    if (!wanted.length || (formats.includes('ean_13') && !wanted.includes('ean_13'))) return null
    return new window.BarcodeDetector({ formats: wanted })
  } catch {
    return null
  }
}

export default function BarcodeScanner({
  onScan, onClose, continuous = false, formats = PRODUCT_FORMATS,
  hint = 'وجّه الكاميرا نحو الباركود',
}) {
  const videoRef  = useRef(null)
  const streamRef = useRef(null)
  const stopRef   = useRef(() => {})
  const lastRef   = useRef({ code: '', at: 0 })
  const onScanRef = useRef(onScan)
  onScanRef.current = onScan
  const [error, setError]   = useState('')
  const [torch, setTorch]   = useState(null)   // null = not supported, else on/off
  const [flash, setFlash]   = useState('')     // last code read (continuous mode feedback)

  useEffect(() => {
    let cancelled = false
    let raf = null
    let zxingControls = null

    function emit(text) {
      const code = String(text || '').trim()
      if (!code) return false
      const now = Date.now()
      if (code === lastRef.current.code && now - lastRef.current.at < 1500) return false
      lastRef.current = { code, at: now }
      try { navigator.vibrate?.(60) } catch { /* not supported */ }
      setFlash(code)
      onScanRef.current?.(code)
      return true
    }

    function stop() {
      cancelled = true
      if (raf) cancelAnimationFrame(raf)
      try { zxingControls?.stop() } catch { /* already stopped */ }
      streamRef.current?.getTracks().forEach(t => t.stop())
    }
    stopRef.current = stop

    async function start() {
      if (!cameraAvailable()) { setError('الكاميرا غير متاحة في هذا المتصفح — اكتب الكود يدوياً'); return }
      let stream
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        })
      } catch {
        setError('تعذّر فتح الكاميرا — اسمح للمتصفح باستخدامها ثم أعد المحاولة')
        return
      }
      if (cancelled) { stream.getTracks().forEach(t => t.stop()); return }
      streamRef.current = stream
      const track = stream.getVideoTracks()[0]
      try { if (track?.getCapabilities?.().torch) setTorch(false) } catch { /* no torch */ }
      const v = videoRef.current
      v.srcObject = stream
      try { await v.play() } catch { /* autoplay blocked — the frame loop still reads */ }

      const detector = await nativeDetector(formats)
      if (cancelled) return
      if (detector) {
        const loop = async () => {
          if (cancelled) return
          try {
            const codes = await detector.detect(v)
            if (codes?.length && emit(codes[0].rawValue) && !continuous) { stop(); return }
          } catch { /* transient frame error */ }
          raf = requestAnimationFrame(loop)
        }
        loop()
        return
      }
      try {
        const { BrowserMultiFormatReader } = await import('@zxing/browser')
        if (cancelled) return
        const reader = new BrowserMultiFormatReader()
        zxingControls = await reader.decodeFromStream(stream, v, (result) => {
          if (cancelled || !result) return
          if (emit(result.getText()) && !continuous) stop()
        })
      } catch {
        setError('تعذّر تشغيل قارئ الباركود — اكتب الكود يدوياً')
      }
    }

    start()
    return stop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function toggleTorch() {
    const track = streamRef.current?.getVideoTracks()[0]
    if (!track) return
    try {
      await track.applyConstraints({ advanced: [{ torch: !torch }] })
      setTorch(t => !t)
    } catch { setTorch(null) }
  }

  function close() { stopRef.current(); onClose?.() }

  return (
    <div className="fixed inset-0 bg-black/85 z-[60] flex flex-col items-center justify-center p-4" dir="rtl"
      role="dialog" aria-label="مسح الباركود بالكاميرا">
      {error ? (
        <div className="bg-white rounded-2xl p-5 max-w-xs text-center space-y-3">
          <div className="text-3xl">📷</div>
          <div className="text-sm text-gray-600">{error}</div>
          <button type="button" onClick={close} className="btn-primary w-full">حسناً</button>
        </div>
      ) : (
        <>
          <div className="relative w-full max-w-sm aspect-[4/3] rounded-2xl overflow-hidden border-2 border-white/60">
            <video ref={videoRef} className="w-full h-full object-cover" playsInline muted />
            <div className="absolute inset-x-6 top-1/2 -translate-y-1/2 h-1/3 border-2 border-brand-400 rounded-xl pointer-events-none" />
          </div>
          <p className="text-white text-sm mt-4">{hint}</p>
          {continuous && flash && <p className="text-brand-200 text-xs mt-1 tabular-nums" dir="ltr">✓ {flash}</p>}
          <div className="flex gap-2 mt-4">
            {torch !== null && (
              <button type="button" onClick={toggleTorch}
                className="bg-white/15 text-white rounded-xl px-4 py-2 text-sm">{torch ? 'إطفاء الفلاش' : 'الفلاش'}</button>
            )}
            <button type="button" onClick={close} className="bg-white/15 text-white rounded-xl px-6 py-2 text-sm">
              {continuous ? 'تم' : 'إلغاء'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
