/**
 * JobsTab — الأوامر: the jobs grid (server-sorted) and the selected job's documents.
 * Keys (useGridKeyboard): ↑↓ move · Enter open the job. The buttons only call the API;
 * the server decides who may approve (never the uploader) or cancel.
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaApi } from '../../api/client'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useServerSort from '../../hooks/useServerSort'
import useSortableRows from '../../hooks/useSortableRows'
import useBranchLabels from '../../hooks/useBranchLabels'
import SortTh from '../../components/SortTh'
import DocumentDrawer from './DocumentDrawer'
import { Badge, DOC_STATUS, DRY_RUN_TEXT, JOB_STATUS, asList, branchText, errText, fmtTime, screenTitle } from './shared.jsx'

// server ordering keys (Task 9 whitelist must accept these)
const ALLOWED = ['id', 'created_at', 'screen', 'branch', 'target_branch', 'filename', 'status']
const docValue = (d, k) => (k === 'status' ? (DOC_STATUS[d.status]?.label || d.status) : d[k])

function DryRunBadge() {
  return (
    <span className="text-xs rounded px-1.5 py-0.5 bg-brand-600/10 text-brand-700 dark:text-brand-300 whitespace-nowrap">
      {DRY_RUN_TEXT}
    </span>
  )
}

function JobDetail({ jobId, onOpenDoc, openDocId }) {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [cancelReason, setCancelReason] = useState('')
  const q = useQuery({ queryKey: ['rpa', 'job', jobId], queryFn: () => rpaApi.job(jobId).then(r => r.data), refetchInterval: 15000 })
  const job = q.data
  const docs = useMemo(() => asList(job?.documents), [job])
  const { sorted, headerProps } = useSortableRows(docs, { getValue: docValue, persistKey: 'rpa-job-docs' })
  const after = () => { setErr(''); setCancelReason(''); qc.invalidateQueries({ queryKey: ['rpa'] }) }
  const approve = useMutation({ mutationFn: () => rpaApi.approveJob(jobId), onSuccess: after, onError: e => setErr(errText(e)) })
  const cancel = useMutation({ mutationFn: () => rpaApi.cancelJob(jobId, cancelReason.trim()), onSuccess: after, onError: e => setErr(errText(e)) })

  if (q.isLoading) return <div className="card p-4 text-muted text-sm">جارٍ التحميل…</div>
  if (q.isError || !job) return <div className="card p-4 text-red-600 text-sm">تعذّر تحميل الأمر.</div>
  return (
    <div className="card p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-bold">أمر #{job.id}</h2>
        <Badge map={JOB_STATUS} value={job.status} />
        {job.dry_run !== false && <DryRunBadge />}
        <div className="ms-auto flex items-center gap-2">
          {err && <span className="text-xs text-red-600">{err}</span>}
          {job.status === 'uploaded' && (
            <button type="button" data-tour="rpa-main-job-approve" className="btn-primary text-sm"
                    disabled={approve.isPending} onClick={() => approve.mutate()}>
              {approve.isPending ? 'جارٍ الاعتماد…' : 'اعتماد الأمر'}
            </button>
          )}
          {['uploaded', 'approved'].includes(job.status) && (
            <>
              <label className="sr-only" htmlFor={`rpa-cancel-reason-${job.id}`}>سبب الإلغاء</label>
              <input id={`rpa-cancel-reason-${job.id}`} className="input-field text-sm w-48" maxLength={250}
                     value={cancelReason} onChange={e => setCancelReason(e.target.value)}
                     placeholder="سبب الإلغاء (مطلوب)" />
              <button type="button" className="btn-secondary text-sm"
                      disabled={!cancelReason.trim() || cancel.isPending} onClick={() => cancel.mutate()}>
                {cancel.isPending ? 'جارٍ الإلغاء…' : 'إلغاء الأمر'}
              </button>
            </>
          )}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <SortTh {...headerProps('seq', 'number')} className="p-2 text-start">المستند</SortTh>
              <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
              <SortTh {...headerProps('line_count', 'number')} className="p-2 text-end">الأسطر</SortTh>
              <SortTh {...headerProps('softech_docnumber', 'number')} className="p-2 text-end">رقم SOFTECH</SortTh>
              <SortTh {...headerProps('needs_person_reason')} className="p-2 text-start">السبب</SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.map(d => (
              <tr key={d.id} onClick={() => onOpenDoc(d.id)}
                  className={`border-b border-line cursor-pointer hover:bg-surface-2 ${openDocId === d.id ? 'bg-surface-2' : ''}`}>
                <td className="p-2">{d.reference || `#${d.id}`}</td>
                <td className="p-2"><Badge map={DOC_STATUS} value={d.status} /></td>
                <td className="p-2 text-end tabular-nums">{d.line_count ?? asList(d.lines).length}</td>
                <td className="p-2 text-end tabular-nums">{d.softech_docnumber ?? '—'}</td>
                <td className="p-2 text-muted">{d.needs_person_reason || ''}</td>
              </tr>
            ))}
            {!sorted.length && <tr><td colSpan={5} className="p-4 text-center text-muted">لا توجد مستندات.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function JobsTab() {
  const bl = useBranchLabels()
  const [ordering, setOrdering] = useState('-created_at')
  const [jobId, setJobId] = useState(null)
  const [docId, setDocId] = useState(null)
  const { headerProps } = useServerSort(ordering, setOrdering, { allowed: ALLOWED, defaultOrdering: '-created_at' })
  const q = useQuery({
    queryKey: ['rpa', 'jobs', ordering],
    queryFn: () => rpaApi.jobs({ ordering }).then(r => r.data),
    refetchInterval: 15000,
  })
  const rows = useMemo(() => asList(q.data), [q.data])
  const open = useCallback(r => { setJobId(r.id); setDocId(null) }, [])
  const kb = useGridKeyboard({ rows, getKey: r => r.id, onConfirm: open, onOpen: open })

  return (
    <div className="space-y-4">
      <div data-tour="rpa-main-jobs" className="card p-0 overflow-x-auto" {...kb.containerProps}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <SortTh {...headerProps('id', 'number')} className="p-2 text-start">#</SortTh>
              <SortTh {...headerProps('created_at', 'date')} className="p-2 text-start">وقت الرفع</SortTh>
              <SortTh {...headerProps('screen')} className="p-2 text-start">الشاشة</SortTh>
              <SortTh {...headerProps('branch')} className="p-2 text-start">من فرع</SortTh>
              <SortTh {...headerProps('target_branch')} className="p-2 text-start">إلى فرع</SortTh>
              <SortTh {...headerProps('filename')} className="p-2 text-start">الملف</SortTh>
              <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.id} {...rp} onClick={() => { rp.onClick?.(); open(r) }}
                    className={`border-b border-line cursor-pointer ${rp.className} ${jobId === r.id ? 'bg-surface-2' : ''}`}>
                  <td className="p-2 tabular-nums">{r.id}</td>
                  <td className="p-2 whitespace-nowrap text-xs">{fmtTime(r.created_at)}</td>
                  <td className="p-2">{screenTitle(r)}</td>
                  <td className="p-2">{branchText(bl, r, 'branch')}</td>
                  <td className="p-2">{branchText(bl, r, 'target_branch')}</td>
                  <td className="p-2 text-muted" dir="ltr">{r.filename || '—'}</td>
                  <td className="p-2"><Badge map={JOB_STATUS} value={r.status} /></td>
                  <td className="p-2">{r.dry_run !== false && <DryRunBadge />}</td>
                </tr>
              )
            })}
            {q.isLoading && <tr><td colSpan={8} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={8} className="p-6 text-center text-red-600">تعذّر تحميل الأوامر.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && (
              <tr><td colSpan={8} className="p-6 text-center text-muted">لا توجد أوامر بعد — ارفع ملفًا من تبويب «رفع ملف».</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-faint">⌨ ↑↓ تنقل · Enter فتح الأمر · اضغط على عنوان العمود للترتيب</div>

      {jobId && <JobDetail jobId={jobId} onOpenDoc={setDocId} openDocId={docId} />}
      {docId && <DocumentDrawer documentId={docId} onClose={() => setDocId(null)} />}
    </div>
  )
}
