/** Contract (تعاقد) fast-entry data — TanStack Query over /pos-orders/contract-assist/* (read-only PG).
 *  `useDebounced` gives the 250 ms typing debounce; the fetchers share the query cache. */
import { useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { posApi } from '../../api/client'

const A = posApi.contractAssist
const FRESH = 60 * 1000
const DEFAULT_CFG = { per_visit_columns: ['roshettano', 'examdate'], approval_column: 'roshettano' }

export function useDebounced(value, ms = 250) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export default function useContractAssist({ personcode, branchId }) {
  const qc = useQueryClient()
  const pc = personcode ? String(personcode) : ''
  const cfgQ = useQuery({
    queryKey: ['contract-assist', 'config', pc],
    queryFn: () => A.config(pc),
    enabled: !!pc, staleTime: 10 * 60 * 1000,
  })
  const config = cfgQ.data || DEFAULT_CFG
  const fetchQ = useCallback((key, fn) => qc.fetchQuery({ queryKey: ['contract-assist', pc, ...key], queryFn: fn, staleTime: FRESH }), [qc, pc])
  return {
    config,
    suggestPatients: useCallback((q) => (pc ? fetchQ(['patients', q], () => A.patients(pc, q)) : Promise.resolve([])), [pc, fetchQ]),
    history: useCallback((patient) => (pc ? fetchQ(['history', patient, branchId], () => A.history(pc, patient, branchId)) : Promise.resolve([])), [pc, branchId, fetchQ]),
    fieldValues: useCallback((column, q) => (pc ? fetchQ(['fv', column, q], () => A.fieldValues(pc, column, q)) : Promise.resolve([])), [pc, fetchQ]),
    checkApproval: useCallback((value) => (pc && value ? A.approvalCheck(pc, value) : Promise.resolve({ reused: false, matches: [] })), [pc]),
  }
}
