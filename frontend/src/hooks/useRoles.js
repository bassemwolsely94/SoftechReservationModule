import { useQuery } from '@tanstack/react-query'
import { authApi } from '../api/client'

// The permission roles come from the backend registry (apps/users/roles.py, GET /api/auth/roles/),
// so a new role shows with its label everywhere with no frontend change.
// roleLabel(key, lang) falls back to the raw key while loading or for an unknown role.
export default function useRoles() {
  const { data, isLoading } = useQuery({
    queryKey: ['roles'],
    queryFn: () => authApi.roles().then((r) => r.data?.roles || []),
    staleTime: Infinity,
  })
  const roles = data || []
  const byKey = Object.fromEntries(roles.map((r) => [r.value, r]))
  const roleLabel = (key, lang = 'ar') => {
    const r = byKey[key]
    return r ? (lang === 'en' ? r.label_en : r.label_ar) : key
  }
  // for bilingual screens that already hold a t(ar, en) helper
  const roleLabelT = (key, t) => {
    const r = byKey[key]
    return r ? t(r.label_ar, r.label_en) : key
  }
  return { roles, roleLabel, roleLabelT, isLoading }
}

// [{value, label}] for a <select> / filter list, in registry order.
export const roleOptions = (roles, lang = 'ar') =>
  (roles || []).map((r) => ({ value: r.value, label: lang === 'en' ? r.label_en : r.label_ar }))
