/**
 * useClosedBranches — the «إظهار الفروع المغلقة» toggle for history/report filter bars.
 *
 *   const { branches, showClosed, toggle } = useClosedBranches(baseBranches)
 *   <BranchMultiSelect branches={branches} showClosed={showClosed} ... />  {toggle}
 *
 * Off: the screen's own (live) list. On: the full list via branchesApi.listAll(), which falls back to the
 * live list for non-admins (the server only serves scope=all to admins).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../api/client'

export default function useClosedBranches(base = []) {
  const [showClosed, setShowClosed] = useState(false)
  const all = useQuery({
    queryKey: ['branches', 'all-kinds'],
    queryFn: () => branchesApi.listAll().then(r => r.data?.results || r.data || []),
    staleTime: 10 * 60 * 1000,
    enabled: showClosed,
  })
  const branches = showClosed && Array.isArray(all.data) ? all.data : base
  const toggle = (
    <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
      <input type="checkbox" checked={showClosed} onChange={e => setShowClosed(e.target.checked)} />
      إظهار الفروع المغلقة
    </label>
  )
  return { branches, showClosed, toggle }
}
