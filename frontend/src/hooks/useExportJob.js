// useExportJob — one export button for every screen (performance Stage 4).
//
// The server builds the file as a background job: `run(...)` starts it (≤ 1 s), the hook polls
// its progress every 1.5 s, downloads the file once when it is ready and forgets the job. The
// user keeps working meanwhile; the job id is kept in sessionStorage per screen, so leaving the
// screen and coming back keeps following the same job. A second click while one runs attaches
// to it (the server answers 409 with its id). Render <ExportJobStatus> next to the button.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { exportJobsApi } from '../api/client'
import { downloadBlob, errText } from '../pages/supply/supplyUi'

export const RUNNING = ['queued', 'running']

// the server names the file (it knows the effective period / run date)
export function fileNameOf(r, fallback) {
  const cd = r?.headers?.['content-disposition'] || ''
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i)
  const plain = cd.match(/filename="?([^";]+)"?/i)
  try { return (star ? decodeURIComponent(star[1]) : (plain ? plain[1] : '')) || fallback } catch { return (plain ? plain[1] : '') || fallback }
}

function read(key) {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    if (/^\d+$/.test(raw)) return { id: Number(raw) }          // PIC's older plain-id entry
    const v = JSON.parse(raw)
    return v && v.id ? v : null
  } catch { return null }
}
function save(key, v) {
  try { if (v) sessionStorage.setItem(key, JSON.stringify(v)); else sessionStorage.removeItem(key) } catch { /* ignore */ }
}

/**
 * @param {object} o
 * @param {string} o.storageKey  one per screen/button, e.g. 'export-job:purchasing'
 * @param {(...args) => Promise} o.start  posts the start request; resolves to the axios response ({data: {id}})
 * @param {(...args) => string} [o.fileName]  a name chosen at start (else the server's)
 * @param {(id) => Promise} [o.status]  defaults to /api/export-jobs/<id>/
 * @param {(id) => Promise} [o.file]    defaults to /api/export-jobs/<id>/download/
 */
export default function useExportJob({ storageKey, start, fileName, status = exportJobsApi.status, file = exportJobsApi.file }) {
  const [cur, setCur] = useState(() => read(storageKey))
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const downloaded = useRef(null)
  const lastArgs = useRef([])

  const attach = v => { save(storageKey, v); setCur(v) }
  const drop = () => { save(storageKey, null); setCur(null) }
  const id = cur?.id || null

  const q = useQuery({
    queryKey: ['export-job', storageKey, id],
    queryFn: () => status(id).then(r => r.data),
    enabled: !!id, gcTime: 0,
    retry: (n, e) => n < 2 && ![403, 404].includes(e?.response?.status),   // rides out a deploy blip, not a gone job
    refetchInterval: s => (!s.state.data || RUNNING.includes(s.state.data.status) ? 1500 : false),
  })
  const job = q.data

  useEffect(() => {
    if (!id) return
    if (q.isError) {                         // gone (older than 48 h, or dropped by an update): say so
      drop()
      setError(q.error?.response?.status === 404
        ? 'انتهت صلاحية الملف — صدّر مرة أخرى'
        : errText(q.error, 'تعذّر متابعة التصدير'))
      return
    }
    if (job?.status === 'failed') { drop(); setError(job.error || 'تعذّر إنشاء الملف — حاول مرة أخرى'); return }
    if (job?.status === 'done' && downloaded.current !== id) {
      downloaded.current = id
      file(id)
        .then(r => downloadBlob(r.data, cur?.name || fileNameOf(r, job.file_name || 'export.xlsx')))
        .catch(e => setError(errText(e, 'تعذّر تنزيل الملف')))
        .finally(drop)
    }
  }, [id, job, q.isError]) // eslint-disable-line react-hooks/exhaustive-deps

  const busy = starting || (!!id && (!job || RUNNING.includes(job.status) || job.status === 'done'))

  const run = async (...args) => {
    if (busy) return
    lastArgs.current = args
    setStarting(true); setError('')
    const name = fileName ? fileName(...args) : undefined
    try {
      const r = await start(...args)
      attach({ id: r.data.id, name })
    } catch (e) {
      const d = e?.response?.data
      if (e?.response?.status === 409 && d?.id) attach({ id: d.id })    // one already running: follow it
      else setError(errText(e, 'تعذّر تصدير الملف'))
    } finally { setStarting(false) }
  }

  return {
    run, busy, error, job,
    running: !!id && (!job || RUNNING.includes(job.status)),
    retry: () => run(...lastArgs.current),
    clearError: () => setError(''),
  }
}
