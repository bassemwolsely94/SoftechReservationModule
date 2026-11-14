/**
 * useClosedBranches — the «إظهار الفروع المغلقة» toggle for history/report filter bars.
 *
 *   const { branches, showClosed, toggle } = useClosedBranches(baseBranches)
 *   <BranchMultiSelect branches={branches} showClosed={showClosed} ... />  {toggle}
 *
 * Off: the screen's own (live) list. On: the full list via branchesApi.listAll(). Admins only: the server
 * serves scope=all to admins alone, so for anyone else the toggle is not shown (toggle = null) and the
 * screen keeps its live list.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'

export default function useClosedBranches(base = []) {
  const isAdmin = useAuthStore(st => st.user?.role) === 'admin'
  const [checked, setShowClosed] = useState(false)
  const showClosed = isAdmin && checked
  const all = useQuery({
    queryKey: ['branches', 'all-kinds'],
    queryFn: () => branchesApi.listAll().then(r => r.data?.results || r.data || []),
    staleTime: 10 * 60 * 1000,
    enabled: showClosed,
  })
  const branches = showClosed && Array.isArray(all.data) ? all.data : base
  const toggle = isAdmin ? (
    <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
      <input type="checkbox" checked={showClosed} onChange={e => setShowClosed(e.target.checked)} />
      إظهار الفروع المغلقة
    </label>
  ) : null
  return { branches, showClosed, toggle }
}
