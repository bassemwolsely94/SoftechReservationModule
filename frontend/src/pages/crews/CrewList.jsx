/**
 * Crews tab (الأطقم), left side: the crew list and the inline «+ طاقم جديد» form (edit only).
 * «إظهار المؤرشفة» swaps the list for the archived crews (the server returns one or the other).
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { crewsApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { BTN, BTN_PRIMARY, INPUT, TD, TH, errText, fmtDate, fmtInt } from './util'

export const CREW_TYPES = [
  { value: 'call_center', label: 'كول سنتر' },
  { value: 'job', label: 'وظيفي' },
  { value: 'custom', label: 'مخصص' },
]

function NewCrewForm({ onCreated }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [type, setType] = useState('job')
  const create = useMutation({
    mutationFn: () => crewsApi.create({ name: name.trim(), type }).then(r => r.data),
    onSuccess: crew => {
      qc.invalidateQueries({ queryKey: ['crews', 'list'] })
      setName(''); setOpen(false)
      onCreated(crew.id)
    },
  })
  if (!open) return <button type="button" className={BTN} onClick={() => setOpen(true)}>+ طاقم جديد</button>
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={e => { e.preventDefault(); if (name.trim()) create.mutate() }}>
      <input autoFocus className={`${INPUT} w-48`} placeholder="اسم الطاقم" value={name} onChange={e => setName(e.target.value)} />
      <select className={INPUT} value={type} onChange={e => setType(e.target.value)}>
        {CREW_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>
      <button type="submit" className={BTN_PRIMARY} disabled={!name.trim() || create.isPending}>إنشاء</button>
      <button type="button" className={BTN} onClick={() => { setOpen(false); create.reset() }}>إلغاء</button>
      {create.isError && <span className="text-xs text-red-600 w-full">{errText(create.error)}</span>}
    </form>
  )
}

export default function CrewList({ query, selectedId, onSelect, archived, onArchived, canEdit }) {
  const rows = query.data || []
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey: 'crews-list' })
  return (
    <div className="card p-3 space-y-3" data-tour="crews-list">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {canEdit && !archived ? <NewCrewForm onCreated={onSelect} /> : <span />}
        <label className="flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" checked={archived} onChange={e => onArchived(e.target.checked)} />
          إظهار المؤرشفة
        </label>
      </div>
      {query.isLoading ? <p className="text-sm text-gray-500">جارٍ التحميل…</p> : rows.length === 0 ? (
        <p className="text-sm text-gray-500">{archived ? 'لا توجد أطقم مؤرشفة.' : 'لا توجد أطقم بعد.'}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50"><tr>
              <SortTh {...h('name', 'text')} className={TH}>الطاقم</SortTh>
              <SortTh {...h('type_label', 'text')} className={TH}>النوع</SortTh>
              <SortTh {...h('member_count', 'number')} className={TH}>الأعضاء اليوم</SortTh>
              <SortTh {...h('last_change', 'date')} className={TH}>آخر تغيير</SortTh>
            </tr></thead>
            <tbody className="divide-y divide-gray-100">
              {sorted.map(c => (
                <tr key={c.id} onClick={() => onSelect(c.id)}
                    className={`cursor-pointer hover:bg-gray-50 ${selectedId === c.id ? 'bg-brand-50' : ''}`}>
                  <td className={`${TD} font-semibold`}>{c.name}</td>
                  <td className={TD}>{c.type_label}</td>
                  <td className={`${TD} tabular-nums`}>{fmtInt(c.member_count)}</td>
                  <td className={`${TD} text-xs text-gray-500`}>{fmtDate(c.last_change, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
