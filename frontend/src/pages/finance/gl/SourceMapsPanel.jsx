/**
 * SourceMapsPanel.jsx — «الربط»: SOFTECH value → finance account (+ branch) for the posting rules.
 *
 * Kinds: bank (خزينة/بنك by bank code), expense (by expense code), card_clearing (by branch code).
 * Values the drafting engine could not map (open «unmapped_account» exceptions) appear highlighted
 * with an empty account, so a person only picks the account and saves. Edits need ledger.edit; the
 * server audits before/after and never deletes a map.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import useSortableRows from '../../../hooks/useSortableRows'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import { AccountPicker } from './EntryEditor'
import { MAP_KINDS } from './RuleEditor'
import { errOf, listOf, useGlBranches, inputCls, btnPrimary, ErrorBox } from './glUi'

function MapRow({ row, accounts, nameOf, branches, canEdit, kind, onSaved }) {
  const [account, setAccount] = useState(row.account_code || '')
  const [branch, setBranch] = useState(row.branch_id ? String(row.branch_id) : '')
  const [note, setNote] = useState(row.note || '')
  const [err, setErr] = useState('')
  const dirty = account !== (row.account_code || '') || branch !== (row.branch_id ? String(row.branch_id) : '') || note !== (row.note || '')
  const save = useMutation({
    mutationFn: () => glApi.mapPut(kind, row.source_value, {
      account_code: account, branch_id: branch ? Number(branch) : null, note,
    }).then(r => r.data),
    onSuccess: () => { setErr(''); onSaved() },
    onError: (e) => setErr(errOf(e, 'تعذّر الحفظ')),
  })
  return (
    <tr className={`border-t border-gray-100 ${row.unmapped ? 'bg-amber-50' : ''}`}>
      <td className="px-3 py-1.5 font-mono">
        {row.source_value}
        {row.unmapped && <span className="ms-2 text-[10px] text-amber-700">غير مربوط</span>}
      </td>
      <td className="px-3 py-1.5 w-80">
        <AccountPicker value={account} name={nameOf[String(account)] || row.account_name || ''} accounts={accounts}
                       disabled={!canEdit} onPick={a => setAccount(a.code)} />
      </td>
      <td className="px-3 py-1.5">
        <select className={inputCls} value={branch} disabled={!canEdit} onChange={e => setBranch(e.target.value)}>
          <option value="">{kind === 'card_clearing' ? '— اختر فرعاً —' : 'بدون فرع'}</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
      </td>
      <td className="px-3 py-1.5">
        <input className={`${inputCls} w-40`} value={note} disabled={!canEdit} onChange={e => setNote(e.target.value)} />
      </td>
      <td className="px-3 py-1.5 whitespace-nowrap">
        {canEdit && (
          <button type="button" className={btnPrimary} disabled={!account || !(dirty || row.unmapped) || save.isPending}
                  onClick={() => save.mutate()}>حفظ</button>
        )}
        {err && <div className="text-xs text-red-600 mt-1 max-w-56">{err}</div>}
      </td>
    </tr>
  )
}

export default function SourceMapsPanel({ canEdit }) {
  const qc = useQueryClient()
  const { branches, labelOf } = useGlBranches()
  const [kind, setKind] = useState('bank')
  const [newValue, setNewValue] = useState('')
  const [extra, setExtra] = useState([])

  const mapsQ = useQuery({ queryKey: ['gl', 'maps', kind], queryFn: () => glApi.maps({ kind }).then(r => listOf(r.data)) })
  const exQ = useQuery({
    queryKey: ['gl', 'exceptions', 'unmapped-values'],
    queryFn: () => glApi.unmappedValues({ kind: 'unmapped_account' }).then(r => listOf(r.data)),
  })
  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', 'posting'],
    queryFn: () => glApi.accounts({ active: 'true', page_size: 2000 }).then(r => listOf(r.data)),
    staleTime: 5 * 60 * 1000,
  })
  const accounts = useMemo(() => (accountsQ.data || []).filter(a => a.is_posting !== false), [accountsQ.data])
  const nameOf = useMemo(() => Object.fromEntries(accounts.map(a => [String(a.code), a.name])), [accounts])
  const branchOpts = useMemo(() => branches.map(b => ({ id: b.id, label: labelOf(b.id) })), [branches]) // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    const have = new Map((mapsQ.data || []).map(m => [String(m.source_value), { ...m, account_code: m.account_code, unmapped: false }]))
    // values the engine reported as unmapped for this kind and that have no row yet
    const missing = new Set()
    ;(exQ.data || []).forEach(e => {
      if (e.kind === kind && !have.has(String(e.value))) missing.add(String(e.value))
    })
    extra.forEach(v => { if (!have.has(v)) missing.add(v) })
    const out = [...have.values()]
    missing.forEach(v => out.push({ id: `new-${v}`, source_value: v, account_code: '', account_name: '', branch_id: null, note: '', unmapped: true }))
    return out
  }, [mapsQ.data, exQ.data, extra, kind])
  const { sorted, headerProps } = useSortableRows(rows, {
    persistKey: 'gl-maps', defaultSort: { key: 'source_value', dir: 'asc', type: 'text' },
  })
  const unmappedCount = rows.filter(r => r.unmapped).length
  const done = () => { qc.invalidateQueries({ queryKey: ['gl', 'maps'] }); qc.invalidateQueries({ queryKey: ['gl', 'exceptions'] }); setExtra([]) }

  return (
    <div className="space-y-3" dir="rtl">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm">
          {Object.entries(MAP_KINDS).map(([k, l]) => (
            <button key={k} type="button" onClick={() => setKind(k)}
                    className={`px-3 py-1.5 ${kind === k ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{l}</button>
          ))}
        </div>
        {unmappedCount > 0 && <span className="text-xs text-amber-700">{unmappedCount} قيمة غير مربوطة</span>}
        {canEdit && (
          <form className="flex items-center gap-1 ms-auto" onSubmit={e => { e.preventDefault(); const v = newValue.trim(); if (v) { setExtra(x => [...x, v]); setNewValue('') } }}>
            <input className={`${inputCls} w-40`} placeholder="قيمة جديدة من SOFTECH" value={newValue} onChange={e => setNewValue(e.target.value)} />
            <button type="submit" className="text-xs text-green-700 hover:underline">+ إضافة</button>
          </form>
        )}
      </div>
      <ErrorBox>{mapsQ.isError ? errOf(mapsQ.error, 'تعذّر تحميل الربط') : ''}</ErrorBox>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="finance-gl-maps-grid">
        {mapsQ.isLoading ? <SkeletonTable rows={6} cols={5} /> : !sorted.length ? (
          <EmptyState title="لا توجد روابط" sub="أضف قيمة من SOFTECH أو شغّل الترحيل ليظهر ما ينقصه ربط" />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('source_value', 'text')} className="text-right px-3 py-2">
                  {kind === 'bank' ? 'كود الخزينة/البنك' : kind === 'expense' ? 'كود المصروف' : 'كود الفرع'}
                </SortTh>
                <SortTh {...headerProps('account_code', 'text')} className="text-right px-3 py-2">الحساب</SortTh>
                <SortTh {...headerProps('branch_id', 'number')} className="text-right px-3 py-2">الفرع</SortTh>
                <SortTh {...headerProps('note')} className="text-right px-3 py-2">ملاحظة</SortTh>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => (
                <MapRow key={`${kind}:${r.source_value}:${r.account_code}:${r.branch_id}`} row={r} kind={kind} accounts={accounts} nameOf={nameOf}
                        branches={branchOpts} canEdit={canEdit} onSaved={done} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
