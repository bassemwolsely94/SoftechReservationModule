/**
 * BranchMultiSelect — the «كل الفروع» filter as a multi-select (tick several branches; none = all).
 *
 *   <BranchMultiSelect selected={ids} onChange={setIds} />                 // values = branch pk (id)
 *   <BranchMultiSelect valueKey="code" selected={codes} onChange={...} />  // values = SOFTECH branch code
 *   <BranchMultiSelect branches={myList} ... />                            // a screen's own (e.g. allowed) list
 *
 * Labels follow the branch rule: "code · name", never a bare code. The server side parses the
 * comma list with core/multi_filter.py. Send `selected.join(',')` only when something is ticked.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../api/client'
import MultiSelectFilter from './MultiSelectFilter'

const codeOf = (b) => String(b.softech_branch_id ?? b.code ?? '').trim()

export default function BranchMultiSelect({ selected = [], onChange, branches, valueKey = 'id',
  allLabel = 'كل الفروع', label, className = 'w-[180px]', menuClassName = 'min-w-[260px]', disabled, dataTour }) {
  const q = useQuery({
    queryKey: ['branch-labels'],          // shared with useBranchLabels — one request per session
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 30 * 60 * 1000,
    enabled: !branches,
  })
  const rows = useMemo(() => {
    const src = branches || (Array.isArray(q.data) ? q.data : (q.data?.results || []))
    return src.map(b => {
      const code = codeOf(b)
      const name = b.name_ar || b.name || ''
      return { code: valueKey === 'code' ? code : b.id, name: code && name ? `${code} · ${name}` : (name || code) }
    })
  }, [branches, q.data, valueKey])
  return (
    <MultiSelectFilter label={label} className={className} menuClassName={menuClassName} showCode={false}
      allLabel={allLabel} options={rows} selected={selected} onChange={onChange} disabled={disabled} dataTour={dataTour} />
  )
}
