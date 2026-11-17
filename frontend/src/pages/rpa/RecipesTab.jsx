/**
 * RecipesTab — الوصفات (admin only): the recorded SOFTECH screen recipes. A draft recipe is
 * uploaded from a .dld recording with its field map, and a SECOND admin approves it (four-eyes,
 * enforced by the server). Approved content is frozen; this screen never edits it.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { Badge, RECIPE_STATUS, SCREEN_LABEL, asList, errText, fmtTime } from './shared.jsx'

const recValue = (r, k) => (k === 'status' ? (RECIPE_STATUS[r.status]?.label || r.status) : r[k])

export default function RecipesTab() {
  const qc = useQueryClient()
  const [file, setFile] = useState(null)
  const [fieldMap, setFieldMap] = useState('')
  const [err, setErr] = useState('')
  const q = useQuery({ queryKey: ['rpa', 'recipes'], queryFn: () => rpaApi.recipes().then(r => r.data) })
  const rows = useMemo(() => asList(q.data), [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { getValue: recValue, persistKey: 'rpa-recipes' })
  const refresh = () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa'] }) }

  const create = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('screen', 'issue_125')
      fd.append('file', file)
      fd.append('field_map', fieldMap.trim())
      return rpaApi.createRecipe(fd)
    },
    onSuccess: () => { setFile(null); setFieldMap(''); refresh() },
    onError: e => setErr(errText(e)),
  })
  const approve = useMutation({ mutationFn: id => rpaApi.approveRecipe(id), onSuccess: refresh, onError: e => setErr(errText(e)) })

  return (
    <div className="space-y-4">
      <div className="card p-4 space-y-3 max-w-2xl">
        <h2 className="font-bold text-sm">رفع وصفة جديدة ({SCREEN_LABEL.issue_125})</h2>
        <div>
          <label className="label" htmlFor="rpa-dld">ملف التسجيل (.dld)</label>
          <input id="rpa-dld" type="file" accept=".dld" className="block text-sm" onChange={e => setFile(e.target.files?.[0] || null)} />
        </div>
        <div>
          <label className="label" htmlFor="rpa-fieldmap">خريطة الحقول (JSON)</label>
          <textarea id="rpa-fieldmap" className="input-field w-full font-mono text-xs" dir="ltr" rows={4}
                    value={fieldMap} onChange={e => setFieldMap(e.target.value)} />
        </div>
        <button type="button" className="btn-primary text-sm" disabled={!file || !fieldMap.trim() || create.isPending}
                onClick={() => create.mutate()}>
          {create.isPending ? 'جارٍ الرفع…' : 'رفع كمسودة'}
        </button>
        {err && <div className="text-sm text-red-600">{err}</div>}
      </div>

      <div data-tour="rpa-main-recipes" className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <SortTh {...headerProps('screen_title')} className="p-2 text-start">الشاشة</SortTh>
              <SortTh {...headerProps('version', 'number')} className="p-2 text-start">الإصدار</SortTh>
              <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
              <SortTh {...headerProps('source_filename')} className="p-2 text-start">الملف</SortTh>
              <SortTh {...headerProps('created_by_name')} className="p-2 text-start">رفعها</SortTh>
              <SortTh {...headerProps('approved_by_name')} className="p-2 text-start">اعتمدها</SortTh>
              <SortTh {...headerProps('approved_at', 'date')} className="p-2 text-start">وقت الاعتماد</SortTh>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => (
              <tr key={r.id} className="border-b border-line">
                <td className="p-2">{r.screen_title || SCREEN_LABEL[r.screen_key || r.screen] || '—'}</td>
                <td className="p-2 tabular-nums">v{r.version}</td>
                <td className="p-2"><Badge map={RECIPE_STATUS} value={r.status} /></td>
                <td className="p-2 text-muted" dir="ltr">{r.source_filename || '—'}</td>
                <td className="p-2">{r.created_by_name || '—'}</td>
                <td className="p-2">{r.approved_by_name || '—'}</td>
                <td className="p-2 text-xs whitespace-nowrap">{fmtTime(r.approved_at)}</td>
                <td className="p-2 text-end">
                  {r.status === 'draft' && (
                    <button type="button" className="btn-secondary text-sm" disabled={approve.isPending} onClick={() => approve.mutate(r.id)}>
                      اعتماد الوصفة
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {q.isLoading && <tr><td colSpan={8} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={8} className="p-6 text-center text-red-600">تعذّر تحميل الوصفات.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && <tr><td colSpan={8} className="p-6 text-center text-muted">لا توجد وصفات.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
