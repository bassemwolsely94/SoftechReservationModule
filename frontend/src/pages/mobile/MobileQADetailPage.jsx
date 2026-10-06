/**
 * MobileQADetailPage.jsx — fill / review a QA branch inspection (route: /m/qa/:id).
 * Draft: per-item pass/fail/na + note, save or submit (computes score).
 * Submitted: read-only with the score.
 */
import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { qaApi } from '../../api/client'
import { MobileLoading, MobileError } from '../../components/mobileUi'

const RESULTS = [
  { v: 'pass', l: 'مطابق', on: 'bg-green-600 text-white', off: 'text-green-700 border-green-300' },
  { v: 'fail', l: 'مخالفة', on: 'bg-red-500 text-white',  off: 'text-red-700 border-red-300' },
  { v: 'na',   l: 'لا ينطبق', on: 'bg-gray-500 text-white', off: 'text-gray-600 border-gray-300' },
]
function toLatin(s) { return s == null ? '' : String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) }

export default function MobileQADetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-qa', id],
    queryFn: () => qaApi.get(id).then(r => r.data),
  })

  const [results, setResults] = useState([])
  const [notes, setNotes]     = useState('')
  const [busy, setBusy]       = useState(false)
  const [error, setError]     = useState('')

  useEffect(() => {
    if (data) { setResults(data.results || []); setNotes(data.notes || '') }
  }, [data])

  if (isLoading) return <MobileLoading />
  if (isError || !data) return <MobileError text="تعذّر تحميل المراجعة" onRetry={refetch} />

  const submitted = data.status === 'submitted'
  const answered  = results.filter(r => r.result).length
  const setResult = (i, v) => setResults(rs => rs.map((r, idx) => idx === i ? { ...r, result: v } : r))
  const setNote   = (i, v) => setResults(rs => rs.map((r, idx) => idx === i ? { ...r, note: v } : r))

  async function save(submitIt) {
    setBusy(true); setError('')
    try {
      if (submitIt) {
        const { data: d } = await qaApi.submit(id, { results, notes })
        qc.setQueryData(['m-qa', id], d)
      } else {
        const { data: d } = await qaApi.update(id, { results, notes })
        qc.setQueryData(['m-qa', id], d)
      }
      qc.invalidateQueries({ queryKey: ['m-qa'] })
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر الحفظ')
    } finally { setBusy(false) }
  }

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/qa')} className="text-sm text-gray-500">→ الرجوع للمراجعات</button>

      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="font-bold text-base text-gray-900">{data.branch_name || `فرع ${data.branch}`}</h1>
          {submitted && data.score != null && (
            <span className={`text-sm font-bold px-3 py-1 rounded-full ${data.score >= 90 ? 'bg-green-100 text-green-700' : data.score >= 70 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'}`}>
              {toLatin(data.score)}%
            </span>
          )}
        </div>
        <div className="text-xs text-gray-400 mt-1">{data.template_name} · {submitted ? 'مُرسَلة' : `أُجيب ${toLatin(answered)} من ${toLatin(results.length)}`}</div>
      </div>

      <div className="space-y-2">
        {results.map((r, i) => (
          <div key={r.key || i} className="bg-white rounded-2xl border border-gray-200 p-3.5">
            <div className="text-sm text-gray-800 mb-2">{r.label}</div>
            {submitted ? (
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${r.result === 'pass' ? 'bg-green-100 text-green-700' : r.result === 'fail' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}`}>
                  {RESULTS.find(x => x.v === r.result)?.l || '—'}
                </span>
                {r.note && <span className="text-xs text-gray-500">— {r.note}</span>}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-3 gap-1.5">
                  {RESULTS.map(opt => (
                    <button key={opt.v} onClick={() => setResult(i, opt.v)}
                      className={`py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${r.result === opt.v ? `${opt.on} border-transparent` : `bg-white ${opt.off}`}`}>
                      {opt.l}
                    </button>
                  ))}
                </div>
                {r.result === 'fail' && (
                  <input className="input-field w-full text-sm mt-2" placeholder="ملاحظة المخالفة..."
                    value={r.note || ''} onChange={e => setNote(i, e.target.value)} />
                )}
              </>
            )}
          </div>
        ))}
      </div>

      {!submitted && (
        <>
          <div className="bg-white rounded-2xl border border-gray-200 p-3.5">
            <label className="label">ملاحظات عامة</label>
            <textarea rows={2} className="input-field w-full resize-none" value={notes} onChange={e => setNotes(e.target.value)} />
          </div>
          {error && <div className="text-sm text-red-600 text-center">{error}</div>}
          <div className="flex gap-2">
            <button onClick={() => save(false)} disabled={busy} className="btn-secondary flex-1 disabled:opacity-50">حفظ كمسودة</button>
            <button onClick={() => save(true)} disabled={busy || answered === 0} className="btn-primary flex-1 py-3 disabled:opacity-50">
              {busy ? '...' : '✅ إرسال'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
