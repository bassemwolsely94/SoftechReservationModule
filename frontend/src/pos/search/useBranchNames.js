/** Catalog branch PK → display name. The search API returns branch PKs; useBranchLabels is keyed by
 *  the SOFTECH code, so this reads the SAME cached query (['branch-labels']) and indexes it by PK. */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../../api/client'

export default function useBranchNames() {
  const q = useQuery({
    queryKey: ['branch-labels'],
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 30 * 60 * 1000,
  })
  return useMemo(() => {
    const rows = Array.isArray(q.data) ? q.data : (q.data?.results || [])
    const byId = Object.fromEntries(rows.map(b => [String(b.id), b.name_ar || b.name || '']))
    return (id) => byId[String(id)] || ''
  }, [q.data])
}
