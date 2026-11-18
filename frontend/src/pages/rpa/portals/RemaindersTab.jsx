/**
 * RemaindersTab — الباقي: lines of open buy lists a supplier was tried for and did not fully give.
 * Keys (useGridKeyboard): ↑↓ move · Enter = pick the next suggested supplier not tried yet.
 * The pick is the same server call as on the buy list (locked lines are refused there).
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaPortalApi } from '../../../api/client'
import useGridKeyboard from '../../../hooks/useGridKeyboard'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import { asList, errText, supplierText } from './shared.jsx'

// the server names the next supplier to try (best-ranked, not tried yet)
const nextSupplier = r => r.next_supplier || ''

export default function RemaindersTab() {
  useHelpTab('remainders')
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const q = useQuery({ queryKey: ['rpa-portal', 'remainders'], queryFn: () => rpaPortalApi.remainders().then(r => r.data) })
  const rows = useMemo(() => asList(q.data?.rows), [q.data])
  const suppliers = q.data?.suppliers || {}
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: 'portal-remainders',
    getValue: (r, k) => (k === 'next' ? nextSupplier(r) : r[k]) })
  const pick = useMutation({
    mutationFn: ({ r, supplier }) => rpaPortalApi.pick(r.buylist_id, r.id, supplier),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa-portal'] }) },
    onError: e => setErr(errText(e)),
  })
  const onConfirm = useCallback(r => { const s = nextSupplier(r); if (s) pick.mutate({ r, supplier: s }) }, [pick])
  const kb = useGridKeyboard({ rows: sorted, getKey: r => r.id, onConfirm })

  return (
    <div className="space-y-2">
      {err && <div className="text-sm text-red-600">{err}</div>}
      <div data-tour="rpa-portals-remainders" className="card p-0 overflow-x-auto" {...kb.containerProps}>
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('buylist_id', 'number')} className="p-2 text-start">القائمة</SortTh>
            <SortTh {...headerProps('item_name')} className="p-2 text-start">الصنف</SortTh>
            <SortTh {...headerProps('needed_qty', 'number')} className="p-2 text-end">المطلوب</SortTh>
            <SortTh {...headerProps('remaining_qty', 'number')} className="p-2 text-end">الباقي</SortTh>
            <th className="p-2 text-start">جُرِّب</th>
            <SortTh {...headerProps('next')} className="p-2 text-start">المورد التالي</SortTh>
          </tr></thead>
          <tbody>
            {sorted.map(r => {
              const rp = kb.rowProps(r)
              const nxt = nextSupplier(r)
              return (
                <tr key={r.id} {...rp} className={`border-b border-line ${rp.className}`}>
                  <td className="p-2 tabular-nums">#{r.buylist_id} · {r.seq}</td>
                  <td className="p-2">{r.item_name} <span className="text-xs text-muted" dir="ltr">{r.item_code}</span></td>
                  <td className="p-2 text-end tabular-nums">{r.needed_qty}</td>
                  <td className="p-2 text-end tabular-nums">{r.remaining_qty}</td>
                  <td className="p-2 text-xs text-muted">
                    {(r.tried || []).map((t, i) => <div key={i}>{supplierText(suppliers, t.supplier)}: {t.accepted}</div>)}
                  </td>
                  <td className="p-2">
                    {nxt ? (
                      <button type="button" className="btn-secondary text-xs" disabled={pick.isPending}
                              onClick={() => pick.mutate({ r, supplier: nxt })}>{supplierText(suppliers, nxt)}</button>
                    ) : <span className="text-xs text-muted">اختره من القائمة</span>}
                    {r.chosen_supplier && <span className="text-xs text-muted ms-1">(المختار: {supplierText(suppliers, r.chosen_supplier)})</span>}
                  </td>
                </tr>
              )
            })}
            {q.isLoading && <tr><td colSpan={6} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={6} className="p-6 text-center text-red-600">تعذّر تحميل الباقي.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && <tr><td colSpan={6} className="p-6 text-center text-muted">لا يوجد باقٍ.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-faint">⌨ ↑↓ تنقل · Enter اختيار المورد التالي · اضغط على عنوان العمود للترتيب</div>
    </div>
  )
}
