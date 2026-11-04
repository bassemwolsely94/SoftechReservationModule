import { useQuery } from '@tanstack/react-query'
import { counsellingApi } from '../api/client'

/**
 * The three Project 4 switches plus what this user may do, all decided by the server:
 * `assistant` is true only when the switch is on AND the user has POS view; `canSend` needs POS
 * create; `homeBranchId` is the branch a card is sent from outside the POS (Customer-360).
 */
export default function useCounsellingStatus() {
  const { data } = useQuery({
    queryKey: ['counselling-status'],
    queryFn: () => counsellingApi.status().then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (!data) return { assistant: false, content: false, cards: false, canSend: false, homeBranchId: null }
  return {
    ...data,
    assistant: !!(data.assistant && data.can_assistant),
    canSend: !!data.can_send,
    homeBranchId: data.home_branch_id ?? null,
  }
}
