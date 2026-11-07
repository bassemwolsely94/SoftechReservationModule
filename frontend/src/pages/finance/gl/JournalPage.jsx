/**
 * JournalPage.jsx — «القيود»
 * Route: /finance/journal
 *
 * Review grid of ledger entries (drafts first): filters, multi-select with the review
 * keyboard (↑↓ Space Enter Ctrl+A), «اعتماد المحدد» → bulk approve with each refusal
 * shown on its row. A row opens EntryEditor in a side panel; «قيد جديد» opens a blank one.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useGridKeyboard from '../../../hooks/useGridKeyboard'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import DataFreshnessBar from '../../../components/DataFreshnessBar'
import ProgressBar from '../../../components/ProgressBar'
import BranchSelect from '../../../components/BranchSelect'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import EntryEditor from './EntryEditor'
import ExceptionsTab from './ExceptionsTab'
import { SOURCE_TYPES } from './RuleEditor'
import {
  BOOKS, STATUS, StatusPill, money, errOf, listOf, todayIso, useGlBranches,
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

const monthStartIso = () => `${todayIso().slice(0, 8)}01`

/** Progress of a drafting run (draft-now / redraft): polls the run until it leaves 'running'. */
function RunProgress({ runId, onFinished }) {
  const runQ = useQuery({
    queryKey: ['gl', 'draft-run', runId],
    queryFn: () => glApi.draftRun1(runId).then(r => r.data),
    enabled: !!runId,
    refetchInterval: (q) => (q.state.status === 'error' || (q.state.data && q.state.data.status !== 'running') ? false : 2000),
  })
  const run = runQ.data
  const finished = !!run && run.status !== 'running'
  const started = useRef(Date.now())
  useEffect(() => { if (finished) onFinished?.(run) }, [finished]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!runId) return null
  if (runQ.isError) return <div className="text-sm rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2">تعذّر قراءة حالة الترحيل — حدّث الصفحة</div>
  const c = run?.counts || {}
  const msg = run ? `قُرئ ${c.read ?? 0} · جديد ${c.new ?? 0} · مسودات ${c.drafted ?? 0} · استثناءات ${c.exceptions ?? 0}` : 'جاري البدء…'
  if (!finished) return <ProgressBar label="ترحيل القيود من SOFTECH" message={msg} since={started.current} />
  const ok = run.status === 'success'
  return (
    <div className={`text-sm rounded-lg border px-3 py-2 ${ok ? 'bg-green-50 border-green-200 text-green-800' : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
      {ok ? 'اكتمل الترحيل' : run.status === 'partial' ? 'اكتمل جزئياً' : 'فشل الترحيل'} — {msg}
      {run.detail?.error && <span> · {String(run.detail.error)}</span>}
      {!!run.detail?.vat_missing && <span> · {run.detail.vat_missing} فاتورة بضريبة ناقصة</span>}
      {!!run.detail?.reader_errors && <span> · تعذّرت قراءة: {Object.keys(run.detail.reader_errors).map(k => SOURCE_TYPES[k] || k).join('، ')}</span>}
    </div>
  )
}

export default function JournalPage() {
  const qc = useQueryClient()
  const perms = usePermissions('ledger')
  const { branches, labelOf } = useGlBranches()
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState({
    status: params.get('status') ?? 'draft', book: '', date_from: '', date_to: '', branch: '',
    account: params.get('account') || '', q: '', source: '',
  })
  const tab = params.get('tab') === 'exceptions' ? 'exceptions' : 'entries'   // follows the URL
  const setTab = (t) => { const p = new URLSearchParams(params); if (t === 'exceptions') p.set('tab', t); else p.delete('tab'); setParams(p, { replace: true }) }
  useHelpTab(tab)
  const [runId, setRunId] = useState(null)
  const [runNote, setRunNote] = useState('')
  const [range, setRange] = useState({ from: monthStartIso(), to: todayIso() })
  const [selected, setSelected] = useState(() => new Set())
  const [rowResult, setRowResult] = useState({})
  const [err, setErr] = useState('')
  const [summary, setSummary] = useState('')
  const openId = params.get('entry')
  const [creating, setCreating] = useState(false)
  // the panel remounts only when the user opens another entry, not when a new draft gets its id
  const [editorKey, setEditorKey] = useState('')

  const setF = (patch) => { setFilters(f => ({ ...f, ...patch })); setSelected(new Set()); setRowResult({}) }
  const apiParams = useMemo(() => {
    const { source, ...rest } = filters
    return Object.fromEntries(Object.entries({ ...rest, source_type: source }).filter(([, v]) => v !== ''))
  }, [filters])
  const excFilters = useMemo(() => ({
    source_type: filters.source && filters.source !== 'manual' ? filters.source : '',
    date_from: filters.date_from, date_to: filters.date_to, branch: filters.branch,
  }), [filters.source, filters.date_from, filters.date_to, filters.branch])

  const listQ = useInfiniteQuery({
    queryKey: ['gl', 'entries', apiParams],
    queryFn: ({ pageParam }) => (pageParam ? glApi.entriesPage(pageParam) : glApi.entries(apiParams)).then(r => r.data),
    initialPageParam: null,
    getNextPageParam: (last) => (Array.isArray(last) ? undefined : last?.next || undefined),
  })
  const rows = useMemo(() => (listQ.data?.pages || []).flatMap(listOf), [listQ.data])
  // own key (same 'gl','exceptions' prefix, so invalidations still reach it) - never the list's key
  const badgeQ = useQuery({
    queryKey: ['gl', 'exceptions', 'counts', 'all'],
    queryFn: () => glApi.exceptionsCounts({}).then(r => r.data),
    refetchInterval: 60000,
  })
  const openExceptions = badgeQ.data?.total ?? 0
  // drop selections that are no longer in the loaded drafts (filter change, reload, approval)
  useEffect(() => {
    setSelected(s => {
      const live = new Set(rows.filter(r => r.status === 'draft').map(r => r.id))
      const n = new Set([...s].filter(id => live.has(id)))
      return n.size === s.size ? s : n
    })
  }, [rows])
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

  const draftNow = useMutation({
    mutationFn: () => glApi.draftRun({ date_from: range.from, date_to: range.to, source_types: [] }).then(r => r.data),
    onSuccess: (d) => { setRunNote(''); setRunId(d.run_id) },
    onError: async (e) => {
      if (e?.response?.status === 409) {
        setRunNote('يعمل بالفعل — هناك ترحيل جارٍ الآن')
        try {
          const r = await glApi.draftRuns({ limit: 3 })
          const run = listOf(r.data).find(x => x.status === 'running')
          if (run) setRunId(run.id)
        } catch { /* the note stays */ }
      } else setRunNote(errOf(e, 'تعذّر بدء الترحيل'))
    },
  })
  const runFinished = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['gl', 'entries'] })
    qc.invalidateQueries({ queryKey: ['gl', 'exceptions'] })
    qc.invalidateQueries({ queryKey: ['data-freshness'] })
  }, [qc])
  const draftNowFn = async () => { await draftNow.mutateAsync().catch(() => {}) }
  const tabBtn = (k) => `px-4 py-1.5 ${tab === k ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`

  return (
    <div className="space-y-3" dir="rtl">
      <div data-tour="finance-gl-journal-freshness">
        <DataFreshnessBar domains={['gl_drafting', 'ap_reconciliation']} canEdit={!!perms.create} onRefresh={draftNowFn} />
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
          <span>«تحديث الآن» يرحّل مستندات SOFTECH كمسودات من</span>
          <input type="date" className={inputCls} value={range.from} onChange={e => setRange(r => ({ ...r, from: e.target.value }))} />
          <span>إلى</span>
          <input type="date" className={inputCls} value={range.to} onChange={e => setRange(r => ({ ...r, to: e.target.value }))} />
          {runNote && <span className="text-amber-700 font-medium">{runNote}</span>}
        </div>
        <RunProgress runId={runId} onFinished={runFinished} />
      </div>

      <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm w-fit">
        <button type="button" onClick={() => setTab('entries')} className={tabBtn('entries')}>المسودات والقيود</button>
        <button type="button" onClick={() => setTab('exceptions')} className={tabBtn('exceptions')}>
          الاستثناءات{openExceptions > 0 && <span className="ms-1.5 rounded-full bg-amber-500 text-white text-[11px] px-1.5">{openExceptions}</span>}
        </button>
      </div>

      {/* filters */}
      <div className="flex flex-wrap items-center gap-2" data-tour="finance-gl-journal-filters">
        {tab === 'entries' && (<>
        <select className={inputCls} value={filters.status} onChange={e => setF({ status: e.target.value })}>
          {Object.entries(STATUS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
          <option value="">كل الحالات</option>
        </select>
        <select className={inputCls} value={filters.book} onChange={e => setF({ book: e.target.value })}>
          <option value="">كل الدفاتر</option>
          {Object.entries(BOOKS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        </>)}
        <label className="text-xs text-gray-500">من</label>
        <input type="date" className={inputCls} value={filters.date_from} onChange={e => setF({ date_from: e.target.value })} />
        <label className="text-xs text-gray-500">إلى</label>
        <input type="date" className={inputCls} value={filters.date_to} onChange={e => setF({ date_to: e.target.value })} />
        <BranchSelect size="sm" className="w-48" branches={branches} value={filters.branch} allLabel="كل الفروع" placeholder="كل الفروع"
                      onChange={v => setF({ branch: v })} />
        <select className={inputCls} value={filters.source} onChange={e => setF({ source: e.target.value })} title="مصدر القيد">
          <option value="">كل المصادر</option>
          {Object.entries(SOURCE_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          <option value="manual">يدوي</option>
        </select>
        {tab === 'entries' && (<>
        <input className={`${inputCls} w-28`} placeholder="كود الحساب" value={filters.account}
               onChange={e => setF({ account: e.target.value.trim() })} />
        <input className={`${inputCls} w-56`} placeholder="بحث في البيان / الرقم" value={filters.q}
               onChange={e => setF({ q: e.target.value })} />
        {perms.create && (
          <button type="button" className={`${btnPlain} ms-auto`} onClick={startNew}>+ قيد يدوي</button>
        )}
        </>)}
      </div>

      {tab === 'exceptions' ? (
        <ExceptionsTab filters={excFilters} perms={perms} onRunStarted={(id) => { setRunNote(''); setRunId(id) }}
                       onBusy={() => setRunNote('يعمل بالفعل — هناك ترحيل جارٍ الآن')} />
      ) : (
        <>
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
        {listQ.isLoading ? <SkeletonTable rows={8} cols={7} /> : listQ.isError ? null : !sorted.length ? (
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

        </>
      )}

      {(openId || creating) && (
        <EntryEditor key={editorKey || openId} entryId={openId} onClose={close}
                     onChanged={(d) => { if (d?.id && creating) { setCreating(false); setEntryParam(d.id) } }} />
      )}
    </div>
  )
}
