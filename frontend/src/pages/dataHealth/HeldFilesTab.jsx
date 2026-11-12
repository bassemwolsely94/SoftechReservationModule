/**
 * Held files tab (الملفات المحجوزة) of /data-health — admin only (the server refuses everyone else).
 * Files the rules moved out of the media folder wait here before the final purge. A row never carries a
 * path or a hash. A thumbnail shows only when the server says `has_thumbnail` (item images only; never a
 * prescription). Restore asks for an inline confirmation, not a modal.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dataHealthApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { TD, TH, errText, fmtBytes, fmtDate } from './format'

function Thumbnail({ id }) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    let objectUrl = null
    let alive = true
    dataHealthApi.thumbnail(id)
      .then(({ data }) => {
        if (!alive) return
        objectUrl = URL.createObjectURL(data)
        setUrl(objectUrl)
      })
      .catch(() => {})
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [id])
  if (!url) return <div className="w-12 h-12 rounded bg-gray-100" />
  return <img src={url} alt="" className="w-12 h-12 rounded object-cover border border-gray-200" />
}

function stateOf(r) {
  if (r.purged_at) return { label: 'حُذف نهائيًا', cls: 'text-gray-500' }
  if (r.restored_at) return { label: 'مسترجع', cls: 'text-emerald-700' }
  return { label: 'محجوز', cls: 'text-gray-800' }
}

const heldValue = (r, key) => (key === 'state' ? stateOf(r).label : r[key])

function RestoreCell({ row }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const restore = useMutation({
    mutationFn: () => dataHealthApi.restore(row.id),
    onSuccess: () => { setConfirming(false); qc.invalidateQueries({ queryKey: ['data-health'] }) },
  })
  if (!row.can_restore) return <span className="text-xs text-gray-400">—</span>
  if (!confirming) {
    return (
      <button type="button" className="btn-secondary !text-xs !px-2 !py-1" data-tour="data-health-main-restore"
              onClick={() => setConfirming(true)}>
        استرجاع
      </button>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-xs text-gray-600">يرجع الملف لمكانه؟</span>
      <button type="button" className="btn-primary !text-xs !px-2 !py-1" disabled={restore.isPending}
              onClick={() => restore.mutate()}>
        {restore.isPending ? '…' : 'نعم، استرجع'}
      </button>
      <button type="button" className="btn-ghost !text-xs !px-2 !py-1" disabled={restore.isPending}
              onClick={() => { setConfirming(false); restore.reset() }}>
        إلغاء
      </button>
      {restore.isError && <span className="text-xs text-red-600 w-full">{errText(restore.error)}</span>}
    </div>
  )
}

export default function HeldFilesTab() {
  const [state, setState] = useState('held')
  const q = useQuery({
    queryKey: ['data-health', 'held', state],
    queryFn: () => dataHealthApi.held(state).then(r => r.data),
  })
  const rows = q.data?.rows || []
  const { sorted, headerProps: h } = useSortableRows(rows, { getValue: heldValue, persistKey: 'data-health-held' })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {[['held', 'المحجوزة الآن'], ['all', 'الكل (مع المسترجع والمحذوف)']].map(([k, label]) => (
            <button key={k} type="button" onClick={() => setState(k)}
                    className={`px-3 py-1 rounded-md text-xs ${state === k ? 'bg-white shadow text-brand-700 font-semibold' : 'text-gray-600'}`}>
              {label}
            </button>
          ))}
        </div>
        {q.data && (
          <span className="text-xs text-gray-500">
            {q.data.total > rows.length ? `يظهر أحدث ${rows.length} من ${q.data.total}` : `${q.data.total} ملف`}
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500">الصور المصغّرة لصور الأصناف فقط؛ لا تظهر أبدًا لصور الروشتات أو المحادثات.</p>

      {q.isLoading && <p className="text-sm text-gray-500">جارٍ التحميل…</p>}
      {q.isError && <p className="text-sm text-red-600">{errText(q.error)}</p>}
      {q.data && !rows.length && <p className="card p-3 text-sm text-gray-500">لا توجد ملفات محجوزة.</p>}
      {rows.length > 0 && (
        <div className="card p-0 overflow-x-auto" data-tour="data-health-main-held">
          <table className="w-full">
            <thead className="bg-gray-50"><tr>
              <th className={TH}><span className="sr-only">صورة</span></th>
              <SortTh {...h('rule_label_ar', 'text')} className={TH}>القاعدة</SortTh>
              <SortTh {...h('record_type_ar', 'text')} className={TH}>السجل</SortTh>
              <SortTh {...h('size', 'number')} className={TH}>الحجم</SortTh>
              <SortTh {...h('moved_at', 'date')} className={TH}>تاريخ الحجز</SortTh>
              <SortTh {...h('purge_after', 'date')} className={TH}>يُحذف نهائيًا بعد</SortTh>
              <SortTh {...h('deleted_by', 'text')} className={TH}>حذفه</SortTh>
              <SortTh {...h('state', 'text')} className={TH}>الحالة</SortTh>
              <th className={TH}><span className="sr-only">إجراء</span></th>
            </tr></thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map(r => {
                const st = stateOf(r)
                return (
                  <tr key={r.id}>
                    <td className={TD}>{r.has_thumbnail ? <Thumbnail id={r.id} /> : null}</td>
                    <td className={TD}>{r.rule_label_ar}</td>
                    <td className={TD}>{r.record_type_ar || '—'}{r.record_id ? <span className="text-xs text-gray-400 ms-1">#{r.record_id}</span> : null}</td>
                    <td className={`${TD} tabular-nums`} dir="ltr">{fmtBytes(r.size)}</td>
                    <td className={TD}>{fmtDate(r.moved_at)}</td>
                    <td className={TD}>{fmtDate(r.purge_after)}</td>
                    <td className={TD}>{r.deleted_by || <span className="text-gray-400">القاعدة</span>}</td>
                    <td className={`${TD} ${st.cls}`}>{st.label}</td>
                    <td className={TD}><RestoreCell row={r} /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
