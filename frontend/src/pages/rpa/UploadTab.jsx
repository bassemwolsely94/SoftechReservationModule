/**
 * UploadTab — رفع ملف: upload an issue-order (إذن صرف) sheet. Stage 1 accepts only the
 * `issue_125` screen. The server parses and validates; this form just sends the multipart body
 * and shows what comes back (including its Arabic refusals, e.g. a file uploaded before).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi, rpaApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import ProgressBar from '../../components/ProgressBar'
import { SCREEN_LABEL, asList, errText } from './shared.jsx'

export default function UploadTab({ onUploaded }) {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [branch, setBranch] = useState('')
  const [target, setTarget] = useState('')
  const [store, setStore] = useState('')
  const [file, setFile] = useState(null)
  const [err, setErr] = useState('')
  const [done, setDone] = useState(null)

  const branchesQ = useQuery({
    queryKey: ['rpa', 'branches'],
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 30 * 60 * 1000,
  })
  const branches = useMemo(() => asList(branchesQ.data), [branchesQ.data])
  const branchName = b => (b.softech_branch_id ? bl(b.softech_branch_id) : (b.name_ar || b.name))

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('screen', 'issue_125')
      fd.append('branch', branch)
      fd.append('target_branch', target)
      fd.append('store_code', store.trim())
      fd.append('file', file)
      return rpaApi.createJob(fd).then(r => r.data)
    },
    onSuccess: data => {
      setErr(''); setFile(null); setDone(data?.id ?? data?.job?.id ?? true)
      qc.invalidateQueries({ queryKey: ['rpa'] })
    },
    onError: e => {
      const id = e?.response?.data?.job_id
      setDone(null)
      setErr(errText(e) + (id ? ` (الأمر رقم ${id})` : ''))
    },
  })

  const ready = branch && target && file && !upload.isPending

  return (
    <form data-tour="rpa-main-upload" className="card p-4 space-y-4 max-w-2xl"
          onSubmit={e => { e.preventDefault(); if (ready) { setDone(null); upload.mutate() } }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="rpa-screen">الشاشة</label>
          <select id="rpa-screen" className="input-field w-full" value="issue_125" disabled>
            <option value="issue_125">{SCREEN_LABEL.issue_125}</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="rpa-store">كود المخزن (اختياري)</label>
          <input id="rpa-store" className="input-field w-full" value={store} dir="ltr" maxLength={20}
                 onChange={e => setStore(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="rpa-branch">من فرع</label>
          <select id="rpa-branch" className="input-field w-full" value={branch} onChange={e => setBranch(e.target.value)}>
            <option value="">اختر الفرع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{branchName(b)}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="rpa-target">إلى فرع (المستلم)</label>
          <select id="rpa-target" className="input-field w-full" value={target} onChange={e => setTarget(e.target.value)}>
            <option value="">اختر الفرع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{branchName(b)}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="rpa-file">ملف إذن الصرف (Excel)</label>
        <input id="rpa-file" type="file" accept=".xlsx,.xls,.csv" className="block text-sm"
               onChange={e => setFile(e.target.files?.[0] || null)} />
      </div>

      {upload.isPending && <ProgressBar label="رفع الملف وقراءة الأسطر" />}
      {err && <div className="text-sm text-red-600">{err}</div>}
      {done && <div className="text-sm text-green-700 dark:text-green-300">
        تم رفع الملف{typeof done === 'number' ? ` — أمر رقم ${done}` : ''}. يحتاج اعتمادًا من شخص آخر.
      </div>}

      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary" disabled={!ready}>رفع الملف</button>
        {done && onUploaded && <button type="button" className="btn-ghost text-sm" onClick={onUploaded}>عرض الأوامر</button>}
      </div>
    </form>
  )
}
