import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { callCenterApi } from '../../api/client'

const STATUS_LABEL = {
  pending: 'في الانتظار', running: 'قيد التفريغ', done: 'تم', failed: 'فشل', skipped: 'تم التخطي',
}

const fmt = (dt) => dt ? new Date(dt).toLocaleString('ar-EG', {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
}) : '—'

function TranscriptRow({ row }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(row.corrected_text || row.whisper_text || row.gemini_text)
  const save = useMutation({
    mutationFn: () => callCenterApi.correctTranscript(row.id, text),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ['whisper-status'] }) },
  })

  return (
    <div className="border-b border-gray-100 dark:border-gray-700 py-2 last:border-0 text-sm">
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-400 tabular-nums">{fmt(row.called_at)}</span>
        <span className="flex-1 truncate">{row.customer_name || row.phone}</span>
        <span className="text-xs text-gray-500">{STATUS_LABEL[row.status]}</span>
        {row.corrected_text && <span className="text-xs text-green-600">✓ مُصحَّح</span>}
        <button onClick={() => setOpen(o => !o)} className="text-xs text-brand-600 hover:underline">
          {open ? 'إغلاق' : 'مقارنة وتصحيح'}
        </button>
      </div>
      {row.error && <div className="text-xs text-red-500 mt-1">{row.error}</div>}
      {open && (
        <div className="mt-2 grid md:grid-cols-2 gap-2">
          <div>
            <div className="text-xs text-gray-400 mb-1">Whisper (محلي)</div>
            <div className="text-xs bg-gray-50 dark:bg-gray-800 rounded p-2 whitespace-pre-wrap min-h-[3rem]">{row.whisper_text || '—'}</div>
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-1">Gemini</div>
            <div className="text-xs bg-gray-50 dark:bg-gray-800 rounded p-2 whitespace-pre-wrap min-h-[3rem]">{row.gemini_text || '—'}</div>
          </div>
          <div className="md:col-span-2">
            <div className="text-xs text-gray-400 mb-1">النص الصحيح (يتعلم منه Whisper أسماء الأدوية والكلمات)</div>
            <textarea value={text} onChange={e => setText(e.target.value)} rows={4}
              className="input w-full text-sm" dir="rtl" />
            <div className="flex justify-end mt-1">
              <button onClick={() => save.mutate()} disabled={save.isPending || !text.trim()}
                className="btn-primary text-xs px-3 py-1 disabled:opacity-50">
                {save.isPending ? '⏳' : '💾 حفظ التصحيح'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function WhisperPanel() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['whisper-status'],
    queryFn: () => callCenterApi.whisperStatus().then(r => r.data),
    refetchInterval: 30_000,
  })
  const [draft, setDraft] = useState(null)
  const control = useMutation({
    mutationFn: (body) => callCenterApi.whisperControl(body).then(r => r.data),
    onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ['whisper-status'] }) },
  })

  if (isLoading || !data) return <section className="card text-sm text-gray-400">جارٍ التحميل…</section>
  const c = data.control
  const s = data.stats
  const form = draft || { window_start: c.window_start, window_end: c.window_end,
                          model_size: c.model_size, cpu_threads: c.cpu_threads }

  return (
    <section className="card space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-gray-600 dark:text-gray-300">تفريغ المكالمات المحلي (Whisper)</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            يعمل ليلاً من {c.window_start} إلى {c.window_end} بأولوية منخفضة؛ ما لا يكتمل يُستكمل الليلة التالية.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!c.enabled && <span className="text-xs text-amber-600">غير مفعّل (WHISPER_ENABLED)</span>}
          {c.running && <span className="text-xs text-blue-600 animate-pulse">● يعمل الآن</span>}
          {c.paused
            ? <button onClick={() => control.mutate({ action: 'resume' })} className="btn-secondary text-xs px-3 py-1">▶ استئناف</button>
            : <button onClick={() => control.mutate({ action: 'pause' })} className="btn-secondary text-xs px-3 py-1">⏸ إيقاف مؤقت</button>}
          {c.running && (
            <button onClick={() => control.mutate({ action: 'stop' })} className="btn-secondary text-xs px-3 py-1 text-red-600">⏹ إيقاف التشغيل الحالي</button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center">
        {[
          ['في الانتظار', s.by_status.pending || 0],
          ['تم', s.by_status.done || 0],
          ['فشل', s.by_status.failed || 0],
          ['دقائق صوت معلقة', s.pending_audio_minutes],
          ['ساعات متوقعة', s.estimated_hours],
        ].map(([label, v]) => (
          <div key={label} className="rounded-lg bg-gray-50 dark:bg-gray-800 py-2">
            <div className="text-xs text-gray-400">{label}</div>
            <div className="text-lg font-bold tabular-nums">{v}</div>
          </div>
        ))}
      </div>

      <div className="text-xs text-gray-500">
        آخر تشغيل: {fmt(c.run_started_at)} → {fmt(c.run_finished_at)} — {c.run_processed} مكالمة
        {c.run_note && ` — ${c.run_note}`} · السرعة: {s.realtime_factor}× من مدة الصوت · تصحيحات: {s.corrections}
      </div>

      <div className="flex flex-wrap items-end gap-3 text-xs">
        <label>من <input type="time" value={form.window_start} className="input text-xs py-1"
          onChange={e => setDraft({ ...form, window_start: e.target.value })} /></label>
        <label>إلى <input type="time" value={form.window_end} className="input text-xs py-1"
          onChange={e => setDraft({ ...form, window_end: e.target.value })} /></label>
        <label>النموذج <select value={form.model_size} className="input text-xs py-1"
          onChange={e => setDraft({ ...form, model_size: e.target.value })}>
          <option value="small">small (أسرع)</option>
          <option value="medium">medium (موصى به)</option>
          <option value="large-v3">large-v3 (أدق، أبطأ كثيراً)</option>
        </select></label>
        <label>أنوية المعالج <input type="number" min="1" max="64" value={form.cpu_threads}
          className="input text-xs py-1 w-16"
          onChange={e => setDraft({ ...form, cpu_threads: e.target.value })} /></label>
        {draft && (
          <button onClick={() => control.mutate(draft)} className="btn-primary text-xs px-3 py-1">حفظ الإعدادات</button>
        )}
        {control.isError && <span className="text-red-600">{control.error?.response?.data?.detail || 'فشل الحفظ'}</span>}
      </div>

      <details className="text-xs text-gray-500">
        <summary className="cursor-pointer">الكلمات التي تعلّمها من التصحيحات</summary>
        <div className="mt-1 whitespace-pre-wrap" dir="rtl">{data.vocabulary_prompt}</div>
      </details>

      <div>
        <div className="text-xs font-semibold text-gray-500 mb-1">آخر التفريغات</div>
        {data.recent.length === 0
          ? <div className="text-xs text-gray-400 py-3">لا توجد تفريغات بعد</div>
          : data.recent.map(r => <TranscriptRow key={r.id} row={r} />)}
      </div>
    </section>
  )
}
