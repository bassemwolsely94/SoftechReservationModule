/**
 * useSavedViews(screen, { getFilters, applyFilters }) — C23 saved filters / default views per user.
 *
 * The server keeps the views (apps/personal/saved_views_api.py): your own, plus views a colleague
 * shared with your role. It drops filter keys the screen does not allow; this hook drops them again
 * on apply (pickKnown), so an old or foreign view can never set state the screen does not have.
 * The DEFAULT view is applied once, when the screen first opens — never over filters already chosen.
 *
 *   const sv = useSavedViews('transits', { keys: ['priority', …], getFilters: () => filters,
 *                                          applyFilters: f => setFilters(f) })
 *   <SavedViewsMenu sv={sv} />
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { personalApi } from '../api/client'

export function pickKnown(filters, keys) {
  const out = {}
  if (!filters || typeof filters !== 'object') return out
  for (const k of keys) if (Object.prototype.hasOwnProperty.call(filters, k)) out[k] = filters[k]
  return out
}

export function defaultView(views) {
  return (views || []).find(v => v.mine && v.is_default) || null
}

export default function useSavedViews(screen, { keys, getFilters, applyFilters, enabled = true }) {
  const qc = useQueryClient()
  const queryKey = ['saved-views', screen]
  const { data } = useQuery({
    queryKey,
    queryFn: () => personalApi.savedViews(screen).then(r => r.data.results || []),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const views = data || []
  const [activeId, setActiveId] = useState(null)
  const [error, setError] = useState('')
  const appliedDefault = useRef(false)

  const apply = useCallback((v) => {
    if (!v) return
    applyFilters(pickKnown(v.filters, keys))
    setActiveId(v.id)
  }, [applyFilters, keys])

  // the default view, once per screen visit
  useEffect(() => {
    if (appliedDefault.current || !data) return
    appliedDefault.current = true
    const d = defaultView(data)
    if (d) apply(d)
  }, [data, apply])

  const refresh = () => qc.invalidateQueries({ queryKey })
  const fail = (e) => setError(e?.response?.data?.detail || 'تعذّر الحفظ')

  const save = async ({ name, isDefault = false, shared = false }) => {
    setError('')
    try {
      const { data: v } = await personalApi.createSavedView({
        screen, name, filters: pickKnown(getFilters(), keys), is_default: isDefault, shared })
      setActiveId(v.id)
      refresh()
      return v
    } catch (e) { fail(e); return null }
  }
  const update = async (id, patch) => {
    setError('')
    try { await personalApi.updateSavedView(id, patch); refresh(); return true } catch (e) { fail(e); return false }
  }
  const overwrite = (id) => update(id, { filters: pickKnown(getFilters(), keys) })
  const setDefault = (id, on = true) => update(id, { is_default: on })
  const remove = async (id) => {
    setError('')
    try {
      await personalApi.deleteSavedView(id)
      if (activeId === id) setActiveId(null)
      refresh()
      return true
    } catch (e) { fail(e); return false }
  }

  return { screen, views, activeId, error, apply, save, overwrite, setDefault, remove, clearActive: () => setActiveId(null) }
}
