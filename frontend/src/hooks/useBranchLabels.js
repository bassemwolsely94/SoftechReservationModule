/**
 * useBranchLabels — SOFTECH branch code → "code · name" everywhere a bare code is shown
 * (owner 2026-10-05: never a branch code without its name). Same rule as the server's
 * apps/finance/recon_labels.branch_label used in the Excel exports.
 *
 *   const bl = useBranchLabels()
 *   bl('170')        → '170 · م. الجيش-العباسية'
 *   bl.nameOf('170') → 'م. الجيش-العباسية'
 */
import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { branchesApi } from '../api/client'

export default function useBranchLabels() {
  const q = useQuery({
    queryKey: ['branch-labels'],
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 30 * 60 * 1000,
  })
  const names = useMemo(() => {
    const rows = Array.isArray(q.data) ? q.data : (q.data?.results || [])
    return Object.fromEntries(rows.map(b => [String(b.softech_branch_id ?? b.code ?? '').trim(), b.name_ar || b.name || '']))
  }, [q.data])
  const name = useCallback((code) => names[String(code ?? '').trim()] || '', [names])
  const label = useCallback((code) => {
    const c = String(code ?? '').trim()
    const n = names[c]
    return n ? `${c} · ${n}` : c
  }, [names])
  label.nameOf = name          // not .name — a function's 'name' is read-only
  return label
}
