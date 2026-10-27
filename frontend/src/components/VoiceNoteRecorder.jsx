/**
 * VoiceNoteRecorder.jsx
 *
 * In-browser voice note recorder using the MediaRecorder Web API.
 *
 * Features:
 *   • Record via microphone (WebRTC)
 *   • Upload existing audio file as alternative
 *   • Playback preview before committing
 *   • Returns a Blob / File for inclusion in FormData
 *
 * Props:
 *   onRecorded   {fn}   — (audioBlob, filename) => void  called when recording / file is ready
 *   onClear      {fn}   — () => void  called when the user discards the recording
 *   disabled     {bool}
 *   maxSeconds   {number}  — max recording duration (default 120)
 */
import { useState, useRef, useEffect } from 'react'

const MIME_PREFERENCE = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
  'audio/mp4',
]

function getSupportedMime() {
  for (const mime of MIME_PREFERENCE) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mime)) {
      return mime
    }
  }
  return ''
}

function formatTime(secs) {
  const m = Math.floor(secs / 60).toString().padStart(2, '0')
  const s = (secs % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

export default function VoiceNoteRecorder({
  onRecorded,
  onClear,
  disabled = false,
  maxSeconds = 120,
}) {
  const [phase, setPhase] = useState('idle')   // idle | requesting | recording | preview | upload_ready
  const [elapsed, setElapsed] = useState(0)
  const [audioUrl, setAudioUrl] = useState(null)
  const [fileName, setFileName] = useState('')
  const [error, setError] = useState('')

  const mediaRecorderRef = useRef(null)
  const chunksRef        = useRef([])
  const timerRef         = useRef(null)
  const audioRef         = useRef(null)

  // Auto-stop at maxSeconds
  useEffect(() => {
    if (phase === 'recording') {
      if (elapsed >= maxSeconds) stopRecording()
    }
  }, [elapsed, phase])

  const startRecording = async () => {
    setError('')
    setPhase('requesting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime   = getSupportedMime()
      const opts   = mime ? { mimeType: mime } : {}
      const mr     = new MediaRecorder(stream, opts)
      chunksRef.current = []

      mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      mr.onstop = () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(chunksRef.current, { type: mime || 'audio/webm' })
        const url  = URL.createObjectURL(blob)
        const ext  = mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm'
        const name = `voice-note-${Date.now()}.${ext}`
        setAudioUrl(url)
        setFileName(name)
        setPhase('preview')
        const file = new File([blob], name, { type: mime || 'audio/webm' })
        onRecorded?.(file, name)
      }

      mr.start(200)   // collect in 200ms chunks
      mediaRecorderRef.current = mr
      setElapsed(0)
      setPhase('recording')

      timerRef.current = setInterval(() => {
        setElapsed(e => e + 1)
      }, 1000)

    } catch (err) {
      setPhase('idle')
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setError('يجب السماح بالوصول للميكروفون من إعدادات المتصفح')
      } else {
        setError(`تعذّر الوصول للميكروفون: ${err.message}`)
      }
    }
  }

  const stopRecording = () => {
    clearInterval(timerRef.current)
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
  }

  const discardRecording = () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl)
    setAudioUrl(null)
    setFileName('')
    setElapsed(0)
    setPhase('idle')
    onClear?.()
  }

  // File upload alternative
  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const validTypes = ['audio/webm','audio/ogg','audio/mp4','audio/mpeg','audio/wav','audio/m4a']
    if (!validTypes.some(t => file.type.startsWith(t.split('/')[0]) && file.type.includes(t.split('/')[1]))) {
      // Be permissive — any audio/* type
      if (!file.type.startsWith('audio/')) {
        setError('يجب اختيار ملف صوتي (webm, ogg, mp3, wav, m4a)')
        return
      }
    }
    const url = URL.createObjectURL(file)
    setAudioUrl(url)
    setFileName(file.name)
    setPhase('upload_ready')
    onRecorded?.(file, file.name)
    e.target.value = ''   // reset input
  }

  const isRecorderAvailable = typeof navigator !== 'undefined' && navigator.mediaDevices?.getUserMedia

  return (
    <div className="voice-recorder" dir="rtl">
      {error && (
        <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-2">
          {error}
        </div>
      )}

      {phase === 'idle' && (
        <div className="flex items-center gap-2">
          {/* Record button */}
          {isRecorderAvailable && (
            <button
              type="button"
              onClick={startRecording}
              disabled={disabled}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-300 text-red-700 hover:bg-red-50 disabled:opacity-50 transition-colors"
            >
              <span className="w-2 h-2 rounded-full bg-red-500" />
              تسجيل ملاحظة صوتية
            </button>
          )}
          {/* Upload alternative */}
          <label className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 cursor-pointer disabled:opacity-50 transition-colors">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            رفع ملف صوتي
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={handleFileUpload}
              disabled={disabled}
            />
          </label>
        </div>
      )}

      {phase === 'requesting' && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="w-4 h-4 border-2 border-red-300 border-t-red-600 rounded-full animate-spin inline-block" />
          جارٍ طلب الوصول للميكروفون…
        </div>
      )}

      {phase === 'recording' && (
        <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          {/* Pulse dot */}
          <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse" />
          <span className="text-sm font-mono text-red-700 font-bold tabular-nums">
            {formatTime(elapsed)}
          </span>
          <span className="text-xs text-red-600">جارٍ التسجيل…</span>
          <div className="flex-1" />
          <span className="text-xs text-red-400">الحد الأقصى {formatTime(maxSeconds)}</span>
          <button
            type="button"
            onClick={stopRecording}
            className="bg-red-600 text-white text-xs px-3 py-1 rounded-lg hover:bg-red-700"
          >
            إيقاف
          </button>
        </div>
      )}

      {(phase === 'preview' || phase === 'upload_ready') && audioUrl && (
        <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-green-800">
              {phase === 'upload_ready' ? '🎵 ملف صوتي جاهز' : `🎙️ مدة التسجيل: ${formatTime(elapsed)}`}
            </span>
            <button
              type="button"
              onClick={discardRecording}
              className="text-xs text-red-500 hover:text-red-700"
            >
              حذف
            </button>
          </div>
          <audio
            ref={audioRef}
            src={audioUrl}
            controls
            className="w-full h-8"
            style={{ direction: 'ltr' }}
          />
          <div className="text-xs text-green-600 truncate">{fileName}</div>
        </div>
      )}
    </div>
  )
}
