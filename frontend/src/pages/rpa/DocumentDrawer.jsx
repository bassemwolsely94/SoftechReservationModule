/**
 * DocumentDrawer — one RPA document: its lines (match status / message / warning), the runs with
 * their step list and screenshots, and — only when the document `needs_person` — the resolve
 * form. A side panel (not a modal); the reason field is inline (rule 11). The server decides
 * who may resolve; this only calls the API.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { Badge, DOC_STATUS, LINE_STATUS, OUTCOME, asList, errText, fmtTime } from './shared.jsx'

const lineValue = (r, k) => (k === 'status' ? (LINE_STATUS[r.status]?.label || r.status) : r[k])

function Lines({ lines }) {
  const { sorted, headerProps } = useSortableRows(lines, { getValue: lineValue, persistKey: 'rpa-lines' })
  if (!lines.length) return <div className="text-sm text-muted">لا توجد أسطر.</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted border-b border-line">
            <SortTh {...headerProps('row_no', 'number')} className="p-2 text-start">#</SortTh>
            <SortTh {...headerProps('itemcode')} className="p-2 text-start">كود الصنف</SortTh>
            <SortTh {...headerProps('item_name')} className="p-2 text-start">الصنف</SortTh>
            <SortTh {...headerProps('qty', 'number')} className="p-2 text-end">الكمية</SortTh>
            <SortTh {...headerProps('expiry', 'date')} className="p-2 text-start">الصلاحية</SortTh>
            <SortTh {...headerProps('status')} className="p-2 text-start">المطابقة</SortTh>
            <SortTh {...headerProps('message')} className="p-2 text-start">الرسالة</SortTh>
            <SortTh {...headerProps('warning')} className="p-2 text-start">تحذير</SortTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map(l => (
            <tr key={l.id ?? l.row_no} className="border-b border-line align-top">
              <td className="p-2 tabular-nums">{l.row_no}</td>
              <td className="p-2 font-mono" dir="ltr">{l.itemcode || '—'}</td>
              <td className="p-2">{l.item_name || l.item?.name || '—'}</td>
              <td className="p-2 text-end tabular-nums">{l.qty ?? '—'}</td>
              <td className="p-2 tabular-nums">{l.expiry || '—'}</td>
              <td className={`p-2 ${LINE_STATUS[l.status]?.cls || ''}`}>{LINE_STATUS[l.status]?.label || l.status}</td>
              <td className="p-2 text-muted">{l.message || ''}</td>
              <td className="p-2 text-amber-700 dark:text-amber-300">{l.warning || ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Run({ run }) {
  const steps = Array.isArray(run.steps) ? run.steps : []
  const shots = run.screenshots || run.shots || []
  return (
    <div className="rounded-lg border border-line p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">تشغيل #{run.id}</span>
        <span className="text-muted">{run.mode === 'live' ? 'حقيقي' : 'تجربة'}</span>
        <span>{OUTCOME[run.outcome] ?? run.outcome}</span>
        <span className="text-xs text-muted">{fmtTime(run.started_at)}</span>
        {run.device_label && <span className="text-xs text-muted">· {run.device_label}</span>}
      </div>
      {steps.length > 0 && (
        <ol className="list-decimal ps-5 text-xs space-y-0.5 text-muted">
          {steps.map((s, i) => (
            <li key={i}>{typeof s === 'string' ? s : (s.label || s.name || s.step || s.message || JSON.stringify(s))}</li>
          ))}
        </ol>
      )}
      {shots.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {shots.map((s, i) => {
            const url = typeof s === 'string' ? s : (s.url || s.image)
            if (!url) return null
            return (
              <a key={s.id ?? i} href={url} target="_blank" rel="noreferrer" title={`خطوة ${s.step_index ?? i + 1}`}>
                <img src={url} alt={`لقطة الشاشة — خطوة ${s.step_index ?? i + 1}`}
                     className="h-20 w-32 object-cover rounded border border-line" loading="lazy" />
              </a>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function DocumentDrawer({ documentId, onClose }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  const q = useQuery({
    queryKey: ['rpa', 'document', documentId],
    queryFn: () => rpaApi.document(documentId).then(r => r.data),
  })
  const doc = q.data
  const lines = useMemo(() => asList(doc?.lines), [doc])
  const runs = useMemo(() => asList(doc?.runs), [doc])

  const resolve = useMutation({
    mutationFn: () => rpaApi.resolve(documentId, reason.trim()),
    onSuccess: () => {
      setReason(''); setErr('')
      qc.invalidateQueries({ queryKey: ['rpa'] })
    },
    onError: e => setErr(errText(e)),
  })

  return (
    <aside className="card p-4 space-y-4" aria-label="تفاصيل المستند">
      <div className="flex items-center gap-2">
        <h2 className="font-bold">مستند {doc?.reference || `#${documentId}`}</h2>
        {doc && <Badge map={DOC_STATUS} value={doc.status} />}
        {doc?.softech_docnumber ? <span className="text-xs text-muted">رقم SOFTECH: {doc.softech_docnumber}</span> : null}
        <button type="button" className="btn-ghost ms-auto text-sm" onClick={onClose}>إغلاق</button>
      </div>

      {q.isLoading && <div className="text-muted text-sm">جارٍ التحميل…</div>}
      {q.isError && <div className="text-red-600 text-sm">تعذّر تحميل المستند.</div>}

      {doc && doc.status === 'needs_person' && (
        <div data-tour="rpa-main-resolve" className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 space-y-2">
          <div className="text-sm font-semibold">يحتاج مراجعة</div>
          {doc.needs_person_reason && <div className="text-sm">{doc.needs_person_reason}</div>}
          <label className="label" htmlFor="rpa-resolve-reason">سبب الحسم (مطلوب)</label>
          <input id="rpa-resolve-reason" className="input-field w-full" value={reason} maxLength={250}
                 onChange={e => setReason(e.target.value)}
                 placeholder="مثال: راجعت SOFTECH ولا يوجد مستند محفوظ" />
          <div className="flex items-center gap-2">
            <button type="button" className="btn-primary text-sm"
                    disabled={!reason.trim() || resolve.isPending} onClick={() => resolve.mutate()}>
              {resolve.isPending ? 'جارٍ الحفظ…' : 'سجّل الحسم'}
            </button>
            {err && <span className="text-xs text-red-600">{err}</span>}
          </div>
        </div>
      )}

      {doc && (
        <>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">الأسطر ({lines.length})</h3>
            <Lines lines={lines} />
          </section>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">التشغيلات ({runs.length})</h3>
            {runs.length === 0 && <div className="text-sm text-muted">لم يبدأ أي تشغيل بعد.</div>}
            {runs.map(r => <Run key={r.id} run={r} />)}
          </section>
        </>
      )}
    </aside>
  )
}
