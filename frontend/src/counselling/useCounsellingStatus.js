import { useQuery } from '@tanstack/react-query'
import { counsellingApi } from '../api/client'

/** The three Project 4 switches ({assistant, content, cards}); all false until the server says so. */
export default function useCounsellingStatus() {
  const { data } = useQuery({
    queryKey: ['counselling-status'],
    queryFn: () => counsellingApi.status().then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  })
  return data || { assistant: false, content: false, cards: false }
}
