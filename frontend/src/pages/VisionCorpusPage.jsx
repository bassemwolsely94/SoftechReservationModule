/**
 * VisionCorpusPage (/vision-corpus) — the in-house OCR corpus dashboard.
 * Watches the owned, labelled dataset grow across sales + purchasing: size, label rate,
 * and the module / engine / media mix that will drive the parallel in-house recogniser.
 */
import { useEffect, useState } from 'react'
import api from '../api/client'

const MODULE_LABEL = {
  pos_rx: 'روشتة (POS)', pos_voice: 'صوت (POS)',
  purchasing_shortage: 'نواقص', purchasing_invoice: 'فاتورة مورّد', other: 'أخرى',
}
const ENGINE_LABEL = { gemini: 'Gemini', easyocr: 'EasyOCR (داخلي)', tesseract: 'Tesseract (داخلي)', inhouse: 'داخلي', paddle: 'PaddleOCR' }
const MEDIA_LABEL = { image: 'صورة', audio: 'صوت' }

export default function VisionCorpusPage() {
  const [d, setD] = useState(null)
  const [acc, setAcc] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api.get('/vision/corpus-stats/').then(r => setD(r.data)).catch(() => setErr('تعذّر تحميل الإحصاءات.'))
    api.get('/vision/corpus-accuracy/').then(r => setAcc(r.data)).catch(() => {})
  }, [])

  return (
    <div className="page-body">
      <div className="mb-4">
        <h1 className="text-lg font-bold text-content">مجموعة بيانات المحرك البصري الداخلي</h1>
        <p className="text-xs text-faint">قاعدة التعلّم المملوكة لصيدليات الرزيقي — تنمو مع كل قراءة وتأكيد عبر المبيعات والمشتريات.</p>
      </div>

      {err && <div className="card text-sm text-amber-700">{err}</div>}
      {!d && !err && <div className="card text-center text-faint py-8">… جارٍ التحميل</div>}

      {d && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <Stat label="إجمالي العيّنات" value={d.total} />
            <Stat label="مُصنَّفة (بتأكيد بشري)" value={d.labelled} />
            <Stat label="جاهزة للتدريب (صور)" value={d.trainable_images ?? '—'} />
            <Stat label="المحرك الداخلي" value={d.inhouse_ready ? 'مُفعَّل ✓' : (d.inhouse_configured ? 'مُهيَّأ' : 'غير مُدرَّب')} />
          </div>
          <div className="grid md:grid-cols-3 gap-3">
            <Breakdown title="حسب المصدر" data={d.by_module} labels={MODULE_LABEL} />
            <Breakdown title="حسب المحرك" data={d.by_engine} labels={ENGINE_LABEL} />
            <Breakdown title="حسب الوسيط" data={d.by_media} labels={MEDIA_LABEL} />
          </div>
          {/* accuracy — in-house engines vs Gemini, measured against human confirmations */}
          {acc && acc.results?.length > 0 && (
            <div className="card mt-4">
              <div className="section-title">دقة المحركات — استرجاع الأصناف المؤكَّدة (آخر {acc.sample_window} عيّنة)</div>
              <div className="space-y-2">
                {acc.results.map(r => (
                  <div key={r.engine}>
                    <div className="flex justify-between text-[11px] mb-0.5">
                      <span className="text-content font-semibold">{ENGINE_LABEL[r.engine] || r.engine}</span>
                      <span className="tabnum text-faint">{Math.round(r.recall * 100)}% · {r.covered}/{r.confirmed}</span>
                    </div>
                    <div className="h-2 rounded bg-surface-3 overflow-hidden">
                      <div className="h-full bg-emerald-500" style={{ width: `${r.recall * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-faint mt-2">كلما ارتفعت دقة المحرك الداخلي على بياناتنا اقتربنا من الاستغناء عن Gemini.</p>
            </div>
          )}

          <p className="text-[11px] text-faint mt-4">
            كل صورة/صوت + تأكيد بشري = مثال تدريب. المحركات تعمل بالتوازي (Gemini + داخلي)، والكتالوج يحكّم بينها بتعزيز التوافق؛ عند تراكم بيانات كافية يُدرَّب المحرك الداخلي (مطبوع + خط اليد، عربي + إنجليزي).
          </p>
        </>
      )}
    </div>
  )
}

const Stat = ({ label, value }) => (
  <div className="card">
    <div className="text-[11px] text-faint">{label}</div>
    <div className="text-2xl font-bold text-content tabnum">{value}</div>
  </div>
)

function Breakdown({ title, data, labels }) {
  const entries = Object.entries(data || {})
  const max = Math.max(1, ...entries.map(([, n]) => n))
  return (
    <div className="card">
      <div className="section-title">{title}</div>
      {!entries.length && <div className="text-xs text-faint">لا بيانات بعد.</div>}
      <div className="space-y-1.5">
        {entries.map(([k, n]) => (
          <div key={k}>
            <div className="flex justify-between text-[11px] mb-0.5">
              <span className="text-content">{labels[k] || k}</span><span className="tabnum text-faint">{n}</span>
            </div>
            <div className="h-1.5 rounded bg-surface-3 overflow-hidden">
              <div className="h-full bg-brand-500" style={{ width: `${(n / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
