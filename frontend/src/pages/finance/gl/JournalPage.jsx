/**
 * JournalPage.jsx — «القيود»
 * Route: /finance/journal
 *
 * Review grid of ledger entries (drafts first): filters, multi-select with the review
 * keyboard (↑↓ Space Enter Ctrl+A), «اعتماد المحدد» → bulk approve with each refusal
 * shown on its row. A row opens EntryEditor in a side panel; «قيد جديد» opens a blank one.
 */
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useGridKeyboard from '../../../hooks/useGridKeyboard'
import SortTh from '../../../components/SortTh'
import BranchSelect from '../../../components/BranchSelect'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import EntryEditor from './EntryEditor'
import {
  BOOKS, STATUS, StatusPill, money, errOf, listOf, useGlBranches,
  inputCls, btnPrimary, btnPlain, ErrorBox,
} from './glUi'

const KEYS_HINT = '⌨ ↑↓ تنقل · مسافة تحديد · Enter فتح القيد · Ctrl+A تحديد الكل'

const totalOf = (e) => e.total_debit ?? e.total ?? e.amount ?? null

function getValue(row, key) {
  if (key === 'total') return totalOf(row)
  return row[key]
}

/** Bulk-approve reply → {id: {ok, number, detail}} whatever list/map shape the server uses. */
function resultsById(data) {
  const list = Array.isArray(data) ? data : Array.isArray(data?.results) ? data.results
    : Object.entries(data?.results || data || {}).map(([id, r]) => ({ id, ...(r || {}) }))
  return Object.fromEntries(list.map(r => [String(r.id), {
    ok: r.ok ?? (r.status === 'approved' || (!!r.number && !r.code)),
    number: r.number, detail: r.detail || r.error || '',
  }]))
}

export default function JournalPage() {
  const qc = useQueryClient()
  const perms = usePermissions('ledger')
  const { branches, labelOf } = useGlBranches()
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState({
    status: params.get('status') ?? 'draft', book: '', date_from: '', date_to: '', branch: '',
    account: params.get('account') || '', q: '',
  })
  const [selected, setSelected] = useState(() => new Set())
  const [rowResult, setRowResult] = useState({})
  const [err, setErr] = useState('')
  const [summary, setSummary] = useState('')
  const openId = params.get('entry')
  const [creating, setCreating] = useState(false)
  // the panel remounts only when the user opens another entry, not when a new draft gets its id
  const [editorKey, setEditorKey] = useState('')

  const setF = (patch) => { setFilters(f => ({ ...f, ...patch })); setSelected(new Set()); setRowResult({}) }
  const apiParams = useMemo(() => Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== '')), [filters])

  const listQ = useInfiniteQuery({
    queryKey: ['gl', 'entries', apiParams],
    queryFn: ({ pageParam }) => (pageParam ? glApi.entriesPage(pageParam) : glApi.entries(apiParams)).then(r => r.data),
    initialPageParam: null,
    getNextPageParam: (last) => (Array.isArray(last) ? undefined : last?.next || undefined),
  })
  const rows = useMemo(() => (listQ.data?.pages || []).flatMap(listOf), [listQ.data])
  const { sorted, headerProps } = useSortableRows(rows, { getValue, persistKey: 'gl-journal' })

  const setEntryParam = (id) => {
    const p = new URLSearchParams(params)
    if (id) p.set('entry', id); else p.delete('entry')
    setParams(p, { replace: true })
  }
  const open = (id) => { setCreating(false); setEditorKey(String(id)); setEntryParam(id) }
  const startNew = () => { setEditorKey(`new-${Date.now()}`); setCreating(true); setEntryParam(null) }
  const close = useCallback(() => {
    setCreating(false)
    const p = new URLSearchParams(params); p.delete('entry'); setParams(p, { replace: true })
  }, [params, setParams])

  const drafts = sorted.filter(r => r.status === 'draft')
  const toggle = (r) => {
    if (r.status !== 'draft') return
    setSelected(s => { const n = new Set(s); n.has(r.id) ? n.delete(r.id) : n.add(r.id); return n })
  }
  const selectAll = () => setSelected(s => (s.size === drafts.length ? new Set() : new Set(drafts.map(r => r.id))))
  const kb = useGridKeyboard({
    rows: sorted, getKey: r => r.id,
    onToggle: perms.approve ? toggle : undefined,
    onSelectAll: perms.approve ? selectAll : undefined,
    onConfirm: (r) => open(r.id),
  })

  const bulk = useMutation({
    mutationFn: (ids) => glApi.entriesApprove(ids).then(r => r.data),
    onSuccess: (data) => {
      const res = resultsById(data)
      setRowResult(res)
      const ok = Object.values(res).filter(r => r.ok).length
      const bad = Object.values(res).length - ok
      setSummary(`اعتُمد ${ok}${bad ? ` · رُفض ${bad} (السبب على كل سطر)` : ''}`)
      setSelected(new Set(Object.entries(res).filter(([, r]) => !r.ok).map(([id]) => Number(id) || id)))
      setErr('')
      qc.invalidateQueries({ queryKey: ['gl', 'entries'] })
    },
    onError: (e) => { setErr(errOf(e, 'تعذّر الاعتماد')); setSummary('') },
  })

  return (
    <div className="space-y-3" dir="rtl">
      {/* filters */}
      <div className="flex flex-wrap items-center gap-2" data-tour="finance-gl-journal-filters">
        <select className={inputCls} value={filters.status} onChange={e => setF({ status: e.target.value })}>
          {Object.entries(STATUS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
          <option value="">كل الحالات</option>
        </select>
        <select className={inputCls} value={filters.book} onChange={e => setF({ book: e.target.value })}>
          <option value="">كل الدفاتر</option>
          {Object.entries(BOOKS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="text-xs text-gray-500">من</label>
        <input type="date" className={inputCls} value={filters.date_from} onChange={e => setF({ date_from: e.target.value })} />
        <label className="text-xs text-gray-500">إلى</label>
        <input type="date" className={inputCls} value={filters.date_to} onChange={e => setF({ date_to: e.target.value })} />
        <BranchSelect size="sm" className="w-48" branches={branches} value={filters.branch} allLabel="كل الفروع"
                      onChange={v => setF({ branch: v })} />
        <input className={`${inputCls} w-28`} placeholder="كود الحساب" value={filters.account}
               onChange={e => setF({ account: e.target.value.trim() })} />
        <input className={`${inputCls} w-56`} placeholder="بحث في البيان / الرقم" value={filters.q}
               onChange={e => setF({ q: e.target.value })} />
        {perms.create && (
          <button type="button" className={`${btnPlain} ms-auto`} onClick={startNew}>+ قيد يدوي</button>
        )}
      </div>

      {perms.approve && (
        <div className="flex items-center gap-3" data-tour="finance-gl-journal-approve">
          <button type="button" className={btnPrimary} disabled={!selected.size || bulk.isPending}
                  onClick={() => bulk.mutate([...selected])}>
            {bulk.isPending ? 'جارٍ الاعتماد…' : `اعتماد المحدد${selected.size ? ` (${selected.size})` : ''}`}
          </button>
          {summary && <span className="text-sm text-gray-700">{summary}</span>}
        </div>
      )}
      <ErrorBox>{err || (listQ.isError ? errOf(listQ.error, 'تعذّر تحميل القيود') : '')}</ErrorBox>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" {...kb.containerProps}>
        {listQ.isLoading ? <SkeletonTable rows={8} cols={7} /> : !sorted.length ? (
          <EmptyState title="لا توجد قيود" sub={filters.status === 'draft' ? 'لا مسودات تنتظر المراجعة' : 'غيّر عوامل التصفية'} />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                {perms.approve && (
                  <th className="px-2 py-2 w-8">
                    <input type="checkbox" checked={!!drafts.length && selected.size === drafts.length}
                           onChange={selectAll} title="تحديد كل المسودات" />
                  </th>
                )}
                <SortTh {...headerProps('number')} className="text-right px-3 py-2">رقم القيد</SortTh>
                <SortTh {...headerProps('entry_date', 'date')} className="text-right px-3 py-2">التاريخ</SortTh>
                <SortTh {...headerProps('book')} className="text-right px-3 py-2">الدفتر</SortTh>
                <SortTh {...headerProps('branch_name')} className="text-right px-3 py-2">الفرع</SortTh>
                <SortTh {...headerProps('description')} className="text-right px-3 py-2">البيان</SortTh>
                <SortTh {...headerProps('total', 'number')} className="text-left px-3 py-2">المبلغ</SortTh>
                <SortTh {...headerProps('status')} className="text-right px-3 py-2">الحالة</SortTh>
                <SortTh {...headerProps('created_by_name')} className="text-right px-3 py-2">أنشأه</SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => {
                const res = rowResult[String(r.id)]
                const kbp = kb.rowProps(r)
                return (
                  <tr key={r.id} {...kbp}
                      className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${selected.has(r.id) ? 'bg-green-50/60' : ''} ${String(openId) === String(r.id) ? 'bg-blue-50/60' : ''} ${kbp.className}`}
                      onClick={() => open(r.id)}>
                    {perms.approve && (
                      <td className="px-2 py-1.5" onClick={e => e.stopPropagation()}>
                        {r.status === 'draft' && <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r)} />}
                      </td>
                    )}
                    <td className="px-3 py-1.5 font-mono">{r.number || <span className="text-gray-400">مسودة #{r.id}</span>}</td>
                    <td className="px-3 py-1.5">{r.entry_date}</td>
                    <td className="px-3 py-1.5">{BOOKS[r.book] || r.book}</td>
                    <td className="px-3 py-1.5">{labelOf(r.branch_id ?? r.branch, r.branch_name) || '—'}</td>
                    <td className="px-3 py-1.5">
                      {r.description}
                      {res && !res.ok && <div className="text-xs text-red-600">{res.detail || 'رُفض'}</div>}
                      {res?.ok && <div className="text-xs text-green-700">اعتُمد {res.number || ''}</div>}
                    </td>
                    <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{totalOf(r) === null ? '—' : money(totalOf(r))}</td>
                    <td className="px-3 py-1.5"><StatusPill status={r.status} /></td>
                    <td className="px-3 py-1.5 text-xs text-gray-500">{r.created_by_name || ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span>{KEYS_HINT}</span>
        {listQ.hasNextPage && (
          <button type="button" className={`${btnPlain} ms-auto`} disabled={listQ.isFetchingNextPage} onClick={() => listQ.fetchNextPage()}>
            {listQ.isFetchingNextPage ? 'جارٍ التحميل…' : 'تحميل المزيد'}
          </button>
        )}
      </div>

      {(openId || creating) && (
        <EntryEditor key={editorKey || openId} entryId={openId} onClose={close}
                     onChanged={(d) => { if (d?.id && creating) { setCreating(false); setEntryParam(d.id) } }} />
      )}
    </div>
  )
}
