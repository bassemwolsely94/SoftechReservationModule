/**
 * BuyListTab — قوائم الشراء: new list (file / pivot / supply request), the lists, one list's lines
 * with a supplier per line, then per supplier: a robot job (site suppliers) or a WhatsApp / Excel
 * order list (the others). The job panel approves / cancels; the server decides (need check,
 * four-eyes, locked lines).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaPortalApi } from '../../../api/client'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import ProgressBar from '../../../components/ProgressBar'
import {
  Badge, BASKET_STATUS, JOB_STATUS, LIST_STATUS, ModeBadge, NeedsPersonBadge, SOURCE, asList, credit,
  downloadBlob, errText, fmtTime, supplierText,
} from './shared.jsx'

const listValue = (r, k) => (k === 'source_kind' ? SOURCE[r.source_kind] : r[k])

function NewList({ onCreated }) {
  const qc = useQueryClient()
  const [file, setFile] = useState(null)
  const [pivot, setPivot] = useState('')
  const [isr, setIsr] = useState('')
  const [err, setErr] = useState('')
  const [rejected, setRejected] = useState([])
  const done = data => {
    setErr(''); setRejected(data?.errors || []); setFile(null); setPivot(''); setIsr('')
    qc.invalidateQueries({ queryKey: ['rpa-portal'] })
    onCreated(data.id)
  }
  const fail = e => { setErr(errText(e)); setRejected(e?.response?.data?.errors || []) }
  const upload = useMutation({
    mutationFn: () => { const fd = new FormData(); fd.append('file', file); return rpaPortalApi.upload(fd).then(r => r.data) },
    onSuccess: done, onError: fail,
  })
  const fromPivot = useMutation({ mutationFn: () => rpaPortalApi.fromPivot(Number(pivot)).then(r => r.data), onSuccess: done, onError: fail })
  const fromIsr = useMutation({ mutationFn: () => rpaPortalApi.fromIsr(Number(isr)).then(r => r.data), onSuccess: done, onError: fail })
  const busy = upload.isPending || fromPivot.isPending || fromIsr.isPending

  return (
    <div data-tour="rpa-portals-new-list" className="card p-4 space-y-3">
      <h2 className="font-bold text-sm">قائمة شراء جديدة</h2>
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label className="label" htmlFor="pl-file">ملف Excel (كود الصنف، الكمية)</label>
          <div className="flex items-center gap-2">
            <input id="pl-file" type="file" accept=".xlsx,.csv" className="block text-sm"
                   onChange={e => setFile(e.target.files?.[0] || null)} />
            <button type="button" className="btn-primary text-sm" disabled={!file || busy} onClick={() => upload.mutate()}>رفع الملف</button>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="pl-pivot">من البيفوت (رقم اللقطة)</label>
          <div className="flex items-center gap-2">
            <input id="pl-pivot" type="number" min="1" step="1" className="input-field w-28" value={pivot}
                   onChange={e => setPivot(e.target.value)} />
            <button type="button" className="btn-secondary text-sm" disabled={!pivot || busy} onClick={() => fromPivot.mutate()}>إنشاء</button>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="pl-isr">من طلب توريد (رقم الطلب)</label>
          <div className="flex items-center gap-2">
            <input id="pl-isr" type="number" min="1" step="1" className="input-field w-28" value={isr}
                   onChange={e => setIsr(e.target.value)} />
            <button type="button" className="btn-secondary text-sm" disabled={!isr || busy} onClick={() => fromIsr.mutate()}>إنشاء</button>
          </div>
        </div>
      </div>
      {busy && <ProgressBar label="إنشاء القائمة وترتيب الموردين" />}
      {err && <div className="text-sm text-red-600">{err}</div>}
      {rejected.length > 0 && (
        <div className="text-sm">
          <div className="text-amber-700 dark:text-amber-300 font-medium">أسطر لم تُقبل ({rejected.length}):</div>
          <ul className="list-disc ms-5 text-muted">
            {rejected.slice(0, 30).map((e, i) => <li key={i}><span dir="ltr">{e.item_code || '—'}</span> — {e.error}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function JobPanel({ jobId }) {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [reasons, setReasons] = useState({})
  const [cancelReason, setCancelReason] = useState('')
  const q = useQuery({ queryKey: ['rpa-portal', 'job', jobId], queryFn: () => rpaPortalApi.job(jobId).then(r => r.data),
                       refetchInterval: 15000 })
  const job = q.data
  const after = () => { setErr(''); setCancelReason(''); qc.invalidateQueries({ queryKey: ['rpa-portal'] }) }
  const approve = useMutation({ mutationFn: () => rpaPortalApi.approveJob(jobId, reasons), onSuccess: after, onError: e => setErr(errText(e)) })
  const cancel = useMutation({ mutationFn: () => rpaPortalApi.cancelJob(jobId, cancelReason.trim()), onSuccess: after, onError: e => setErr(errText(e)) })
  const lines = useMemo(() => asList(job?.lines), [job])
  const baskets = useMemo(() => asList(job?.baskets), [job])
  const { sorted, headerProps } = useSortableRows(baskets, { persistKey: 'portal-job-baskets',
    getValue: (b, k) => (k === 'status' ? BASKET_STATUS[b.status]?.label : b[k]) })

  if (q.isLoading) return <div className="text-muted text-sm p-2">جارٍ التحميل…</div>
  if (q.isError || !job) return <div className="text-red-600 text-sm p-2">تعذّر تحميل المهمة.</div>
  const disc = job.discovery || {}
  return (
    <div className="rounded-lg border border-line p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">مهمة #{job.id}</span>
        <Badge map={JOB_STATUS} value={job.status} />
        <ModeBadge dryRun={job.dry_run} />
        <span className="text-xs text-muted">{job.portal_title} · {job.account_label} · {credit(job.account_last_credit)}</span>
        {job.estimated_value != null && <span className="text-xs text-muted">القيمة التقديرية {job.estimated_value}</span>}
        {disc.needs_person && (
          <span className="text-xs rounded px-1.5 py-0.5 bg-red-500/10 text-red-700 dark:text-red-300">
            تحتاج موظف — فشلت قراءة الأكواد {disc.failed_reads} مرات، أكّدها من «الأكواد»
          </span>
        )}
        {!disc.needs_person && disc.missing_codes > 0 && (
          <span className="text-xs text-muted">أصناف بلا كود: {disc.missing_codes}</span>
        )}
        <div className="ms-auto flex flex-wrap items-center gap-2">
          {err && <span className="text-xs text-red-600">{err}</span>}
          {job.status === 'draft' && (
            <button type="button" data-tour="rpa-portals-job-approve" className="btn-primary text-sm"
                    disabled={approve.isPending} onClick={() => approve.mutate()}>
              {approve.isPending ? 'جارٍ الاعتماد…' : 'اعتماد المهمة'}
            </button>
          )}
          {['draft', 'approved'].includes(job.status) && (
            <>
              <label className="sr-only" htmlFor={`pj-cancel-${job.id}`}>سبب الإلغاء</label>
              <input id={`pj-cancel-${job.id}`} className="input-field text-sm w-44" maxLength={250} value={cancelReason}
                     onChange={e => setCancelReason(e.target.value)} placeholder="سبب الإلغاء (مطلوب)" />
              <button type="button" className="btn-secondary text-sm" disabled={!cancelReason.trim() || cancel.isPending}
                      onClick={() => cancel.mutate()}>إلغاء المهمة</button>
            </>
          )}
        </div>
      </div>
      {job.status === 'draft' && lines.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <th className="p-1.5 text-start">الصنف</th><th className="p-1.5 text-end">الكمية</th>
            <th className="p-1.5 text-start">سبب الزيادة عن الاحتياج (إن طُلب)</th>
          </tr></thead>
          <tbody>
            {lines.map(ln => (
              <tr key={ln.id} className="border-b border-line">
                <td className="p-1.5">{ln.item_name} <span className="text-xs text-muted" dir="ltr">{ln.item_code}</span></td>
                <td className="p-1.5 text-end tabular-nums">{ln.remaining_qty}</td>
                <td className="p-1.5">
                  <input className="input-field text-sm w-full" maxLength={250} value={reasons[ln.id] || ''}
                         aria-label={`سبب ${ln.item_name}`}
                         onChange={e => setReasons(r => ({ ...r, [ln.id]: e.target.value }))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {baskets.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('seq', 'number')} className="p-1.5 text-start">السلة</SortTh>
            <SortTh {...headerProps('status')} className="p-1.5 text-start">الحالة</SortTh>
            <SortTh {...headerProps('line_count', 'number')} className="p-1.5 text-end">الأصناف</SortTh>
            <SortTh {...headerProps('portal_ref')} className="p-1.5 text-start">رقم الطلب</SortTh>
          </tr></thead>
          <tbody>
            {sorted.map(b => (
              <tr key={b.id} className="border-b border-line">
                <td className="p-1.5 tabular-nums">{b.seq}</td>
                <td className="p-1.5"><Badge map={BASKET_STATUS} value={b.status} /> <NeedsPersonBadge show={b.needs_person && b.status !== 'needs_person'} /></td>
                <td className="p-1.5 text-end tabular-nums">{b.line_count}</td>
                <td className="p-1.5" dir="ltr">{b.portal_ref || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function SupplierActions({ list, code, lines, portals, accounts, onJob }) {
  const qc = useQueryClient()
  const [account, setAccount] = useState('')
  const [err, setErr] = useState('')
  const [text, setText] = useState('')
  const portal = portals.find(p => p.supplier_code === code)
  const mine = accounts.filter(a => portal && a.portal === portal.key && a.active)
  const chosen = mine.find(a => String(a.id) === String(account))
  const createJob = useMutation({
    mutationFn: () => rpaPortalApi.createJob({ buylist_id: list.id, portal: portal.key, account_id: Number(account) }).then(r => r.data),
    onSuccess: d => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa-portal'] }); onJob(d.id) },
    onError: e => setErr(errText(e)),
  })
  const sendText = useMutation({
    mutationFn: () => rpaPortalApi.sendOther(list.id, code).then(r => r.data),
    onSuccess: d => { setErr(''); setText(d.text || ''); qc.invalidateQueries({ queryKey: ['rpa-portal'] }) },
    onError: e => setErr(errText(e)),
  })
  const sendXlsx = useMutation({
    mutationFn: () => rpaPortalApi.sendOtherXlsx(list.id, code).then(r => r.data),
    onSuccess: d => { setErr(''); downloadBlob(d, `order-${code}-${list.id}.xlsx`); qc.invalidateQueries({ queryKey: ['rpa-portal'] }) },
    onError: e => setErr(errText(e)),
  })
  const open = lines.filter(l => l.remaining_qty > 0).length
  return (
    <div className="rounded-lg border border-line p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">{supplierText(list.suppliers, code)}</span>
        <span className="text-muted">{open} صنف</span>
        {portal ? (
          <div data-tour="rpa-portals-account" className="flex flex-wrap items-center gap-2 ms-auto">
            <label className="sr-only" htmlFor={`pa-${code}`}>حساب الموقع</label>
            <select id={`pa-${code}`} className="input-field text-sm" value={account} onChange={e => setAccount(e.target.value)}>
              <option value="">اختر حساب الموقع</option>
              {mine.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
            {chosen && <span className="text-xs text-muted">آخر رصيد: {credit(chosen.last_credit)}</span>}
            <button type="button" className="btn-primary text-sm" disabled={!account || !open || createJob.isPending}
                    onClick={() => createJob.mutate()}>إنشاء مهمة للروبوت</button>
          </div>
        ) : (
          <div className="flex items-center gap-2 ms-auto">
            <button type="button" className="btn-secondary text-sm" disabled={!open || sendText.isPending} onClick={() => sendText.mutate()}>قائمة واتساب</button>
            <button type="button" className="btn-secondary text-sm" disabled={!open || sendXlsx.isPending} onClick={() => sendXlsx.mutate()}>Excel</button>
          </div>
        )}
      </div>
      {err && <div className="text-xs text-red-600">{err}</div>}
      {text && (
        <div className="space-y-1">
          <textarea readOnly className="input-field w-full text-sm h-32" value={text} aria-label="نص الطلبية" />
          <button type="button" className="btn-ghost text-xs" onClick={() => navigator.clipboard?.writeText(text)}>نسخ النص</button>
        </div>
      )}
    </div>
  )
}

function ListDetail({ listId }) {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [jobId, setJobId] = useState(null)
  const q = useQuery({ queryKey: ['rpa-portal', 'buylist', listId], queryFn: () => rpaPortalApi.buylist(listId).then(r => r.data) })
  const portalsQ = useQuery({ queryKey: ['rpa-portal', 'portals'], queryFn: () => rpaPortalApi.portals().then(r => r.data) })
  const accountsQ = useQuery({ queryKey: ['rpa-portal', 'accounts'], queryFn: () => rpaPortalApi.accounts().then(r => r.data) })
  const list = q.data
  const lines = useMemo(() => asList(list?.lines), [list])
  const { sorted, headerProps } = useSortableRows(lines, { persistKey: 'portal-buylist-lines',
    getValue: (r, k) => (k === 'chosen_supplier' ? supplierText(list?.suppliers, r.chosen_supplier) : r[k]) })
  const pick = useMutation({
    mutationFn: ({ line, supplier }) => rpaPortalApi.pick(listId, line, supplier),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa-portal', 'buylist', listId] }) },
    onError: e => setErr(errText(e)),
  })
  const groups = useMemo(() => {
    const g = {}
    lines.forEach(l => { if (l.chosen_supplier) (g[l.chosen_supplier] = g[l.chosen_supplier] || []).push(l) })
    return g
  }, [lines])

  if (q.isLoading) return <div className="card p-4 text-muted text-sm">جارٍ التحميل…</div>
  if (q.isError || !list) return <div className="card p-4 text-red-600 text-sm">تعذّر تحميل القائمة.</div>
  const portals = portalsQ.data?.portals || []
  const accounts = asList(accountsQ.data)
  const isOpen = list.status === 'open'
  return (
    <div className="card p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-bold">قائمة شراء #{list.id}</h2>
        <Badge map={LIST_STATUS} value={list.status} />
        <span className="text-xs text-muted">{SOURCE[list.source_kind]} {list.source_ref}</span>
        {err && <span className="text-xs text-red-600 ms-auto">{err}</span>}
      </div>
      <div data-tour="rpa-portals-buylist" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('seq', 'number')} className="p-2 text-start">#</SortTh>
            <SortTh {...headerProps('item_code')} className="p-2 text-start">الكود</SortTh>
            <SortTh {...headerProps('item_name')} className="p-2 text-start">الصنف</SortTh>
            <SortTh {...headerProps('needed_qty', 'number')} className="p-2 text-end">المطلوب</SortTh>
            <SortTh {...headerProps('remaining_qty', 'number')} className="p-2 text-end">الباقي</SortTh>
            <SortTh {...headerProps('chosen_supplier')} className="p-2 text-start">المورد</SortTh>
          </tr></thead>
          <tbody>
            {sorted.map(ln => {
              const options = Array.from(new Set([...(ln.ranking || []), ln.chosen_supplier].filter(Boolean)))
              return (
                <tr key={ln.id} className="border-b border-line">
                  <td className="p-2 tabular-nums">{ln.seq}</td>
                  <td className="p-2" dir="ltr">{ln.item_code}</td>
                  <td className="p-2">{ln.item_name}</td>
                  <td className="p-2 text-end tabular-nums">{ln.needed_qty}</td>
                  <td className="p-2 text-end tabular-nums">{ln.remaining_qty}</td>
                  <td className="p-2">
                    {ln.frozen || !isOpen ? (
                      <span>{supplierText(list.suppliers, ln.chosen_supplier)}
                        {ln.frozen && <span className="ms-1 text-xs rounded px-1.5 py-0.5 bg-surface-2 text-muted">مقفول</span>}</span>
                    ) : (
                      <select className="input-field text-sm" value={ln.chosen_supplier} aria-label={`مورد ${ln.item_name}`}
                              onChange={e => pick.mutate({ line: ln.id, supplier: e.target.value })}>
                        {!ln.chosen_supplier && <option value="">اختر المورد</option>}
                        {options.map((c, i) => <option key={c} value={c}>{i === 0 && ln.ranking?.[0] === c ? '★ ' : ''}{supplierText(list.suppliers, c)}</option>)}
                      </select>
                    )}
                  </td>
                </tr>
              )
            })}
            {!sorted.length && <tr><td colSpan={6} className="p-4 text-center text-muted">لا توجد أسطر.</td></tr>}
          </tbody>
        </table>
      </div>
      {isOpen && Object.entries(groups).map(([code, ls]) => (
        <SupplierActions key={code} list={list} code={code} lines={ls} portals={portals} accounts={accounts} onJob={setJobId} />
      ))}
      {asList(list.jobs).length > 0 && (
        <div className="space-y-2">
          <h3 className="font-semibold text-sm">المهام</h3>
          <div className="flex flex-wrap gap-2">
            {asList(list.jobs).map(j => (
              <button key={j.id} type="button" onClick={() => setJobId(j.id)}
                      className={`text-sm rounded border px-2 py-1 ${jobId === j.id ? 'border-brand-600' : 'border-line'}`}>
                #{j.id} <Badge map={JOB_STATUS} value={j.status} />
              </button>
            ))}
          </div>
        </div>
      )}
      {jobId && <JobPanel jobId={jobId} />}
    </div>
  )
}

export default function BuyListTab() {
  useHelpTab('buylists')
  const [listId, setListId] = useState(null)
  const q = useQuery({ queryKey: ['rpa-portal', 'buylists'], queryFn: () => rpaPortalApi.buylists().then(r => r.data) })
  const rows = useMemo(() => asList(q.data), [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { getValue: listValue, persistKey: 'portal-buylists' })
  return (
    <div className="space-y-4">
      <NewList onCreated={setListId} />
      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('id', 'number')} className="p-2 text-start">#</SortTh>
            <SortTh {...headerProps('created_at', 'date')} className="p-2 text-start">الوقت</SortTh>
            <SortTh {...headerProps('source_kind')} className="p-2 text-start">المصدر</SortTh>
            <SortTh {...headerProps('created_by_name')} className="p-2 text-start">بواسطة</SortTh>
            <SortTh {...headerProps('line_count', 'number')} className="p-2 text-end">الأسطر</SortTh>
            <SortTh {...headerProps('open_count', 'number')} className="p-2 text-end">لم تكتمل</SortTh>
            <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
          </tr></thead>
          <tbody>
            {sorted.map(r => (
              <tr key={r.id} onClick={() => setListId(r.id)}
                  className={`border-b border-line cursor-pointer hover:bg-surface-2 ${listId === r.id ? 'bg-surface-2' : ''}`}>
                <td className="p-2 tabular-nums">{r.id}</td>
                <td className="p-2 text-xs whitespace-nowrap">{fmtTime(r.created_at)}</td>
                <td className="p-2">{SOURCE[r.source_kind]} <span className="text-xs text-muted">{r.source_ref}</span></td>
                <td className="p-2">{r.created_by_name}</td>
                <td className="p-2 text-end tabular-nums">{r.line_count}</td>
                <td className="p-2 text-end tabular-nums">{r.open_count}</td>
                <td className="p-2"><Badge map={LIST_STATUS} value={r.status} /></td>
              </tr>
            ))}
            {q.isLoading && <tr><td colSpan={7} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={7} className="p-6 text-center text-red-600">تعذّر تحميل القوائم.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && (
              <tr><td colSpan={7} className="p-6 text-center text-muted">لا توجد قوائم بعد — أنشئ واحدة من الأعلى.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {listId && <ListDetail listId={listId} />}
    </div>
  )
}
