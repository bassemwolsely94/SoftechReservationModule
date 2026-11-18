/**
 * DiscoveryTab — الأكواد: items without a supplier code on the site, with the robot's candidates.
 * Keys (useGridKeyboard): ↑↓ move · Enter = confirm this candidate · M = none of these (the item's
 * line goes back to the buyer). The server checks the edit right, code conflicts and learning.
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaPortalApi } from '../../../api/client'
import useGridKeyboard from '../../../hooks/useGridKeyboard'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import { asList, errText } from './shared.jsx'

export default function DiscoveryTab() {
  useHelpTab('discovery')
  const qc = useQueryClient()
  const [jobId, setJobId] = useState('')
  const [err, setErr] = useState('')
  const jobsQ = useQuery({ queryKey: ['rpa-portal', 'jobs', 'approved'],
                           queryFn: () => rpaPortalApi.jobs({ status: 'approved' }).then(r => r.data) })
  const jobs = asList(jobsQ.data)
  const q = useQuery({ queryKey: ['rpa-portal', 'discovery', jobId], enabled: !!jobId,
                       queryFn: () => rpaPortalApi.discovery(jobId).then(r => r.data), refetchInterval: 20000 })
  const d = q.data
  // one row per candidate; an item with no candidate still gets a row (so M works on it)
  const rows = useMemo(() => asList(d?.lines).flatMap(ln => (ln.candidates?.length
    ? ln.candidates.map(c => ({ key: `c${c.availability_line_id}`, ...ln, cand: c }))
    : [{ key: `b${ln.buyline_id}`, ...ln, cand: null }])), [d])
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: 'portal-discovery',
    getValue: (r, k) => (k.startsWith('cand.') ? r.cand?.[k.slice(5)] : r[k]) })
  const after = () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa-portal'] }) }
  const confirm = useMutation({ mutationFn: id => rpaPortalApi.confirmCode(id), onSuccess: after, onError: e => setErr(errText(e)) })
  const none = useMutation({ mutationFn: id => rpaPortalApi.noneOfThese(id), onSuccess: after, onError: e => setErr(errText(e)) })
  const onConfirm = useCallback(r => { if (r.cand && !r.cand.code_conflict) confirm.mutate(r.cand.availability_line_id) }, [confirm])
  const onNone = useCallback(r => none.mutate(r.buyline_id), [none])
  const kb = useGridKeyboard({ rows: sorted, getKey: r => r.key, onConfirm, onOpen: onNone })

  return (
    <div className="space-y-3">
      <div className="card p-3 flex flex-wrap items-center gap-3 text-sm">
        <label htmlFor="pd-job">المهمة</label>
        <select id="pd-job" className="input-field text-sm" value={jobId} onChange={e => setJobId(e.target.value)}>
          <option value="">اختر مهمة معتمدة</option>
          {jobs.map(j => <option key={j.id} value={j.id}>#{j.id} · {j.portal_title} · {j.account_label}</option>)}
        </select>
        {d && <span className="text-muted">أصناف بلا كود: {d.missing_codes}</span>}
        {d?.reading && <span className="text-muted">الروبوت يبحث الآن…</span>}
        {d?.needs_person && (
          <span className="text-xs rounded px-1.5 py-0.5 bg-red-500/10 text-red-700 dark:text-red-300">
            تحتاج موظف — فشلت القراءة {d.failed_reads} مرات وتوقف الروبوت عن المحاولة
          </span>
        )}
        {err && <span className="text-xs text-red-600 ms-auto">{err}</span>}
      </div>
      <div data-tour="rpa-portals-discovery" className="card p-0 overflow-x-auto" {...kb.containerProps}>
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('seq', 'number')} className="p-2 text-start">#</SortTh>
            <SortTh {...headerProps('item_name')} className="p-2 text-start">الصنف عندنا</SortTh>
            <SortTh {...headerProps('cand.name')} className="p-2 text-start">المرشح في الموقع</SortTh>
            <SortTh {...headerProps('cand.sku')} className="p-2 text-start">كود المورد</SortTh>
            <SortTh {...headerProps('cand.price', 'number')} className="p-2 text-end">السعر</SortTh>
            <th className="p-2" />
          </tr></thead>
          <tbody>
            {sorted.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.key} {...rp} className={`border-b border-line ${rp.className}`}>
                  <td className="p-2 tabular-nums">{r.seq}</td>
                  <td className="p-2">{r.item_name} <span className="text-xs text-muted" dir="ltr">{r.item_code}</span></td>
                  <td className="p-2">{r.cand ? r.cand.name : <span className="text-muted">لا مرشحين</span>}</td>
                  <td className="p-2" dir="ltr">{r.cand?.sku || '—'}</td>
                  <td className="p-2 text-end tabular-nums">{r.cand?.price ?? '—'}</td>
                  <td className="p-2 whitespace-nowrap">
                    {r.cand?.out_of_stock && <span className="text-xs me-1 rounded px-1.5 py-0.5 bg-amber-500/10 text-amber-700 dark:text-amber-300">غير متاح</span>}
                    {r.cand?.code_conflict && <span className="text-xs me-1 rounded px-1.5 py-0.5 bg-amber-500/10 text-amber-700 dark:text-amber-300">كود مستخدم</span>}
                    {r.cand?.learn_failed && <span className="text-xs me-1 rounded px-1.5 py-0.5 bg-amber-500/10 text-amber-700 dark:text-amber-300">لم يُحفظ الكود</span>}
                    {r.cand && !r.cand.code_conflict && (
                      <button type="button" className="btn-primary text-xs" disabled={confirm.isPending}
                              onClick={() => confirm.mutate(r.cand.availability_line_id)}>هذا هو</button>
                    )}
                    <button type="button" className="btn-ghost text-xs ms-1" disabled={none.isPending}
                            onClick={() => none.mutate(r.buyline_id)}>لا شيء منها</button>
                  </td>
                </tr>
              )
            })}
            {!jobId && <tr><td colSpan={6} className="p-6 text-center text-muted">اختر مهمة لترى أصنافها بلا كود.</td></tr>}
            {jobId && q.isLoading && <tr><td colSpan={6} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {jobId && q.isError && <tr><td colSpan={6} className="p-6 text-center text-red-600">تعذّر التحميل.</td></tr>}
            {jobId && d && !rows.length && <tr><td colSpan={6} className="p-6 text-center text-muted">كل الأصناف لها كود.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-faint">⌨ ↑↓ تنقل · Enter تأكيد المرشح · M لا شيء منها · اضغط على عنوان العمود للترتيب</div>
    </div>
  )
}
